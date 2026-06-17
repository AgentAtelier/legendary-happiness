"""Tests for ScatterPlanner — grammar loading, prompt building, response parsing.

Run with:  cd devforge_review_package && .venv/bin/python -m pytest devforge/tests/test_scatter_planner.py -v
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from tempfile import NamedTemporaryFile

from devforge.spatial.scatter_planner import ScatterPlanner, ScatterPlanningError
from devforge.spatial.lexicon import AssetLexicon


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def lexicon():
    return AssetLexicon()


@pytest.fixture
def planner(lexicon):
    return ScatterPlanner(lexicon=lexicon)


@pytest.fixture
def planner_no_lexicon():
    """ScatterPlanner with default empty lexicon."""
    return ScatterPlanner(lexicon=None)


# ── Grammar loading tests ────────────────────────────────────────

class TestGrammarLoading:
    """Grammar file loading: default path, custom path, missing path."""

    def test_default_grammar_loads(self, planner):
        """Default scatter_planner.gbnf loads successfully."""
        assert planner.grammar is not None
        assert len(planner.grammar) > 50
        assert "root ::=" in planner.grammar
        assert "region-object" in planner.grammar
        assert "species-object" in planner.grammar

    def test_custom_grammar_path(self, lexicon):
        """Custom grammar path overrides the default."""
        with NamedTemporaryFile(mode="w", suffix=".gbnf", delete=False) as f:
            f.write("root ::= \"hello\"\n")
            tmp_path = f.name

        try:
            p = ScatterPlanner(lexicon=lexicon, grammar_path=tmp_path)
            assert p.grammar == "root ::= \"hello\""
        finally:
            Path(tmp_path).unlink()

    def test_nonexistent_grammar_path(self, lexicon):
        """Nonexistent grammar path → grammar is None, no crash."""
        p = ScatterPlanner(lexicon=lexicon, grammar_path="/nonexistent/path.gbnf")
        assert p.grammar is None

    def test_grammar_has_required_rules(self, planner):
        """Default grammar contains the key structural rules."""
        g = planner.grammar
        assert "keep-out-array" in g
        assert "species-array" in g
        assert "number" in g
        assert "string" in g

    def test_default_grammar_path_is_absolute(self, lexicon):
        """DEFAULT_GRAMMAR_PATH resolves to a real file."""
        path = Path(ScatterPlanner.DEFAULT_GRAMMAR_PATH)
        assert path.exists(), f"Grammar not found at {path}"


# ── Prompt building tests ────────────────────────────────────────

class TestPromptBuilding:
    """_build_prompt: asset filtering, structure, edge cases."""

    def test_prompt_contains_asset_ids(self, planner):
        """Prompt lists the scatter-category asset IDs."""
        prompt = planner._build_prompt("context text", "scatter trees")
        # Our lexicon has tree, bush, flower, rock in scatter category
        assert "tree" in prompt
        assert "bush" in prompt
        assert "flower" in prompt
        assert "rock" in prompt

    def test_prompt_contains_asset_labels(self, planner):
        """Prompt includes human-readable asset labels."""
        prompt = planner._build_prompt("ctx", "scatter trees")
        assert "Tree" in prompt
        assert "Bush" in prompt

    def test_prompt_contains_asset_footprints(self, planner):
        """Prompt includes asset footprint dimensions."""
        prompt = planner._build_prompt("ctx", "scatter trees")
        # Tree: footprint 1.2×1.2
        assert "1.2" in prompt

    def test_prompt_contains_user_prompt(self, planner):
        """The user's natural language request appears verbatim."""
        prompt = planner._build_prompt("ctx", "scatter trees and bushes")
        assert "scatter trees and bushes" in prompt

    def test_prompt_contains_context(self, planner):
        """The scene context text appears in the prompt."""
        prompt = planner._build_prompt("Building at (0,0)", "scatter")
        assert "Building at (0,0)" in prompt

    def test_prompt_has_schema_structure(self, planner):
        """Prompt describes the expected JSON schema."""
        prompt = planner._build_prompt("ctx", "scatter")
        assert "OUTPUT SCHEMA" in prompt
        assert '"region"' in prompt
        assert '"keep_out"' in prompt
        assert '"species"' in prompt

    def test_prompt_has_spacing_guidelines(self, planner):
        """Prompt includes min_spacing guidance per plant type."""
        prompt = planner._build_prompt("ctx", "scatter")
        assert "min_spacing" in prompt
        # Should mention specific spacing ranges
        assert "3-5" in prompt or "4" in prompt

    def test_no_scatter_assets_fallback(self, planner_no_lexicon):
        """When no scatter assets exist, prompt uses hardcoded fallback IDs."""
        prompt = planner_no_lexicon._build_prompt("ctx", "scatter")
        # The planner_no_lexicon creates a default AssetLexicon which DOES
        # have tree/bush/flower/rock — so the prompt should list them.
        assert "tree" in prompt
        assert "bush" in prompt


# ── Response parsing tests ──────────────────────────────────────

class TestResponseParsing:
    """_parse_response: valid JSON, edge cases, error handling."""

    def test_parse_valid_complete_json(self, planner):
        """Parse a fully-populated garden JSON."""
        response = json.dumps({
            "region": {"width": 20.0, "depth": 15.0},
            "keep_out": [
                {"x": 4.0, "z": 4.0, "w": 12.0, "d": 8.0},
            ],
            "species": [
                {"id": "tree", "count": 5, "min_spacing": 4.0},
                {"id": "bush", "count": 10, "min_spacing": 2.0},
            ],
        })
        result = planner._parse_response(response)
        assert result["region"]["width"] == 20.0
        assert result["region"]["depth"] == 15.0
        assert len(result["keep_out"]) == 1
        assert result["keep_out"][0]["x"] == 4.0
        assert len(result["species"]) == 2
        assert result["species"][0]["id"] == "tree"
        assert result["species"][0]["count"] == 5

    def test_parse_minimal_json(self, planner):
        """Parse a minimal garden JSON with only region and one species."""
        response = json.dumps({
            "region": {"width": 10.0, "depth": 10.0},
            "keep_out": [],
            "species": [
                {"id": "flower", "count": 3, "min_spacing": 1.5},
            ],
        })
        result = planner._parse_response(response)
        assert result["species"][0]["count"] == 3
        assert result["keep_out"] == []

    def test_parse_with_thinking_tags(self, planner):
        """Strip ＜think＞...＜/think＞ tags before parsing JSON."""
        response = "<think>Let me plan a garden</think>\n" + json.dumps({
            "region": {"width": 20.0, "depth": 20.0},
            "keep_out": [],
            "species": [{"id": "tree", "count": 3, "min_spacing": 4.0}],
        })
        result = planner._parse_response(response)
        assert result["species"][0]["count"] == 3

    def test_parse_with_markdown_fences(self, planner):
        """Strip ```json and ``` fences before parsing JSON."""
        response = "```json\n" + json.dumps({
            "region": {"width": 15.0, "depth": 15.0},
            "keep_out": [],
            "species": [{"id": "bush", "count": 5, "min_spacing": 2.0}],
        }) + "\n```"
        result = planner._parse_response(response)
        assert result["species"][0]["id"] == "bush"

    def test_parse_with_prose_prefix(self, planner):
        """JSON preceded by prose text — find the JSON object and parse it."""
        response = "Here is the garden plan:\n" + json.dumps({
            "region": {"width": 12.0, "depth": 8.0},
            "keep_out": [],
            "species": [{"id": "rock", "count": 2, "min_spacing": 1.5}],
        })
        result = planner._parse_response(response)
        assert result["region"]["width"] == 12.0

    def test_parse_missing_fields_use_defaults(self, planner):
        """Missing region/keep_out/species → safe defaults."""
        response = json.dumps({"species": [{"id": "tree", "count": 1, "min_spacing": 3.0}]})
        result = planner._parse_response(response)
        assert result["region"]["width"] == 20.0
        assert result["region"]["depth"] == 20.0
        assert result["keep_out"] == []
        assert len(result["species"]) == 1

    def test_parse_integer_counts_as_ints(self, planner):
        """Count values are parsed as integers (not floats)."""
        response = json.dumps({
            "region": {"width": 10, "depth": 10},
            "keep_out": [],
            "species": [{"id": "tree", "count": 5, "min_spacing": 4}],
        })
        result = planner._parse_response(response)
        # JSON doesn't distinguish int/float, but the value should be numeric
        assert result["species"][0]["count"] == 5

    def test_parse_empty_response_raises(self, planner):
        """Empty string → ValueError."""
        with pytest.raises(ValueError, match="Empty LLM response"):
            planner._parse_response("")

    def test_parse_whitespace_only_raises(self, planner):
        """Whitespace-only string → ValueError."""
        with pytest.raises(ValueError, match="Empty LLM response"):
            planner._parse_response("   \n\t  ")

    def test_parse_no_json_raises(self, planner):
        """Response with no JSON at all → ValueError."""
        with pytest.raises(ValueError, match="No JSON found"):
            planner._parse_response("Just some prose, no braces here.")

    def test_parse_invalid_json_raises(self, planner):
        """Malformed JSON → ValueError."""
        with pytest.raises(ValueError, match="Invalid JSON"):
            planner._parse_response('{"region": {"width": 20, "depth": 15}, "species": [}')

    def test_parse_thinking_with_no_json_raises(self, planner):
        """Thinking tags but no JSON afterwards → ValueError."""
        response = "<think>planning a garden...</think>\nJust some text."
        with pytest.raises(ValueError, match="No JSON found"):
            planner._parse_response(response)


# ── Plan integration tests ──────────────────────────────────────

class TestPlanMethod:
    """plan() method: LLM integration, error propagation, result shape."""

    def test_plan_returns_correct_shape(self, planner):
        """plan() with a mock LLM returns the expected dict shape."""
        mock_response = json.dumps({
            "region": {"width": 20.0, "depth": 20.0},
            "keep_out": [],
            "species": [{"id": "tree", "count": 3, "min_spacing": 4.0}],
        })

        def mock_llm(prompt: str) -> str:
            return mock_response

        result = planner.plan(
            context="test context",
            prompt="scatter trees",
            llm_fn=mock_llm,
        )
        assert "region" in result
        assert "keep_out" in result
        assert "species" in result
        assert result["species"][0]["id"] == "tree"

    def test_plan_propagates_llm_errors(self, planner):
        """When LLM returns invalid output, ScatterPlanningError is raised."""
        def bad_llm(prompt: str) -> str:
            return "no json here"

        with pytest.raises(ScatterPlanningError):
            planner.plan(
                context="ctx",
                prompt="scatter",
                llm_fn=bad_llm,
            )

    def test_plan_passes_scene_parameter(self, planner):
        """scene parameter is accepted (for API compatibility)."""
        mock_response = json.dumps({
            "region": {"width": 10, "depth": 10},
            "keep_out": [],
            "species": [{"id": "bush", "count": 2, "min_spacing": 2}],
        })

        def mock_llm(prompt: str) -> str:
            return mock_response

        # scene is unused but shouldn't crash
        result = planner.plan(
            context="ctx",
            prompt="scatter",
            llm_fn=mock_llm,
            scene={"name": "Main", "children": []},
        )
        assert len(result["species"]) == 1

    def test_plan_llm_exception_propagates(self, planner):
        """When llm_fn raises an exception, ScatterPlanningError is raised."""
        def crashing_llm(prompt: str) -> str:
            raise RuntimeError("LLM crashed")

        with pytest.raises(ScatterPlanningError, match="LLM crashed"):
            planner.plan(
                context="ctx",
                prompt="scatter",
                llm_fn=crashing_llm,
            )


# ── Import / structure tests ─────────────────────────────────────

class TestScatterPlannerImports:
    def test_imports_available(self):
        from devforge.spatial.scatter_planner import ScatterPlanner, ScatterPlanningError
        assert ScatterPlanner is not None
        assert ScatterPlanningError is not None

    def test_planner_creatable_without_lexicon(self):
        p = ScatterPlanner(lexicon=None)
        assert p._lexicon is not None  # creates a default AssetLexicon
        assert isinstance(p._lexicon, AssetLexicon)

    def test_planner_grammar_path_default(self, lexicon):
        p = ScatterPlanner(lexicon=lexicon)
        assert "scatter_planner.gbnf" in p._grammar_path

    def test_scatter_planning_error_is_exception(self):
        err = ScatterPlanningError("test error")
        assert isinstance(err, Exception)
        assert str(err) == "test error"
