"""TDD tests for foundry.eval.sampler — seeded stratified sampler (slice 1).

stratify_and_sample partitions records by their objective signals into
strata (a record may appear in multiple problem strata; 'clean' is its
own stratum), then deterministically — given a seed — selects probes:

    - all problem-stratum records (optionally capped at problem_cap)
    - plus exactly min(clean_baseline_n, |clean|) clean records

estimate_clean_rate projects a sampled clean-stratum pass-rate onto the
full clean population (pure math).

Tests use synthetic RunRecords — no pipeline, no llm, no Blender.
"""

from __future__ import annotations

import pytest
from eval.harness import RunRecord
from eval.sampler import SampleResult, estimate_clean_rate, stratify_and_sample

# ── helpers ───────────────────────────────────────────────────────────


def _rec(
    request: str = "a table",
    *,
    error: str | None = None,
    gate_passed: bool | None = None,
    gate_reasons: list[str] | None = None,
    decisions: list[dict] | None = None,
    spec: dict | None = None,
) -> RunRecord:
    return RunRecord(
        request=request,
        spec=spec,
        decisions=list(decisions or []),
        gate_passed=gate_passed,
        gate_reasons=list(gate_reasons or []),
        built=False,
        error=error,
        glb_path=None,
        seconds=0.01,
    )


def _clean_record(i: int) -> RunRecord:
    """A record whose signals are {'clean'}: no error, gate passes,
    no decisions, spec has no size/material mismatches."""
    # Cabinet at mid height, no keywords in request.
    return _rec(
        request=f"plain storage unit {i}",
        gate_passed=True,
        spec={
            "asset_id": "cabinet",
            "generator": "cabinet",
            "material": "worn_oak",
            "age": 0.15,
            "params": {
                "width": 0.8, "depth": 0.5, "height": 1.3,
                "panel_thickness": 0.04, "base_height": 0.08,
            },
        },
    )


def _error_record(i: int) -> RunRecord:
    return _rec(request=f"crash me {i}", error=f"RuntimeError('boom {i}')")


def _gate_rejected_record(i: int) -> RunRecord:
    return _rec(
        request=f"rejected {i}",
        spec={
            "asset_id": "table",
            "generator": "table",
            "material": "worn_oak",
            "age": 0.15,
            "params": {
                "top_width": 1.5, "top_depth": 0.8, "top_thickness": 0.06,
                "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
            },
        },
        gate_passed=False,
        gate_reasons=["polygon budget exceeded"],
    )


# ── overall shape ────────────────────────────────────────────────────


def test_sampler_returns_sample_result_dataclass_with_expected_fields():
    records = [_clean_record(i) for i in range(3)]
    out = stratify_and_sample(records, seed=1337, clean_baseline_n=2)
    assert isinstance(out, SampleResult)
    assert isinstance(out.probes, list)
    assert isinstance(out.stratum_sizes, dict)
    assert out.seed == 1337


# ── "all problem records selected" (no cap) ──────────────────────────


def test_sampler_all_problem_records_selected_when_no_cap():
    """No problem_cap → every problem-stratum record is selected (and the
    dedup'd union is what's returned, with multi-strata labelling)."""
    records: list[RunRecord] = []
    records.extend(_error_record(i)       for i in range(2))   # 2 build_error
    records.extend(_gate_rejected_record(i) for i in range(3)) # 3 gate_rejected
    records.extend(_clean_record(i)         for i in range(5)) # 5 clean
    out = stratify_and_sample(records, seed=42, clean_baseline_n=2)
    # All 2 build_error + All 3 gate_rejected = 5 problem probes (no overlap
    # because we don't mix signals per record here).
    # Plus exactly min(2, 5) = 2 clean probes.
    assert len(out.probes) == 7
    # The probes must include every error and every gate-rejected index.
    picked_indexes = {p["index"] for p in out.probes}
    for i in range(2):
        assert i in picked_indexes  # error indices 0,1
    for i in range(2, 5):
        assert i in picked_indexes  # gate indexes 2,3,4


# ── multi-stratum membership ─────────────────────────────────────────


def test_sampler_multi_strata_record_has_all_strata_in_its_reason():
    """A record in multiple problem strata appears ONCE in probes with
    all its strata listed."""
    # A record with BOTH error and a decision would be in 'build_error'
    # AND 'decision_fired' strata.
    multi = _rec(
        request="broken decided",
        error="RuntimeError('a')",
        decisions=[{"code": "material.family_defaulted"}],
    )
    records = [multi, _clean_record(99)]
    out = stratify_and_sample(records, seed=1, clean_baseline_n=1)
    # The multi-record is in 'build_error' AND 'decision_fired'; should
    # appear once with both strata listed.
    problem_probes = [p for p in out.probes if p["index"] == 0]
    assert len(problem_probes) == 1
    probe = problem_probes[0]
    assert set(probe["strata"]) == {"build_error", "decision_fired"}


# ── clean baseline ───────────────────────────────────────────────────


def test_sampler_clean_baseline_count_is_min_of_baseline_and_population():
    records = [_clean_record(i) for i in range(4)]
    # baseline=10 with only 4 clean records → exactly 4 probes.
    out = stratify_and_sample(records, seed=1, clean_baseline_n=10)
    clean_probes = [p for p in out.probes if "clean" in p["strata"]]
    assert len(clean_probes) == 4
    # baseline=2 → exactly 2.
    out = stratify_and_sample(records, seed=1, clean_baseline_n=2)
    clean_probes = [p for p in out.probes if "clean" in p["strata"]]
    assert len(clean_probes) == 2
    # baseline=0 → no clean probes.
    out = stratify_and_sample(records, seed=1, clean_baseline_n=0)
    clean_probes = [p for p in out.probes if "clean" in p["strata"]]
    assert len(clean_probes) == 0


# ── determinism ──────────────────────────────────────────────────────


def test_sampler_same_seed_same_probes():
    """Same seed → same probe indices, in the same order."""
    records = (_clean_record(i) for i in range(20))  # 20 clean
    records = list(records)
    out1 = stratify_and_sample(records, seed=1337, clean_baseline_n=5)
    out2 = stratify_and_sample(records, seed=1337, clean_baseline_n=5)
    assert [p["index"] for p in out1.probes] == [p["index"] for p in out2.probes]
    assert [p["strata"] for p in out1.probes] == [p["strata"] for p in out2.probes]


def test_sampler_different_seed_may_differ():
    """Two different seeds can produce different probe sets (the spec
    only requires same-seed-same-probe, not different-seed-different;
    we assert MAY, not WILL, so this is robust to random.Random's choice
    for these particular sizes — we test the more meaningful same-seed
    determinism separately above)."""
    records = [_clean_record(i) for i in range(50)]
    out_a = stratify_and_sample(records, seed=1, clean_baseline_n=10)
    out_b = stratify_and_sample(records, seed=2, clean_baseline_n=10)
    a_indexes = [p["index"] for p in out_a.probes]
    b_indexes = [p["index"] for p in out_b.probes]
    # With 50 records and 10 picks, random collision is unlikely but not
    # impossible; sanity-check at least the determinism property in
    # places where it matters.  We just verify both runs succeeded.
    assert len(a_indexes) == 10
    assert len(b_indexes) == 10


# ── problem_cap ──────────────────────────────────────────────────────


def test_sampler_problem_cap_limits_per_stratum_with_seeded_rng():
    """Each non-clean stratum is capped at problem_cap (drawn with seeded
    RNG); the final probe list is the union across strata."""
    records: list[RunRecord] = []
    records.extend(_error_record(i)        for i in range(8))  # 8 build_error
    records.extend(_gate_rejected_record(i) for i in range(8)) # 8 gate_rejected
    records.extend(_clean_record(i)         for i in range(8)) # 8 clean
    out = stratify_and_sample(
        records, seed=1337, clean_baseline_n=0, problem_cap=3,
    )
    # Up to 3 build_error + up to 3 gate_rejected = up to 6 probes (no
    # overlap because errors don't also have gate_passed=False here).
    assert len(out.probes) <= 6
    assert len(out.probes) >= 1  # at least one from each stratum cap
    # Per-stratum cap of 3 — each stratum contributes at most 3.
    build_error_probes = [p for p in out.probes if "build_error" in p["strata"]]
    gate_probes = [p for p in out.probes if "gate_rejected" in p["strata"]]
    assert len(build_error_probes) <= 3
    assert len(gate_probes) <= 3


def test_sampler_problem_cap_deterministic_with_seed():
    """Same seed + same problem_cap → same probe set."""
    records = [_error_record(i) for i in range(10)] + [_clean_record(i) for i in range(10)]
    out1 = stratify_and_sample(records, seed=99, clean_baseline_n=2, problem_cap=4)
    out2 = stratify_and_sample(records, seed=99, clean_baseline_n=2, problem_cap=4)
    assert [p["index"] for p in out1.probes] == [p["index"] for p in out2.probes]


# ── stratum_sizes reflects POPULATION, not sample ────────────────────


def test_stratum_sizes_reflect_full_population_not_sample():
    """stratum_sizes is the population counts per stratum (NOT the
    sampled/capped counts). All 8 errors must appear in 'build_error'."""
    records = [_error_record(i) for i in range(8)] + [_clean_record(i) for i in range(4)]
    out = stratify_and_sample(records, seed=1, clean_baseline_n=2, problem_cap=2)
    assert out.stratum_sizes["build_error"] == 8
    assert out.stratum_sizes["clean"] == 4


# ── estimate_clean_rate pure math ────────────────────────────────────


def test_estimate_clean_rate_basic_projection():
    """8/10 sampled clean probes OK on a clean population of 100 →
    sample_pass_rate=0.8, projected_clean_ok=80."""
    out = estimate_clean_rate(clean_pass=8, clean_sampled=10, clean_size=100)
    assert out["sample_pass_rate"] == pytest.approx(0.8)
    assert out["projected_clean_ok"] == 80
    assert out["clean_size"] == 100


def test_estimate_clean_rate_zero_sampled_safe():
    """clean_sampled=0 → sample_pass_rate=0.0, projected=0 (no division by zero)."""
    out = estimate_clean_rate(clean_pass=0, clean_sampled=0, clean_size=42)
    assert out["sample_pass_rate"] == 0.0
    assert out["projected_clean_ok"] == 0
    assert out["clean_size"] == 42


def test_estimate_clean_rate_dict_keys():
    """The estimator returns the three named keys."""
    out = estimate_clean_rate(clean_pass=1, clean_sampled=2, clean_size=10)
    assert set(out.keys()) >= {"sample_pass_rate", "projected_clean_ok", "clean_size"}


# ── Severity-weighted sampler (slice 2) ──────────────────────────────────
# SIGNAL_SEVERITY maps each signal tag to "high" or "low".  A record's
# tier is "high" if ANY tag is high; else "low" if any low tag; else
# "clean".  The new low_severity_cap parameter caps the low-tier
# records; high-tier are always included.


def _decision_fired_record(i: int) -> RunRecord:
    """A record whose ONLY signal is decision_fired (low-tier).  Uses the
    benign material.family_defaulted — exactly the live-run-blame case
    the design doc calls out (15 of 47 records bloomed the probe set)."""
    return _rec(
        request=f"wooden table {i}",
        decisions=[{"code": "material.family_defaulted", "stage": "planner"}],
        spec={
            "asset_id": "table", "generator": "table", "material": "worn_oak",
            "age": 0.15,
            "params": {
                "top_width": 1.2, "top_depth": 0.8, "top_thickness": 0.06,
                "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
            },
        },
        gate_passed=True,
    )


def test_sampler_severity_low_capped_at_low_severity_cap_high_all_in_clean_intact():
    """20 low-tier decision_fired + 3 high-tier gate_rejected + 30 clean,
    low_severity_cap=8, clean_baseline_n=10:
      - all 3 high-tier included
      - exactly 8 low-tier included (seeded-sampled from 20)
      - exactly 10 clean baseline
      - stratum_sizes reflect the FULL population.
    """
    recs: list[RunRecord] = []
    recs.extend(_decision_fired_record(i) for i in range(20))
    recs.extend(_gate_rejected_record(i + 20) for i in range(3))
    recs.extend(_clean_record(i + 23) for i in range(30))

    out = stratify_and_sample(
        recs, seed=1337, clean_baseline_n=10, low_severity_cap=8,
    )

    high_probes  = [p for p in out.probes if p["strata"] == ["gate_rejected"]]
    low_probes   = [p for p in out.probes if "decision_fired" in p["strata"]]
    clean_probes = [p for p in out.probes if p["strata"] == ["clean"]]

    assert len(high_probes) == 3,   f"expected 3 high-tier probes; got {len(high_probes)}"
    assert len(low_probes) == 8,    f"expected 8 low-tier probes; got {len(low_probes)}"
    assert len(clean_probes) == 10, f"expected 10 clean probes; got {len(clean_probes)}"
    assert len(out.probes) == 21

    for p in high_probes:
        assert "high-tier" in p["reason"], p["reason"]
    for p in low_probes:
        assert "low-tier-sampled" in p["reason"], p["reason"]
    for p in clean_probes:
        assert "clean-baseline" in p["reason"], p["reason"]

    assert out.stratum_sizes["decision_fired"] == 20
    assert out.stratum_sizes["gate_rejected"] == 3
    assert out.stratum_sizes["clean"] == 30


def test_sampler_severity_deterministic_by_seed():
    """Same seed → identical probe set when low_severity_cap kicks in."""
    recs = [_decision_fired_record(i) for i in range(20)] + [_clean_record(99)]
    out1 = stratify_and_sample(recs, seed=99, clean_baseline_n=0, low_severity_cap=5)
    out2 = stratify_and_sample(recs, seed=99, clean_baseline_n=0, low_severity_cap=5)
    assert [p["index"] for p in out1.probes] == [p["index"] for p in out2.probes]
    assert [p["strata"] for p in out1.probes] == [p["strata"] for p in out2.probes]


def test_sampler_severity_low_below_cap_keeps_all_low_records():
    """When low-tier population ≤ low_severity_cap, every low-tier
    record is included (no rng.sample draw needed)."""
    recs = [_decision_fired_record(i) for i in range(5)] + [_clean_record(99)]
    out = stratify_and_sample(recs, seed=1, clean_baseline_n=0, low_severity_cap=8)
    low_probes = [p for p in out.probes if "decision_fired" in p["strata"]]
    assert len(low_probes) == 5


def test_sampler_severity_default_low_severity_cap_is_8():
    """low_severity_cap defaults to 8 (per design spec)."""
    recs = [_decision_fired_record(i) for i in range(20)]
    out = stratify_and_sample(recs, seed=42, clean_baseline_n=0)  # no kwarg
    assert len(out.probes) == 8


def test_sampler_severity_high_included_regardless_of_cap():
    """High-tier records are NEVER pruned by low_severity_cap."""
    recs = (
        [_decision_fired_record(i) for i in range(20)]
        + [_gate_rejected_record(i + 20) for i in range(5)]
    )
    out = stratify_and_sample(recs, seed=42, clean_baseline_n=0, low_severity_cap=8)
    high_probes = [p for p in out.probes if "gate_rejected" in p["strata"]]
    assert len(high_probes) == 5


def test_sampler_severity_record_tier_helper():
    """record_tier boxes a tag set into high/low/clean."""
    from eval.signals import record_tier
    assert record_tier({"clean"}) == "clean"
    assert record_tier(set()) == "clean"
    assert record_tier({"decision_fired"}) == "low"
    assert record_tier({"build_error"}) == "high"
    assert record_tier({"gate_rejected", "decision_fired"}) == "high"  # high wins
    assert record_tier({"size_mismatch"}) == "high"
    assert record_tier({"material_conflict"}) == "high"
    assert record_tier({"age_mismatch"}) == "high"


def test_sampler_severity_signal_severity_public_dict():
    """SIGNAL_SEVERITY is a public deterministic map used by both the
    sampler and the regression tests."""
    from eval.signals import SIGNAL_SEVERITY
    assert SIGNAL_SEVERITY["build_error"]       == "high"
    assert SIGNAL_SEVERITY["gate_rejected"]     == "high"
    assert SIGNAL_SEVERITY["size_mismatch"]     == "high"
    assert SIGNAL_SEVERITY["material_mismatch"] == "high"
    assert SIGNAL_SEVERITY["material_conflict"] == "high"
    assert SIGNAL_SEVERITY["age_mismatch"]      == "high"
    assert SIGNAL_SEVERITY["decision_fired"]    == "low"
