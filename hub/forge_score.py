"""Unified scoring for the Forge hub Testing tab.

Pure functions only — no I/O, no FastAPI. Turns any suite's raw result into the
common scorecard shape and durations into a soft ETA. Tested in
tests/test_forge_score.py.
"""

from __future__ import annotations
from statistics import median
from typing import Any


def score_to_verdict(score: float, pass_at: float = 90, partial_at: float = 60) -> str:
    """Map a 0-100 score to a verdict band."""
    if score >= pass_at:
        return "pass"
    if score >= partial_at:
        return "partial"
    return "fail"


def _metric_good(label: str, value: Any) -> bool:
    """Heuristic: a metric is 'good' unless it signals a shortfall.
    - 'n/m' fraction: good iff n >= m.
    - 'overlap'/'err'/'errors': good iff zero/falsey.
    - bool: good iff True. Everything else: good (informational)."""
    low = label.lower()
    if isinstance(value, str) and "/" in value:
        try:
            num, den = (int(x) for x in value.split("/", 1))
            return num >= den
        except ValueError:
            return True
    if low in ("overlap", "err", "errors", "failed"):
        return not value
    if isinstance(value, bool):
        return value
    return True


def normalize_result(suite: str, raw: dict, *, target: str = "current", label: str = "") -> dict:
    """Turn any suite's raw result into the unified scorecard shape.

    Tier 2.6: the unified envelope. Recognizes `kind` from the raw result
    (bench, probe, gauntlet, scenarios) and includes config_hash for
    time-series comparison. Aligns with /api/runs for the Testing-tab
    history view."""
    metrics: list[dict] = []
    if suite == "health":
        checks = raw.get("checks", [])
        passed = sum(1 for c in checks if c.get("passed"))
        score = round(100 * passed / len(checks)) if checks else 0
        metrics = [
            {"label": c.get("name", "?"), "value": "pass" if c.get("passed") else "fail", "good": bool(c.get("passed"))}
            for c in checks
        ]
    else:  # scenarios, gauntlet, and any coverage-based suite
        score = round(raw.get("coverage", raw.get("score", 0)))
        for k, v in (raw.get("metrics") or {}).items():
            metrics.append({"label": k, "value": v, "good": _metric_good(k, v)})
    return {
        "suite": suite,
        "target": target,
        "label": label,
        "score": score,
        "verdict": score_to_verdict(score),
        "metrics": metrics,
        "kind": raw.get("kind", suite),
        "model": raw.get("model", "?"),
        "config_hash": raw.get("config_hash", ""),
        "ts": raw.get("ts", ""),
    }


def eta_from_durations(durations: list[float], recent: int = 5) -> float | None:
    """Median of the most recent `recent` run durations, or None if <2 samples.
    Returns an estimate in the same unit as the inputs (seconds)."""
    if len(durations) < 2:
        return None
    window = durations[-recent:]
    return median(window)
