"""Library/lexicon integration. The foundry reads the lexicon JSON directly (no
engine import) to get the placement envelope (the gate oracle), and writes an
accepted asset's path back into the entry. This is the seam the live pipeline
later reads — but instancing the asset into a live scene is a LATER slice."""

from __future__ import annotations

import json
from pathlib import Path

# Real lexicon: repo_root/engine/devforge/spatial/asset_lexicon.json
# This file is foundry/library.py → parents[1] is repo root.
LIVE_LEXICON = str(
    Path(__file__).resolve().parents[1]
    / "engine" / "devforge" / "spatial" / "asset_lexicon.json"
)


def read_envelope(lexicon_path: str, asset_id: str) -> tuple[dict, float]:
    data = json.loads(Path(lexicon_path).read_text(encoding="utf-8"))
    entry = data["assets"][asset_id]
    fp = entry["footprint"]
    return {"width": fp["width"], "depth": fp["depth"]}, float(entry["height"])


def register_asset(lexicon_path: str, asset_id: str, asset_path: str) -> None:
    path = Path(lexicon_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if asset_id not in data["assets"]:
        raise KeyError(f"asset_id {asset_id!r} not in lexicon")
    data["assets"][asset_id]["path"] = asset_path
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
