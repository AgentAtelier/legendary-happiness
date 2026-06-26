import json
import shutil
from pathlib import Path

import pytest
from library import (
    LIVE_LEXICON,
    read_envelope,
    register_asset,
    register_variant,
)


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


# ── Variant tests ───────────────────────────────────────────────

def test_register_variant_puts_path_under_variants(lexicon_copy):
    """register_variant sets variants[material_id] = path."""
    register_variant(lexicon_copy, "table", "dark_walnut",
                     "res://assets/table_dark_walnut.glb")
    data = json.loads(Path(lexicon_copy).read_text(encoding="utf-8"))
    assert data["assets"]["table"]["variants"]["dark_walnut"] == \
        "res://assets/table_dark_walnut.glb"


def test_register_variant_does_not_touch_other_entries(lexicon_copy):
    """register_variant only modifies the target asset entry."""
    register_variant(lexicon_copy, "table", "dark_walnut",
                     "res://assets/table_dark_walnut.glb")
    data = json.loads(Path(lexicon_copy).read_text(encoding="utf-8"))
    # chair should NOT have a variants dict
    assert "variants" not in data["assets"]["chair"]
    # table should have both the variant AND the original path untouched
    assert data["assets"]["table"].get("path", "") == ""
    assert data["assets"]["table"]["variants"]["dark_walnut"] == \
        "res://assets/table_dark_walnut.glb"


def test_register_variant_creates_variants_if_absent(lexicon_copy):
    """If the entry has no 'variants' key, register_variant creates one."""
    data_before = json.loads(Path(lexicon_copy).read_text(encoding="utf-8"))
    assert "variants" not in data_before["assets"]["table"]

    register_variant(lexicon_copy, "table", "default",
                     "res://assets/table.glb")
    data_after = json.loads(Path(lexicon_copy).read_text(encoding="utf-8"))
    assert "variants" in data_after["assets"]["table"]
    assert data_after["assets"]["table"]["variants"]["default"] == \
        "res://assets/table.glb"


def test_register_multiple_variants_no_collapse(lexicon_copy):
    """Registering two variants preserves both (no overwrite/collapse)."""
    register_variant(lexicon_copy, "table", "default",
                     "res://assets/table.glb")
    register_variant(lexicon_copy, "table", "dark_walnut",
                     "res://assets/table_dark_walnut.glb")
    data = json.loads(Path(lexicon_copy).read_text(encoding="utf-8"))
    variants = data["assets"]["table"]["variants"]
    assert len(variants) == 2
    assert variants["default"] == "res://assets/table.glb"
    assert variants["dark_walnut"] == "res://assets/table_dark_walnut.glb"


def test_register_variant_unknown_asset_raises(lexicon_copy):
    with pytest.raises(KeyError):
        register_variant(lexicon_copy, "spaceship", "default",
                         "res://assets/spaceship.glb")
