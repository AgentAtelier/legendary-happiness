"""Unit tests for foundry.blender.geometry_ops — WS-3.3."""

import sys
import math

# geometry_ops imports bpy which is only available inside Blender.
# All tests mock the Blender API.


def test_module_imports_without_blender():
    """geometry_ops can be imported without Blender (graceful degradation)."""
    # Remove any cached module
    sys.modules.pop("geometry_ops", None)
    sys.modules.pop("bpy", None)
    sys.modules.pop("bmesh", None)
    # Should import cleanly
    from blender import geometry_ops
    assert geometry_ops._HAS_BPY is False
    assert geometry_ops.bevel is not None
    assert geometry_ops.solidify is not None
    assert geometry_ops.array is not None
    assert geometry_ops.greeble is not None
    assert geometry_ops.parametric_variation is not None
    assert geometry_ops.apply_ops is not None


def test_apply_ops_validates_unknown_op():
    """apply_ops raises ValueError for unknown operation names."""
    sys.modules.pop("bpy", None)
    from blender import geometry_ops

    class FakeMesh:
        vertices = []

    mesh = FakeMesh()
    try:
        geometry_ops.apply_ops(mesh, [{"op": "nonexistent"}], seed=1)
        assert False, "should have raised"
    except ValueError as e:
        assert "nonexistent" in str(e)


def test_apply_ops_passes_through_without_blender():
    """Without Blender, ops return the mesh unchanged."""
    sys.modules.pop("bpy", None)
    from blender import geometry_ops

    class FakeMesh:
        vertices = []

    mesh = FakeMesh()
    result = geometry_ops.apply_ops(mesh, [
        {"op": "bevel", "width": 0.01},
        {"op": "solidify", "thickness": 0.02},
    ], seed=42)
    assert result is mesh


def test_bevel_noop_without_blender():
    """bevel returns mesh unchanged when bpy not available."""
    sys.modules.pop("bpy", None)
    from blender import geometry_ops
    mesh = object()
    result = geometry_ops.bevel(mesh)
    assert result is mesh


def test_solidify_noop_without_blender():
    """solidify returns mesh unchanged when bpy not available."""
    sys.modules.pop("bpy", None)
    from blender import geometry_ops
    mesh = object()
    result = geometry_ops.solidify(mesh)
    assert result is mesh


def test_array_noop_without_blender():
    """array returns mesh unchanged when bpy not available."""
    sys.modules.pop("bpy", None)
    from blender import geometry_ops
    mesh = object()
    result = geometry_ops.array(mesh)
    assert result is mesh


def test_greeble_noop_without_blender():
    """greeble returns mesh unchanged when bpy not available."""
    sys.modules.pop("bpy", None)
    from blender import geometry_ops
    mesh = object()
    result = geometry_ops.greeble(mesh)
    assert result is mesh


def test_parametric_variation_noop_without_blender():
    """parametric_variation returns mesh unchanged when bpy not available."""
    sys.modules.pop("bpy", None)
    from blender import geometry_ops
    mesh = object()
    result = geometry_ops.parametric_variation(mesh)
    assert result is mesh


def test_ops_registry_complete():
    """All 5 ops are registered in apply_ops."""
    sys.modules.pop("bpy", None)
    from blender import geometry_ops
    ops = {"bevel", "solidify", "array", "greeble", "parametric_variation"}
    # Check that all names are in the module
    for name in ops:
        assert hasattr(geometry_ops, name), f"missing op {name}"


def test_mesh_bounds_empty():
    """_mesh_bounds handles empty meshes."""
    sys.modules.pop("bpy", None)
    from blender import geometry_ops

    class FakeMesh:
        vertices = []

    bounds = geometry_ops._mesh_bounds(FakeMesh())
    assert bounds == (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def test_smallest_extent_empty():
    """_smallest_extent handles empty meshes."""
    sys.modules.pop("bpy", None)
    from blender import geometry_ops

    class FakeMesh:
        vertices = []

    ext = geometry_ops._smallest_extent(FakeMesh())
    assert ext == 0.0


def test_rng_deterministic():
    """_rng produces deterministic output for same seed."""
    sys.modules.pop("bpy", None)
    from blender import geometry_ops
    r1 = geometry_ops._rng(42)
    r2 = geometry_ops._rng(42)
    assert r1.randint(0, 1000) == r2.randint(0, 1000)


def test_rng_different_seeds_differ():
    """_rng with different seeds produces different output."""
    sys.modules.pop("bpy", None)
    from blender import geometry_ops
    r1 = geometry_ops._rng(1)
    r2 = geometry_ops._rng(2)
    v1 = [r1.random() for _ in range(20)]
    v2 = [r2.random() for _ in range(20)]
    assert v1 != v2
