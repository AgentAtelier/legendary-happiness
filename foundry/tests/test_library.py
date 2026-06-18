import json
import shutil
from pathlib import Path

import pytest

from library import LIVE_LEXICON, read_envelope, register_asset


@pytest.fixture
def lexicon_copy(tmp_path):
    dst = tmp_path / "asset_lexicon.json"
    shutil.copy(LIVE_LEXICON, dst)
    return str(dst)


def test_live_lexicon_exists():
    assert Path(LIVE_LEXICON).exists(), LIVE_LEXICON


def test_read_envelope_table(lexicon_copy):
    footprint, height = read_envelope(lexicon_copy, "table")
    assert footprint == {"width": 1.5, "depth": 1.0}
    assert height == 0.75


def test_register_writes_path(lexicon_copy):
    register_asset(lexicon_copy, "table", "res://assets/table.glb")
    data = json.loads(Path(lexicon_copy).read_text(encoding="utf-8"))
    assert data["assets"]["table"]["path"] == "res://assets/table.glb"


def test_register_unknown_asset_raises(lexicon_copy):
    with pytest.raises(KeyError):
        register_asset(lexicon_copy, "dragon", "res://assets/dragon.glb")
