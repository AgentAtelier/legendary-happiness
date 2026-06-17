"""SSP Engine — Semantic Spatial Primitives for room generation.

Two input formats supported (detected automatically):

1. **Legacy archetype** (backward compat):
   ``{"archetype": "kitchen", "dimensions": ..., "slot_overrides": ...}``
   LLM picks a label; engine fills in from ROOM_ARCHETYPES presets.

2. **Intent Descriptor** (Stage 4 rebalance):
   ``{"room_type": "kitchen", "size": "cramped", "style": "rustic",
   "clutter": 0.3, "mood_tags": ["abandoned"], "must_have": ["stove"],
   "special_features": ["secret_passage"], "seed": 42}``
   LLM writes a rich brief; engine resolves EVERY field with a seeded RNG.

See STAGE-4-REBALANCE-PLAN.md §Move 3 for the full resolution map.
"""

from __future__ import annotations

import colorsys
import random
from typing import Any, Dict, List, Optional, Tuple

from devforge.compilation.ir.plan import DevForgePlan
from devforge.infrastructure.logger import logger

# ── Size presets ───────────────────────────────────────────────────

_SIZE_PRESETS: Dict[str, Dict[str, float]] = {
    "cramped":  {"width": 3.0, "height": 2.8, "depth": 3.0},
    "normal":   {"width": 5.0, "height": 3.0, "depth": 4.0},
    "spacious": {"width": 8.0, "height": 3.5, "depth": 6.0},
}

# ── Style palettes — RGB color tints per style ─────────────────────

_STYLE_PALETTES: Dict[str, Dict[str, list]] = {
    "rustic": {
        "warm_brown":  [0.55, 0.35, 0.20],
        "wood":        [0.50, 0.38, 0.25],
        "dark_wood":   [0.35, 0.22, 0.12],
        "warm_grey":   [0.55, 0.50, 0.45],
    },
    "industrial": {
        "steel_grey":  [0.45, 0.45, 0.50],
        "dark_metal":  [0.30, 0.30, 0.35],
        "concrete":    [0.65, 0.65, 0.65],
        "pipe_black":  [0.15, 0.15, 0.18],
    },
    "noble": {
        "rich_red":    [0.55, 0.15, 0.10],
        "gold":        [0.85, 0.70, 0.20],
        "ivory":       [0.95, 0.90, 0.80],
        "dark_oak":    [0.25, 0.15, 0.08],
    },
    "derelict": {
        "moss_green":  [0.25, 0.35, 0.20],
        "rust":        [0.50, 0.25, 0.10],
        "grey_mold":   [0.40, 0.42, 0.35],
        "faded_wood":  [0.45, 0.38, 0.30],
    },
}

# Default palette when no style is specified
_DEFAULT_PALETTE: Dict[str, list] = {
    "warm_brown": [0.55, 0.40, 0.30],
    "light_grey": [0.70, 0.70, 0.72],
    "dark_grey":  [0.30, 0.30, 0.35],
    "cream":      [0.90, 0.85, 0.78],
}

# ── Mood modifiers — how mood_tags affect the build ─────────────────

_MOOD_MODIFIERS: Dict[str, dict] = {
    "abandoned": {
        "saturation_scale": 0.4,    # desaturated colours
        "brightness_scale": 0.6,    # darker
        "intact_prop_ratio": 0.5,   # half of non-essential props missing
        "add_scatter": True,         # scattered debris
    },
    "cozy": {
        "saturation_scale": 1.15,
        "brightness_scale": 1.1,
        "placement_bias": "centered",  # props cluster to center
        "height_scale": 0.9,           # slightly lower ceiling feel
    },
    "grand": {
        "saturation_scale": 1.1,
        "brightness_scale": 1.15,
        "height_scale": 1.3,           # taller ceiling feel
        "prop_count_mult": 1.5,
    },
    "sterile": {
        "saturation_scale": 0.7,
        "brightness_scale": 1.2,
        "intact_prop_ratio": 1.0,
        "clutter_mult": 0.0,           # override clutter to zero
    },
    "airy": {
        "brightness_scale": 1.25,
        "height_scale": 1.15,
        "clutter_mult": 0.5,
    },
    "dark": {
        "brightness_scale": 0.4,
        "saturation_scale": 0.5,
    },
    "bright": {
        "brightness_scale": 1.4,
        "saturation_scale": 1.1,
    },
    "cluttered_feel": {
        "clutter_mult": 2.0,
        "placement_bias": "walls",
    },
    "minimal": {
        "clutter_mult": 0.0,
        "prop_count_mult": 0.5,
    },
    "ancient": {
        "saturation_scale": 0.5,
        "brightness_scale": 0.7,
        "intact_prop_ratio": 0.6,
    },
    "pristine": {
        "saturation_scale": 1.1,
        "brightness_scale": 1.15,
        "intact_prop_ratio": 1.0,
    },
    "haunted": {
        "saturation_scale": 0.3,
        "brightness_scale": 0.5,
        "add_scatter": True,
    },
    "lived_in": {
        "clutter_mult": 1.3,
        "placement_bias": "natural",
        "intact_prop_ratio": 0.9,
    },
}

# ── Room type → required asset categories ──────────────────────────

# Each room type maps to categories of assets that MUST be present.
# The engine picks from the asset pool for each category.
_REQUIRED_CATEGORIES: Dict[str, List[str]] = {
    "kitchen":      ["cooking_surface", "food_storage", "prep_surface", "lighting"],
    "living_room":  ["seating", "surface", "lighting"],
    "bedroom":      ["sleeping_surface", "storage", "lighting"],
    "bathroom":     ["wash_surface", "storage"],
    "study":        ["work_surface", "seating", "storage"],
    "hallway":      ["lighting"],
    "dining_room":  ["dining_surface", "seating", "lighting"],
    "office":       ["work_surface", "seating", "storage", "lighting"],
    "library":      ["work_surface", "seating", "storage", "storage"],
    "workshop":     ["work_surface", "seating", "storage", "lighting"],
    "cellar":       ["storage", "storage"],
    "attic":        ["storage", "storage"],
    "porch":        ["seating", "surface"],
    "pantry":       ["storage", "storage", "prep_surface"],
}

# ── Category → asset IDs mapping ───────────────────────────────────

_CATEGORY_TO_ASSETS: Dict[str, List[str]] = {
    "cooking_surface": ["stove"],
    "food_storage":    ["fridge"],
    "prep_surface":    ["counter"],
    "seating":         ["chair"],
    "surface":         ["table"],
    "dining_surface":  ["table"],
    "sleeping_surface":["table"],   # greybox: table = bed placeholder
    "work_surface":    ["table"],
    "storage":         ["cabinet", "shelf"],
    "wash_surface":    ["sink"],
    "lighting":        ["chair"],   # greybox: chair = light placeholder
}

# ── Legacy archetype catalog (backward compat) ──────────────────────

ROOM_ARCHETYPES: Dict[str, dict] = {
    "kitchen": {
        "label": "Kitchen",
        "pattern": "rectangle_room",
        "dimensions": {"width": 5.0, "height": 3.0, "depth": 5.0},
        "slot_fills": {
            "north_counter_center": "stove",
            "north_counter_left": "fridge",
            "north_counter_right": "counter",
            "center_table": "table",
        },
    },
    "living_room": {
        "label": "Living Room",
        "pattern": "rectangle_room",
        "dimensions": {"width": 6.0, "height": 3.0, "depth": 6.0},
        "slot_fills": {
            "center_table": "table",
            "chair_north": "chair",
            "chair_south": "chair",
            "east_storage": "shelf",
        },
    },
    "bedroom": {
        "label": "Bedroom",
        "pattern": "rectangle_room",
        "dimensions": {"width": 4.0, "height": 3.0, "depth": 4.0},
        "slot_fills": {
            "center_table": "table",
            "east_storage": "cabinet",
        },
    },
    "bathroom": {
        "label": "Bathroom",
        "pattern": "rectangle_room",
        "dimensions": {"width": 3.0, "height": 2.5, "depth": 3.0},
        "slot_fills": {
            "north_counter_center": "sink",
            "east_storage": "cabinet",
        },
    },
    "study": {
        "label": "Study / Office",
        "pattern": "rectangle_room",
        "dimensions": {"width": 4.0, "height": 3.0, "depth": 4.0},
        "slot_fills": {
            "center_table": "table",
            "east_storage": "shelf",
            "chair_south": "chair",
        },
    },
    "hallway": {
        "label": "Hallway",
        "pattern": "corridor",
        "dimensions": {"width": 2.0, "height": 3.0, "depth": 8.0},
        "slot_fills": {
            "north_mid_slot": "shelf",
            "south_mid_slot": "shelf",
        },
    },
    "dining_room": {
        "label": "Dining Room",
        "pattern": "rectangle_room",
        "dimensions": {"width": 5.0, "height": 3.0, "depth": 5.0},
        "slot_fills": {
            "center_table": "table",
            "chair_north": "chair",
            "chair_south": "chair",
            "chair_east": "chair",
            "chair_west": "chair",
        },
    },
    "office": {
        "label": "Office",
        "pattern": "rectangle_room",
        "dimensions": {"width": 4.0, "height": 2.8, "depth": 4.0},
        "slot_fills": {
            "center_table": "table",
            "chair_south": "chair",
            "east_storage": "shelf",
        },
    },
    "library": {
        "label": "Library",
        "pattern": "rectangle_room",
        "dimensions": {"width": 6.0, "height": 3.5, "depth": 6.0},
        "slot_fills": {
            "center_table": "table",
            "north_counter_left": "shelf",
            "north_counter_right": "shelf",
            "east_storage": "shelf",
            "chair_south": "chair",
        },
    },
    "workshop": {
        "label": "Workshop",
        "pattern": "rectangle_room",
        "dimensions": {"width": 5.0, "height": 3.0, "depth": 5.0},
        "slot_fills": {
            "center_table": "table",
            "north_counter_center": "counter",
            "east_storage": "cabinet",
            "chair_south": "chair",
        },
    },
    "cellar": {
        "label": "Cellar",
        "pattern": "rectangle_room",
        "dimensions": {"width": 4.0, "height": 2.2, "depth": 4.0},
        "slot_fills": {
            "east_storage": "cabinet",
            "north_counter_left": "shelf",
        },
    },
    "attic": {
        "label": "Attic",
        "pattern": "rectangle_room",
        "dimensions": {"width": 6.0, "height": 2.2, "depth": 5.0},
        "slot_fills": {
            "east_storage": "cabinet",
            "north_counter_left": "shelf",
            "north_counter_right": "shelf",
        },
    },
    "porch": {
        "label": "Porch / Veranda",
        "pattern": "rectangle_room",
        "dimensions": {"width": 6.0, "height": 2.8, "depth": 3.0},
        "slot_fills": {
            "center_table": "table",
            "east_storage": "shelf",
        },
    },
    "pantry": {
        "label": "Pantry",
        "pattern": "rectangle_room",
        "dimensions": {"width": 2.5, "height": 2.5, "depth": 2.5},
        "slot_fills": {
            "north_counter_center": "counter",
            "north_counter_left": "shelf",
            "north_counter_right": "shelf",
        },
    },
}

# ── Available room slots (for mapping categories to positions) ─────

_AVAILABLE_SLOTS: List[str] = [
    "north_counter_center", "north_counter_left", "north_counter_right",
    "center_table",
    "east_storage", "west_storage",
    "chair_north", "chair_south", "chair_east", "chair_west",
    "north_mid_slot", "south_mid_slot",
]

# ── Clutter prop categories ────────────────────────────────────────

_CLUTTER_SLOTS: List[str] = [
    "chair_north", "chair_south", "chair_east", "chair_west",
    "north_mid_slot", "south_mid_slot", "west_storage",
]

_CLUTTER_ASSETS: List[str] = ["chair", "shelf", "cabinet", "counter"]


# ── Helper Functions ────────────────────────────────────────────────

def _apply_color_mod(color: list, saturation_scale: float,
                     brightness_scale: float) -> list:
    """Modify an RGB colour by saturation and brightness factors."""
    r, g, b = color
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    s = min(1.0, max(0.0, s * saturation_scale))
    l = min(1.0, max(0.0, l * brightness_scale))
    r2, g2, b2 = colorsys.hls_to_rgb(h, l, s)
    return [round(r2, 3), round(g2, 3), round(b2, 3)]


def _pick_with_seed(items: list, seed: int, index: int = 0) -> Any:
    """Deterministic pick from a list given a seed and cycle index."""
    if not items:
        return None
    rng = random.Random(f"{seed}:{index}")
    return rng.choice(items)


def _shuffle_with_seed(items: list, seed: int) -> list:
    """Deterministic shuffle given a seed."""
    rng = random.Random(f"shuffle:{seed}")
    result = list(items)
    rng.shuffle(result)
    return result


# ── Engine ────────────────────────────────────────────────────────


class SSPEngine:
    """Semantic room compiler — resolves archetype or Intent Descriptor.

    Two input modes, detected automatically:

    **Legacy archetype** (``room_json`` has an ``"archetype"`` key):
        Looks up ``ROOM_ARCHETYPES``, merges overrides, delegates to
        ``SpatialCompiler.compile_layout()``.

    **Intent Descriptor** (``room_json`` has a ``"room_type"`` key):
        Resolves every field — size, style, clutter, mood, must_have,
        special_features, seed — into slot_fills + dimensions + colour
        modifiers, then delegates. Same brief + same seed = same room;
        different seed = different valid room.
    """

    def __init__(self, compiler: Any = None):
        """Create an SSP engine.

        Args:
            compiler: Existing SpatialCompiler instance. If None, rooms
                      produce empty plans (unit-test mode).
        """
        self._compiler = compiler

    # ── public API ────────────────────────────────────────────────

    def compile_room(
        self,
        room_json: dict,
        root_path: str = "/root/Main",
        origin: Tuple[float, float] = (0.0, 0.0),
        shell: bool = True,
    ) -> DevForgePlan:
        """Compile a room JSON into a DevForgePlan.

        Detects format automatically:
        - ``"archetype"`` key → legacy archetype path
        - ``"room_type"`` key → Intent Descriptor path

        Args:
            room_json: LLM output — either legacy archetype or Intent Descriptor.
            root_path: Godot node path to the room container.
            origin: World-space (x, z) offset for the room.
            shell: Whether to build floor/ceiling (False for BSP buildings).

        Returns:
            DevForgePlan with fully-furnished room steps.
        """
        if "archetype" in room_json:
            return self._compile_legacy(room_json, root_path, origin, shell)
        elif "room_type" in room_json:
            return self._compile_intent(room_json, root_path, origin, shell)
        else:
            # Neither key — fall back to kitchen via intent path
            logger.warn(
                "ssp",
                "No 'archetype' or 'room_type' in room_json; "
                "falling back to kitchen via intent path",
            )
            return self._compile_intent(
                {"room_type": "kitchen"}, root_path, origin, shell,
            )

    @property
    def archetype_ids(self) -> List[str]:
        """All registered room archetype IDs."""
        return sorted(ROOM_ARCHETYPES.keys())

    def archetype_summary_for_prompt(self) -> str:
        """One-line-per-archetype summary for the LLM prompt."""
        lines = []
        for aid in sorted(ROOM_ARCHETYPES.keys()):
            a = ROOM_ARCHETYPES[aid]
            defaults = a["slot_fills"]
            dims = a["dimensions"]
            slot_str = ", ".join(
                f"{slot}→{asset}"
                for slot, asset in sorted(defaults.items())
            )
            lines.append(
                f"  {aid}: {a['label']} — "
                f"{dims['width']:.0f}×{dims['height']:.0f}×{dims['depth']:.0f}m. "
                f"Default slots: {slot_str}"
            )
        return "\n".join(lines)

    # ── Legacy path (backward compat) ──────────────────────────────

    def _compile_legacy(
        self,
        room_json: dict,
        root_path: str,
        origin: Tuple[float, float],
        shell: bool,
    ) -> DevForgePlan:
        """Handle pre-Stage-4 archetype format."""
        archetype_id = room_json.get("archetype", "kitchen")
        preset = ROOM_ARCHETYPES.get(archetype_id)

        if preset is None:
            logger.warn(
                "ssp",
                f"Unknown archetype '{archetype_id}'; falling back to kitchen",
            )
            preset = ROOM_ARCHETYPES["kitchen"]

        slot_fills = {
            **preset["slot_fills"],
            **room_json.get("slot_overrides", {}),
        }
        dimensions = {
            **preset["dimensions"],
            **room_json.get("dimensions", {}),
        }
        pattern = room_json.get("pattern") or preset["pattern"]

        layout_json = {
            "pattern": pattern,
            "dimensions": dimensions,
            "slot_fills": slot_fills,
            "arcs_overrides": room_json.get("arcs_overrides", []),
        }

        return self._delegate_to_compiler(
            layout_json, root_path, origin, shell,
            f"SSP room: {archetype_id} (legacy)",
        )

    # ── Intent Descriptor path (Stage 4) ───────────────────────────

    def _compile_intent(
        self,
        descriptor: dict,
        root_path: str,
        origin: Tuple[float, float],
        shell: bool,
    ) -> DevForgePlan:
        """Resolve a full Intent Descriptor into slot_fills + modifiers.

        Resolution map (per STAGE-4-REBALANCE-PLAN.md §Move 3):
            room_type  → required asset categories → slot_fills
            size       → dimensions
            style      → colour palette
            clutter    → number of extra props
            mood_tags  → saturation/placement/intact modifiers
            must_have  → guaranteed assets (override pool defaults)
            special_features → known handled, unknown logged
            seed       → seeded RNG for variation
        """
        room_type = descriptor.get("room_type", "kitchen")
        seed = descriptor.get("seed", hash(room_type) & 0xFFFFFFFF)
        rng = random.Random(seed)

        # ── Step 1: required assets from room_type ──
        categories = _REQUIRED_CATEGORIES.get(room_type, ["surface", "seating"])
        slot_fills: Dict[str, str] = {}

        # Assign each required category to an available slot
        slots = list(_AVAILABLE_SLOTS)
        rng.shuffle(slots)

        cat_index = 0
        for cat in categories:
            asset_ids = _CATEGORY_TO_ASSETS.get(cat, ["table"])
            if cat_index < len(slots):
                chosen_asset = rng.choice(asset_ids)
                slot_fills[slots[cat_index]] = chosen_asset
                cat_index += 1

        # ── Step 2: size → dimensions ──
        size_key = descriptor.get("size", "normal")
        size_preset = _SIZE_PRESETS.get(size_key, _SIZE_PRESETS["normal"])
        dimensions = dict(size_preset)

        # ── Step 3: style → colour palette ──
        style_key = descriptor.get("style")
        palette = _STYLE_PALETTES.get(style_key, _DEFAULT_PALETTE) if style_key else _DEFAULT_PALETTE

        # ── Step 4: mood_tags → modifiers ──
        mood_tags = descriptor.get("mood_tags", [])
        saturation_scale = 1.0
        brightness_scale = 1.0
        height_scale = 1.0
        clutter_mult = 1.0
        prop_count_mult = 1.0
        intact_ratio = 1.0
        placement_bias: Optional[str] = None
        add_scatter = False

        for tag in mood_tags:
            if not isinstance(tag, str):
                continue
            tag_lower = tag.lower().strip()
            mod = _MOOD_MODIFIERS.get(tag_lower)
            if mod is None:
                logger.warn("ssp", f"Unknown mood tag '{tag}', skipping")
                continue
            saturation_scale *= mod.get("saturation_scale", 1.0)
            brightness_scale *= mod.get("brightness_scale", 1.0)
            height_scale *= mod.get("height_scale", 1.0)
            clutter_mult *= mod.get("clutter_mult", 1.0)
            prop_count_mult *= mod.get("prop_count_mult", 1.0)
            intact_ratio *= mod.get("intact_prop_ratio", 1.0)
            if "placement_bias" in mod:
                placement_bias = mod["placement_bias"]
            if mod.get("add_scatter", False):
                add_scatter = True

        # Apply mood height modifier to dimensions
        if height_scale != 1.0:
            dimensions["height"] *= height_scale

        # ── Step 5: clutter → extra props ──
        clutter = float(descriptor.get("clutter", 0.0))
        clutter = max(0.0, min(1.0, clutter)) * clutter_mult

        if clutter > 0.01:
            # Number of extra clutter props proportional to clutter
            max_clutter_slots = len(_CLUTTER_SLOTS)
            num_clutter = int(round(clutter * max_clutter_slots))
            # Scaling: apply prop_count_mult from moods
            num_clutter = int(round(num_clutter * prop_count_mult))

            used_slots = set(slot_fills.keys())
            available_clutter = [s for s in _CLUTTER_SLOTS if s not in used_slots]

            # Bias placement based on mood
            if placement_bias == "centered":
                # Prioritize center-adjacent slots
                center_slots = ["chair_north", "chair_south", "chair_east", "chair_west"]
                available_clutter = [s for s in available_clutter if s in center_slots] + \
                                    [s for s in available_clutter if s not in center_slots]
            elif placement_bias == "walls":
                # Prioritize wall-adjacent slots
                wall_slots = ["north_mid_slot", "south_mid_slot", "west_storage", "east_storage"]
                available_clutter = [s for s in available_clutter if s in wall_slots] + \
                                    [s for s in available_clutter if s not in wall_slots]

            rng.shuffle(available_clutter)
            for i in range(min(num_clutter, len(available_clutter))):
                slot_fills[available_clutter[i]] = rng.choice(_CLUTTER_ASSETS)

        # ── Step 6: must_have → forced assets ──
        must_have = descriptor.get("must_have", [])
        if must_have:
            # Find unused slots for must-have assets
            unused = [s for s in _AVAILABLE_SLOTS if s not in slot_fills]
            # Also consider replacing clutter slots for must-haves
            unused += [s for s in _CLUTTER_SLOTS if s in slot_fills]
            rng.shuffle(unused)

            for i, asset_id in enumerate(must_have):
                if i < len(unused):
                    slot_fills[unused[i]] = asset_id
                else:
                    logger.warn(
                        "ssp",
                        f"No available slot for must_have asset '{asset_id}'",
                    )

        # ── Step 7: special_features → known handled ──
        special_features = descriptor.get("special_features", [])
        arcs_overrides: List[dict] = []
        for feature in special_features:
            if not isinstance(feature, str):
                continue
            feature_lower = feature.lower().strip()
            if feature_lower in ("secret_passage", "hidden_door"):
                # Place a concealed shelf against a wall as the passage marker
                arcs_overrides.append({
                    "asset": "shelf",
                    "anchor": {"chain": ["floor", "north_wall", 0.3]},
                    "offset": [0, 0, 0],
                })
                logger.info("ssp", f"Special feature built: {feature}")
            elif feature_lower == "fireplace":
                arcs_overrides.append({
                    "asset": "cabinet",
                    "anchor": {"chain": ["floor", "north_wall", 0.0]},
                    "offset": [0, 0, 0],
                })
                logger.info("ssp", f"Special feature built: {feature}")
            else:
                logger.warn(
                    "ssp",
                    f"Unknown special feature '{feature}' — logged and skipped",
                )

        # ── Step 8: greybox colour application ──
        # Pick palette colours for each asset
        # (Colour is embedded in layout_json and applied by SpatialCompiler)
        palette_colors = list(palette.values())
        rng.shuffle(palette_colors)

        # Apply mood modifiers to palette colours
        modified_palette: Dict[str, list] = {}
        for color_name, color in palette.items():
            modified_palette[color_name] = _apply_color_mod(
                color, saturation_scale, brightness_scale,
            )

        # Build slot_colours from the modified palette
        slot_colours: Dict[str, list] = {}
        color_cycle = list(modified_palette.values())
        for i, slot in enumerate(slot_fills.keys()):
            if i < len(color_cycle):
                slot_colours[slot] = color_cycle[i]
            else:
                slot_colours[slot] = color_cycle[i % len(color_cycle)]

        # ── Intact prop removal (abandoned/haunted moods) ──
        if intact_ratio < 1.0:
            non_essential = [s for s in slot_fills if s in _CLUTTER_SLOTS]
            rng.shuffle(non_essential)
            remove_count = int(len(non_essential) * (1.0 - intact_ratio))
            for i in range(min(remove_count, len(non_essential))):
                slot = non_essential[i]
                del slot_fills[slot]
                if slot in slot_colours:
                    del slot_colours[slot]

        # ── Step 9: build layout_json ──
        pattern = room_type if room_type in ("hallway",) else "rectangle_room"
        if room_type == "hallway":
            pattern = "corridor"

        # Sort slot_fills so non-chain anchors are placed before chain-
        # dependent ones. Chain slots (chair_*) reference center_table via
        # { chain: ["center_table", ...] } and fail if the target hasn't
        # been placed yet. Processing non-chain slots first ensures
        # center_table is always placed before any chair_*.
        _CHAIN_SLOTS = {
            "chair_north", "chair_south", "chair_east", "chair_west",
            # l_shape_room.yaml chain slots (also depend on center_table)
            "chair_inner", "chair_outer",
        }
        ordered: Dict[str, str] = {}
        for s, a in slot_fills.items():
            if s not in _CHAIN_SLOTS:
                ordered[s] = a
        for s, a in slot_fills.items():
            if s in _CHAIN_SLOTS:
                ordered[s] = a
        slot_fills = ordered

        layout_json: Dict[str, Any] = {
            "pattern": pattern,
            "dimensions": dimensions,
            "slot_fills": slot_fills,
            "arcs_overrides": list(arcs_overrides),
            "slot_colours": slot_colours,
        }

        # ── Step 10: delegate ──
        label = (
            f"SSP room: {room_type} ({size_key}, {style_key or 'default'}, "
            f"clutter={clutter:.1f}, moods={mood_tags}, seed={seed})"
        )
        return self._delegate_to_compiler(
            layout_json, root_path, origin, shell, label,
        )

    # ── Shared delegation ──────────────────────────────────────────

    def _delegate_to_compiler(
        self,
        layout_json: dict,
        root_path: str,
        origin: Tuple[float, float],
        shell: bool,
        label: str,
    ) -> DevForgePlan:
        """Call the SpatialCompiler (or return empty plan in test mode)."""
        if self._compiler is not None:
            plan = self._compiler.compile_layout(
                layout_json,
                root_path=root_path,
                origin=origin,
                shell=shell,
            )
        else:
            plan = DevForgePlan(
                goal=label,
                steps=[],
            )

        dims = layout_json.get("dimensions", {})
        slots = len(layout_json.get("slot_fills", {}))
        logger.info(
            "ssp",
            f"Compiled {label}: "
            f"{dims.get('width', 0):.0f}×{dims.get('depth', 0):.0f}, "
            f"{slots} slots filled",
        )

        return plan
