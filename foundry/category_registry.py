"""category_registry — single source of truth for all asset categories (T-4).

Before T-4, a new generator had to be registered in ~6 places (grammar,
compiler GENERATORS/PARAM_RANGES, lexicon, blender _BUILDERS, room_layout
FURNITURE/CARRYABLES, scene_compiler _COLLISION_SIZES).  The scatter was
the root cause of three integration bugs (carryables dropped from theme
filter, new props remapped to table, behaviour-gen crash w/o carryable).

After T-4, add a category *here* and the other modules derive from it:
  - compiler.GENERATORS = set(REGISTRY)
  - compiler.PARAM_RANGES = {k: v["param_ranges"] for k,v in REGISTRY.items() if "param_ranges" in v}
  - room_layout.FURNITURE = tuple(k for k,v in REGISTRY.items() if v["kind"]=="furniture")
  - room_layout.CARRYABLES = tuple(k for k,v in REGISTRY.items() if v["kind"]=="carryable")
  - scene_compiler._COLLISION_SIZES = {k: v["collision_size"] for k,v in REGISTRY.items()}
  - room_control._BASE_FURNITURE = {"table","chair","shelf","cabinet"}  (stays hand-curated)

The grammars (GBNF files) are NOT auto-generated — they're hand-written
validator files.  Adding a category here also requires updating the GBNF
files (category-val alternation).  Same for blender _BUILDERS (function
references can't be in a data module).

Per-category fields:
  kind            "furniture" | "carryable" | "decor" | "npc"
  collision_size  (x, y, z) tuple for BoxShape3D
  param_ranges    {param: (min, max)} for compiler validation (may be None for decor)
  furniture_top_y float — where carryables sit on this furniture (may be None)
  decor           bool — True for decoration-only categories
"""

from __future__ import annotations

from typing import Dict, Tuple

# ── Category registry — single source of truth ───────────────────

REGISTRY: Dict[str, dict] = {

    # ── Furniture ──────────────────────────────────────────────
    "table": {
        "kind": "furniture",
        "collision_size": (1.2, 0.6, 0.8),
        "furniture_top_y": 0.78,
        "param_ranges": {
            "top_width": (0.5, 3.0),
            "top_depth": (0.4, 2.0),
            "top_thickness": (0.03, 0.2),
            "leg_height": (0.3, 1.1),
            "leg_radius": (0.03, 0.12),
            "leg_inset": (0.0, 0.3),
        },
    },
    "chair": {
        "kind": "furniture",
        "collision_size": (0.5, 0.9, 0.5),
        "furniture_top_y": 0.48,
        "param_ranges": {
            "seat_width": (0.3, 0.55),
            "seat_depth": (0.3, 0.55),
            "seat_thickness": (0.03, 0.08),
            "leg_height": (0.25, 0.55),
            "leg_radius": (0.02, 0.05),
            "leg_inset": (0.0, 0.1),
            "back_height": (0.15, 0.4),
        },
    },
    "shelf": {
        "kind": "furniture",
        "collision_size": (1.0, 1.2, 0.3),
        "furniture_top_y": 1.2,
        "param_ranges": {
            "width": (0.5, 1.15),
            "depth": (0.2, 0.345),
            "height": (0.6, 1.38),
            "board_thickness": (0.02, 0.06),
            "n_shelves": (2, 5),
            "side_thickness": (0.02, 0.05),
        },
    },
    "cabinet": {
        "kind": "furniture",
        "collision_size": (0.8, 1.5, 0.5),
        "furniture_top_y": 1.55,
        "param_ranges": {
            "width": (0.5, 0.92),
            "depth": (0.3, 0.575),
            "height": (0.8, 1.84),
            "panel_thickness": (0.02, 0.06),
            "base_height": (0.03, 0.12),
        },
    },
    # P-F batch 1: themed-useful stress-test generators
    "barrel": {
        "kind": "furniture",
        "collision_size": (0.55, 1.05, 0.55),
        "furniture_top_y": 1.05,
        "param_ranges": {
            "radius": (0.2, 0.5),
            "height": (0.4, 1.0),
        },
    },
    "crate": {
        "kind": "furniture",
        "collision_size": (0.85, 0.85, 0.85),
        "furniture_top_y": 0.85,
        "param_ranges": {
            "width": (0.3, 0.8),
            "depth": (0.3, 0.8),
            "height": (0.3, 0.8),
        },
    },
    "chest": {
        "kind": "furniture",
        "collision_size": (0.75, 0.55, 0.55),
        "furniture_top_y": 0.55,
        "param_ranges": {
            "width": (0.3, 0.7),
            "depth": (0.2, 0.5),
            "height": (0.2, 0.5),
        },
    },
    "stool": {
        "kind": "furniture",
        "collision_size": (0.35, 0.65, 0.35),
        "furniture_top_y": 0.6,
        "param_ranges": {
            "radius": (0.15, 0.3),
            "height": (0.3, 0.6),
        },
    },
    "bench": {
        "kind": "furniture",
        "collision_size": (2.1, 0.6, 0.45),
        "furniture_top_y": 0.55,
        "param_ranges": {
            "width": (0.8, 2.0),
            "depth": (0.2, 0.4),
            "height": (0.3, 0.55),
        },
    },
    # P-F batch 2: themed-useful generators
    "wardrobe": {
        "kind": "furniture",
        "collision_size": (1.25, 2.6, 0.75),
        "furniture_top_y": 2.55,
        "param_ranges": {
            "width": (0.6, 1.2),
            "depth": (0.4, 0.7),
            "height": (1.5, 2.5),
        },
    },
    "desk": {
        "kind": "furniture",
        "collision_size": (2.1, 0.95, 0.85),
        "furniture_top_y": 0.88,
        "param_ranges": {
            "width": (0.8, 2.0),
            "depth": (0.4, 0.8),
            "height": (0.5, 0.9),
        },
    },
    "lantern": {
        "kind": "furniture",
        "collision_size": (0.28, 0.85, 0.28),
        "furniture_top_y": 0.82,
        "param_ranges": {
            "radius": (0.08, 0.2),
            "height": (0.3, 0.8),
        },
    },
    "pot": {
        "kind": "furniture",
        "collision_size": (0.45, 1.15, 0.45),
        "furniture_top_y": 1.12,
        "param_ranges": {
            "body_radius": (0.15, 0.4),
            "body_height": (0.3, 0.8),
            "neck_radius": (0.08, 0.25),
            "neck_height": (0.1, 0.3),
        },
    },
    "weapon-rack": {
        "kind": "furniture",
        "collision_size": (0.85, 2.3, 0.35),
        "furniture_top_y": 2.25,
        "param_ranges": {
            "width": (0.3, 0.8),
            "depth": (0.15, 0.3),
            "height": (1.0, 2.2),
        },
    },
    "pillar": {
        "kind": "furniture",
        "collision_size": (0.45, 3.15, 0.45),
        "furniture_top_y": 3.1,
        "param_ranges": {
            "radius": (0.15, 0.4),
            "height": (1.0, 3.0),
        },
    },
    "planter": {
        "kind": "furniture",
        "collision_size": (0.85, 0.75, 0.85),
        "furniture_top_y": 0.72,
        "param_ranges": {
            "width": (0.3, 0.8),
            "depth": (0.3, 0.8),
            "height": (0.3, 0.7),
        },
    },
    # P-F batch 3: edge-case generators
    "huge_table": {
        "kind": "furniture",
        "collision_size": (3.15, 1.3, 2.1),
        "furniture_top_y": 1.25,
        "param_ranges": {
            "top_width": (0.5, 3.0),
            "top_depth": (0.4, 2.0),
            "top_thickness": (0.03, 0.2),
            "leg_height": (0.3, 1.1),
            "leg_radius": (0.03, 0.12),
            "leg_inset": (0.0, 0.3),
        },
    },
    "tiny_stool": {
        "kind": "furniture",
        "collision_size": (0.2, 0.35, 0.2),
        "furniture_top_y": 0.32,
        "param_ranges": {
            "radius": (0.08, 0.15),
            "height": (0.15, 0.3),
        },
    },
    "partition": {
        "kind": "furniture",
        "collision_size": (3.15, 3.15, 0.12),
        "furniture_top_y": 3.1,
        "param_ranges": {
            "width": (1.0, 3.0),
            "depth": (0.03, 0.08),
            "height": (1.5, 3.0),
        },
    },
    "tall_post": {
        "kind": "furniture",
        "collision_size": (0.1, 4.2, 0.1),
        "furniture_top_y": 4.15,
        "param_ranges": {
            "radius": (0.03, 0.08),
            "height": (2.0, 4.0),
        },
    },
    "wide_platform": {
        "kind": "furniture",
        "collision_size": (4.2, 0.15, 4.2),
        "furniture_top_y": 0.12,
        "param_ranges": {
            "width": (2.0, 4.0),
            "depth": (2.0, 4.0),
            "height": (0.04, 0.1),
        },
    },
    "many_leg_table": {
        "kind": "furniture",
        "collision_size": (2.1, 0.95, 1.6),
        "furniture_top_y": 0.92,
        "param_ranges": {
            "top_width": (0.5, 2.0),
            "top_depth": (0.4, 1.5),
            "top_thickness": (0.03, 0.15),
            "leg_height": (0.3, 0.9),
            "leg_radius": (0.02, 0.06),
        },
    },
    "ladder": {
        "kind": "furniture",
        "collision_size": (0.65, 3.15, 0.1),
        "furniture_top_y": 3.1,
        "param_ranges": {
            "width": (0.3, 0.6),
            "depth": (0.03, 0.06),
            "height": (1.5, 3.0),
            "n_rungs": (4, 15),
        },
    },
    "L_bench": {
        "kind": "furniture",
        "collision_size": (2.3, 0.6, 2.3),
        "furniture_top_y": 0.55,
        "param_ranges": {
            "width": (0.8, 2.0),
            "depth": (0.3, 0.6),
            "height": (0.3, 0.55),
        },
    },

    # ── Carryables (P-E) ───────────────────────────────────────
    "key": {
        "kind": "carryable",
        "collision_size": (0.12, 0.01, 0.06),
        "furniture_top_y": None,
        "param_ranges": {
            "head_w": (0.03, 0.08),
            "head_h": (0.02, 0.05),
            "shaft_l": (0.04, 0.1),
        },
    },
    "book": {
        "kind": "carryable",
        "collision_size": (0.25, 0.05, 0.2),
        "furniture_top_y": None,
        "param_ranges": {
            "width": (0.1, 0.25),
            "depth": (0.08, 0.2),
            "thickness": (0.01, 0.05),
        },
    },
    "cup": {
        "kind": "carryable",
        "collision_size": (0.16, 0.15, 0.16),
        "furniture_top_y": None,
        "param_ranges": {
            "radius": (0.03, 0.08),
            "height": (0.06, 0.15),
        },
    },
    "gem": {
        "kind": "carryable",
        "collision_size": (0.08, 0.08, 0.08),
        "furniture_top_y": None,
        "param_ranges": {
            "size": (0.03, 0.08),
        },
    },
    "bottle": {
        "kind": "carryable",
        "collision_size": (0.14, 0.22, 0.14),
        "furniture_top_y": None,
        "param_ranges": {
            "body_radius": (0.03, 0.07),
            "body_height": (0.06, 0.15),
            "neck_radius": (0.01, 0.03),
            "neck_height": (0.03, 0.08),
        },
    },
    "scroll": {
        "kind": "carryable",
        "collision_size": (0.06, 0.05, 0.25),
        "furniture_top_y": None,
        "param_ranges": {
            "radius": (0.02, 0.05),
            "length": (0.1, 0.25),
        },
    },
    "coin-pouch": {
        "kind": "carryable",
        "collision_size": (0.15, 0.1, 0.12),
        "furniture_top_y": None,
        "param_ranges": {
            "width": (0.06, 0.15),
            "depth": (0.05, 0.12),
            "height": (0.04, 0.1),
        },
    },
    "candle": {
        "kind": "carryable",
        "collision_size": (0.1, 0.15, 0.1),
        "furniture_top_y": None,
        "param_ranges": {
            "radius": (0.02, 0.05),
            "height": (0.06, 0.15),
        },
    },
    "dagger": {
        "kind": "carryable",
        "collision_size": (0.25, 0.04, 0.06),
        "furniture_top_y": None,
        "param_ranges": {
            "blade_l": (0.1, 0.2),
            "blade_w": (0.01, 0.03),
            "handle_l": (0.05, 0.1),
        },
    },
    "ring": {
        "kind": "carryable",
        "collision_size": (0.07, 0.03, 0.07),
        "furniture_top_y": None,
        "param_ranges": {
            "size": (0.03, 0.07),
        },
    },

    # ── Decor ─────────────────────────────────────────────────
    "rug": {
        "kind": "decor",
        "collision_size": (0.8, 0.01, 0.6),  # not used (decor)
        "furniture_top_y": None,
        "param_ranges": {
            "width": (0.8, 3.5),
            "depth": (0.6, 2.5),
            "thickness": (0.01, 0.04),
        },
    },
    "painting": {
        "kind": "decor",
        "collision_size": (0.3, 1.2, 0.03),  # not used (decor)
        "furniture_top_y": None,
        "param_ranges": {
            "width": (0.3, 1.2),
            "height": (0.3, 1.2),
            "thickness": (0.03, 0.08),
        },
    },

    # ── NPC ───────────────────────────────────────────────────
    "humanoid": {
        "kind": "npc",
        "collision_size": (0.5, 2.8, 0.4),
        "furniture_top_y": None,
        "param_ranges": {
            "total_height": (1.2, 2.2),
            "body_width": (0.3, 0.7),
            "limb_thickness": (0.08, 0.2),
            "head_size": (0.15, 0.35),
        },
    },
}

# ── Default fallback ─────────────────────────────────────────────

_DEFAULT = {
    "collision_size": (0.5, 0.5, 0.5),
    "furniture_top_y": 0.8,
}

# ── Derived convenience accessors ─────────────────────────────────

def get_kind(category: str) -> str:
    """Return the kind of a category ('furniture', 'carryable', 'decor', 'npc')."""
    entry = REGISTRY.get(category)
    return entry["kind"] if entry else "?"


def get_collision_size(category: str) -> Tuple[float, float, float]:
    """Return the collision BoxShape3D size for *category*."""
    entry = REGISTRY.get(category)
    if entry:
        return entry["collision_size"]
    return _DEFAULT["collision_size"]


def get_furniture_top_y(category: str) -> float:
    """Return the top-Y (where carryables sit) for furniture *category*."""
    entry = REGISTRY.get(category)
    if entry and entry.get("furniture_top_y") is not None:
        return entry["furniture_top_y"]
    if entry and entry["kind"] == "furniture":
        return _DEFAULT["furniture_top_y"]
    return 0.0


def get_param_ranges(category: str) -> dict:
    """Return the param_ranges dict for *category*."""
    entry = REGISTRY.get(category)
    if entry and entry.get("param_ranges"):
        return entry["param_ranges"]
    return {}


# ── Derived sets/tuples for other modules ────────────────────────

GENERATORS = frozenset(REGISTRY)

FURNITURE = tuple(
    k for k, v in REGISTRY.items() if v["kind"] == "furniture"
)

CARRYABLES = tuple(
    k for k, v in REGISTRY.items() if v["kind"] == "carryable"
)

DECOR_CATEGORIES = frozenset(
    k for k, v in REGISTRY.items() if v["kind"] == "decor"
)

# C-0 theme tables only gate BASE furniture for theme palette checks;
# carryables + extended props pass through every theme.
BASE_FURNITURE = frozenset({"table", "chair", "shelf", "cabinet"})

COLLISION_SIZES: Dict[str, Tuple[float, float, float]] = {
    k: v["collision_size"] for k, v in REGISTRY.items()
}
COLLISION_SIZES["?"] = _DEFAULT["collision_size"]

PARAM_RANGES: Dict[str, dict] = {
    k: v["param_ranges"]
    for k, v in REGISTRY.items()
    if v.get("param_ranges")
}

FURNITURE_TOP_Y: Dict[str, float] = {
    k: v["furniture_top_y"]
    for k, v in REGISTRY.items()
    if v.get("furniture_top_y") is not None
}
