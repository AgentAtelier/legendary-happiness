"""Structured logging for DevForge.

Every component uses this instead of print() so we can trace issues
across the pipeline.

Log level is controlled by ``DEVFORGE_LOG_LEVEL`` (default: INFO).
When ``DEVFORGE_LOG_FILE`` is set, logs are also written to a rotating
file (max 10 files × 5 MB each) for post-mortem debugging.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import time
import json
import sys
from dataclasses import dataclass, field
from typing import Any

# ── Rotating file handler (M5) ─────────────────────────────────

_file_handler: logging.handlers.RotatingFileHandler | None = None


def _init_file_logging() -> None:
    """Configure a rotating file logger when DEVFORGE_LOG_FILE is set.

    Writes structured JSON lines (one per log entry) to the named file.
    Rotation: 10 backups × 5 MB each.
    """
    global _file_handler
    log_path = os.environ.get("DEVFORGE_LOG_FILE", "")
    if not log_path or _file_handler is not None:
        return
    try:
        _file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=10,
        )
        _file_handler.setLevel(logging.DEBUG)
        _file_handler.setFormatter(logging.Formatter("%(message)s"))
        _file_logger = logging.getLogger("devforge.file")
        _file_logger.addHandler(_file_handler)
        _file_logger.setLevel(logging.DEBUG)
        _file_logger.propagate = False
    except OSError:
        pass  # can't write log file — not fatal


# ── Structured entries ─────────────────────────────────────────


@dataclass
class LogEntry:
    timestamp: float
    level: str
    component: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.timestamp,
            "level": self.level,
            "component": self.component,
            "msg": self.message,
            **self.data,
        }

    def __str__(self) -> str:
        ts = time.strftime("%H:%M:%S", time.localtime(self.timestamp))
        # default=str: a log line must NEVER crash the request it is logging.
        # Structured kwargs can carry non-JSON-serializable values (e.g. a
        # header value that's a mock in tests, or any object) — stringify
        # rather than raise.
        data_str = f" | {json.dumps(self.data, default=str)}" if self.data else ""
        return f"[{ts}] [{self.level}] [{self.component}] {self.message}{data_str}"


class DevForgeLogger:
    """Central logger that accumulates structured entries.

    Log level is controlled by ``DEVFORGE_LOG_LEVEL`` (DEBUG, INFO,
    WARN, ERROR — default INFO).  Levels below the threshold are
    dropped entirely.
    """

    _LEVEL_ORDER: dict[str, int] = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}

    def __init__(self):
        self._entries: list[LogEntry] = []
        self._max_entries = 5000
        _init_file_logging()

    @property
    def _min_level(self) -> int:
        """Minimum log level from env (default INFO)."""
        level_name = os.environ.get("DEVFORGE_LOG_LEVEL", "INFO").upper()
        return self._LEVEL_ORDER.get(level_name, 20)

    def _log(self, level: str, component: str, message: str, **data: Any) -> LogEntry:
        entry = LogEntry(
            timestamp=time.time(),
            level=level,
            component=component,
            message=message,
            data=data,
        )

        # Drop entries below the configured threshold
        if self._LEVEL_ORDER.get(level, 0) < self._min_level:
            return entry

        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries :]

        # Always print to stderr for immediate visibility
        print(entry, file=sys.stderr)

        # Also write to rotating file log (structured JSON)
        if _file_handler is not None:
            try:
                _file_logger = logging.getLogger("devforge.file")
                _file_logger.info(json.dumps(entry.to_dict(), default=str))
            except Exception:
                pass  # file logging is best-effort

        return entry

    def debug(self, component: str, message: str, **data: Any) -> LogEntry:
        return self._log("DEBUG", component, message, **data)

    def info(self, component: str, message: str, **data: Any) -> LogEntry:
        return self._log("INFO", component, message, **data)

    def warn(self, component: str, message: str, **data: Any) -> LogEntry:
        return self._log("WARN", component, message, **data)

    # stdlib-style alias — calling logger.warning() instead of warn() has
    # crashed a security path before (Round-2 audit F1); accept both.
    warning = warn

    def error(self, component: str, message: str, **data: Any) -> LogEntry:
        return self._log("ERROR", component, message, **data)

    def get_entries(self, component: str | None = None, level: str | None = None) -> list[LogEntry]:
        entries = self._entries
        if component:
            entries = [e for e in entries if e.component == component]
        if level:
            entries = [e for e in entries if e.level == level]
        return entries

    def get_recent(self, n: int = 50) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._entries[-n:]]

    def clear(self) -> None:
        self._entries.clear()


# Singleton
logger = DevForgeLogger()
