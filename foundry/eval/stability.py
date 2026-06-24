"""foundry.eval.stability — stability lens (Prompt 4).

Run each request N times through the planner and measure run-to-run
variance of qwen's choices.  This directly validates whether the age
pre-pass made age deterministic: age variance should be 0.

Unstable if across N runs:
  - generator differs
  - material differs (regression guard — should be 0)
  - age differs (post-age-prepass should be 0)
  - any param drifts >15% relative

``run_stability`` is pure/injectable: a FAKE llm makes it deterministic
in tests.  Outputs report.md + report.json.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Dict, List, Tuple

# ── Core entry point ──────────────────────────────────────────────────


def _default_plan(
    request: str, llm: Callable[[str, str | None], str]
) -> Tuple[dict, List]:
    from planner import AssetPlanner
    return AssetPlanner().plan(request, llm)


def _param_drift(a: float, b: float) -> float:
    """Relative difference between *a* and *b*, clipped to a small floor
    to avoid division by zero.  Returns >0.15 when params have drifted."""
    denom = max(abs(a), abs(b), 0.001)
    return abs(a - b) / denom


def _captured_keys(spec: dict) -> dict:
    """Extract the stability-relevant keys from a plan() spec."""
    return {
        "generator": spec.get("generator"),
        "material": spec.get("material"),
        "age": spec.get("age"),
        "params": dict(spec.get("params") or {}),
    }


def run_stability(
    requests: List[str],
    *,
    runs: int = 5,
    seed: int = 1337,
    llm: Callable[[str, str | None], str] | None = None,
    plan: Callable[..., Tuple[dict, List]] | None = None,
) -> Tuple[List[dict], float]:
    """Run *requests* through the planner N times, measuring variance.

    Args:
        requests: NL asset descriptions (from a corpus file).
        runs: Number of times to run each request (default 5).
        seed: Echoed into the report for reproducibility.
        llm: Injectable LLM callable (fake for tests, FoundryLLM for live).
        plan: Injectable plan function. Defaults to ``AssetPlanner().plan``.

    Returns:
        ``(per_request_results, stability_score)`` where
        ``per_request_results`` is a list of dicts each with
        ``{request, stable, varied, runs_info}`` and ``stability_score``
        is the percentage (0.0–1.0) of requests that were stable.
    """
    if plan is None:
        plan = _default_plan

    per_request: List[dict] = []
    stable_count = 0

    for req in requests:
        captures: List[dict] = []
        for _ in range(runs):
            spec, _decisions = plan(req, llm)
            captures.append(_captured_keys(spec))

        varied: set[str] = set()

        # Check generator
        gens = {c["generator"] for c in captures}
        if len(gens) > 1:
            varied.add("generator")

        # Check material (regression guard)
        mats = {c["material"] for c in captures}
        if len(mats) > 1:
            varied.add("material")

        # Check age (validation of age pre-pass)
        ages = {c["age"] for c in captures}
        if len(ages) > 1:
            varied.add("age")

        # Check param drift >15%
        param_keys = set()
        for c in captures:
            param_keys.update(c["params"].keys())
        for key in sorted(param_keys):
            values = [c["params"].get(key) for c in captures]
            # Only compare if at least 2 runs have this key
            valid = [v for v in values if v is not None and isinstance(v, (int, float))]
            if len(valid) < 2:
                continue
            for i in range(len(valid)):
                for j in range(i + 1, len(valid)):
                    if _param_drift(valid[i], valid[j]) > 0.15:
                        varied.add(f"param:{key}")
                        break
                if f"param:{key}" in varied:
                    break

        stable = len(varied) == 0
        if stable:
            stable_count += 1

        # Build runs_info: per-run {generator, material, age, params}
        runs_info = [
            {
                "generator": c["generator"],
                "material": c["material"],
                "age": c["age"],
                "params": c["params"],
            }
            for c in captures
        ]

        per_request.append({
            "request": req,
            "stable": stable,
            "varied": sorted(varied),
            "runs_info": runs_info,
        })

    stability_score = stable_count / len(requests) if requests else 0.0
    return per_request, stability_score


# ── Report builders ───────────────────────────────────────────────────


def build_report_dict(
    per_request: List[dict],
    stability_score: float,
    runs: int,
    seed: int,
    total: int,
) -> dict:
    """Build the machine dict for the stability report."""
    unstable = [r for r in per_request if not r["stable"]]
    return {
        "total": total,
        "runs_per_request": runs,
        "seed": seed,
        "stable_count": total - len(unstable),
        "unstable_count": len(unstable),
        "stability_score": round(stability_score, 4),
        "varied_counts": _count_varied(per_request),
        "unstable": [
            {
                "request": r["request"],
                "varied": r["varied"],
            }
            for r in unstable
        ],
        "per_request": per_request,
    }


def build_report_md(report_dict: dict) -> str:
    """Build the markdown digest for the stability report."""
    lines: List[str] = []
    lines.append("# Foundry Eval — Stability Report")
    lines.append("")
    lines.append(f"- **Total requests:** {report_dict['total']}")
    lines.append(f"- **Runs per request:** {report_dict['runs_per_request']}")
    lines.append(f"- **Seed:** {report_dict['seed']}")
    lines.append(f"- **Stable:** {report_dict['stable_count']} / {report_dict['total']}")
    lines.append(f"- **Unstable:** {report_dict['unstable_count']} / {report_dict['total']}")
    lines.append(f"- **Stability score:** {report_dict['stability_score']:.1%}")
    lines.append("")

    # Varied-field counts
    vc = report_dict.get("varied_counts") or {}
    if vc:
        lines.append("## What varied")
        for field in sorted(vc):
            lines.append(f"- {field} — {vc[field]} request(s)")
    else:
        lines.append("## What varied")
        lines.append("_(nothing — all requests stable)_")
    lines.append("")

    # Unstable detail
    unstable = report_dict.get("unstable") or []
    if unstable:
        lines.append("## Unstable requests")
        lines.append("")
        for i, u in enumerate(unstable, start=1):
            varied_str = ", ".join(u["varied"])
            lines.append(f"{i}. `\"{u['request']}\"` — varied: {varied_str}")
    else:
        lines.append("## Unstable requests")
        lines.append("")
        lines.append("_(none — all stable)_")
    lines.append("")

    return "\n".join(lines) + "\n"


def _count_varied(per_request: List[dict]) -> Dict[str, int]:
    """Count how many requests varied in each field."""
    from collections import Counter
    c: Counter[str] = Counter()
    for r in per_request:
        for v in r.get("varied", []):
            c[v] += 1
    return dict(c)
