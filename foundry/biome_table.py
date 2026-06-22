"""foundry.biome_table — static exterior biome data + resolver.

The exterior counterpart to ``room_control.THEME_TABLE``: pure data describing
each biome's terrain shape, ground materials, flora mix, and atmosphere. The LLM
interpreter picks a ``base_biome`` tag (an enum); ``resolve_biome`` maps it to a
row, falling back to the generic ``"*"`` biome for anything unknown. The
biome-recipe layer (``biome_recipe.py``) may then perturb the flora mix /
density within this row's safe envelope.

Ground material tags here (grass/snow/sand/dirt/rock/moss) are EXTERIOR ground
materials; the Blender terrain-material slice registers them in MATERIAL_PALETTE.

Each row:
    biome             str
    terrain           {amplitude, base_frequency, octaves, lacunarity, persistence}
    ground_materials  tuple[str, ...]
    flora_set         tuple[{category: 'tree'|'shrub'|'rock', weight, density}]
                      density = target instances per square metre
    atmosphere        {fog_color (r,g,b), fog_density, sun_energy, sky_tint (r,g,b)}
"""

from __future__ import annotations

from typing import Tuple


BIOME_TABLE: list[dict] = [
    {
        "biome": "snow_forest",
        "terrain": {"amplitude": 1.6, "base_frequency": 0.045, "octaves": 4,
                    "lacunarity": 2.0, "persistence": 0.5},
        "ground_materials": ("snow", "rock"),
        "flora_set": (
            {"category": "tree", "weight": 0.7, "density": 0.05},
            {"category": "rock", "weight": 0.2, "density": 0.02},
            {"category": "shrub", "weight": 0.1, "density": 0.03},
        ),
        "atmosphere": {"fog_color": (0.78, 0.82, 0.88), "fog_density": 0.020,
                       "sun_energy": 0.7, "sky_tint": (0.7, 0.78, 0.9)},
    },
    {
        "biome": "temperate_forest",
        "terrain": {"amplitude": 2.2, "base_frequency": 0.05, "octaves": 5,
                    "lacunarity": 2.0, "persistence": 0.5},
        "ground_materials": ("grass", "dirt"),
        "flora_set": (
            {"category": "tree", "weight": 0.6, "density": 0.07},
            {"category": "shrub", "weight": 0.3, "density": 0.06},
            {"category": "rock", "weight": 0.1, "density": 0.01},
        ),
        "atmosphere": {"fog_color": (0.6, 0.68, 0.6), "fog_density": 0.012,
                       "sun_energy": 1.1, "sky_tint": (0.6, 0.72, 0.85)},
    },
    {
        "biome": "meadow",
        "terrain": {"amplitude": 0.9, "base_frequency": 0.04, "octaves": 3,
                    "lacunarity": 2.0, "persistence": 0.5},
        "ground_materials": ("grass", "dirt"),
        "flora_set": (
            {"category": "shrub", "weight": 0.6, "density": 0.05},
            {"category": "tree", "weight": 0.3, "density": 0.015},
            {"category": "rock", "weight": 0.1, "density": 0.01},
        ),
        "atmosphere": {"fog_color": (0.7, 0.78, 0.7), "fog_density": 0.008,
                       "sun_energy": 1.3, "sky_tint": (0.62, 0.75, 0.9)},
    },
    {
        "biome": "desert",
        "terrain": {"amplitude": 2.8, "base_frequency": 0.03, "octaves": 3,
                    "lacunarity": 2.1, "persistence": 0.55},
        "ground_materials": ("sand", "rock"),
        "flora_set": (
            {"category": "rock", "weight": 0.7, "density": 0.02},
            {"category": "shrub", "weight": 0.3, "density": 0.008},
        ),
        "atmosphere": {"fog_color": (0.85, 0.78, 0.62), "fog_density": 0.006,
                       "sun_energy": 1.5, "sky_tint": (0.8, 0.8, 0.78)},
    },
    {
        "biome": "swamp",
        "terrain": {"amplitude": 0.7, "base_frequency": 0.055, "octaves": 4,
                    "lacunarity": 2.0, "persistence": 0.55},
        "ground_materials": ("moss", "dirt"),
        "flora_set": (
            {"category": "tree", "weight": 0.5, "density": 0.06},
            {"category": "shrub", "weight": 0.4, "density": 0.08},
            {"category": "rock", "weight": 0.1, "density": 0.01},
        ),
        "atmosphere": {"fog_color": (0.5, 0.55, 0.48), "fog_density": 0.030,
                       "sun_energy": 0.6, "sky_tint": (0.5, 0.58, 0.55)},
    },
    {
        "biome": "rocky",
        "terrain": {"amplitude": 3.2, "base_frequency": 0.045, "octaves": 4,
                    "lacunarity": 2.2, "persistence": 0.5},
        "ground_materials": ("rock", "dirt"),
        "flora_set": (
            {"category": "rock", "weight": 0.8, "density": 0.04},
            {"category": "shrub", "weight": 0.2, "density": 0.015},
        ),
        "atmosphere": {"fog_color": (0.62, 0.62, 0.66), "fog_density": 0.010,
                       "sun_energy": 1.0, "sky_tint": (0.6, 0.66, 0.74)},
    },
    {
        # Generic grassland — the fallback for any unknown/missing biome.
        "biome": "*",
        "terrain": {"amplitude": 1.2, "base_frequency": 0.045, "octaves": 4,
                    "lacunarity": 2.0, "persistence": 0.5},
        "ground_materials": ("grass", "dirt"),
        "flora_set": (
            {"category": "tree", "weight": 0.4, "density": 0.03},
            {"category": "shrub", "weight": 0.4, "density": 0.04},
            {"category": "rock", "weight": 0.2, "density": 0.015},
        ),
        "atmosphere": {"fog_color": (0.66, 0.72, 0.7), "fog_density": 0.010,
                       "sun_energy": 1.1, "sky_tint": (0.62, 0.74, 0.88)},
    },
]

BIOMES: Tuple[str, ...] = tuple(r["biome"] for r in BIOME_TABLE)

_BY_TAG = {r["biome"]: r for r in BIOME_TABLE}
_GENERIC = _BY_TAG["*"]


def resolve_biome(biome_tag: str) -> dict:
    """Return the BIOME_TABLE row for *biome_tag*, or the generic '*' row.

    Exact tag match only — free-text → tag inference is the interpreter's job
    (the LLM picks the enum). Unknown/empty → the generic grassland fallback.
    """
    if not biome_tag:
        return _GENERIC
    return _BY_TAG.get(biome_tag.strip().lower(), _GENERIC)
