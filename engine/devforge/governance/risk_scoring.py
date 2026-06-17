"""
DevForge Risk Scoring Calculator
=================================
Computes risk score by formula only — no model judgment.
Score determines report verbosity and human review requirements.

Ported from WorldForge. Source: Constitution Section VI (Risk Scoring)

Usage:
    from devforge.governance.risk_scoring import compute_risk

    score, tier = compute_risk(
        subsystems=["ecology", "entity_registry"],
        depth="modifies_interface",
        files_modified=5,
        crosses_sim_render=False
    )
"""

from dataclasses import dataclass
from enum import Enum
from typing import List

# --------------------------------------------------------------------------
# Subsystem weights (Constitution Section VI)
# --------------------------------------------------------------------------
SUBSYSTEM_WEIGHTS: dict[str, int] = {
    "player_survival": 1,
    "crafting": 1,
    "recipes": 1,
    "npc_behaviour": 2,
    "ecology": 3,  # EcoRegion simulation
    "entity_registry": 4,
    "tick_scheduler": 5,  # halt → Architectural Change Mode
    "sim_render_interface": 5,
    "persistence": 5,
}


class Depth(Enum):
    """Depth of modification — determines multiplier."""

    READ_ONLY = "read_only"  # ×1.0
    NEW_BEHAVIOUR = "new_behaviour"  # ×1.5
    MODIFIES_INTERFACE = "modifies_interface"  # ×2.5
    RESTRUCTURES = "restructures"  # ×4.0


DEPTH_MULTIPLIERS: dict[Depth, float] = {
    Depth.READ_ONLY: 1.0,
    Depth.NEW_BEHAVIOUR: 1.5,
    Depth.MODIFIES_INTERFACE: 2.5,
    Depth.RESTRUCTURES: 4.0,
}


class RiskTier(Enum):
    """Risk tier — derived from score."""

    LOW = "low"  # R ≤ 3  — brief report
    MEDIUM = "medium"  # R 4–7  — structured report
    HIGH = "high"  # R 8–11 — full architectural delta report
    CRITICAL = "critical"  # R ≥ 12 — block until human reviews plan


@dataclass
class RiskResult:
    """Result of a risk computation."""

    base_weight: int
    depth_multiplier: float
    file_bonus: int
    cross_boundary_bonus: int
    raw_score: float
    final_score: int
    tier: RiskTier
    auto_xl: bool
    architect_review_required: bool
    halt_architectural_change: bool


def _file_bonus(file_count: int) -> tuple[int, bool]:
    """Returns (bonus, auto_xl_flag)."""
    if file_count < 3:
        return 0, False
    elif file_count <= 8:
        return 1, False
    elif file_count <= 15:
        return 2, False
    else:
        return 3, True  # auto XL


def _cross_boundary_bonus(crosses: bool) -> tuple[int, bool]:
    """Returns (bonus, architect_review_required)."""
    if crosses:
        return 3, True
    return 0, False


def compute_risk(
    subsystems: List[str],
    depth: str,
    files_modified: int,
    crosses_sim_render: bool = False,
) -> RiskResult:
    """
    Compute risk score for a change.

    Args:
        subsystems: List of subsystem names touched (uses highest weight).
        depth: One of 'read_only', 'new_behaviour', 'modifies_interface', 'restructures'.
        files_modified: Total number of files in the staged diff.
        crosses_sim_render: True if diff touches both sim/ and render/ paths.

    Returns:
        RiskResult with score, tier, and flags.

    Raises:
        ValueError: If subsystem name or depth is unrecognized.
    """
    # Validate inputs
    depth_enum = Depth(depth)

    unknown = [s for s in subsystems if s not in SUBSYSTEM_WEIGHTS]
    if unknown:
        raise ValueError(f"Unknown subsystems: {unknown}. Valid: {list(SUBSYSTEM_WEIGHTS.keys())}")

    # Base weight = highest subsystem weight touched
    base_weight = max(SUBSYSTEM_WEIGHTS[s] for s in subsystems) if subsystems else 0

    # Check for halt condition (weight 5 subsystems)
    halt = base_weight >= 5

    # Multiplier
    multiplier = DEPTH_MULTIPLIERS[depth_enum]

    # Bonuses
    f_bonus, auto_xl = _file_bonus(files_modified)
    cb_bonus, architect_review = _cross_boundary_bonus(crosses_sim_render)

    # Final score
    raw_score = (base_weight * multiplier) + f_bonus + cb_bonus
    final_score = int(raw_score)  # Floor to integer

    # Tier
    if final_score <= 3:
        tier = RiskTier.LOW
    elif final_score <= 7:
        tier = RiskTier.MEDIUM
    elif final_score <= 11:
        tier = RiskTier.HIGH
    else:
        tier = RiskTier.CRITICAL

    return RiskResult(
        base_weight=base_weight,
        depth_multiplier=multiplier,
        file_bonus=f_bonus,
        cross_boundary_bonus=cb_bonus,
        raw_score=raw_score,
        final_score=final_score,
        tier=tier,
        auto_xl=auto_xl,
        architect_review_required=architect_review,
        halt_architectural_change=halt,
    )


# --------------------------------------------------------------------------
# CLI usage for quick checks
# --------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="DevForge Risk Scoring Calculator")
    parser.add_argument(
        "--subsystems", nargs="+", required=True, help=f"Subsystems touched. Options: {list(SUBSYSTEM_WEIGHTS.keys())}"
    )
    parser.add_argument("--depth", required=True, choices=[d.value for d in Depth], help="Depth of modification.")
    parser.add_argument("--files", type=int, required=True, help="Number of files modified.")
    parser.add_argument("--crosses-boundary", action="store_true", help="Set if diff touches both sim/ and render/.")

    args = parser.parse_args()

    result = compute_risk(
        subsystems=args.subsystems,
        depth=args.depth,
        files_modified=args.files,
        crosses_sim_render=args.crosses_boundary,
    )

    output = {
        "base_weight": result.base_weight,
        "depth_multiplier": result.depth_multiplier,
        "file_bonus": result.file_bonus,
        "cross_boundary_bonus": result.cross_boundary_bonus,
        "raw_score": result.raw_score,
        "final_score": result.final_score,
        "tier": result.tier.value,
        "auto_xl": result.auto_xl,
        "architect_review_required": result.architect_review_required,
        "halt_architectural_change": result.halt_architectural_change,
    }

    print(json.dumps(output, indent=2))
