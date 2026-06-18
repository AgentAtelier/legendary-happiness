import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from library import LIVE_LEXICON
from runner import forge
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
