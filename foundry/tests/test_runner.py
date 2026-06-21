import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from decisions import DecisionPoint
from library import LIVE_LEXICON
from runner import forge, forge_from_request
from sidecar import validate_sidecar

BLENDER = shutil.which("blender")
SPEC = str(Path(__file__).resolve().parents[1] / "specs" / "table.json")

pytestmark = pytest.mark.skipif(BLENDER is None, reason="blender not installed")


def test_forge_table_end_to_end(tmp_path):
    lexicon = tmp_path / "asset_lexicon.json"
    shutil.copy(LIVE_LEXICON, lexicon)
    library_dir = tmp_path / "library"

    result = forge(SPEC, str(lexicon), str(library_dir))

    assert result.gate.passed, result.gate.reasons
    assert Path(result.glb_path).exists()
    assert result.glb_path.startswith(str(library_dir))
    assert result.registered

    import json
    data = json.loads(lexicon.read_text(encoding="utf-8"))
    assert data["assets"]["table"]["path"] == result.glb_path


def test_forge_names_by_material(tmp_path):
    """Forged output file and sidecar are named {asset_id}_{material}."""
    lexicon = tmp_path / "asset_lexicon.json"
    shutil.copy(LIVE_LEXICON, lexicon)
    library_dir = tmp_path / "library"

    result = forge(SPEC, str(lexicon), str(library_dir))

    assert result.gate.passed, result.gate.reasons

    glb_path = Path(result.glb_path)
    # File named by asset AND material
    assert glb_path.name == "table_worn_oak.glb"

    # Sidecar exists with same basename
    sidecar_path = glb_path.with_suffix(".sidecar.json")
    assert sidecar_path.exists()

    # Sidecar's asset_id is bare (not material-suffixed)
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["asset_id"] == "table"
    # Sidecar validates against the schema
    validate_sidecar(sidecar)


def test_forge_two_materials_no_overwrite(tmp_path):
    """Forging the same asset_id with two materials produces two distinct files."""
    lexicon = tmp_path / "asset_lexicon.json"
    shutil.copy(LIVE_LEXICON, lexicon)
    library_dir = tmp_path / "library"

    # First forge with worn_oak (the default spec)
    result1 = forge(SPEC, str(lexicon), str(library_dir))
    assert result1.gate.passed, result1.gate.reasons

    # Create a second spec with a different material
    spec_dw = {
        "asset_id": "table",
        "generator": "table",
        "material": "dark_walnut",
        "params": {
            "top_width": 1.5, "top_depth": 1.0, "top_thickness": 0.08,
            "leg_height": 0.67, "leg_radius": 0.06, "leg_inset": 0.1,
        },
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(spec_dw, f)
        spec_dw_path = f.name

    try:
        result2 = forge(spec_dw_path, str(lexicon), str(library_dir))
        assert result2.gate.passed, result2.gate.reasons

        # Both files exist on disk
        assert Path(library_dir, "table_worn_oak.glb").exists()
        assert Path(library_dir, "table_dark_walnut.glb").exists()
        # They are distinct paths (no overwrite)
        assert result1.glb_path != result2.glb_path
    finally:
        os.unlink(spec_dw_path)


# ── Slice 11: ForgeResult.decisions + sidecar threading ──────────────


def test_forge_emits_sidecar_without_decisions_key(tmp_path):
    """The explicit-spec forge() path: sidecar has NO 'decisions' key
    (resolver doesn't run; material is given)."""
    lexicon = tmp_path / "asset_lexicon.json"
    shutil.copy(LIVE_LEXICON, lexicon)
    library_dir = tmp_path / "library"

    result = forge(SPEC, str(lexicon), str(library_dir))
    assert result.gate.passed, result.gate.reasons
    assert result.decisions == []

    sidecar_path = Path(result.glb_path).with_suffix(".sidecar.json")
    assert sidecar_path.exists()
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert "decisions" not in sidecar, (
        "explicit-spec forge() should NOT emit a decisions key in sidecar"
    )
    validate_sidecar(sidecar)


def test_forge_from_request_writes_decisions_into_sidecar(tmp_path, monkeypatch):
    """forge_from_request: planner.plan() emits decisions → sidecar
    carries them under top-level 'decisions'."""
    import json as _json
    from material_resolver import resolve_material
    from sidecar import build_sidecar

    lexicon = tmp_path / "asset_lexicon.json"
    shutil.copy(LIVE_LEXICON, lexicon)
    library_dir = tmp_path / "library"

    # Avoid the heavyweight Blender build: replace _build with a stub that
    # writes a zero-byte .glb (gating will fail, but we only care about
    # the sidecar being written AND decisions reaching it).
    def _stub_build(spec_path, out_glb, blender):
        Path(out_glb).write_bytes(b"")

    from runner import _build as real_build
    monkeypatch.setattr("runner._build", _stub_build)
    # Stub gate_asset to always-fail so we don't depend on trimesh/blender.
    # NOTE: runner.py does `from gate import gate_asset`, so to override
    # the version actually called inside forge_from_request, patch
    # runner.gate_asset, not gate.gate_asset.
    from gate import GateResult
    monkeypatch.setattr(
        "runner.gate_asset",
        lambda *args, **kwargs: GateResult(passed=False, reasons=("stub:no_glb",)),
    )

    # Request 'wooden coffee table' → family_defaulted decision
    result = forge_from_request(
        "a wooden coffee table",
        str(lexicon),
        str(library_dir),
        llm=lambda prompt, grammar=None, json_schema=None, **kw: _json.dumps({
            "asset_id": "table",
            "generator": "table",
            # No material field — resolver drives it
            "params": {
                "top_width": 1.2, "top_depth": 0.7, "top_thickness": 0.06,
                "leg_height": 0.6, "leg_radius": 0.05, "leg_inset": 0.1,
            },
        }),
    )

    # Result carries the resolver's family_defaulted decision (material)
    # AND the age resolver's unspecified_defaulted (no wear word).
    assert any(d.code == "material.family_defaulted" for d in result.decisions), (
        f"expected material.family_defaulted in decisions, got {result.decisions}"
    )
    dp = next(d for d in result.decisions if d.code == "material.family_defaulted")
    assert dp.severity == "assumption"
    assert dp.stage == "planner"
    assert isinstance(dp, DecisionPoint)
    assert any(d.code == "age.unspecified_defaulted" for d in result.decisions)

    # Spec was driven by resolver (wood family default = worn_oak)
    assert result.glb_path.endswith("_worn_oak.glb"), (
        f"expected worn_oak (family default), got {result.glb_path}"
    )

    # Sidecar carries the decisions under top-level 'decisions'
    sidecar_path = Path(result.glb_path).with_suffix(".sidecar.json")
    assert sidecar_path.exists()
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert "decisions" in sidecar, (
        "forge_from_request sidecar must carry top-level 'decisions'"
    )
    assert len(sidecar["decisions"]) >= 1
    # Find the material.family_defaulted entry
    saved = next(d for d in sidecar["decisions"] if d["code"] == "material.family_defaulted")
    assert saved["context"]["family"] == "wood"
    assert saved["context"]["resolved"] == "worn_oak"
    assert isinstance(saved["choices"], list)
    assert len(saved["choices"]) == 2  # dark_walnut + weathered_pine
    choice_values = {c["apply"]["value"] for c in saved["choices"]}
    assert "dark_walnut" in choice_values
    assert "weathered_pine" in choice_values
    assert "worn_oak" not in choice_values

    # Sidecar still schema-valid
    validate_sidecar(sidecar)


def test_forge_from_request_specific_keyword_carries_no_decision(tmp_path, monkeypatch):
    """'wrought-iron cabinet' → specific match, no decision emitted, but
    sidecar carries nothing under 'decisions' (key omitted)."""
    import json as _json

    lexicon = tmp_path / "asset_lexicon.json"
    shutil.copy(LIVE_LEXICON, lexicon)
    library_dir = tmp_path / "library"

    def _stub_build(spec_path, out_glb, blender):
        Path(out_glb).write_bytes(b"")

    from gate import GateResult
    monkeypatch.setattr("runner._build", _stub_build)
    # Patch runner.gate_asset (not gate.gate_asset): runner.py did
    # `from gate import gate_asset`, so the runner module holds its own
    # binding that's the one called inside forge_from_request.
    monkeypatch.setattr(
        "runner.gate_asset",
        lambda *args, **kwargs: GateResult(passed=False, reasons=("stub:no_glb",)),
    )

    result = forge_from_request(
        "a wrought-iron storage cabinet",
        str(lexicon),
        str(library_dir),
        llm=lambda prompt, grammar=None, json_schema=None, **kw: _json.dumps({
            "asset_id": "cabinet",
            "generator": "cabinet",
            "params": {
                "width": 0.8, "depth": 0.5, "height": 1.5,
                "panel_thickness": 0.04, "base_height": 0.08,
            },
        }),
    )

    # Headline bug stays fixed: wrought_iron, not worn_oak
    # Material is confident, but age resolver adds unspecified_defaulted
    # ("wrought-iron storage cabinet" has no wear word).
    assert any(d.code == "age.unspecified_defaulted" for d in result.decisions)
    assert all(d.code != "material.family_defaulted" for d in result.decisions)
    assert result.glb_path.endswith("_wrought_iron.glb")

    sidecar_path = Path(result.glb_path).with_suffix(".sidecar.json")
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    # Decisions now exist (age.unspecified_defaulted); key is present
    assert "decisions" in sidecar
    assert len(sidecar["decisions"]) >= 1
