"""Unit tests for foundry.terrain_field — deterministic heightfield (exterior archetype).

Pure, seeded FBM value-noise heightfield shared by the exterior planner (height
queries) and the Blender terrain builder (mesh displacement), so they never
diverge. Determinism is the contract: same (params, seed) → identical heights.
"""

from __future__ import annotations

import pytest
from terrain_field import height_at, make_field, slope_at


def test_height_is_deterministic_same_field():
    f = make_field(seed=7)
    assert height_at(f, 3.2, -1.5) == height_at(f, 3.2, -1.5)


def test_height_is_deterministic_across_fields_same_seed():
    f = make_field(seed=7)
    g = make_field(seed=7)
    for x, z in [(0.0, 0.0), (3.2, -1.5), (-9.0, 4.4)]:
        assert height_at(f, x, z) == height_at(g, x, z)


def test_height_varies_with_seed():
    f1 = make_field(seed=1)
    f2 = make_field(seed=2)
    samples = [(0.0, 0.0), (5.0, 5.0), (-3.0, 2.0), (10.0, -7.0)]
    assert any(height_at(f1, x, z) != height_at(f2, x, z) for x, z in samples)


def test_height_varies_spatially():
    f = make_field(seed=3, amplitude=2.0)
    vals = {round(height_at(f, float(x), 0.0), 5) for x in range(-10, 11)}
    assert len(vals) > 1  # not flat


def test_zero_amplitude_is_flat_at_base_height():
    f = make_field(seed=3, amplitude=0.0, base_height=1.5)
    assert height_at(f, 4.0, 9.0) == pytest.approx(1.5)
    assert height_at(f, -8.0, 2.0) == pytest.approx(1.5)


def test_slope_is_non_negative():
    f = make_field(seed=5)
    assert slope_at(f, 2.0, 2.0) >= 0.0


def test_flat_field_has_zero_slope():
    f = make_field(seed=5, amplitude=0.0)
    assert slope_at(f, 2.0, 2.0) == pytest.approx(0.0, abs=1e-9)


def test_field_exposes_extent():
    f = make_field(extent=40.0, seed=0)
    assert f.extent == 40.0


def test_amplitude_bounds_height_range():
    # FBM normalized to [-1, 1] before * amplitude → height stays within
    # base ± amplitude (a useful guarantee for the building pad math).
    amp = 3.0
    f = make_field(seed=11, amplitude=amp, base_height=0.0)
    for x in range(-20, 21, 2):
        for z in range(-20, 21, 2):
            h = height_at(f, float(x), float(z))
            assert -amp - 1e-6 <= h <= amp + 1e-6
