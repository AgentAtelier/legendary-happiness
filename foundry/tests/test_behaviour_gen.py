"""Tests for QuestBehaviourPlanner — quest-spec grammar + behaviour-gen call.

The deterministic core needs NO live LLM.  All plan() tests pass a
FAKE callable so the manifest validation, dialogue validation, NPC role
validation, and Decision Point emission can be exercised deterministically.

Tests (per P1 + P2 TDD spec):
  (a) manifest of 4 props → spec references a real id
  (b) LLM returns a dangling id → auto-recover + DP (P2: non-blocking)
  (c) junk dialogue → fallback fires
  (d) good dialogue → passes through
  (e) NPC role empty → default + DP
  (f) NPC role too long / duplicated → cleaned + DP
  (g) all quest DPs carry actionable choices
"""

from __future__ import annotations

import json
import socket

import pytest
from behaviour_gen import _DEFAULT_NPC_ROLE, _MAX_NPC_ROLE_LEN, QuestBehaviourPlanner, _validate_npc_role
from llm import load_grammar

# ── Test manifest (4 props) ──────────────────────────────────────

_MANIFEST_4: list[dict] = [
    {"id": "table_0", "category": "table", "material": "worn_oak", "wear": 0.8},
    {"id": "shelf_0", "category": "shelf", "material": "rough_granite", "wear": 0.15},
    {"id": "cabinet_0", "category": "cabinet", "material": "wrought_iron", "wear": 0.8},
    {"id": "table_1", "category": "table", "material": "dark_walnut", "wear": 0.15},
]

_VALID_MANIFEST_IDS = {"table_0", "shelf_0", "cabinet_0", "table_1"}


# ── Grammar normalisation tests ──────────────────────────────────

def _load_quest_grammar() -> str:
    from pathlib import Path as _Path
    _grammar_path = str(_Path(__file__).resolve().parents[1] / "grammar" / "quest_spec.gbnf")
    return load_grammar(_grammar_path)


def test_quest_grammar_no_line_starts_with_pipe():
    """No line of the normalized quest grammar starts with |."""
    grammar = _load_quest_grammar()
    for i, line in enumerate(grammar.split("\n")):
        stripped = line.strip()
        assert not stripped.startswith("|"), (
            f"Line {i} starts with '|': {line!r}"
        )


def test_quest_grammar_contains_dialogue_keys():
    """The quest grammar constrains the dialogue object keys."""
    grammar = _load_quest_grammar()
    assert "greet" in grammar
    assert "ask" in grammar
    assert "wrong" in grammar
    assert "thank" in grammar


def test_quest_grammar_is_single_line_root():
    """After normalize_gbnf, the root rule is one line."""
    grammar = _load_quest_grammar()
    root_lines = [
        l for l in grammar.split("\n")
        if l.strip().startswith("root ") and "::=" in l
    ]
    assert len(root_lines) == 1, (
        f"expected one root rule line, got {len(root_lines)}: {root_lines}"
    )


# ── Prompt tests ─────────────────────────────────────────────────

def test_build_prompt_contains_room_theme_and_manifest():
    planner = QuestBehaviourPlanner()
    prompt = planner.build_prompt("a hermit's shack", _MANIFEST_4)
    assert "a hermit's shack" in prompt
    assert "table_0" in prompt
    assert "shelf_0" in prompt
    assert "cabinet_0" in prompt
    assert "table_1" in prompt
    # EB-7b: manifest lines now include material adjective: "id (adj category)"
    assert "(wooden table)" in prompt
    assert "(stone shelf)" in prompt
    assert "(brass cabinet)" in prompt


def test_build_prompt_contains_example():
    planner = QuestBehaviourPlanner()
    prompt = planner.build_prompt("a test room", _MANIFEST_4)
    assert "Example:" in prompt
    assert '"npc_role"' in prompt
    assert '"target_entity"' in prompt
    assert '"dialogue"' in prompt
    assert '"objective"' in prompt


# ── Parse tests ──────────────────────────────────────────────────

def test_parse_valid_quest_json():
    planner = QuestBehaviourPlanner()
    raw = json.dumps({
        "npc_role": "hermit",
        "target_entity": "shelf_0",
        "dialogue": {
            "greet": "Hello!",
            "ask": "Find my book on the shelf.",
            "wrong": "That is not it.",
            "thank": "You found it!",
        },
        "objective": {
            "type": "fetch",
            "target": "shelf_0",
            "giver": "npc",
        },
    })
    spec = planner.parse(raw)
    assert spec["npc_role"] == "hermit"
    assert spec["target_entity"] == "shelf_0"
    assert spec["dialogue"]["greet"] == "Hello!"
    assert spec["objective"]["type"] == "fetch"


def test_parse_with_markdown_fences():
    planner = QuestBehaviourPlanner()
    raw = '```json\n{"npc_role":"hermit","target_entity":"table_0","dialogue":{"greet":"Hi","ask":"Find a book","wrong":"Not it","thank":"Thanks"},"objective":{"type":"fetch","target":"table_0","giver":"npc"}}\n```'  # noqa: E501  test-data
    spec = planner.parse(raw)
    assert spec["npc_role"] == "hermit"
    assert spec["target_entity"] == "table_0"


def test_parse_with_think_tags():
    planner = QuestBehaviourPlanner()
    raw = '<think>I should pick a hermit</think>\n{"npc_role":"hermit","target_entity":"table_0","dialogue":{"greet":"Hi","ask":"Find a book","wrong":"Not it","thank":"Thanks"},"objective":{"type":"fetch","target":"table_0","giver":"npc"}}'  # noqa: E501  test-data
    spec = planner.parse(raw)
    assert spec["npc_role"] == "hermit"


def test_parse_ignores_trailing_content_after_json():
    """Ungrammared models (multi-NPC path) often append prose or an unclosed
    <think> AFTER the JSON object. parse() must extract just the first complete
    object via raw_decode — json.loads(text[start:]) rejected the 'Extra data'
    and collapsed the whole quest to canned fallbacks intermittently."""
    planner = QuestBehaviourPlanner()
    raw = (
        '{"npc_0":{"npc_role":"blacksmith","target_entity":"key_0",'
        '"dialogue":{"greet":"Hail","ask":"Find it","wrong":"No","thank":"Ta"},'
        '"objective":{"type":"fetch","target":"key_0","giver":"npc"}}}\n\n'
        '<think>\nNow let me reconsider whether the apprentice should...\n'  # unclosed think + prose
    )
    spec = planner.parse(raw)
    assert spec["npc_0"]["npc_role"] == "blacksmith"


def test_parse_empty_text_raises():
    planner = QuestBehaviourPlanner()
    with pytest.raises(ValueError, match="Empty"):
        planner.parse("")


def test_parse_no_json_raises():
    planner = QuestBehaviourPlanner()
    with pytest.raises(ValueError, match="No JSON"):
        planner.parse("hello world")


# ── Fake LLMs ────────────────────────────────────────────────────

def _fake_llm_valid(prompt: str, grammar: str | None = None,
                     json_schema: dict | None = None) -> str:
    """Returns a valid quest spec with good dialogue referencing shelf_0."""
    return json.dumps({
        "npc_role": "hermit",
        "target_entity": "shelf_0",
        "dialogue": {
            "greet": "Ah, a visitor! Welcome.",
            "ask": "I have lost something on the shelf. Can you find it?",
            "wrong": "No, that is not the shelf item.",
            "thank": "Yes, you found my shelf item! Thank you.",
        },
        "objective": {
            "type": "fetch",
            "target": "shelf_0",
            "giver": "npc",
        },
    })


def _fake_llm_dangling(prompt: str, grammar: str | None = None,
                       json_schema: dict | None = None) -> str:
    """Returns a quest spec with a target_entity NOT in the manifest."""
    return json.dumps({
        "npc_role": "hermit",
        "target_entity": "dragon_gold",
        "dialogue": {
            "greet": "Hello.",
            "ask": "Find my gold.",
            "wrong": "Not it.",
            "thank": "Thanks!",
        },
        "objective": {
            "type": "fetch",
            "target": "dragon_gold",
            "giver": "npc",
        },
    })


def _fake_llm_junk_dialogue(prompt: str, grammar: str | None = None,
                            json_schema: dict | None = None) -> str:
    """Returns a quest spec with invalid dialogue lines."""
    return json.dumps({
        "npc_role": "hermit",
        "target_entity": "table_0",
        "dialogue": {
            "greet": "",                    # empty — too short
            "ask": "<script>alert(1)</script>",  # code injection
            "wrong": "```\ncode block\n```",      # markdown code fence
            "thank": "x",                   # too short (< 3 chars)
        },
        "objective": {
            "type": "fetch",
            "target": "table_0",
            "giver": "npc",
        },
    })


def _fake_llm_short_dialogue(prompt: str, grammar: str | None = None,
                              json_schema: dict | None = None) -> str:
    """Returns a quest spec with dialogue lines that pass length but
    fail quest-relevance (no quest word, no category mention)."""
    return json.dumps({
        "npc_role": "hermit",
        "target_entity": "cabinet_0",
        "dialogue": {
            "greet": "Hello.",            # barely passes length, no quest word
            "ask": "Where is it?",        # no quest word, no category
            "wrong": "Hmm.",              # barely passes length
            "thank": "Finally.",          # no quest word, no category
        },
        "objective": {
            "type": "fetch",
            "target": "cabinet_0",
            "giver": "npc",
        },
    })


# ── plan() tests with FAKE llm ────────────────────────────────────

# (a) Manifest of 4 props → spec references a real id

def test_plan_with_valid_manifest_and_good_dialogue():
    """A 4-prop manifest + valid LLM → quest spec with real target id,
    good dialogue passes through, no decisions emitted."""
    planner = QuestBehaviourPlanner()
    spec, decisions = planner.plan(
        "a hermit's shack", _MANIFEST_4, _fake_llm_valid
    )
    assert spec["target_entity"] == "shelf_0"
    assert spec["target_entity"] in _VALID_MANIFEST_IDS
    assert spec["npc_role"] == "hermit"
    assert spec["dialogue"]["greet"] == "Ah, a visitor! Welcome."
    assert spec["dialogue"]["ask"] == "I have lost something on the shelf. Can you find it?"
    assert spec["objective"]["type"] == "fetch"
    assert spec["objective"]["target"] == "shelf_0"
    assert spec["objective"]["giver"] == "npc"
    assert decisions == []  # no issues


# (b) LLM returns a dangling id → auto-recover + DecisionPoint (P2: non-blocking)

def test_plan_dangling_target_auto_recovers():
    """P2: dangling target is now non-blocking.  The pipeline auto-picks
    the first available prop and emits a quest.dangling_target DP with
    actionable choices."""
    planner = QuestBehaviourPlanner()
    spec, decisions = planner.plan(
        "a test room", _MANIFEST_4, _fake_llm_dangling
    )

    # Auto-recovered: should pick the first available prop alphabetically
    assert spec["target_entity"] in _VALID_MANIFEST_IDS
    assert spec["target_entity"] == sorted(_VALID_MANIFEST_IDS)[0]  # cabinet_0
    # Dangling DP emitted
    dangling_dps = [d for d in decisions if d.code == "quest.dangling_target"]
    assert len(dangling_dps) == 1
    dp = dangling_dps[0]
    assert dp.severity == "error"
    assert dp.context["entity"] == "dragon_gold"
    # Choices should exist (P2: actionable)
    assert len(dp.choices) >= 1
    # First choice should set a real target entity
    assert dp.choices[0].apply.get("field") == "target_entity"
    assert dp.choices[0].apply["value"] in _VALID_MANIFEST_IDS


def test_dangling_target_dp_has_actionable_choices():
    """The dangling target DP carries choices: auto-pick + re-run."""
    planner = QuestBehaviourPlanner()
    _, decisions = planner.plan("a room", _MANIFEST_4, _fake_llm_dangling)
    dp = next(d for d in decisions if d.code == "quest.dangling_target")
    choice_labels = {c.label for c in dp.choices}
    assert "cabinet_0" in choice_labels  # auto-pick choice
    assert "Re-run" in choice_labels      # retry choice


def test_dangling_target_also_recovers_empty_npc_role():
    """When the LLM returns both a dangling target AND an empty npc_role,
    both recover: target auto-picks, role defaults to villager."""
    def fake_dangling_empty_role(prompt, grammar):
        return json.dumps({
            "npc_role": "",
            "target_entity": "dragon_gold",
            "dialogue": {
                "greet": "Hello traveler, can you help me find something?",
                "ask": "Find my missing item!",
                "wrong": "Not what I need.",
                "thank": "Thank you, you found it!",
            },
            "objective": {"type": "fetch", "target": "dragon_gold", "giver": "npc"},
        })

    planner = QuestBehaviourPlanner()
    spec, decisions = planner.plan("a room", _MANIFEST_4, fake_dangling_empty_role)
    assert spec["npc_role"] == _DEFAULT_NPC_ROLE
    assert spec["target_entity"] in _VALID_MANIFEST_IDS


# (c) Junk dialogue → fallback fires

def test_plan_junk_dialogue_fallback_fires():
    """Dialogue with empty lines, code injection, markdown → fallback
    substituted for each bad line, and dialogue_fallback DPs emitted."""
    planner = QuestBehaviourPlanner()
    spec, decisions = planner.plan(
        "a test room", _MANIFEST_4, _fake_llm_junk_dialogue
    )

    # All four fields should have fallback values (since all were invalid)
    assert spec["target_entity"] == "table_0"
    from dialogue_validator import fallback_dialogue
    # P-E: fallback now includes the material adjective ("wooden table")
    fallback = fallback_dialogue("table", adjective="wooden")
    for field in ("greet", "ask", "wrong", "thank"):
        assert spec["dialogue"][field] == fallback[field], (
            f"field {field}: expected fallback {fallback[field]!r}, "
            f"got {spec['dialogue'][field]!r}"
        )

    # Should have 4 dialogue_fallback DPs (one per field)
    fallback_dps = [d for d in decisions if d.code == "quest.dialogue_fallback"]
    assert len(fallback_dps) == 4
    fields = {d.context["field"] for d in fallback_dps}
    assert fields == {"greet", "ask", "wrong", "thank"}


# (d) Good dialogue → passes through

def test_plan_good_dialogue_passes_through():
    """Dialogue that passes all validations → no fallback, no DPs."""
    planner = QuestBehaviourPlanner()
    spec, decisions = planner.plan(
        "a hermit's shack", _MANIFEST_4, _fake_llm_valid
    )

    assert spec["dialogue"]["greet"] == "Ah, a visitor! Welcome."
    assert spec["dialogue"]["ask"] == "I have lost something on the shelf. Can you find it?"
    assert spec["dialogue"]["wrong"] == "No, that is not the shelf item."
    assert spec["dialogue"]["thank"] == "Yes, you found my shelf item! Thank you."
    # No decisions — good dialogue shouldn't emit anything
    assert decisions == []


def test_plan_short_irrelevant_dialogue_gets_fallback():
    """Dialogue that passes length but fails quest-relevance → fallback
    fires for those lines.  Short greetings like 'Hello.' now pass
    (hello is a valid NPC opener, word-boundary match); truly irrelevant
    lines ('Where is it?', 'Hmm.', 'Finally.') trigger fallback."""
    planner = QuestBehaviourPlanner()
    spec, decisions = planner.plan(
        "a test room", _MANIFEST_4, _fake_llm_short_dialogue
    )

    # target is cabinet_0 → category is "cabinet", material "wrought_iron" → adjective "brass"
    from dialogue_validator import fallback_dialogue
    fallback = fallback_dialogue("cabinet", adjective="brass")

    # "Hello." → passes ("hello" is a valid NPC greeting word, \b match)
    assert spec["dialogue"]["greet"] == "Hello."
    # "Where is it?" → fails (no quest word on \b boundaries) → fallback
    assert spec["dialogue"]["ask"] == fallback["ask"]
    # "Hmm." → fails (no quest word) → fallback
    assert spec["dialogue"]["wrong"] == fallback["wrong"]
    # "Finally." → fails ("find" does not match inside "finally" on \b) → fallback
    assert spec["dialogue"]["thank"] == fallback["thank"]

    # 3 fallbacks: ask + wrong + thank
    fallback_dps = [d for d in decisions if d.code == "quest.dialogue_fallback"]
    assert len(fallback_dps) == 3
    fields = {d.context["field"] for d in fallback_dps}
    assert fields == {"ask", "wrong", "thank"}


# ── P2: NPC role validation (non-blocking) ──────────────────────

def test_validate_npc_role_empty_defaults_to_villager():
    """Empty npc_role → default to 'villager' + quest.npc_role_empty DP."""
    role, decisions = _validate_npc_role("")
    assert role == _DEFAULT_NPC_ROLE
    assert len(decisions) == 1
    assert decisions[0].code == "quest.npc_role_empty"
    assert decisions[0].severity == "assumption"
    assert decisions[0].context["resolved"] == _DEFAULT_NPC_ROLE


def test_validate_npc_role_whitespace_defaults_to_villager():
    """Whitespace-only npc_role → default."""
    role, decisions = _validate_npc_role("   ")
    assert role == _DEFAULT_NPC_ROLE
    assert len(decisions) == 1
    assert decisions[0].code == "quest.npc_role_empty"


def test_validate_npc_role_empty_has_choices():
    """The npc_role_empty DP carries actionable choices."""
    _, decisions = _validate_npc_role("")
    dp = decisions[0]
    assert len(dp.choices) >= 2
    choice_labels = {c.label for c in dp.choices}
    assert "Villager" in choice_labels
    assert "Custom role" in choice_labels
    assert dp.choices[0].apply["field"] == "npc_role"
    assert dp.choices[0].apply["value"] == _DEFAULT_NPC_ROLE


def test_validate_npc_role_too_long_truncates():
    """NPC role exceeding _MAX_NPC_ROLE_LEN → truncated + DP."""
    long_role = "a" * (_MAX_NPC_ROLE_LEN + 10)
    role, decisions = _validate_npc_role(long_role)
    assert len(role) <= _MAX_NPC_ROLE_LEN
    assert len(decisions) == 1
    assert decisions[0].code == "quest.npc_role_malformed"
    assert decisions[0].severity == "assumption"
    assert decisions[0].context["original"] == long_role
    assert decisions[0].context["resolved"] == role


def test_validate_npc_role_duplicate_words_collapsed():
    """'hermit hermit' → collapsed to 'hermit' + DP."""
    role, decisions = _validate_npc_role("hermit hermit")
    assert role == "hermit"
    assert len(decisions) == 1
    assert decisions[0].code == "quest.npc_role_malformed"
    assert decisions[0].context["original"] == "hermit hermit"
    assert decisions[0].context["resolved"] == "hermit"


def test_validate_npc_role_multiple_duplicates_collapsed():
    """'hermit hermit hermit' → single 'hermit'."""
    role, decisions = _validate_npc_role("hermit hermit hermit")
    assert role == "hermit"
    assert len(decisions) == 1
    assert decisions[0].code == "quest.npc_role_malformed"


def test_validate_npc_role_alternating_duplicates_collapsed():
    """'hermit shopkeeper hermit' → 'hermit shopkeeper' (only adjacent
    duplicates are collapsed)."""
    role, decisions = _validate_npc_role("hermit shopkeeper hermit")
    assert role == "hermit shopkeeper hermit"  # not adjacent, preserved
    assert decisions == []


def test_validate_npc_role_malformed_has_choices():
    """The npc_role_malformed DP carries actionable choices."""
    _, decisions = _validate_npc_role("hermit hermit")
    dp = decisions[0]
    assert len(dp.choices) >= 2
    choice_labels = {c.label for c in dp.choices}
    assert "Hermit" in choice_labels
    assert "Custom role" in choice_labels


def test_validate_npc_role_good_passes_through():
    """A valid NPC role → no decisions, role unchanged."""
    role, decisions = _validate_npc_role("hermit")
    assert role == "hermit"
    assert decisions == []


def test_plan_empty_npc_role_gets_default():
    """LLM returns empty npc_role → plan() defaults to villager + DP."""
    def fake_empty_role(prompt, grammar):
        return json.dumps({
            "npc_role": "",
            "target_entity": "table_0",
            "dialogue": {
                "greet": "Hello traveler, can you help me find something?",
                "ask": "Find my lost book on the table!",
                "wrong": "No, that is not my book.",
                "thank": "Yes, you found my book! Thank you.",
            },
            "objective": {"type": "fetch", "target": "table_0", "giver": "npc"},
        })

    planner = QuestBehaviourPlanner()
    spec, decisions = planner.plan("a room", _MANIFEST_4, fake_empty_role)
    assert spec["npc_role"] == _DEFAULT_NPC_ROLE
    assert any(d.code == "quest.npc_role_empty" for d in decisions)


def test_plan_duplicate_npc_role_words_collapsed():
    """LLM returns 'hermit hermit' → collapsed to 'hermit' + DP."""
    def fake_dupe_role(prompt, grammar):
        return json.dumps({
            "npc_role": "hermit hermit",
            "target_entity": "table_0",
            "dialogue": {
                "greet": "Hello traveler, can you help me find something?",
                "ask": "Find my lost book on the table!",
                "wrong": "No, that is not my book.",
                "thank": "Yes, you found my book! Thank you.",
            },
            "objective": {"type": "fetch", "target": "table_0", "giver": "npc"},
        })

    planner = QuestBehaviourPlanner()
    spec, decisions = planner.plan("a room", _MANIFEST_4, fake_dupe_role)
    assert spec["npc_role"] == "hermit"
    assert any(d.code == "quest.npc_role_malformed" for d in decisions)


# ── P2: Dialogue fallback DP has choices ─────────────────────────

def test_dialogue_fallback_dp_has_choices():
    """The dialogue_fallback DP carries at least one choice."""
    planner = QuestBehaviourPlanner()
    _, decisions = planner.plan(
        "a room", _MANIFEST_4, _fake_llm_junk_dialogue
    )
    fallback_dps = [d for d in decisions if d.code == "quest.dialogue_fallback"]
    assert len(fallback_dps) == 4
    for dp in fallback_dps:
        # Each fallback DP should mention the field and original
        assert "field" in dp.context
        assert dp.context["field"] in {"greet", "ask", "wrong", "thank"}


# ── Edge cases ────────────────────────────────────────────────────

def test_plan_empty_manifest_raises():
    """An empty manifest → no eligible targets → ValueError."""
    planner = QuestBehaviourPlanner()
    with pytest.raises(ValueError, match="no eligible"):
        planner.plan("a room", [], _fake_llm_valid)


def test_plan_manifest_ids():
    planner = QuestBehaviourPlanner()
    ids = planner._manifest_ids(_MANIFEST_4)
    assert ids == _VALID_MANIFEST_IDS


def test_plan_target_category():
    planner = QuestBehaviourPlanner()
    assert planner._target_category(_MANIFEST_4, "table_0") == "table"
    assert planner._target_category(_MANIFEST_4, "shelf_0") == "shelf"
    assert planner._target_category(_MANIFEST_4, "cabinet_0") == "cabinet"
    assert planner._target_category(_MANIFEST_4, "nonexistent") == "thing"


def test_plan_returns_correct_shape():
    """The spec dict has all expected top-level keys."""
    planner = QuestBehaviourPlanner()
    spec, _ = planner.plan("a room", _MANIFEST_4, _fake_llm_valid)
    assert set(spec.keys()) == {"npc_role", "target_entity", "dialogue", "objective", "idle_barks"}
    assert set(spec["dialogue"].keys()) == {"greet", "ask", "wrong", "thank"}
    assert set(spec["objective"].keys()) == {"type", "target", "giver"}


def test_plan_fake_llm_with_wrong_objective_shape_is_fixed():
    """If the LLM returns a mangled objective, plan() fixes it to the
    canonical shape (using the validated target_entity)."""
    def fake_wrong_obj(prompt, grammar):
        return json.dumps({
            "npc_role": "hermit",
            "target_entity": "table_1",
            "dialogue": {
                "greet": "Hello traveler, welcome.",
                "ask": "Can you find the table item I need?",
                "wrong": "No, that table is not right.",
                "thank": "Yes, the table item! Thank you.",
            },
            "objective": {
                "type": "kill",   # wrong type
                "target": "goblin",  # wrong target
                "giver": "quest_board",  # wrong giver
            },
        })

    planner = QuestBehaviourPlanner()
    spec, _ = planner.plan("a room", _MANIFEST_4, fake_wrong_obj)
    assert spec["objective"] == {
        "type": "fetch",
        "target": "table_1",
        "giver": "npc",
    }


def test_plan_fallback_dialogue_includes_category():
    """The fallback dialogue ask line includes the target's category."""
    planner = QuestBehaviourPlanner()
    spec, _ = planner.plan(
        "a room", _MANIFEST_4, _fake_llm_junk_dialogue
    )
    # target is table_0 → category "table", material "worn_oak" → adjective "wooden"
    # P-E: ask line now includes adjective: "I am looking for the wooden table..."
    assert "wooden" in spec["dialogue"]["ask"] or "table" in spec["dialogue"]["ask"]


# ── P-H-1: Seed determinism ─────────────────────────────────────

def _make_seeded_fake_llm(expected_seed: int):
    """Factory: returns a fake LLM that encodes its seed in the output
    so we can assert same-seed reproducibility."""
    def fake(prompt: str, grammar: str | None) -> str:
        idx = expected_seed % 2
        target = ["table_0", "shelf_0"][idx]
        return json.dumps({
            "npc_role": f"npc_s{expected_seed}",
            "target_entity": target,
            "dialogue": {
                "greet": f"Greetings from seed {expected_seed}.",
                "ask": f"Find the thing on the {target.split('_')[0]}.",
                "wrong": "Not the right one.",
                "thank": "You found it, thanks!",
            },
            "objective": {"type": "fetch", "target": target, "giver": "npc"},
        })
    return fake


def test_plan_same_seed_same_output():
    """P-H-1: Same seed → identical quest spec (deterministic plumbing)."""
    planner = QuestBehaviourPlanner()
    spec1, _ = planner.plan(
        "a room", _MANIFEST_4, _make_seeded_fake_llm(42), seed=42
    )
    spec2, _ = planner.plan(
        "a room", _MANIFEST_4, _make_seeded_fake_llm(42), seed=42
    )
    assert spec1 == spec2, (
        f"Same seed should produce identical specs:\n{spec1}\n{spec2}"
    )


def test_plan_different_seeds_different_output():
    """P-H-1: Different seeds → different quest spec."""
    planner = QuestBehaviourPlanner()
    spec1, _ = planner.plan(
        "a room", _MANIFEST_4, _make_seeded_fake_llm(42), seed=42
    )
    spec2, _ = planner.plan(
        "a room", _MANIFEST_4, _make_seeded_fake_llm(99), seed=99
    )
    assert spec1 != spec2, (
        "Different seeds should produce different specs"
    )


def test_plan_no_seed_still_works():
    """P-H-1: plan() without seed still functions (stochastic path)."""
    planner = QuestBehaviourPlanner()
    spec, decisions = planner.plan(
        "a room", _MANIFEST_4, _fake_llm_valid
    )
    assert spec["target_entity"] in _VALID_MANIFEST_IDS
    assert spec["npc_role"] == "hermit"


def _make_seeded_room_fake_llm(expected_seed: int):
    """Factory: returns a fake room-planner LLM that encodes seed in output."""
    def fake(prompt: str, grammar: str | None) -> str:
        w = 4 + (expected_seed % 8)
        d = 4 + ((expected_seed // 8) % 8)
        count = 1 + (expected_seed % 3)
        return json.dumps({
            "room_size": {"w": w, "d": d},
            "props": [{"category": "table", "material": "worn_oak", "count": count}],
        })
    return fake


def test_room_planner_same_seed_same_output():
    """P-H-1: Same seed → identical room plan with seed-aware stub."""
    from room_planner import RoomPlanner
    planner = RoomPlanner()
    plan1, _ = planner.plan("a room", _make_seeded_room_fake_llm(42), seed=42)
    plan2, _ = planner.plan("a room", _make_seeded_room_fake_llm(42), seed=42)
    assert plan1 == plan2, (
        f"Same seed should produce identical room plans:\n{plan1}\n{plan2}"
    )


def test_room_planner_different_seeds_different_output():
    """P-H-1: Different seeds → different room plan."""
    from room_planner import RoomPlanner
    planner = RoomPlanner()
    plan1, _ = planner.plan("a room", _make_seeded_room_fake_llm(42), seed=42)
    plan2, _ = planner.plan("a room", _make_seeded_room_fake_llm(99), seed=99)
    assert plan1 != plan2, (
        "Different seeds should produce different room plans"
    )


def test_room_planner_accepts_seed():
    """P-H-1: RoomPlanner.plan() accepts optional seed parameter."""
    from room_planner import RoomPlanner
    planner = RoomPlanner()
    # Stub LLM that returns a minimal valid room plan
    def fake_room_llm(prompt, grammar):
        return '{"room_size": {"w": 6, "d": 6}, "props": [{"category": "table", "material": "worn_oak", "count": 2}]}'
    room_plan, decisions = planner.plan("a room", fake_room_llm, seed=42)
    assert room_plan["room_size"]["w"] == 6
    assert len(room_plan["props"]) == 1
    assert room_plan["props"][0]["count"] == 2


@pytest.mark.live
def test_room_planner_live_seed_reproducible():
    """P-H-1: With a real FoundryLLM + seed, two plan() calls produce
    identical room plans (requires llama server)."""
    if not _llama_server_reachable():
        pytest.skip("llama.cpp server not reachable at 127.0.0.1:8002")

    from llm import FoundryLLM
    from room_planner import RoomPlanner

    planner = RoomPlanner()
    llm1 = FoundryLLM(seed=42)
    llm2 = FoundryLLM(seed=42)

    plan1, _ = planner.plan("a hermit's shack", llm1, seed=42)
    plan2, _ = planner.plan("a hermit's shack", llm2, seed=42)
    assert plan1 == plan2, (
        f"Same seed should produce identical room plans with live LLM:\n"
        f"plan1={plan1}\nplan2={plan2}"
    )


def test_layout_room_accepts_seed():
    """P-H-1: layout_room() accepts optional seed parameter."""
    from room_layout import layout_room
    plan = {"room_size": {"w": 6, "d": 6}, "props": [
        {"category": "table", "material": "worn_oak", "count": 2},
    ]}
    manifest, room_size, decisions = layout_room(plan, seed=42)
    assert room_size["w"] == 6
    # 2 furniture + 1 auto-guaranteed carryable target (a room must be winnable).
    furniture = [e for e in manifest if e["category"] in ("table", "chair", "shelf", "cabinet")]
    assert len(furniture) == 2
    assert any(e["category"] == "key" for e in manifest)


# ── Live integration test ────────────────────────────────────────

def _llama_server_reachable() -> bool:
    """Check if the llama.cpp server is listening at 127.0.0.1:8002."""
    try:
        s = socket.create_connection(("127.0.0.1", 8002), timeout=2)
        s.close()
        return True
    except (TimeoutError, ConnectionRefusedError, OSError):
        return False


@pytest.mark.live
def test_plan_live_produces_valid_quest_spec():
    """Integration: real LLM produces a quest spec with a valid target_entity
    and all required fields."""
    if not _llama_server_reachable():
        pytest.skip("llama.cpp server not reachable at 127.0.0.1:8002")

    from llm import FoundryLLM

    llm = FoundryLLM()
    planner = QuestBehaviourPlanner()
    spec, decisions = planner.plan(
        "a hermit's shack", _MANIFEST_4, llm
    )

    # Structural checks
    assert spec["target_entity"] in _VALID_MANIFEST_IDS, (
        f"target_entity {spec['target_entity']!r} not in manifest"
    )
    assert isinstance(spec["npc_role"], str)
    assert len(spec["npc_role"]) > 0
    assert set(spec["dialogue"].keys()) == {"greet", "ask", "wrong", "thank"}
    assert spec["objective"]["type"] == "fetch"
    assert spec["objective"]["target"] == spec["target_entity"]
    assert spec["objective"]["giver"] == "npc"

    # Dialogue lines should be non-empty (may or may not have fallback)
    for field in ("greet", "ask", "wrong", "thank"):
        line = spec["dialogue"][field]
        assert len(line) >= 3, (
            f"dialogue.{field} too short: {line!r}"
        )

    # Log decisions for the report
    print(f"\n  npc_role: {spec['npc_role']}")
    print(f"  target_entity: {spec['target_entity']}")
    print(f"  dialogue.greet: {spec['dialogue']['greet']}")
    print(f"  dialogue.ask: {spec['dialogue']['ask']}")
    print(f"  dialogue.wrong: {spec['dialogue']['wrong']}")
    print(f"  dialogue.thank: {spec['dialogue']['thank']}")
    print(f"  decisions: {[d.code for d in decisions]}")
    if decisions:
        for d in decisions:
            print(f"    [{d.severity}] {d.code}: {d.technical}")


def test_plan_no_carryables_falls_back_to_furniture():
    """Robustness: when carryable_ids is empty (room has no carryables), the
    planner must fall back to a furniture target, not hard-fail."""
    planner = QuestBehaviourPlanner()
    spec, decisions = planner.plan(
        "a hermit's shack", _MANIFEST_4, _fake_llm_valid, carryable_ids=set()
    )
    assert spec["target_entity"] in _VALID_MANIFEST_IDS


def test_plan_multi_recovers_from_malformed_json():
    """C-4 robustness: a weak model's malformed multi-NPC JSON must not crash —
    every NPC still gets a winnable quest with a distinct target."""
    planner = QuestBehaviourPlanner()
    def bad_llm(prompt, grammar=None, **kw):
        return "{not valid json at all"
    specs, decisions = planner.plan_multi("a tavern", _MANIFEST_4, bad_llm, npc_count=2)
    assert len(specs) == 2
    targets = [s["target_entity"] for s in specs]
    assert all(t in _VALID_MANIFEST_IDS for t in targets)
    assert len(set(targets)) == 2  # distinct targets per NPC


def test_plan_multi_calls_llm_with_json_schema_not_empty_grammar():
    """Spine Fix: plan_multi MUST pass a json_schema to constrain output,
    NOT grammar="" (the old ungrammared path let verbose thinkers ramble
    in prose, collapsing every model to canned fallbacks).

    The contract is: multi-NPC generation is constrained via json_schema,
    whose 'required' lists all npc_ids.
    """
    planner = QuestBehaviourPlanner()
    seen_calls: list = []

    def capturing(prompt, grammar=None, json_schema=None):
        seen_calls.append((grammar, json_schema))
        return "{}"

    planner.plan_multi("a tavern", _MANIFEST_4, capturing, npc_count=2)

    # The first call (multi-NPC) MUST pass a json_schema
    assert len(seen_calls) >= 1
    grammar_arg, schema_arg = seen_calls[0]
    assert schema_arg is not None, (
        f"expected json_schema to be set, got {schema_arg!r}"
    )
    assert schema_arg["type"] == "object"
    # required must list all npc_ids
    assert set(schema_arg["required"]) == {"npc_0", "npc_1"}, (
        f"json_schema.required={schema_arg['required']} missing npc_ids"
    )


# ── Spine Slice 2 Task 2: plan_multi consumes Brief + brief-seeded roles ──

def _brief_with_characters() -> dict:
    """A Brief v2 dict with two named characters."""
    return {
        "schema_version": 2,
        "source_prompt": "a blacksmith's forge with an apprentice",
        "setting": "a blacksmith's forge",
        "theme_tag": "blacksmith",
        "scale": "medium",
        "mood": [],
        "key_features": [],
        "unmapped": [],
        "characters": [
            {"role": "blacksmith", "note": "master forger"},
            {"role": "apprentice", "note": None},
        ],
    }


def test_plan_multi_back_compat_string_input():
    """plan_multi with a raw string (back-compat) → 2 specs with distinct
    targets, same behaviour as before."""
    planner = QuestBehaviourPlanner()

    # CARRYABLE manifest for plan_multi (needs at least npc_count=2 carryables)
    carry_manifest = [
        {"id": "key_0", "category": "key", "material": "wrought_iron"},
        {"id": "gem_0", "category": "gem", "material": "rough_granite"},
    ]

    def fake_multi_llm(prompt, grammar=None, json_schema=None, **kw):
        return json.dumps({
            "npc_0": {
                "npc_role": "tavern_keeper",
                "target_entity": "key_0",
                "dialogue": {"greet": "Hi", "ask": "Find key", "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc"},
            },
            "npc_1": {
                "npc_role": "patron",
                "target_entity": "gem_0",
                "dialogue": {"greet": "Hello", "ask": "Find gem", "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "gem_0", "giver": "npc"},
            },
        })

    specs, decs = planner.plan_multi(
        "a tavern", carry_manifest, fake_multi_llm, npc_count=2,
        carryable_ids={"key_0", "gem_0"},
    )
    assert len(specs) == 2
    targets = {s["target_entity"] for s in specs}
    assert targets == {"key_0", "gem_0"}  # distinct


def test_plan_multi_brief_seeded_roles():
    """Brief with characters → NPC roles come from the Brief, not the model."""
    planner = QuestBehaviourPlanner()

    carry_manifest = [
        {"id": "key_0", "category": "key", "material": "wrought_iron"},
        {"id": "gem_0", "category": "gem", "material": "rough_granite"},
    ]

    def fake_multi_llm(prompt, grammar=None, json_schema=None, **kw):
        # Model returns "villager" roles — should be overridden by Brief
        return json.dumps({
            "npc_0": {
                "npc_role": "villager",
                "target_entity": "key_0",
                "dialogue": {"greet": "Hi", "ask": "Find key", "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc"},
            },
            "npc_1": {
                "npc_role": "villager",
                "target_entity": "gem_0",
                "dialogue": {"greet": "Hello", "ask": "Find gem", "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "gem_0", "giver": "npc"},
            },
        })

    brief = _brief_with_characters()
    specs, decs = planner.plan_multi(
        brief, carry_manifest, fake_multi_llm, npc_count=2,
        carryable_ids={"key_0", "gem_0"},
    )

    roles = [s["npc_role"] for s in specs]
    assert roles == ["blacksmith", "apprentice"]

    # quest.role_from_brief DPs should be present
    role_dps = [d for d in decs if d.code == "quest.role_from_brief"]
    assert len(role_dps) == 2


def test_plan_multi_brief_characters_with_empty_model_roles():
    """Brief characters set roles even when model returns no roles."""
    planner = QuestBehaviourPlanner()

    carry_manifest = [
        {"id": "key_0", "category": "key", "material": "wrought_iron"},
        {"id": "gem_0", "category": "gem", "material": "rough_granite"},
    ]

    def fake_multi_llm(prompt, grammar=None, json_schema=None):
        return json.dumps({
            "npc_0": {
                "npc_role": "",
                "target_entity": "key_0",
                "dialogue": {"greet": "Hi", "ask": "Find key", "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc"},
            },
            "npc_1": {
                "target_entity": "gem_0",
                "dialogue": {"greet": "Hello", "ask": "Find gem", "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "gem_0", "giver": "npc"},
            },
        })

    brief = _brief_with_characters()
    specs, decs = planner.plan_multi(
        brief, carry_manifest, fake_multi_llm, npc_count=2,
        carryable_ids={"key_0", "gem_0"},
    )

    roles = [s["npc_role"] for s in specs]
    assert roles == ["blacksmith", "apprentice"]


# ── Spine Slice 2 Task 3: Per-NPC grammared fallback ──


def test_plan_multi_grammared_fallback_for_missing_npc():
    """When multi-call returns {} for npc_1, retry via grammar-constrained
    plan() → npc_1 gets themed dialogue (NOT 'villager'/'Hello there, traveler'),
    and quest.npc_grammared_fallback DP fires."""
    planner = QuestBehaviourPlanner()

    carry_manifest = [
        {"id": "key_0", "category": "key", "material": "wrought_iron"},
        {"id": "gem_0", "category": "gem", "material": "rough_granite"},
    ]

    def fake_multi_llm(prompt, grammar=None, json_schema=None, **kw):
        # Multi-call returns data only for npc_0, npc_1 is missing
        return json.dumps({
            "npc_0": {
                "npc_role": "hermit",
                "target_entity": "key_0",
                "dialogue": {"greet": "Hi", "ask": "Find key", "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc"},
            },
        })

    def fake_single_llm(prompt, grammar=None, json_schema=None, **kw):
        return json.dumps({
            "npc_role": "shopkeeper",
            "target_entity": "gem_0",
            "dialogue": {
                "greet": "Welcome to my shop.",
                "ask": "Can you find my gem for me?",
                "wrong": "No, that is not the gem I need.",
                "thank": "Yes, the gem! Thank you so much.",
            },
            "objective": {"type": "fetch", "target": "gem_0", "giver": "npc"},
        })

    # Create a planner with injected LLMs
    # The multi-call uses fake_multi_llm, the fallback plan() uses fake_single_llm
    class TestPlanner(QuestBehaviourPlanner):
        def plan(self, room_theme, manifest, llm, seed=None, carryable_ids=None):
            return QuestBehaviourPlanner.plan(
                self, room_theme, manifest, fake_single_llm,
                seed=seed, carryable_ids=carryable_ids,
            )

    planner2 = TestPlanner()
    specs, decs = planner2.plan_multi(
        "a hermit's shack", carry_manifest, fake_multi_llm, npc_count=2,
        carryable_ids={"key_0", "gem_0"},
    )

    assert len(specs) == 2
    # First NPC from multi-call
    assert specs[0]["npc_role"] == "hermit"
    # Second NPC from grammared fallback
    assert specs[1]["npc_role"] == "shopkeeper"
    # Dialogue should NOT be canned — should be the themed dialogue
    assert "shop" in specs[1]["dialogue"]["greet"]

    # Should have quest.npc_grammared_fallback DP
    fb_dps = [d for d in decs if d.code == "quest.npc_grammared_fallback"]
    assert len(fb_dps) == 1
    assert fb_dps[0].context["npc_id"] == "npc_1"

    # Should NOT have quest.llm_retry_failed for npc_1
    missing_dps = [d for d in decs if d.code == "quest.llm_retry_failed"]
    assert not [d for d in missing_dps if d.context.get("npc_id") == "npc_1"]

    # Targets remain distinct
    targets = {s["target_entity"] for s in specs}
    assert len(targets) == 2


def test_plan_multi_both_multi_and_grammared_fail():
    """When both multi-call and plan() fail → canned default + quest.llm_retry_failed."""
    planner = QuestBehaviourPlanner()

    carry_manifest = [
        {"id": "key_0", "category": "key", "material": "wrought_iron"},
        {"id": "gem_0", "category": "gem", "material": "rough_granite"},
    ]

    def bad_llm(prompt, grammar=None, json_schema=None, **kw):
        return "{not valid json at all"

    # Both calls fail — this should route through missing_npc
    specs, decs = planner.plan_multi(
        "a tavern", carry_manifest, bad_llm, npc_count=2,
        carryable_ids={"key_0", "gem_0"},
    )

    assert len(specs) == 2
    # Should have quest.llm_retry_failed for BOTH NPCs (grammared fallback also failed)
    missing_dps = [d for d in decs if d.code == "quest.llm_retry_failed"]
    assert len(missing_dps) == 2

    # Grammared fallback DPs should NOT be present (they failed too)
    fb_dps = [d for d in decs if d.code == "quest.npc_grammared_fallback"]
    assert len(fb_dps) == 0


# ── Spine Slice 3 Task 3: Soul tone in prompts + soul on specs ──

_BRIEF_WITH_SOULS: dict = {
    "schema_version": 2,
    "source_prompt": "a fearful hermit and a bold blacksmith",
    "setting": "a shared workshop",
    "theme_tag": "blacksmith",
    "scale": "medium",
    "mood": [],
    "key_features": [],
    "unmapped": [],
    "characters": [
        {
            "role": "hermit",
            "note": None,
            "soul": {
                "substrate": {"courage": -0.6, "generosity": 0.0, "stability": 0.0},
                "axes": {"security": 0.0, "belonging": 0.0, "agency": 0.0, "satiation": 0.0},
            },
        },
        {
            "role": "blacksmith",
            "note": None,
            "soul": {
                "substrate": {"courage": 0.8, "generosity": 0.0, "stability": 0.0},
                "axes": {"security": 0.0, "belonging": 0.0, "agency": 0.0, "satiation": 0.0},
            },
        },
    ],
}


def test_plan_multi_prompt_contains_tone_from_soul():
    """A Brief with soul → the prompt passed to the LLM contains the tone adjective."""
    planner = QuestBehaviourPlanner()

    carry_manifest = [
        {"id": "key_0", "category": "key", "material": "wrought_iron"},
        {"id": "gem_0", "category": "gem", "material": "rough_granite"},
    ]

    captured_prompt: list[str] = []

    def capturing_llm(prompt, grammar=None, json_schema=None, **kw):
        captured_prompt.append(prompt)
        return json.dumps({
            "npc_0": {
                "npc_role": "hermit",
                "target_entity": "key_0",
                "dialogue": {"greet": "Hi", "ask": "Find key", "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc"},
            },
            "npc_1": {
                "npc_role": "blacksmith",
                "target_entity": "gem_0",
                "dialogue": {"greet": "Hello", "ask": "Find gem", "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "gem_0", "giver": "npc"},
            },
        })

    planner.plan_multi(
        _BRIEF_WITH_SOULS, carry_manifest, capturing_llm, npc_count=2,
        carryable_ids={"key_0", "gem_0"},
    )

    assert len(captured_prompt) == 1
    prompt_text = captured_prompt[0]
    assert "timid" in prompt_text, f"expected 'timid' in prompt, got:\n{prompt_text[:500]}"
    assert "bold" in prompt_text, "expected 'bold' in prompt"
    assert "hermit is a timid character" in prompt_text
    assert "blacksmith is a bold character" in prompt_text


def test_plan_multi_every_spec_has_soul_key():
    """Every spec returned by plan_multi has a 'soul' key with the full shape,
    including NPCs with no named character → default_soul()."""
    planner = QuestBehaviourPlanner()

    carry_manifest = [
        {"id": "key_0", "category": "key", "material": "wrought_iron"},
        {"id": "gem_0", "category": "gem", "material": "rough_granite"},
    ]

    def fake_multi_llm(prompt, grammar=None, json_schema=None, **kw):
        return json.dumps({
            "npc_0": {
                "npc_role": "hermit",
                "target_entity": "key_0",
                "dialogue": {"greet": "Hi", "ask": "Find key", "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc"},
            },
            "npc_1": {
                "npc_role": "blacksmith",
                "target_entity": "gem_0",
                "dialogue": {"greet": "Hello", "ask": "Find gem", "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "gem_0", "giver": "npc"},
            },
        })

    specs, decs = planner.plan_multi(
        _BRIEF_WITH_SOULS, carry_manifest, fake_multi_llm, npc_count=2,
        carryable_ids={"key_0", "gem_0"},
    )

    assert len(specs) == 2
    for i, spec in enumerate(specs):
        assert "soul" in spec, f"spec[{i}] missing 'soul' key"
        soul = spec["soul"]
        assert "substrate" in soul
        assert "axes" in soul
        assert set(soul["substrate"].keys()) == {"courage", "generosity", "stability"}
        assert set(soul["axes"].keys()) == {"security", "belonging", "agency", "satiation"}

    # First NPC (hermit) should have the timid soul from Brief
    assert specs[0]["soul"]["substrate"]["courage"] == -0.6
    # Second NPC (blacksmith) should have the bold soul from Brief
    assert specs[1]["soul"]["substrate"]["courage"] == 0.8


def test_plan_multi_different_tones_from_opposite_courage():
    """Two characters with opposite courage → tone hints differ ('timid' vs 'bold')."""
    planner = QuestBehaviourPlanner()

    carry_manifest = [
        {"id": "key_0", "category": "key", "material": "wrought_iron"},
        {"id": "gem_0", "category": "gem", "material": "rough_granite"},
    ]

    captured_prompt: list[str] = []

    def capturing_llm(prompt, grammar=None, json_schema=None, **kw):
        captured_prompt.append(prompt)
        return json.dumps({
            "npc_0": {
                "npc_role": "hermit",
                "target_entity": "key_0",
                "dialogue": {"greet": "Hi", "ask": "Find key", "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc"},
            },
            "npc_1": {
                "npc_role": "blacksmith",
                "target_entity": "gem_0",
                "dialogue": {"greet": "Hello", "ask": "Find gem", "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "gem_0", "giver": "npc"},
            },
        })

    planner.plan_multi(
        _BRIEF_WITH_SOULS, carry_manifest, capturing_llm, npc_count=2,
        carryable_ids={"key_0", "gem_0"},
    )

    prompt_text = captured_prompt[0]
    # hermit is timid, blacksmith is bold
    timid_pos = prompt_text.find("timid")
    bold_pos = prompt_text.find("bold")
    assert timid_pos != -1
    assert bold_pos != -1
    assert timid_pos != bold_pos  # different positions → different tones


def test_plan_multi_default_souls_for_nameless_npcs():
    """NPCs without a named character in the Brief get default_soul()."""
    planner = QuestBehaviourPlanner()
    from soul import default_soul

    carry_manifest = [
        {"id": "key_0", "category": "key", "material": "wrought_iron"},
        {"id": "gem_0", "category": "gem", "material": "rough_granite"},
    ]

    def fake_multi_llm(prompt, grammar=None, json_schema=None):
        return json.dumps({
            "npc_0": {
                "npc_role": "villager",
                "target_entity": "key_0",
                "dialogue": {"greet": "Hi", "ask": "Find key", "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc"},
            },
            "npc_1": {
                "npc_role": "villager",
                "target_entity": "gem_0",
                "dialogue": {"greet": "Hello", "ask": "Find gem", "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "gem_0", "giver": "npc"},
            },
        })

    # Use a string (no characters) → all NPCs get default_soul
    specs, decs = planner.plan_multi(
        "a tavern", carry_manifest, fake_multi_llm, npc_count=2,
        carryable_ids={"key_0", "gem_0"},
    )

    for spec in specs:
        assert spec["soul"] == default_soul()


# ═══════════════════════════════════════════════════════════════════════
#  CB-1: Quest depth — multi-type objectives + chain validation
# ═══════════════════════════════════════════════════════════════════════

_CARRY_MANIFEST_2: list[dict] = [
    {"id": "key_0", "category": "key", "material": "wrought_iron"},
    {"id": "gem_0", "category": "gem", "material": "rough_granite"},
    {"id": "table_0", "category": "table", "material": "worn_oak"},
]


def test_plan_multi_produces_deliver_objective():
    """CB-1: plan_multi accepts a deliver objective from the LLM and
    preserves recipient."""
    planner = QuestBehaviourPlanner()

    def fake_deliver_llm(prompt, grammar=None, json_schema=None, **kw):
        return json.dumps({
            "npc_0": {
                "npc_role": "hermit",
                "target_entity": "key_0",
                "quest_id": "q_npc_0",
                "dialogue": {"greet": "Hi", "ask": "Take key to alchemist",
                            "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "deliver", "target": "key_0", "giver": "npc",
                             "recipient": "npc_1"},
            },
            "npc_1": {
                "npc_role": "alchemist",
                "target_entity": "gem_0",
                "quest_id": "q_npc_1",
                "dialogue": {"greet": "Hello", "ask": "Find gem",
                            "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "gem_0", "giver": "npc"},
            },
        })

    specs, decs = planner.plan_multi(
        "a lab", _CARRY_MANIFEST_2, fake_deliver_llm, npc_count=2,
        carryable_ids={"key_0", "gem_0"},
    )

    assert len(specs) == 2
    deliver_spec = specs[0]
    assert deliver_spec["objective"]["type"] == "deliver"
    assert deliver_spec["objective"]["recipient"] == "npc_1"
    assert deliver_spec["quest_id"] == "q_npc_0"


def test_plan_multi_produces_talk_objective():
    """CB-1: plan_multi accepts a talk objective from the LLM."""
    planner = QuestBehaviourPlanner()

    def fake_talk_llm(prompt, grammar=None, json_schema=None, **kw):
        return json.dumps({
            "npc_0": {
                "npc_role": "guide",
                "target_entity": "key_0",
                "quest_id": "q_npc_0",
                "dialogue": {"greet": "Hi", "ask": "Speak to the alchemist",
                            "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "talk", "target": "npc_1", "giver": "npc"},
            },
            "npc_1": {
                "npc_role": "alchemist",
                "target_entity": "gem_0",
                "quest_id": "q_npc_1",
                "dialogue": {"greet": "Hello", "ask": "Find gem",
                            "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "gem_0", "giver": "npc"},
            },
        })

    specs, decs = planner.plan_multi(
        "a lab", _CARRY_MANIFEST_2, fake_talk_llm, npc_count=2,
        carryable_ids={"key_0", "gem_0"},
    )

    assert len(specs) == 2
    talk_spec = specs[0]
    assert talk_spec["objective"]["type"] == "talk"
    assert talk_spec["objective"]["target"] == "npc_1"


def test_plan_multi_invalid_objective_falls_back_to_fetch():
    """CB-1: An objective that fails quest_validator (e.g. deliver with
    non-existent recipient) → falls back to fetch + DP."""
    planner = QuestBehaviourPlanner()

    def fake_bad_deliver_llm(prompt, grammar=None, json_schema=None, **kw):
        return json.dumps({
            "npc_0": {
                "npc_role": "hermit",
                "target_entity": "key_0",
                "dialogue": {"greet": "Hi", "ask": "Deliver key",
                            "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "deliver", "target": "key_0", "giver": "npc",
                             # recipient npc_99 doesn't exist
                             "recipient": "npc_99"},
            },
            "npc_1": {
                "npc_role": "alchemist",
                "target_entity": "gem_0",
                "dialogue": {"greet": "Hello", "ask": "Find gem",
                            "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "gem_0", "giver": "npc"},
            },
        })

    specs, decs = planner.plan_multi(
        "a lab", _CARRY_MANIFEST_2, fake_bad_deliver_llm, npc_count=2,
        carryable_ids={"key_0", "gem_0"},
    )

    assert len(specs) == 2
    # First NPC should have been downgraded to fetch
    assert specs[0]["objective"]["type"] == "fetch"
    # Should have objective_not_winnable DP
    winnable_dps = [d for d in decs if d.code == "quest.objective_not_winnable"]
    assert len(winnable_dps) >= 1
    assert winnable_dps[0].context["original_type"] == "deliver"


def test_plan_multi_chain_with_depends_on():
    """CB-1: plan_multi preserves depends_on chains from the LLM."""
    planner = QuestBehaviourPlanner()

    def fake_chain_llm(prompt, grammar=None, json_schema=None, **kw):
        return json.dumps({
            "npc_0": {
                "npc_role": "hermit",
                "target_entity": "key_0",
                "quest_id": "q_npc_0",
                "dialogue": {"greet": "Hi", "ask": "Find key",
                            "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc",
                             "depends_on": []},
            },
            "npc_1": {
                "npc_role": "alchemist",
                "target_entity": "gem_0",
                "quest_id": "q_npc_1",
                "dialogue": {"greet": "Hello", "ask": "Find gem",
                            "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "gem_0", "giver": "npc",
                             # npc_1's quest depends on npc_0's quest
                             "depends_on": ["q_npc_0"]},
            },
        })

    specs, decs = planner.plan_multi(
        "a lab", _CARRY_MANIFEST_2, fake_chain_llm, npc_count=2,
        carryable_ids={"key_0", "gem_0"},
    )

    assert len(specs) == 2
    assert specs[0]["objective"].get("depends_on") == []
    assert specs[1]["objective"]["depends_on"] == ["q_npc_0"]
    # quest_id should be on each spec
    assert specs[0]["quest_id"] == "q_npc_0"
    assert specs[1]["quest_id"] == "q_npc_1"


def test_plan_multi_chain_unsolvable_flattened():
    """CB-1: A cyclic depends_on chain → flattened to independent quests
    + quest.chain_unsolvable DP."""
    planner = QuestBehaviourPlanner()

    def fake_cycle_llm(prompt, grammar=None, json_schema=None, **kw):
        return json.dumps({
            "npc_0": {
                "npc_role": "hermit",
                "target_entity": "key_0",
                "quest_id": "q_npc_0",
                "dialogue": {"greet": "Hi", "ask": "Find key",
                            "wrong": "No", "thank": "Thanks"},
                # npc_0 depends on npc_1 → cycle!
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc",
                             "depends_on": ["q_npc_1"]},
            },
            "npc_1": {
                "npc_role": "alchemist",
                "target_entity": "gem_0",
                "quest_id": "q_npc_1",
                "dialogue": {"greet": "Hello", "ask": "Find gem",
                            "wrong": "No", "thank": "Thanks"},
                # npc_1 depends on npc_0 → cycle!
                "objective": {"type": "fetch", "target": "gem_0", "giver": "npc",
                             "depends_on": ["q_npc_0"]},
            },
        })

    specs, decs = planner.plan_multi(
        "a lab", _CARRY_MANIFEST_2, fake_cycle_llm, npc_count=2,
        carryable_ids={"key_0", "gem_0"},
    )

    assert len(specs) == 2
    # Chain should have been flattened: no depends_on on either
    for spec in specs:
        assert "depends_on" not in spec.get("objective", {})
    # Should have chain_unsolvable DP
    chain_dps = [d for d in decs if d.code == "quest.chain_unsolvable"]
    assert len(chain_dps) == 1


def test_plan_multi_quest_id_on_every_spec():
    """CB-1: Every spec from plan_multi has a quest_id (generated from
    model or auto-generated from npc_id)."""
    planner = QuestBehaviourPlanner()

    def fake_no_qid_llm(prompt, grammar=None, json_schema=None, **kw):
        # Model returns no quest_id — should be auto-generated
        return json.dumps({
            "npc_0": {
                "npc_role": "hermit",
                "target_entity": "key_0",
                "dialogue": {"greet": "Hi", "ask": "Find key",
                            "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc"},
            },
            "npc_1": {
                "npc_role": "alchemist",
                "target_entity": "gem_0",
                "dialogue": {"greet": "Hello", "ask": "Find gem",
                            "wrong": "No", "thank": "Thanks"},
                "objective": {"type": "fetch", "target": "gem_0", "giver": "npc"},
            },
        })

    specs, decs = planner.plan_multi(
        "a lab", _CARRY_MANIFEST_2, fake_no_qid_llm, npc_count=2,
        carryable_ids={"key_0", "gem_0"},
    )

    assert len(specs) == 2
    assert specs[0]["quest_id"] == "q_npc_0"
    assert specs[1]["quest_id"] == "q_npc_1"


# ═══════════════════════════════════════════════════════════════════════
#  AUDIT-02 L1 / AUDIT-01 A10: soft-fallback for insufficient carryables
# ═══════════════════════════════════════════════════════════════════════


def test_plan_multi_soft_fallback_when_carryables_short():
    """AUDIT-02 L1 / AUDIT-01 A10: layout_room.auto-injects missing
    carryables — plan_multi must NOT re-raise the same invariant.
    With fewer carryables than npc_count, plan_multi must emit a
    quest.carryables_short Decision Point (severity='warning') and
    return specs using the available targets round-robin.  Hard-raising
    here would crash the build with a misleading message if layout_room
    ever regressed.
    """
    planner = QuestBehaviourPlanner()

    # Only 1 carryable for 2 NPCs — triggers len(valid_ids) < npc_count.
    short_manifest = [
        {"id": "key_0", "category": "key", "material": "wrought_iron"},
    ]

    def fake_short_llm(prompt, grammar=None, json_schema=None, **kw):
        # npc_0 picks the lone carryable; npc_1 picks a non-existent
        # item so the dangling_target handler round-robins back to key_0.
        return json.dumps({
            "npc_0": {
                "npc_role": "hermit",
                "target_entity": "key_0",
                "dialogue": {"greet": "Hi.", "ask": "Find the key, please.",
                            "wrong": "Not the right key.",
                            "thank": "Yes, that key is exactly right."},
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc"},
            },
            "npc_1": {
                "npc_role": "apprentice",
                "target_entity": "dragon_gold",  # not in manifest
                "dialogue": {"greet": "Hi.", "ask": "Find the gold, please.",
                            "wrong": "Not gold.",
                            "thank": "Yes, that gold is just right."},
                "objective": {"type": "fetch", "target": "dragon_gold",
                              "giver": "npc"},
            },
        })

    # ACT: must NOT raise (was raising ValueError before the fix).
    specs, decs = planner.plan_multi(
        "a shack", short_manifest, fake_short_llm, npc_count=2,
        carryable_ids={"key_0"},
    )

    # ASSERT: 2 specs returned, both targeting the lone available carryable.
    assert len(specs) == 2
    for spec in specs:
        assert spec["target_entity"] == "key_0", (
            f"expected round-robin to key_0, got {spec['target_entity']!r}"
        )

    # ASSERT: quest.carryables_short DP emitted with severity='warning'.
    cs_dps = [d for d in decs if d.code == "quest.carryables_short"]
    assert len(cs_dps) == 1, (
        f"expected exactly one quest.carryables_short DP; "
        f"got codes {[d.code for d in decs]}"
    )
    dp = cs_dps[0]
    assert dp.severity == "warning"
    assert dp.stage == "planner"
    assert dp.context["npc_count"] == 2
    assert dp.context["carryable_count"] == 1


def test_plan_multi_soft_fallback_emits_no_dp_when_carryables_sufficient():
    """Happy-path companion: 2 carryables for 2 NPCs → no
    quest.carryables_short DP emitted (the invariant holds, no warning)."""
    planner = QuestBehaviourPlanner()

    exact_manifest = [
        {"id": "key_0", "category": "key", "material": "wrought_iron"},
        {"id": "gem_0", "category": "gem", "material": "rough_granite"},
    ]

    def fake_exact_llm(prompt, grammar=None, json_schema=None, **kw):
        return json.dumps({
            "npc_0": {
                "npc_role": "hermit",
                "target_entity": "key_0",
                "dialogue": {"greet": "Hi.", "ask": "Find the key, please.",
                            "wrong": "Not the right key.",
                            "thank": "Yes, that key is exactly right."},
                "objective": {"type": "fetch", "target": "key_0", "giver": "npc"},
            },
            "npc_1": {
                "npc_role": "apprentice",
                "target_entity": "gem_0",
                "dialogue": {"greet": "Hi.", "ask": "Find the gem, please.",
                            "wrong": "Not the right gem.",
                            "thank": "Yes, that gem is exactly right."},
                "objective": {"type": "fetch", "target": "gem_0", "giver": "npc"},
            },
        })

    specs, decs = planner.plan_multi(
        "a shack", exact_manifest, fake_exact_llm, npc_count=2,
        carryable_ids={"key_0", "gem_0"},
    )

    cs_dps = [d for d in decs if d.code == "quest.carryables_short"]
    assert cs_dps == [], (
        f"happy path should not emit quest.carryables_short; "
        f"got codes {[d.code for d in decs]}"
    )
