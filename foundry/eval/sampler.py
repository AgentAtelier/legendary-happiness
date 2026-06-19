"""foundry.eval.sampler — seeded stratified sampler (slice 1).

The harness drives a corpus through the planner/forge and captures a
``RunRecord`` per request.  This module turns those records into a
PROBE SET — a small, statistically-chosen slice that a human can
actually eyeball — without losing the population scaffold.

Algorithm (per spec):
    1. Compute signals for each record.
    2. Partition into strata by signal tag:
         - each non-"clean" tag is a PROBLEM STRATUM (a record may
           appear in multiple problem strata — e.g. an error+decision
           record goes in BOTH "build_error" AND "decision_fired").
         - "clean" is its own stratum.
    3. probes = union of:
         - problem-stratum records, optionally capped per stratum at
           problem_cap (seeded RNG above the cap), AND
         - min(clean_baseline_n, |clean|) random clean records drawn
           with the SAME seeded RNG.
    4. Probe objects include the record's index, its full multi-set of
       strata, and a human-readable "reason" string.

The estimator (``estimate_clean_rate``) is pure math: given human
pass/fail verdicts on the sampled clean probes, project a clean-stratum
quality rate (rate × population).  Used by the friction report later.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from eval.harness import RunRecord
from eval.signals import compute_signals


# ── SampleResult ──────────────────────────────────────────────────────


@dataclass
class SampleResult:
    """The outcome of one stratify-and-sample run."""

    # Each probe is a dict so the report layer can JSON-serialize directly.
    # Probe shape: {"index": int, "strata": list[str], "reason": str}.
    probes: List[dict] = field(default_factory=list)
    # Full population counts per stratum (NOT the sampled/capped counts).
    stratum_sizes: Dict[str, int] = field(default_factory=dict)
    # The RNG seed — echoed for reproducibility in the report.
    seed: int = 0


# ── Public entry points ───────────────────────────────────────────────


def stratify_and_sample(
    records: List[RunRecord],
    *,
    seed: int,
    clean_baseline_n: int,
    signals_fn: Callable[[RunRecord], set] = compute_signals,
    problem_cap: Optional[int] = None,
) -> SampleResult:
    """Pick a deterministic, statistically-sound probe set.

    Args:
        records: Full population of RunRecords from ``run_corpus``.
        seed: RNG seed — same seed → same probes (reproducibility).
        clean_baseline_n: How many random clean records to add to the
            probe set. Capped at ``|clean|``.
        signals_fn: Pure function record → set of signal tags.
            Default: ``compute_signals``.  Injected for tests.
        problem_cap: If set, each non-clean stratum is sampled down to
            at most this many records via the seeded RNG.  All-cap
            (None) selects every problem-stratum record — the cheap
            option for small corpora.

    Returns:
        ``SampleResult`` with probes (dedup'd union, multi-strata
        labelled), stratum_sizes (full population counts), and the seed.
    """
    rng = random.Random(seed)

    # ── 1. Compute signals + populate strata
    # ───────────────────────────────────
    stratum_to_indices: Dict[str, List[int]] = {}
    for idx, rec in enumerate(records):
        tags = signals_fn(rec) or set()
        for tag in tags:
            # Every tag (including 'clean') is its own stratum.
            stratum_to_indices.setdefault(tag, []).append(idx)

    # ── 2. Sample problem strata (each non-clean tag) ─────────────────
    picked: Dict[int, List[str]] = {}  # index → strata this index belongs to
    for tag, indices in stratum_to_indices.items():
        if tag == "clean":
            continue  # clean handled below
        if problem_cap is None:
            for i in indices:
                picked.setdefault(i, []).append(tag)
        else:
            # Seeded sample up to problem_cap.
            chosen = indices if len(indices) <= problem_cap else rng.sample(
                indices, problem_cap
            )
            for i in chosen:
                picked.setdefault(i, []).append(tag)

    # ── 3. Clean baseline (same RNG) ─────────────────────────────────
    clean_indices = stratum_to_indices.get("clean", [])
    if clean_baseline_n > 0 and clean_indices:
        n_clean_pick = min(clean_baseline_n, len(clean_indices))
        chosen_clean = (
            clean_indices if n_clean_pick == len(clean_indices)
            else rng.sample(clean_indices, n_clean_pick)
        )
        for i in chosen_clean:
            picked.setdefault(i, []).append("clean")

    # ── 4. Build probe list (preserve insertion order: problems first,
    #       then clean — keeps reports stable + the spec says ALL
    #       problem records come first).
    problem_first = []
    clean_after = []
    for idx, strata in picked.items():
        is_clean_only = strata == ["clean"]
        if is_clean_only:
            clean_after.append((idx, strata))
        else:
            problem_first.append((idx, strata))

    # Deterministic within-group order: by record index keeps the report
    # in input order, which matches run_corpus output. Seeded RNG already
    # broke ties for the cap + clean pick.
    problem_first.sort(key=lambda x: x[0])
    clean_after.sort(key=lambda x: x[0])

    probes: List[dict] = []
    for idx, strata in problem_first:
        probes.append({
            "index": idx,
            "strata": strata,
            "reason": _reason_for(strata, kind="problem"),
        })
    for idx, strata in clean_after:
        probes.append({
            "index": idx,
            "strata": strata,
            "reason": _reason_for(strata, kind="clean"),
        })

    # ── 5. Stratum sizes = full population counts ────────────────────
    stratum_sizes = {tag: len(idx_list) for tag, idx_list in stratum_to_indices.items()}

    return SampleResult(probes=probes, stratum_sizes=stratum_sizes, seed=seed)


def estimate_clean_rate(
    clean_pass: int, clean_sampled: int, clean_size: int
) -> dict:
    """Pure math: project a sampled clean-stratum pass-rate onto the full
    clean population.

    Returns a dict with:
        "sample_pass_rate"     – clean_pass / clean_sampled (0 if sampled==0)
        "projected_clean_ok"   – round(sample_pass_rate * clean_size)
        "clean_size"           – the clean population size
    """
    sample_pass_rate = (clean_pass / clean_sampled) if clean_sampled > 0 else 0.0
    projected_clean_ok = int(round(sample_pass_rate * clean_size))
    return {
        "sample_pass_rate": sample_pass_rate,
        "projected_clean_ok": projected_clean_ok,
        "clean_size": clean_size,
    }


# ── Inner helpers ─────────────────────────────────────────────────────


def _reason_for(strata: List[str], *, kind: str) -> str:
    """Build a human-readable 'why was this picked' string."""
    if kind == "clean":
        return "clean baseline" if strata == ["clean"] else (
            f"clean baseline; also in: {', '.join(s for s in strata if s != 'clean')}"
        )
    # problem
    return f"problem stratum: {', '.join(strata)}"
