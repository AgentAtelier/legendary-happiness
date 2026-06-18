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
