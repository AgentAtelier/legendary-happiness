"""GitOps — git operations for DevForge transactional changes.

Uses GitPython (``git.Repo``) which is already a project dependency.
Commits each successful change with the spec/prompt as the commit message
so every change is individually revertible.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from devforge.infrastructure.logger import logger


class GitOps:
    """Git operations scoped to a specific repository.

    Usage::

        git = GitOps(repo_path=".")
        commit_hash = git.commit("add player entity")
        git.revert(commit_hash)

    All file operations are relative to the repo root.
    """

    def __init__(self, repo_path: str | Path = "."):
        self._repo_path = Path(repo_path).resolve()
        self._repo = None

    # ------------------------------------------------------------------
    # Lazy repo access
    # ------------------------------------------------------------------

    @property
    def _git_repo(self):
        """Lazy-load the git.Repo instance."""
        if self._repo is None:
            import git
            self._repo = git.Repo(self._repo_path)
        return self._repo

    @property
    def is_available(self) -> bool:
        """Check if the path is inside a git repository."""
        try:
            _ = self._git_repo
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def commit(self, message: str, files: Optional[List[str | Path]] = None) -> str | None:
        """Stage and commit specific files.

        Args:
            message: Commit message (typically the spec/prompt).
            files: Files to stage and commit. Must be provided —
                   avoids accidentally committing unrelated dirty files.

        Returns:
            Commit hexsha on success, None if repo unavailable or nothing to commit.
        """
        if not self.is_available:
            logger.warn("git_ops", "No git repo available — skipping commit")
            return None

        try:
            repo = self._git_repo

            if not files:
                logger.info("git_ops", "No files specified — nothing to commit")
                return None

            # Stage only the specified files
            for f in files:
                repo.index.add([str(f)])

            # Check if there's anything to commit
            if not repo.index.diff("HEAD"):
                logger.info("git_ops", "Nothing to commit — index unchanged")
                return None

            commit = repo.index.commit(message)
            logger.info("git_ops", f"Committed: {commit.hexsha[:8]} — {message}")
            return commit.hexsha

        except Exception as exc:
            logger.error("git_ops", f"Commit failed: {exc}")
            return None

    def revert(self, commit_hash: str) -> bool:
        """Revert a specific commit.

        Args:
            commit_hash: The commit to revert.

        Returns:
            True on success, False on failure.
        """
        if not self.is_available:
            logger.warn("git_ops", "No git repo available — skipping revert")
            return False

        try:
            repo = self._git_repo
            repo.git.revert(commit_hash, no_edit=True)
            logger.info("git_ops", f"Reverted commit: {commit_hash[:8]}")
            return True

        except Exception as exc:
            logger.error("git_ops", f"Revert failed: {exc}")
            return False

    def status(self) -> dict:
        """Get current repo status.

        Returns:
            Dict with 'modified', 'untracked', 'staged' file lists.
        """
        if not self.is_available:
            return {"modified": [], "untracked": [], "staged": []}

        try:
            repo = self._git_repo
            return {
                "modified": [item.a_path for item in repo.index.diff(None)],
                "staged": [item.a_path for item in repo.index.diff("HEAD")],
                "untracked": repo.untracked_files,
            }
        except Exception:
            return {"modified": [], "untracked": [], "staged": []}
