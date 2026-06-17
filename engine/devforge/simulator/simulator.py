"""Balance Simulator — Monte Carlo combat simulations over the Lorekeeper content DB.

Deterministic core (tier 0): no LLM calls. Answers questions like:
- "Can a level-10 player survive 3 goblin encounters in a row?"
- "Is the endgame sword affordable at the expected gold rate?"
- "Does the dragon boss one-shot players at the intended level?"

Feeds from Lorekeeper data files. The combat engine uses configurable
formulas so the user can match their game's actual damage math.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable

from devforge.infrastructure.logger import logger

# ── Combat data model ────────────────────────────────────────────


@dataclass
class Combatant:
    """A participant in combat simulation."""

    id: str  # unique identifier
    name: str  # display name
    hp: int = 100
    max_hp: int = 100
    attack: int = 10  # base damage before variance
    defense: int = 5  # flat damage reduction
    speed: int = 10  # turn order (higher = faster)
    accuracy: float = 0.9  # hit chance (0.0–1.0)
    crit_chance: float = 0.1  # critical hit probability
    crit_multiplier: float = 1.5  # crit damage multiplier
    level: int = 1
    tags: list[str] = field(default_factory=list)

    def is_alive(self) -> bool:
        return self.hp > 0

    def take_damage(self, amount: int) -> int:
        """Apply damage. Returns actual damage dealt."""
        actual = max(0, amount)
        self.hp = max(0, self.hp - actual)
        return actual

    def heal(self, amount: int) -> int:
        """Heal up to max_hp. Returns actual HP restored."""
        before = self.hp
        self.hp = min(self.max_hp, self.hp + amount)
        return self.hp - before

    def clone(self) -> Combatant:
        """Deep-clone for simulation runs."""
        return Combatant(
            id=self.id,
            name=self.name,
            hp=self.hp,
            max_hp=self.max_hp,
            attack=self.attack,
            defense=self.defense,
            speed=self.speed,
            accuracy=self.accuracy,
            crit_chance=self.crit_chance,
            crit_multiplier=self.crit_multiplier,
            level=self.level,
            tags=list(self.tags),
        )


@dataclass
class Encounter:
    """A group of enemies the player must fight."""

    id: str  # "goblin_patrol"
    name: str  # "Goblin Patrol"
    enemies: list[str] = field(default_factory=list)  # combatant IDs
    enemy_counts: dict[str, int] = field(default_factory=dict)  # id → count


@dataclass
class SimulationResult:
    """Results of a Monte Carlo simulation run."""

    encounter_id: str
    encounter_name: str
    total_simulations: int
    player_wins: int
    player_losses: int
    win_probability: float
    avg_rounds: float
    avg_player_hp_remaining: float
    avg_damage_dealt: float
    avg_damage_taken: float
    avg_crits_landed: float
    player_first_turn_pct: float  # % of fights where player goes first
    one_shot_probability: float  # % where player dies in first 2 rounds
    flawless_victory_probability: float  # % where player takes 0 damage

    def to_dict(self) -> dict:
        return {
            "encounter_id": self.encounter_id,
            "encounter_name": self.encounter_name,
            "total_simulations": self.total_simulations,
            "player_wins": self.player_wins,
            "player_losses": self.player_losses,
            "win_probability": round(self.win_probability, 4),
            "avg_rounds": round(self.avg_rounds, 2),
            "avg_player_hp_remaining": round(self.avg_player_hp_remaining, 1),
            "avg_damage_dealt": round(self.avg_damage_dealt, 1),
            "avg_damage_taken": round(self.avg_damage_taken, 1),
            "avg_crits_landed": round(self.avg_crits_landed, 1),
            "player_first_turn_pct": round(self.player_first_turn_pct, 3),
            "one_shot_probability": round(self.one_shot_probability, 4),
            "flawless_victory_probability": round(self.flawless_victory_probability, 4),
        }


# ── Damage formula (configurable) ─────────────────────────────────


def default_damage_formula(attacker: Combatant, defender: Combatant) -> int:
    """Default damage formula: attack - defense with ±20% variance.

    Override this with a callable matching your game's actual formula.
    """
    base = attacker.attack - int(defender.defense * 0.5)
    base = max(1, base)  # minimum 1 damage
    variance = random.uniform(0.8, 1.2)
    return max(1, int(base * variance))


def default_hit_check(attacker: Combatant, _defender: Combatant) -> bool:
    """Default hit check: roll against attacker's accuracy."""
    return random.random() < attacker.accuracy


def default_crit_check(attacker: Combatant, _defender: Combatant) -> bool:
    """Default crit check: roll against attacker's crit_chance."""
    return random.random() < attacker.crit_chance


# ── Combat engine ────────────────────────────────────────────────


@dataclass
class CombatLogEntry:
    """A single round entry for analysis."""

    round_num: int
    attacker_id: str
    defender_id: str
    damage: int
    was_crit: bool
    defender_hp_after: int


def simulate_combat(
    player: Combatant,
    enemies: list[Combatant],
    *,
    damage_formula: Callable[[Combatant, Combatant], int] = default_damage_formula,
    hit_check: Callable[[Combatant, Combatant], bool] = default_hit_check,
    crit_check: Callable[[Combatant, Combatant], bool] = default_crit_check,
    max_rounds: int = 500,
    seed: int | None = None,
) -> tuple[bool, list[CombatLogEntry], dict[str, Any]]:
    """Run one deterministic combat simulation.

    Returns:
        (player_won, combat_log, stats_dict)
        stats_dict contains: rounds, player_hp_remaining, damage_dealt,
                             damage_taken, crits_landed, player_first,
                             one_shot, flawless
    """
    if seed is not None:
        random.seed(seed)

    p = player.clone()
    e_list = [e.clone() for e in enemies]

    log: list[CombatLogEntry] = []
    round_num = 0
    damage_dealt = 0
    damage_taken = 0
    crits_landed = 0
    player_first = False
    one_shot = False
    flawless = True

    # Determine first turn
    fastest_enemy = max(e_list, key=lambda e: e.speed) if e_list else None
    if fastest_enemy is None:
        return True, log, _build_stats(0, player.max_hp, 0, 0, 0, True, False, True)

    player_first = p.speed >= fastest_enemy.speed

    while round_num < max_rounds:
        round_num += 1

        # Player's turn
        if player_first:
            alive_enemies = [e for e in e_list if e.is_alive()]
            if not alive_enemies:
                break

            # Pick target (highest threat = highest attack)
            target = max(alive_enemies, key=lambda e: (e.attack, e.speed))
            result = _attack(p, target, damage_formula, hit_check, crit_check)
            if result:
                dmg, was_crit = result
                damage_dealt += dmg
                if was_crit:
                    crits_landed += 1
                log.append(
                    CombatLogEntry(
                        round_num=round_num,
                        attacker_id=p.id,
                        defender_id=target.id,
                        damage=dmg,
                        was_crit=was_crit,
                        defender_hp_after=target.hp,
                    )
                )

        # Enemy turns
        for enemy in e_list:
            if not enemy.is_alive():
                continue
            if not p.is_alive():
                break

            result = _attack(enemy, p, damage_formula, hit_check, crit_check)
            if result:
                dmg, was_crit = result
                damage_taken += dmg
                if flawless:
                    flawless = False
                log.append(
                    CombatLogEntry(
                        round_num=round_num,
                        attacker_id=enemy.id,
                        defender_id=p.id,
                        damage=dmg,
                        was_crit=was_crit,
                        defender_hp_after=p.hp,
                    )
                )

        # Check end conditions
        if not p.is_alive():
            if round_num <= 2:
                one_shot = True
            break

        if not any(e.is_alive() for e in e_list):
            break

    player_won = p.is_alive()
    stats = _build_stats(
        round_num,
        p.hp,
        damage_dealt,
        damage_taken,
        crits_landed,
        player_first,
        one_shot,
        flawless,
    )
    return player_won, log, stats


def _attack(
    attacker: Combatant,
    defender: Combatant,
    damage_formula: Callable,
    hit_check: Callable,
    crit_check: Callable,
) -> tuple[int, bool] | None:
    """Execute one attack. Returns (damage, was_crit) or None on miss."""
    if not hit_check(attacker, defender):
        return None

    base_damage = damage_formula(attacker, defender)
    was_crit = crit_check(attacker, defender)
    if was_crit:
        base_damage = int(base_damage * attacker.crit_multiplier)

    actual = defender.take_damage(base_damage)
    return actual, was_crit


def _build_stats(
    rounds: int,
    player_hp: int,
    damage_dealt: int,
    damage_taken: int,
    crits_landed: int,
    player_first: bool,
    one_shot: bool,
    flawless: bool,
) -> dict:
    return {
        "rounds": rounds,
        "player_hp_remaining": player_hp,
        "damage_dealt": damage_dealt,
        "damage_taken": damage_taken,
        "crits_landed": crits_landed,
        "player_first": player_first,
        "one_shot": one_shot,
        "flawless": flawless,
    }


# ── Monte Carlo runner ───────────────────────────────────────────


def monte_carlo_encounter(
    player: Combatant,
    enemies: list[Combatant],
    encounter_id: str,
    encounter_name: str,
    *,
    simulations: int = 1000,
    damage_formula: Callable = default_damage_formula,
    hit_check: Callable = default_hit_check,
    crit_check: Callable = default_crit_check,
    max_rounds: int = 500,
) -> SimulationResult:
    """Run Monte Carlo simulations for a single encounter.

    Returns a SimulationResult with aggregate statistics.
    """
    wins = 0
    losses = 0
    total_rounds = 0
    total_hp_remaining = 0
    total_damage_dealt = 0
    total_damage_taken = 0
    total_crits = 0
    first_turns = 0
    one_shots = 0
    flawless_victories = 0

    for i in range(simulations):
        won, _, stats = simulate_combat(
            player,
            enemies,
            damage_formula=damage_formula,
            hit_check=hit_check,
            crit_check=crit_check,
            max_rounds=max_rounds,
            seed=None,  # let system entropy vary each run
        )

        if won:
            wins += 1
        else:
            losses += 1

        total_rounds += stats["rounds"]
        total_hp_remaining += stats["player_hp_remaining"]
        total_damage_dealt += stats["damage_dealt"]
        total_damage_taken += stats["damage_taken"]
        total_crits += stats["crits_landed"]
        if stats["player_first"]:
            first_turns += 1
        if stats["one_shot"]:
            one_shots += 1
        if stats["flawless"]:
            flawless_victories += 1

    n = float(simulations)
    return SimulationResult(
        encounter_id=encounter_id,
        encounter_name=encounter_name,
        total_simulations=simulations,
        player_wins=wins,
        player_losses=losses,
        win_probability=wins / n,
        avg_rounds=total_rounds / n,
        avg_player_hp_remaining=total_hp_remaining / n if wins > 0 else 0.0,
        avg_damage_dealt=total_damage_dealt / n,
        avg_damage_taken=total_damage_taken / n,
        avg_crits_landed=total_crits / n,
        player_first_turn_pct=first_turns / n,
        one_shot_probability=one_shots / n,
        flawless_victory_probability=flawless_victories / n,
    )


def monte_carlo_gauntlet(
    player: Combatant,
    encounters: list[dict],
    enemy_lookup: dict[str, dict] | None = None,
    *,
    simulations: int = 1000,
    **kwargs,
) -> list[SimulationResult]:
    """Run Monte Carlo across a sequence of encounters (no healing between).

    Each dict in *encounters* has: enemies (IDs), enemy_counts (dict).
    *enemy_lookup* maps enemy ID → raw dict for combatant_from_entry.
    The player's HP carries over between encounters.
    Returns per-encounter results.
    """
    lookup = enemy_lookup or {}
    results: list[SimulationResult] = []
    # For gauntlet, run full sequence per simulation
    win_counts = [0] * len(encounters)
    round_counts = [0.0] * len(encounters)
    hp_remaining = [0.0] * len(encounters)

    for _ in range(simulations):
        p = player.clone()
        survived_all = True
        for ei, enc in enumerate(encounters):
            enemy_list = _build_enemy_list(enc["enemies"], enc.get("enemy_counts", {}), lookup, **kwargs)
            if not enemy_list:
                continue
            won, _, stats = simulate_combat(p, enemy_list, **kwargs)
            if won:
                win_counts[ei] += 1
                hp_remaining[ei] += stats["player_hp_remaining"]
                # HP carries over (no heal)
            else:
                survived_all = False
            round_counts[ei] += stats["rounds"]
            if not survived_all:
                break  # player died, stop gauntlet

    n = float(simulations)
    for ei, enc in enumerate(encounters):
        results.append(
            SimulationResult(
                encounter_id=enc.get("id", f"encounter_{ei}"),
                encounter_name=enc.get("name", f"Encounter {ei + 1}"),
                total_simulations=simulations,
                player_wins=win_counts[ei],
                player_losses=simulations - win_counts[ei],
                win_probability=win_counts[ei] / n,
                avg_rounds=round_counts[ei] / n,
                avg_player_hp_remaining=hp_remaining[ei] / n if win_counts[ei] > 0 else 0.0,
                avg_damage_dealt=0.0,  # not tracked per-encounter in gauntlet
                avg_damage_taken=0.0,
                avg_crits_landed=0.0,
                player_first_turn_pct=0.0,
                one_shot_probability=0.0,
                flawless_victory_probability=0.0,
            )
        )

    return results


# ── Lorekeeper integration ───────────────────────────────────────


def combatant_from_entry(
    entry: dict,
    hp_field: str = "hp",
    attack_field: str = "attack",
    defense_field: str = "defense",
    speed_field: str = "speed",
    level_field: str = "level",
) -> Combatant:
    """Convert a Lorekeeper data entry into a Combatant.

    Uses configurable field name mappings so the user can match
    their game's actual schema field names.
    """
    return Combatant(
        id=str(entry.get("id", entry.get("name", "unknown"))),
        name=str(entry.get("name", entry.get("id", "unknown"))),
        hp=int(entry.get(hp_field, 100)),
        max_hp=int(entry.get(hp_field, 100)),
        attack=int(entry.get(attack_field, 10)),
        defense=int(entry.get(defense_field, 5)),
        speed=int(entry.get(speed_field, 10)),
        accuracy=float(entry.get("accuracy", 0.9)),
        crit_chance=float(entry.get("crit_chance", 0.1)),
        crit_multiplier=float(entry.get("crit_multiplier", 1.5)),
        level=int(entry.get(level_field, 1)),
        tags=list(entry.get("tags", [])),
    )


def _build_enemy_list(
    enemies: list[str],
    enemy_counts: dict[str, int],
    enemy_lookup: dict[str, dict],
    **field_mappings,
) -> list[Combatant]:
    """Build a list of enemy Combatants from IDs, counts, and a data lookup."""
    result: list[Combatant] = []
    for eid in enemies:
        if eid not in enemy_lookup:
            logger.warn("simulator", f"Enemy '{eid}' not found in lookup")
            continue
        count = enemy_counts.get(eid, 1)
        for _ in range(count):
            result.append(combatant_from_entry(enemy_lookup[eid], **field_mappings))
    return result


# ── High-level orchestrator ──────────────────────────────────────


def evaluate_encounter(
    player_data: dict,
    enemy_data: list[dict],
    encounter_enemies: list[str],
    encounter_counts: dict[str, int] | None = None,
    *,
    encounter_id: str = "custom",
    encounter_name: str = "Custom Encounter",
    simulations: int = 1000,
    hp_field: str = "hp",
    attack_field: str = "attack",
    defense_field: str = "defense",
    speed_field: str = "speed",
    level_field: str = "level",
) -> dict:
    """High-level entry point: evaluate one encounter.

    *player_data*: single dict with player stats.
    *enemy_data*: list of dicts, each an enemy definition.
    *encounter_enemies*: list of enemy IDs to include.
    *encounter_counts*: dict of enemy_id → count (defaults to 1 each).
    """
    player = combatant_from_entry(
        player_data,
        hp_field=hp_field,
        attack_field=attack_field,
        defense_field=defense_field,
        speed_field=speed_field,
        level_field=level_field,
    )

    # Build lookup
    enemy_lookup: dict[str, dict] = {}
    for e in enemy_data:
        eid = str(e.get("id", e.get("name", "")))
        enemy_lookup[eid] = e

    counts = encounter_counts or {}
    enemy_list: list[Combatant] = []
    for eid in encounter_enemies:
        if eid not in enemy_lookup:
            logger.warn("simulator", f"Enemy '{eid}' not found in enemy data")
            continue
        count = counts.get(eid, 1)
        for _ in range(count):
            enemy_list.append(
                combatant_from_entry(
                    enemy_lookup[eid],
                    hp_field=hp_field,
                    attack_field=attack_field,
                    defense_field=defense_field,
                    speed_field=speed_field,
                    level_field=level_field,
                )
            )

    result = monte_carlo_encounter(
        player,
        enemy_list,
        encounter_id=encounter_id,
        encounter_name=encounter_name,
        simulations=simulations,
    )
    return result.to_dict()


def evaluate_level_progression(
    player_base: dict,
    enemy_data: list[dict],
    level_range: range,
    encounters: list[dict],
    *,
    simulations: int = 500,
    **field_mappings,
) -> dict:
    """Evaluate how a player fares against encounters at each level.

    Scales player stats linearly with level (hp += 10/lvl, attack += 2/lvl, etc.).
    Returns per-level win probabilities.
    """
    results: dict[int, dict[str, float]] = {}
    for level in level_range:
        scaled = dict(player_base)
        scaled["level"] = level
        scaled["hp"] = int(player_base.get("hp", 100)) + (level - 1) * 10
        scaled["attack"] = int(player_base.get("attack", 10)) + (level - 1) * 2
        scaled["defense"] = int(player_base.get("defense", 5)) + (level - 1) * 1

        player = combatant_from_entry(scaled, **field_mappings)

        level_results: dict[str, float] = {}
        for enc in encounters:
            enemy_list: list[Combatant] = []
            enemy_lookup = {str(e.get("id", e.get("name", ""))): e for e in enemy_data}
            for eid in enc.get("enemies", []):
                count = enc.get("enemy_counts", {}).get(eid, 1)
                if eid in enemy_lookup:
                    for _ in range(count):
                        enemy_list.append(
                            combatant_from_entry(
                                enemy_lookup[eid],
                                **field_mappings,
                            )
                        )

            r = monte_carlo_encounter(
                player,
                enemy_list,
                encounter_id=enc.get("id", "unknown"),
                encounter_name=enc.get("name", "Unknown"),
                simulations=simulations,
            )
            level_results[enc["id"]] = r.win_probability

        results[level] = level_results

    return {
        "levels": list(level_range),
        "encounter_ids": [e["id"] for e in encounters],
        "win_probabilities": {
            str(level): {eid: round(prob, 4) for eid, prob in probs.items()} for level, probs in results.items()
        },
        "sweet_spot": _find_sweet_spot(results),
    }


def _find_sweet_spot(results: dict[int, dict[str, float]]) -> dict:
    """Find the level range where win rates are 40-70% (the 'fun zone')."""
    sweet: dict[str, str] = {}
    for eid in next(iter(results.values())).keys():
        levels_in_zone = []
        for level in sorted(results):
            prob = results[level].get(eid, 0.0)
            if 0.40 <= prob <= 0.75:
                levels_in_zone.append(level)
        if levels_in_zone:
            sweet[eid] = f"Levels {min(levels_in_zone)}–{max(levels_in_zone)}"
        else:
            sweet[eid] = "no sweet spot found"
    return sweet
