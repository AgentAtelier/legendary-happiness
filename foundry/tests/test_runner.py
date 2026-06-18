import shutil
from pathlib import Path

import pytest

from library import LIVE_LEXICON
from runner import forge

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
