"""Asset Lexicon — load, validate, and query asset definitions.

The lexicon is the single source of truth for what assets exist, their
physical footprints (width/depth/height), and how to greybox-render them.

For the initial greybox slice, assets are primitive placeholders (boxes,
cylinders) with hand-authored footprints. Migrating to real art is a
one-field change: add a scene_path and the compiler instances the model
at the same resolved transform.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from devforge.infrastructure.logger import logger


class SlotViolation(ValueError):
    """An asset cannot fit in a slot (too large) or doesn't exist in the lexicon."""


class AssetLexicon:
    """Loads and validates asset_lexicon.json."""

    DEFAULT_PATH = Path(__file__).resolve().parent / "asset_lexicon.json"

    def __init__(self, path: str | Path | None = None):
        self._path = Path(path) if path else self.DEFAULT_PATH
        self._assets: Dict[str, dict] = {}
        self._by_category: Dict[str, List[str]] = {}
        self._load()

    # ── public API ──────────────────────────────────────────

    @property
    def asset_ids(self) -> List[str]:
        return sorted(self._assets.keys())

    def get(self, asset_id: str) -> Optional[dict]:
        """Return the full asset entry dict or None."""
        return self._assets.get(asset_id)

    def require(self, asset_id: str) -> dict:
        """Return the asset entry; raise SlotViolation if missing."""
        entry = self._assets.get(asset_id)
        if entry is None:
            raise SlotViolation(f"Asset '{asset_id}' not found in lexicon. Available: {', '.join(self.asset_ids)}")
        return entry

    def by_category(self, category: str) -> List[str]:
        """Asset ids matching a category."""
        return self._by_category.get(category, [])

    def footprint(self, asset_id: str) -> Optional[dict]:
        """Return {width, depth} for the asset."""
        entry = self._assets.get(asset_id)
        if entry:
            return entry.get("footprint")
        return None

    def height(self, asset_id: str) -> float:
        """Return the asset's height in metres."""
        entry = self._assets.get(asset_id)
        if entry:
            return float(entry.get("height", 1.0))
        return 1.0

    def fits_slot(self, asset_id: str, max_footprint: dict | None) -> bool:
        """Check whether the asset fits within the slot's max footprint."""
        if max_footprint is None:
            return True
        fp = self.footprint(asset_id)
        if fp is None:
            return False
        max_w = float(max_footprint.get("width", 0))
        max_d = float(max_footprint.get("depth", 0))
        return float(fp.get("width", 0)) <= max_w and float(fp.get("depth", 0)) <= max_d

    def greybox_ops(
        self, asset_id: str, parent: str, name: str, position: dict, facing: Optional[list] = None
    ) -> List[dict]:
        """Produce the batch_execute ops to place a greybox asset.

        Returns the standard DevForge op dicts: add_node + set_property
        (mesh, color, position, rotation). Uses the existing Phase 4 props
        pipeline — zero new executor surface.

        ``position`` is {x, y, z} in Godot space.
        ``facing`` is an optional [x, y, z] look-at direction.
        """
        entry = self.require(asset_id)
        gb = entry.get("greybox", {})
        mesh = gb.get("mesh", "box")
        color = gb.get("color", [0.5, 0.5, 0.5])
        h = entry.get("height", 1.0)
        fp = entry.get("footprint", {})

        ops: List[dict] = []

        # add_node
        ops.append(
            {
                "type": "add_node",
                "parent": parent,
                "node_type": "MeshInstance3D",
                "name": name,
            }
        )

        node_path = f"{parent}/{name}"

        # mesh — build the resource dict separately for clarity
        if mesh == "box":
            mesh_value: dict = {
                "__class__": "BoxMesh",
                "size": {
                    "x": float(fp.get("width", 1)),
                    "y": h,
                    "z": float(fp.get("depth", 1)),
                },
            }
        else:
            # Cylinder — use the footprint width as the diameter
            radius = float(fp.get("width", 0.5)) / 2
            mesh_value = {
                "__class__": "CylinderMesh",
                "top_radius": radius,
                "bottom_radius": radius,
                "height": h,
            }

        ops.append(
            {
                "type": "set_property",
                "node": node_path,
                "property": "mesh",
                "value": mesh_value,
            }
        )

        # position
        ops.append(
            {
                "type": "set_property",
                "node": node_path,
                "property": "position",
                "value": {"x": position["x"], "y": position["y"] + h / 2, "z": position["z"]},
            }
        )

        # color (material_override)
        ops.append(
            {
                "type": "set_property",
                "node": node_path,
                "property": "material_override",
                "value": {
                    "__class__": "StandardMaterial3D",
                    "albedo_color": {"r": color[0], "g": color[1], "b": color[2], "a": 1.0},
                },
            }
        )

        return ops

    def summary_for_prompt(self) -> str:
        """One-line-per-asset summary for the LLM prompt."""
        lines = []
        for aid in sorted(self._assets.keys()):
            entry = self._assets[aid]
            fp = entry.get("footprint", {})
            h = entry.get("height", 0)
            cats = ", ".join(entry.get("category", []))
            lines.append(f"  {aid}: {fp.get('width', 0)}×{fp.get('depth', 0)}×{h}m [{cats}]")
        return "\n".join(lines)

    # ── internals ───────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            logger.warn("lexicon", f"Lexicon not found: {self._path}")
            return

        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("lexicon", f"Failed to parse {self._path}: {exc}")
            return

        assets = data.get("assets", {})
        for aid, entry in assets.items():
            self._validate_entry(aid, entry)
            self._assets[aid] = entry
            for cat in entry.get("category", []):
                self._by_category.setdefault(cat, []).append(aid)

        logger.info("lexicon", f"Loaded {len(self._assets)} assets from {self._path}")

    @staticmethod
    def _validate_entry(aid: str, entry: dict) -> None:
        required = ["category", "footprint", "height", "greybox"]
        for key in required:
            if key not in entry:
                raise SlotViolation(f"Asset '{aid}' missing required field '{key}'")
        fp = entry["footprint"]
        if not isinstance(fp, dict) or "width" not in fp or "depth" not in fp:
            raise SlotViolation(f"Asset '{aid}' footprint missing width/depth")
