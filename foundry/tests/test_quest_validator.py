"""Unit tests for foundry.quest_validator (B9 quest-depth foundation).

Pure deterministic validation of quest objectives (fetch/deliver/place/talk)
and quest chains (depends_on DAG). No LLM, no I/O.
"""

from __future__ import annotations

import pytest

from quest_validator import (
    OBJECTIVE_TYPES,
    chain_solvable,
    objective_winnable,
)


# ── Fixtures: a small manifest with a carryable, a surface, and decor ──

@pytest.fixture
def manifest():
    return [
        {"id": "key_0", "category": "key"},        # carryable
        {"id": "book_1", "category": "book"},       # carryable
        {"id": "table_0", "category": "table"},     # furniture w/ top surface
        {"id": "chair_2", "category": "chair"},     # furniture w/ top surface
        {"id": "rug_3", "category": "rug"},         # decor (no top)
    ]


NPCS = {"npc_0", "npc_1"}


# ── fetch ─────────────────────────────────────────────────────────

def test_fetch_winnable_for_carryable(manifest):
    ok, reason = objective_winnable(
        {"type": "fetch", "target": "key_0"}, manifest=manifest, npc_ids=NPCS)
    assert ok is True
    assert reason == ""


def test_fetch_unwinnable_target_missing(manifest):
    ok, reason = objective_winnable(
        {"type": "fetch", "target": "ghost_9"}, manifest=manifest, npc_ids=NPCS)
    assert ok is False
    assert "ghost_9" in reason


def test_fetch_unwinnable_target_not_carryable(manifest):
    ok, reason = objective_winnable(
        {"type": "fetch", "target": "table_0"}, manifest=manifest, npc_ids=NPCS)
    assert ok is False
    assert "carryable" in reason.lower()


# ── deliver ───────────────────────────────────────────────────────

def test_deliver_winnable(manifest):
    ok, reason = objective_winnable(
        {"type": "deliver", "target": "key_0", "recipient": "npc_1"},
        manifest=manifest, npc_ids=NPCS)
    assert ok is True
    assert reason == ""


def test_deliver_unwinnable_recipient_missing(manifest):
    ok, reason = objective_winnable(
        {"type": "deliver", "target": "key_0", "recipient": "npc_9"},
        manifest=manifest, npc_ids=NPCS)
    assert ok is False
    assert "recipient" in reason.lower()


def test_deliver_unwinnable_target_not_carryable(manifest):
    ok, reason = objective_winnable(
        {"type": "deliver", "target": "table_0", "recipient": "npc_1"},
        manifest=manifest, npc_ids=NPCS)
    assert ok is False
    assert "carryable" in reason.lower()


# ── place ─────────────────────────────────────────────────────────

def test_place_winnable_on_surface(manifest):
    ok, reason = objective_winnable(
        {"type": "place", "target": "book_1", "location": "table_0"},
        manifest=manifest, npc_ids=NPCS)
    assert ok is True
    assert reason == ""


def test_place_unwinnable_location_has_no_surface(manifest):
    # rug is decor — nothing can be placed "on" it
    ok, reason = objective_winnable(
        {"type": "place", "target": "book_1", "location": "rug_3"},
        manifest=manifest, npc_ids=NPCS)
    assert ok is False
    assert "surface" in reason.lower()


def test_place_unwinnable_location_missing(manifest):
    ok, reason = objective_winnable(
        {"type": "place", "target": "book_1", "location": "nowhere_9"},
        manifest=manifest, npc_ids=NPCS)
    assert ok is False
    assert "nowhere_9" in reason


# ── talk ──────────────────────────────────────────────────────────

def test_talk_winnable(manifest):
    ok, reason = objective_winnable(
        {"type": "talk", "target": "npc_1"}, manifest=manifest, npc_ids=NPCS)
    assert ok is True
    assert reason == ""


def test_talk_unwinnable_npc_missing(manifest):
    ok, reason = objective_winnable(
        {"type": "talk", "target": "npc_9"}, manifest=manifest, npc_ids=NPCS)
    assert ok is False
    assert "npc_9" in reason


# ── unknown type ──────────────────────────────────────────────────

def test_unknown_type_unwinnable(manifest):
    ok, reason = objective_winnable(
        {"type": "teleport", "target": "key_0"}, manifest=manifest, npc_ids=NPCS)
    assert ok is False
    assert "teleport" in reason


def test_objective_types_constant():
    assert OBJECTIVE_TYPES == ("fetch", "deliver", "place", "talk")


# ── chain solvability (DAG) ───────────────────────────────────────

def test_chain_linear_solvable():
    quests = [
        {"quest_id": "a", "objective": {"depends_on": []}},
        {"quest_id": "b", "objective": {"depends_on": ["a"]}},
        {"quest_id": "c", "objective": {"depends_on": ["b"]}},
    ]
    ok, reason = chain_solvable(quests)
    assert ok is True
    assert reason == ""


def test_chain_no_deps_solvable():
    quests = [
        {"quest_id": "a", "objective": {}},
        {"quest_id": "b", "objective": {}},
    ]
    ok, reason = chain_solvable(quests)
    assert ok is True


def test_chain_cycle_unsolvable():
    quests = [
        {"quest_id": "a", "objective": {"depends_on": ["b"]}},
        {"quest_id": "b", "objective": {"depends_on": ["a"]}},
    ]
    ok, reason = chain_solvable(quests)
    assert ok is False
    assert "cycle" in reason.lower()


def test_chain_dangling_dependency_unsolvable():
    quests = [
        {"quest_id": "a", "objective": {"depends_on": ["ghost"]}},
    ]
    ok, reason = chain_solvable(quests)
    assert ok is False
    assert "ghost" in reason


def test_chain_duplicate_quest_id_unsolvable():
    quests = [
        {"quest_id": "a", "objective": {}},
        {"quest_id": "a", "objective": {}},
    ]
    ok, reason = chain_solvable(quests)
    assert ok is False
    assert "duplicate" in reason.lower()


def test_chain_self_dependency_is_cycle():
    quests = [{"quest_id": "a", "objective": {"depends_on": ["a"]}}]
    ok, reason = chain_solvable(quests)
    assert ok is False
    assert "cycle" in reason.lower()
