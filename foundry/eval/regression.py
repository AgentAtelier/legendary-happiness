"""foundry.eval.regression — golden-master regression lens (Prompt 5).

Each corpus request gets a paired JSON expectation capturing expected
(generator, material, age).  Run each request once and compare:

  - material + age → HARD assertions (deterministic via resolvers;
    a mismatch is a real failure).
  - generator → tracked assertion (reported but weighted separately —
    may reflect residual qwen variance).

``--update`` rewrites expectation files from current output (re-bless
after approved changes).  Outputs report.md + report.json with
per-field diffs and an aggregate score.

Inject a FAKE llm/plan for deterministic tests.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


# ── Hashing ──────────────────────────────────────────────────────────


def _request_hash(request: str) -> str:
    """Deterministic key for a request — first 16 hex chars of SHA-256
    of the lowercased, stripped request."""
    return hashlib.sha256(request.strip().lower().encode()).hexdigest()[:16]


# ── Expectation I/O ──────────────────────────────────────────────────


def _load_expectation(expectations_dir: str, req_hash: str) -> Optional[dict]:
    path = Path(expectations_dir) / f"{req_hash}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _save_expectation(expectations_dir: str, req_hash: str, spec: dict):
    path = Path(expectations_dir) / f"{req_hash}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generator": spec.get("generator"),
        "material": spec.get("material"),
        "age": spec.get("age"),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# ── Default plan ─────────────────────────────────────────────────────


def _default_plan(
    request: str, llm: Callable[[str, Optional[str]], str]
) -> Tuple[dict, List]:
    from planner import AssetPlanner
    return AssetPlanner().plan(request, llm)


# ── Public entry point ───────────────────────────────────────────────


def run_regression(
    requests: List[str],
    expectations_dir: str,
    *,
    llm: Optional[Callable[[str, Optional[str]], str]] = None,
    plan: Optional[Callable] = None,
    update: bool = False,
) -> Tuple[List[dict], dict]:
    """Run *requests* once each through the planner, comparing output
    against golden-master expectations.

    Args:
        requests: NL asset descriptions.
        expectations_dir: Dir where per-request ``<hash>.json`` expectation
            files live (created on first run via ``--update``).
        llm: Injectable LLM callable.
        plan: Injectable plan function. Defaults to AssetPlanner().plan.
        update: When True, save the CURRENT planner output as the new
            expectation (re-bless after approved changes).

    Returns:
        ``(per_request_results, score_dict)``.
    """
    if plan is None:
        plan = _default_plan

    results: List[dict] = []
    hard_pass = 0
    hard_fail = 0
    generator_mismatches = 0

    for req in requests:
        req_hash = _request_hash(req)
        expected = _load_expectation(expectations_dir, req_hash)

        spec, _decisions = plan(req, llm)

        got = {
            "generator": spec.get("generator"),
            "material": spec.get("material"),
            "age": spec.get("age"),
        }

        if update:
            _save_expectation(expectations_dir, req_hash, spec)

        diffs: Dict[str, dict] = {}
        hard_ok = True

        # HARD — material (must be deterministic via resolver)
        if expected is not None and expected.get("material") != got["material"]:
            diffs["material"] = {
                "expected": expected["material"],
                "got": got["material"],
            }
            hard_ok = False

        # HARD — age (must be deterministic via resolver post-P1)
        if expected is not None and expected.get("age") != got["age"]:
            diffs["age"] = {
                "expected": expected.get("age"),
                "got": got["age"],
            }
            hard_ok = False

        # TRACKED — generator (informational only; may vary with qwen)
        if expected is not None and expected.get("generator") != got["generator"]:
            diffs["generator"] = {
                "expected": expected["generator"],
                "got": got["generator"],
            }
            generator_mismatches += 1

        if expected is not None:
            if hard_ok:
                hard_pass += 1
            else:
                hard_fail += 1

        results.append({
            "request": req,
            "hash": req_hash,
            "passed": hard_ok if expected is not None else None,
            "expected": expected,
            "got": got,
            "diffs": diffs if diffs else None,
        })

    total_with_expectations = hard_pass + hard_fail
    score = round(hard_pass / total_with_expectations, 4) if total_with_expectations > 0 else 1.0

    score_dict = {
        "total": len(requests),
        "with_expectations": total_with_expectations,
        "hard_pass": hard_pass,
        "hard_fail": hard_fail,
        "generator_mismatches": generator_mismatches,
        "score": score,
    }

    return results, score_dict


# ── Report builders ──────────────────────────────────────────────────


def build_report_dict(
    results: List[dict],
    score: dict,
) -> dict:
    """Build the machine dict for the regression report."""
    failed = [r for r in results if r["passed"] is False]
    generator_only = [
        r for r in results
        if r["passed"] is not False
        and r["diffs"] is not None
        and "generator" in r["diffs"]
    ]
    return {
        "total": score["total"],
        "with_expectations": score["with_expectations"],
        "hard_pass": score["hard_pass"],
        "hard_fail": score["hard_fail"],
        "generator_mismatches": score["generator_mismatches"],
        "score": score["score"],
        "failed": [
            {
                "request": r["request"],
                "hash": r["hash"],
                "diffs": r["diffs"],
            }
            for r in failed
        ],
        "generator_only_mismatches": [
            {
                "request": r["request"],
                "hash": r["hash"],
                "diffs": r["diffs"],
            }
            for r in generator_only
        ],
        "per_request": results,
    }


def build_report_md(report_dict: dict) -> str:
    """Build the markdown digest for the regression report."""
    lines: List[str] = []
    lines.append("# Foundry Eval — Regression Report")
    lines.append("")
    lines.append(f"- **Total requests:** {report_dict['total']}")
    lines.append(f"- **With expectations:** {report_dict['with_expectations']}")
    lines.append(f"- **HARD pass:** {report_dict['hard_pass']}")
    lines.append(f"- **HARD fail:** {report_dict['hard_fail']}")
    lines.append(f"- **Generator-only mismatches:** {report_dict['generator_mismatches']}")
    lines.append(f"- **Score:** {report_dict['score']:.1%}")
    lines.append("")

    failed = report_dict.get("failed") or []
    if failed:
        lines.append("## HARD failures")
        lines.append("")
        for i, f in enumerate(failed, start=1):
            diffs_desc = ", ".join(
                f"{k}: expected={v['expected']}, got={v['got']}"
                for k, v in (f.get("diffs") or {}).items()
            )
            lines.append(f"{i}. `\"{f['request']}\"` — {diffs_desc}")
    else:
        lines.append("## HARD failures")
        lines.append("")
        lines.append("_(none)_")
    lines.append("")

    gen_only = report_dict.get("generator_only_mismatches") or []
    if gen_only:
        lines.append("## Generator-only mismatches (tracked, not hard failures)")
        lines.append("")
        for i, g in enumerate(gen_only, start=1):
            d = g["diffs"].get("generator", {})
            lines.append(
                f"{i}. `\"{g['request']}\"` — "
                f"expected={d.get('expected')}, got={d.get('got')}"
            )
    else:
        lines.append("## Generator-only mismatches (tracked, not hard failures)")
        lines.append("")
        lines.append("_(none)_")
    lines.append("")

    return "\n".join(lines) + "\n"
