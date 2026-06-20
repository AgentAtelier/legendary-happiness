"""Build any (category, material) GLB a manifest references that isn't yet in
the library. The category is already known, so we build it **deterministically**
(midpoint params → spec → Blender) rather than asking an LLM to re-derive the
generator from prose — that round-trip is lossy for the newer decor generators
(rug/painting). Never mutates the real lexicon — copies it to /tmp first.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable, List

from decisions import DecisionPoint


def _forge_category(category: str, material: str, library_dir: str, lexicon_path: str):
    """Build one asset deterministically from its category (no LLM).

    Midpoint of each PARAM_RANGES entry is a known-good, in-envelope value.
    """
    from compiler import PARAM_RANGES
    from runner import forge

    params = {k: (lo + hi) / 2.0 for k, (lo, hi) in PARAM_RANGES[category].items()}
    spec = {"asset_id": category, "generator": category,
            "material": material, "age": 0.2, "params": params}
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(spec, f)
        spec_path = f.name
    try:
        return forge(spec_path, lexicon_path, library_dir)
    finally:
        os.unlink(spec_path)


def ensure_assets(
    manifest: List[dict],
    library_dir: str,
    lexicon_path: str,
    *,
    builder: Callable = None,
) -> List[DecisionPoint]:
    """For each unique (category, material) in *manifest* with no GLB in
    *library_dir*, build it via *builder* (default: deterministic
    ``_forge_category``). Returns any Decision Points the builds emitted.
    """
    if builder is None:
        builder = _forge_category
    decisions: List[DecisionPoint] = []
    # /tmp copy of the lexicon — never mutate the real one.
    tmp_lex = Path(tempfile.mkdtemp()) / "asset_lexicon.json"
    shutil.copy(lexicon_path, tmp_lex)
    Path(library_dir).mkdir(parents=True, exist_ok=True)

    seen: set[tuple[str, str]] = set()
    for e in manifest:
        cat, mat = e["category"], e["material"]
        if (cat, mat) in seen:
            continue
        seen.add((cat, mat))
        if (Path(library_dir) / f"{cat}_{mat}.glb").exists():
            continue
        result = builder(cat, mat, library_dir, str(tmp_lex))
        if result is not None and getattr(result, "decisions", None):
            decisions.extend(result.decisions)
    return decisions
