"""BSP Multi-Room Building Partition Engine.

Deterministic engine that turns an LLM-generated split tree into room
rectangles, places each room via the existing SpatialCompiler, and
generates interior partition walls with doorways.

The LLM is a topologist — it never outputs a Vector3. It emits a
depth-bounded binary space partition (BSP) tree. This engine computes
every coordinate.

See SPATIAL-STAGE-3-5-PLAN.md §2 for the full design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from devforge.compilation.ir.plan import (
    CreateEntityStep,
    DevForgePlan,
    SetPropertyStep,
)
from devforge.infrastructure.logger import logger

# ── Constants ────────────────────────────────────────────────────

# Wall appearance
_WALL_MATERIAL: dict = {
    "__class__": "StandardMaterial3D",
    "albedo_color": {"r": 0.75, "g": 0.70, "b": 0.65, "a": 1.0},
}
_WALL_THICKNESS: float = 0.15
_WALL_HEIGHT: float = 2.8

# Doorway gap width in metres (centered on each wall)
_DOOR_GAP: float = 1.2

# Floor appearance
_FLOOR_MATERIAL: dict = {
    "__class__": "StandardMaterial3D",
    "albedo_color": {"r": 0.55, "g": 0.50, "b": 0.45, "a": 1.0},
}
_FLOOR_THICKNESS: float = 0.2

# Degenerate ratio guard (plan §2.7)
_MIN_RATIO: float = 0.1
_MAX_RATIO: float = 0.9

# Minimum wall-segment length before we skip it (metres)
_MIN_SEGMENT: float = 0.01


# ── Data types ────────────────────────────────────────────────────


@dataclass
class RoomRect:
    """A leaf room produced by the BSP partition."""

    origin: Tuple[float, float]  # (x, z) world offset of bottom-left corner
    size: Tuple[float, float]  # (width, depth) in metres
    pattern: str  # pattern id e.g. "rectangle_room"
    slot_fills: Dict[str, str] = field(default_factory=dict)
    room_name: str = ""


@dataclass
class _WallSpec:
    """Internal: a partition wall between two sub-regions.

    Generated at each SPLIT boundary during tree traversal.
    """

    axis: str  # "x" or "z" — which axis the wall runs along
    wall_x: float  # x coordinate of the split line
    wall_z: float  # z coordinate of the split line
    span_start: float  # start of the wall span
    span_end: float  # end of the wall span


# ── Engine ────────────────────────────────────────────────────────


class BSPPartitioner:
    """Deterministic BSP → room rects + walls compiled as DevForgePlan.

    Usage::

        compiler = SpatialCompiler(lexicon)
        bsp = BSPPartitioner(compiler)
        plan = bsp.compile_building(building_json, root_path="/root/Main")
        # plan.steps → CreateEntityStep + SetPropertyStep for floor,
        #               per-room furniture, and partition walls
    """

    def __init__(self, room_compiler: Any = None):
        """Create a BSP partitioner.

        Args:
            room_compiler: Existing SpatialCompiler instance for per-room
                           furniture/ARCS placement.  If None, rooms produce
                           empty plans — useful for unit-testing _partition.
        """
        self._room_compiler = room_compiler

    # ── public API ────────────────────────────────────────────────

    def compile_building(
        self,
        building_json: dict,
        root_path: str = "/root/Main",
    ) -> DevForgePlan:
        """Compile a building split-tree JSON into a DevForgePlan.

        Args:
            building_json: LLM output with ``footprint`` + ``tree``
                           (see SPATIAL-STAGE-3-5-PLAN.md §2.1).
            root_path: Godot node path to the scene root.

        Returns:
            DevForgePlan with CreateEntityStep + SetPropertyStep for the
            building floor, each room's furniture (via SpatialCompiler),
            and partition walls with centred doorways.
        """
        tree = building_json.get("tree", {})
        footprint = building_json.get("footprint", {})
        fp_width = float(footprint.get("width", 12.0))
        fp_depth = float(footprint.get("depth", 8.0))
        building_name = building_json.get("building", "Building")

        # 1. Partition the tree into leaf room rects + wall specs
        walls: List[_WallSpec] = []
        leaves = self._partition(
            tree,
            origin=(0.0, 0.0),
            size=(fp_width, fp_depth),
            walls=walls,
        )

        if not leaves:
            logger.warn("bsp", "BSP tree produced 0 leaf rooms")
            return DevForgePlan(
                goal=f"BSP building: {building_name} (0 rooms)",
                steps=[],
            )

        steps: List = []

        # 2. Building floor slab (one PlaneMesh spanning the footprint)
        steps.extend(
            self._building_floor(
                origin=(0.0, 0.0),
                size=(fp_width, fp_depth),
                root_path=root_path,
            )
        )

        # 3. Per-room compilation via the existing SpatialCompiler.
        #    Each room gets a Node3D container so furniture names don't
        #    collide when two rooms share the same slot (e.g. both have
        #    a "center_table" → "living/table_center_table" and
        #    "kitchen/table_center_table" instead of one overwriting
        #    the other).
        for leaf in leaves:
            room_path = f"{root_path}/{leaf.room_name}"

            # Room container node
            steps.append(
                CreateEntityStep(
                    name=leaf.room_name,
                    node_type="Node3D",
                    parent=root_path,
                )
            )

            room_json = {
                "pattern": leaf.pattern,
                "dimensions": {
                    "width": leaf.size[0],
                    "height": 3.0,
                    "depth": leaf.size[1],
                },
                "slot_fills": leaf.slot_fills,
                "arcs_overrides": [],
            }
            if self._room_compiler is not None:
                try:
                    sub_plan = self._room_compiler.compile_layout(
                        room_json,
                        root_path=room_path,
                        origin=leaf.origin,
                        shell=False,  # BSP lays one building-wide floor
                    )
                    steps.extend(sub_plan.steps)
                except Exception as exc:
                    logger.warn(
                        "bsp",
                        f"Room '{leaf.room_name}' compilation failed: {exc}",
                    )
            # If no compiler, the room is an empty leaf — unit-test mode.

        # 4. Partition walls with centred doorways
        steps.extend(self._build_partition_walls(walls, root_path))

        logger.info(
            "bsp",
            f"Compiled {building_name}: {len(leaves)} rooms, {len(steps)} steps, {len(walls)} wall boundaries",
        )

        return DevForgePlan(
            goal=f"BSP building: {building_name} ({len(leaves)} rooms)",
            steps=steps,
        )

    # ── partition tree → rects ────────────────────────────────────

    def _partition(
        self,
        node: dict,
        origin: Tuple[float, float],
        size: Tuple[float, float],
        walls: List[_WallSpec] | None = None,
    ) -> List[RoomRect]:
        """Recursively partition a BSP tree node into leaf RoomRects.

        SPLIT nodes divide the region along an axis at a ratio.
        LEAF nodes (with a ``room`` field) return a single RoomRect.

        Args:
            node: The BSP tree node (SPLIT or LEAF).
            origin: (x, z) bottom-left corner of the current region.
            size: (width, depth) of the current region in metres.
            walls: Optional list to collect wall specs from SPLIT boundaries.

        Returns:
            List of RoomRect leaves in this subtree.
        """
        if walls is None:
            walls = []

        # Empty node guard
        if not isinstance(node, dict) or not node:
            return []

        width, depth = size
        ox, oz = origin

        # ── LEAF node — has 'room' field ──
        if "room" in node:
            room_name = node.get("room", "room")
            pattern = node.get("pattern", "rectangle_room")
            slot_fills = node.get("slot_fills", {})
            return [
                RoomRect(
                    origin=(ox, oz),
                    size=(width, depth),
                    pattern=pattern,
                    slot_fills=slot_fills,
                    room_name=room_name,
                )
            ]

        # ── SPLIT node — has 'axis', 'ratio', 'left', 'right' ──
        if "axis" not in node:
            # Malformed node: neither LEAF nor SPLIT.  Treat as empty
            # so it doesn't produce a stray wall spec.
            logger.warn("bsp", f"BSP node has neither 'room' nor 'axis': {node}")
            return []

        axis = node.get("axis", "x")
        raw_ratio = float(node.get("ratio", 0.5))
        # Clamp degenerate ratios (plan §2.7)
        ratio = max(_MIN_RATIO, min(_MAX_RATIO, raw_ratio))

        if ratio != raw_ratio:
            logger.info(
                "bsp",
                f"Clamped degenerate ratio {raw_ratio} → {ratio}",
            )

        if axis == "x":
            # Split along X axis — left gets ratio×width
            left_w = width * ratio
            right_w = width - left_w
            left_origin = (ox, oz)
            right_origin = (ox + left_w, oz)

            left_size = (left_w, depth)
            right_size = (right_w, depth)

            # Wall at the split line, spanning the full depth
            walls.append(
                _WallSpec(
                    axis="z",  # wall runs along Z (vertical in top-down)
                    wall_x=ox + left_w,
                    wall_z=oz,
                    span_start=oz,
                    span_end=oz + depth,
                )
            )
        else:
            # Split along Z axis — left gets ratio×depth
            left_d = depth * ratio
            right_d = depth - left_d
            left_origin = (ox, oz)
            right_origin = (ox, oz + left_d)

            left_size = (width, left_d)
            right_size = (width, right_d)

            # Wall at the split line, spanning the full width
            walls.append(
                _WallSpec(
                    axis="x",  # wall runs along X
                    wall_x=ox,
                    wall_z=oz + left_d,
                    span_start=ox,
                    span_end=ox + width,
                )
            )

        left_node = node.get("left", {})
        right_node = node.get("right", {})

        leaves: List[RoomRect] = []
        leaves.extend(self._partition(left_node, left_origin, left_size, walls))
        leaves.extend(self._partition(right_node, right_origin, right_size, walls))
        return leaves

    # ── floor ─────────────────────────────────────────────────────

    def _building_floor(
        self,
        origin: Tuple[float, float],
        size: Tuple[float, float],
        root_path: str,
    ) -> List:
        """Create one floor slab for the entire building footprint.

        A single PlaneMesh scaled to the footprint, placed slightly below
        y=0 so room furniture sits on top without z-fighting.
        """
        width, depth = size
        ox, oz = origin
        steps: List = []

        floor_name = "BuildingFloor"
        floor_path = f"{root_path}/{floor_name}"

        steps.append(
            CreateEntityStep(
                name=floor_name,
                node_type="MeshInstance3D",
                parent=root_path,
            )
        )

        # Position at centre of footprint, y just below 0
        steps.append(
            SetPropertyStep(
                node=floor_path,
                property="position",
                value={
                    "x": ox + width / 2,
                    "y": -_FLOOR_THICKNESS / 2,
                    "z": oz + depth / 2,
                },
            )
        )

        # PlaneMesh with the footprint dimensions
        steps.append(
            SetPropertyStep(
                node=floor_path,
                property="mesh",
                value={
                    "__class__": "PlaneMesh",
                    "size": {"x": width, "y": depth},
                },
            )
        )

        steps.append(
            SetPropertyStep(
                node=floor_path,
                property="material_override",
                value=_FLOOR_MATERIAL,
            )
        )

        return steps

    # ── partition walls ───────────────────────────────────────────

    def _build_partition_walls(
        self,
        walls: List[_WallSpec],
        root_path: str,
    ) -> List:
        """Generate thin wall boxes with centred doorway gaps.

        Each internal SPLIT boundary becomes a wall.  The wall is split
        into two segments (above and below the doorway gap) so a centred
        opening (~1.2 m) remains between rooms.
        """
        steps: List = []
        wall_count = 0

        for w in walls:
            # Doorway gap centred along the wall span
            span_centre = (w.span_start + w.span_end) / 2
            gap_half = _DOOR_GAP / 2

            # Two wall segments: below the door, above the door
            segments = [
                (w.span_start, span_centre - gap_half),  # segment 1
                (span_centre + gap_half, w.span_end),  # segment 2
            ]

            for seg_start, seg_end in segments:
                seg_len = seg_end - seg_start
                if seg_len <= _MIN_SEGMENT:
                    continue  # door gap leaves no room for this segment

                wall_count += 1
                wall_name = f"Wall_{wall_count}"
                wall_path = f"{root_path}/{wall_name}"

                steps.append(
                    CreateEntityStep(
                        name=wall_name,
                        node_type="MeshInstance3D",
                        parent=root_path,
                    )
                )

                seg_centre = (seg_start + seg_end) / 2

                if w.axis == "x":
                    # Wall runs along X (horizontal in top-down view)
                    steps.append(
                        SetPropertyStep(
                            node=wall_path,
                            property="position",
                            value={
                                "x": seg_centre,
                                "y": _WALL_HEIGHT / 2,
                                "z": w.wall_z,
                            },
                        )
                    )
                    steps.append(
                        SetPropertyStep(
                            node=wall_path,
                            property="mesh",
                            value={
                                "__class__": "BoxMesh",
                                "size": {
                                    "x": seg_len,
                                    "y": _WALL_HEIGHT,
                                    "z": _WALL_THICKNESS,
                                },
                            },
                        )
                    )
                else:
                    # Wall runs along Z
                    steps.append(
                        SetPropertyStep(
                            node=wall_path,
                            property="position",
                            value={
                                "x": w.wall_x,
                                "y": _WALL_HEIGHT / 2,
                                "z": seg_centre,
                            },
                        )
                    )
                    steps.append(
                        SetPropertyStep(
                            node=wall_path,
                            property="mesh",
                            value={
                                "__class__": "BoxMesh",
                                "size": {
                                    "x": _WALL_THICKNESS,
                                    "y": _WALL_HEIGHT,
                                    "z": seg_len,
                                },
                            },
                        )
                    )

                steps.append(
                    SetPropertyStep(
                        node=wall_path,
                        property="material_override",
                        value=_WALL_MATERIAL,
                    )
                )

        return steps
