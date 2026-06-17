"""SceneStore — versioned scene snapshot with staleness detection.

The SceneStore holds a cached copy of the Godot scene tree alongside a
monotonically increasing version counter. Every pipeline run begins by
fetching the current scene through the executor; if the scene content has
changed, the version is bumped. Plans are stamped with their source version,
and before execution the scene is re-checked — if it has moved, the plan is
re-run against the fresh snapshot.

This prevents the silent corruption that occurs when the agent (or a user
in the editor) modifies the scene between when the planner reads it and
when operations are applied.  Without this, DevForge's SystemGraph can go
stale and deterministic dedup will drop entities that "already exist"
against a world model that is wrong.

See architecture-teardown.md §2 for the original diagnosis.

Thread safety: FastMCP may serve concurrent tool calls from different
threads, so all mutating methods are guarded by a threading.Lock.
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any, Dict, Optional, Tuple

from devforge.infrastructure.logger import logger


class SceneStore:
    """Versioned scene snapshot cache with staleness detection."""

    def __init__(self):
        self._snapshot: Optional[Dict[str, Any]] = None
        self._version: int = 0
        self._last_hash: str = ""
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_or_fetch(
        self, executor
    ) -> Tuple[Dict[str, Any], int]:
        """Return (scene_tree, version), fetching from Godot if changed.

        Fetches the live scene from the executor on every call.  The
        version is bumped only when the scene content actually differs
        from the last fetch, so a sequence of reads against a stable
        scene all share the same version.

        Returns a sensible empty scene on first call (no cached snapshot
        and no live scene available).

        Thread-safe: guarded by the instance lock so concurrent
        ``apply_spec`` calls don't race on version assignment.
        """
        with self._lock:
            fresh = executor.get_scene()
            if fresh is None:
                if self._snapshot is not None:
                    return self._snapshot, self._version
                empty: Dict[str, Any] = {
                    "name": "Main",
                    "type": "Node3D",
                    "children": [],
                }
                return empty, 0

            new_hash = self._hash_scene(fresh)
            if new_hash != self._last_hash:
                self._version += 1
                self._last_hash = new_hash
                logger.info(
                    "scene_store",
                    f"Scene changed — version bumped to {self._version}",
                )

            self._snapshot = fresh
            return fresh, self._version

    def get_version(self) -> int:
        """Return the current scene version without fetching."""
        return self._version

    def note_writes(self) -> None:
        """Called after operations are applied.

        Bumps the version so subsequent plans know the world has moved.
        Also invalidates the cached hash so the next ``get_or_fetch``
        will re-fetch and compute a fresh baseline.

        Thread-safe.
        """
        with self._lock:
            self._version += 1
            self._last_hash = ""
            logger.debug("scene_store", f"Version after writes: {self._version}")

    def invalidate(self) -> None:
        """Mark the cache as stale.  Next ``get_or_fetch`` will re-fetch.

        Thread-safe.
        """
        with self._lock:
            self._last_hash = ""

    def is_stale(self, expected_version: int) -> bool:
        """Return True if *expected_version* is behind the current version.

        A planner can call this after building a plan to detect whether
        the scene moved during planning (e.g. the user saved in Godot).
        """
        return expected_version < self._version

    def has_snapshot(self) -> bool:
        """Return True if we have a cached scene snapshot."""
        return self._snapshot is not None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_scene(scene: Dict[str, Any]) -> str:
        """Stable content hash of a scene tree for change detection.

        Sorts keys so structurally identical trees produce the same hash
        regardless of key ordering.
        """
        canonical = json.dumps(scene, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()
