"""World State — shared spatial coordination layer for multi-engine composition.

Phase B of Guide 2: a lightweight, layered occupancy grid that allows
generative engines to read from and write to a shared spatial context.
Engines check occupancy before placing, adjust Y-heights from terrain,
and mark their placements for downstream engines.

The LLM never sees the raw grid — only a topological summary of known
regions and vacant areas, assembled by ContextAssembler at plan time.

See docs/reviews/world-state-richness/DESIGN-PROPOSAL.md §1-2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RegionSpec:
    """A named, typed region of the world for LLM topology queries."""

    type: str  # "forest", "village", "lake", "mountain", "plains", etc.
    bounds: tuple[float, float, float, float]  # (min_x, min_z, width, depth)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorldState:
    """Layered occupancy grid for multi-engine spatial coordination.

    All coordinates are world-space (x, z). The grid is coarse (default
    2m cells) to keep memory and LLM context footprint small.

    Layers:
        height:     Base Y-elevation per cell (default 0.0 = flat).
        biome:      Categorical tag per cell.
        occupancy:  Set of entity IDs blocking each cell.
        network:    Infrastructure type per cell (dirt_road, river, …).
        regions:    Named bounding boxes with type tags.
    """

    cell_size: float = 2.0  # metres per cell
    origin: tuple[float, float] = (0.0, 0.0)  # world-space (x, z) of cell (0, 0)

    height: dict[tuple[int, int], float] = field(default_factory=dict)
    biome: dict[tuple[int, int], str] = field(default_factory=dict)
    occupancy: dict[tuple[int, int], set[str]] = field(default_factory=dict)
    network: dict[tuple[int, int], str] = field(default_factory=dict)
    regions: dict[str, RegionSpec] = field(default_factory=dict)

    # ── grid helpers ──────────────────────────────────────────

    def cell_at(self, x: float, z: float) -> tuple[int, int]:
        """Return the (col, row) cell index for world-space (x, z)."""
        ox, oz = self.origin
        return (int((x - ox) / self.cell_size), int((z - oz) / self.cell_size))

    def cell_center(self, col: int, row: int) -> tuple[float, float]:
        """Return world-space (x, z) centre of a grid cell."""
        ox, oz = self.origin
        return (
            ox + (col + 0.5) * self.cell_size,
            oz + (row + 0.5) * self.cell_size,
        )

    # ── occupancy queries ─────────────────────────────────────

    def is_occupied(self, x: float, z: float, margin: float = 0.0) -> bool:
        """Check if the cell at (x, z) has any occupancy entries.

        When margin > 0, also checks neighbouring cells within the margin
        radius (Manhattan distance ≤ margin in cells).
        """
        col, row = self.cell_at(x, z)
        cells = max(0, int(margin / self.cell_size))
        for dc in range(-cells, cells + 1):
            for dr in range(-cells, cells + 1):
                cell = self.occupancy.get((col + dc, row + dr))
                if cell:
                    return True
        return False

    def is_cell_occupied(self, col: int, row: int) -> bool:
        """Check if a specific grid cell is occupied."""
        return bool(self.occupancy.get((col, row)))

    # ── occupancy writes ──────────────────────────────────────

    def mark_occupied(
        self,
        x: float,
        z: float,
        entity_id: str,
        footprint: tuple[float, float] = (1.0, 1.0),
    ) -> None:
        """Mark all cells covered by an entity's footprint as occupied.

        Args:
            x, z: World-space centre of the entity.
            entity_id: Unique name (e.g. "bld_civic_0_0").
            footprint: (width, depth) in metres. Default (1,1) = single cell.
        """
        hw = footprint[0] / 2
        hd = footprint[1] / 2
        min_col, min_row = self.cell_at(x - hw, z - hd)
        max_col, max_row = self.cell_at(x + hw, z + hd)
        for c in range(min_col, max_col + 1):
            for r in range(min_row, max_row + 1):
                self.occupancy.setdefault((c, r), set()).add(entity_id)

    def unmark_occupied(self, entity_id: str) -> None:
        """Remove an entity from all occupancy cells (e.g. tree removal)."""
        for cell in self.occupancy.values():
            cell.discard(entity_id)

    def clear_occupancy(self) -> None:
        """Remove all occupancy entries (does not affect other layers)."""
        self.occupancy.clear()

    # ── height ────────────────────────────────────────────────

    def get_height(self, x: float, z: float) -> float:
        """Return the Y-elevation at world-space (x, z). Default 0.0."""
        return self.height.get(self.cell_at(x, z), 0.0)

    def set_height(self, x: float, z: float, y: float) -> None:
        """Set the Y-elevation for the cell containing (x, z)."""
        self.height[self.cell_at(x, z)] = y

    # ── biome ─────────────────────────────────────────────────

    def get_biome(self, x: float, z: float) -> str:
        return self.biome.get(self.cell_at(x, z), "plains")

    def set_biome(self, x: float, z: float, biome: str) -> None:
        self.biome[self.cell_at(x, z)] = biome

    # ── region management ─────────────────────────────────────

    def add_region(self, region_id: str, spec: RegionSpec) -> None:
        """Register a named region (e.g. 'dark_forest')."""
        self.regions[region_id] = spec

    def query_region(self, region_id: str) -> RegionSpec | None:
        return self.regions.get(region_id)

    def region_bounds(self, region_id: str) -> tuple[float, float, float, float] | None:
        """Return (x, z, w, d) for a named region, or None."""
        r = self.regions.get(region_id)
        return r.bounds if r else None

    # ── summary for LLM context ───────────────────────────────

    def summary(self) -> dict:
        """Return a compact JSON-serialisable summary for the LLM prompt.

        The LLM sees topological awareness (regions + vacant areas), not
        the raw grid.  This keeps context tokens small.
        """
        known = []
        for rid, r in self.regions.items():
            x, z, w, d = r.bounds
            known.append({"id": rid, "type": r.type, "bounds": {"x": x, "z": z, "w": w, "d": d}})

        # Find contiguous unoccupied regions (simplistic: just report
        # the full area as vacant if no regions are registered)
        vacant: list[dict] = []
        if not self.regions:
            # No regions yet — everything is vacant
            vacant.append({"x": -500, "z": -500, "w": 1000, "d": 1000})
        else:
            # Compute the convex hull of known regions and report
            # areas outside it
            all_x = [r.bounds[0] for r in self.regions.values()]
            all_z = [r.bounds[1] for r in self.regions.values()]
            if all_x:
                min_x, max_x = min(all_x), max(all_x) + max(r.bounds[2] for r in self.regions.values())
                min_z, max_z = min(all_z), max(all_z) + max(r.bounds[3] for r in self.regions.values())
                # Simple: vacant is everything beyond ±500m of known regions
                margin = 500
                vacant.append(
                    {
                        "x": min_x - margin,
                        "z": min_z - margin,
                        "w": (max_x - min_x) + 2 * margin,
                        "d": (max_z - min_z) + 2 * margin,
                    }
                )

        return {
            "cell_size_m": self.cell_size,
            "known_regions": known,
            "vacant_regions": vacant,
        }

    # ── serialisation ─────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict for persistence."""
        return {
            "cell_size": self.cell_size,
            "origin": list(self.origin),
            "height": {f"{c},{r}": v for (c, r), v in self.height.items()},
            "biome": {f"{c},{r}": v for (c, r), v in self.biome.items()},
            "occupancy": {f"{c},{r}": sorted(v) for (c, r), v in self.occupancy.items()},
            "network": {f"{c},{r}": v for (c, r), v in self.network.items()},
            "regions": {
                rid: {"type": r.type, "bounds": list(r.bounds), "metadata": r.metadata}
                for rid, r in self.regions.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> WorldState:
        """Deserialize from a JSON-safe dict."""

        def _parse_cells(d: dict) -> dict:
            return {tuple(int(x) for x in k.split(",")): v for k, v in d.items()}

        return cls(
            cell_size=data.get("cell_size", 2.0),
            origin=tuple(data.get("origin", [0.0, 0.0])),
            height=_parse_cells(data.get("height", {})),
            biome=_parse_cells(data.get("biome", {})),
            occupancy={k: set(v) for k, v in _parse_cells(data.get("occupancy", {})).items()},
            network=_parse_cells(data.get("network", {})),
            regions={
                rid: RegionSpec(
                    type=r["type"],
                    bounds=tuple(r["bounds"]),
                    metadata=r.get("metadata", {}),
                )
                for rid, r in data.get("regions", {}).items()
            },
        )
