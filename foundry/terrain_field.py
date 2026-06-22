"""foundry.terrain_field — deterministic procedural heightfield (exterior archetype).

A pure, seeded FBM value-noise heightfield. It is the SINGLE source of terrain
elevation, shared by:
  * the exterior planner (``height_at`` / ``slope_at`` placement queries), and
  * the Blender terrain builder (mesh vertex displacement),
so the two can never diverge (a flush building pad depends on exact parity).

Determinism is the contract: identical ``make_field`` args → identical heights,
byte-for-byte, with no RNG state or wall-clock. The noise uses an integer hash
(not ``random``/``sin``) so it is portable and stateless.

FBM is normalized to ``[-1, 1]`` before scaling, so a height is always within
``base_height ± amplitude`` — a guarantee the pad-flatten math relies on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    """An immutable terrain heightfield definition (cheap to pass around)."""
    extent: float          # scene is roughly [-extent/2, extent/2] in X and Z
    amplitude: float       # max vertical deviation from base_height (metres)
    base_frequency: float  # spatial frequency of the first octave
    octaves: int
    lacunarity: float      # frequency multiplier per octave
    persistence: float     # amplitude multiplier per octave
    base_height: float
    seed: int


def make_field(
    *,
    extent: float = 40.0,
    amplitude: float = 2.0,
    base_frequency: float = 0.05,
    octaves: int = 4,
    lacunarity: float = 2.0,
    persistence: float = 0.5,
    base_height: float = 0.0,
    seed: int = 0,
) -> Field:
    """Construct a terrain :class:`Field` from biome params + a seed."""
    return Field(
        extent=float(extent),
        amplitude=float(amplitude),
        base_frequency=float(base_frequency),
        octaves=max(1, int(octaves)),
        lacunarity=float(lacunarity),
        persistence=float(persistence),
        base_height=float(base_height),
        seed=int(seed),
    )


def height_at(field: Field, x: float, z: float) -> float:
    """Terrain elevation (Y) at world position ``(x, z)``.

    Returns ``base_height`` exactly when ``amplitude == 0`` (a flat field).
    """
    if field.amplitude == 0.0:
        return field.base_height
    return field.base_height + field.amplitude * _fbm(field, x, z)


def slope_at(field: Field, x: float, z: float, eps: float = 0.5) -> float:
    """Magnitude of the terrain gradient at ``(x, z)`` (central difference).

    Always non-negative; exactly 0.0 on a flat field. Used by the scatter
    masks to keep flora off steep slopes.
    """
    hx = (height_at(field, x + eps, z) - height_at(field, x - eps, z)) / (2.0 * eps)
    hz = (height_at(field, x, z + eps) - height_at(field, x, z - eps)) / (2.0 * eps)
    return math.hypot(hx, hz)


# ── Deterministic value noise (integer hash, no RNG/sin) ──────────

def _hash01(ix: int, iz: int, seed: int) -> float:
    """Stateless integer hash of a lattice point → float in ``[0, 1)``."""
    h = (ix * 374761393 + iz * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    h = (h ^ (h >> 16)) & 0xFFFFFFFF
    return h / 4294967296.0


def _value_noise(x: float, z: float, seed: int) -> float:
    """Smooth value noise at ``(x, z)`` in ``[0, 1)`` (bilinear + smoothstep)."""
    x0 = math.floor(x)
    z0 = math.floor(z)
    fx = x - x0
    fz = z - z0
    u = fx * fx * (3.0 - 2.0 * fx)
    v = fz * fz * (3.0 - 2.0 * fz)
    n00 = _hash01(x0, z0, seed)
    n10 = _hash01(x0 + 1, z0, seed)
    n01 = _hash01(x0, z0 + 1, seed)
    n11 = _hash01(x0 + 1, z0 + 1, seed)
    nx0 = n00 * (1.0 - u) + n10 * u
    nx1 = n01 * (1.0 - u) + n11 * u
    return nx0 * (1.0 - v) + nx1 * v


def _fbm(field: Field, x: float, z: float) -> float:
    """Fractal Brownian motion, normalized to ``[-1, 1]``."""
    freq = field.base_frequency
    amp = 1.0
    total = 0.0
    norm = 0.0
    for o in range(field.octaves):
        n = _value_noise(x * freq, z * freq, field.seed + o * 101)
        total += (2.0 * n - 1.0) * amp
        norm += amp
        amp *= field.persistence
        freq *= field.lacunarity
    return total / norm if norm > 0.0 else 0.0
