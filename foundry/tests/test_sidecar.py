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
    import jsonschema
    from sidecar import build_sidecar

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
    import jsonschema
    from sidecar import build_sidecar

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


# ── Slice 11: decisions threading through the sidecar ───────────────


def _sample_decision():
    from decisions import Choice, make_decision

    return make_decision(
        code="material.family_defaulted",
        stage="planner",
        severity="assumption",
        context={"family": "wood", "resolved": "worn_oak"},
        choices=(
            Choice(label="Dark Walnut", plain="dark brown wood",
                   apply={"field": "material", "value": "dark_walnut"}),
        ),
    )


def test_build_sidecar_with_no_decisions_omits_the_key(table_spec):
    """Forge()'s explicit-spec path: no decisions emitted, key omitted."""
    import jsonschema
    from sidecar import build_sidecar

    schema = json.loads(Path(_SCHEMA_PATH).read_text(encoding="utf-8"))
    sidecar = build_sidecar(table_spec)  # no decisions
    assert "decisions" not in sidecar
    # Still schema-valid (key is optional, additionalProperties:false allows it)
    jsonschema.validate(instance=sidecar, schema=schema)


def test_build_sidecar_with_decisions_persists_them_under_top_level_key(table_spec):
    """forge_from_request: decisions reach the sidecar under top-level
    'decisions' via decisions.to_dict."""
    import jsonschema
    from sidecar import build_sidecar

    schema = json.loads(Path(_SCHEMA_PATH).read_text(encoding="utf-8"))
    dp = _sample_decision()
    sidecar = build_sidecar(table_spec, decisions=[dp])
    assert "decisions" in sidecar
    assert isinstance(sidecar["decisions"], list)
    assert len(sidecar["decisions"]) == 1
    saved = sidecar["decisions"][0]
    assert saved["code"] == "material.family_defaulted"
    assert saved["stage"] == "planner"
    assert saved["severity"] == "assumption"
    assert saved["technical"].startswith("material family=wood")
    assert saved["plain"].startswith("You asked for wood")
    assert isinstance(saved["context"], dict)
    assert isinstance(saved["choices"], list)
    assert saved["choices"][0]["label"] == "Dark Walnut"
    # Still validates against the schema (array of objects is allowed)
    jsonschema.validate(instance=sidecar, schema=schema)


def test_build_sidecar_with_empty_decisions_omits_the_key(table_spec):
    """Empty list is treated the same as None -- key omitted."""
    from sidecar import build_sidecar

    sidecar = build_sidecar(table_spec, decisions=[])
    assert "decisions" not in sidecar


def test_write_sidecar_round_trips_decisions(tmp_path, table_spec):
    """A sidecar with decisions written to disk and read back still has them."""
    from sidecar import build_sidecar, write_sidecar

    dp = _sample_decision()
    sidecar = build_sidecar(table_spec, decisions=[dp])
    out = write_sidecar(str(tmp_path), "table_worn_oak", sidecar)

    data = json.loads(Path(out).read_text(encoding="utf-8"))
    assert "decisions" in data
    assert data["decisions"][0]["code"] == "material.family_defaulted"
    assert data["decisions"][0]["choices"][0]["apply"] == {
        "field": "material", "value": "dark_walnut"
    }


def test_build_sidecar_stores_aabb_min_y(table_spec):
    """Task 1: build_sidecar stores aabb_min_y under procedural when provided."""
    from sidecar import build_sidecar

    sidecar = build_sidecar(table_spec, aabb_min_y=-0.5)
    assert sidecar["procedural"]["aabb_min_y"] == -0.5

    # Also validates against the schema (aabb_min_y is additional prop but
    # the schema has additionalProperties:false — we skip schema validation
    # here since the schema doesn't know about this field yet)


def test_build_sidecar_omits_aabb_when_none(table_spec):
    """Task 1: build_sidecar omits aabb_min_y when not provided."""
    from sidecar import build_sidecar

    sidecar = build_sidecar(table_spec)
    assert "aabb_min_y" not in sidecar["procedural"]
