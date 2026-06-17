"""Result — the uniform result shape. One schema for probe, scenario,
capability, variety, intent — everything that can be measured.

Every Result can hold multiple self-describing Metrics so downstream
renderers format each number correctly by reading its unit, not by guessing.
"""

from __future__ import annotations

from typing import Literal

from .metric import Metric

Status = Literal["ok", "partial", "broke", "error"]


class Result:
    """The universal result shape: test identification + metrics + raw data.

    Attributes:
        test_id: The unique test identifier (e.g. "probe.llama.throughput").
        category: "probe" | "scenario" | "capability" | "variety" | "intent" | "ceiling"
        suite: Which suite this run belongs to (e.g. "everything").
        model: The model alias in use when this test ran.
        ts: ISO timestamp of the run.
        run_index: 1-based index within this test's repeat group.
        repeat_count: Total number of repeats for this test.
        status: Uniform verdict across all test kinds (ok/partial/broke/error).
        score: Canonical 0-100 headline or None if not applicable (probes).
        metrics: Named self-describing Metric objects.
        raw: Test-specific observations (what the test wants to carry).
        errors: List of error strings if status is "error" or "broke".
        latency_ms: Wall clock duration of the run.
        screenshot: Optional path to a screenshot artifact.
    """

    __slots__ = (
        "test_id",
        "category",
        "suite",
        "model",
        "ts",
        "run_index",
        "repeat_count",
        "status",
        "score",
        "metrics",
        "raw",
        "errors",
        "latency_ms",
        "screenshot",
    )

    def __init__(
        self,
        test_id: str,
        category: str,
        model: str,
        status: Status,
        *,
        suite: str = "",
        ts: str = "",
        run_index: int = 1,
        repeat_count: int = 1,
        score: int | None = None,
        metrics: dict[str, Metric] | None = None,
        raw: dict | None = None,
        errors: list[str] | None = None,
        latency_ms: int = 0,
        screenshot: str = "",
    ) -> None:
        self.test_id = test_id
        self.category = category
        self.suite = suite
        self.model = model
        self.ts = ts
        self.run_index = run_index
        self.repeat_count = repeat_count
        self.status = status
        self.score = score
        self.metrics = metrics or {}
        self.raw = raw or {}
        self.errors = errors or []
        self.latency_ms = latency_ms
        self.screenshot = screenshot

    def to_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "category": self.category,
            "suite": self.suite,
            "model": self.model,
            "ts": self.ts,
            "run_index": self.run_index,
            "repeat_count": self.repeat_count,
            "status": self.status,
            "score": self.score,
            "metrics": {k: v.to_dict() for k, v in self.metrics.items()},
            "raw": self.raw,
            "errors": self.errors,
            "latency_ms": self.latency_ms,
            "screenshot": self.screenshot,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Result":
        return cls(
            test_id=d["test_id"],
            category=d["category"],
            model=d["model"],
            status=d["status"],
            suite=d.get("suite", ""),
            ts=d.get("ts", ""),
            run_index=d.get("run_index", 1),
            repeat_count=d.get("repeat_count", 1),
            score=d.get("score"),
            metrics={k: Metric.from_dict(v) for k, v in d.get("metrics", {}).items()},
            raw=d.get("raw"),
            errors=d.get("errors"),
            latency_ms=d.get("latency_ms", 0),
            screenshot=d.get("screenshot", ""),
        )


class ScoredResult:
    """What test.score() returns: status + score + metrics — no run metadata.

    This is what each test's score() pure function produces. The runner
    wraps it in a full Result with model, ts, run_index, etc.
    """

    __slots__ = ("test_id", "status", "score", "metrics", "raw", "errors")

    def __init__(
        self,
        test_id: str,
        status: Status,
        score: int | None = None,
        metrics: dict[str, Metric] | None = None,
        raw: dict | None = None,
        errors: list[str] | None = None,
    ) -> None:
        self.test_id = test_id
        self.status = status
        self.score = score
        self.metrics = metrics or {}
        self.raw = raw or {}
        self.errors = errors or []
