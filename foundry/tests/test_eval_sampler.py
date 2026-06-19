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

from typing import List

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
    records: List[RunRecord] = []
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
    records: List[RunRecord] = []
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
