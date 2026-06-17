"""Performance Sentinel — sample, store, and analyze Godot performance metrics.

Deterministic core (tier 0): no LLM calls.  Designed to be called
periodically during development to build a performance profile.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Any

from devforge.infrastructure.logger import logger


@dataclass
class PerfSample:
    """A single performance snapshot."""

    timestamp: float
    metrics: dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "metrics": self.metrics,
        }


class PerformanceSentinel:
    """Collects, stores, and reports Godot performance monitor samples.

    Thread-safe.  Holds up to *max_samples* in memory; older samples
    are evicted when the limit is reached.

    Usage::

        sentinel = PerformanceSentinel()
        sentinel.sample_from(executor.get_performance_monitors())
        history = sentinel.history()
    """

    def __init__(self, max_samples: int = 100):
        self._max_samples = max_samples
        self._samples: list[PerfSample] = []
        self._lock = threading.Lock()

    @property
    def count(self) -> int:
        """Number of samples currently stored."""
        with self._lock:
            return len(self._samples)

    def sample(self, metrics: dict[str, Any] | None) -> PerfSample | None:
        """Record a new performance sample.

        Returns the stored sample, or None if *metrics* is None
        (e.g. editor unreachable).
        """
        if metrics is None:
            logger.warn("sentinel", "Skipped sample — no metrics received")
            return None

        sample = PerfSample(timestamp=time.time(), metrics=metrics)

        with self._lock:
            self._samples.append(sample)
            if len(self._samples) > self._max_samples:
                self._samples = self._samples[-self._max_samples:]

        logger.info(
            "sentinel",
            f"Sample recorded: {len(metrics)} metrics, "
            f"total samples={len(self._samples)}",
        )
        return sample

    def history(self, n: int = 20) -> dict[str, Any]:
        """Return the most recent *n* samples with summary stats.

        Returns a dict with:
        - ``samples``: list of recent samples (newest first)
        - ``summary``: per-metric stats (min, max, avg) across all samples
        - ``total_samples``: number of samples in the ring buffer
        """
        with self._lock:
            recent = self._samples[-n:][::-1]  # newest first
            all_samples = list(self._samples)

        # ── Per-metric summary ──────────────────────────────
        # Aggregate numeric metrics across all samples
        metric_values: dict[str, list[float]] = {}

        for s in all_samples:
            for key, val in s.metrics.items():
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    metric_values.setdefault(key, []).append(val)

        summary: dict[str, dict] = {}
        for key, vals in metric_values.items():
            if vals:
                summary[key] = {
                    "min": min(vals),
                    "max": max(vals),
                    "avg": round(sum(vals) / len(vals), 2),
                    "sample_count": len(vals),
                }

        return {
            "samples": [s.to_dict() for s in recent],
            "summary": summary,
            "total_samples": len(all_samples),
        }

    def clear(self) -> None:
        """Clear all stored samples."""
        with self._lock:
            self._samples.clear()
