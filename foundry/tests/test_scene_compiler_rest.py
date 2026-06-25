from placement import read_asset_aabb_min_y
from scene_compiler import rest_offset


def test_rest_offset_centered_origin():
    # GLB whose origin is at its center, half-height 0.5 -> min_y = -0.5
    assert rest_offset(-0.5) == 0.5


def test_rest_offset_base_origin():
    # GLB already authored with base at origin -> min_y = 0 -> no shift
    assert rest_offset(0.0) == 0.0


def test_read_asset_aabb_from_json(tmp_path):
    """Task 1: read_asset_aabb_min_y reads .aabb.json when present."""
    import json
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "table_worn_oak.aabb.json").write_text(
        json.dumps({"aabb_min_y": -0.45})
    )
    result = read_asset_aabb_min_y(str(assets), "table", "worn_oak")
    assert result == -0.45


def test_read_asset_aabb_from_sidecar(tmp_path):
    """Task 1: read_asset_aabb_min_y reads from sidecar when .aabb.json absent."""
    import json
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "table_worn_oak.sidecar.json").write_text(
        json.dumps({
            "asset_id": "table",
            "procedural": {"aabb_min_y": -0.38},
        })
    )
    result = read_asset_aabb_min_y(str(assets), "table", "worn_oak")
    assert result == -0.38


def test_read_asset_aabb_returns_none_when_missing(tmp_path):
    """Task 1: read_asset_aabb_min_y returns None when no data files exist."""
    assets = tmp_path / "assets"
    assets.mkdir()
    result = read_asset_aabb_min_y(str(assets), "table", "worn_oak")
    assert result is None
