"""Artifact store — caches full pipeline results and serves summaries.

apply_spec stores its full payload here keyed by UUID and returns a
compact summary to the caller (Odysseus).  The LLM can fetch the full
details on demand via the ``read_artifact`` MCP tool, avoiding context
bloat from large tool results.

Design:
  - Thread-safe (uses threading.Lock, same pattern as SceneStore).
  - In-memory dict — no persistence needed; results are per-session.
  - ``store()`` returns an artifact_id (UUID4).
  - ``get()`` retrieves the full payload.
  - ``build_summary()`` extracts the compact summary from a full result.
"""

from __future__ import annotations

import uuid
import threading
from typing import Any, Dict, List, Optional


class ArtifactStore:
    """Thread-safe in-memory cache of full pipeline results.

    Evicts oldest entries when *max_entries* is reached to bound
    memory in long editor sessions (each artifact carries full file
    contents, operation lists, and scene snapshots).
    """

    def __init__(self, max_entries: int = 50):
        self._store: Dict[str, Dict[str, Any]] = {}
        self._order: list[str] = []  # access order for LRU eviction (oldest first)
        self.max_entries = max_entries
        self._lock = threading.Lock()

    def store(self, payload: Dict[str, Any]) -> str:
        """Store a full pipeline result and return its artifact_id.

        Evicts the least-recently-used entry when at capacity.
        """
        artifact_id = uuid.uuid4().hex[:12]
        with self._lock:
            if len(self._store) >= self.max_entries:
                oldest = self._order.pop(0)
                del self._store[oldest]
            self._store[artifact_id] = payload
            self._order.append(artifact_id)
        return artifact_id

    def get(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a full pipeline result by artifact_id.

        Refreshes the entry's LRU position. Returns None if the
        artifact_id is unknown or the artifact has been evicted.
        """
        with self._lock:
            payload = self._store.get(artifact_id)
            if payload is not None:
                self._order.remove(artifact_id)
                self._order.append(artifact_id)
            return payload

    def build_summary(self, artifact_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Extract a compact summary from a full pipeline result.

        The summary is what ``apply_spec`` returns to the LLM — small
        enough to not bloat context, but informative enough for the
        agent to know whether the change succeeded and which files
        were touched.  Full detail is one ``read_artifact`` call away.
        """
        ops = payload.get("operations") or []
        files = payload.get("files") or []
        errors = payload.get("errors") or []
        execution = payload.get("execution") or {}

        # ExecutionResult.to_dict() already provides the applied count
        applied = execution.get("success_count", 0)

        # File paths only — no contents
        file_paths: List[str] = []
        for f in files:
            if isinstance(f, dict):
                fp = f.get("path", "")
                if fp:
                    file_paths.append(fp)

        # Error summaries — just the message, not full stack traces
        error_msgs: List[str] = []
        for e in errors:
            if isinstance(e, dict):
                msg = e.get("message") or str(e)
            else:
                msg = str(e)
            # Cap individual error messages
            if len(msg) > 200:
                msg = msg[:200] + "…"
            error_msgs.append(msg)

        # Executor-level errors too
        exec_errors = execution.get("errors") or []
        for e in exec_errors:
            if isinstance(e, dict):
                msg = e.get("message") or str(e)
            else:
                msg = str(e)
            if len(msg) > 200:
                msg = msg[:200] + "…"
            error_msgs.append(msg)

        return {
            "artifact_id": artifact_id,
            "applied": applied,
            "operations_total": len(ops),
            "files": file_paths,
            "errors": error_msgs,
            "error_count": len(error_msgs),
            "scene_version": payload.get("scene_version", 0),
            "has_full_detail": True,
            "hint": (
                "Call read_artifact with this artifact_id to get full "
                "operation details, file contents, and execution results."
            ),
        }
