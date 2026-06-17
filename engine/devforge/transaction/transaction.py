"""ExecutionTransaction — transactional safety context manager.

Snapshots target paths on entry, rolls back on failure, commits on success.

Usage::

    with ExecutionTransaction(
        paths=["scripts/player.gd", "scenes/main.tscn"],
        git=GitOps(),
        description="add player movement system",
    ) as tx:
        # Modify files here
        tx.write("scripts/player.gd", new_content)
        # If an exception occurs, all changes are rolled back.
        # On success, changes are committed via git.

Done when: a deliberately failing multi-op change rolls back with
zero partial edits; successes are individual revertible commits.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Dict, List

from devforge.infrastructure.logger import logger
from devforge.transaction.git_ops import GitOps


def _safe_snapshot_name(path: Path) -> str:
    """Convert a file path to a unique, safe temp filename.

    ``scripts/player.gd`` → ``scripts_player.gd``
    """
    return str(path).replace("/", "_").replace("\\", "_")


class ExecutionTransaction:
    """Context manager that guarantees atomic file modifications.

    ``__enter__`` snapshots target paths to a temp directory.
    ``__exit__`` restores from snapshot on exception, or commits via
    GitOps on success.  If commit fails, files are left intact — only
    the git commit is skipped; valid work is never destroyed.
    """

    def __init__(
        self,
        paths: List[str | Path] | None = None,
        *,
        git: GitOps | None = None,
        description: str = "",
    ):
        """
        Args:
            paths: Files or directories to protect. If None, the
                   transaction tracks files written via ``tx.write()``.
            git: GitOps instance for committing on success.
            description: Human-readable change description (used as
                         the git commit message).
        """
        self._paths = [Path(p) for p in (paths or [])]
        self._git = git
        self._description = description
        self._snapshot_dir: str | None = None
        self._snapshots: Dict[str, str] = {}  # original_path → snapshot_path
        self._modified: List[Path] = []
        self._committed: bool = False
        self._commit_hash: str | None = None

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> "ExecutionTransaction":
        """Snapshot all protected paths to a temp directory."""
        self._snapshot_dir = tempfile.mkdtemp(prefix="devforge_tx_")

        # Snapshot explicitly listed paths
        for path in self._paths:
            if path.exists():
                self._snapshot_path(path)

        logger.info(
            "transaction",
            f"Transaction started: {len(self._snapshots)} paths snapshotted",
            description=self._description,
        )

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Roll back on exception, commit on success.

        Commit failures do NOT roll back — valid work on disk is preserved.
        """
        if exc_type is not None:
            logger.warn(
                "transaction",
                f"Rolling back due to: {exc_type.__name__}: {exc_val}",
            )
            self._rollback()
            self._cleanup()
            return False  # Re-raise the exception

        # Success — commit (best-effort)
        self._commit()
        self._cleanup()
        return False

    # ------------------------------------------------------------------
    # File operations (use inside ``with`` block)
    # ------------------------------------------------------------------

    def write(self, path: str | Path, content: str) -> None:
        """Write content to a file, snapshotting it first if not already.

        Call this instead of raw ``Path.write_text()`` to auto-protect
        files that weren't listed in the constructor's ``paths``.
        """
        p = Path(path)

        # Auto-snapshot if not already protected
        if str(p) not in self._snapshots and p.exists():
            self._snapshot_path(p)

        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        self._modified.append(p)

    def read(self, path: str | Path) -> str | None:
        """Read a file, returning None if it doesn't exist."""
        p = Path(path)
        if not p.exists():
            return None
        return p.read_text()

    @property
    def commit_hash(self) -> str | None:
        """The git commit hash after successful commit (None before)."""
        return self._commit_hash

    @property
    def modified_files(self) -> List[Path]:
        """List of files modified in this transaction."""
        return list(self._modified)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _snapshot_path(self, path: Path) -> None:
        """Copy a file or directory tree to the snapshot dir.

        Uses the full relative path (with / replaced by _) as the
        snapshot name to avoid collisions (e.g. scripts/player.gd and
        scenes/player.gd).
        """
        snapshot_name = _safe_snapshot_name(path)
        snapshot_path = Path(self._snapshot_dir) / snapshot_name

        if path.is_file():
            shutil.copy2(path, snapshot_path)
        elif path.is_dir():
            shutil.copytree(path, snapshot_path, symlinks=True)

        self._snapshots[str(path)] = str(snapshot_path)

    def _rollback(self) -> None:
        """Restore all snapshotted files from the temp directory."""
        for original_str, snapshot_str in self._snapshots.items():
            original = Path(original_str)
            snapshot = Path(snapshot_str)

            try:
                if snapshot.is_file():
                    shutil.copy2(snapshot, original)
                elif snapshot.is_dir():
                    if original.exists():
                        shutil.rmtree(original)
                    shutil.copytree(snapshot, original, symlinks=True)
            except Exception as exc:
                logger.error(
                    "transaction",
                    f"Rollback failed for {original}: {exc}",
                )

        # Remove any newly created files that weren't in the snapshot
        for modified in self._modified:
            if str(modified) not in self._snapshots and modified.exists():
                try:
                    if modified.is_dir():
                        shutil.rmtree(modified)
                    else:
                        modified.unlink()
                except Exception:
                    pass

        logger.info("transaction", "Rollback complete")

    def _commit(self) -> None:
        """Commit changes via GitOps (if available).

        Commit failures are logged but do NOT roll back — the files on
        disk are valid and should be preserved.
        """
        if self._git is None:
            logger.info("transaction", "No GitOps configured — changes left uncommitted")
            return

        message = self._description or "devforge: automated change"
        modified_strs = [str(p) for p in self._modified]

        try:
            commit_hash = self._git.commit(message, files=modified_strs if modified_strs else None)

            if commit_hash:
                self._committed = True
                self._commit_hash = commit_hash
                logger.info(
                    "transaction",
                    f"Committed: {commit_hash[:8]} — {message}",
                    files=len(modified_strs),
                )
            else:
                logger.info("transaction", "No changes to commit")
        except Exception as exc:
            # Commit failure: log and leave files intact
            logger.error(
                "transaction",
                f"Commit failed (files left intact on disk): {exc}",
            )

    def _cleanup(self) -> None:
        """Remove the temp snapshot directory."""
        if self._snapshot_dir:
            try:
                shutil.rmtree(self._snapshot_dir, ignore_errors=True)
            except Exception:
                pass
