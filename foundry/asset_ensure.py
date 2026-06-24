"""Build any (category, material) GLB a manifest references that isn't yet in
the library. The category is already known, so we build it **deterministically**
(midpoint params → spec → Blender) rather than asking an LLM to re-derive the
generator from prose — that round-trip is lossy for the newer decor generators
(rug/painting). Never mutates the real lexicon — copies it to /tmp first.

P-L-1: Parallel builds using concurrent.futures.ProcessPoolExecutor.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import List

from decisions import Choice, DecisionPoint


def _forge_category(category: str, material: str, library_dir: str, lexicon_path: str):
    """Build one asset deterministically from its category (no LLM).

    Midpoint of each PARAM_RANGES entry is a known-good, in-envelope value.
    P-G: Paintings include painting_mode="blank" by default.
    """
    from compiler import PARAM_RANGES
    from runner import forge

    params = {k: (lo + hi) / 2.0 for k, (lo, hi) in PARAM_RANGES[category].items()}
    spec = {"asset_id": category, "generator": category,
            "material": material, "age": 0.2, "params": params}
    # P-G: paintings get a painting_mode for procedural canvas textures
    if category == "painting":
        spec["painting_mode"] = "blank"
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
    max_workers: int = 1,
) -> List[DecisionPoint]:
    """For each unique (category, material) in *manifest* with no GLB in
    *library_dir*, build it via *builder* (default: deterministic
    ``_forge_category``). Returns any Decision Points the builds emitted.

    P-L-1: Builds run in parallel across *max_workers* processes.
    Serial fallback when max_workers=1 (used in tests).
    """
    if builder is None:
        builder = _forge_category
    decisions: List[DecisionPoint] = []
    # /tmp copy of the lexicon — never mutate the real one.
    tmp_lex = Path(tempfile.mkdtemp()) / "asset_lexicon.json"
    shutil.copy(lexicon_path, tmp_lex)
    Path(library_dir).mkdir(parents=True, exist_ok=True)

    # Collect the missing (category, material) pairs.
    seen: set[tuple[str, str]] = set()
    to_build: list[tuple[str, str]] = []
    for e in manifest:
        cat, mat = e["category"], e["material"]
        if (cat, mat) in seen:
            continue
        seen.add((cat, mat))
        if (Path(library_dir) / f"{cat}_{mat}.glb").exists():
            continue
        to_build.append((cat, mat))

    if not to_build:
        return decisions

    # P-L-1: Parallel builds with bounded process pool.
    # Each forge() is independent — safe to run concurrently.
    if max_workers > 1:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(builder, cat, mat, library_dir, str(tmp_lex))
                : (cat, mat)
                for cat, mat in to_build
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result is not None and getattr(result, "decisions", None):
                        decisions.extend(result.decisions)
                except Exception:
                    cat, mat = futures[future]
                    decisions.append(DecisionPoint(
                        code="asset.builder_failed",
                        technical=f"Builder failed for {cat}_{mat}",
                        plain=f"Failed to build {cat} ({mat})",
                        stage="build",
                        severity="error",
                        context={"category": cat, "material": mat},
                        choices=[Choice(label="Retry",
                                        plain=f"Retry building {cat}_{mat}",
                                        apply={"retry": True})],
                    ))
    else:
        # Serial path for tests (ProcessPoolExecutor doesn't play well
        # with stub builders that aren't picklable).
        for cat, mat in to_build:
            result = builder(cat, mat, library_dir, str(tmp_lex))
            if result is not None and getattr(result, "decisions", None):
                decisions.extend(result.decisions)

    return decisions
