"""Deterministic quality / collapse gate — signals, never blocks.

The chat + CLI surveys converged: judge the scene graph deterministically, not
with another model. This inspects the planner output (entities, systems) and the
generated operations for cheap, countable collapse signals and returns
plain-language WARNINGS. It is ADVISORY — it never blocks, retries, or escalates.
The warnings ride along in PipelineResult so the caller, the artifact, and the
testbench can see them.
"""

from __future__ import annotations

from typing import Any

# Words implying the scene needs behavior/systems, not just geometry.
_BEHAVIOR_KEYWORDS = (
    "move",
    "walk",
    "run",
    "patrol",
    "attack",
    "collect",
    "spawn",
    "die",
    "health",
    "score",
    "input",
    "control",
    "signal",
    "timer",
    "animate",
    "interact",
    "npc",
    "enemy",
    "player",
    "open",
    "close",
    "trigger",
)


def assess_quality(
    operations: list[dict[str, Any]],
    arch_delta: dict[str, Any],
    prompt: str,
) -> list[str]:
    """Return collapse/quality WARNINGS. Empty list = healthy. Pure function."""
    warnings: list[str] = []
    entities = arch_delta.get("entities") or []
    systems = arch_delta.get("systems") or []
    prompt_lc = (prompt or "").lower()
    word_count = len((prompt or "").split())

    # 1. Variety collapse: several entities, all the same type.
    if len(entities) >= 3:
        types = {e.get("type", "") for e in entities if isinstance(e, dict)}
        if len(types) == 1:
            warnings.append(f"variety_collapse: {len(entities)} entities but all are type '{next(iter(types))}'")

    # 2. Operation monoculture: several ops, all the same op type.
    if len(operations) >= 3:
        op_types = {o.get("type", "") for o in operations if isinstance(o, dict)}
        if len(op_types) == 1:
            warnings.append(f"operation_monoculture: {len(operations)} ops but all are '{next(iter(op_types))}'")

    # 3. Thin generation: a non-trivial request produced almost nothing.
    if word_count > 5 and len(operations) < 2:
        warnings.append(f"thin_generation: only {len(operations)} op(s) for a {word_count}-word request")

    # 4. Missing systems: the request implies behavior but none was planned.
    if not systems and any(kw in prompt_lc for kw in _BEHAVIOR_KEYWORDS):
        warnings.append("missing_systems: request implies behavior but no systems were planned")

    return warnings
