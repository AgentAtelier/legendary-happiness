"""Monitor — tracing and telemetry for the DevForge pipeline.

Every /generate request gets a trace that tracks timing,
operations, and errors through the pipeline.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from devforge.infrastructure.logger import logger


@dataclass
class Trace:
    trace_id: str
    prompt: str
    start_time: float
    end_time: float = 0.0
    status: str = "running"
    steps: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def duration_ms(self) -> int:
        if self.end_time > 0:
            return int((self.end_time - self.start_time) * 1000)
        return int((time.time() - self.start_time) * 1000)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "prompt": self.prompt[:100],
            "status": self.status,
            "duration_ms": self.duration_ms(),
            "steps": len(self.steps),
            "warnings": len(self.warnings),
            "errors": self.errors,
            "metadata": self.metadata,
        }


class Monitor:
    def __init__(self):
        self._traces: List[Trace] = []
        self._max_traces = 200

    def begin_trace(self, prompt: str) -> Trace:
        trace = Trace(
            trace_id=str(uuid.uuid4())[:8],
            prompt=prompt,
            start_time=time.time(),
        )
        self._traces.append(trace)
        if len(self._traces) > self._max_traces:
            self._traces = self._traces[-self._max_traces :]

        logger.info("monitor", f"Trace started: {trace.trace_id}", prompt=prompt[:80])
        return trace

    def log_step(self, trace: Trace, step_name: str, data: Dict | None = None) -> None:
        entry = {
            "step": step_name,
            "time": time.time(),
            "data": data or {},
        }
        trace.steps.append(entry)
        logger.debug("monitor", f"[{trace.trace_id}] {step_name}", **(data or {}))

    def log_warning(self, trace: Trace, warning_type: str, data: Dict | None = None) -> None:
        entry = {
            "type": warning_type,
            "time": time.time(),
            "data": data or {},
        }
        trace.warnings.append(entry)
        logger.warn("monitor", f"[{trace.trace_id}] {warning_type}", **(data or {}))

    def log_error(self, trace: Trace, message: str) -> None:
        trace.errors.append(message)
        logger.error("monitor", f"[{trace.trace_id}] {message}")

    def end_trace(self, trace: Trace, status: str = "complete", **metadata) -> None:
        trace.end_time = time.time()
        trace.status = status
        trace.metadata.update(metadata)

        logger.info("monitor", f"Trace ended: {trace.trace_id}", status=status, duration_ms=trace.duration_ms())

    def get_traces(self, limit: int = 50) -> List[Dict]:
        return [t.to_dict() for t in self._traces[-limit:]]

    def get_trace(self, trace_id: str) -> Optional[Trace]:
        for t in self._traces:
            if t.trace_id == trace_id:
                return t
        return None

    def get_stats(self) -> Dict[str, Any]:
        total = len(self._traces)
        completed = sum(1 for t in self._traces if t.status == "complete")
        errored = sum(1 for t in self._traces if t.status == "error")
        avg_ms = 0

        if completed > 0:
            durations = [t.duration_ms() for t in self._traces if t.status == "complete"]
            avg_ms = int(sum(durations) / len(durations))

        return {
            "total_traces": total,
            "completed": completed,
            "errored": errored,
            "avg_duration_ms": avg_ms,
        }

    # ------------------------------------------------------------------
    # Phase 10: Performance metrics
    # ------------------------------------------------------------------

    def get_perf_stats(self) -> Dict[str, Any]:
        """Compute per-stage p50/p95 from trace step data.

        Returns a dict with per-stage latency stats and cache hit rate.
        """
        stage_latencies: Dict[str, list] = {}
        total_latencies: list = []

        for t in self._traces:
            if t.status != "complete":
                continue
            total_latencies.append(t.duration_ms())
            for step in t.steps:
                name = step.get("step", "unknown")
                data = step.get("data", {})
                if "elapsed_ms" in data:
                    if name not in stage_latencies:
                        stage_latencies[name] = []
                    stage_latencies[name].append(data["elapsed_ms"])

        def _p50(values: list) -> float:
            if not values:
                return 0
            s = sorted(values)
            return s[len(s) // 2]

        def _p95(values: list) -> float:
            if not values:
                return 0
            s = sorted(values)
            idx = int(len(s) * 0.95)
            return s[min(idx, len(s) - 1)]

        stages = {}
        for name, lats in stage_latencies.items():
            stages[name] = {
                "p50_ms": round(_p50(lats), 1),
                "p95_ms": round(_p95(lats), 1),
                "min_ms": round(min(lats), 1),
                "max_ms": round(max(lats), 1),
                "samples": len(lats),
            }

        result: Dict[str, Any] = {
            "total": {
                "p50_ms": round(_p50(total_latencies), 1),
                "p95_ms": round(_p95(total_latencies), 1),
                "samples": len(total_latencies),
            },
            "stages": stages,
        }

        # Include cache stats if available from metadata
        for t in self._traces:
            if t.status == "complete" and "cache_hits" in t.metadata:
                result["cache"] = {
                    "hits": t.metadata.get("cache_hits", 0),
                    "misses": t.metadata.get("cache_misses", 0),
                    "hit_rate": t.metadata.get("cache_hit_rate", 0),
                }
                break

        return result


# Singleton
monitor = Monitor()
