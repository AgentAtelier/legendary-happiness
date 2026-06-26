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


def test_uv_seam_split_passes_gate(tmp_path):
    """A closed box whose seam vertices are duplicated (same positions, distinct
    vertex indices, i.e. a UV-seam split) must PASS the gate. The watertight
    check must be tolerant of vertex splitting caused by UV seams."""
    import numpy as np

    # Build a watertight box, then duplicate one vertex to simulate a UV seam.
    box = trimesh.creation.box(extents=[1.5, 0.75, 1.0])
    verts = box.vertices.copy()
    faces = box.faces.copy()

    n_verts = len(verts)
    # Duplicate vertex 0 at the exact same position.
    new_verts = np.vstack([verts, verts[0:1].copy()])
    # Remap one face reference from original vertex 0 → the duplicate,
    # so the duplicate appears in the topology but is geometrically the
    # same spot (simulating what Blender does at a UV seam).
    done = False
    for fi in range(len(faces)):
        if done:
            break
        for j in range(3):
            if faces[fi, j] == 0:
                faces[fi, j] = n_verts
                done = True
                break

    # Add UV data — the duplicate gets a different UV from the original.
    # Without this, merge_vertices merges by position trivially.
    # With different UV coords, the OLD gate would see distinct vertices
    # and reject the mesh.  The NEW gate builds a position-only topology
    # mesh first and therefore tolerates the split.
    uv = np.zeros((len(new_verts), 2), dtype=np.float32)
    uv[0] = [0.0, 0.0]       # original vertex 0
    uv[n_verts] = [0.5, 0.5]  # duplicate — different UV
    visual = trimesh.visual.TextureVisuals(uv=uv)
    seam_mesh = trimesh.Trimesh(vertices=new_verts, faces=faces, visual=visual)

    glb = _export(tmp_path, seam_mesh, "seam.glb")
    res = gate_asset(glb, FOOTPRINT, HEIGHT)
    assert res.passed, f"seam-split mesh should pass but got: {res.reasons}"
