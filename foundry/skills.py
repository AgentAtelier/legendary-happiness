"""skills — CB-6 skill domains, affordances, practice/decay.

Anvil port: 7 skill domains, unlockable affordances, practice/decay,
perceptibility→animation mapping.  Each skill is a standalone,
extractable progression system.

Skill schema (the CB-6 data contract, per-skill):
```python
{
    "domain": "combat",
    "level": 0,               # 0-100
    "xp": 0.0,                # progress toward next level
    "xp_per_level": 50.0,     # base XP needed per level (scales)
    "decay_rate": 0.01,       # XP lost per tick when not practiced
    "affordances": [],        # unlocked ability IDs
    "last_practiced_tick": 0,
}
```

Affordances are unlocks gated by skill level (e.g. "power_attack" at
combat 25, "dodge_roll" at combat 50).
"""

from __future__ import annotations

from typing import Dict, List, Optional


# ── Skill domain definitions ────────────────────────────────────

SKILL_DOMAINS: Dict[str, dict] = {
    "combat": {
        "name": "Combat",
        "description": "Melee fighting ability — damage, swing speed, parry.",
        "xp_per_hit": 4.0,
        "xp_per_kill": 15.0,
        "xp_per_level": 50.0,
        "decay_rate": 0.005,
        "affordances": {
            10: "quick_slash",       # faster swing cooldown
            25: "power_attack",      # bonus damage on charged swing
            50: "dodge_roll",         # iframe dodge
            75: "riposte",           # parry counter
            100: "whirlwind",         # AoE spin attack
        },
    },
    "crafting": {
        "name": "Crafting",
        "description": "Creating and repairing items — quality, speed, material efficiency.",
        "xp_per_craft": 8.0,
        "xp_per_repair": 4.0,
        "xp_per_level": 40.0,
        "decay_rate": 0.002,
        "affordances": {
            10: "simple_repair",
            25: "quality_craft",     # +1 quality tier
            50: "material_efficiency",  # 50% material cost
            75: "masterwork",        # unique item crafting
            100: "legendary_craft",   # best-in-slot items
        },
    },
    "athletics": {
        "name": "Athletics",
        "description": "Movement ability — sprint speed, jump height, stamina.",
        "xp_per_sprint": 0.5,
        "xp_per_jump": 2.0,
        "xp_per_level": 60.0,
        "decay_rate": 0.01,
        "affordances": {
            10: "sprint_boost",
            25: "wall_jump",
            50: "double_jump",
            75: "dash",
            100: "aerial_dash",
        },
    },
    "stealth": {
        "name": "Stealth",
        "description": "Sneaking and detection avoidance — noise reduction, pickpocket.",
        "xp_per_stealth_action": 5.0,
        "xp_per_level": 45.0,
        "decay_rate": 0.003,
        "affordances": {
            10: "quiet_footsteps",
            25: "pickpocket",
            50: "shadow_blend",
            75: "silent_kill",
            100: "ghost_walk",
        },
    },
    "speech": {
        "name": "Speech",
        "description": "Persuasion and bartering — better prices, quest rewards, dialogue options.",
        "xp_per_persuade": 6.0,
        "xp_per_barter": 3.0,
        "xp_per_level": 35.0,
        "decay_rate": 0.001,
        "affordances": {
            10: "haggle",
            25: "persuade",
            50: "intimidate",
            75: "charm",
            100: "silver_tongue",
        },
    },
    "survival": {
        "name": "Survival",
        "description": "Resource gathering and environmental resistance — foraging, cooking.",
        "xp_per_gather": 3.0,
        "xp_per_cook": 5.0,
        "xp_per_level": 40.0,
        "decay_rate": 0.004,
        "affordances": {
            10: "forage_basic",
            25: "cook_basic",
            50: "forage_rare",
            75: "cook_advanced",
            100: "master_forager",
        },
    },
    "perception": {
        "name": "Perception",
        "description": "Detection and awareness — trap spotting, hidden items, enemy radar.",
        "xp_per_detect": 4.0,
        "xp_per_level": 45.0,
        "decay_rate": 0.003,
        "affordances": {
            10: "trap_spotting",
            25: "hidden_items",
            50: "enemy_radar",
            75: "danger_sense",
            100: "true_sight",
        },
    },
}


# ── Skill state management ──────────────────────────────────────

def new_skill_state(domain: str) -> dict:
    """Create a fresh skill state dict for *domain*."""
    dom = SKILL_DOMAINS.get(domain, {})
    return {
        "domain": domain,
        "level": 0,
        "xp": 0.0,
        "xp_per_level": dom.get("xp_per_level", 50.0),
        "decay_rate": dom.get("decay_rate", 0.01),
        "affordances": [],
        "last_practiced_tick": 0,
    }


def gain_xp(skill: dict, amount: float, tick: int = 0) -> dict:
    """Add XP, level up if threshold met, return updated skill dict.

    Modifies the skill dict in-place and returns it.
    """
    skill["xp"] += amount
    skill["last_practiced_tick"] = tick

    # Check level-ups
    while skill["xp"] >= skill["xp_per_level"]:
        skill["xp"] -= skill["xp_per_level"]
        skill["level"] += 1
        skill["xp_per_level"] *= 1.1  # scale per level

        # Check for new affordance unlocks
        dom = SKILL_DOMAINS.get(skill["domain"], {})
        affordances = dom.get("affordances", {})
        for level_threshold, affordance_id in sorted(affordances.items()):
            if skill["level"] >= level_threshold and affordance_id not in skill["affordances"]:
                skill["affordances"].append(affordance_id)

    return skill


def tick_decay(skill: dict, current_tick: int) -> dict:
    """Apply XP decay if the skill hasn't been practiced recently.

    Decays XP toward 0 at the domain's decay_rate per tick since
    last practice.  Does not de-level.
    """
    ticks_since = current_tick - skill.get("last_practiced_tick", 0)
    if ticks_since <= 0:
        return skill

    decay = skill["decay_rate"] * ticks_since
    skill["xp"] = max(0.0, skill["xp"] - decay)
    return skill


def get_affordances(skill: dict) -> List[str]:
    """Return the list of unlocked affordance IDs for a skill."""
    return list(skill.get("affordances", []))


def get_level(skill: dict) -> int:
    """Return the current level of a skill."""
    return skill.get("level", 0)


def all_skills() -> List[str]:
    """Return all skill domain names."""
    return list(SKILL_DOMAINS.keys())


def new_player_skills() -> Dict[str, dict]:
    """Create a fresh set of all skills for a new player."""
    return {domain: new_skill_state(domain) for domain in SKILL_DOMAINS}


def skill_level_to_bonus(level: int, scale: float = 0.01) -> float:
    """Convert a skill level to a multiplicative bonus.

    Level 0 → 1.0, Level 50 → 1.5, Level 100 → 2.0.
    """
    return 1.0 + level * scale


# ── Enemy spec schema (the CB-6 enemy data contract) ────────────

def enemy_spec(
    enemy_id: str,
    archetype: str = "golem",
    health: float = 50.0,
    damage: float = 8.0,
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
) -> dict:
    """Create an enemy spec dict following the CB-6 enemy spec schema.

    ```python
    {
        "enemy_id": "enemy_0",
        "archetype": "golem",
        "health": 50.0,
        "max_health": 50.0,
        "damage": 8.0,
        "aggro_range": 8.0,
        "attack_range": 1.5,
        "attack_cooldown": 1.2,
        "speed": 2.5,
        "placement": {"x": 0.0, "y": 0.0, "z": 0.0},
    }
    ```
    """
    return {
        "enemy_id": enemy_id,
        "archetype": archetype,
        "health": health,
        "max_health": health,
        "damage": damage,
        "aggro_range": 8.0,
        "attack_range": 1.5,
        "attack_cooldown": 1.2,
        "speed": 2.5,
        "placement": {"x": x, "y": y, "z": z},
    }
