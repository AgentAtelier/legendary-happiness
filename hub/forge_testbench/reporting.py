"""Reporting — pure render functions of an Artifact.

Every renderer formats from the Metric's unit field, so the display is
derived from the data, never hand-passed. This is the ×100/"broke is better"
bug-class eliminated by construction.

Functions:
  matrix(artifact)     → model × test coverage matrix
  scorecards(artifact) → per-model scorecards with verdict breakdown
  summary(artifact)    → human-readable summary text
  stability(a, b)      → diff two artifacts for regression detection
"""

from __future__ import annotations

from typing import Any

from .artifact import Artifact
from .metric import Metric


def _format_metric(m: Metric) -> str:
    """Format a Metric correctly from its unit. No guessing."""
    v = m.value
    unit = m.unit
    if unit == "ratio":
        return f"{float(v):.2f}"
    elif unit == "percent":
        return f"{float(v):.1f}%"
    elif unit == "count":
        return str(int(v))
    elif unit == "ms":
        if v > 60000:
            return f"{v / 1000:.1f}s"
        return f"{int(v)}ms"
    elif unit == "tok_s":
        return f"{float(v):.1f} tok/s"
    elif unit == "bool":
        return "✓" if v else "✗"
    elif unit == "score":
        return f"{int(v)}"
    return str(v)


def matrix(artifact: Artifact) -> dict[str, Any]:
    """Build a model × test matrix with coverage/scores.

    Returns a dict suitable for the Testing tab's matrix view.
    Each cell has: status, score, mean_score, latencies_ms, runs, metrics.
    """
    models = artifact.models
    test_ids = sorted(set(r.test_id for r in artifact.results))
    rows: dict[str, dict[str, dict]] = {}

    for tid in test_ids:
        rows[tid] = {}
        for model in models:
            runs = [r for r in artifact.results if r.test_id == tid and r.model == model]
            if not runs:
                rows[tid][model] = {"status": "no-data"}
                continue

            scores = [r.score for r in runs if r.score is not None]
            lats = [r.latency_ms for r in runs]
            statuses = [r.status for r in runs]
            # Worst status wins
            rank = {"ok": 0, "partial": 1, "broke": 2, "error": 3}
            worst = max(statuses, key=lambda s: rank.get(s, 0))

            cell: dict = {
                "status": worst,
                "runs": len(runs),
                "mean_score": round(sum(scores) / max(len(scores), 1)) if scores else None,
                "mean_latency_ms": round(sum(lats) / max(len(lats), 1)),
                "latencies_ms": lats,
            }

            # Aggregate metrics across runs
            all_metrics: dict[str, list[float]] = {}
            for r in runs:
                for k, m in r.metrics.items():
                    val = m.value
                    if isinstance(val, (int, float)):
                        all_metrics.setdefault(k, []).append(float(val))
            for k, vals in all_metrics.items():
                cell[f"metric_{k}_mean"] = round(sum(vals) / len(vals), 3)

            rows[tid][model] = cell

    return {
        "models": models,
        "test_ids": test_ids,
        "rows": rows,
    }


def scorecards(artifact: Artifact) -> dict[str, Any]:
    """Per-model scorecards with verdict breakdown and top metrics."""
    cards: dict[str, dict] = {}
    for model in artifact.models:
        runs = artifact.by_model(model)
        verdicts = {"ok": 0, "partial": 0, "broke": 0, "error": 0}
        scores: list[int] = []
        total_latency = 0
        test_results: dict[str, dict] = {}

        for r in runs:
            verdicts[r.status] = verdicts.get(r.status, 0) + 1
            if r.score is not None:
                scores.append(r.score)
            total_latency += r.latency_ms

            test_results[r.test_id] = {
                "status": r.status,
                "score": r.score,
                "latency_ms": r.latency_ms,
                "metrics": {k: _format_metric(v) for k, v in r.metrics.items()},
            }

        cards[model] = {
            "verdicts": verdicts,
            "total": len(runs),
            "avg_score": round(sum(scores) / max(len(scores), 1)) if scores else None,
            "total_latency_ms": total_latency,
            "tests": test_results,
        }

    return cards


def summary(artifact: Artifact) -> str:
    """Human-readable summary: model lineup, verdict counts, best model."""
    lines = [
        "╔══════════════════════════════════════════════════════════╗",
        "║     Forge Testbench — Results                             ║",
        "╚══════════════════════════════════════════════════════════╝",
        f"  Suite:     {artifact.suite}",
        f"  Models:    {', '.join(artifact.models)}",
        f"  Results:   {len(artifact.results)}",
        "",
        "═══ Per-Model ═══",
    ]

    cards = scorecards(artifact)
    best_model = ("", 0)
    for model, card in cards.items():
        c = card["verdicts"]
        avg = card["avg_score"]
        lines.append(
            f"  {model:25s}  "
            f"✓{c['ok']}  ~{c['partial']}  ✗{c['broke']}  !{c['error']}  "
            f"score={avg if avg is not None else '—'}"
        )
        if avg is not None and avg > best_model[1]:
            best_model = (model, avg)

    if best_model[0]:
        lines.append(f"\n  ★ Best: {best_model[0]} (avg score {best_model[1]})")

    # Per-test detail
    lines.append("\n═══ Per-Test ═══")
    for model in artifact.models:
        lines.append(f"\n  [{model}]")
        for r in artifact.by_model(model):
            icon = {"ok": "✓", "partial": "~", "broke": "✗", "error": "✗"}[r.status]
            score_str = f"score={r.score}" if r.score is not None else ""
            metrics_str = ", ".join(f"{k}={_format_metric(v)}" for k, v in r.metrics.items())
            lines.append(f"    {icon} {r.test_id:35s}  {score_str:10s}  ({r.latency_ms}ms)  {metrics_str}")

    return "\n".join(lines)


def stability(
    artifact_a: Artifact,
    artifact_b: Artifact,
) -> dict[str, Any]:
    """Compare two artifacts to detect regressions.

    Returns a dict of test_id → {model_a_status, model_b_status, delta_score}.
    A negative delta_score means the second run scored lower.
    """
    diffs: dict[str, dict] = {}

    test_ids = sorted(set(r.test_id for r in artifact_a.results) | set(r.test_id for r in artifact_b.results))

    for tid in test_ids:
        a_runs = artifact_a.by_test(tid)
        b_runs = artifact_b.by_test(tid)

        a_scores = [r.score for r in a_runs if r.score is not None]
        b_scores = [r.score for r in b_runs if r.score is not None]

        a_avg = round(sum(a_scores) / max(len(a_scores), 1)) if a_scores else None
        b_avg = round(sum(b_scores) / max(len(b_scores), 1)) if b_scores else None

        a_status = max(
            (r.status for r in a_runs),
            key=lambda s: {"ok": 0, "partial": 1, "broke": 2, "error": 3}.get(s, 0),
            default="no-data",
        )
        b_status = max(
            (r.status for r in b_runs),
            key=lambda s: {"ok": 0, "partial": 1, "broke": 2, "error": 3}.get(s, 0),
            default="no-data",
        )

        delta = None
        if a_avg is not None and b_avg is not None:
            delta = b_avg - a_avg

        diffs[tid] = {
            "a_status": a_status,
            "b_status": b_status,
            "a_score": a_avg,
            "b_score": b_avg,
            "delta_score": delta,
            "regression": delta is not None and delta < -5,  # >5 point drop = red flag
        }

    return diffs
