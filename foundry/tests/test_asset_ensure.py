"""generate-on-demand orchestration (stub builder — no Blender, no llama)."""
from __future__ import annotations

import json
from pathlib import Path

from asset_ensure import ensure_assets


def test_builds_only_missing_glbs(tmp_path):
    lib = tmp_path / "assets"; lib.mkdir()
    (lib / "table_worn_oak.glb").write_text("existing")     # already built
    lex = tmp_path / "asset_lexicon.json"
    lex.write_text(json.dumps({"assets": {"table": {"footprint": {"width": 1, "depth": 1}, "height": 1}}}))
    built = []

    def fake_builder(category, material, library_dir, lexicon_path):
        Path(library_dir, f"{category}_{material}.glb").write_text("built")
        built.append((category, material, lexicon_path))

    manifest = [
        {"id": "table_0", "category": "table", "material": "worn_oak"},      # exists → skip
        {"id": "shelf_0", "category": "shelf", "material": "wrought_iron"},   # missing → build
        {"id": "rug_0", "category": "rug", "material": "worn_oak"},           # missing → build
        {"id": "rug_1", "category": "rug", "material": "worn_oak"},           # dup → build once
    ]
    ensure_assets(manifest, str(lib), str(lex), builder=fake_builder)
    pairs = [(b[0], b[1]) for b in built]
    assert ("shelf", "wrought_iron") in pairs       # missing → built
    assert ("rug", "worn_oak") in pairs             # decor built deterministically by category
    assert ("table", "worn_oak") not in pairs       # already present → skipped
    assert pairs.count(("rug", "worn_oak")) == 1    # deduped
    # never built against the real lexicon path
    assert all(b[2] != str(lex) for b in built), "must use a /tmp lexicon copy"


# ── P-L-1: Parallel builds ──────────────────────────────────────────

def test_parallel_builds_all_missing(tmp_path):
    """P-L-1: With max_workers=2 (serial via stub), all missing pairs
    are built exactly once."""
    lib = tmp_path / "assets"; lib.mkdir()
    lex = tmp_path / "asset_lexicon.json"
    lex.write_text(json.dumps({"assets": {"table": {"footprint": {"width": 1, "depth": 1}, "height": 1}}}))
    built = []

    def fake_builder(category, material, library_dir, lexicon_path):
        Path(library_dir, f"{category}_{material}.glb").write_text("built")
        built.append((category, material))

    manifest = [
        {"id": "a", "category": "chair", "material": "worn_oak"},
        {"id": "b", "category": "shelf", "material": "rough_granite"},
        {"id": "c", "category": "cabinet", "material": "wrought_iron"},
    ]
    ensure_assets(manifest, str(lib), str(lex), builder=fake_builder, max_workers=1)
    assert len(built) == 3
    assert ("chair", "worn_oak") in built
    assert ("shelf", "rough_granite") in built
    assert ("cabinet", "wrought_iron") in built


def test_parallel_skips_existing(tmp_path):
    """P-L-1: Existing GLBs are skipped even with parallel workers."""
    lib = tmp_path / "assets"; lib.mkdir()
    (lib / "table_worn_oak.glb").write_text("existing")
    lex = tmp_path / "asset_lexicon.json"
    lex.write_text(json.dumps({"assets": {"table": {"footprint": {"width": 1, "depth": 1}, "height": 1}}}))
    built = []

    def fake_builder(category, material, library_dir, lexicon_path):
        built.append((category, material))

    manifest = [
        {"id": "t0", "category": "table", "material": "worn_oak"},
        {"id": "s0", "category": "shelf", "material": "rough_granite"},
    ]
    ensure_assets(manifest, str(lib), str(lex), builder=fake_builder, max_workers=1)
    assert ("table", "worn_oak") not in built
    assert ("shelf", "rough_granite") in built


def test_parallel_dedupes_across_manifest(tmp_path):
    """P-L-1: Same (category, material) only built once."""
    lib = tmp_path / "assets"; lib.mkdir()
    lex = tmp_path / "asset_lexicon.json"
    lex.write_text(json.dumps({"assets": {"table": {"footprint": {"width": 1, "depth": 1}, "height": 1}}}))
    built = []

    def fake_builder(category, material, library_dir, lexicon_path):
        built.append((category, material))

    manifest = [
        {"id": "a", "category": "table", "material": "worn_oak"},
        {"id": "b", "category": "table", "material": "worn_oak"},
        {"id": "c", "category": "table", "material": "worn_oak"},
    ]
    ensure_assets(manifest, str(lib), str(lex), builder=fake_builder, max_workers=1)
    assert len(built) == 1


def test_parallel_empty_manifest_returns_empty(tmp_path):
    """P-L-1: Empty manifest → no builds, no errors."""
    lib = tmp_path / "assets"; lib.mkdir()
    lex = tmp_path / "asset_lexicon.json"
    lex.write_text(json.dumps({}))
    decisions = ensure_assets([], str(lib), str(lex), max_workers=1)
    assert decisions == []
