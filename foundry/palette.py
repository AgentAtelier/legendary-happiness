"""foundry.palette — deterministic scene palette from theme anchors + harmony.

build_palette() expands a theme's anchor colors + mood into a harmonized set of
ROLE colors (base/shadow/midtone/highlight/accent/foliage/sky). Engine-agnostic;
the compiler maps material-classes onto these roles. Deterministic.
"""
from __future__ import annotations

import colorsys
import struct
import zlib
from pathlib import Path

# anchors = primary (+optional) RGB; mood = temperature / saturation / value-key.
THEME_ANCHORS: dict[str, dict] = {
    "stone_keep":     {"anchors": [(0.46, 0.45, 0.43)], "mood": {"temp": "cool", "saturation": 0.5, "key": "mid"}},
    "dusk_crypt":     {"anchors": [(0.30, 0.30, 0.34)], "mood": {"temp": "cool", "saturation": 0.5, "key": "dark"}},
    "sunlit_market":  {"anchors": [(0.62, 0.50, 0.34)], "mood": {"temp": "warm", "saturation": 0.7, "key": "bright"}},
    "*":              {"anchors": [(0.50, 0.48, 0.45)], "mood": {"temp": "neutral", "saturation": 0.5, "key": "mid"}},
}

_KEY_VALUE = {"dark": 0.42, "mid": 0.62, "bright": 0.82}


def build_palette(theme: str, seed: int = 0, anchors: dict | None = None) -> dict:
    spec = anchors or THEME_ANCHORS.get(theme, THEME_ANCHORS["*"])
    base_rgb = spec["anchors"][0]
    mood = spec["mood"]
    h, s, v = colorsys.rgb_to_hsv(*base_rgb)

    # seed perturbs hue slightly within the mood (bounded ±0.04)
    h = (h + ((seed * 0.6180339887) % 1.0 - 0.5) * 0.08) % 1.0
    key_v = _KEY_VALUE[mood["key"]]
    # Derive base saturation from the ANCHOR's own HSV — mood
    # scales value (key) and biases temperature, but does not
    # override saturation.  A desaturated grey anchor stays grey.

    def rgb(hue, sat, val):
        return tuple(round(c, 4) for c in colorsys.hsv_to_rgb(hue % 1.0, max(0, min(1, sat)), max(0, min(1, val))))

    warm = mood["temp"] == "warm"
    roles = {
        "base":      rgb(h, s, key_v),
        "shadow":    rgb(h, s * 0.85, key_v * 0.6),
        "midtone":   rgb(h, s, key_v * 0.82),
        "highlight": rgb(h, s * 0.9, min(1.0, key_v * 1.35)),
        "accent":    rgb(h + 0.45, min(1.0, s + 0.2), key_v * 1.05),
        "foliage":   rgb(0.28, 0.45, key_v * (0.9 if mood["key"] != "dark" else 0.7)),
        "sky":       rgb(0.07 if warm else 0.6, 0.35, min(1.0, key_v * (1.2 if mood["key"] != "dark" else 0.9))),
    }
    return {"roles": roles, "theme": theme, "seed": int(seed)}


# ── Palette class texture generation ──────────────────────────────
# The scene compiler emits ext_resource Texture2D references to
# res://assets/class_{cls}_albedo.png and class_{cls}_normal.png.
# generate_class_textures() writes minimal valid PNGs so Godot's
# scene loader doesn't fatally Parse Error on missing textures.

_NORMAL_FLAT = (128, 128, 255)  # RGBA flat normal (0.5, 0.5, 1.0)


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    chunk = chunk_type + data
    return (
        struct.pack(">I", len(data))
        + chunk
        + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
    )


def _make_solid_png_1x1(r: int, g: int, b: int) -> bytes:
    """Return the bytes of a valid 1×1 8-bit RGB PNG with no alpha."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr = _png_chunk(b"IHDR", ihdr_data)
    raw = b"\x00" + struct.pack("BBB", r, g, b)
    idat = _png_chunk(b"IDAT", zlib.compress(raw))
    iend = _png_chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def generate_class_textures(
    palette: dict,
    class_set: set,
    assets_dir: str,
) -> int:
    """Write per-class albedo + normal PNG textures into *assets_dir*.

    Albedo is a 1×1 solid fill of the palette role color scaled to
    0-255.  Normal is the flat (128,128,255) — a default tangent-
    space normal pointing straight up.

    Skips any file that already exists.  Returns the number of files
    written.

    Args:
        palette: The result dict from build_palette().
        class_set: Set of material class names ("stone", "wood", …).
        assets_dir: Path to the build's assets/ directory.
    """
    from material_classes import CLASSES
    roles = palette.get("roles", {})
    assets = Path(assets_dir)
    assets.mkdir(parents=True, exist_ok=True)
    written = 0

    for cls in sorted(class_set):
        ci = CLASSES.get(cls, CLASSES.get("stone", {}))
        role_name = ci.get("role", "base")
        role_rgb = roles.get(role_name, roles.get("base", (0.5, 0.5, 0.5)))
        # Scale 0..1 float → 0..255 int
        r = max(0, min(255, int(round(role_rgb[0] * 255))))
        g = max(0, min(255, int(round(role_rgb[1] * 255))))
        b = max(0, min(255, int(round(role_rgb[2] * 255))))

        # Albedo
        albedo_path = assets / f"class_{cls}_albedo.png"
        if not albedo_path.exists():
            albedo_path.write_bytes(_make_solid_png_1x1(r, g, b))
            written += 1

        # Normal (flat)
        normal_path = assets / f"class_{cls}_normal.png"
        if not normal_path.exists():
            normal_path.write_bytes(
                _make_solid_png_1x1(*_NORMAL_FLAT)
            )
            written += 1

    return written
