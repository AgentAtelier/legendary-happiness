"""TDD tests for foundry.sidecar — build_sidecar validates against the real
asset-metadata schema (procedural branch)."""

import json
from pathlib import Path

import pytest

_PKG = str(Path(__file__).resolve().parents[1])
_SCHEMA_PATH = str(
    Path(__file__).resolve().parents[2]
    / "engine"
    / "devforge"
    / "governance"
    / "schemas"
    / "asset_metadata_sidecar_schema.json"
)


@pytest.fixture
def table_spec():
    return {
        "asset_id": "table",
        "generator": "table",
        "material": "worn_oak",
        "params": {
            "top_width": 1.5,
            "top_depth": 1.0,
            "top_thickness": 0.08,
            "leg_height": 0.67,
            "leg_radius": 0.06,
            "leg_inset": 0.1,
        },
    }


def test_build_sidecar_validates_against_real_schema(table_spec):
    """build_sidecar for a table spec passes validation with jsonschema
    using the real engine-side schema file."""
    from sidecar import build_sidecar

    import jsonschema

    schema = json.loads(Path(_SCHEMA_PATH).read_text(encoding="utf-8"))
    sidecar = build_sidecar(table_spec)
    jsonschema.validate(instance=sidecar, schema=schema)  # raises on failure


def test_geometry_template_id_matches_generator(table_spec):
    """The procedural.geometry_template_id equals the spec's generator."""
    from sidecar import build_sidecar

    sidecar = build_sidecar(table_spec)
    assert sidecar["procedural"]["geometry_template_id"] == "table"


def test_pipeline_type_is_procedural(table_spec):
    """The pipeline_type is always 'procedural' for foundry assets."""
    from sidecar import build_sidecar

    sidecar = build_sidecar(table_spec)
    assert sidecar["pipeline_type"] == "procedural"


def test_sidecar_has_required_top_level_keys(table_spec):
    from sidecar import build_sidecar

    sidecar = build_sidecar(table_spec)
    for key in ("asset_id", "pipeline_type", "creation_date", "style_version"):
        assert key in sidecar, f"Missing required key: {key}"


def test_write_sidecar_writes_file_and_returns_path(tmp_path):
    from sidecar import build_sidecar, write_sidecar

    spec = {"asset_id": "test_asset", "generator": "table"}
    sidecar = build_sidecar(spec)
    out = write_sidecar(str(tmp_path), "test_asset", sidecar)

    expected = tmp_path / "test_asset.sidecar.json"
    assert out == str(expected)
    assert expected.exists()
    data = json.loads(expected.read_text(encoding="utf-8"))
    assert data["asset_id"] == "test_asset"


def test_build_sidecar_has_procedural_required_keys(table_spec):
    from sidecar import build_sidecar

    sidecar = build_sidecar(table_spec)
    proc = sidecar["procedural"]
    for key in (
        "geometry_template_id", "seed", "export_parameters",
        "lod_configuration", "collision_type", "biome_tags",
    ):
        assert key in proc, f"Missing required procedural key: {key}"


def test_chair_spec_sidecar_validates():
    """A chair spec sidecar also validates."""
    from sidecar import build_sidecar

    import jsonschema

    schema = json.loads(Path(_SCHEMA_PATH).read_text(encoding="utf-8"))
    spec = {
        "asset_id": "chair",
        "generator": "chair",
        "material": "dark_walnut",
        "params": {
            "seat_width": 0.5, "seat_depth": 0.5, "seat_thickness": 0.06,
            "leg_height": 0.45, "leg_radius": 0.04, "leg_inset": 0.05,
            "back_height": 0.35,
        },
    }
    sidecar = build_sidecar(spec)
    jsonschema.validate(instance=sidecar, schema=schema)
    assert sidecar["procedural"]["geometry_template_id"] == "chair"
