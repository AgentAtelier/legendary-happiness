"""Unit tests for WFCPlanner. No live LLM — llm_fn is stubbed.

Mirrors test_scatter_planner.py / test_ssp_planner.py: grammar loading,
prompt building, response parsing (think-tags / fences / prose / defaults),
the plan() method, and imports.
"""

from __future__ import annotations

import pytest

from devforge.spatial.wfc_planner import WFCPlanner, WFCPlanningError


@pytest.fixture
def planner():
    return WFCPlanner()


# ── Imports ──────────────────────────────────────────────────────


class TestWFCPlannerImports:
    def test_planner_importable(self):
        assert WFCPlanner is not None

    def test_error_importable(self):
        assert issubclass(WFCPlanningError, Exception)

    def test_constructs(self, planner):
        assert isinstance(planner, WFCPlanner)


# ── Grammar loading ──────────────────────────────────────────────


class TestGrammarLoading:
    def test_grammar_loaded(self, planner):
        assert planner.grammar is not None and len(planner.grammar) > 0

    def test_missing_grammar_does_not_crash(self, tmp_path):
        p = WFCPlanner(grammar_path=tmp_path / "nope.gbnf")
        assert p.grammar is None  # warned, not raised


# ── Prompt building ──────────────────────────────────────────────


class TestPromptBuilding:
    def test_prompt_contains_schema_and_context(self, planner):
        prompt = planner._build_prompt("SCENE_CTX", "build a dungeon")
        assert "size" in prompt and "tile_size" in prompt
        assert "build a dungeon" in prompt
        assert "SCENE_CTX" in prompt

    def test_prompt_lists_tile_types(self, planner):
        prompt = planner._build_prompt("", "x")
        for tile in ("floor", "wall", "corridor", "door"):
            assert tile in prompt


# ── Response parsing ─────────────────────────────────────────────


class TestResponseParsing:
    def test_plain_json(self, planner):
        out = planner._parse_response('{"size":{"width":10,"depth":12},"tile_size":1.5,"seed":3}')
        assert out["size"] == {"width": 10, "depth": 12}
        assert out["tile_size"] == 1.5
        assert out["seed"] == 3

    def test_strips_think_tags(self, planner):
        out = planner._parse_response('<think>hmm</think>{"size":{"width":8,"depth":8}}')
        assert out["size"]["width"] == 8

    def test_strips_markdown_fence(self, planner):
        out = planner._parse_response('```json\n{"size":{"width":6,"depth":6}}\n```')
        assert out["size"]["depth"] == 6

    def test_prose_prefix(self, planner):
        out = planner._parse_response('Sure! Here it is: {"size":{"width":9,"depth":9}} done')
        assert out["size"]["width"] == 9

    def test_defaults_applied(self, planner):
        out = planner._parse_response("{}")
        assert out["size"] == {"width": 8, "depth": 8}
        assert out["tile_size"] == 2.0
        assert out["seed"] is None

    def test_empty_raises(self, planner):
        with pytest.raises(ValueError):
            planner._parse_response("")

    def test_no_json_raises(self, planner):
        with pytest.raises(ValueError):
            planner._parse_response("no json here at all")


# ── plan() ───────────────────────────────────────────────────────


class TestPlanMethod:
    def test_plan_returns_parsed(self, planner):
        """Non-keyword prompt exercises the LLM path (skip-heuristic won't match)."""
        out = planner.plan(
            context="",
            prompt="a winding underground complex",
            llm_fn=lambda p: '{"size":{"width":11,"depth":7},"tile_size":2.5}',
        )
        assert out["size"] == {"width": 11, "depth": 7}
        assert out["tile_size"] == 2.5

    def test_skip_heuristic_keyword_returns_default(self, planner):
        """Keyword 'dungeon' triggers the heuristic — returns default, no LLM call."""

        def should_not_be_called(_):
            raise RuntimeError("LLM was called but heuristic should have intercepted")

        out = planner.plan(
            context="",
            prompt="build a dungeon",
            llm_fn=should_not_be_called,
        )
        assert "size" in out
        assert out["size"]["width"] == 10 and out["size"]["depth"] == 10
        assert out["tile_size"] == 2.0

    def test_skip_heuristic_cave_keyword(self, planner):
        """Keyword 'cave' → 8×8, 2.5m tile size."""
        out = planner._try_heuristic("a dark cave system")
        assert out is not None
        assert out["size"] == {"width": 8, "depth": 8}
        assert out["tile_size"] == 2.5

    def test_skip_heuristic_maze_keyword(self, planner):
        """Keyword 'maze' → 12×12, 1.5m tile size."""
        out = planner._try_heuristic("generate a maze")
        assert out is not None
        assert out["size"] == {"width": 12, "depth": 12}
        assert out["tile_size"] == 1.5

    def test_skip_heuristic_no_match_returns_none(self, planner):
        """Non-keyword prompt → heuristic returns None, LLM path used."""
        out = planner._try_heuristic("a winding underground complex")
        assert out is None

    def test_plan_wraps_llm_errors(self, planner):
        def boom(_):
            raise RuntimeError("llm down")

        with pytest.raises(WFCPlanningError):
            planner.plan(context="", prompt="an empty dimensional void", llm_fn=boom)

    def test_plan_wraps_unparseable(self, planner):
        with pytest.raises(WFCPlanningError):
            planner.plan(context="", prompt="x", llm_fn=lambda p: "garbage no json")
