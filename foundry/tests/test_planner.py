"""Tests for the AssetPlanner (Slice 5 + Slice 11 Decision Points).

The deterministic core needs NO live LLM.  All plan() tests pass a
FAKE callable so the pre-pass (material resolver) and post-processing
(param clamping, range defaulting) can be exercised deterministically.

Slice 11: material is no longer qwen's job — the resolver drives it,
and plan() now returns ``(spec, decisions)`` so the resolver's
Decision Points reach the caller.
"""

from __future__ import annotations

import json
import socket

import pytest
from compiler import PARAM_RANGES, compile_spec
from decisions import DecisionPoint
from llm import FoundryLLM, load_grammar, normalize_gbnf
from planner import AssetPlanner

# ── Grammar normalisation tests ────────────────────────────────────


def test_normalize_gbnf_joins_multiline_alternations():
    """Multi-line | alternations are folded onto the rule line."""
    raw = "root ::= \"a\"\n         | \"b\"\n         | \"c\""
    got = normalize_gbnf(raw)
    # All three alternatives should be on one line
    assert "|" in got
    lines = [l for l in got.split("\n") if l.strip()]
    assert len(lines) == 1
    assert "\"a\"" in lines[0]
    assert "\"b\"" in lines[0]
    assert "\"c\"" in lines[0]


def test_normalized_grammar_has_no_line_starting_with_pipe():
    """No line of the normalized grammar starts with |."""
    grammar = load_grammar()
    for i, line in enumerate(grammar.split("\n")):
        stripped = line.strip()
        assert not stripped.startswith("|"), (
            f"Line {i} starts with '|': {line!r}"
        )


def test_normalized_grammar_contains_chair():
    """The normalized grammar contains 'chair' (as a generator value)."""
    grammar = load_grammar()
    assert "chair" in grammar, "grammar should contain 'chair'"


def test_normalize_gbnf_handles_empty_lines_and_comments():
    """Empty lines and comments between a rule and its | continuation are skipped."""
    raw = "root ::= \"x\"\n# comment\n         | \"y\""
    got = normalize_gbnf(raw)
    lines = [l for l in got.split("\n") if l.strip() and not l.lstrip().startswith("#")]
    assert len(lines) == 1
    assert "\"x\"" in lines[0]
    assert "\"y\"" in lines[0]


# ── Prompt tests ──────────────────────────────────────────────────────


def test_build_prompt_contains_request_and_schema():
    planner = AssetPlanner()
    prompt = planner.build_prompt("a low wooden coffee table")
    assert "a low wooden coffee table" in prompt
    assert "top_width" in prompt
    assert "top_depth" in prompt
    assert "top_thickness" in prompt
    assert "leg_height" in prompt
    assert "leg_radius" in prompt
    assert "leg_inset" in prompt


def test_build_prompt_does_not_ask_for_material():
    """Slice 11: material is the resolver's job now — the prompt no longer
    asks qwen to pick a material. Asserts the old instruction is gone."""
    planner = AssetPlanner()
    prompt = planner.build_prompt("a dark walnut table")
    assert "Allowed material values" not in prompt
    assert "wrought_iron" not in prompt, (
        "prompt should no longer carry the materials list — qwen does not pick"
    )
    assert "dark_walnut" not in prompt  # any of the palette ids, really


def test_build_prompt_no_longer_carries_material_section():
    planner = AssetPlanner()
    prompt = planner.build_prompt("a table")
    # No 'Material' line heading anywhere — the resolver drives material now.
    assert "Material" not in prompt
    # ...but the prompt can still discuss 'top_thickness' etc — verify the
    # geometry params survived intact (we didn't accidentally nuke them).
    assert "top_thickness" in prompt


# ── Parse tests ────────────────────────────────────────────────────────


def test_parse_valid_json():
    planner = AssetPlanner()
    raw = """```json
{
  "asset_id": "table",
  "generator": "table",
  "material": "worn_oak",
  "params": {
    "top_width": 1.5,
    "top_depth": 0.8,
    "top_thickness": 0.06,
    "leg_height": 0.65,
    "leg_radius": 0.05,
    "leg_inset": 0.1
  }
}
```"""
    spec = planner.parse(raw)
    assert spec["asset_id"] == "table"
    assert spec["generator"] == "table"
    assert spec["material"] == "worn_oak"
    assert spec["params"]["top_width"] == 1.5
    assert spec["params"]["leg_height"] == 0.65


def test_parse_json_without_fences():
    planner = AssetPlanner()
    raw = '{"asset_id":"table","generator":"table","material":"worn_oak","params":{"top_width":1.2,"top_depth":0.7,"top_thickness":0.05,"leg_height":0.55,"leg_radius":0.04,"leg_inset":0.08}}'
    spec = planner.parse(raw)
    assert spec["asset_id"] == "table"
    assert spec["params"]["top_width"] == 1.2


def test_parse_think_tags_stripped():
    planner = AssetPlanner()
    # Literal angle-bracketed  tags so the regex in parse() exercises stripping.
    raw = (
        "<think>I should output a table spec</think>\n"
        '{"asset_id":"table","generator":"table","material":"worn_oak","params":{"top_width":1.0,"top_depth":0.5,"top_thickness":0.04,'
        '"leg_height":0.5,"leg_radius":0.03,"leg_inset":0.05}}'
    )
    spec = planner.parse(raw)
    assert spec["asset_id"] == "table"


def test_parse_empty_text_raises():
    planner = AssetPlanner()
    with pytest.raises(ValueError, match="Empty"):
        planner.parse("")


def test_parse_no_json_raises():
    planner = AssetPlanner()
    with pytest.raises(ValueError, match="No JSON"):
        planner.parse("hello world")


# ── plan() helper + fake llms ────────────────────────────────────────


def _fake_llm_valid(prompt: str, grammar: str | None) -> str:
    return json.dumps({
        "asset_id": "table",
        "generator": "table",
        # NOTE: no "material" key — the resolver drives spec["material"].
        "params": {
            "top_width": 1.5,
            "top_depth": 0.8,
            "top_thickness": 0.06,
            "leg_height": 0.65,
            "leg_radius": 0.05,
            "leg_inset": 0.1,
        },
    })


def _fake_llm_out_of_range(prompt: str, grammar: str | None) -> str:
    """Returns params that are WAY outside the allowed ranges."""
    return json.dumps({
        "asset_id": "table",
        "generator": "table",
        "params": {
            "top_width": 999.0,
            "top_depth": -5.0,
            "top_thickness": 0.001,
            "leg_height": 5.0,
            "leg_radius": 0.001,
            "leg_inset": 999.0,
        },
    })


def _fake_llm_missing_params(prompt: str, grammar: str | None) -> str:
    """Returns a spec missing some params entirely."""
    return json.dumps({
        "asset_id": "table",
        "generator": "table",
        "params": {
            "top_width": 1.5,
            # missing top_depth, top_thickness, etc.
        },
    })


def _fake_llm_non_numeric_param(prompt: str, grammar: str | None) -> str:
    """A spec where one param is a string instead of a number."""
    return json.dumps({
        "asset_id": "table",
        "generator": "table",
        "params": {
            "top_width": "hello",
            "top_depth": 0.8,
            "top_thickness": 0.06,
            "leg_height": 0.65,
            "leg_radius": 0.05,
            "leg_inset": 0.1,
        },
    })


# ── plan() tests with FAKE llm ───────────────────────────────────────


def test_plan_with_valid_spec_preserved():
    """A valid spec passes compile_spec unchanged (except float coercion)."""
    planner = AssetPlanner()
    # Request has no specific material keyword, no family keyword → resolver
    # returns worn_oak + unspecified_defaulted.
    spec, _ = planner.plan("a table", _fake_llm_valid)
    assert spec["generator"] == "table"
    assert spec["material"] == "worn_oak"
    assert spec["params"]["top_width"] == 1.5
    assert spec["params"]["top_depth"] == 0.8
    compile_spec(spec)


def test_plan_with_non_numeric_param_defaults_to_midpoint():
    """A non-numeric param value (string) is replaced with the range midpoint."""
    planner = AssetPlanner()
    spec, _ = planner.plan("a table", _fake_llm_non_numeric_param)
    ranges = PARAM_RANGES["table"]
    lo, hi = ranges["top_width"]
    assert spec["params"]["top_width"] == pytest.approx((lo + hi) / 2.0)
    assert spec["params"]["top_depth"] == 0.8
    compile_spec(spec)


def test_plan_with_out_of_range_params_clamped():
    """Out-of-range params are clamped and the result passes compile_spec."""
    planner = AssetPlanner()
    spec, _ = planner.plan("a table", _fake_llm_out_of_range)

    ranges = PARAM_RANGES["table"]
    assert spec["params"]["top_width"] == ranges["top_width"][1]
    assert spec["params"]["top_depth"] == ranges["top_depth"][0]
    assert spec["params"]["top_thickness"] == ranges["top_thickness"][0]
    assert spec["params"]["leg_height"] == ranges["leg_height"][1]
    assert spec["params"]["leg_radius"] == ranges["leg_radius"][0]
    assert spec["params"]["leg_inset"] == ranges["leg_inset"][1]
    compile_spec(spec)


def test_plan_with_missing_params_filled():
    """Missing params get default midpoint values and the result compiles."""
    planner = AssetPlanner()
    spec, _ = planner.plan("a table", _fake_llm_missing_params)

    ranges = PARAM_RANGES["table"]
    assert spec["params"]["top_width"] == 1.5
    for key in ("top_depth", "top_thickness", "leg_height", "leg_radius", "leg_inset"):
        lo, hi = ranges[key]
        assert spec["params"][key] == pytest.approx((lo + hi) / 2.0)
    compile_spec(spec)


def test_plan_with_unknown_material_in_fake_defaults_to_worn_oak():
    """Even if the LLM emits a bogus material, the resolver's verdict
    (worn_oak for 'a table') is authoritative — and an
    unspecified_defaulted decision is emitted."""
    def fake_with_bogus_material(prompt, grammar):
        return json.dumps({
            "asset_id": "table",
            "generator": "table",
            "material": "glitter_unobtanium",
            "params": {
                "top_width": 1.5, "top_depth": 0.8, "top_thickness": 0.06,
                "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
            },
        })

    planner = AssetPlanner()
    spec, decisions = planner.plan("a table", fake_with_bogus_material)
    assert spec["material"] == "worn_oak"
    assert any(d.code == "material.unspecified_defaulted" for d in decisions), (
        "expected unspecified_defaulted decision when material can't derive"
    )
    compile_spec(spec)


# ── Slice 11: resolver drives material, decisions reachable ───────────


def test_plan_returns_tuple_with_spec_and_decisions():
    """plan() returns (spec, decisions) — tuple-like, two-element."""
    planner = AssetPlanner()
    out = planner.plan("a table", _fake_llm_valid)
    # 2-element unpackable
    assert len(out) == 2
    spec, decisions = out
    assert isinstance(spec, dict)
    assert "asset_id" in spec
    assert isinstance(decisions, list)
    assert all(isinstance(d, DecisionPoint) for d in decisions)


def test_plan_uses_resolver_when_fake_llm_omits_material():
    """A fake llm whose JSON has NO material field still yields a spec
    whose material came from the resolver, and the decisions reach the
    caller."""
    def fake_no_material(prompt, grammar):
        return json.dumps({
            "asset_id": "table",
            "generator": "table",
            # explicit: no material field
            "params": {
                "top_width": 1.5, "top_depth": 0.8, "top_thickness": 0.06,
                "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
            },
        })
    planner = AssetPlanner()
    # 'wooden' → material.family_defaulted; 'wrought-iron' → confident
    # (no wear word) → age.unspecified_defaulted
    spec, decisions = planner.plan("a tall wrought-iron table", fake_no_material)
    assert spec["material"] == "wrought_iron", (
        "resolver should have set material to wrought_iron from the request text"
    )
    # Material is confident; age is unspecified_defaulted
    assert all(d.code != "material.family_defaulted" for d in decisions), (
        "material should be confident specific match"
    )
    assert any(d.code == "age.unspecified_defaulted" for d in decisions)
    compile_spec(spec)


def test_plan_wooden_table_emits_family_defaulted_with_choices():
    """For a 'wooden' request, family_defaulted decision surfaces to caller."""
    planner = AssetPlanner()
    spec, decisions = planner.plan("a wooden table", _fake_llm_valid)
    assert spec["material"] == "worn_oak"
    assert len(decisions) >= 1
    dp = decisions[0]
    assert dp.code == "material.family_defaulted"
    assert dp.severity == "assumption"
    assert dp.stage == "planner"
    # Choices cover the OTHER wood members
    choice_values = {c.apply["value"] for c in dp.choices}
    assert "dark_walnut" in choice_values
    assert "weathered_pine" in choice_values
    assert "worn_oak" not in choice_values


def test_plan_resolver_overrides_llm_material_when_keywords_match():
    """If the LLM guesses a wrong material AND the resolver matches a
    specific keyword from the request, the resolver's verdict wins."""
    def fake_with_wrong_material(prompt, grammar):
        return json.dumps({
            "asset_id": "table",
            "generator": "table",
            "material": "dark_walnut",  # LLM guess; should be ignored
            "params": {
                "top_width": 1.5, "top_depth": 0.8, "top_thickness": 0.06,
                "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
            },
        })
    planner = AssetPlanner()
    # 'iron' → wrought_iron (confident); no wear word → age.unspecified_defaulted
    spec, decisions = planner.plan("an iron table", fake_with_wrong_material)
    assert spec["material"] == "wrought_iron"
    assert all(d.code != "material.family_defaulted" for d in decisions)
    assert any(d.code == "age.unspecified_defaulted" for d in decisions)


# ── Slice 6 / 7 / 10 fast tests with resolver-aware assertions ────────


def test_plan_with_dark_walnut_material_via_resolver():
    """Request text contains 'walnut' → resolver picks dark_walnut."""
    planner = AssetPlanner()
    spec, _ = planner.plan("a dark walnut table", _fake_llm_valid)
    assert spec["material"] == "dark_walnut"
    compile_spec(spec)


def test_plan_with_weathered_pine_material_via_resolver():
    """Request text contains 'pine' → resolver picks weathered_pine."""
    planner = AssetPlanner()
    spec, _ = planner.plan("a pine table", _fake_llm_valid)
    assert spec["material"] == "weathered_pine"
    compile_spec(spec)


def test_plan_with_wrought_iron_material_via_resolver():
    """Request text contains 'iron' → resolver picks wrought_iron."""
    planner = AssetPlanner()
    spec, _ = planner.plan("an iron table", _fake_llm_valid)
    assert spec["material"] == "wrought_iron"
    compile_spec(spec)


def test_plan_with_rough_granite_material_via_resolver():
    """Request text contains 'granite' → resolver picks rough_granite."""
    planner = AssetPlanner()
    spec, _ = planner.plan("a granite table", _fake_llm_valid)
    assert spec["material"] == "rough_granite"
    compile_spec(spec)


# ── Live integration test ────────────────────────────────────────────


def _llama_server_reachable() -> bool:
    """Check if the llama.cpp server is listening at 127.0.0.1:8002."""
    try:
        s = socket.create_connection(("127.0.0.1", 8002), timeout=2)
        s.close()
        return True
    except (TimeoutError, ConnectionRefusedError, OSError):
        return False


@pytest.mark.live
def test_plan_live_produces_buildable_spec():
    """Integration: real LLM produces a spec that passes compile_spec.

    Prompt with 'a dark walnut coffee table' — assert material is one of the
    palette ids (do NOT hard-assert dark_walnut, since live LLM has noise).
    """
    if not _llama_server_reachable():
        pytest.skip("llama.cpp server not reachable at 127.0.0.1:8002")

    from compiler import MATERIALS

    llm = FoundryLLM()
    planner = AssetPlanner()
    spec, decisions = planner.plan("a dark walnut coffee table", llm)

    assert "asset_id" in spec
    assert "generator" in spec
    assert spec["generator"] == "table"
    assert spec["material"] in MATERIALS, (
        f"material {spec['material']!r} not in palette {sorted(MATERIALS)}"
    )
    assert "params" in spec
    assert isinstance(decisions, list)

    params = spec["params"]
    for key in PARAM_RANGES["table"]:
        assert key in params, f"Missing param: {key}"
        assert isinstance(params[key], (int, float)), f"Param {key} is not a number"

    compile_spec(spec)

    for key, val in params.items():
        assert val > 0, f"param {key}={val} is not positive"


# ── Slice 7: chair generator plan() tests ────────────────────────────


def _fake_llm_chair(prompt: str, grammar: str | None) -> str:
    return json.dumps({
        "asset_id": "chair",
        "generator": "chair",
        "params": {
            "seat_width": 0.5,
            "seat_depth": 0.5,
            "seat_thickness": 0.06,
            "leg_height": 0.45,
            "leg_radius": 0.04,
            "leg_inset": 0.05,
            "back_height": 0.35,
        },
    })


def _fake_llm_chair_missing_params(prompt: str, grammar: str | None) -> str:
    return json.dumps({
        "asset_id": "chair",
        "generator": "chair",
        "params": {
            "seat_width": 0.5,
        },
    })


def test_plan_chair_with_fake_llm():
    """plan('a chair', fake_llm) → generator=='chair', asset_id=='chair', buildable.
    'a chair' has no material keyword → resolver picks worn_oak.
    """
    planner = AssetPlanner()
    spec, _ = planner.plan("a chair", _fake_llm_chair)
    assert spec["generator"] == "chair"
    assert spec["asset_id"] == "chair"
    assert spec["material"] == "worn_oak"
    compile_spec(spec)


def test_plan_chair_missing_params_filled():
    """Missing chair params are filled from range defaults."""
    planner = AssetPlanner()
    spec, _ = planner.plan("a chair", _fake_llm_chair_missing_params)

    ranges = PARAM_RANGES["chair"]
    assert spec["params"]["seat_width"] == 0.5
    for key in ("seat_depth", "seat_thickness", "leg_height", "leg_radius",
                "leg_inset", "back_height"):
        lo, hi = ranges[key]
        assert spec["params"][key] == pytest.approx((lo + hi) / 2.0)
    compile_spec(spec)


# ── Slice 10: shelf + cabinet generator plan() tests ────────────────


def _fake_llm_shelf(prompt: str, grammar: str | None) -> str:
    return json.dumps({
        "asset_id": "shelf",
        "generator": "shelf",
        "params": {
            "width": 1.0, "depth": 0.3, "height": 1.2,
            "board_thickness": 0.04, "n_shelves": 3, "side_thickness": 0.03,
        },
    })


def _fake_llm_cabinet(prompt: str, grammar: str | None) -> str:
    return json.dumps({
        "asset_id": "cabinet",
        "generator": "cabinet",
        "params": {
            "width": 0.8, "depth": 0.5, "height": 1.5,
            "panel_thickness": 0.04, "base_height": 0.08,
        },
    })


def test_plan_shelf_with_fake_llm():
    """plan('a wooden bookshelf', fake_llm) → generator=='shelf'."""
    planner = AssetPlanner()
    # 'wooden' matches family "wood" with 3 members → worn_oak, family_defaulted
    spec, decisions = planner.plan("a wooden bookshelf", _fake_llm_shelf)
    assert spec["generator"] == "shelf"
    assert spec["asset_id"] == "shelf"
    assert spec["material"] == "worn_oak"
    # 'wooden' → material.family_defaulted; no wear word → age.unspecified_defaulted
    assert len(decisions) >= 1
    dp = decisions[0]
    assert dp.code == "material.family_defaulted"
    compile_spec(spec)


def test_plan_cabinet_with_fake_llm():
    """plan('a tall storage cabinet', fake_llm) → generator=='cabinet'.
    No material keyword → worn_oak, unspecified_defaulted.
    """
    planner = AssetPlanner()
    spec, decisions = planner.plan("a tall storage cabinet", _fake_llm_cabinet)
    assert spec["generator"] == "cabinet"
    assert spec["asset_id"] == "cabinet"
    assert spec["material"] == "worn_oak"
    assert any(d.code == "material.unspecified_defaulted" for d in decisions)
    compile_spec(spec)


@pytest.mark.live
def test_plan_live_chair_produces_buildable_spec():
    """Integration: real LLM produces a chair spec from 'a simple wooden chair'.
    'wooden' => family_defaulted decision.
    """
    if not _llama_server_reachable():
        pytest.skip("llama.cpp server not reachable at 127.0.0.1:8002")

    from compiler import MATERIALS

    llm = FoundryLLM()
    planner = AssetPlanner()
    spec, _ = planner.plan("a simple wooden chair", llm)

    assert "generator" in spec
    assert spec["material"] in MATERIALS
    assert "params" in spec

    gen = spec["generator"]
    params = spec["params"]
    for key in PARAM_RANGES.get(gen, {}):
        assert key in params, f"Missing param '{key}' for generator {gen}"
        assert isinstance(params[key], (int, float)), f"Param {key} is not a number"

    compile_spec(spec)
    for key, val in params.items():
        assert val > 0, f"param {key}={val} is not positive"


# ── Slice 11: grammar + planner integration ────────────────────────


def test_grammar_root_rule_no_longer_includes_material_field():
    """The grammar's root rule must not include a 'material' field — qwen
    no longer chooses material (the resolver does)."""
    grammar = load_grammar()
    # Find the root rule line (first non-comment, non-blank line that starts
    # with "root").
    root_lines = [
        l for l in grammar.split("\n")
        if l.strip().startswith("root ") and "::=" in l
    ]
    assert root_lines, "could not find root rule in normalized grammar"
    root_line = root_lines[0]
    assert "material" not in root_line, (
        f"grammar root rule still contains 'material': {root_line!r}"
    )


def test_normalized_grammar_is_single_line_root():
    """After normalize_gbnf, the grammar is still a single-line root."""
    grammar = load_grammar()
    # Find root lines
    root_lines = [
        l for l in grammar.split("\n")
        if l.strip().startswith("root ") and "::=" in l
    ]
    assert len(root_lines) == 1, (
        f"expected one root rule line, got {len(root_lines)}: {root_lines}"
    )


# ── Age pre-pass integration (P1) ────────────────────────────────────


def test_plan_old_chair_gets_age_0_8_from_resolver():
    """'an old chair' → resolve_age → 0.8 (confident, no age decision)."""
    planner = AssetPlanner()
    spec, decisions = planner.plan("an old chair", _fake_llm_chair)
    assert spec["age"] == 0.8
    # 'old' is confident → no age DecisionPoint; but 'chair' has no
    # material keyword → material.unspecified_defaulted
    assert any(d.code == "material.unspecified_defaulted" for d in decisions)
    assert all(d.code != "age.unspecified_defaulted" for d in decisions)
    compile_spec(spec)


def test_plan_new_table_gets_age_0_15_from_resolver():
    """'a new table' → resolve_age → 0.15 (confident)."""
    planner = AssetPlanner()
    spec, decisions = planner.plan("a new table", _fake_llm_valid)
    assert spec["age"] == 0.15
    assert all(d.code != "age.unspecified_defaulted" for d in decisions)
    compile_spec(spec)


def test_plan_neutral_request_gets_age_0_15_with_decision():
    """'a plain table' (no wear word) → age=0.15 + unspecified_defaulted."""
    planner = AssetPlanner()
    spec, decisions = planner.plan("a plain table", _fake_llm_valid)
    assert spec["age"] == 0.15
    assert any(d.code == "age.unspecified_defaulted" for d in decisions)
    compile_spec(spec)


def test_plan_vintage_cabinet_gets_age_0_8_from_resolver():
    """'a vintage cabinet' → resolve_age → 0.8 (confident)."""
    planner = AssetPlanner()
    spec, decisions = planner.plan("a vintage cabinet", _fake_llm_cabinet)
    assert spec["age"] == 0.8
    assert all(d.code != "age.unspecified_defaulted" for d in decisions)
    compile_spec(spec)


def test_plan_old_new_conflict_gets_age_0_8_with_conflict_decision():
    """'an old new cabinet' → age.conflict → 0.8 (aged wins tie)."""
    planner = AssetPlanner()
    spec, decisions = planner.plan("an old new cabinet", _fake_llm_cabinet)
    assert spec["age"] == 0.8
    assert any(d.code == "age.conflict" for d in decisions)
    compile_spec(spec)


def test_plan_fake_llm_with_no_age_field_yields_valid_spec():
    """A fake LLM whose JSON has NO age field still yields a valid spec
    whose age came from the age resolver."""
    def fake_no_age(prompt, grammar):
        return json.dumps({
            "asset_id": "table",
            "generator": "table",
            # explicit: no age field
            "params": {
                "top_width": 1.5, "top_depth": 0.8, "top_thickness": 0.06,
                "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
            },
        })
    planner = AssetPlanner()
    spec, decisions = planner.plan("an old weathered table", fake_no_age)
    assert spec["age"] == 0.8
    assert all(d.code != "age.unspecified_defaulted" for d in decisions)
    compile_spec(spec)


def test_grammar_root_rule_no_longer_includes_age_field():
    """The grammar's root rule must not include an 'age' field — qwen
    no longer chooses age (the resolver does)."""
    grammar = load_grammar()
    root_lines = [
        l for l in grammar.split("\n")
        if l.strip().startswith("root ") and "::=" in l
    ]
    assert root_lines, "could not find root rule in normalized grammar"
    root_line = root_lines[0]
    assert "age" not in root_line, (
        f"grammar root rule still contains 'age': {root_line!r}"
    )


# ── Slice 12: Age-anchoring few-shot examples in the planner prompt ────


def _slice_examples_section(prompt: str) -> str:
    """Slice out the substring between the ``Examples:`` marker and the
    *final* ``Request: {request}`` template literal. Robust to extra
    ``Request:`` lines inside the examples block."""
    if "Examples:" not in prompt:
        return ""
    tail = prompt.split("Examples:", 1)[1]
    cut_at = tail.rfind("Request: {request}")
    if cut_at == -1:
        cut_at = tail.rfind("Output JSON now")
        if cut_at == -1:
            return tail
    return tail[:cut_at]


def _extract_example_blocks(examples_section: str) -> list[str]:
    """Pull every top-level ``{...}`` JSON block out of *examples_section*."""
    blocks: list[str] = []
    depth = 0
    start: int | None = None
    for idx, c in enumerate(examples_section):
        if c == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start is not None:
                blocks.append(examples_section[start:idx + 1])
                start = None
    return blocks


_PROMPT_TESTS_REQUEST = "a plain table"


def test_prompt_has_examples_block():
    """The planner prompt contains an ``Examples:`` block.

    Live runs showed qwen leaning ``age`` high on neutral requests (e.g.
    a plain 'tall cabinet' -> 0.7). The fix is few-shot examples — not a
    model swap — anchoring low/mid/high age behaviour.
    """
    planner = AssetPlanner()
    prompt = planner.build_prompt(_PROMPT_TESTS_REQUEST)
    assert "Examples:" in prompt, "planner prompt must contain an Examples: block"


def test_examples_do_not_include_age():
    """Age is now deterministic (resolver), not qwen's job.  No example
    JSON block should contain an ``age`` key."""
    planner = AssetPlanner()
    prompt = planner.build_prompt(_PROMPT_TESTS_REQUEST)
    blocks = _extract_example_blocks(_slice_examples_section(prompt))
    assert len(blocks) >= 3, f"expected >=3 example blocks, got {len(blocks)}"
    for b in blocks:
        parsed = json.loads(b)
        assert "age" not in parsed, (
            f"example block contains 'age' key (resolver owns it):\n{parsed}"
        )


def test_examples_cover_at_least_two_generators():
    """The few-shot examples span >=2 generators (table, chair, shelf,
    cabinet) — qwen needs to see both shape variance AND age anchors."""
    planner = AssetPlanner()
    prompt = planner.build_prompt(_PROMPT_TESTS_REQUEST)
    blocks = _extract_example_blocks(_slice_examples_section(prompt))
    assert len(blocks) >= 3, f"expected >=3 example blocks, got {len(blocks)}"

    gens = {json.loads(b)["generator"] for b in blocks}
    assert len(gens) >= 2, f"examples must span >=2 generators, got {gens}"


def test_examples_have_no_material_key():
    """None of the example JSON blocks contains a ``material`` key —
    material is the resolver's job (Slice 11), not the LLM's.

    Regression guard: a previous prompt revision DID include a
    ``material`` field in the schema; the resolver owns material now and
    the few-shot examples must not give the model the wrong idea.
    """
    planner = AssetPlanner()
    prompt = planner.build_prompt(_PROMPT_TESTS_REQUEST)
    blocks = _extract_example_blocks(_slice_examples_section(prompt))
    assert len(blocks) >= 3, f"expected >=3 example blocks, got {len(blocks)}"

    for b in blocks:
        parsed = json.loads(b)
        assert "material" not in parsed, (
            f"example block contains 'material' key (resolver owns it):\n{parsed}"
        )


def test_examples_use_only_schema_keys():
    """Each example's JSON has exactly the four canonical keys:
    asset_id, generator, age, params. No extra fields."""
    planner = AssetPlanner()
    prompt = planner.build_prompt(_PROMPT_TESTS_REQUEST)
    blocks = _extract_example_blocks(_slice_examples_section(prompt))
    assert len(blocks) >= 3, f"expected >=3 example blocks, got {len(blocks)}"

    expected = {"asset_id", "generator", "params"}
    for b in blocks:
        parsed = json.loads(b)
        assert set(parsed.keys()) == expected, (
            f"example keys={set(parsed.keys())} != expected {expected}: {parsed}"
        )


def test_examples_params_are_in_param_ranges():
    """Every example's param values land inside PARAM_RANGES for its
    declared generator — the examples must teach in-range shape, not
    out-of-range garbage qwen would imitate."""
    planner = AssetPlanner()
    prompt = planner.build_prompt(_PROMPT_TESTS_REQUEST)
    blocks = _extract_example_blocks(_slice_examples_section(prompt))
    assert len(blocks) >= 3, f"expected >=3 example blocks, got {len(blocks)}"

    for b in blocks:
        parsed = json.loads(b)
        gen = parsed["generator"]
        ranges = PARAM_RANGES.get(gen, {})
        assert ranges, f"unknown generator {gen!r}"
        for k, v in parsed["params"].items():
            lo, hi = ranges[k]
            assert lo <= float(v) <= hi, (
                f"example param {k}={v} out of [{lo}, {hi}] for {gen}: {parsed}"
            )


def test_examples_anchor_plan_still_parses_and_compiles():
    """The example values in the prompt must be valid asset-specs:
    AssetPlanner.plan() with a FAKE llm that mirrors the example shape
    parses, clamps, and passes compile_spec.

    This guards against an example whose params would fail compile_spec
    (e.g. an example declaring a 4 m tall cabinet).
    """
    planner = AssetPlanner()
    prompt = planner.build_prompt(_PROMPT_TESTS_REQUEST)
    blocks = _extract_example_blocks(_slice_examples_section(prompt))
    assert len(blocks) >= 3, f"expected >=3 example blocks, got {len(blocks)}"

    for b in blocks:
        spec_like = json.loads(b)
        # Hand-roll a FAKE llm that emits exactly the example JSON.
        spec_payload = json.dumps(spec_like)

        def fake(_prompt: str, _grammar: str | None, _payload: str = spec_payload) -> str:
            return _payload

        out_spec, _ = planner.plan("a plain table", fake)
        # Material is mandatory for compile_spec — plan() fills it via the
        # resolver (a generic request -> worn_oak + decision).
        compile_spec(out_spec)
