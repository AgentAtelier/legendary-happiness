"""TDD tests for foundry.eval.signals — objective signal layer.

``compute_signals(record)`` is a pure function returning a set of objective
tags for a RunRecord: build_error, gate_rejected, decision_fired,
size_mismatch, material_mismatch (or 'clean' when none apply).

Tests construct synthetic RunRecords directly — no live pipeline.
"""

from __future__ import annotations

import pytest

from eval.harness import RunRecord


# ── helpers: build a synthetic RunRecord ──────────────────────────────


def _make_record(
    request: str = "a table",
    spec: dict | None = None,
    decisions: list[dict] | None = None,
    gate_passed: bool | None = None,
    gate_reasons: list[str] | None = None,
    built: bool = False,
    error: str | None = None,
    glb_path: str | None = None,
) -> RunRecord:
    return RunRecord(
        request=request,
        spec=spec,
        decisions=list(decisions or []),
        gate_passed=gate_passed,
        gate_reasons=list(gate_reasons or []),
        built=built,
        error=error,
        glb_path=glb_path,
        seconds=0.01,
    )


def _cabinet_spec(height: float, width: float = 0.8, depth: float = 0.5) -> dict:
    """Build a cabinet spec with the given height (other params mid-range)."""
    return {
        "asset_id": "cabinet",
        "generator": "cabinet",
        "material": "worn_oak",
        "age": 0.15,
        "params": {
            "width": width,
            "depth": depth,
            "height": height,
            "panel_thickness": 0.04,
            "base_height": 0.08,
        },
    }


# ── Test cases ────────────────────────────────────────────────────────


def test_signals_gate_rejected_flag():
    from eval.signals import compute_signals
    r = _make_record(
        request="a table",
        spec=None,
        gate_passed=False,
        gate_reasons=["polygon budget exceeded"],
        built=True,
    )
    tags = compute_signals(r)
    assert "gate_rejected" in tags


def test_signals_build_error_flag():
    from eval.signals import compute_signals
    r = _make_record(
        request="a table",
        spec=None,
        error="RuntimeError('boom')",
    )
    tags = compute_signals(r)
    assert "build_error" in tags


def test_signals_decision_fired_flag():
    from eval.signals import compute_signals
    r = _make_record(
        request="a table",
        spec={"generator": "table"},
        decisions=[{"code": "material.family_defaulted", "stage": "planner"}],
    )
    tags = compute_signals(r)
    assert "decision_fired" in tags


def test_signals_clean_record():
    """A record with no error, gate_passed True, no decisions, no
    size/material mismatch → 'clean'."""
    from compiler import PARAM_RANGES
    from eval.signals import compute_signals
    # Pick a request that has no size word and no material keyword, and
    # build a mid-range spec.
    lo, hi = PARAM_RANGES["table"]["top_width"]
    width = (lo + hi) / 2.0
    lo, hi = PARAM_RANGES["table"]["leg_height"]
    leg_h = (lo + hi) / 2.0
    spec = {
        "asset_id": "table",
        "generator": "table",
        "material": "worn_oak",
        "age": 0.15,
        "params": {
            "top_width": width,
            "top_depth": 0.8,
            "top_thickness": 0.06,
            "leg_height": leg_h,
            "leg_radius": 0.05,
            "leg_inset": 0.1,
        },
    }
    r = _make_record(
        request="a plain coffee table",
        spec=spec,
        gate_passed=True,
        built=True,
    )
    tags = compute_signals(r)
    assert tags == {"clean"}


def test_signals_size_mismatch_tall_cabinet_at_low_end():
    """'a tall cabinet' whose height is in the BOTTOM 20% of the cabinet
    height range → size_mismatch."""
    from compiler import PARAM_RANGES
    from eval.signals import compute_signals
    lo, hi = PARAM_RANGES["cabinet"]["height"]
    # Make height sit firmly at the low end (10% into the range).
    low_height = lo + 0.10 * (hi - lo)
    spec = _cabinet_spec(height=low_height)
    r = _make_record(request="a tall cabinet", spec=spec, gate_passed=True)
    tags = compute_signals(r)
    assert "size_mismatch" in tags


def test_signals_no_size_mismatch_when_size_matches_direction():
    """'a tall cabinet' with a height near the HIGH end → NOT size_mismatch."""
    from compiler import PARAM_RANGES
    from eval.signals import compute_signals
    lo, hi = PARAM_RANGES["cabinet"]["height"]
    high_height = hi - 0.10 * (hi - lo)
    spec = _cabinet_spec(height=high_height)
    r = _make_record(request="a tall cabinet", spec=spec, gate_passed=True)
    tags = compute_signals(r)
    assert "size_mismatch" not in tags


def test_signals_size_mismatch_wide_table_at_low_width():
    """'a wide table' whose top_width is in the BOTTOM 20% → size_mismatch."""
    from compiler import PARAM_RANGES
    from eval.signals import compute_signals
    lo, hi = PARAM_RANGES["table"]["top_width"]
    narrow_width = lo + 0.10 * (hi - lo)
    spec = {
        "asset_id": "table",
        "generator": "table",
        "material": "worn_oak",
        "age": 0.15,
        "params": {
            "top_width": narrow_width,
            "top_depth": 0.8,
            "top_thickness": 0.06,
            "leg_height": 0.65,
            "leg_radius": 0.05,
            "leg_inset": 0.1,
        },
    }
    r = _make_record(request="a wide table", spec=spec, gate_passed=True)
    tags = compute_signals(r)
    assert "size_mismatch" in tags


def test_signals_size_mismatch_low_cabinet_at_top_height():
    """'a low cabinet' whose height is in the TOP 20% → size_mismatch
    (low expects low; spec is at opposite / top end)."""
    from compiler import PARAM_RANGES
    from eval.signals import compute_signals
    lo, hi = PARAM_RANGES["cabinet"]["height"]
    high_height = hi - 0.10 * (hi - lo)
    spec = _cabinet_spec(height=high_height)
    r = _make_record(request="a low cabinet", spec=spec, gate_passed=True)
    tags = compute_signals(r)
    assert "size_mismatch" in tags


def test_signals_no_size_mismatch_without_spec():
    """A request with a size word but no spec → no size_mismatch flag
    (nothing to compare)."""
    from eval.signals import compute_signals
    r = _make_record(request="a tall table", spec=None, error="planner crashed")
    tags = compute_signals(r)
    assert "size_mismatch" not in tags


def test_signals_material_mismatch_oak_table_wrong_material():
    """'an oak table' with material=wrought_iron → material_mismatch."""
    from eval.signals import compute_signals
    spec = {
        "asset_id": "table",
        "generator": "table",
        "material": "wrought_iron",  # wrong; oak expects worn_oak
        "age": 0.15,
        "params": {
            "top_width": 1.2, "top_depth": 0.8, "top_thickness": 0.06,
            "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
        },
    }
    r = _make_record(request="an oak table", spec=spec, gate_passed=True)
    tags = compute_signals(r)
    assert "material_mismatch" in tags


def test_signals_no_material_mismatch_when_resolver_agrees():
    """'an oak table' with material=worn_oak → no material_mismatch."""
    from eval.signals import compute_signals
    spec = {
        "asset_id": "table",
        "generator": "table",
        "material": "worn_oak",
        "age": 0.15,
        "params": {
            "top_width": 1.2, "top_depth": 0.8, "top_thickness": 0.06,
            "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
        },
    }
    r = _make_record(request="an oak table", spec=spec, gate_passed=True)
    tags = compute_signals(r)
    assert "material_mismatch" not in tags


def test_signals_no_material_mismatch_without_spec():
    """Material keyword in request but no spec → no flag (nothing to compare)."""
    from eval.signals import compute_signals
    r = _make_record(request="an oak table", spec=None, error="planner crashed")
    tags = compute_signals(r)
    assert "material_mismatch" not in tags


def test_decision_codes_returns_codes_of_fired_decisions():
    """decision_codes() returns a list of the codes from record.decisions."""
    from eval.signals import decision_codes
    r = _make_record(
        request="a table",
        decisions=[
            {"code": "material.family_defaulted", "stage": "planner"},
            {"code": "material.unspecified_defaulted", "stage": "planner"},
        ],
    )
    codes = decision_codes(r)
    assert sorted(codes) == [
        "material.family_defaulted",
        "material.unspecified_defaulted",
    ]


def test_signals_combined_tags_supported():
    """A record can carry multiple tags at once — e.g. error + size."""
    from compiler import PARAM_RANGES
    from eval.signals import compute_signals
    lo, hi = PARAM_RANGES["cabinet"]["height"]
    low_height = lo + 0.05 * (hi - lo)
    spec = _cabinet_spec(height=low_height)
    r = _make_record(
        request="a tall cabinet",
        spec=spec,
        error="RuntimeError('late failure')",
    )
    tags = compute_signals(r)
    assert "build_error" in tags


def test_signals_full_table_layout_no_words_no_material():
    """A request without size words or material keywords + valid mid-range
    cabinet spec → clean (just 'clean')."""
    from compiler import PARAM_RANGES
    from eval.signals import compute_signals
    lo, hi = PARAM_RANGES["cabinet"]["height"]
    mid_height = (lo + hi) / 2.0
    spec = _cabinet_spec(height=mid_height)
    # request has no size word (not "tall", "low", etc.) and no material.
    r = _make_record(request="a plain storage cabinet", spec=spec, gate_passed=True)
    tags = compute_signals(r)
    assert tags == {"clean"}


# ── size_mismatch_detail (Task 4 helper) ──────────────────────────────


def test_size_mismatch_detail_returns_none_for_clean_request():
    """A request with no size word → detail is None."""
    from eval.signals import size_mismatch_detail
    spec = _cabinet_spec(height=1.3)
    assert size_mismatch_detail("a plain cabinet", spec) is None


def test_size_mismatch_detail_returns_dict_with_named_fields():
    """When a mismatch fires, the dict has the named fields (per Task 4)."""
    from compiler import PARAM_RANGES
    from eval.signals import size_mismatch_detail
    lo, hi = PARAM_RANGES["cabinet"]["height"]
    low_height = lo + 0.05 * (hi - lo)
    spec = _cabinet_spec(height=low_height)
    detail = size_mismatch_detail("a tall cabinet", spec)
    assert detail is not None
    assert detail["word"] == "tall"
    assert detail["expected_direction"] == "high"
    assert detail["dimension"] == "height"
    assert detail["generator"] == "cabinet"
    assert detail["value"] == pytest.approx(low_height)
    assert detail["range"] == [lo, hi]


def test_size_mismatch_detail_low_word_at_top_returns_dict():
    """A 'low' cabinet at the top extreme → detail with word='low'."""
    from compiler import PARAM_RANGES
    from eval.signals import size_mismatch_detail
    lo, hi = PARAM_RANGES["cabinet"]["height"]
    high_height = hi - 0.05 * (hi - lo)
    spec = _cabinet_spec(height=high_height)
    detail = size_mismatch_detail("a low cabinet", spec)
    assert detail is not None
    assert detail["word"] == "low"
    assert detail["expected_direction"] == "low"
    assert detail["dimension"] == "height"


def test_size_mismatch_detail_returns_none_when_value_agrees():
    """A 'tall' cabinet whose height sits at the high end → no mismatch."""
    from compiler import PARAM_RANGES
    from eval.signals import size_mismatch_detail
    lo, hi = PARAM_RANGES["cabinet"]["height"]
    high_height = hi - 0.05 * (hi - lo)
    spec = _cabinet_spec(height=high_height)
    assert size_mismatch_detail("a tall cabinet", spec) is None


def test_size_mismatch_detail_no_spec_returns_none():
    from eval.signals import size_mismatch_detail
    assert size_mismatch_detail("a tall cabinet", None) is None


# ── material_conflict (slice 2) ─────────────────────────────────
# material_conflict fires when the request's matched material cues
# span MORE THAN ONE distinct family (e.g. stone + wood).  Same-family
# multi-cue (oak + walnut → both wood) is NOT a conflict.  Single
# or no cue is also NOT a conflict.


def _table_spec_ok(material: str = "worn_oak", age: float = 0.15) -> dict:
    """A table spec at mid-range, with explicit material/age so tests can
    vary them WITHOUT triggering material_mismatch or age_mismatch."""
    return {
        "asset_id": "table",
        "generator": "table",
        "material": material,
        "age": age,
        "params": {
            "top_width": 1.2, "top_depth": 0.8, "top_thickness": 0.06,
            "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
        },
    }


def test_signals_material_conflict_stone_wood_fires():
    """'a stone-look wooden cabinet' spans {stone, wood} → material_conflict."""
    from eval.signals import compute_signals
    rec = _make_record(
        request="a stone-look wooden cabinet",
        spec={
            "asset_id": "cabinet", "generator": "cabinet", "material": "worn_oak",
            "age": 0.15,
            "params": {
                "width": 0.8, "depth": 0.5, "height": 1.3,
                "panel_thickness": 0.04, "base_height": 0.08,
            },
        },
        gate_passed=True,
    )
    tags = compute_signals(rec)
    assert "material_conflict" in tags


def test_signals_no_material_conflict_oak_walnut_same_family():
    """oak + walnut both map to family=wood → NOT a conflict."""
    from eval.signals import compute_signals
    rec = _make_record(
        request="an oak walnut table",
        spec=_table_spec_ok(material="worn_oak"),
        gate_passed=True,
    )
    tags = compute_signals(rec)
    assert "material_conflict" not in tags


def test_signals_no_material_conflict_single_material():
    """A single family keyword → NOT a conflict."""
    from eval.signals import compute_signals
    rec = _make_record(
        request="a wooden table",
        spec=_table_spec_ok(material="worn_oak"),
        gate_passed=True,
    )
    tags = compute_signals(rec)
    assert "material_conflict" not in tags


def test_signals_no_material_conflict_no_keywords():
    """A request void of any material keyword → NOT a conflict."""
    from eval.signals import compute_signals
    rec = _make_record(
        request="a plain storage cabinet",
        spec={
            "asset_id": "cabinet", "generator": "cabinet", "material": "worn_oak",
            "age": 0.15,
            "params": {
                "width": 0.8, "depth": 0.5, "height": 1.3,
                "panel_thickness": 0.04, "base_height": 0.08,
            },
        },
        gate_passed=True,
    )
    tags = compute_signals(rec)
    assert "material_conflict" not in tags


def test_signals_material_conflict_two_specific_keywords_two_families():
    """'oak' (specific → wood) + 'iron' (specific → metal) span two families."""
    from eval.signals import compute_signals
    rec = _make_record(
        request="an oak iron table",
        spec=_table_spec_ok(material="worn_oak"),
        gate_passed=True,
    )
    tags = compute_signals(rec)
    assert "material_conflict" in tags
