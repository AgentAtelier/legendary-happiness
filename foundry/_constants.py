"""foundry._constants — shared determinism anchors.

Centralises magic literals so every consumer imports the same value and
a single-line change propagates everywhere.  No other module should
define its own copy of these values.
"""

from __future__ import annotations

# Default seed used everywhere "a fixed, non-zero seed" is needed for
# deterministic output that varies enough to look intentional.  42 is
# the project convention (see AUDIT-02 D4).
DEFAULT_RNG_SEED: int = 42

# DirectionalLight3D transform basis for interior rooms (Godot Y-up,
# pleasant afternoon sun slant).  The full 12-element row-major basis
# used in scene_compiler._build_room_nodes.
_SUN_BASIS_INTERIOR_TUPLE: tuple[float, ...] = (
    0.866025, -0.433013, 0.25,   # X axis
    0.0,       0.5,      0.866025,  # Y axis
    -0.5,     -0.75,     0.433013,  # Z axis
)

# DirectionalLight3D transform basis for exterior scenes (plain string
# format used in exterior_compiler).  A fixed pleasant angle; biome
# sets the energy, not the direction.
SUN_BASIS_EXTERIOR: str = (
    "0.707107, -0.5, 0.5, 0, 0.707107, 0.707107, -0.707107, -0.5, 0.5"
)

# CLI arg default; no magic `42` bare literals elsewhere.
DEFAULT_LIGHTING_SEED: int = 0
