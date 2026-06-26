"""Tests for skills — CB-6 skill domains, XP, level-up, decay, enemy spec."""

from __future__ import annotations

from skills import (
    SKILL_DOMAINS,
    all_skills,
    enemy_spec,
    gain_xp,
    get_affordances,
    get_level,
    new_player_skills,
    new_skill_state,
    skill_level_to_bonus,
    tick_decay,
)

# ── Domain validity ─────────────────────────────────────────────

def test_has_7_domains():
    assert len(SKILL_DOMAINS) == 7


def test_domains_are_registered():
    for domain in ("combat", "crafting", "athletics", "stealth", "speech",
                    "survival", "perception"):
        assert domain in SKILL_DOMAINS


def test_each_domain_has_affordances():
    for domain, entry in SKILL_DOMAINS.items():
        assert "affordances" in entry
        aff = entry["affordances"]
        assert len(aff) >= 1  # at least one affordance per domain


def test_all_skills_returns_7():
    assert len(all_skills()) == 7


# ── Skill state ─────────────────────────────────────────────────

def test_new_skill_state_level_zero():
    state = new_skill_state("combat")
    assert state["domain"] == "combat"
    assert state["level"] == 0
    assert state["xp"] == 0.0
    assert state["affordances"] == []
    assert state["last_practiced_tick"] == 0


def test_new_player_skills_has_all():
    skills = new_player_skills()
    assert len(skills) == 7
    for domain in SKILL_DOMAINS:
        assert domain in skills


# ── XP and level-up ─────────────────────────────────────────────

def test_gain_xp_increases():
    state = new_skill_state("combat")
    gain_xp(state, 30.0, tick=1)
    assert state["xp"] == 30.0
    assert state["last_practiced_tick"] == 1


def test_gain_xp_levels_up():
    state = new_skill_state("combat")  # xp_per_level = 50.0
    gain_xp(state, 50.0, tick=1)
    assert state["level"] == 1
    assert state["xp"] == 0.0


def test_gain_xp_multiple_levels():
    state = new_skill_state("combat")
    gain_xp(state, 120.0, tick=1)  # 50 → level 1, remaining 70
    # After level 1: xp_per_level = 50 * 1.1 = 55
    # 70 >= 55 → level 2, remaining 15
    assert state["level"] == 2
    assert abs(state["xp"] - 15.0) < 0.01


def test_gain_xp_unlocks_affordances():
    """At combat level 10, quick_slash is unlocked."""
    state = new_skill_state("combat")
    # Need 50 * 10 = 500 base XP to reach level 10
    # But xp_per_level scales by 1.1 each level
    # Total needed: sum of 50 * 1.1^i for i=0..9
    needed = sum(50.0 * (1.1 ** i) for i in range(10))
    gain_xp(state, needed + 1.0, tick=1)
    assert state["level"] >= 10
    assert "quick_slash" in state["affordances"]


# ── Tick decay ──────────────────────────────────────────────────

def test_tick_decay_reduces_xp():
    state = new_skill_state("combat")
    gain_xp(state, 30.0, tick=1)
    tick_decay(state, current_tick=11)  # 10 ticks since practice
    # combat decay_rate = 0.005, 10 ticks → 0.05 decay
    assert state["xp"] < 30.0


def test_tick_decay_does_not_delevel():
    state = new_skill_state("combat")
    gain_xp(state, 55.0, tick=1)  # leveled up to 1, xp=5
    tick_decay(state, current_tick=1000)  # massive decay
    assert state["xp"] < 0.01, f"xp should be near zero after massive decay, got {state['xp']}"
    assert state["level"] >= 1  # level preserved


def test_tick_decay_no_effect_same_tick():
    state = new_skill_state("combat")
    gain_xp(state, 30.0, tick=5)
    tick_decay(state, current_tick=5)  # no ticks passed
    assert state["xp"] == 30.0


# ── Affordance query ────────────────────────────────────────────

def test_get_affordances_empty_at_level_0():
    state = new_skill_state("combat")
    assert get_affordances(state) == []


def test_get_level():
    state = new_skill_state("combat")
    assert get_level(state) == 0
    gain_xp(state, 50.0, tick=1)
    assert get_level(state) == 1


# ── Skill bonus scaling ─────────────────────────────────────────

def test_skill_level_to_bonus():
    assert abs(skill_level_to_bonus(0) - 1.0) < 0.01
    assert abs(skill_level_to_bonus(50) - 1.5) < 0.01
    assert abs(skill_level_to_bonus(100) - 2.0) < 0.01


# ── Enemy spec schema ───────────────────────────────────────────

def test_enemy_spec_schema():
    spec = enemy_spec("enemy_0", "golem", 50.0, 8.0, 3.0, 0.0, -4.0)
    assert spec["enemy_id"] == "enemy_0"
    assert spec["archetype"] == "golem"
    assert spec["health"] == 50.0
    assert spec["max_health"] == 50.0
    assert spec["damage"] == 8.0
    assert spec["aggro_range"] == 8.0
    assert spec["attack_range"] == 1.5
    assert spec["attack_cooldown"] == 1.2
    assert spec["speed"] == 2.5
    assert spec["placement"] == {"x": 3.0, "y": 0.0, "z": -4.0}


def test_enemy_spec_defaults():
    spec = enemy_spec("enemy_1")
    assert spec["health"] == 50.0
    assert spec["placement"]["x"] == 0.0
