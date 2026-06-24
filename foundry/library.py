"""Library/lexicon integration. The foundry reads the lexicon JSON directly (no
engine import) to get the placement envelope (the gate oracle), and writes an
accepted asset's path back into the entry. This is the seam the live pipeline
later reads — but instancing the asset into a live scene is a LATER slice."""

from __future__ import annotations

import json
import re
from pathlib import Path

# Real lexicon: repo_root/engine/devforge/spatial/asset_lexicon.json
# This file is foundry/library.py → parents[1] is repo root.
LIVE_LEXICON = str(
    Path(__file__).resolve().parents[1]
    / "engine" / "devforge" / "spatial" / "asset_lexicon.json"
)


def read_envelope(lexicon_path: str, asset_id: str) -> tuple[dict, float]:
    data = json.loads(Path(lexicon_path).read_text(encoding="utf-8"))
    assets = data["assets"]
    if asset_id in assets:
        entry = assets[asset_id]
    else:
        # WS-3.2: fall back to base category name by stripping _NN suffix.
        # Also handles asset_ids where hyphens become underscores (e.g.
        # candle_stand_01 -> candle-stand).
        base_id = re.sub(r"_\d+$", "", asset_id)
        # Try hyphenated form (underscore -> hyphen) for categories like "candle-stand"
        hyphen_id = base_id.replace("_", "-")
        if hyphen_id != base_id and hyphen_id in assets:
            entry = assets[hyphen_id]
        elif base_id != asset_id and base_id in assets:
            entry = assets[base_id]
        else:
            raise KeyError(
                f"asset_id {asset_id!r} (base {base_id!r}) not in lexicon"
            ) from None
    fp = entry["footprint"]
    return {"width": fp["width"], "depth": fp["depth"]}, float(entry["height"])


def register_asset(lexicon_path: str, asset_id: str, asset_path: str) -> None:
    path = Path(lexicon_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if asset_id not in data["assets"]:
        raise KeyError(f"asset_id {asset_id!r} not in lexicon")
    data["assets"][asset_id]["path"] = asset_path
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def register_variant(
    lexicon_path: str, asset_id: str, material_id: str, asset_path: str
) -> None:
    """Register a material-variant path for *asset_id* in the lexicon.

    Sets ``lexicon["assets"][asset_id]["variants"][material_id] = asset_path``,
    creating the ``variants`` dict if absent.  The legacy ``path`` field is
    left untouched for back-compat.

    Raises ``KeyError`` if *asset_id* is not in the lexicon.
    """
    path = Path(lexicon_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if asset_id not in data["assets"]:
        raise KeyError(f"asset_id {asset_id!r} not in lexicon")
    entry = data["assets"][asset_id]
    if "variants" not in entry:
        entry["variants"] = {}
    entry["variants"][material_id] = asset_path
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
