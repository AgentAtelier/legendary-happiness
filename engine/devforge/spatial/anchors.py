"""Anchor-Resolver — ARCS (Anchor-Relative Coordinate System) engine.

The LLM never outputs a Vector3. It outputs anchor chains: "place the stove
at the cook_counter slot, offset by δ". This engine resolves those chains
into absolute Godot-space positions.

Anchor types:
  named   — a fixed reference point defined in the pattern YAML
            (e.g. "center", "north_wall", "nw_corner")
  chained — relative to a previously-placed object
            (e.g. {chain: ["center_table", "north", "1.2"]})

Named anchors may contain parameter expressions ($width/2) which are
evaluated against the resolved room dimensions.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

from devforge.infrastructure.logger import logger


# A 3D position in Godot space (x=right, y=up, z=forward)
Vec3 = Dict[str, float]


def _vec(x: float, y: float, z: float) -> Vec3:
    return {"x": x, "y": y, "z": z}


class AnchorResolver:
    """Resolves named anchors and chained ARCS into absolute Vector3 positions.

    Usage::

        resolver = AnchorResolver(pattern_anchors, dimensions)
        pos = resolver.resolve("center")           # → {x: 2.5, y: 0, z: 2.5}
        pos = resolver.resolve_chain(["center_table", "north", 1.2], bounding_boxes)
    """

    # Direction vectors for chained anchor resolution.
    _DIRECTIONS: Dict[str, Vec3] = {
        "north": _vec(0, 0, -1),
        "south": _vec(0, 0, 1),
        "east": _vec(1, 0, 0),
        "west": _vec(-1, 0, 0),
        "up": _vec(0, 1, 0),
        "down": _vec(0, -1, 0),
    }

    # Expression pattern: $param or $param op number
    _EXPR_RE = re.compile(r"\$(\w+)\s*(?:([+\-*/])\s*([\d.]+))?")

    def __init__(
        self,
        anchors: Dict[str, dict],
        dimensions: Dict[str, float],
        origin: Tuple[float, float] = (0.0, 0.0),
    ):
        self._anchors = anchors
        self._dims = dimensions
        # World-space (x, z) offset added to every NAMED anchor. Chains build
        # off already-offset placed objects, so the origin propagates for free.
        # Default (0,0) → single-room callers are unchanged. BSP passes a leaf's
        # origin so rooms tile without overlap.
        self._origin = (float(origin[0]), float(origin[1]))
        self._resolved: Dict[str, Vec3] = {}

    def resolve(self, anchor_id: str) -> Vec3:
        """Resolve a NAMED anchor (must exist in the pattern's anchors dict)."""
        if anchor_id in self._resolved:
            return self._resolved[anchor_id]

        entry = self._anchors.get(anchor_id)
        if entry is None:
            raise ValueError(
                f"Anchor '{anchor_id}' not found in pattern anchors. Available: {sorted(self._anchors.keys())}"
            )

        raw = entry.get("position", [0, 0, 0])
        pos = _vec(
            self._eval(raw[0]) + self._origin[0],
            self._eval(raw[1]),
            self._eval(raw[2]) + self._origin[1],
        )
        self._resolved[anchor_id] = pos
        return pos

    def resolve_chain(
        self,
        chain: List[Any],
        bounding_boxes: Dict[str, dict] | None = None,
    ) -> Vec3:
        """Resolve a CHAINED anchor relative to a previously-placed object.

        ``chain`` is [object_name, direction, distance] where object_name
        was already placed and its bounding box is known.

        If bounding_boxes is provided and contains the object, the offset
        starts from the object's edge (including its half-extent in that
        direction) rather than its center. The distance is added as a gap
        from the object's surface.
        """
        if len(chain) < 3:
            raise ValueError(f"Chain requires [object, direction, distance], got {chain}")

        obj_name = str(chain[0])
        direction = str(chain[1]).lower()
        distance = float(chain[2])

        # Find the object's center position
        origin = self._resolved.get(obj_name)
        if origin is None:
            # Try as a named anchor
            try:
                origin = self.resolve(obj_name)
            except ValueError:
                raise ValueError(
                    f"Chain target '{obj_name}' is not a placed object or "
                    f"named anchor. Placed: {sorted(self._resolved.keys())}"
                )

        dir_vec = self._DIRECTIONS.get(direction)
        if dir_vec is None:
            raise ValueError(f"Unknown direction '{direction}'. Valid: {sorted(self._DIRECTIONS.keys())}")

        result = {
            "x": origin["x"],
            "y": origin["y"],
            "z": origin["z"],
        }

        # Move from object center to its edge in the given direction,
        # then add the gap distance
        half_extent = 0.0
        if bounding_boxes and obj_name in bounding_boxes:
            bb = bounding_boxes[obj_name]
            half_w = bb.get("half_width", 0.5)
            half_d = bb.get("half_depth", 0.5)
            if direction in ("north", "south"):
                half_extent = half_d
            elif direction in ("east", "west"):
                half_extent = half_w

        total_offset = half_extent + distance
        result["x"] += dir_vec["x"] * total_offset
        result["y"] += dir_vec["y"] * total_offset
        result["z"] += dir_vec["z"] * total_offset

        return result

    def register_placed(self, name: str, position: Vec3, footprint: dict | None = None) -> None:
        """Register a placed object so it can be used as a chain target."""
        self._resolved[name] = position

    # ── expression evaluation ───────────────────────────────

    def _eval(self, expr: Any) -> float:
        """Evaluate a parameter expression like '$width/2' or plain number."""
        if isinstance(expr, (int, float)):
            return float(expr)
        if isinstance(expr, str):
            m = self._EXPR_RE.match(expr.strip())
            if m:
                param = m.group(1)
                op = m.group(2)
                rhs = float(m.group(3)) if m.group(3) else 0.0
                val = self._dims.get(param, 0.0)
                if op == "+":
                    return val + rhs
                elif op == "-":
                    return val - rhs
                elif op == "*":
                    return val * rhs
                elif op == "/":
                    return val / rhs if rhs != 0 else val
                return val
            try:
                return float(expr)
            except ValueError:
                return 0.0
        return float(expr)
