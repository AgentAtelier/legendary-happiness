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
from eval.signals import compute_signals, record_tier


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
    low_severity_cap: Optional[int] = 8,
) -> SampleResult:
    """Pick a deterministic, statistically-sound probe set.

    Slice-1 (default): per-stratum pick, with optional ``problem_cap`` to
    cap each problem stratum, and ``clean_baseline_n`` for the random
    clean baseline.

    Slice-2 (severity-weighted): in addition, every record's tag set is
    classified into a tier via ``record_tier`` ("high" | "low" | "clean"):

      - **high-tier** records are ALL included (high-severity tags must
        be eyeballed; the sampler can't screen them out).
      - **low-tier** records (only low-severity tags, e.g. decision_fired)
        are capped at ``low_severity_cap`` (seeded-sampled when over the
        cap).  Default ``low_severity_cap = 8`` matches the design spec.
      - **clean** records continue to use ``clean_baseline_n`` exactly
        as before.

    The legacy per-stratum ``problem_cap`` still applies when set: each
    non-clean stratum is capped at most ``problem_cap`` records.  The
    severity tier filter is layered ON TOP of the per-stratum pick — it
    only ever REINS IN low-tier records further when there are more
    than ``low_severity_cap`` of them.

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
        low_severity_cap: If set, after the per-stratum pass, low-tier
            (severity=="low") records in ``picked`` are sampled down to
            at most this many records via the seeded RNG.  Default 8.

    Returns:
        ``SampleResult`` with probes (dedup'd union, multi-strata
        labelled), stratum_sizes (full population counts), and the seed.
        Each probe carries a human-readable ``reason`` reflecting its
        tier selection ("high-tier (...)", "low-tier-sampled (...)",
        "clean-baseline").
    """
    rng = random.Random(seed)

    # ── 1. Compute signals + populate strata (full population)
    # ───────────────────────────────────
    stratum_to_indices: Dict[str, List[int]] = {}
    record_tags: Dict[int, Set[str]] = {}
    for idx, rec in enumerate(records):
        tags = (signals_fn(rec) or set())
        if not tags:
            tags = {"clean"}
        record_tags[idx] = tags
        for tag in tags:
            # Every tag (including 'clean') is its own stratum.
            stratum_to_indices.setdefault(tag, []).append(idx)

    # ── 2. Per-stratum pick (slice-1 contract; honors problem_cap)
    # ────────────────────────────
    picked: Dict[int, List[str]] = {}  # index → strata this index belongs to
    for tag, indices in stratum_to_indices.items():
        if tag == "clean":
            continue  # clean handled below
        if problem_cap is None or len(indices) <= problem_cap:
            chosen = indices
        else:
            # Seeded sample up to problem_cap.
            chosen = rng.sample(indices, problem_cap)
        for i in chosen:
            if i not in picked:
                picked[i] = []
            if tag not in picked[i]:
                picked[i].append(tag)

    # ── 3. Severity-tier filter (slice-2): cap low-tier records
    # ──────────────────────
    # High-tier records are NOT touched here — they were already in
    # ``picked`` from step 2 (or were all included if problem_cap was
    # None) and we want every one of them in the probe set.
    low_tier_in_picked: List[int] = [
        idx for idx, tags in record_tags.items()
        if idx in picked and record_tier(tags) == "low"
    ]
    if low_severity_cap is not None and len(low_tier_in_picked) > low_severity_cap:
        chosen_low_set = set(rng.sample(low_tier_in_picked, low_severity_cap))
        for idx in low_tier_in_picked:
            if idx not in chosen_low_set:
                # Low-tier records have ONLY low-severity tags by
                # definition, so deleting the whole entry is safe.
                picked.pop(idx, None)

    # ── 4. Clean baseline (slice-1 contract; same RNG) ──────────
    clean_indices = stratum_to_indices.get("clean", [])
    if clean_baseline_n > 0 and clean_indices:
        n_clean_pick = min(clean_baseline_n, len(clean_indices))
        chosen_clean = (
            clean_indices if n_clean_pick == len(clean_indices)
            else rng.sample(clean_indices, n_clean_pick)
        )
        for i in chosen_clean:
            if i not in picked:
                picked[i] = []
            if "clean" not in picked[i]:
                picked[i].append("clean")

    # ── 5. Build probe list (preserve insertion order: problems first,
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
        tier = record_tier(record_tags[idx])
        probes.append({
            "index": idx,
            "strata": strata,
            "reason": _reason_for(strata, tier=tier),
        })
    for idx, strata in clean_after:
        probes.append({
            "index": idx,
            "strata": strata,
            "reason": _reason_for(strata, tier="clean"),
        })

    # ── 6. Stratum sizes = full population counts ────────────────────
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


def _reason_for(strata: List[str], *, tier: str) -> str:
    """Build a human-readable 'why was this picked' string.

    After severity-tier classification (slice 2), reasons explicitly
    label a probe as one of:

      - "high-tier (strata: ...)"       (severity-weighted inclusion)
      - "low-tier-sampled (strata: ...)" (severity-capped, default cap 8)
      - "clean-baseline"                 (the slice-1 contract baseline)
    """
    if tier == "clean":
        if strata == ["clean"]:
            return "clean-baseline"
        return (
            "clean-baseline (also: "
            f"{', '.join(s for s in strata if s != 'clean')})"
        )
    if tier == "high":
        return f"high-tier (strata: {', '.join(strata)})"
    if tier == "low":
        return f"low-tier-sampled (strata: {', '.join(strata)})"
    # legacy / unknown tier
    return f"problem stratum: {', '.join(strata)}"
