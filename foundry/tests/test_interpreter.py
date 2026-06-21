"""TDD tests for foundry.interpreter — prompt → Brief (spine slice 1 task 2).

Tests the Interpreter's build_prompt, parse (raw_decode), and interpret
behaviour — all with stub LLMs (no llama.cpp dependency).  Mirrors the
test_behaviour_gen.py / test_room_planner.py pattern.
"""

from __future__ import annotations

import json
from typing import Optional

import pytest


# ── build_prompt ───────────────────────────────────────────────────


def test_build_prompt_contains_vocabularies():
    """build_prompt injects the closed vocabularies so the LLM can
    make capability-aware choices."""
    from interpreter import Interpreter

    interp = Interpreter()
    prompt_text = interp.build_prompt("a wizard's tower study")

    # Known themes should be listed
    assert "hermit" in prompt_text
    assert "blacksmith" in prompt_text
    assert "wizard" in prompt_text
    assert "tavern" in prompt_text
    assert 'or "*"' in prompt_text

    # Placeable categories should be listed
    assert "table" in prompt_text
    assert "chair" in prompt_text
    assert "shelf" in prompt_text

    # The user's description should be included
    assert "a wizard's tower study" in prompt_text

    # Output JSON instruction should be present
    assert "Output JSON now" in prompt_text


# ── parse ──────────────────────────────────────────────────────────


def test_parse_valid_json():
    from interpreter import Interpreter

    data = Interpreter.parse('{"theme_tag": "blacksmith", "scale": "medium"}')
    assert data["theme_tag"] == "blacksmith"
    assert data["scale"] == "medium"


def test_parse_json_with_markdown_fences():
    from interpreter import Interpreter

    data = Interpreter.parse('```json\n{"theme_tag": "wizard"}\n```')
    assert data["theme_tag"] == "wizard"


def test_parse_json_with_think_tags():
    from interpreter import Interpreter

    data = Interpreter.parse(
        '<think>hmm</think>\n{"theme_tag": "tavern", "mood": ["cozy"]}'
    )
    assert data["theme_tag"] == "tavern"
    assert data["mood"] == ["cozy"]


def test_parse_trailing_prose_handled_by_raw_decode():
    """Trailing prose / unclosed <think> after JSON → raw_decode
    parses the first complete object, ignores the rest.  This is the
    hard-won lesson — json.loads() would reject with 'Extra data'."""
    from interpreter import Interpreter

    # Trailing prose after valid JSON
    data = Interpreter.parse(
        '{"theme_tag": "dungeon", "scale": "small"}<think>unclosed prose'
    )
    assert data["theme_tag"] == "dungeon"
    assert data["scale"] == "small"

    # Unclosed think block after valid JSON
    data = Interpreter.parse(
        '{"theme_tag": "armory"}<think>this is not closed'
    )
    assert data["theme_tag"] == "armory"


def test_parse_empty_text_raises():
    from interpreter import Interpreter

    with pytest.raises(ValueError, match="Empty"):
        Interpreter.parse("")


def test_parse_no_json_found_raises():
    from interpreter import Interpreter

    with pytest.raises(ValueError, match="No JSON found"):
        Interpreter.parse("not json at all")


def test_parse_malformed_json_raises():
    from interpreter import Interpreter

    with pytest.raises(ValueError, match="Invalid JSON"):
        Interpreter.parse("{malformed : stuff")


# ── interpret (stub LLMs, no llama) ────────────────────────────────


def test_interpret_valid_json_passthrough():
    """Stub returns valid JSON → interpret yields Brief with
    source_prompt set, no error decisions."""
    from interpreter import Interpreter
    from brief import THEMES

    def fake_llm(prompt: str, grammar: Optional[str]) -> str:
        return json.dumps({
            "theme_tag": "blacksmith",
            "scale": "medium",
            "setting": "a blacksmith's forge",
            "mood": ["hot", "industrious"],
            "key_features": [
                {"text": "anvil", "category": "table"},
            ],
        })

    interp = Interpreter()
    brief, decs = interp.interpret("a blacksmith's forge", fake_llm)

    assert brief["theme_tag"] == "blacksmith"
    assert brief["scale"] == "medium"
    assert brief["source_prompt"] == "a blacksmith's forge"
    assert brief["setting"] == "a blacksmith's forge"
    assert brief["mood"] == ["hot", "industrious"]
    assert len(brief["key_features"]) == 1

    # No error decisions for clean input
    error_dps = [d for d in decs if d.severity == "error"]
    assert not error_dps, f"Unexpected error DPs: {[d.code for d in error_dps]}"


def test_interpret_parse_fallback():
    """Stub returns unparseable text → Brief.minimal + parse_fallback
    decision.  Never raises."""
    from interpreter import Interpreter
    from brief import THEMES

    def fake_llm(prompt: str, grammar: Optional[str]) -> str:
        return "not json at all"

    interp = Interpreter()
    brief, decs = interp.interpret("a wizard's tower", fake_llm)

    # Should fall back to minimal Brief (theme inferred from prompt)
    assert brief["source_prompt"] == "a wizard's tower"
    assert brief["scale"] == "medium"  # minimal default

    # parse_fallback DP must be present
    dp = next((d for d in decs if d.code == "brief.parse_fallback"), None)
    assert dp is not None, f"No parse_fallback decision: {[d.code for d in decs]}"
    assert dp.severity == "error"


def test_interpret_passes_empty_string_as_grammar():
    """interpret() MUST pass \"\" (not None) as the grammar argument
    so the LLM produces free-form output.  None would trigger the
    default asset-spec GBNF, silently straitjacketing every model."""
    from interpreter import Interpreter

    seen: list[Optional[str]] = []

    def capturing_llm(prompt: str, grammar: Optional[str]) -> str:
        seen.append(grammar)
        return json.dumps({
            "theme_tag": "wizard",
            "scale": "medium",
        })

    interp = Interpreter()
    interp.interpret("mystical study", capturing_llm)

    assert len(seen) == 1
    assert seen[0] == "", (
        f"interpret() must pass \"\" for free-form output, got {seen[0]!r}. "
        f"None would apply the default asset grammar."
    )


def test_interpret_llm_exception_handled():
    """LLM raises an exception → Brief.minimal + parse_fallback, no raise."""
    from interpreter import Interpreter

    def crashing_llm(prompt: str, grammar: Optional[str]) -> str:
        raise RuntimeError("LLM server down")

    interp = Interpreter()
    brief, decs = interp.interpret("cozy tavern", crashing_llm)

    assert brief["source_prompt"] == "cozy tavern"
    dp = next(d for d in decs if d.code == "brief.parse_fallback")
    assert "LLM server down" in dp.context["error"]


def test_interpret_valid_with_unmapped_features():
    """Stub returns features with unknown categories → unmapped in Brief."""
    from interpreter import Interpreter

    def fake_llm(prompt: str, grammar: Optional[str]) -> str:
        return json.dumps({
            "theme_tag": "kitchen",
            "scale": "large",
            "key_features": [
                {"text": "a magic portal", "category": "portal"},
                {"text": "large table", "category": "table"},
            ],
        })

    interp = Interpreter()
    brief, decs = interp.interpret("magic kitchen", fake_llm)

    assert len(brief["key_features"]) == 2
    assert brief["key_features"][0]["status"] == "unmapped"
    assert "a magic portal" in brief["unmapped"]
    assert brief["key_features"][1]["status"] == "mapped"


def test_interpret_star_theme_passthrough():
    """Valid Brief with theme_tag=\"*\" is accepted without error."""
    from interpreter import Interpreter

    def fake_llm(prompt: str, grammar: Optional[str]) -> str:
        return json.dumps({
            "theme_tag": "*",
            "scale": "large",
        })

    interp = Interpreter()
    brief, decs = interp.interpret("some strange place", fake_llm)

    assert brief["theme_tag"] == "*"
    error_dps = [d for d in decs if d.severity == "error"]
    assert not error_dps
