"""World model dataclasses and the ``propose`` entry point.

All state is immutable-friendly — ``propose`` works on a STAGED copy
and only commits on accept.  Geometry is referenced by ``asset_hash``,
NEVER stored in the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from decisions import DecisionPoint

# ── Data classes ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Placement:
    """One asset placed in the world.  Geometry is referenced by
    ``asset_hash`` — never stored in the model."""

    id: str
    asset_hash: str                     # opaque hash; geometry is derived
    attrs: dict[str, Any] = field(default_factory=dict)
    # Typical attrs: material, generator, zone


@dataclass
class World:
    """The world state: an ordered list of Placements.

    This is the canonical state.  The event log is a separate concern
    (see ``foundry.world.log``)."""

    placements: list[Placement] = field(default_factory=list)


@dataclass(frozen=True)
class Intent:
    """A WHOLE small change proposal — never a diff.

    ``action`` is ``"add"`` or ``"replace"``.
    ``placement`` is the full Placement to add or the replacement for
    an existing placement (matched by ``placement.id``)."""

    action: str          # "add" | "replace"
    placement: Placement


@dataclass
class ProposeResult:
    """The outcome of ``propose``.

    ``accepted`` → the intent was applied (event appended).
    ``world`` → the new World (STAGED copy when rejected, committed when accepted).
    ``decisions`` → Decision Points emitted by invariants."""

    accepted: bool
    world: World
    decisions: list[DecisionPoint] = field(default_factory=list)


# ── Propose ───────────────────────────────────────────────────────────


def propose(
    world: World,
    intent: Intent,
    *,
    material_palette: dict[str, Any] | None = None,
    max_per_zone: int = 100,
) -> ProposeResult:
    """Validate *intent* against *world* and either accept (append event,
    return new World) or reject (return STAGED copy with Decision Points).

    Args:
        world: Current world state.
        intent: A whole change proposal (``add`` or ``replace``).
        material_palette: Dict of known materials for referential integrity.
            If None, defaults to ``materials.MATERIAL_PALETTE``.
        max_per_zone: Maximum placements per zone (budget invariant).

    Returns:
        ``ProposeResult`` with the outcome.
    """
    from foundry.world.invariants import check_invariants

    # Work on a staged copy.
    staged = World(placements=list(world.placements))

    # Apply the intent to the staged copy.
    if intent.action == "add":
        staged.placements.append(intent.placement)
    elif intent.action == "replace":
        replaced = False
        for i, p in enumerate(staged.placements):
            if p.id == intent.placement.id:
                staged.placements[i] = intent.placement
                replaced = True
                break
        if not replaced:
            # Replacement target not found → add instead (idempotent).
            staged.placements.append(intent.placement)
    else:
        return ProposeResult(
            accepted=False,
            world=world,
            decisions=[
                DecisionPoint(
                    code="world.unknown_action",
                    stage="world-model",
                    severity="error",
                    technical=f"unknown intent action: {intent.action!r}",
                    plain=f"Unknown action: {intent.action}.",
                    context={"action": intent.action},
                    choices=(),
                )
            ],
        )

    # Run tiered invariants.
    decisions = check_invariants(
        staged, material_palette=material_palette, max_per_zone=max_per_zone
    )

    # Separate HARD decisions (blocking) from SOFT (warn-only).
    hard_decisions = [d for d in decisions if d.severity == "error"]
    soft_decisions = [d for d in decisions if d.severity != "error"]

    if hard_decisions:
        return ProposeResult(
            accepted=False,
            world=world,   # return ORIGINAL world on reject
            decisions=hard_decisions,
        )

    # Accepted — return the staged world.
    return ProposeResult(
        accepted=True,
        world=staged,
        decisions=soft_decisions,
    )
