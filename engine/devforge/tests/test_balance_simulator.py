"""Unit tests for Balance Simulator: combat engine, Monte Carlo runner, Lorekeeper integration.

Tests: simulate_combat (deterministic), monte_carlo (statistical), evaluate_encounter,
evaluate_level_progression, edge cases.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── simulate_combat ──────────────────────────────────────────────


def test_player_wins_easy_encounter() -> None:
    """Player with strong stats wins a 1v1 against a weak goblin."""
    from devforge.simulator.simulator import simulate_combat, Combatant

    player = Combatant(id="hero", name="Hero", hp=100, attack=20, defense=10, speed=15)
    goblin = Combatant(id="goblin", name="Goblin", hp=20, attack=5, defense=2, speed=8)

    won, log, stats = simulate_combat(player, [goblin], seed=42)
    assert won, "Player should beat a single weak goblin"
    assert stats["rounds"] > 0
    assert stats["player_hp_remaining"] > 0


def test_player_loses_to_strong_enemy() -> None:
    """Player loses against a much stronger enemy."""
    from devforge.simulator.simulator import simulate_combat, Combatant

    player = Combatant(id="hero", name="Hero", hp=20, attack=5, defense=2, speed=8)
    dragon = Combatant(id="dragon", name="Dragon", hp=200, attack=40, defense=15, speed=20)

    won, log, stats = simulate_combat(player, [dragon], seed=99)
    assert not won, "Player should lose against a dragon"
    assert stats["player_hp_remaining"] == 0


def test_deterministic_with_seed() -> None:
    """Same seed produces identical results."""
    from devforge.simulator.simulator import simulate_combat, Combatant

    player = Combatant(id="hero", name="Hero", hp=100, attack=15, defense=8, speed=10)
    enemy = Combatant(id="ogre", name="Ogre", hp=60, attack=12, defense=5, speed=10)

    won1, _, s1 = simulate_combat(player, [enemy], seed=42)
    won2, _, s2 = simulate_combat(player, [enemy], seed=42)

    assert won1 == won2
    assert s1["rounds"] == s2["rounds"]
    assert s1["player_hp_remaining"] == s2["player_hp_remaining"]
    assert s1["damage_dealt"] == s2["damage_dealt"]


def test_combat_seed_none_stochastic() -> None:
    """Without seed, two runs should differ (stochastic combat)."""
    from devforge.simulator.simulator import simulate_combat, Combatant

    player = Combatant(id="hero", name="Hero", hp=1000, attack=15, defense=8, speed=10)
    enemy = Combatant(id="ogre", name="Ogre", hp=1000, attack=12, defense=5, speed=10)

    won1, _, s1 = simulate_combat(player, [enemy], seed=None)
    won2, _, s2 = simulate_combat(player, [enemy], seed=None)

    # Long fight with high variance — almost certainly differ
    assert s1["rounds"] != s2["rounds"] or s1["damage_dealt"] != s2["damage_dealt"]


def test_win_probability_converges() -> None:
    """Monte Carlo with many sims should converge to ~0.5 for evenly matched."""
    from devforge.simulator.simulator import monte_carlo_encounter, Combatant

    # Evenly matched: identical stats
    player = Combatant(id="hero", name="Hero", hp=50, attack=10, defense=5, speed=10)
    enemy = Combatant(id="clone", name="Clone", hp=50, attack=10, defense=5, speed=10)

    result = monte_carlo_encounter(
        player,
        [enemy],
        encounter_id="test",
        encounter_name="Test",
        simulations=2000,
    )

    # Player has first-turn advantage (tie goes to player for equal speed)
    assert 0.50 <= result.win_probability <= 0.75, f"Expected win probability ~0.55-0.70, got {result.win_probability}"
    assert result.total_simulations == 2000
    assert result.player_wins + result.player_losses == 2000


def test_varied_damage_rolls() -> None:
    """Combat log entries have varied damage due to variance."""
    from devforge.simulator.simulator import simulate_combat, Combatant

    player = Combatant(id="hero", name="Hero", hp=500, attack=15, defense=10, speed=20)
    enemy = Combatant(id="tank", name="Tank", hp=200, attack=5, defense=20, speed=5)

    _, log, _ = simulate_combat(player, [enemy], seed=None, max_rounds=200)
    damages = {e.damage for e in log if e.attacker_id == "hero"}
    assert len(damages) > 1, "Damage should vary due to ±20% variance"


# ── Combatant helpers ────────────────────────────────────────────


def test_combatant_clone_is_independent() -> None:
    """Clone creates an independent copy."""
    from devforge.simulator.simulator import Combatant

    a = Combatant(id="hero", name="Hero", hp=100)
    b = a.clone()
    b.take_damage(50)
    assert a.hp == 100
    assert b.hp == 50


def test_combatant_heal_capped() -> None:
    """Heal doesn't exceed max_hp."""
    from devforge.simulator.simulator import Combatant

    c = Combatant(id="hero", name="Hero", hp=80, max_hp=100)
    healed = c.heal(50)
    assert healed == 20
    assert c.hp == 100


# ── evaluate_encounter ───────────────────────────────────────────


def test_evaluate_encounter_returns_valid_result() -> None:
    """evaluate_encounter produces correct result dict."""
    from devforge.simulator.simulator import evaluate_encounter

    player = {"id": "hero", "name": "Hero", "hp": 100, "attack": 15, "defense": 8, "speed": 12, "level": 5}
    enemies = [
        {"id": "goblin", "name": "Goblin", "hp": 25, "attack": 6, "defense": 3, "speed": 8, "level": 2},
        {"id": "orc", "name": "Orc", "hp": 50, "attack": 10, "defense": 5, "speed": 6, "level": 3},
    ]

    result = evaluate_encounter(
        player_data=player,
        enemy_data=enemies,
        encounter_enemies=["goblin"],
        encounter_counts={"goblin": 2},
        simulations=500,
    )

    assert result["total_simulations"] == 500
    assert result["player_wins"] + result["player_losses"] == 500
    assert 0.0 <= result["win_probability"] <= 1.0
    assert result["avg_rounds"] > 0
    assert result["encounter_id"] == "custom"


def test_evaluate_encounter_missing_enemy_warns() -> None:
    """Unknown enemy ID is skipped gracefully."""
    from devforge.simulator.simulator import evaluate_encounter

    player = {"id": "hero", "name": "Hero", "hp": 100, "attack": 10, "defense": 5, "speed": 10, "level": 1}
    enemies = [{"id": "goblin", "name": "Goblin", "hp": 20, "attack": 5, "defense": 2, "speed": 8, "level": 1}]

    result = evaluate_encounter(
        player_data=player,
        enemy_data=enemies,
        encounter_enemies=["unknown_boss"],
        simulations=100,
    )

    # Should still return a valid result, just with no enemies (instant win)
    assert result["win_probability"] == 1.0


# ── Monte Carlo gauntlet ─────────────────────────────────────────


def test_monte_carlo_gauntlet_player_dies() -> None:
    """In a gauntlet of tough enemies, player win rate drops across encounters."""
    from devforge.simulator.simulator import monte_carlo_gauntlet, Combatant

    player = Combatant(id="hero", name="Hero", hp=50, attack=10, defense=5, speed=10)
    encounters = [
        {"id": "e1", "name": "First", "enemies": ["goblin"], "enemy_counts": {"goblin": 2}},
        {"id": "e2", "name": "Second", "enemies": ["goblin"], "enemy_counts": {"goblin": 2}},
    ]

    # Build the enemies list inline
    goblin_data = {"id": "goblin", "name": "Goblin", "hp": 25, "attack": 7, "defense": 3, "speed": 8, "level": 2}
    enemy_lookup = {"goblin": goblin_data}

    results = monte_carlo_gauntlet(
        player,
        encounters,
        enemy_lookup,
        simulations=500,
    )

    assert len(results) == 2
    # Second encounter should have lower or equal win rate (HP carries over)
    assert results[1].win_probability <= results[0].win_probability + 0.02  # tolerance


# ── evaluate_level_progression ───────────────────────────────────


def test_level_progression_finds_sweet_spots() -> None:
    """Level progression identifies levels where encounters are balanced."""
    from devforge.simulator.simulator import evaluate_level_progression

    player = {"id": "hero", "name": "Hero", "hp": 80, "attack": 10, "defense": 5, "speed": 10, "level": 1}
    enemies = [
        {"id": "goblin", "name": "Goblin", "hp": 30, "attack": 8, "defense": 3, "speed": 8, "level": 2},
        {"id": "orc", "name": "Orc", "hp": 60, "attack": 12, "defense": 6, "speed": 6, "level": 4},
    ]
    encounters = [
        {"id": "goblin_patrol", "name": "Goblin Patrol", "enemies": ["goblin"], "enemy_counts": {"goblin": 2}},
    ]

    result = evaluate_level_progression(
        player_base=player,
        enemy_data=enemies,
        level_range=range(1, 6),
        encounters=encounters,
        simulations=200,
        hp_field="hp",
        attack_field="attack",
        defense_field="defense",
        speed_field="speed",
        level_field="level",
    )

    assert len(result["levels"]) == 5  # levels 1–5
    assert "goblin_patrol" in result["encounter_ids"]
    assert "sweet_spot" in result
    # Sweet spot should exist for at least one encounter
    sweet = result["sweet_spot"]
    assert sweet, "sweet_spot dict should not be empty"


# ── Main ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_player_wins_easy_encounter,
        test_player_loses_to_strong_enemy,
        test_deterministic_with_seed,
        test_combat_seed_none_stochastic,
        test_win_probability_converges,
        test_varied_damage_rolls,
        test_combatant_clone_is_independent,
        test_combatant_heal_capped,
        test_evaluate_encounter_returns_valid_result,
        test_evaluate_encounter_missing_enemy_warns,
        test_monte_carlo_gauntlet_player_dies,
        test_level_progression_finds_sweet_spots,
    ]

    passed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {test.__name__}: {e}")

    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)
