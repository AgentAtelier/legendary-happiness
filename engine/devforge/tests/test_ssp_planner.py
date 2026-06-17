"""Tests for SSP Planner — grammar loading, prompt building, response parsing.

Run with:  cd engine && .venv/bin/python -m pytest devforge/tests/test_ssp_planner.py -v
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from tempfile import NamedTemporaryFile

from devforge.spatial.ssp_planner import SSPPlanner, SSPPlanningError
from devforge.spatial.ssp import SSPEngine
from devforge.spatial.lexicon import AssetLexicon


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def lexicon():
    return AssetLexicon()


@pytest.fixture
def ssp_engine():
    return SSPEngine(compiler=None)


@pytest.fixture
def planner(lexicon, ssp_engine):
    return SSPPlanner(lexicon=lexicon, ssp_engine=ssp_engine)


# ── Grammar loading tests ────────────────────────────────────────


class TestGrammarLoading:
    """Grammar file loading and structure."""

    def test_default_grammar_loads(self, planner):
        """Default ssp_planner.gbnf loads successfully."""
        assert planner.grammar is not None
        assert len(planner.grammar) > 50
        assert "root ::=" in planner.grammar
        assert "archetype" in planner.grammar

    def test_custom_grammar_path(self, lexicon, ssp_engine):
        """Custom grammar path overrides default."""
        with NamedTemporaryFile(mode="w", suffix=".gbnf", delete=False) as f:
            f.write('root ::= "custom"\n')
            tmp_path = f.name
        try:
            p = SSPPlanner(lexicon=lexicon, ssp_engine=ssp_engine, grammar_path=tmp_path)
            assert p.grammar == 'root ::= "custom"'
        finally:
            Path(tmp_path).unlink()

    def test_nonexistent_grammar_path(self, lexicon, ssp_engine):
        """Nonexistent grammar → grammar is None, no crash."""
        p = SSPPlanner(lexicon=lexicon, ssp_engine=ssp_engine, grammar_path="/nonexistent/path.gbnf")
        assert p.grammar is None

    def test_grammar_has_dimensions_and_slots(self, planner):
        """Grammar includes dimensions and slot_overrides rules."""
        g = planner.grammar
        assert "dimensions-kv" in g
        assert "slot-overrides-kv" in g


# ── Prompt building tests ────────────────────────────────────────


class TestPromptBuilding:
    """_build_prompt: archetype catalog, asset filtering."""

    def test_prompt_contains_archetype_ids(self, planner):
        """Prompt lists all archetype IDs."""
        prompt = planner._build_prompt("ctx", "build a kitchen")
        for aid in SSPEngine().archetype_ids:
            assert aid in prompt, f"{aid} missing from prompt"

    def test_prompt_contains_indoor_assets_only(self, planner):
        """Prompt filters to indoor assets (no tree/bush/flower/rock)."""
        prompt = planner._build_prompt("ctx", "build a kitchen")
        assert "fridge" in prompt
        assert "table" in prompt
        assert "stove" in prompt
        # Outdoor assets should NOT appear as comma-separated asset IDs
        asset_list = [a.strip() for a in prompt.split(",")]
        for outdoor in ("tree", "bush", "flower", "rock"):
            assert outdoor not in asset_list, f"{outdoor} leaked into SSP prompt"

    def test_prompt_contains_user_request(self, planner):
        """The user's natural language prompt appears verbatim."""
        prompt = planner._build_prompt("ctx", "build a kitchen")
        assert "build a kitchen" in prompt

    def test_prompt_contains_context(self, planner):
        """Scene context appears in the prompt."""
        prompt = planner._build_prompt("scene has a building at 0,0", "build kitchen")
        assert "scene has a building at 0,0" in prompt

    def test_prompt_has_schema_structure(self, planner):
        """Prompt describes the JSON schema."""
        prompt = planner._build_prompt("ctx", "build")
        assert "OUTPUT SCHEMA" in prompt
        assert '"archetype"' in prompt
        assert '"dimensions"' in prompt
        assert '"slot_overrides"' in prompt

    def test_prompt_has_pattern_list(self, planner):
        """Prompt mentions valid pattern names."""
        prompt = planner._build_prompt("ctx", "build")
        assert "rectangle_room" in prompt
        assert "corridor" in prompt


# ── Response parsing tests ──────────────────────────────────────


class TestResponseParsing:
    """_parse_response: valid JSON, edge cases, error handling."""

    def test_parse_simple_archetype(self, planner):
        """Parse minimal valid room JSON."""
        response = json.dumps({"archetype": "kitchen"})
        result = planner._parse_response(response)
        assert result["archetype"] == "kitchen"
        assert result["dimensions"] == {}
        assert result["slot_overrides"] == {}
        assert result["arcs_overrides"] == []
        assert result["pattern"] is None

    def test_parse_with_overrides(self, planner):
        """Parse JSON with slot and dimension overrides."""
        response = json.dumps(
            {
                "archetype": "living_room",
                "dimensions": {"width": 7, "height": 3, "depth": 7},
                "slot_overrides": {"chair_north": "stool"},
            }
        )
        result = planner._parse_response(response)
        assert result["archetype"] == "living_room"
        assert result["dimensions"]["width"] == 7
        assert result["slot_overrides"]["chair_north"] == "stool"

    def test_parse_with_thinking_tags(self, planner):
        """Strip <think>...</think> tags before parsing."""
        response = "<think>let me pick a room</think>\n" + json.dumps({"archetype": "bedroom"})
        result = planner._parse_response(response)
        assert result["archetype"] == "bedroom"

    def test_parse_with_markdown_fences(self, planner):
        """Strip ```json fences before parsing."""
        response = "```json\n" + json.dumps({"archetype": "bathroom"}) + "\n```"
        result = planner._parse_response(response)
        assert result["archetype"] == "bathroom"

    def test_parse_with_prose_prefix(self, planner):
        """JSON preceded by prose text."""
        response = "Here's the room:\n" + json.dumps({"archetype": "study"})
        result = planner._parse_response(response)
        assert result["archetype"] == "study"

    def test_parse_missing_archetype_defaults(self, planner):
        """Missing archetype field → 'kitchen' default."""
        response = json.dumps({"dimensions": {"width": 5, "height": 3, "depth": 5}})
        result = planner._parse_response(response)
        assert result["archetype"] == "kitchen"

    def test_parse_empty_response_raises(self, planner):
        """Empty string → ValueError."""
        with pytest.raises(ValueError, match="Empty"):
            planner._parse_response("")

    def test_parse_no_json_raises(self, planner):
        """No JSON → ValueError."""
        with pytest.raises(ValueError, match="No JSON"):
            planner._parse_response("just prose")

    def test_parse_invalid_json_raises(self, planner):
        """Malformed JSON → ValueError."""
        with pytest.raises(ValueError, match="Invalid JSON"):
            planner._parse_response('{"archetype": "kitchen"')


# ── Plan integration tests ──────────────────────────────────────


class TestPlanMethod:
    """plan() method: LLM integration, error handling."""

    def test_plan_returns_correct_shape(self, planner):
        """plan() with mock LLM returns the expected dict shape."""
        mock_resp = json.dumps({"archetype": "kitchen"})

        def mock_llm(prompt: str) -> str:
            return mock_resp

        result = planner.plan(
            context="ctx",
            prompt="build a kitchen",
            llm_fn=mock_llm,
        )
        assert result["archetype"] == "kitchen"

    def test_plan_with_slot_overrides(self, planner):
        """plan() handles slot overrides from LLM."""
        mock_resp = json.dumps(
            {
                "archetype": "living_room",
                "slot_overrides": {"center_table": "desk"},
            }
        )

        def mock_llm(prompt: str) -> str:
            return mock_resp

        result = planner.plan(
            context="ctx",
            prompt="build",
            llm_fn=mock_llm,
        )
        assert result["slot_overrides"]["center_table"] == "desk"

    def test_plan_propagates_parse_errors(self, planner):
        """Invalid LLM output → SSPPlanningError."""

        def bad_llm(prompt: str) -> str:
            return "no json here"

        with pytest.raises(SSPPlanningError):
            planner.plan(context="ctx", prompt="build", llm_fn=bad_llm)

    def test_plan_propagates_llm_exceptions(self, planner):
        """LLM crash → SSPPlanningError."""

        def crash_llm(prompt: str) -> str:
            raise RuntimeError("LLM down")

        with pytest.raises(SSPPlanningError, match="LLM down"):
            planner.plan(context="ctx", prompt="build", llm_fn=crash_llm)

    def test_plan_passes_scene_parameter(self, planner):
        """scene parameter accepted (API compat)."""

        def mock_llm(prompt: str) -> str:
            return json.dumps({"archetype": "kitchen"})

        result = planner.plan(
            context="ctx",
            prompt="build",
            llm_fn=mock_llm,
            scene={"name": "Main"},
        )
        assert result["archetype"] == "kitchen"


# ── Import / structure tests ─────────────────────────────────────


class TestSSPPlannerImports:
    def test_imports_available(self):
        from devforge.spatial.ssp_planner import SSPPlanner, SSPPlanningError

        assert SSPPlanner is not None
        assert SSPPlanningError is not None

    def test_planner_creatable_defaults(self):
        p = SSPPlanner()
        assert p._lexicon is not None
        assert p._ssp_engine is not None

    def test_planner_grammar_path_default(self):
        p = SSPPlanner()
        assert "ssp_planner.gbnf" in p._grammar_path

    def test_ssp_planning_error_is_exception(self):
        err = SSPPlanningError("test")
        assert isinstance(err, Exception)
        assert str(err) == "test"
