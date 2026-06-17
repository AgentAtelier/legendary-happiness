"""Balance Simulator — Monte Carlo combat simulations over the Lorekeeper content DB."""

from devforge.simulator.simulator import (
    Combatant,
    CombatLogEntry,
    Encounter,
    SimulationResult,
    combatant_from_entry,
    default_crit_check,
    default_damage_formula,
    default_hit_check,
    evaluate_encounter,
    evaluate_level_progression,
    monte_carlo_encounter,
    monte_carlo_gauntlet,
    simulate_combat,
)

__all__ = [
    "Combatant",
    "Encounter",
    "SimulationResult",
    "CombatLogEntry",
    "simulate_combat",
    "monte_carlo_encounter",
    "monte_carlo_gauntlet",
    "evaluate_encounter",
    "evaluate_level_progression",
    "combatant_from_entry",
    "default_damage_formula",
    "default_hit_check",
    "default_crit_check",
]
