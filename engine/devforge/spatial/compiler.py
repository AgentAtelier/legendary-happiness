"""Spatial Compiler — layout JSON → DevForgePlan → batch_execute ops.

The heart of the spatial pipeline. Takes the LLM's semantic intent
(pattern choice, slot→asset assignments, ARCS overrides) and resolves
it into absolute transforms via the pattern YAML + AnchorResolver.

Output is a standard DevForgePlan (CreateEntityStep + SetPropertyStep)
that flows through the existing OperationGenerator → Validator → Executor
pipeline unchanged.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from devforge.compilation.ir.plan import (
    DevForgePlan,
    CreateEntityStep,
    SetPropertyStep,
)
from devforge.infrastructure.logger import logger
from devforge.spatial.lexicon import AssetLexicon, SlotViolation
from devforge.spatial.anchors import AnchorResolver

# Reusable mesh resources for room shell (floor/ceiling planes).
_PLANE_MESH = {"__class__": "PlaneMesh", "size": {"x": 10, "y": 10}}
_DEFAULT_MATERIAL = {
    "__class__": "StandardMaterial3D",
    "albedo_color": {"r": 1.0, "g": 0.0, "b": 0.0, "a": 1.0},
}


def _material(r: float, g: float, b: float) -> dict:
    return {
        "__class__": "StandardMaterial3D",
        "albedo_color": {"r": r, "g": g, "b": b, "a": 1.0},
    }


class SpatialCompiler:
    """Compiles layout JSON into a DevForgePlan with standard ops."""

    DEFAULT_PATTERNS_DIR = Path(__file__).resolve().parent / "patterns"

    def __init__(
        self,
        lexicon: AssetLexicon | None = None,
        patterns_dir: str | Path | None = None,
    ):
        self._lexicon = lexicon or AssetLexicon()
        self._patterns_dir = Path(patterns_dir) if patterns_dir else self.DEFAULT_PATTERNS_DIR
        self._patterns: Dict[str, dict] = {}
        self._load_patterns()

    # ── public API ──────────────────────────────────────────

    def compile_layout(
        self,
        layout_json: dict,
        root_path: str = "/root/Main",
        origin: Tuple[float, float] = (0.0, 0.0),
        shell: bool = True,
    ) -> DevForgePlan:
        """Compile a layout JSON into a DevForgePlan.

        Args:
            layout_json: The LLM's output — {pattern, dimensions, slot_fills,
                         arcs_overrides}.
            root_path: The Godot node path to the scene root (e.g. "/root/Main").
                       Resolved at runtime from the live scene to avoid the
                       Main→Main2 corruption (P1: Godot auto-suffixes duplicate
                       root names).
            origin: World-space (x, z) offset for the whole room. Default (0,0).
                    BSP passes a leaf's origin so a building's rooms tile without
                    overlap (Stage 3 §2.3). Every placed asset + the shell is
                    offset by this.
            shell: Whether to build the room's own floor/ceiling. Default True.
                   BSP sets shell=False and lays one building-wide floor instead,
                   so per-room slabs don't z-fight.

        Returns:
            DevForgePlan with CreateEntityStep + SetPropertyStep ready for
            the existing OperationGenerator → Validator → Executor pipeline.
        """
        pattern_id = layout_json.get("pattern", "rectangle_room")
        pattern = self._require_pattern(pattern_id)

        dims = self._resolve_dimensions(layout_json.get("dimensions", {}), pattern)
        steps: List = []
        bounding_boxes: Dict[str, dict] = {}
        placed: Set[str] = set()

        # 1. Build the room shell (floor, ceiling — walls implicit)
        if shell:
            steps.extend(self._build_shell(pattern, dims, root_path, origin))

        # 2. Create the resolver with resolved dimensions + world origin
        resolver = AnchorResolver(pattern.get("anchors", {}), dims, origin)

        # 3. Fill slots
        slot_fills = layout_json.get("slot_fills", {})
        slot_defs = pattern.get("slots", {})

        for slot_id, asset_id in slot_fills.items():
            if not slot_id or not asset_id:
                continue
            if slot_id not in slot_defs:
                logger.warn("spatial.compiler", f"Slot '{slot_id}' not defined in pattern '{pattern_id}'; skipped")
                continue

            slot = slot_defs[slot_id]
            try:
                slot_steps, placed_name, placed_pos, bb = self._fill_slot(
                    slot_id,
                    slot,
                    asset_id,
                    resolver,
                    root_path,
                    bounding_boxes,
                    placed,
                    dims,
                )
                steps.extend(slot_steps)
                if placed_name:
                    resolver.register_placed(placed_name, placed_pos, bb)
                    bounding_boxes[placed_name] = bb
                    placed.add(placed_name)
            except (SlotViolation, ValueError) as sv:
                logger.warn("spatial.compiler", f"Slot '{slot_id}' failed: {sv}")

        # 3b. Apply slot_colours (Intent Descriptor style/mood palettes) —
        #     after all slots are placed so we know the final node paths.
        slot_colours = layout_json.get("slot_colours", {})
        for slot_id, colour in slot_colours.items():
            if not isinstance(colour, list) or len(colour) < 3:
                continue
            asset_id = slot_fills.get(slot_id, "")
            if not asset_id:
                continue
            node_name = f"{asset_id}_{slot_id}"
            if node_name not in placed:
                continue
            node_path = f"{root_path}/{node_name}"
            steps.append(
                SetPropertyStep(
                    node=node_path,
                    property="material_override",
                    value=_material(colour[0], colour[1], colour[2]),
                )
            )

        # 4. Process ARCS overrides
        arcs_overrides = layout_json.get("arcs_overrides", [])
        for override in arcs_overrides:
            try:
                arc_steps, arc_name, arc_pos, arc_bb = self._process_arcs(
                    override,
                    resolver,
                    root_path,
                    bounding_boxes,
                    dims,
                )
                steps.extend(arc_steps)
                if arc_name:
                    resolver.register_placed(arc_name, arc_pos, arc_bb)
                    bounding_boxes[arc_name] = arc_bb
                    placed.add(arc_name)
            except (ValueError, SlotViolation) as exc:
                logger.warn("spatial.compiler", f"ARCS override failed: {exc}")

        # 5. Collision-nudge safety pass (already done per-object during
        #    slot fill and ARCS processing — _fill_slot and _process_arcs
        #    each call _overlaps + _nudge inline)

        plan = DevForgePlan(goal=f"Spatial layout: {pattern_id}", steps=steps)
        errors = plan.validate()
        if errors:
            logger.warn("spatial.compiler", f"Plan has {len(errors)} validation warnings", errors=errors)

        logger.info("spatial.compiler", f"Compiled {pattern_id} → {len(steps)} steps, {len(placed)} placed assets")
        return plan

    @property
    def pattern_ids(self) -> List[str]:
        return sorted(self._patterns.keys())

    def pattern_summary_for_prompt(self) -> str:
        """One-paragraph-per-pattern summary for the LLM prompt."""
        lines = []
        for pid, pat in sorted(self._patterns.items()):
            name = pat.get("name", pid)
            desc = pat.get("description", "")
            slots = sorted(pat.get("slots", {}).keys())
            lines.append(f"  {pid}: {name} — {desc}. Slots: {', '.join(slots[:8])}" + ("..." if len(slots) > 8 else ""))
        return "\n".join(lines)

    # ── internals ───────────────────────────────────────────

    def _load_patterns(self) -> None:
        if not self._patterns_dir.exists():
            logger.warn("spatial.compiler", f"Patterns directory not found: {self._patterns_dir}")
            return
        for yf in sorted(self._patterns_dir.glob("*.yaml")):
            try:
                pat = yaml.safe_load(yf.read_text(encoding="utf-8"))
                if isinstance(pat, dict) and "name" in pat:
                    self._patterns[yf.stem] = pat
                    logger.info("spatial.compiler", f"Loaded pattern: {yf.stem} ({pat['name']})")
            except Exception as exc:
                logger.warn("spatial.compiler", f"Failed to load {yf}: {exc}")

    def _require_pattern(self, pattern_id: str) -> dict:
        pat = self._patterns.get(pattern_id)
        if pat is None:
            ids = sorted(self._patterns.keys())
            raise ValueError(f"Pattern '{pattern_id}' not found. Available: {ids}")
        return pat

    @staticmethod
    def _resolve_dimensions(user_dims: dict, pattern: dict) -> Dict[str, float]:
        """Merge user dimensions with pattern defaults."""
        resolved: Dict[str, float] = {}
        for param, spec in pattern.get("parameters", {}).items():
            val = user_dims.get(param)
            if val is not None:
                resolved[param] = float(val)
            else:
                resolved[param] = float(spec.get("default", 3))
        return resolved

    def _build_shell(
        self,
        pattern: dict,
        dims: Dict[str, float],
        root: str,
        origin: Tuple[float, float] = (0.0, 0.0),
    ) -> List:
        """Create the room's structural nodes (floor, ceiling)."""
        steps: List = []
        for node_spec in pattern.get("shell", []):
            name = node_spec.get("name", "Shell")
            node_type = node_spec.get("type", "MeshInstance3D")
            node_path = f"{root}/{name}"

            steps.append(
                CreateEntityStep(
                    name=name,
                    node_type=node_type,
                    parent=root,
                )
            )

            # Position (offset by the world origin so BSP-placed rooms tile)
            raw_pos = node_spec.get("position", [0, 0, 0])
            # Evaluate expressions in a temp resolver
            # For shell nodes, expressions like $width/2 need dims
            pos_x = self._eval_shell_expr(raw_pos[0], dims) + origin[0]
            pos_y = self._eval_shell_expr(raw_pos[1], dims)
            pos_z = self._eval_shell_expr(raw_pos[2], dims) + origin[1]

            steps.append(
                SetPropertyStep(
                    node=node_path,
                    property="position",
                    value={"x": pos_x, "y": pos_y, "z": pos_z},
                )
            )

            # Mesh
            mesh_name = node_spec.get("mesh", "plane")
            steps.append(
                SetPropertyStep(
                    node=node_path,
                    property="mesh",
                    value={"__class__": f"{mesh_name.capitalize()}Mesh", "size": {"x": 10, "y": 10}},
                )
            )

            # Scale for floor/ceiling planes
            scale = node_spec.get("scale")
            if scale and isinstance(scale, list) and len(scale) == 3:
                sx = self._eval_shell_expr(scale[0], dims)
                sy = self._eval_shell_expr(scale[1], dims)
                sz = self._eval_shell_expr(scale[2], dims)
                steps.append(
                    SetPropertyStep(
                        node=node_path,
                        property="scale",
                        value={"x": sx, "y": sy, "z": sz},
                    )
                )

            # Color
            color = node_spec.get("color")
            if color and isinstance(color, list) and len(color) == 3:
                steps.append(
                    SetPropertyStep(
                        node=node_path,
                        property="material_override",
                        value=_material(color[0], color[1], color[2]),
                    )
                )

        return steps

    def _fill_slot(
        self,
        slot_id: str,
        slot_def: dict,
        asset_id: str,
        resolver: AnchorResolver,
        root: str,
        bounding_boxes: Dict[str, dict],
        placed: Set[str],
        dims: Dict[str, float],
    ) -> Tuple[List, Optional[str], Optional[dict], Optional[dict]]:
        """Fill one slot with an asset. Returns (steps, name, position, bb)."""
        # Validate asset exists
        entry = self._lexicon.require(asset_id)

        # Validate fits
        max_fp = slot_def.get("max_footprint")
        if max_fp and not self._lexicon.fits_slot(asset_id, max_fp):
            fp = self._lexicon.footprint(asset_id) or {}
            raise SlotViolation(
                f"Asset '{asset_id}' ({fp.get('width', 0)}×{fp.get('depth', 0)}) "
                f"doesn't fit slot '{slot_id}' "
                f"(max {max_fp.get('width', 0)}×{max_fp.get('depth', 0)})"
            )

        # Resolve position
        anchor = slot_def.get("anchor", {})
        if isinstance(anchor, dict) and "chain" in anchor:
            chain = anchor["chain"]
            try:
                pos = resolver.resolve_chain(chain, bounding_boxes)
            except ValueError:
                # Chain target not found as placed object — try matching
                # against any placed object whose name ends with _<target>
                # (placed objects are named {asset}_{slot})
                target = str(chain[0]) if chain else ""
                found = False
                for placed_name in bounding_boxes:
                    if placed_name.endswith(f"_{target}"):
                        chain[0] = placed_name
                        pos = resolver.resolve_chain(chain, bounding_boxes)
                        found = True
                        break
                if not found:
                    raise
        elif isinstance(anchor, str):
            pos = resolver.resolve(anchor)
        else:
            pos = resolver.resolve("center")

        # Apply slot offset
        offset = slot_def.get("offset", [0, 0, 0])
        pos = {
            "x": pos["x"] + float(offset[0]),
            "y": pos["y"] + float(offset[1]),
            "z": pos["z"] + float(offset[2]),
        }

        # Build name
        name = f"{asset_id}_{slot_id}"

        # Check overlap — bb must include cx/cz for the position
        fp = entry.get("footprint", {})
        bb = {
            "half_width": float(fp.get("width", 1)) / 2,
            "half_depth": float(fp.get("depth", 1)) / 2,
            "cx": pos["x"],
            "cz": pos["z"],
        }
        if self._overlaps(pos, bb, bounding_boxes):
            pos = self._nudge(pos, bb, bounding_boxes)

        # Emit ops via lexicon
        ops = self._lexicon.greybox_ops(asset_id, root, name, pos)
        steps = self._ops_to_steps(ops)

        return steps, name, pos, bb

    def _process_arcs(
        self,
        override: dict,
        resolver: AnchorResolver,
        root: str,
        bounding_boxes: Dict[str, dict],
        dims: Dict[str, float],
    ) -> Tuple[List, Optional[str], Optional[dict], Optional[dict]]:
        """Process an ARCS override: {asset, anchor, offset}."""
        asset_id = override.get("asset", "")
        if not asset_id:
            return [], None, None, None

        entry = self._lexicon.require(asset_id)

        anchor_spec = override.get("anchor", {})
        if isinstance(anchor_spec, dict) and "chain" in anchor_spec:
            pos = resolver.resolve_chain(anchor_spec["chain"], bounding_boxes)
        elif isinstance(anchor_spec, str):
            pos = resolver.resolve(anchor_spec)
        else:
            pos = resolver.resolve("center")

        offset = override.get("offset", [0, 0, 0])
        pos = {
            "x": pos["x"] + float(offset[0]) if len(offset) > 0 else pos["x"],
            "y": pos["y"] + float(offset[1]) if len(offset) > 1 else pos["y"],
            "z": pos["z"] + float(offset[2]) if len(offset) > 2 else pos["z"],
        }

        name = f"{asset_id}_arcs"

        fp = entry.get("footprint", {})
        bb = {
            "half_width": float(fp.get("width", 1)) / 2,
            "half_depth": float(fp.get("depth", 1)) / 2,
            "cx": pos["x"],
            "cz": pos["z"],
        }

        # Collision-nudge ARCS objects too — they share the room with the
        # slot-placed furniture, so an override must not clip into it
        # (parity with _fill_slot; the safety net is structural, rule #4).
        if self._overlaps(pos, bb, bounding_boxes):
            pos = self._nudge(pos, bb, bounding_boxes)

        ops = self._lexicon.greybox_ops(asset_id, root, name, pos)
        steps = self._ops_to_steps(ops)

        return steps, name, pos, bb

    def _ops_to_steps(self, ops: List[dict]) -> List:
        """Convert raw op dicts → PlanSteps for the DevForgePlan."""
        steps: List = []
        for op in ops:
            t = op.get("type", "")
            if t == "add_node":
                steps.append(
                    CreateEntityStep(
                        name=op["name"],
                        node_type=op.get("node_type", "MeshInstance3D"),
                        parent=op.get("parent", "/root/Main"),  # caller resolves the root
                    )
                )
            elif t == "set_property":
                steps.append(
                    SetPropertyStep(
                        node=op["node"],
                        property=op["property"],
                        value=op["value"],
                    )
                )
        return steps

    # ── collision detection ─────────────────────────────────

    @staticmethod
    def _overlaps(pos: dict, bb: dict, existing: Dict[str, dict]) -> bool:
        """Check if an AABB at pos overlaps any existing AABB."""
        hw, hd = bb["half_width"], bb["half_depth"]
        for name, other in existing.items():
            ohw = other.get("half_width", 0.5)
            ohd = other.get("half_depth", 0.5)
            ox = other.get("cx", 0)
            oz = other.get("cz", 0)
            # Simple 2D AABB overlap on the XZ plane
            if abs(pos["x"] - ox) < (hw + ohw) and abs(pos["z"] - oz) < (hd + ohd):
                return True
        return False

    @staticmethod
    def _nudge(pos: dict, bb: dict, existing: Dict[str, dict]) -> dict:
        """Nudge a position to resolve overlaps (simple iterative push)."""
        hw, hd = bb["half_width"], bb["half_depth"]
        for _ in range(10):
            moved = False
            for name, other in existing.items():
                ohw = other.get("half_width", 0.5)
                ohd = other.get("half_depth", 0.5)
                ox = other.get("cx", 0)
                oz = other.get("cz", 0)
                dx = pos["x"] - ox
                dz = pos["z"] - oz
                ox_overlap = (hw + ohw) - abs(dx)
                oz_overlap = (hd + ohd) - abs(dz)
                if ox_overlap > 0 and oz_overlap > 0:
                    # Push along the axis with smaller overlap
                    if ox_overlap < oz_overlap:
                        pos["x"] += math.copysign(ox_overlap, dx)
                    else:
                        pos["z"] += math.copysign(oz_overlap, dz)
                    moved = True
            if not moved:
                break

        # Update bb center for future queries
        bb["cx"] = pos["x"]
        bb["cz"] = pos["z"]
        return pos

    @staticmethod
    def _eval_shell_expr(expr: Any, dims: Dict[str, float]) -> float:
        """Evaluate a simple expression like '$width/2' using safe regex."""
        import re

        if isinstance(expr, (int, float)):
            return float(expr)
        if isinstance(expr, str):
            # Replace $param with its numeric value
            s = expr.strip()
            for param, val in dims.items():
                s = s.replace(f"${param}", str(val))
            # Evaluate basic arithmetic: number, op, number
            m = re.match(r"^\s*([\d.]+)\s*(?:([+\-*/])\s*([\d.]+))?\s*$", s)
            if m:
                a = float(m.group(1))
                op = m.group(2)
                if op and m.group(3):
                    b = float(m.group(3))
                    if op == "+":
                        return a + b
                    elif op == "-":
                        return a - b
                    elif op == "*":
                        return a * b
                    elif op == "/":
                        return a / b if b != 0 else a
                return a
            try:
                return float(s)
            except ValueError:
                return 0.0
        return float(expr)
