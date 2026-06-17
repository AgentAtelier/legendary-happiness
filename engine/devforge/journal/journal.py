"""Progress Journal — append-only, time-series event log.

Every DevForge tool that reads or mutates the scene can emit a
timestamped entry.  The journal is a JSONL file (one JSON object per
line) in ``.devforge/journal/journal.jsonl``.  Retention: last N
entries (default 500), trimmed on append.

Architecture rule #6: \"Everything emits to the Journal.\"
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

from devforge.infrastructure.logger import logger

DEFAULT_JOURNAL_PATH = ".devforge/journal/journal.jsonl"
DEFAULT_MAX_ENTRIES = 500


@dataclass
class JournalEntry:
    """A single timestamped event in the progress journal."""

    timestamp: float  # epoch seconds
    tool: str  # "audit_scene", "batch_apply", "template_apply", ...
    event: str  # one-line human-readable summary
    data: dict[str, Any]  # structured metrics (counts, version, errors, ...)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "tool": self.tool,
            "event": self.event,
            "data": self.data,
        }


class Journal:
    """Append-only, thread-safe event log for DevForge operations.

    Usage::

        journal = Journal()
        journal.append("audit_scene", "Audit: 2 critical, 3 warning",
                        {"scene_version": 5, "critical": 2, "warning": 3})
        entries = journal.get_entries(n=20)
        summary = journal.summary()
    """

    def __init__(
        self,
        path: str = DEFAULT_JOURNAL_PATH,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ):
        self._path = path
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._entries: list[JournalEntry] = []
        self._load()

    # ── Public API ──────────────────────────────────────────────

    def append(self, tool: str, event: str, data: dict[str, Any] | None = None) -> JournalEntry:
        """Append a journal entry and persist to disk.

        Thread-safe.  Trims oldest entries and compacts the file
        when at capacity.
        """
        entry = JournalEntry(
            timestamp=time.time(),
            tool=tool,
            event=event,
            data=data or {},
        )
        with self._lock:
            self._entries.append(entry)
            trimmed = len(self._entries) > self._max_entries
            if trimmed:
                self._entries = self._entries[-self._max_entries :]
                self._compact()  # rewrite file to remove trimmed lines
            else:
                self._persist_entry(entry)
        return entry

    def get_entries(
        self,
        n: int = 50,
        tool: str | None = None,
    ) -> list[dict]:
        """Return the most recent *n* entries, optionally filtered by *tool*.

        Returns newest-first.
        """
        with self._lock:
            entries = list(self._entries)
        if tool:
            entries = [e for e in entries if e.tool == tool]
        return [e.to_dict() for e in entries[-n:][::-1]]

    def summary(self) -> dict:
        """Return aggregated stats across all journal entries.

        Returns:
            {
              "total_entries": 142,
              "first_ts": 1718100000.0,
              "last_ts": 1718180000.0,
              "by_tool": {"audit_scene": 80, "batch_apply": 12, ...},
              "recent_tools": ["audit_scene", "triage_errors", ...],
            }
        """
        with self._lock:
            entries = list(self._entries)

        if not entries:
            return {
                "total_entries": 0,
                "first_ts": None,
                "last_ts": None,
                "by_tool": {},
                "recent_tools": [],
            }

        by_tool: dict[str, int] = {}
        recent: set[str] = set()
        for e in entries[-50:]:
            recent.add(e.tool)
        for e in entries:
            by_tool[e.tool] = by_tool.get(e.tool, 0) + 1

        return {
            "total_entries": len(entries),
            "first_ts": entries[0].timestamp,
            "last_ts": entries[-1].timestamp,
            "by_tool": by_tool,
            "recent_tools": sorted(recent),
        }

    def clear(self) -> None:
        """Truncate all entries (for testing)."""
        with self._lock:
            self._entries.clear()
            try:
                os.remove(self._path)
            except OSError:
                pass

    # ── Internal ────────────────────────────────────────────────

    def _load(self) -> None:
        """Load existing entries from the JSONL file.

        Streams the file and only keeps the last ``_max_entries``
        lines — avoids creating objects for discarded history.
        """
        try:
            if os.path.exists(self._path):
                with open(self._path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                            self._entries.append(
                                JournalEntry(
                                    timestamp=obj["timestamp"],
                                    tool=obj["tool"],
                                    event=obj["event"],
                                    data=obj.get("data", {}),
                                )
                            )
                        except (json.JSONDecodeError, KeyError):
                            pass
                        # Rolling window — keep only the last N
                        if len(self._entries) > self._max_entries:
                            self._entries = self._entries[-self._max_entries :]
                # If the file had more lines than max_entries, rewrite
                if len(self._entries) >= self._max_entries:
                    self._compact()
        except OSError:
            pass

    def _persist_entry(self, entry: JournalEntry) -> None:
        """Append one JSON line to the journal file."""
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "a") as f:
                f.write(json.dumps(entry.to_dict(), default=str) + "\n")
        except OSError as exc:
            logger.warn(
                "journal",
                f"Failed to persist journal entry: {exc}",
            )

    def _compact(self) -> None:
        """Rewrite the journal file with only the current in-memory entries.

        Removes trimmed/corrupted lines from disk.  Must be called
        while holding ``_lock``.
        """
        try:
            tmp_path = self._path + ".tmp"
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(tmp_path, "w") as f:
                for entry in self._entries:
                    f.write(json.dumps(entry.to_dict(), default=str) + "\n")
            os.replace(tmp_path, self._path)
        except OSError as exc:
            logger.warn(
                "journal",
                f"Failed to compact journal: {exc}",
            )
