"""Tests for foundry.publish — deterministic, no live stack, no Godot needed."""
import json
import shutil
from pathlib import Path

import pytest

from library import LIVE_LEXICON
from publish import publish, _resolve_asset_id


# ── Helpers ──────────────────────────────────────────────────────────


@pytest.fixture
def lexicon_copy(tmp_path):
    """A copy of the real lexicon — never mutated in place."""
    dst = tmp_path / "asset_lexicon.json"
    shutil.copy(LIVE_LEXICON, dst)
    return str(dst)


def _make_glb(path: Path) -> None:
    """Create a tiny valid .glb using trimesh (no Blender needed)."""
    import trimesh
    box = trimesh.creation.box(extents=[0.1, 0.1, 0.1])
    box.export(str(path))


# ── Unit: _resolve_asset_id ─────────────────────────────────────────


def test_resolve_exact_match():
    ids = {"table", "chair", "fridge"}
    assert _resolve_asset_id("table", ids) == "table"
    assert _resolve_asset_id("chair", ids) == "chair"


def test_resolve_material_suffix_fallback():
    ids = {"table", "chair", "fridge"}
    assert _resolve_asset_id("table_dark_walnut", ids) == "table"
    assert _resolve_asset_id("chair_oak", ids) == "chair"


def test_resolve_unknown_stem_returns_none():
    ids = {"table", "chair", "fridge"}
    assert _resolve_asset_id("dragon", ids) is None
    assert _resolve_asset_id("dragon_red", ids) is None


def test_resolve_full_stem_with_underscore_takes_priority():
    """If the full stem is itself a lexicon id, use it directly."""
    ids = {"table", "table_dark", "chair"}
    assert _resolve_asset_id("table_dark", ids) == "table_dark"


# ── Integration: publish ─────────────────────────────────────────────


def test_publish_copies_glb_and_registers_path(tmp_path, lexicon_copy):
    """A matching .glb is copied and the lexicon path is set to res://."""
    lib_dir = tmp_path / "library"
    lib_dir.mkdir()
    _make_glb(lib_dir / "table.glb")

    project_dir = tmp_path / "my_project"
    project_dir.mkdir()

    result = publish(str(lib_dir), str(project_dir), lexicon_copy)

    assert len(result["published"]) == 1
    assert len(result["skipped"]) == 0
    entry = result["published"][0]
    assert entry["id"] == "table"
    assert entry["res_path"] == "res://assets/table.glb"
    assert Path(entry["dst"]).exists()
    assert Path(entry["dst"]).suffix == ".glb"

    # Lexicon entry updated
    data = json.loads(Path(lexicon_copy).read_text(encoding="utf-8"))
    assert data["assets"]["table"]["path"] == "res://assets/table.glb"


def test_unknown_stem_is_skipped(tmp_path, lexicon_copy):
    """A .glb whose stem can't resolve to a lexicon id is skipped."""
    lib_dir = tmp_path / "library"
    lib_dir.mkdir()
    _make_glb(lib_dir / "dragon.glb")

    project_dir = tmp_path / "my_project"
    project_dir.mkdir()

    result = publish(str(lib_dir), str(project_dir), lexicon_copy)

    assert len(result["published"]) == 0
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["file"] == "dragon.glb"
    assert "not in lexicon" in result["skipped"][0]["reason"]

    # Nothing copied
    assets = project_dir / "assets"
    assert not assets.exists() or not list(assets.glob("*.glb"))


def test_material_suffix_fallback_copies_and_registers(tmp_path, lexicon_copy):
    """A stem like 'table_dark_walnut' resolves to 'table' via fallback."""
    lib_dir = tmp_path / "library"
    lib_dir.mkdir()
    _make_glb(lib_dir / "table_dark_walnut.glb")

    project_dir = tmp_path / "my_project"
    project_dir.mkdir()

    result = publish(str(lib_dir), str(project_dir), lexicon_copy)

    assert len(result["published"]) == 1
    assert len(result["skipped"]) == 0
    entry = result["published"][0]
    assert entry["id"] == "table"
    assert entry["res_path"] == "res://assets/table.glb"

    data = json.loads(Path(lexicon_copy).read_text(encoding="utf-8"))
    assert data["assets"]["table"]["path"] == "res://assets/table.glb"


def test_res_path_format(tmp_path, lexicon_copy):
    """The res_path is exactly res://<assets_subdir>/<id>.glb."""
    lib_dir = tmp_path / "library"
    lib_dir.mkdir()
    _make_glb(lib_dir / "chair.glb")

    project_dir = tmp_path / "my_project"
    project_dir.mkdir()

    result = publish(str(lib_dir), str(project_dir), lexicon_copy)
    assert result["published"][0]["res_path"] == "res://assets/chair.glb"


def test_custom_assets_subdir(tmp_path, lexicon_copy):
    """Custom assets_subdir is reflected in dst and res_path."""
    lib_dir = tmp_path / "library"
    lib_dir.mkdir()
    _make_glb(lib_dir / "table.glb")

    project_dir = tmp_path / "my_project"
    project_dir.mkdir()

    result = publish(str(lib_dir), str(project_dir), lexicon_copy, assets_subdir="models")

    entry = result["published"][0]
    assert entry["res_path"] == "res://models/table.glb"
    assert "models" in str(entry["dst"])
    assert Path(entry["dst"]).exists()


def test_idempotent(tmp_path, lexicon_copy):
    """Running publish twice yields the same lexicon path (no corruption)."""
    lib_dir = tmp_path / "library"
    lib_dir.mkdir()
    _make_glb(lib_dir / "table.glb")

    project_dir = tmp_path / "my_project"
    project_dir.mkdir()

    # First run
    r1 = publish(str(lib_dir), str(project_dir), lexicon_copy)
    assert len(r1["published"]) == 1
    path_after_first = r1["published"][0]["res_path"]

    # Second run
    r2 = publish(str(lib_dir), str(project_dir), lexicon_copy)
    assert len(r2["published"]) == 1
    assert r2["published"][0]["res_path"] == path_after_first
    assert len(r2["skipped"]) == 0

    # Lexicon is intact
    data = json.loads(Path(lexicon_copy).read_text(encoding="utf-8"))
    assert data["assets"]["table"]["path"] == path_after_first


def test_mixed_published_and_skipped(tmp_path, lexicon_copy):
    """A directory with both matching and non-matching .glbs."""
    lib_dir = tmp_path / "library"
    lib_dir.mkdir()
    _make_glb(lib_dir / "table.glb")
    _make_glb(lib_dir / "dragon.glb")
    _make_glb(lib_dir / "chair.glb")
    _make_glb(lib_dir / "spaceship_red.glb")

    project_dir = tmp_path / "my_project"
    project_dir.mkdir()

    result = publish(str(lib_dir), str(project_dir), lexicon_copy)

    assert len(result["published"]) == 2
    assert len(result["skipped"]) == 2

    pub_ids = {e["id"] for e in result["published"]}
    assert pub_ids == {"table", "chair"}

    skip_files = {e["file"] for e in result["skipped"]}
    assert skip_files == {"dragon.glb", "spaceship_red.glb"}


def test_empty_library_dir(tmp_path, lexicon_copy):
    """An empty library dir publishes nothing without error."""
    lib_dir = tmp_path / "library"
    lib_dir.mkdir()

    project_dir = tmp_path / "my_project"
    project_dir.mkdir()

    result = publish(str(lib_dir), str(project_dir), lexicon_copy)
    assert result == {"published": [], "skipped": []}


def test_nonexistent_library_dir(lexicon_copy):
    """A non-existent library dir publishes nothing without error."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        project_dir = Path(td) / "proj"
        project_dir.mkdir()
        result = publish("/nonexistent/path", str(project_dir), lexicon_copy)
        assert result == {"published": [], "skipped": []}
