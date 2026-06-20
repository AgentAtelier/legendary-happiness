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


# ── age_mismatch (slice 2) ────────────────────────────────────────
# Age-appropriateness: deterministic wear lexicons split **at age 0.4**:
#   - request has AGED word but spec age < 0.4          → age_mismatch
#   - request has NEW  word but spec age >= 0.4         → age_mismatch
#   - request has NO   wear word but spec age >= 0.4    → age_mismatch
#
# "vintage" is AGED — so "a vintage cabinet" at age 0.75 must NOT flag
# (the live-run case that prompted the signal).


def test_signals_age_mismatch_old_chair_at_low_age_fires():
    """'an old chair' age=0.15 (AGER + low age) → age_mismatch."""
    from eval.signals import compute_signals
    rec = _make_record(
        request="an old chair",
        spec={
            "asset_id": "chair", "generator": "chair", "material": "worn_oak",
            "age": 0.15,
            "params": {"seat_width": 0.45},
        },
        gate_passed=True,
    )
    tags = compute_signals(rec)
    assert "age_mismatch" in tags


def test_signals_age_mismatch_new_chair_at_high_age_fires():
    """'a new chair' age=0.8 (NEW + high age) → age_mismatch."""
    from eval.signals import compute_signals
    rec = _make_record(
        request="a new chair",
        spec={
            "asset_id": "chair", "generator": "chair", "material": "worn_oak",
            "age": 0.8,
            "params": {"seat_width": 0.45},
        },
        gate_passed=True,
    )
    tags = compute_signals(rec)
    assert "age_mismatch" in tags


def test_signals_age_mismatch_vintage_cabinet_at_0_75_does_NOT_fire():
    """Live-run case: vintage (AGED) at age 0.75 must NOT flag (consistent)."""
    from eval.signals import compute_signals
    rec = _make_record(
        request="a vintage cabinet",
        spec={
            "asset_id": "cabinet", "generator": "cabinet", "material": "worn_oak",
            "age": 0.75,
            "params": {
                "width": 0.8, "depth": 0.5, "height": 1.3,
                "panel_thickness": 0.04, "base_height": 0.08,
            },
        },
        gate_passed=True,
    )
    tags = compute_signals(rec)
    assert "age_mismatch" not in tags


def test_signals_age_mismatch_old_chair_at_high_age_does_NOT_fire():
    """'an old chair' age=0.85 → consistent (AGED + high age). No flag."""
    from eval.signals import compute_signals
    rec = _make_record(
        request="an old chair",
        spec={
            "asset_id": "chair", "generator": "chair", "material": "worn_oak",
            "age": 0.85,
            "params": {"seat_width": 0.45},
        },
        gate_passed=True,
    )
    tags = compute_signals(rec)
    assert "age_mismatch" not in tags


def test_signals_age_mismatch_neutral_request_at_high_age_fires():
    """No wear word in request, but spec age=0.7 ≥ 0.4 → age_mismatch
    (regression guard for the few-shot age fix)."""
    from eval.signals import compute_signals
    rec = _make_record(
        request="a plain table",
        spec={
            "asset_id": "table", "generator": "table", "material": "worn_oak",
            "age": 0.7,
            "params": {
                "top_width": 1.2, "top_depth": 0.8, "top_thickness": 0.06,
                "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
            },
        },
        gate_passed=True,
    )
    tags = compute_signals(rec)
    assert "age_mismatch" in tags


def test_signals_age_mismatch_neutral_request_at_low_age_does_NOT_fire():
    """Aged implied by low age when no wear word is present — that IS the
    intent of the few-shot fix; a low age with neutral request is
    consistent (no flag)."""
    from eval.signals import compute_signals
    rec = _make_record(
        request="a plain table",
        spec=_table_spec_ok(age=0.15),
        gate_passed=True,
    )
    tags = compute_signals(rec)
    assert "age_mismatch" not in tags


def test_signals_age_mismatch_brand_new_with_hyphen_at_high_age_fires():
    """'brand-new' hyphen form — NEW at age=0.8 → age_mismatch."""
    from eval.signals import compute_signals
    rec = _make_record(
        request="a brand-new cabinet",
        spec={
            "asset_id": "cabinet", "generator": "cabinet", "material": "worn_oak",
            "age": 0.8,
            "params": {
                "width": 0.8, "depth": 0.5, "height": 1.3,
                "panel_thickness": 0.04, "base_height": 0.08,
            },
        },
        gate_passed=True,
    )
    tags = compute_signals(rec)
    assert "age_mismatch" in tags


def test_signals_age_mismatch_brand_new_with_space_at_high_age_fires():
    """'brand new' space form — same as hyphen form per spec."""
    from eval.signals import compute_signals
    rec = _make_record(
        request="a brand new cabinet",
        spec={
            "asset_id": "cabinet", "generator": "cabinet", "material": "worn_oak",
            "age": 0.8,
            "params": {
                "width": 0.8, "depth": 0.5, "height": 1.3,
                "panel_thickness": 0.04, "base_height": 0.08,
            },
        },
        gate_passed=True,
    )
    tags = compute_signals(rec)
    assert "age_mismatch" in tags


def test_signals_age_mismatch_weathered_word_at_low_age_fires():
    """'weathered' is AGED; 'weathered cabinet' age=0.2 → flag."""
    from eval.signals import compute_signals
    rec = _make_record(
        request="a weathered cabinet",
        spec={
            "asset_id": "cabinet", "generator": "cabinet", "material": "worn_oak",
            "age": 0.2,
            "params": {
                "width": 0.8, "depth": 0.5, "height": 1.3,
                "panel_thickness": 0.04, "base_height": 0.08,
            },
        },
        gate_passed=True,
    )
    tags = compute_signals(rec)
    assert "age_mismatch" in tags


# ═══════════════════════════════════════════════════════════════════════
#  P8: quest playability oracle — quest-level signals
# ═══════════════════════════════════════════════════════════════════════

from eval.harness import QuestRecord  # noqa: E402

_QUEST_MANIFEST = [
    {"id": "table_0", "category": "table", "material": "worn_oak",
     "x": 1.0, "y": 0.0, "z": -1.5},
    {"id": "shelf_0", "category": "shelf", "material": "rough_granite",
     "x": -2.0, "y": 0.0, "z": -3.0},
    {"id": "cabinet_0", "category": "cabinet", "material": "wrought_iron",
     "x": 2.5, "y": 0.0, "z": -2.0},
]

_VALID_QUEST_SPEC = {
    "npc_role": "hermit",
    "target_entity": "shelf_0",
    "dialogue": {
        "greet": "Ah, a visitor!",
        "ask": "Find my book.",
        "wrong": "Not my book.",
        "thank": "You found it!",
    },
    "objective": {
        "type": "fetch",
        "target": "shelf_0",
        "giver": "npc",
    },
}


def _make_quest_record(
    room_theme: str = "a hermit's shack",
    quest_spec: dict | None = None,
    decisions: list[dict] | None = None,
    compiled: bool = True,
    scene_path: str | None = None,
    manifest: list[dict] | None = None,
    error: str | None = None,
) -> QuestRecord:
    return QuestRecord(
        room_theme=room_theme,
        quest_spec=quest_spec,
        decisions=list(decisions or []),
        compiled=compiled,
        scene_path=scene_path,
        manifest=manifest or _QUEST_MANIFEST,
        error=error,
        seconds=0.01,
    )


def test_quest_signals_clean():
    """A valid quest record with no issues → 'clean' + informative signals.
    EB-7: room_not_monochrome fires because the manifest has ≥2 materials
    (low-severity, informative)."""
    from eval.signals import compute_quest_signals
    qr = _make_quest_record(quest_spec=_VALID_QUEST_SPEC)
    tags = compute_quest_signals(qr)
    # EB-7: _QUEST_MANIFEST has 3 materials ≠ monochrome
    assert "room_not_monochrome" in tags
    assert "quest_build_error" not in tags
    assert "quest_no_target" not in tags
    assert "quest_no_npc" not in tags


def test_quest_signals_build_error():
    """Error set or compiled=False → quest_build_error."""
    from eval.signals import compute_quest_signals
    qr = _make_quest_record(error="RuntimeError('boom')", compiled=False)
    tags = compute_quest_signals(qr)
    assert "quest_build_error" in tags


def test_quest_signals_dialogue_fallback():
    """Decisions containing a dialogue fallback code → quest_dialogue_fallback."""
    from eval.signals import compute_quest_signals
    qr = _make_quest_record(
        quest_spec=_VALID_QUEST_SPEC,
        decisions=[{"code": "quest.dialogue_fallback", "stage": "planner"}],
    )
    tags = compute_quest_signals(qr)
    assert "quest_dialogue_fallback" in tags


def test_quest_signals_decision_fired():
    """Any decisions → quest_decision_fired."""
    from eval.signals import compute_quest_signals
    qr = _make_quest_record(
        quest_spec=_VALID_QUEST_SPEC,
        decisions=[{"code": "quest.dangling_target", "stage": "planner"}],
    )
    tags = compute_quest_signals(qr)
    assert "quest_decision_fired" in tags


def test_quest_signals_no_target():
    """target_entity not in manifest → quest_no_target."""
    from eval.signals import compute_quest_signals
    bad_spec = dict(_VALID_QUEST_SPEC)
    bad_spec["target_entity"] = "missing_prop"
    qr = _make_quest_record(quest_spec=bad_spec)
    tags = compute_quest_signals(qr)
    assert "quest_no_target" in tags


def test_quest_signals_no_npc():
    """npc_role empty → quest_no_npc."""
    from eval.signals import compute_quest_signals
    bad_spec = dict(_VALID_QUEST_SPEC)
    bad_spec["npc_role"] = ""
    qr = _make_quest_record(quest_spec=bad_spec)
    tags = compute_quest_signals(qr)
    assert "quest_no_npc" in tags


def test_quest_signals_npc_role_missing():
    """npc_role not in spec → quest_no_npc."""
    from eval.signals import compute_quest_signals
    bad_spec = dict(_VALID_QUEST_SPEC)
    del bad_spec["npc_role"]
    qr = _make_quest_record(quest_spec=bad_spec)
    tags = compute_quest_signals(qr)
    assert "quest_no_npc" in tags


def test_quest_signals_unwinnable_wrong_objective():
    """objective.type != 'fetch' → quest_unwinnable."""
    from eval.signals import compute_quest_signals
    bad_spec = dict(_VALID_QUEST_SPEC)
    bad_spec["objective"] = {"type": "talk", "target": "shelf_0", "giver": "npc"}
    qr = _make_quest_record(quest_spec=bad_spec)
    tags = compute_quest_signals(qr)
    assert "quest_unwinnable" in tags


def test_quest_signals_no_spec_returns_clean():
    """No quest_spec at all → only checks what's available (build_error if
    error/not compiled, otherwise clean)."""
    from eval.signals import compute_quest_signals
    qr = _make_quest_record(quest_spec=None, compiled=True)
    tags = compute_quest_signals(qr)
    assert tags == {"clean"}


def test_quest_signals_combined_tags():
    """Multiple issues → multiple tags."""
    from eval.signals import compute_quest_signals
    bad_spec = dict(_VALID_QUEST_SPEC)
    bad_spec["target_entity"] = "missing_prop"
    bad_spec["npc_role"] = ""
    qr = _make_quest_record(
        quest_spec=bad_spec,
        decisions=[{"code": "quest.dialogue_fallback", "stage": "planner"}],
    )
    tags = compute_quest_signals(qr)
    assert "quest_no_target" in tags
    assert "quest_no_npc" in tags
    assert "quest_dialogue_fallback" in tags
    assert "quest_decision_fired" in tags


def test_quest_signals_unwinnable_blocked_by_no_target():
    """When quest_no_target fires, quest_unwinnable does NOT also fire
    (unwinnability is implied; signal only checks when structural prereqs
    are met)."""
    from eval.signals import compute_quest_signals
    bad_spec = dict(_VALID_QUEST_SPEC)
    bad_spec["target_entity"] = "missing_prop"
    bad_spec["objective"] = {"type": "talk"}
    qr = _make_quest_record(quest_spec=bad_spec)
    tags = compute_quest_signals(qr)
    assert "quest_no_target" in tags
    assert "quest_unwinnable" not in tags


def test_quest_decision_codes():
    """quest_decision_codes returns codes from QuestRecord decisions."""
    from eval.signals import quest_decision_codes
    qr = _make_quest_record(
        quest_spec=_VALID_QUEST_SPEC,
        decisions=[
            {"code": "quest.dangling_target", "stage": "planner"},
            {"code": "quest.dialogue_fallback", "stage": "planner"},
        ],
    )
    codes = quest_decision_codes(qr)
    assert sorted(codes) == [
        "quest.dangling_target",
        "quest.dialogue_fallback",
    ]


def test_quest_signals_severity_map():
    """All quest signal tags are in SIGNAL_SEVERITY."""
    from eval.signals import SIGNAL_SEVERITY
    quest_tags = {
        "quest_build_error", "quest_dialogue_fallback",
        "quest_no_target", "quest_no_npc", "quest_unwinnable",
        "quest_decision_fired",
    }
    for tag in quest_tags:
        assert tag in SIGNAL_SEVERITY, f"missing severity for {tag}"


def test_quest_signals_record_tier_with_quest_tags():
    """record_tier correctly classifies quest signal sets."""
    from eval.signals import record_tier
    assert record_tier({"quest_build_error"}) == "high"
    assert record_tier({"quest_no_target"}) == "high"
    assert record_tier({"quest_no_npc"}) == "high"
    assert record_tier({"quest_unwinnable"}) == "high"
    assert record_tier({"quest_dialogue_fallback"}) == "low"
    assert record_tier({"quest_decision_fired"}) == "low"
    assert record_tier({"clean"}) == "clean"
    assert record_tier({"quest_dialogue_fallback", "quest_unwinnable"}) == "high"


# ═══════════════════════════════════════════════════════════════════════
#  P-K: Eval oracle extensions — decor-never-target, room variety,
#       headless-load-clean
# ═══════════════════════════════════════════════════════════════════════

def test_decor_never_target_returns_tag():
    """P-K: When target_entity is a decor item, check_decor_never_target
    returns 'decor_never_target'."""
    from eval.signals import check_decor_never_target
    decor_manifest = [
        {"id": "rug_0", "category": "rug", "material": "worn_oak",
         "x": 0, "y": 0, "z": 0, "decor": True},
        {"id": "table_0", "category": "table", "material": "worn_oak",
         "x": 1, "y": 0, "z": 1, "decor": False},
    ]
    decor_spec = dict(_VALID_QUEST_SPEC)
    decor_spec["target_entity"] = "rug_0"
    qr = _make_quest_record(quest_spec=decor_spec, manifest=decor_manifest)
    assert check_decor_never_target(qr) == "decor_never_target"


def test_decor_never_target_returns_none_for_furniture():
    """P-K: Furniture targets don't trigger decor_never_target."""
    from eval.signals import check_decor_never_target
    qr = _make_quest_record(quest_spec=_VALID_QUEST_SPEC)
    assert check_decor_never_target(qr) is None


def test_decor_never_target_returns_none_without_manifest():
    """P-K: No manifest → no decor check possible → None."""
    from eval.signals import check_decor_never_target
    qr = _make_quest_record(quest_spec=_VALID_QUEST_SPEC, manifest=[])
    assert check_decor_never_target(qr) is None


def test_room_variety_computes_spread():
    """P-K: compute_room_variety returns size/prop-count spread and
    material diversity."""
    from eval.signals import compute_room_variety
    m1 = [{"id": "table_0", "category": "table", "material": "worn_oak"}]
    m2 = [
        {"id": "table_0", "category": "table", "material": "worn_oak"},
        {"id": "chair_0", "category": "chair", "material": "wrought_iron"},
    ]
    r1 = _make_quest_record(room_theme="a shack", manifest=m1)
    r2 = _make_quest_record(room_theme="a shack", manifest=m2)
    result = compute_room_variety([r1, r2])
    assert result["count"] == 2
    assert result["prop_count_spread"] == (1, 2)
    assert result["material_diversity"] == 2
    assert result["distinct"] is True


def test_room_variety_empty_records():
    """P-K: Empty record list → count=0, distinct=False."""
    from eval.signals import compute_room_variety
    result = compute_room_variety([])
    assert result["count"] == 0
    assert result["distinct"] is False


def test_headless_load_clean_detects_script_error():
    """P-K: Stderr with SCRIPT ERROR → False."""
    from eval.signals import check_headless_load_clean
    stderr = "SCRIPT ERROR: Parse Error: Invalid cast.\n  at: GDScript::reload"
    assert check_headless_load_clean(stderr) is False


def test_headless_load_clean_detects_parse_error():
    """P-K: Stderr with Parse Error → False."""
    from eval.signals import check_headless_load_clean
    stderr = " Parse Error: Unexpected token\n"
    assert check_headless_load_clean(stderr) is False


def test_headless_load_clean_detects_failed_to_load():
    """P-K: Stderr with 'Failed to load script' → False."""
    from eval.signals import check_headless_load_clean
    stderr = "ERROR: Failed to load script 'res://scripts/broken.gd'"
    assert check_headless_load_clean(stderr) is False


def test_headless_load_clean_returns_true_for_empty_stderr():
    """P-K: Clean stderr → True."""
    from eval.signals import check_headless_load_clean
    assert check_headless_load_clean("") is True
    assert check_headless_load_clean("Godot Engine v4.3\n") is True


def test_decor_never_target_in_severity_map():
    """P-K: decor_never_target is in SIGNAL_SEVERITY as 'high'."""
    from eval.signals import SIGNAL_SEVERITY
    assert SIGNAL_SEVERITY.get("decor_never_target") == "high"
    assert SIGNAL_SEVERITY.get("headless_not_clean") == "high"


# ═══════════════════════════════════════════════════════════════════════
#  P-E: target-is-carryable + named-in-dialogue signals
# ═══════════════════════════════════════════════════════════════════════

_PE_CARRYABLE_MANIFEST = [
    {"id": "key_0", "category": "key", "material": "wrought_iron",
     "x": 0.5, "y": 0.8, "z": -0.3, "decor": False},
    {"id": "table_0", "category": "table", "material": "worn_oak",
     "x": 1.0, "y": 0.0, "z": -1.5, "decor": False},
]

_PE_CARRYABLE_SPEC_NAMED = {
    "npc_role": "hermit",
    "target_entity": "key_0",
    "dialogue": {
        "greet": "Hello.",
        "ask": "Find my brass key.",
        "wrong": "Not my key.",
        "thank": "You found the key!",
    },
    "objective": {"type": "fetch", "target": "key_0", "giver": "npc"},
}


def test_target_is_carryable_clean_when_carryable_target():
    """P-E: Target is a carryable → no signal."""
    from eval.signals import check_target_is_carryable
    qr = _make_quest_record(
        quest_spec=_PE_CARRYABLE_SPEC_NAMED,
        manifest=_PE_CARRYABLE_MANIFEST,
    )
    assert check_target_is_carryable(qr) is None


def test_target_is_carryable_fires_when_furniture_target():
    """P-E: Carryables exist but target is furniture → target_not_carryable."""
    from eval.signals import check_target_is_carryable
    furniture_spec = dict(_PE_CARRYABLE_SPEC_NAMED)
    furniture_spec["target_entity"] = "table_0"
    qr = _make_quest_record(
        quest_spec=furniture_spec,
        manifest=_PE_CARRYABLE_MANIFEST,
    )
    assert check_target_is_carryable(qr) == "target_not_carryable"


def test_target_is_carryable_clean_when_no_carryables():
    """P-E: No carryables in manifest → signal doesn't fire (pre-P-E room)."""
    from eval.signals import check_target_is_carryable
    qr = _make_quest_record(
        quest_spec=_VALID_QUEST_SPEC,
        manifest=_QUEST_MANIFEST,  # furniture-only manifest
    )
    assert check_target_is_carryable(qr) is None


def test_target_named_in_dialogue_clean_when_category_mentioned():
    """P-E: Dialogue mentions the target category ("key") → clean."""
    from eval.signals import check_target_named_in_dialogue
    qr = _make_quest_record(
        quest_spec=_PE_CARRYABLE_SPEC_NAMED,
        manifest=_PE_CARRYABLE_MANIFEST,
    )
    assert check_target_named_in_dialogue(qr) is None


def test_target_named_in_dialogue_clean_when_adjective_mentioned():
    """P-E: Dialogue mentions the material adjective ("brass") → clean."""
    from eval.signals import check_target_named_in_dialogue
    adj_spec = dict(_PE_CARRYABLE_SPEC_NAMED)
    adj_spec["dialogue"] = {
        "greet": "Hello.",
        "ask": "Find the brass item.",
        "wrong": "Not brass.",
        "thank": "Thanks for the brass.",
    }
    qr = _make_quest_record(quest_spec=adj_spec, manifest=_PE_CARRYABLE_MANIFEST)
    assert check_target_named_in_dialogue(qr) is None


def test_target_named_in_dialogue_fires_when_not_mentioned():
    """P-E: Dialogue never names category or adjective → target_not_named_in_dialogue."""
    from eval.signals import check_target_named_in_dialogue
    unnamed_spec = dict(_PE_CARRYABLE_SPEC_NAMED)
    unnamed_spec["dialogue"] = {
        "greet": "Hello.",
        "ask": "Find my lost item.",
        "wrong": "Not what I need.",
        "thank": "You found it!",
    }
    qr = _make_quest_record(quest_spec=unnamed_spec, manifest=_PE_CARRYABLE_MANIFEST)
    assert check_target_named_in_dialogue(qr) == "target_not_named_in_dialogue"


def test_target_named_in_dialogue_clean_when_no_carryables():
    """P-E: No carryables in manifest → signal doesn't fire."""
    from eval.signals import check_target_named_in_dialogue
    qr = _make_quest_record(
        quest_spec=_VALID_QUEST_SPEC,
        manifest=_QUEST_MANIFEST,
    )
    assert check_target_named_in_dialogue(qr) is None


def test_pe_signals_in_severity_map():
    """P-E: target_not_carryable and target_not_named_in_dialogue are in SIGNAL_SEVERITY."""
    from eval.signals import SIGNAL_SEVERITY
    assert SIGNAL_SEVERITY.get("target_not_carryable") == "high"
    assert SIGNAL_SEVERITY.get("target_not_named_in_dialogue") == "high"


# ═══════════════════════════════════════════════════════════════════════
#  EB-7: Multi-NPC target integrity + material variety signals
# ═══════════════════════════════════════════════════════════════════════


def test_multi_npc_distinct_targets_clean():
    """EB-7: With distinct targets and enough carryables → no signal."""
    from eval.signals import check_multi_npc_distinct_targets
    spec1 = dict(_VALID_QUEST_SPEC)
    spec1["target_entity"] = "key_0"
    spec2 = dict(_VALID_QUEST_SPEC)
    spec2["target_entity"] = "book_0"
    manifest = [
        {"id": "key_0", "category": "key", "material": "wrought_iron"},
        {"id": "book_0", "category": "book", "material": "worn_oak"},
    ]
    qr = _make_quest_record(
        quest_spec=_VALID_QUEST_SPEC, manifest=manifest,
    )
    # Hack: set quest_specs on the record
    qr.quest_specs = [spec1, spec2]
    result = check_multi_npc_distinct_targets(qr, npc_count=2)
    assert result is None


def test_multi_npc_distinct_targets_duplicate_fires():
    """EB-7: Two NPCs sharing the same target → multi_npc_distinct_targets."""
    from eval.signals import check_multi_npc_distinct_targets
    spec1 = dict(_VALID_QUEST_SPEC)
    spec1["target_entity"] = "key_0"
    spec2 = dict(_VALID_QUEST_SPEC)
    spec2["target_entity"] = "key_0"  # same!
    manifest = [
        {"id": "key_0", "category": "key", "material": "wrought_iron"},
        {"id": "book_0", "category": "book", "material": "worn_oak"},
    ]
    qr = _make_quest_record(manifest=manifest)
    qr.quest_specs = [spec1, spec2]
    result = check_multi_npc_distinct_targets(qr, npc_count=2)
    assert result == "multi_npc_distinct_targets"


def test_insufficient_carryables_for_npcs_fires():
    """EB-7: Fewer carryables than npc_count → insufficient_carryables_for_npcs."""
    from eval.signals import check_multi_npc_distinct_targets
    manifest = [
        {"id": "key_0", "category": "key", "material": "wrought_iron"},
        {"id": "table_0", "category": "table", "material": "worn_oak"},
    ]
    qr = _make_quest_record(manifest=manifest)
    result = check_multi_npc_distinct_targets(qr, npc_count=3)
    assert result == "insufficient_carryables_for_npcs"


def test_room_not_monochrome_fires():
    """EB-7: Room with ≥2 non-decor materials → room_not_monochrome."""
    from eval.signals import check_room_not_monochrome
    manifest = [
        {"id": "table_0", "category": "table", "material": "worn_oak"},
        {"id": "shelf_0", "category": "shelf", "material": "rough_granite"},
        {"id": "rug_0", "category": "rug", "material": "linen", "decor": True},
    ]
    qr = _make_quest_record(manifest=manifest)
    result = check_room_not_monochrome(qr)
    assert result == "room_not_monochrome"


def test_room_not_monochrome_monochrome_returns_none():
    """EB-7: Room with 1 non-decor material → None (monochrome)."""
    from eval.signals import check_room_not_monochrome
    manifest = [
        {"id": "table_0", "category": "table", "material": "worn_oak"},
        {"id": "chair_0", "category": "chair", "material": "worn_oak"},
    ]
    qr = _make_quest_record(manifest=manifest)
    result = check_room_not_monochrome(qr)
    assert result is None


def test_fabric_in_fabric_themes_fires():
    """EB-7: Manifest with linen → fabric_in_fabric_themes fires
    regardless of theme (signal confirms fabric actually surfaced)."""
    from eval.signals import check_fabric_in_fabric_themes
    manifest = [
        {"id": "rug_0", "category": "rug", "material": "linen", "decor": True},
        {"id": "table_0", "category": "table", "material": "worn_oak"},
    ]
    qr = _make_quest_record(manifest=manifest, room_theme="a kitchen")
    result = check_fabric_in_fabric_themes(qr, theme="kitchen")
    assert result == "fabric_in_fabric_themes"


def test_fabric_in_fabric_themes_no_fabric_in_manifest_returns_none():
    """EB-7: Manifest without fabric materials → None."""
    from eval.signals import check_fabric_in_fabric_themes
    manifest = [
        {"id": "rug_0", "category": "rug", "material": "worn_oak", "decor": True},
    ]
    qr = _make_quest_record(manifest=manifest, room_theme="a hermit's shack")
    result = check_fabric_in_fabric_themes(qr, theme="hermit")
    assert result is None


def test_eb7_signals_in_severity_map():
    """EB-7: All new signal tags are in SIGNAL_SEVERITY."""
    from eval.signals import SIGNAL_SEVERITY
    assert SIGNAL_SEVERITY.get("multi_npc_distinct_targets") == "high"
    assert SIGNAL_SEVERITY.get("insufficient_carryables_for_npcs") == "high"
    assert SIGNAL_SEVERITY.get("room_not_monochrome") == "low"
    assert SIGNAL_SEVERITY.get("fabric_in_fabric_themes") == "low"


# ── B0: Winnable oracle tests ────────────────────────────────────────

class TestWinnableOracle:
    """B0: Verify the winnable/reachability oracle correctly asserts
    structural winnability and catches deliberately-broken quests."""

    @staticmethod
    def _mock_record(quest_specs, manifest, error=None, compiled=True):
        """Create a minimal mock QuestRecord for oracle testing."""
        class MockRecord:
            pass
        r = MockRecord()
        r.error = error
        r.compiled = compiled
        r.quest_specs = quest_specs
        r.quest_spec = quest_specs[0] if quest_specs else None
        r.manifest = manifest
        r.decisions = []
        r.npc_count = len(quest_specs)
        r.room_theme = "tavern"
        return r

    def test_winnable_oracle_passes_for_valid_quest(self):
        """B0: Oracle returns 'quest_all_npcs_winnable' when every NPC
        has a gettable + deliverable target."""
        from eval.signals import compute_quest_signals

        manifest = [
            {"id": "key_0", "category": "key", "material": "wrought_iron"},
            {"id": "gem_1", "category": "gem", "material": "rough_granite"},
        ]
        specs = [
            {
                "npc_role": "blacksmith",
                "target_entity": "key_0",
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc_0"},
                "npc_id": "npc_0",
            },
            {
                "npc_role": "alchemist",
                "target_entity": "gem_1",
                "objective": {"type": "fetch", "target": "gem_1", "giver": "npc_1"},
                "npc_id": "npc_1",
            },
        ]

        record = self._mock_record(specs, manifest)
        tags = compute_quest_signals(record)

        assert "quest_all_npcs_winnable" in tags, (
            f"Expected quest_all_npcs_winnable in tags for valid 2-NPC quest, got: {tags}"
        )

    def test_oracle_catches_target_not_in_manifest(self):
        """B0: Oracle does NOT return winnable when a target is missing
        from the manifest."""
        from eval.signals import compute_quest_signals

        manifest = [
            {"id": "key_0", "category": "key", "material": "wrought_iron"},
        ]
        specs = [
            {
                "npc_role": "blacksmith",
                "target_entity": "key_0",
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc_0"},
            },
            {
                "npc_role": "alchemist",
                "target_entity": "gem_missing",  # NOT in manifest
                "objective": {"type": "fetch", "target": "gem_missing", "giver": "npc_1"},
            },
        ]

        record = self._mock_record(specs,manifest)
        tags = compute_quest_signals(record)

        assert "quest_all_npcs_winnable" not in tags, (
            f"Expected quest_all_npcs_winnable to be ABSENT when target missing from manifest, got: {tags}"
        )
        assert "quest_no_target" in tags, (
            f"Expected quest_no_target for missing gem_missing, got: {tags}"
        )

    def test_oracle_catches_target_not_carryable(self):
        """B0: Oracle does NOT return winnable when a target is furniture
        (not a carryable)."""
        from eval.signals import compute_quest_signals

        manifest = [
            {"id": "key_0", "category": "key", "material": "wrought_iron"},
            {"id": "table_0", "category": "table", "material": "worn_oak"},
        ]
        specs = [
            {
                "npc_role": "blacksmith",
                "target_entity": "key_0",
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc_0"},
            },
            {
                "npc_role": "alchemist",
                "target_entity": "table_0",  # furniture, not carryable
                "objective": {"type": "fetch", "target": "table_0", "giver": "npc_1"},
            },
        ]

        record = self._mock_record(specs, manifest)
        tags = compute_quest_signals(record)

        assert "quest_all_npcs_winnable" not in tags, (
            f"Expected quest_all_npcs_winnable to be ABSENT when target is furniture, got: {tags}"
        )

    def test_oracle_catches_missing_npc_role(self):
        """B0: Oracle does NOT return winnable when an NPC has no role."""
        from eval.signals import compute_quest_signals

        manifest = [
            {"id": "key_0", "category": "key", "material": "wrought_iron"},
            {"id": "gem_1", "category": "gem", "material": "rough_granite"},
        ]
        specs = [
            {
                "npc_role": "blacksmith",
                "target_entity": "key_0",
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc_0"},
            },
            {
                "npc_role": "",  # empty role
                "target_entity": "gem_1",
                "objective": {"type": "fetch", "target": "gem_1", "giver": "npc_1"},
            },
        ]

        record = self._mock_record(specs, manifest)
        tags = compute_quest_signals(record)

        assert "quest_all_npcs_winnable" not in tags, (
            f"Expected quest_all_npcs_winnable to be ABSENT when NPC has no role, got: {tags}"
        )
    def test_oracle_catches_non_fetch_objective(self):
        """B0: Oracle does NOT return winnable when objective is not fetch."""
        from eval.signals import compute_quest_signals

        manifest = [
            {"id": "key_0", "category": "key", "material": "wrought_iron"},
            {"id": "gem_1", "category": "gem", "material": "rough_granite"},
        ]
        specs = [
            {
                "npc_role": "blacksmith",
                "target_entity": "key_0",
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc_0"},
            },
            {
                "npc_role": "alchemist",
                "target_entity": "gem_1",
                "objective": {"type": "talk", "target": "gem_1", "giver": "npc_1"},
            },
        ]

        record = self._mock_record(specs, manifest)
        tags = compute_quest_signals(record)

        assert "quest_all_npcs_winnable" not in tags, (
            f"Expected quest_all_npcs_winnable to be ABSENT for non-fetch objective, got: {tags}"
        )

    def test_oracle_works_for_single_npc(self):
        """B0: Oracle works for single-NPC quests (backward compat)."""
        from eval.signals import compute_quest_signals

        manifest = [
            {"id": "key_0", "category": "key", "material": "wrought_iron"},
        ]
        specs = [
            {
                "npc_role": "blacksmith",
                "target_entity": "key_0",
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc_0"},
            },
        ]

        record = self._mock_record(specs, manifest)
        tags = compute_quest_signals(record)

        assert "quest_all_npcs_winnable" in tags, (
            f"Expected quest_all_npcs_winnable for valid single-NPC quest, got: {tags}"
        )

