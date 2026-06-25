"""World validation gate — sub-project (a), unit 2 (Wall W3).

Rejects spatially-impossible operations BEFORE they are applied (and long
before they reach Godot), returning structured ``Violation``s a caller —
eventually the LLM — uses to auto-correct: *"that courtyard intersects the
armory; shrink it or attach it to the north portal instead."*

Scope is the SPATIAL layer only; referential integrity (missing space /
entity / duplicate id) stays in ``world.operations.apply_op``:

* ``add_space``   — footprint well-formed; must NOT volumetrically overlap
                    any existing space (touching faces IS allowed — that is
                    exactly how adjacent spaces connect via a portal).
* ``add_portal``  — the two spaces must be face-ADJACENT, and the portal
                    ``position`` must lie on that shared boundary.
* ``add_entity``  — the entity ``pos`` must lie inside the space footprint.
* ``move_entity`` — the ``new_pos`` must lie inside the space footprint.

``validate_op`` is PURE and returns ``list[Violation]`` (empty = ok). It
skips a check when a referent is absent (``apply_op`` will raise the
referential error). ``apply_op_checked`` runs the gate then applies; on any
violation it raises ``WorldValidationError`` — a ``WorldOpError`` subclass,
so existing ``except WorldOpError`` handlers catch it uniformly — carrying
``.violations`` for structured auto-correction.

Replay does NOT re-validate: a saved op_log is valid by construction, and
re-validating could reject a historically-valid op if rules later tighten.
Only NEW ops are gated, via ``apply_op_checked``.

This is the W1/W3 geometry contract: spaces TILE without overlapping and
connect only on shared faces — "rooms immutable once placed, the world
grows via portals."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from world.model import World
from world.operations import WorldOpError, apply_op

# Faces within EPS are "touching"; an overlap must EXCEED EPS to count, so
# face-adjacent neighbours are never flagged as overlapping.
EPS = 1e-6
# How far a portal position may sit from the shared boundary (metres).
PORTAL_POS_TOL = 0.5

Aabb = tuple[tuple[float, float, float], tuple[float, float, float]]


@dataclass
class Violation:
    """One spatial problem with an op. ``message`` is phrased as a
    correctable hint; ``code`` is stable for programmatic handling."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class WorldValidationError(WorldOpError):
    """Raised by ``apply_op_checked`` when an op fails spatial validation.

    Subclasses ``WorldOpError`` so ``except WorldOpError`` catches both the
    referential and the spatial layer uniformly. Carries ``.violations``.
    """

    def __init__(self, violations: list[Violation]):
        self.violations = violations
        super().__init__(
            "; ".join(f"[{v.code}] {v.message}" for v in violations)
            or "validation failed"
        )


# ── AABB geometry ──────────────────────────────────────────────────────


def aabb(footprint: dict) -> Aabb | None:
    """``(lo, hi)`` corners from ``{origin:[x,y,z], size:[w,h,d]}``.

    Returns ``None`` when the footprint is malformed (missing/short
    origin or size, non-numeric, or non-positive size).
    """
    origin = footprint.get("origin")
    size = footprint.get("size")
    if (not isinstance(origin, (list, tuple)) or len(origin) != 3
            or not isinstance(size, (list, tuple)) or len(size) != 3):
        return None
    try:
        lo = (float(origin[0]), float(origin[1]), float(origin[2]))
        sz = (float(size[0]), float(size[1]), float(size[2]))
    except (TypeError, ValueError):
        return None
    if any(s <= 0.0 for s in sz):
        return None
    return lo, (lo[0] + sz[0], lo[1] + sz[1], lo[2] + sz[2])


def _axis_overlaps(a: Aabb, b: Aabb) -> tuple[float, float, float]:
    """Per-axis overlap length: >EPS overlapping, ~0 touching, <-EPS apart."""
    (alo, ahi), (blo, bhi) = a, b
    return tuple(min(ahi[i], bhi[i]) - max(alo[i], blo[i]) for i in range(3))


def overlaps(a: Aabb, b: Aabb, eps: float = EPS) -> bool:
    """True if a and b overlap by more than ``eps`` on ALL three axes
    (touching faces do not count as overlap)."""
    return all(o > eps for o in _axis_overlaps(a, b))


def adjacent(a: Aabb, b: Aabb, eps: float = EPS) -> bool:
    """True if a and b share a FACE: their intervals touch on exactly one
    axis (faces meet within ``eps``) and overlap on the other two, with no
    axis separated by a gap."""
    ov = _axis_overlaps(a, b)
    touching = [i for i in range(3) if abs(ov[i]) <= eps]
    separated = [i for i in range(3) if ov[i] < -eps]
    overlapping = [i for i in range(3) if ov[i] > eps]
    return not separated and len(touching) == 1 and len(overlapping) == 2


def _dist_to_aabb(p: tuple[float, float, float], box: Aabb) -> float:
    """Euclidean distance from point ``p`` to AABB ``box`` (0 if inside)."""
    lo, hi = box
    d2 = 0.0
    for i in range(3):
        excess = max(lo[i] - p[i], 0.0, p[i] - hi[i])
        d2 += excess * excess
    return d2 ** 0.5


def point_in_aabb(p, box: Aabb, eps: float = EPS) -> bool:
    """True if ``p`` lies within ``box`` (inclusive, with ``eps`` slack)."""
    lo, hi = box
    return all(lo[i] - eps <= p[i] <= hi[i] + eps for i in range(3))


# ── The gate ───────────────────────────────────────────────────────────


def validate_op(world: World, op: dict) -> list[Violation]:
    """Spatial validation for a single op. PURE; returns [] when valid or
    when the check does not apply (malformed op / absent referent — the
    referential layer in ``apply_op`` handles those)."""
    if not isinstance(op, dict):
        return []
    name = op.get("op")
    if name == "add_space":
        return _v_add_space(world, op)
    if name == "add_portal":
        return _v_add_portal(world, op)
    if name in ("add_entity", "move_entity"):
        return _v_entity_pos(world, op)
    return []


def _v_add_space(world: World, op: dict) -> list[Violation]:
    footprint = op.get("footprint")
    if not isinstance(footprint, dict):
        return [Violation("space.bad_footprint",
                          f"space {op.get('id')!r} has no footprint dict")]
    box = aabb(footprint)
    if box is None:
        return [Violation(
            "space.bad_footprint",
            f"space {op.get('id')!r} footprint is malformed "
            "(need origin[3] + positive size[3])",
            {"footprint": footprint})]
    violations: list[Violation] = []
    for sid, node in world.nodes.items():
        other = aabb(node.footprint)
        if other is not None and overlaps(box, other):
            violations.append(Violation(
                "space.overlap",
                f"new space {op.get('id')!r} overlaps existing space "
                f"{sid!r}; shrink it or attach it as an adjacent space",
                {"conflicts_with": sid}))
    return violations


def _v_add_portal(world: World, op: dict) -> list[Violation]:
    frm, to = op.get("from_space"), op.get("to_space")
    a_node, b_node = world.nodes.get(frm), world.nodes.get(to)
    if a_node is None or b_node is None:
        return []  # referential — apply_op raises
    a, b = aabb(a_node.footprint), aabb(b_node.footprint)
    if a is None or b is None:
        return []  # a malformed footprint was already an add_space violation
    if not adjacent(a, b):
        return [Violation(
            "portal.not_adjacent",
            f"spaces {frm!r} and {to!r} are not face-adjacent; a portal "
            "needs a shared boundary — move one space to touch the other",
            {"from": frm, "to": to})]
    pos = op.get("position")
    if isinstance(pos, (list, tuple)) and len(pos) == 3:
        p = tuple(float(c) for c in pos)
        if _dist_to_aabb(p, a) > PORTAL_POS_TOL or _dist_to_aabb(p, b) > PORTAL_POS_TOL:
            return [Violation(
                "portal.off_boundary",
                f"portal {op.get('id')!r} position {p} is not on the shared "
                f"boundary of {frm!r} and {to!r}",
                {"position": list(p)})]
    return []


def _v_entity_pos(world: World, op: dict) -> list[Violation]:
    space = world.nodes.get(op.get("space"))
    if space is None:
        return []  # referential — apply_op raises
    box = aabb(space.footprint)
    if box is None:
        return []
    if op["op"] == "add_entity":
        ent = op.get("entity") or {}
        pos, eid = ent.get("pos"), ent.get("id")
    else:
        pos, eid = op.get("new_pos"), op.get("entity_id")
    if not isinstance(pos, (list, tuple)) or len(pos) != 3:
        return []
    p = tuple(float(c) for c in pos)
    if not point_in_aabb(p, box):
        return [Violation(
            "entity.out_of_bounds",
            f"entity {eid!r} at {p} is outside space "
            f"{op.get('space')!r} bounds {box}",
            {"entity": eid, "pos": list(p)})]
    return []


def apply_op_checked(world: World, op: dict) -> World:
    """Validate ``op`` spatially, then apply it. Raises
    ``WorldValidationError`` (carrying ``.violations``) on any spatial
    violation; otherwise delegates to ``apply_op`` (which also enforces
    referential integrity). This is THE gated entry point for new ops."""
    violations = validate_op(world, op)
    if violations:
        raise WorldValidationError(violations)
    return apply_op(world, op)
