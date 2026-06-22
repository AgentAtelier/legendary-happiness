"""foundry.quest_validator — deterministic quest objective + chain validation (B9).

Pure functions, no LLM and no I/O.  These define what "winnable" *means* for
each quest objective type, so the quest generator (behaviour_gen) and the eval
oracle agree on it, and so a chained quest set can be checked for solvability
before it ships.

Objective types and their winnability conditions:
    fetch   — pick up ``target`` (must exist + be a carryable).
    deliver — pick up ``target`` (carryable) and bring it to ``recipient`` (an NPC).
    place   — pick up ``target`` (carryable) and set it on ``location`` (a furniture
              entity that has a top surface, per the category registry).
    talk    — speak with ``target`` (an NPC).

Carryable / surface facts come from ``category_registry`` (the single source of
truth), never re-hardcoded here.
"""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from category_registry import get_furniture_top_y, get_kind

OBJECTIVE_TYPES: Tuple[str, ...] = ("fetch", "deliver", "place", "talk")


# ── Manifest helpers ──────────────────────────────────────────────

def _category_by_id(manifest: List[dict]) -> Dict[str, str]:
    """Map manifest entity id → category."""
    return {e["id"]: e.get("category", "") for e in manifest if "id" in e}


def _is_carryable(category: str) -> bool:
    return get_kind(category) == "carryable"


def _is_surface(category: str) -> bool:
    """A category is a placement surface if it is furniture with a top that
    carryables sit on (``get_furniture_top_y`` returns 0.0 for non-surfaces)."""
    return get_kind(category) == "furniture" and get_furniture_top_y(category) > 0.0


# ── Objective winnability ─────────────────────────────────────────

def objective_winnable(
    objective: dict,
    *,
    manifest: List[dict],
    npc_ids: Set[str],
) -> Tuple[bool, str]:
    """Return ``(winnable, reason)`` for a single objective.

    ``reason`` is ``""`` when winnable, else a short human-readable cause.
    """
    if not isinstance(objective, dict):
        return False, "objective is not a dict"

    otype = objective.get("type", "")
    if otype not in OBJECTIVE_TYPES:
        return False, f"unknown objective type '{otype}'"

    cats = _category_by_id(manifest)
    target = objective.get("target", "")

    if otype == "talk":
        if target not in npc_ids:
            return False, f"talk target '{target}' is not an NPC"
        return True, ""

    # fetch / deliver / place all require a carryable target that exists.
    if target not in cats:
        return False, f"target '{target}' not in manifest"
    if not _is_carryable(cats[target]):
        return False, f"target '{target}' ({cats[target]}) is not carryable"

    if otype == "fetch":
        return True, ""

    if otype == "deliver":
        recipient = objective.get("recipient", "")
        if recipient not in npc_ids:
            return False, f"deliver recipient '{recipient}' is not an NPC"
        return True, ""

    if otype == "place":
        location = objective.get("location", "")
        if location not in cats:
            return False, f"place location '{location}' not in manifest"
        if not _is_surface(cats[location]):
            return False, f"place location '{location}' ({cats[location]}) has no surface"
        return True, ""

    # Unreachable (otype already validated), but keep total.
    return False, f"unhandled objective type '{otype}'"


# ── Chain solvability (DAG over quest_id / depends_on) ─────────────

def chain_solvable(quests: List[dict]) -> Tuple[bool, str]:
    """Return ``(solvable, reason)`` for a set of (possibly chained) quests.

    A chain is solvable when quest ids are unique, every ``depends_on``
    reference points at a real quest, and the dependency graph is acyclic
    (so there is an order in which every quest can be started).
    """
    ids: List[str] = [q.get("quest_id", "") for q in quests]

    # Unique ids
    seen: Set[str] = set()
    for qid in ids:
        if qid in seen:
            return False, f"duplicate quest_id '{qid}'"
        seen.add(qid)

    id_set = set(ids)

    # Build edges; validate references
    deps: Dict[str, List[str]] = {}
    for q in quests:
        qid = q.get("quest_id", "")
        obj = q.get("objective", {}) or {}
        prereqs = obj.get("depends_on", []) or []
        for p in prereqs:
            if p not in id_set:
                return False, f"quest '{qid}' depends on unknown quest '{p}'"
        deps[qid] = list(prereqs)

    # Kahn topological sort — if not all nodes drain, there's a cycle.
    indeg: Dict[str, int] = {qid: 0 for qid in id_set}
    for qid, prereqs in deps.items():
        indeg[qid] = len(prereqs)
    queue = [qid for qid, d in indeg.items() if d == 0]
    dependents: Dict[str, List[str]] = {qid: [] for qid in id_set}
    for qid, prereqs in deps.items():
        for p in prereqs:
            dependents[p].append(qid)

    resolved = 0
    while queue:
        node = queue.pop()
        resolved += 1
        for child in dependents[node]:
            indeg[child] -= 1
            if indeg[child] == 0:
                queue.append(child)

    if resolved != len(id_set):
        return False, "dependency cycle among quests"

    return True, ""
