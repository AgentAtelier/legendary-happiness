"""Tests for the AssetPlanner (Slice 5).  The deterministic core needs NO live LLM."""

from __future__ import annotations

import json
import socket

import pytest

from compiler import compile_spec, PARAM_RANGES
from llm import normalize_gbnf, load_grammar, FoundryLLM
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


def test_normalize_gbnf_handles_empty_lines_and_comments():
    """Empty lines and comments between a rule and its | continuation are skipped."""
    raw = "root ::= \"x\"\n# comment\n         | \"y\""
    got = normalize_gbnf(raw)
    lines = [l for l in got.split("\n") if l.strip() and not l.lstrip().startswith("#")]
    assert len(lines) == 1
    assert "\"x\"" in lines[0]
    assert "\"y\"" in lines[0]


# ── Prompt tests ──────────────────────────────────────────────────


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


def test_build_prompt_contains_material_hints():
    """Slice 6: the prompt lists the three palette materials with tone hints."""
    planner = AssetPlanner()
    prompt = planner.build_prompt("a dark walnut table")
    assert "worn_oak" in prompt
    assert "dark_walnut" in prompt
    assert "weathered_pine" in prompt


# ── Parse tests ───────────────────────────────────────────────────


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
    raw = '<think>I should output a table spec</think>\n{"asset_id":"table","generator":"table","material":"worn_oak","params":{"top_width":1.0,"top_depth":0.5,"top_thickness":0.04,"leg_height":0.5,"leg_radius":0.03,"leg_inset":0.05}}'
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


# ── plan() tests with FAKE llm ────────────────────────────────────


def _fake_llm_valid(prompt: str, grammar: str | None) -> str:
    return json.dumps({
        "asset_id": "table",
        "generator": "table",
        "material": "worn_oak",
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
        "material": "worn_oak",
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
        "material": "worn_oak",
        "params": {
            "top_width": 1.5,
            # missing top_depth, top_thickness, etc.
        },
    })

def _fake_llm_non_numeric_param(prompt: str, grammar: str | None) -> str:
    """Returns a spec where one param is a string instead of a number."""
    return json.dumps({
        "asset_id": "table",
        "generator": "table",
        "material": "worn_oak",
        "params": {
            "top_width": "hello",
            "top_depth": 0.8,
            "top_thickness": 0.06,
            "leg_height": 0.65,
            "leg_radius": 0.05,
            "leg_inset": 0.1,
        },
    })


def test_plan_with_valid_spec_preserved():
    """A valid spec passes compile_spec unchanged (except float coercion)."""
    planner = AssetPlanner()
    spec = planner.plan("a table", _fake_llm_valid)
    assert spec["generator"] == "table"
    assert spec["material"] == "worn_oak"
    assert spec["params"]["top_width"] == 1.5
    assert spec["params"]["top_depth"] == 0.8
    # Must pass compile_spec
    compile_spec(spec)  # does not raise


def test_plan_with_non_numeric_param_defaults_to_midpoint():
    """A non-numeric param value (string) is replaced with the range midpoint."""
    planner = AssetPlanner()
    spec = planner.plan("a table", _fake_llm_non_numeric_param)
    ranges = PARAM_RANGES["table"]
    lo, hi = ranges["top_width"]
    assert spec["params"]["top_width"] == pytest.approx((lo + hi) / 2.0)
    # Other params unchanged
    assert spec["params"]["top_depth"] == 0.8
    compile_spec(spec)


def test_plan_with_out_of_range_params_clamped():
    """Out-of-range params are clamped and the result passes compile_spec."""
    planner = AssetPlanner()
    spec = planner.plan("a table", _fake_llm_out_of_range)

    ranges = PARAM_RANGES["table"]
    # top_width was 999 → clamped to max 3.0
    assert spec["params"]["top_width"] == ranges["top_width"][1]
    # top_depth was -5 → clamped to min 0.4
    assert spec["params"]["top_depth"] == ranges["top_depth"][0]
    # top_thickness was 0.001 → clamped to min 0.03
    assert spec["params"]["top_thickness"] == ranges["top_thickness"][0]
    # leg_height was 5 → clamped to max 1.1
    assert spec["params"]["leg_height"] == ranges["leg_height"][1]
    # leg_radius was 0.001 → clamped to min 0.03
    assert spec["params"]["leg_radius"] == ranges["leg_radius"][0]
    # leg_inset was 999 → clamped to max 0.3
    assert spec["params"]["leg_inset"] == ranges["leg_inset"][1]

    # Must pass compile_spec
    compile_spec(spec)  # does not raise


def test_plan_with_missing_params_filled():
    """Missing params get default midpoint values and the result compiles."""
    planner = AssetPlanner()
    spec = planner.plan("a table", _fake_llm_missing_params)

    ranges = PARAM_RANGES["table"]
    # top_width was provided
    assert spec["params"]["top_width"] == 1.5
    # The missing ones get midpoints
    for key in ("top_depth", "top_thickness", "leg_height", "leg_radius", "leg_inset"):
        lo, hi = ranges[key]
        assert spec["params"][key] == pytest.approx((lo + hi) / 2.0)

    compile_spec(spec)  # does not raise


def test_plan_with_missing_material_fills_default():
    """Missing material is filled with 'worn_oak'."""
    def fake_no_material(prompt, grammar):
        return json.dumps({
            "generator": "table",
            "params": {
                "top_width": 1.5, "top_depth": 0.8, "top_thickness": 0.06,
                "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
            },
        })
    planner = AssetPlanner()
    spec = planner.plan("a table", fake_no_material)
    assert spec["material"] == "worn_oak"
    compile_spec(spec)


# ── Live integration test ─────────────────────────────────────────


def _llama_server_reachable() -> bool:
    """Check if the llama.cpp server is listening at 127.0.0.1:8002."""
    try:
        s = socket.create_connection(("127.0.0.1", 8002), timeout=2)
        s.close()
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


# ── Slice 6: material palette plan() tests ─────────────────────────

def _fake_llm_dark_walnut(prompt: str, grammar: str | None) -> str:
    """Fake LLM that returns a spec with material=dark_walnut."""
    return json.dumps({
        "asset_id": "table",
        "generator": "table",
        "material": "dark_walnut",
        "params": {
            "top_width": 1.5,
            "top_depth": 0.8,
            "top_thickness": 0.06,
            "leg_height": 0.65,
            "leg_radius": 0.05,
            "leg_inset": 0.1,
        },
    })


def _fake_llm_weathered_pine(prompt: str, grammar: str | None) -> str:
    """Fake LLM that returns a spec with material=weathered_pine."""
    return json.dumps({
        "asset_id": "table",
        "generator": "table",
        "material": "weathered_pine",
        "params": {
            "top_width": 1.5,
            "top_depth": 0.8,
            "top_thickness": 0.06,
            "leg_height": 0.65,
            "leg_radius": 0.05,
            "leg_inset": 0.1,
        },
    })


def _fake_llm_unknown_material(prompt: str, grammar: str | None) -> str:
    """Fake LLM that returns a spec with an unknown material."""
    return json.dumps({
        "asset_id": "table",
        "generator": "table",
        "material": "glitter_unobtanium",
        "params": {
            "top_width": 1.5,
            "top_depth": 0.8,
            "top_thickness": 0.06,
            "leg_height": 0.65,
            "leg_radius": 0.05,
            "leg_inset": 0.1,
        },
    })


def test_plan_with_dark_walnut_material():
    """plan() preserves a valid palette material from the LLM."""
    planner = AssetPlanner()
    spec = planner.plan("a dark table", _fake_llm_dark_walnut)
    assert spec["material"] == "dark_walnut"
    compile_spec(spec)  # does not raise


def test_plan_with_weathered_pine_material():
    """plan() preserves weathered_pine from the LLM."""
    planner = AssetPlanner()
    spec = planner.plan("a pale table", _fake_llm_weathered_pine)
    assert spec["material"] == "weathered_pine"
    compile_spec(spec)  # does not raise


def test_plan_with_unknown_material_defaults_to_worn_oak():
    """An LLM returning an out-of-palette material is defaulted to worn_oak."""
    planner = AssetPlanner()
    spec = planner.plan("a table", _fake_llm_unknown_material)
    assert spec["material"] == "worn_oak"
    compile_spec(spec)  # does not raise


def test_plan_live_produces_buildable_spec():
    """Integration: real LLM produces a spec that passes compile_spec.

    Prompt with "a dark walnut coffee table" — assert material is one of the
    three palette ids (do NOT hard-assert dark_walnut).
    """
    if not _llama_server_reachable():
        pytest.skip("llama.cpp server not reachable at 127.0.0.1:8002")

    from compiler import MATERIALS

    llm = FoundryLLM()
    planner = AssetPlanner()
    spec = planner.plan("a dark walnut coffee table", llm)

    # Must have the required keys
    assert "asset_id" in spec
    assert "generator" in spec
    assert spec["generator"] == "table"
    assert spec["material"] in MATERIALS, (
        f"material {spec['material']!r} not in palette {sorted(MATERIALS)}"
    )
    assert "params" in spec

    # All six params must be present
    params = spec["params"]
    for key in PARAM_RANGES["table"]:
        assert key in params, f"Missing param: {key}"
        assert isinstance(params[key], (int, float)), f"Param {key} is not a number"

    # Must pass the compiler gate
    compile_spec(spec)  # does not raise

    # Sanity: numbers should be positive
    for key, val in params.items():
        assert val > 0, f"param {key}={val} is not positive"
