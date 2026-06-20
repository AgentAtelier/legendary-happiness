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
