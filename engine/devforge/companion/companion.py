"""Design Companion — genre pattern database for open-world FP RPG.

Deterministic core (tier 0): no LLM calls. Matches the user's game mechanics
against a curated database of genre patterns and suggests missing pieces.

Patterns cover: player mechanics, world systems, UI/UX, progression, content types.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from devforge.infrastructure.logger import logger


@dataclass
class Pattern:
    """A game design pattern for open-world FP RPGs."""

    id: str  # "stamina_gating"
    name: str  # "Stamina Gating"
    category: str  # "player_mechanics" | "world_systems" | "ui_ux" | "progression" | "content"
    description: str  # what the pattern is
    why: str  # why it matters for open-world FP RPG
    detects: list[str] = field(default_factory=list)  # mechanics/features that indicate this pattern exists
    conflicts_with: list[str] = field(default_factory=list)  # pattern IDs that conflict
    requires: list[str] = field(default_factory=list)  # pattern IDs this depends on
    priority: int = 3  # 1=essential, 2=important, 3=nice-to-have

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "why": self.why,
            "priority": self.priority,
        }


# ── Pattern database ─────────────────────────────────────────────

PATTERNS: list[Pattern] = [
    # Player mechanics
    Pattern(
        "stamina_gating",
        "Stamina Gating",
        "player_mechanics",
        "Sprinting, dodging, and power attacks consume a stamina bar that regenerates over time.",
        "Prevents infinite sprint/dodge spam; creates tactical resource management.",
        detects=["stamina", "sprint", "dodge"],
        priority=1,
    ),
    Pattern(
        "crouch_stealth",
        "Crouch & Stealth",
        "player_mechanics",
        "Crouching reduces visibility and noise, enabling stealth play.",
        "Gives players a non-combat approach to encounters; depth for infiltration quests.",
        detects=["crouch", "stealth", "visibility", "noise"],
        priority=2,
    ),
    Pattern(
        "climbing_system",
        "Climbing / Parkour",
        "player_mechanics",
        "Player can climb ledges, walls, and terrain within stamina constraints.",
        "Vertical exploration is a staple of open-world games; without it, mountains are invisible walls.",
        detects=["climb", "mantle", "ledge", "parkour"],
        priority=2,
    ),
    # World systems
    Pattern(
        "day_night_cycle",
        "Day/Night Cycle",
        "world_systems",
        "Time-of-day system with lighting changes, NPC schedules, and gameplay effects.",
        "Makes the world feel alive; enables time-gated content and atmosphere.",
        detects=["time_of_day", "day_night", "sun_light", "night", "dawn"],
        priority=1,
    ),
    Pattern(
        "weather_system",
        "Weather System",
        "world_systems",
        "Dynamic weather (rain, fog, snow, wind) with gameplay effects.",
        "Atmosphere multiplier; rain affects visibility/audio, snow changes terrain.",
        detects=["weather", "rain", "snow", "fog", "wind"],
        requires=["day_night_cycle"],
        priority=2,
    ),
    Pattern(
        "world_streaming",
        "World Streaming",
        "world_systems",
        "Chunk-based world loading/unloading around the player with LOD management.",
        "THE open-world template — without it, you can't have a large seamless world.",
        detects=["streaming", "cell", "chunk", "load_radius", "unload"],
        priority=1,
    ),
    Pattern(
        "fast_travel",
        "Fast Travel",
        "world_systems",
        "Player can teleport between discovered POIs via map or signposts.",
        "Walking across the same terrain for the 50th time is not gameplay.",
        detects=["fast_travel", "teleport", "waypoint", "map_marker"],
        priority=1,
    ),
    Pattern(
        "npc_schedules",
        "NPC Schedules",
        "world_systems",
        "NPCs follow time-of-day routines: work, patrol, sleep, idle.",
        "Makes the world feel inhabited; enables time-based quest availability.",
        detects=["schedule", "waypoint", "patrol", "npc_state"],
        requires=["day_night_cycle"],
        priority=2,
    ),
    # UI/UX
    Pattern(
        "interaction_prompts",
        "Interaction Prompts",
        "ui_ux",
        "Context-sensitive prompts appear when the player looks at interactable objects.",
        "The primary way players discover what they can interact with in a 3D world.",
        detects=["interact", "prompt", "raycast", "interactable"],
        priority=1,
    ),
    Pattern(
        "compass_minimap",
        "Compass / Minimap",
        "ui_ux",
        "On-screen compass or minimap showing objectives, POIs, and cardinal directions.",
        "Open worlds are disorienting without navigation aids.",
        detects=["compass", "minimap", "radar", "navigation"],
        priority=2,
    ),
    Pattern(
        "quest_journal",
        "Quest Journal UI",
        "ui_ux",
        "Tracked quests with objectives, progress, and rewards displayed to the player.",
        "Players can't remember 20 active quests without a journal.",
        detects=["quest_log", "journal", "quest_ui", "objective_tracker"],
        priority=1,
    ),
    Pattern(
        "inventory_grid",
        "Inventory Grid UI",
        "ui_ux",
        "Grid-based or list-based inventory with item icons, tooltips, and drag-drop.",
        "The primary interface for item management — every RPG needs one.",
        detects=["inventory", "item_slot", "grid", "backpack"],
        priority=1,
    ),
    # Progression
    Pattern(
        "leveling_system",
        "XP & Leveling",
        "progression",
        "Players gain XP from combat/quests, level up, and allocate stat points.",
        "The core progression loop; gives players a sense of growth and goal to pursue.",
        detects=["xp", "level_up", "experience", "stat_points"],
        priority=1,
    ),
    Pattern(
        "skill_trees",
        "Skill Trees / Perks",
        "progression",
        "Branching skill trees unlock abilities, passives, and playstyle specialization.",
        "Build variety and replay value; the difference between an RPG and an action game.",
        detects=["skill_tree", "perk", "talent", "ability_unlock"],
        requires=["leveling_system"],
        priority=2,
    ),
    Pattern(
        "equipment_progression",
        "Equipment Progression",
        "progression",
        "Gear tiers (common→rare→epic→legendary) with increasing stats.",
        "The loot loop keeps players exploring and fighting; core to the genre.",
        detects=["equipment", "gear_tier", "rarity", "item_level"],
        priority=2,
    ),
    # Content
    Pattern(
        "loot_system",
        "Loot & Containers",
        "content",
        "Lootable containers, enemy drops, and treasure chests with random or curated loot.",
        "Rewards exploration; every corner of the world promises something to find.",
        detects=["loot", "container", "chest", "drop_table"],
        priority=1,
    ),
    Pattern(
        "crafting_system",
        "Crafting System",
        "content",
        "Players gather resources and craft items, equipment, or consumables.",
        "Extends the loot loop; gives value to otherwise-junk items.",
        detects=["craft", "recipe", "ingredient", "workbench"],
        priority=3,
    ),
    Pattern(
        "rest_mechanics",
        "Rest / Camp Mechanics",
        "content",
        "Players can rest at campfires or beds to heal, pass time, and save.",
        "Creates a gameplay loop of adventure→rest→adventure; dramatic pacing.",
        detects=["rest", "camp", "sleep", "campfire"],
        priority=2,
    ),
]


# ── Pattern matching engine ─────────────────────────────────────


@dataclass
class Suggestion:
    """A design suggestion for a missing pattern."""

    pattern: Pattern
    is_present: bool = False
    evidence: list[str] = field(default_factory=list)  # detected features that match
    missing_dependencies: list[str] = field(default_factory=list)  # unmet requires

    def to_dict(self) -> dict:
        d = self.pattern.to_dict()
        d.update(
            {
                "is_present": self.is_present,
                "evidence": self.evidence,
                "missing_dependencies": self.missing_dependencies or None,
            }
        )
        return d


class DesignCompanion:
    """Matches user's game features against the pattern database.

    Usage::

        companion = DesignCompanion()
        results = companion.analyze(["stamina", "sprint", "inventory", "quest_log"])
    """

    def __init__(self, patterns: list[Pattern] | None = None):
        self._patterns = patterns or PATTERNS

    def analyze(self, features: list[str]) -> dict:
        """Match *features* against the pattern database.

        *features*: list of mechanic/feature names the user's game has
        (e.g. ["stamina", "inventory", "day_night"]).

        Returns present patterns, missing patterns (by priority), and
        a category breakdown.
        """
        features_lower = [f.lower() for f in features]
        suggestions: list[Suggestion] = []

        for pattern in self._patterns:
            # Check if any detect keyword matches
            evidence = [d for d in pattern.detects if any(d.lower() in f for f in features_lower)]
            is_present = len(evidence) > 0

            # Check dependencies
            missing_deps = []
            if not is_present:
                for req_id in pattern.requires:
                    req = self._get_pattern(req_id)
                    if req:
                        req_evidence = [d for d in req.detects if any(d.lower() in f for f in features_lower)]
                        if not req_evidence:
                            missing_deps.append(req.name)

            suggestions.append(
                Suggestion(
                    pattern=pattern,
                    is_present=is_present,
                    evidence=evidence,
                    missing_dependencies=missing_deps,
                )
            )

        present = [s for s in suggestions if s.is_present]
        missing = [s for s in suggestions if not s.is_present]
        # Sort missing by priority (essential first)
        missing.sort(key=lambda s: s.pattern.priority)

        by_category: dict[str, dict] = {}
        for cat in sorted(set(p.category for p in self._patterns)):
            cat_suggestions = [s for s in suggestions if s.pattern.category == cat]
            present_count = len([s for s in cat_suggestions if s.is_present])
            by_category[cat] = {
                "total": len(cat_suggestions),
                "present": present_count,
                "coverage": round(present_count / len(cat_suggestions), 2) if cat_suggestions else 0,
            }

        logger.info(
            "companion",
            f"Design analysis: {len(present)} present, {len(missing)} missing patterns from {len(features)} features",
        )

        return {
            "features_provided": len(features),
            "features": sorted(features),
            "patterns_total": len(self._patterns),
            "patterns_present": len(present),
            "patterns_missing": len(missing),
            "present": [s.to_dict() for s in present],
            "missing_essential": [s.to_dict() for s in missing if s.pattern.priority == 1],
            "missing_important": [s.to_dict() for s in missing if s.pattern.priority == 2],
            "missing_nice": [s.to_dict() for s in missing if s.pattern.priority == 3],
            "by_category": by_category,
            "hint": (
                f"Your game has {len(present)} of {len(self._patterns)} genre patterns. "
                f"Focus on the {len([s for s in missing if s.pattern.priority == 1])} "
                f"essential patterns first."
            ),
        }

    def _get_pattern(self, pattern_id: str) -> Pattern | None:
        for p in self._patterns:
            if p.id == pattern_id:
                return p
        return None


def analyze_design(features: list[str]) -> dict:
    """Convenience wrapper: analyze features against the default pattern database."""
    companion = DesignCompanion()
    return companion.analyze(features)
