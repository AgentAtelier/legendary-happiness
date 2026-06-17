"""DevForge Monitor — structured event logging, request tracing, and analytics.

This module captures every step of the DevForge pipeline:
  prompt received → context built → LLM called → response parsed →
  operations validated → operations ordered → plugin executes → results reported

Every event is stored in SQLite with a trace_id that links all events from a
single request together, so you can follow one prompt from input to output.

Usage:
    from devforge.platform.monitor import monitor

    # Start a traced request
    trace = monitor.begin_trace("create a player controller")

    # Log events at each pipeline stage
    monitor.log_context_built(trace, scene_nodes=5, scripts=3, api_sections=2)
    monitor.log_llm_request(trace, prompt_text, prompt_tokens=1200)
    monitor.log_llm_response(trace, raw_response, elapsed_ms=3400)
    monitor.log_parse_result(trace, files=1, operations=4, parse_errors=[])
    monitor.log_validation(trace, total=4, passed=3, rejected=1, reasons=["bad parent path"])
    monitor.log_execution(trace, results=[...])

    # End the trace
    monitor.end_trace(trace, status="complete")

    # Query analytics
    monitor.get_recent_traces(limit=20)
    monitor.get_failure_analysis()
    monitor.get_llm_performance()
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

# ── Event Types ─────────────────────────────────────────────────────


class EventType(str, Enum):
    # Request lifecycle
    TRACE_START = "trace_start"
    TRACE_END = "trace_end"

    # Context assembly
    CONTEXT_BUILT = "context_built"

    # LLM interaction
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    LLM_ERROR = "llm_error"

    # Response processing
    PARSE_RESULT = "parse_result"
    PARSE_ERROR = "parse_error"

    # Validation
    VALIDATION = "validation"
    VALIDATION_REJECTED = "validation_rejected"

    # Operation ordering
    ORDERING = "ordering"

    # Plugin execution
    EXECUTION_RESULT = "execution_result"
    EXECUTION_SUCCESS = "execution_success"
    EXECUTION_FAILURE = "execution_failure"

    # Repair
    REPAIR_REQUESTED = "repair_requested"
    REPAIR_RESULT = "repair_result"

    # Game model
    MODEL_LEARNED = "model_learned"

    # Warnings and errors
    WARNING = "warning"
    ERROR = "error"


class Severity(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ── Trace Object ────────────────────────────────────────────────────


class Trace:
    """Represents a single request flowing through the pipeline."""

    __slots__ = ("trace_id", "prompt", "start_time", "intent", "metadata")

    def __init__(self, prompt: str):
        self.trace_id = str(uuid.uuid4())[:12]
        self.prompt = prompt
        self.start_time = time.time()
        self.intent: str | None = None
        self.metadata: dict[str, Any] = {}


# ── SQLite Schema ───────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id    TEXT NOT NULL,
    timestamp   REAL NOT NULL,
    event_type  TEXT NOT NULL,
    severity    TEXT NOT NULL DEFAULT 'info',
    message     TEXT NOT NULL DEFAULT '',
    data        TEXT NOT NULL DEFAULT '{}',
    prompt      TEXT DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_trace ON events(trace_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_time ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_severity ON events(severity);

CREATE TABLE IF NOT EXISTS traces (
    trace_id    TEXT PRIMARY KEY,
    prompt      TEXT NOT NULL,
    intent      TEXT DEFAULT '',
    start_time  REAL NOT NULL,
    end_time    REAL DEFAULT 0,
    status      TEXT DEFAULT 'in_progress',
    files_count INTEGER DEFAULT 0,
    ops_count   INTEGER DEFAULT 0,
    ops_passed  INTEGER DEFAULT 0,
    ops_failed  INTEGER DEFAULT 0,
    llm_time_ms INTEGER DEFAULT 0,
    total_time_ms INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_traces_time ON traces(start_time);
CREATE INDEX IF NOT EXISTS idx_traces_status ON traces(status);
"""


# ── Monitor Class ───────────────────────────────────────────────────


class Monitor:
    """Central monitoring hub.  One instance per server process."""

    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            db_path = Path(".devforge") / "monitor.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self._db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── Trace lifecycle ─────────────────────────────────────────────

    def begin_trace(self, prompt: str) -> Trace:
        """Start tracking a new request through the pipeline."""
        trace = Trace(prompt)
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO traces (trace_id, prompt, start_time, created_at) VALUES (?, ?, ?, ?)",
                (trace.trace_id, prompt, trace.start_time, now),
            )
        self._emit(trace, EventType.TRACE_START, Severity.INFO, f"Request: {prompt[:100]}")
        return trace

    def end_trace(
        self,
        trace: Trace,
        *,
        status: str = "complete",
        files_count: int = 0,
        ops_count: int = 0,
        ops_passed: int = 0,
        ops_failed: int = 0,
        llm_time_ms: int = 0,
    ) -> None:
        """Mark a trace as finished."""
        end_time = time.time()
        total_ms = int((end_time - trace.start_time) * 1000)

        with self._conn() as conn:
            conn.execute(
                """UPDATE traces SET end_time=?, status=?, intent=?,
                   files_count=?, ops_count=?, ops_passed=?, ops_failed=?,
                   llm_time_ms=?, total_time_ms=?
                   WHERE trace_id=?""",
                (
                    end_time,
                    status,
                    trace.intent or "",
                    files_count,
                    ops_count,
                    ops_passed,
                    ops_failed,
                    llm_time_ms,
                    total_ms,
                    trace.trace_id,
                ),
            )
        self._emit(trace, EventType.TRACE_END, Severity.INFO, f"Completed in {total_ms}ms: {status}")

    # ── Pipeline event loggers ──────────────────────────────────────

    def log_context_built(
        self,
        trace: Trace,
        *,
        scene_nodes: int = 0,
        scripts_found: int = 0,
        api_sections: int = 0,
        game_model_entities: int = 0,
        prompt_length: int = 0,
    ) -> None:
        self._emit(
            trace,
            EventType.CONTEXT_BUILT,
            Severity.INFO,
            f"Context: {scene_nodes} nodes, {scripts_found} scripts, "
            f"{api_sections} API refs, {prompt_length} chars total",
            data={
                "scene_nodes": scene_nodes,
                "scripts_found": scripts_found,
                "api_sections": api_sections,
                "game_model_entities": game_model_entities,
                "prompt_length": prompt_length,
            },
        )

    def log_llm_request(
        self,
        trace: Trace,
        *,
        prompt_text: str = "",
        prompt_tokens_est: int = 0,
        model: str = "",
        multi_step: bool = False,
        step_name: str = "",
    ) -> None:
        self._emit(
            trace,
            EventType.LLM_REQUEST,
            Severity.INFO,
            f"LLM request: ~{prompt_tokens_est} tokens, model={model}" + (f", step={step_name}" if step_name else ""),
            data={
                "prompt_text": prompt_text[:5000],  # Truncate for storage
                "prompt_tokens_est": prompt_tokens_est,
                "model": model,
                "multi_step": multi_step,
                "step_name": step_name,
            },
        )

    def log_llm_response(
        self,
        trace: Trace,
        *,
        raw_response: str = "",
        elapsed_ms: int = 0,
        response_tokens_est: int = 0,
        step_name: str = "",
    ) -> None:
        self._emit(
            trace,
            EventType.LLM_RESPONSE,
            Severity.INFO,
            f"LLM response: {elapsed_ms}ms, ~{response_tokens_est} tokens"
            + (f", step={step_name}" if step_name else ""),
            data={
                "raw_response": raw_response[:5000],
                "elapsed_ms": elapsed_ms,
                "response_tokens_est": response_tokens_est,
                "step_name": step_name,
            },
        )

    def log_llm_error(self, trace: Trace, *, error: str = "", attempt: int = 1) -> None:
        self._emit(
            trace,
            EventType.LLM_ERROR,
            Severity.ERROR,
            f"LLM error (attempt {attempt}): {error}",
            data={"error": error, "attempt": attempt},
        )

    def log_parse_result(
        self,
        trace: Trace,
        *,
        files_count: int = 0,
        ops_count: int = 0,
        parse_errors: list[str] | None = None,
        step_name: str = "",
    ) -> None:
        severity = Severity.WARNING if parse_errors else Severity.INFO
        self._emit(
            trace,
            EventType.PARSE_RESULT,
            severity,
            f"Parsed: {files_count} files, {ops_count} operations"
            + (f" ({len(parse_errors)} errors)" if parse_errors else ""),
            data={
                "files_count": files_count,
                "ops_count": ops_count,
                "parse_errors": parse_errors or [],
                "step_name": step_name,
            },
        )

    def log_validation(
        self,
        trace: Trace,
        *,
        total: int = 0,
        passed: int = 0,
        rejected: int = 0,
        rejection_reasons: list[str] | None = None,
    ) -> None:
        severity = Severity.WARNING if rejected > 0 else Severity.INFO
        self._emit(
            trace,
            EventType.VALIDATION,
            severity,
            f"Validation: {passed}/{total} passed, {rejected} rejected",
            data={
                "total": total,
                "passed": passed,
                "rejected": rejected,
                "rejection_reasons": rejection_reasons or [],
            },
        )

    def log_validation_rejected(self, trace: Trace, *, operation: dict | None = None, reason: str = "") -> None:
        self._emit(
            trace,
            EventType.VALIDATION_REJECTED,
            Severity.WARNING,
            f"Rejected: {operation.get('type', '?')} — {reason}",
            data={"operation": operation or {}, "reason": reason},
        )

    def log_ordering(self, trace: Trace, *, order: list[str] | None = None) -> None:
        self._emit(
            trace,
            EventType.ORDERING,
            Severity.DEBUG,
            f"Operation order: {' → '.join(order or [])}",
            data={"order": order or []},
        )

    def log_execution_result(
        self, trace: Trace, *, op_type: str = "", op_name: str = "", status: str = "ok", error: str = ""
    ) -> None:
        event = EventType.EXECUTION_SUCCESS if status == "ok" else EventType.EXECUTION_FAILURE
        severity = Severity.INFO if status == "ok" else Severity.ERROR
        self._emit(
            trace,
            event,
            severity,
            f"{'✓' if status == 'ok' else '✗'} {op_type} {op_name}" + (f" — {error}" if error else ""),
            data={"op_type": op_type, "op_name": op_name, "status": status, "error": error},
        )

    def log_repair(
        self, trace: Trace, *, attempt: int = 1, failed_op: dict | None = None, error: str = "", result_ops: int = 0
    ) -> None:
        self._emit(
            trace,
            EventType.REPAIR_REQUESTED,
            Severity.WARNING,
            f"Repair attempt {attempt}: {error}",
            data={"attempt": attempt, "failed_op": failed_op or {}, "error": error, "result_ops": result_ops},
        )

    def log_model_learned(
        self, trace: Trace, *, new_entities: int = 0, new_systems: int = 0, new_interactions: int = 0
    ) -> None:
        self._emit(
            trace,
            EventType.MODEL_LEARNED,
            Severity.INFO,
            f"Learned: {new_entities} entities, {new_systems} systems, {new_interactions} interactions",
            data={"new_entities": new_entities, "new_systems": new_systems, "new_interactions": new_interactions},
        )

    def log_warning(self, trace: Trace | None, message: str, data: dict | None = None) -> None:
        self._emit(trace, EventType.WARNING, Severity.WARNING, message, data=data or {})

    def log_error(self, trace: Trace | None, message: str, data: dict | None = None) -> None:
        self._emit(trace, EventType.ERROR, Severity.ERROR, message, data=data or {})

    # ── Internal event writer ───────────────────────────────────────

    def _emit(
        self, trace: Trace | None, event_type: EventType, severity: Severity, message: str, data: dict | None = None
    ) -> None:
        trace_id = trace.trace_id if trace else "system"
        prompt = trace.prompt if trace else ""
        now = time.time()
        created = datetime.now(timezone.utc).isoformat()

        # Console output (always)
        prefix = f"[{severity.value.upper():8s}] [{trace_id}]"
        print(f"{prefix} {message}")

        # SQLite
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO events (trace_id, timestamp, event_type, severity, message, data, prompt, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (trace_id, now, event_type.value, severity.value, message, json.dumps(data or {}), prompt, created),
            )

    # ── Analytics queries ───────────────────────────────────────────

    def get_recent_traces(self, limit: int = 20) -> list[dict]:
        """Get the most recent request traces."""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM traces ORDER BY start_time DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_trace_events(self, trace_id: str) -> list[dict]:
        """Get all events for a specific trace."""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM events WHERE trace_id=? ORDER BY timestamp", (trace_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_failure_analysis(self) -> dict[str, Any]:
        """Analyze common failure patterns."""
        with self._conn() as conn:
            # Operations that fail most
            failure_rows = conn.execute(
                """SELECT json_extract(data, '$.op_type') as op_type,
                          COUNT(*) as count
                   FROM events WHERE event_type='execution_failure'
                   GROUP BY op_type ORDER BY count DESC LIMIT 10"""
            ).fetchall()

            # Validation rejection reasons
            rejection_rows = conn.execute(
                """SELECT json_extract(data, '$.reason') as reason,
                          COUNT(*) as count
                   FROM events WHERE event_type='validation_rejected'
                   GROUP BY reason ORDER BY count DESC LIMIT 10"""
            ).fetchall()

            # Parse error rate
            parse_rows = conn.execute(
                """SELECT
                     SUM(CASE WHEN json_array_length(json_extract(data, '$.parse_errors')) > 0 THEN 1 ELSE 0 END) as errors,
                     COUNT(*) as total
                   FROM events WHERE event_type='parse_result'"""
            ).fetchone()

            return {
                "top_failing_operations": [dict(r) for r in failure_rows],
                "top_rejection_reasons": [dict(r) for r in rejection_rows],
                "parse_error_rate": {
                    "errors": parse_rows["errors"] or 0 if parse_rows else 0,
                    "total": parse_rows["total"] or 0 if parse_rows else 0,
                },
            }

    def get_llm_performance(self) -> dict[str, Any]:
        """LLM response time and reliability stats."""
        with self._conn() as conn:
            resp_rows = conn.execute(
                """SELECT
                     AVG(json_extract(data, '$.elapsed_ms')) as avg_ms,
                     MIN(json_extract(data, '$.elapsed_ms')) as min_ms,
                     MAX(json_extract(data, '$.elapsed_ms')) as max_ms,
                     COUNT(*) as total
                   FROM events WHERE event_type='llm_response'"""
            ).fetchone()

            error_count = conn.execute("SELECT COUNT(*) as c FROM events WHERE event_type='llm_error'").fetchone()

            return {
                "avg_response_ms": int(resp_rows["avg_ms"] or 0) if resp_rows else 0,
                "min_response_ms": int(resp_rows["min_ms"] or 0) if resp_rows else 0,
                "max_response_ms": int(resp_rows["max_ms"] or 0) if resp_rows else 0,
                "total_requests": resp_rows["total"] or 0 if resp_rows else 0,
                "total_errors": error_count["c"] or 0 if error_count else 0,
            }

    def get_success_rate(self) -> dict[str, Any]:
        """Overall pipeline success rate."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT
                     SUM(CASE WHEN status='complete' AND ops_failed=0 THEN 1 ELSE 0 END) as fully_successful,
                     SUM(CASE WHEN status='complete' THEN 1 ELSE 0 END) as completed,
                     SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as errored,
                     COUNT(*) as total
                   FROM traces"""
            ).fetchone()
            return dict(row) if row else {}

    def get_operation_stats(self) -> list[dict]:
        """Per-operation-type success/failure counts."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT json_extract(data, '$.op_type') as op_type,
                          json_extract(data, '$.status') as status,
                          COUNT(*) as count
                   FROM events
                   WHERE event_type IN ('execution_success', 'execution_failure')
                   GROUP BY op_type, status
                   ORDER BY op_type"""
            ).fetchall()
            return [dict(r) for r in rows]

    def get_events_by_severity(self, severity: str, limit: int = 50) -> list[dict]:
        """Get recent events of a specific severity."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE severity=? ORDER BY timestamp DESC LIMIT ?",
                (severity, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_prompt_history(self, limit: int = 50) -> list[dict]:
        """Get prompt history with outcomes."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT trace_id, prompt, intent, status,
                          files_count, ops_count, ops_passed, ops_failed,
                          llm_time_ms, total_time_ms, created_at
                   FROM traces ORDER BY start_time DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def clear_all(self) -> None:
        """Clear all monitoring data. Use for testing."""
        with self._conn() as conn:
            conn.execute("DELETE FROM events")
            conn.execute("DELETE FROM traces")


# ── Module-level singleton ──────────────────────────────────────────
# DO NOT create the singleton here — __init__.py owns the single instance.
# Import `monitor` from the package (devforge.platform.monitor), not from
# this module directly.
