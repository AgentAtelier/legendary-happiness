"""Unit tests for RoomIntentPlanner. No live LLM — llm_fn is stubbed.

Mirrors test_wfc_planner.py: grammar loading, prompt building, response
parsing (think-tags / fences / prose / defaults / graceful degradation),
the plan() method, and imports.
"""

from __future__ import annotations

import pytest

from devforge.spatial.room_intent_planner import RoomIntentPlanner, RoomPlanningError


@pytest.fixture
def planner():
    return RoomIntentPlanner()


@pytest.fixture
def planner_no_grammar(tmp_path):
    return RoomIntentPlanner(grammar_path=tmp_path / "nope.gbnf")


# ── Imports ──────────────────────────────────────────────────────


class TestRoomIntentPlannerImports:
    def test_planner_importable(self):
        assert RoomIntentPlanner is not None

    def test_error_importable(self):
        assert issubclass(RoomPlanningError, Exception)

    def test_constructs(self, planner):
        assert isinstance(planner, RoomIntentPlanner)

    def test_lexicon_accessible(self, planner):
        """Lexicon is loaded and has asset IDs."""
        assert planner._lexicon is not None
        assert len(planner._lexicon.asset_ids) > 0


# ── Grammar loading ──────────────────────────────────────────────


class TestGrammarLoading:
    def test_grammar_loaded(self, planner):
        assert planner.grammar is not None and len(planner.grammar) > 0

    def test_grammar_contains_room_type_key(self, planner):
        """Grammar constrains room_type as required."""
        # GBNF uses escaped quotes: \"room_type\"
        assert 'room_type' in planner.grammar

    def test_grammar_constrains_size(self, planner):
        """Grammar enumerates cramped/normal/spacious."""
        assert 'cramped' in planner.grammar
        assert 'normal' in planner.grammar
        assert 'spacious' in planner.grammar

    def test_grammar_constrains_style(self, planner):
        """Grammar enumerates rustic/industrial/noble/derelict."""
        for style in ("rustic", "industrial", "noble", "derelict"):
            assert style in planner.grammar

    def test_missing_grammar_does_not_crash(self, planner_no_grammar):
        assert planner_no_grammar.grammar is None  # warned, not raised


# ── Prompt building ──────────────────────────────────────────────


class TestPromptBuilding:
    def test_prompt_contains_schema_fields(self, planner):
        prompt = planner._build_prompt("SCENE_CTX", "build a kitchen")
        for field in ("room_type", "size", "style", "clutter",
                       "mood_tags", "must_have", "special_features", "seed"):
            assert field in prompt, f"'{field}' missing from prompt"

    def test_prompt_contains_context(self, planner):
        prompt = planner._build_prompt("SCENE_CTX_HERE", "x")
        assert "SCENE_CTX_HERE" in prompt

    def test_prompt_contains_user_request(self, planner):
        prompt = planner._build_prompt("", "build a cramped abandoned kitchen")
        assert "build a cramped abandoned kitchen" in prompt

    def test_prompt_lists_room_types(self, planner):
        prompt = planner._build_prompt("", "x")
        for rt in ("kitchen", "living_room", "bedroom", "library", "workshop"):
            assert rt in prompt

    def test_prompt_lists_known_features(self, planner):
        prompt = planner._build_prompt("", "x")
        for feat in ("secret_passage", "fireplace", "skylight", "loft"):
            assert feat in prompt

    def test_prompt_lists_known_moods(self, planner):
        prompt = planner._build_prompt("", "x")
        for mood in ("abandoned", "cozy", "grand", "haunted"):
            assert mood in prompt

    def test_prompt_lists_indoor_assets(self, planner):
        """Prompt includes asset IDs from the lexicon for must_have guidance."""
        prompt = planner._build_prompt("", "x")
        # Should list common indoor assets
        for asset in ("stove", "table", "chair"):
            assert asset in prompt

    def test_prompt_includes_rules(self, planner):
        prompt = planner._build_prompt("", "x")
        assert "REQUIRED" in prompt
        assert "JSON only" in prompt


# ── Response parsing — valid inputs ──────────────────────────────


class TestResponseParsing:
    def test_plain_json_minimal(self, planner):
        """Minimal descriptor — room_type only, all other fields default."""
        out = planner._parse_response('{"room_type":"kitchen"}')
        assert out["room_type"] == "kitchen"
        assert "size" not in out
        assert "style" not in out
        assert "clutter" not in out

    def test_plain_json_full(self, planner):
        """Full descriptor — all fields present."""
        out = planner._parse_response(
            '{"room_type":"library","size":"spacious","style":"noble",'
            '"clutter":0.7,"mood_tags":["cozy","grand"],'
            '"must_have":["table","shelf"],'
            '"special_features":["fireplace","skylight"],"seed":42}'
        )
        assert out["room_type"] == "library"
        assert out["size"] == "spacious"
        assert out["style"] == "noble"
        assert out["clutter"] == 0.7
        assert out["mood_tags"] == ["cozy", "grand"]
        assert out["must_have"] == ["table", "shelf"]
        assert out["special_features"] == ["fireplace", "skylight"]
        assert out["seed"] == 42

    def test_strips_think_tags(self, planner):
        out = planner._parse_response(
            '<think>hmm what room</think>{"room_type":"bedroom"}'
        )
        assert out["room_type"] == "bedroom"

    def test_strips_markdown_fence(self, planner):
        out = planner._parse_response(
            '```json\n{"room_type":"living_room"}\n```'
        )
        assert out["room_type"] == "living_room"

    def test_prose_prefix(self, planner):
        out = planner._parse_response(
            'Sure! Here is your descriptor: {"room_type":"kitchen","size":"cramped"}'
        )
        assert out["room_type"] == "kitchen"
        assert out["size"] == "cramped"

    def test_prose_suffix(self, planner):
        out = planner._parse_response(
            '{"room_type":"study","size":"normal"} Hope that helps!'
        )
        assert out["room_type"] == "study"
        assert out["size"] == "normal"

    def test_clutter_as_int(self, planner):
        """Clutter can be an integer."""
        out = planner._parse_response('{"room_type":"workshop","clutter":1}')
        assert out["clutter"] == 1.0

    def test_clutter_clamped_high(self, planner):
        """Clutter > 1.0 is clamped to 1.0."""
        out = planner._parse_response('{"room_type":"hallway","clutter":5.0}')
        assert out["clutter"] == 1.0

    def test_clutter_clamped_low(self, planner):
        """Clutter < 0.0 is clamped to 0.0."""
        out = planner._parse_response('{"room_type":"hallway","clutter":-2.5}')
        assert out["clutter"] == 0.0

    def test_mood_tags_filtered_non_strings(self, planner):
        """Non-string mood tags are dropped."""
        out = planner._parse_response(
            '{"room_type":"attic","mood_tags":["abandoned",42,null,"cozy"]}'
        )
        assert out["mood_tags"] == ["abandoned", "cozy"]

    def test_must_have_unknown_assets_dropped(self, planner):
        """must_have assets not in lexicon are filtered out."""
        out = planner._parse_response(
            '{"room_type":"kitchen","must_have":["stove","dragon_egg","fridge"]}'
        )
        # dragon_egg is not a real asset — dropped
        assert "must_have" in out
        assert "dragon_egg" not in out["must_have"]
        assert "stove" in out["must_have"]
        assert "fridge" in out["must_have"]

    def test_seed_as_integer(self, planner):
        out = planner._parse_response('{"room_type":"cellar","seed":1234}')
        assert out["seed"] == 1234

    def test_seed_as_negative(self, planner):
        out = planner._parse_response('{"room_type":"cellar","seed":-1}')
        assert out["seed"] == -1

    def test_seed_omitted(self, planner):
        out = planner._parse_response('{"room_type":"porch"}')
        assert "seed" not in out

    def test_unknown_room_type_accepted(self, planner):
        """room_type is free text — engine falls back gracefully."""
        out = planner._parse_response('{"room_type":"spaceship_bridge"}')
        assert out["room_type"] == "spaceship_bridge"


# ── Response parsing — graceful degradation ─────────────────────


class TestGracefulDegradation:
    def test_unknown_size_logged_and_skipped(self, planner):
        """Unknown size value is logged but not included in descriptor."""
        out = planner._parse_response(
            '{"room_type":"kitchen","size":"enormous"}'
        )
        assert "size" not in out  # skipped

    def test_unknown_style_logged_and_skipped(self, planner):
        """Unknown style value is logged but not included."""
        out = planner._parse_response(
            '{"room_type":"kitchen","style":"cyberpunk"}'
        )
        assert "style" not in out  # skipped

    def test_valid_size_passes_through(self, planner):
        for size in ("cramped", "normal", "spacious"):
            out = planner._parse_response(
                f'{{"room_type":"kitchen","size":"{size}"}}'
            )
            assert out["size"] == size

    def test_valid_style_passes_through(self, planner):
        for style in ("rustic", "industrial", "noble", "derelict"):
            out = planner._parse_response(
                f'{{"room_type":"kitchen","style":"{style}"}}'
            )
            assert out["style"] == style

    def test_mixed_valid_invalid_moods(self, planner):
        """Known moods pass through, unknown silently dropped."""
        out = planner._parse_response(
            '{"room_type":"living_room",'
            '"mood_tags":["cozy","not_a_mood","grand","also_fake"]}'
        )
        # All are strings so all pass the type filter; RoomIntentPlanner
        # doesn't filter mood_tags against KNOWN_MOODS — that's the engine's job
        assert "cozy" in out["mood_tags"]
        assert "grand" in out["mood_tags"]

    def test_empty_arrays_preserved(self, planner):
        """Empty arrays are valid."""
        out = planner._parse_response(
            '{"room_type":"kitchen","mood_tags":[],"must_have":[],"special_features":[]}'
        )
        assert out["mood_tags"] == []
        # Empty must_have array means no forced assets (descriptor doesn't
        # include the key since the list is empty)
        # Empty special_features is fine
        assert out["special_features"] == []


# ── Response parsing — errors ───────────────────────────────────


class TestResponseParsingErrors:
    def test_empty_raises(self, planner):
        with pytest.raises(ValueError):
            planner._parse_response("")

    def test_whitespace_only_raises(self, planner):
        with pytest.raises(ValueError):
            planner._parse_response("   \n  \t  ")

    def test_no_json_raises(self, planner):
        with pytest.raises(ValueError):
            planner._parse_response("no json here at all")

    def test_malformed_json_raises(self, planner):
        with pytest.raises(ValueError):
            planner._parse_response('{"room_type":"kitchen",}')

    def test_no_room_type_still_works(self, planner):
        """Missing room_type defaults to 'kitchen'."""
        out = planner._parse_response('{"size":"cramped"}')
        assert out["room_type"] == "kitchen"


# ── plan() method ───────────────────────────────────────────────


class TestPlanMethod:
    def test_plan_returns_parsed_minimal(self, planner):
        """plan() with a stubbed LLM returns a valid descriptor."""
        out = planner.plan(
            context="",
            prompt="build a kitchen",
            llm_fn=lambda p: '{"room_type":"kitchen"}',
        )
        assert out["room_type"] == "kitchen"

    def test_plan_returns_full_descriptor(self, planner):
        """plan() handles all fields."""
        out = planner.plan(
            context="ctx", prompt="make a grand library",
            llm_fn=lambda p: (
                '{"room_type":"library","size":"spacious","style":"noble",'
                '"clutter":0.5,"mood_tags":["grand"],'
                '"must_have":["table"],"special_features":["fireplace"],'
                '"seed":99}'
            ),
        )
        assert out["room_type"] == "library"
        assert out["size"] == "spacious"
        assert out["style"] == "noble"
        assert out["clutter"] == 0.5
        assert out["mood_tags"] == ["grand"]
        assert out["must_have"] == ["table"]
        assert out["special_features"] == ["fireplace"]
        assert out["seed"] == 99

    def test_plan_wraps_llm_errors(self, planner):
        def boom(_):
            raise RuntimeError("llm down")
        with pytest.raises(RoomPlanningError):
            planner.plan(context="", prompt="x", llm_fn=boom)

    def test_plan_wraps_unparseable(self, planner):
        with pytest.raises(RoomPlanningError):
            planner.plan(
                context="", prompt="x",
                llm_fn=lambda p: "garbage no json",
            )

    def test_plan_accepts_skip_cache(self, planner):
        """skip_cache parameter is accepted (forward-compat)."""
        out = planner.plan(
            context="",
            prompt="build a kitchen",
            llm_fn=lambda p: '{"room_type":"kitchen"}',
            skip_cache=True,
        )
        assert out["room_type"] == "kitchen"

    def test_plan_passes_context_to_llm(self, planner):
        """Verify context appears in the prompt sent to LLM."""
        sent_prompts = []

        def capture(p):
            sent_prompts.append(p)
            return '{"room_type":"hallway"}'

        planner.plan(
            context="EXISTING_BUILDING", prompt="add a hallway",
            llm_fn=capture,
        )
        assert len(sent_prompts) == 1
        assert "EXISTING_BUILDING" in sent_prompts[0]
        assert "add a hallway" in sent_prompts[0]


# ── Known constants ─────────────────────────────────────────────


class TestConstants:
    def test_room_types_contains_core(self):
        assert "kitchen" in RoomIntentPlanner.ROOM_TYPES
        assert "living_room" in RoomIntentPlanner.ROOM_TYPES
        assert "bedroom" in RoomIntentPlanner.ROOM_TYPES

    def test_known_features_non_empty(self):
        assert len(RoomIntentPlanner.KNOWN_FEATURES) > 0
        assert "fireplace" in RoomIntentPlanner.KNOWN_FEATURES

    def test_known_moods_non_empty(self):
        assert len(RoomIntentPlanner.KNOWN_MOODS) > 0
        assert "abandoned" in RoomIntentPlanner.KNOWN_MOODS
