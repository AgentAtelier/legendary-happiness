import json

import pytest

from compiler import SpecError, compile_spec, load_spec


def _spec():
    return {
        "asset_id": "table",
        "generator": "table",
        "material": "worn_oak",
        "params": {
            "top_width": 1.5, "top_depth": 1.0, "top_thickness": 0.08,
            "leg_height": 0.67, "leg_radius": 0.06, "leg_inset": 0.1,
        },
    }


def test_valid_spec_compiles():
    out = compile_spec(_spec())
    assert out["generator"] == "table"
    assert out["material"] == "worn_oak"
    assert out["params"]["top_width"] == 1.5


def test_unknown_generator_rejected():
    s = _spec(); s["generator"] = "spaceship"
    with pytest.raises(SpecError):
        compile_spec(s)


def test_unknown_material_rejected():
    s = _spec(); s["material"] = "neon_plasma"
    with pytest.raises(SpecError):
        compile_spec(s)


def test_param_out_of_range_rejected():
    s = _spec(); s["params"]["top_width"] = 10.0
    with pytest.raises(SpecError):
        compile_spec(s)


def test_missing_param_rejected():
    s = _spec(); del s["params"]["leg_height"]
    with pytest.raises(SpecError):
        compile_spec(s)


def test_load_spec_reads_file(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(_spec()), encoding="utf-8")
    assert load_spec(str(p))["asset_id"] == "table"


# ── Slice 6: material palette ─────────────────────────────────────

def test_worn_oak_compiles():
    s = _spec(); s["material"] = "worn_oak"
    out = compile_spec(s)
    assert out["material"] == "worn_oak"


def test_dark_walnut_compiles():
    s = _spec(); s["material"] = "dark_walnut"
    out = compile_spec(s)
    assert out["material"] == "dark_walnut"


def test_weathered_pine_compiles():
    s = _spec(); s["material"] = "weathered_pine"
    out = compile_spec(s)
    assert out["material"] == "weathered_pine"


def test_unknown_material_still_rejected():
    s = _spec(); s["material"] = "neon_plasma"
    with pytest.raises(SpecError):
        compile_spec(s)


# ── Slice 7: chair generator ──────────────────────────────────────

def _chair_spec():
    return {
        "asset_id": "chair",
        "generator": "chair",
        "material": "worn_oak",
        "params": {
            "seat_width": 0.5, "seat_depth": 0.5, "seat_thickness": 0.06,
            "leg_height": 0.45, "leg_radius": 0.04, "leg_inset": 0.05,
            "back_height": 0.35,
        },
    }


def test_chair_is_valid_generator():
    """'chair' is a known generator and a full spec validates."""
    out = compile_spec(_chair_spec())
    assert out["generator"] == "chair"
    assert out["material"] == "worn_oak"
    assert out["params"]["seat_width"] == 0.5


def test_chair_param_out_of_range_rejected():
    """An out-of-range chair param is rejected by compile_spec."""
    s = _chair_spec(); s["params"]["seat_width"] = 999.0
    with pytest.raises(SpecError):
        compile_spec(s)


def test_chair_missing_param_rejected():
    """A missing chair param is rejected."""
    s = _chair_spec(); del s["params"]["back_height"]
    with pytest.raises(SpecError):
        compile_spec(s)
