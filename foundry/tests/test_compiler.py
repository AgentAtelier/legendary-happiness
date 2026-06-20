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


# ── Slice 10: stone + metal materials ────────────────────────────

def test_rough_granite_compiles():
    """rough_granite is a valid material."""
    s = _spec(); s["material"] = "rough_granite"
    out = compile_spec(s)
    assert out["material"] == "rough_granite"


def test_wrought_iron_compiles():
    """wrought_iron is a valid material."""
    s = _spec(); s["material"] = "wrought_iron"
    out = compile_spec(s)
    assert out["material"] == "wrought_iron"


# ── Slice 10: shelf + cabinet generators ──────────────────────────

def _shelf_spec():
    return {
        "asset_id": "shelf",
        "generator": "shelf",
        "material": "worn_oak",
        "params": {
            "width": 1.0, "depth": 0.3, "height": 1.2,
            "board_thickness": 0.04, "n_shelves": 3, "side_thickness": 0.03,
        },
    }


def _cabinet_spec():
    return {
        "asset_id": "cabinet",
        "generator": "cabinet",
        "material": "worn_oak",
        "params": {
            "width": 0.8, "depth": 0.5, "height": 1.5,
            "panel_thickness": 0.04, "base_height": 0.08,
        },
    }


def test_shelf_is_valid_generator():
    out = compile_spec(_shelf_spec())
    assert out["generator"] == "shelf"
    assert out["params"]["width"] == 1.0
    assert out["params"]["n_shelves"] == 3.0


def test_cabinet_is_valid_generator():
    out = compile_spec(_cabinet_spec())
    assert out["generator"] == "cabinet"
    assert out["params"]["width"] == 0.8
    assert out["params"]["base_height"] == 0.08


def test_shelf_param_out_of_range_rejected():
    s = _shelf_spec(); s["params"]["width"] = 999.0
    with pytest.raises(SpecError):
        compile_spec(s)


def test_cabinet_missing_param_rejected():
    s = _cabinet_spec(); del s["params"]["panel_thickness"]
    with pytest.raises(SpecError):
        compile_spec(s)


def test_rug_spec_compiles():
    from compiler import compile_spec
    spec = {"asset_id": "rug", "generator": "rug", "material": "worn_oak",
            "age": 0.2, "params": {"width": 2.0, "depth": 1.4, "thickness": 0.02}}
    out = compile_spec(spec)
    assert out["generator"] == "rug" and out["params"]["thickness"] == 0.02


def test_painting_spec_compiles():
    from compiler import compile_spec
    spec = {"asset_id": "painting", "generator": "painting", "material": "worn_oak",
            "age": 0.2, "params": {"width": 0.6, "height": 0.8, "thickness": 0.05}}
    out = compile_spec(spec)
    assert out["generator"] == "painting" and out["params"]["height"] == 0.8
