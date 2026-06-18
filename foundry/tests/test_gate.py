import trimesh

from gate import gate_asset

FOOTPRINT = {"width": 1.5, "depth": 1.0}
HEIGHT = 0.75


def _export(tmp_path, mesh, name):
    p = tmp_path / name
    mesh.export(str(p))
    return str(p)


def test_well_formed_asset_passes(tmp_path):
    # extents map to (width=X, height=Y, depth=Z) per the GLB Y-up convention
    box = trimesh.creation.box(extents=[1.5, 0.75, 1.0])
    glb = _export(tmp_path, box, "good.glb")
    res = gate_asset(glb, FOOTPRINT, HEIGHT)
    assert res.passed, res.reasons


def test_oversized_asset_fails_bounds(tmp_path):
    box = trimesh.creation.box(extents=[3.0, 0.75, 1.0])  # too wide
    glb = _export(tmp_path, box, "wide.glb")
    res = gate_asset(glb, FOOTPRINT, HEIGHT)
    assert not res.passed
    assert any("width" in r for r in res.reasons)


def test_non_watertight_fails(tmp_path):
    box = trimesh.creation.box(extents=[1.5, 0.75, 1.0])
    holey = trimesh.Trimesh(vertices=box.vertices, faces=box.faces[:-2])
    glb = _export(tmp_path, holey, "holey.glb")
    res = gate_asset(glb, FOOTPRINT, HEIGHT)
    assert not res.passed
    assert any("watertight" in r for r in res.reasons)


def test_over_budget_fails(tmp_path):
    sphere = trimesh.creation.icosphere(subdivisions=4)  # ~5120 faces
    sphere.apply_scale([1.5, 0.75, 1.0])
    glb = _export(tmp_path, sphere, "dense.glb")
    res = gate_asset(glb, FOOTPRINT, HEIGHT, poly_budget=2000)
    assert not res.passed
    assert any("budget" in r for r in res.reasons)


def test_degenerate_fails(tmp_path):
    flat = trimesh.creation.box(extents=[1.5, 0.0001, 1.0])
    glb = _export(tmp_path, flat, "flat.glb")
    res = gate_asset(glb, FOOTPRINT, HEIGHT)
    assert not res.passed
    assert any("degenerate" in r for r in res.reasons)
