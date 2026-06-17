"""Unit tests for VoronoiPlanner. No live LLM — llm_fn is stubbed.

Mirrors test_wfc_planner.py: grammar loading, prompt building,
response parsing (think-tags / fences / prose / defaults),
the plan() method, and imports.
"""

from __future__ import annotations

import pytest

from devforge.spatial.voronoi_planner import VoronoiPlanner, VoronoiPlanningError


@pytest.fixture
def planner():
    return VoronoiPlanner()


# ── Imports ──────────────────────────────────────────────────────


class TestVoronoiPlannerImports:
    def test_planner_importable(self):
        assert VoronoiPlanner is not None

    def test_error_importable(self):
        assert issubclass(VoronoiPlanningError, Exception)

    def test_constructs(self, planner):
        assert isinstance(planner, VoronoiPlanner)


# ── Grammar loading ──────────────────────────────────────────────


class TestGrammarLoading:
    def test_grammar_loaded(self, planner):
        assert planner.grammar is not None and len(planner.grammar) > 0

    def test_missing_grammar_does_not_crash(self, tmp_path):
        p = VoronoiPlanner(grammar_path=tmp_path / "nope.gbnf")
        assert p.grammar is None  # warned, not raised


# ── Prompt building ──────────────────────────────────────────────


class TestPromptBuilding:
    def test_prompt_contains_schema_and_context(self, planner):
        prompt = planner._build_prompt("SCENE_CTX", "build a town")
        assert "region" in prompt and "districts" in prompt
        assert "build a town" in prompt
        assert "SCENE_CTX" in prompt

    def test_prompt_lists_district_types(self, planner):
        prompt = planner._build_prompt("", "x")
        for dtype in ("residential", "commercial", "industrial", "park", "civic"):
            assert dtype in prompt


# ── Response parsing ─────────────────────────────────────────────


class TestResponseParsing:
    def test_plain_json(self, planner):
        out = planner._parse_response(
            '{"region":{"width":100,"depth":80},"districts":6,"tile_size":3.0,"seed":7}',
        )
        assert out["region"] == {"width": 100, "depth": 80}
        assert out["districts"] == 6
        assert out["tile_size"] == 3.0
        assert out["seed"] == 7

    def test_strips_think_tags(self, planner):
        out = planner._parse_response(
            '<think>hmm</think>{"region":{"width":60,"depth":60},"districts":4}',
        )
        assert out["region"]["width"] == 60

    def test_strips_markdown_fence(self, planner):
        out = planner._parse_response(
            '```json\n{"region":{"width":80,"depth":80},"districts":5}\n```',
        )
        assert out["districts"] == 5

    def test_prose_prefix(self, planner):
        out = planner._parse_response(
            'Sure! Here it is: {"region":{"width":70,"depth":70},"districts":7} done',
        )
        assert out["region"]["width"] == 70

    def test_defaults_applied(self, planner):
        out = planner._parse_response("{}")
        assert out["region"] == {"width": 80, "depth": 80}
        assert out["districts"] == 5
        assert out["tile_size"] == 4.0
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
        out = planner.plan(
            context="",
            prompt="a town with 6 districts",
            llm_fn=lambda p: '{"region":{"width":100,"depth":100},"districts":6}',
        )
        assert out["region"] == {"width": 100, "depth": 100}
        assert out["districts"] == 6

    def test_plan_wraps_llm_errors(self, planner):
        def boom(_):
            raise RuntimeError("llm down")

        with pytest.raises(VoronoiPlanningError):
            planner.plan(context="", prompt="x", llm_fn=boom)

    def test_plan_wraps_unparseable(self, planner):
        with pytest.raises(VoronoiPlanningError):
            planner.plan(context="", prompt="x", llm_fn=lambda p: "garbage no json")
