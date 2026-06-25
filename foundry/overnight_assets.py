"""Unattended overnight asset generation — the art-director batch.

Phase A (this module, foundry venv, no GPU inference): for each curated medieval-
fantasy hero spec, build the procedural GLB, voxelize it into a Hunyuan proxy, and
render an appearance image, then enqueue a Hunyuan job. Resilient: a per-asset
failure is logged and skipped, never halts the batch.

Phase B (the spike's asset_server.py, run with --swap-llama): drains the queue on
the GPU overnight, post-processes, and caches.

    python overnight_assets.py prep            # build proxies+images, enqueue all
    python overnight_assets.py prep --limit 1  # just one (for the verify gate)

The Hunyuan cache/queue root is the standard ~/.cache/forge/hunyuan.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import traceback
from pathlib import Path

import hunyuan_queue as q
import proxy

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """0.9b: configure the root logger once at CLI entry."""
    logging.basicConfig(
        level=os.environ.get("FORGE_LOG_LEVEL", "INFO"),
        format="%(levelname)s:%(name)s:%(message)s",
    )

ROOT = Path(__file__).resolve().parent
BUILD = str(ROOT / "blender" / "build_asset.py")
WORK = Path.home() / ".cache" / "forge" / "overnight_work"

# ── Art direction: the curated hero set (category, material, params, target m) ──
# Sizes are real-world metres (post-bake scale-normalize envelope).
def _S(cat, mat, dims, **p):
    return {"category": cat, "material": mat, "params": p,
            "target_dims": list(dims)}

SPECS = [
    _S("barrel", "weathered_pine", (0.6, 0.9, 0.6), radius=0.3, height=0.9, staves=12),
    _S("barrel", "wrought_iron", (0.6, 0.9, 0.6), radius=0.3, height=0.9, staves=12),
    _S("chest", "worn_oak", (0.9, 0.6, 0.55), width=0.9, depth=0.55, height=0.6),
    _S("chest", "wrought_iron", (0.8, 0.55, 0.5), width=0.8, depth=0.5, height=0.55),
    _S("crate", "weathered_pine", (0.7, 0.7, 0.7), width=0.7, depth=0.7, height=0.7),
    _S("anvil", "wrought_iron", (0.7, 0.5, 0.3), width=0.7, depth=0.3, height=0.5),
    _S("cauldron", "wrought_iron", (0.7, 0.7, 0.7), width=0.7, depth=0.7, height=0.7),
    _S("pot", "ceramic", (0.4, 0.5, 0.4), width=0.4, depth=0.4, height=0.5),
    _S("lantern", "wrought_iron", (0.25, 0.5, 0.25), width=0.25, depth=0.25, height=0.5),
    _S("candle-stand", "wrought_iron", (0.3, 1.1, 0.3), width=0.3, depth=0.3, height=1.1),
    _S("torch-sconce", "wrought_iron", (0.3, 0.6, 0.25), width=0.3, depth=0.25, height=0.6),
    _S("weapon-rack", "worn_oak", (1.2, 1.4, 0.4), width=1.2, depth=0.4, height=1.4),
    _S("table", "worn_oak", (1.4, 0.78, 0.9), top_width=1.4, top_depth=0.9, leg_height=0.7),
    _S("chair", "worn_oak", (0.5, 0.95, 0.5), seat_width=0.46, seat_depth=0.46, back_height=0.5),
    _S("bench", "weathered_pine", (1.6, 0.5, 0.45), width=1.6, depth=0.45, height=0.5),
    _S("stool", "worn_oak", (0.4, 0.5, 0.4), width=0.4, depth=0.4, height=0.5),
    _S("shelf", "worn_oak", (1.0, 1.8, 0.4), width=1.0, depth=0.4, height=1.8),
    _S("cabinet", "worn_oak", (1.0, 1.6, 0.5), width=1.0, depth=0.5, height=1.6),
    _S("wardrobe", "worn_oak", (1.2, 2.0, 0.6), width=1.2, depth=0.6, height=2.0),
    _S("desk", "worn_oak", (1.3, 0.78, 0.7), width=1.3, depth=0.7, height=0.78),
    _S("lectern", "worn_oak", (0.6, 1.2, 0.5), width=0.6, depth=0.5, height=1.2),
    _S("cup", "ceramic", (0.1, 0.12, 0.1), width=0.1, depth=0.1, height=0.12),
    _S("bottle", "ceramic", (0.1, 0.3, 0.1), width=0.1, depth=0.1, height=0.3),
    _S("pillar", "rough_granite", (0.6, 3.0, 0.6), width=0.6, depth=0.6, height=3.0),
    _S("planter", "ceramic", (0.5, 0.5, 0.5), width=0.5, depth=0.5, height=0.5),
    _S("sack", "weathered_pine", (0.4, 0.6, 0.4), width=0.4, depth=0.4, height=0.6),
    _S("bedroll", "weathered_pine", (0.7, 0.3, 1.8), width=0.7, depth=1.8, height=0.3),
    _S("tapestry", "wrought_iron", (1.4, 2.0, 0.05), width=1.4, depth=0.05, height=2.0),
    _S("rock", "rough_granite", (1.2, 0.9, 1.2), radius=0.6, roughness=0.25, subdivisions=2),
    _S("tree", "weathered_pine", (3.0, 5.0, 3.0), trunk_height=1.2, foliage_height=3.5, tiers=4),
    _S("shrub", "worn_oak", (0.8, 0.7, 0.8), radius=0.4, lobes=5),
    _S("book", "leather", (0.22, 0.05, 0.16), width=0.22, depth=0.16, height=0.05),
    _S("scroll", "leather", (0.3, 0.08, 0.08), width=0.3, depth=0.08, height=0.08),
    _S("dagger", "wrought_iron", (0.08, 0.04, 0.3), width=0.08, depth=0.3, height=0.04),
    _S("humanoid", "rough_granite", (0.6, 1.9, 0.4), total_height=1.9, body_width=0.5),
    _S("painting", "worn_oak", (0.8, 1.0, 0.05), width=0.8, depth=0.05, height=1.0),
]


def _log(msg):
    logger.info(msg)


def _build_glb(spec, out_glb):
    asset_id = f"{spec['category']}_{spec['material']}"
    sp = {"asset_id": asset_id, "generator": spec["category"],
          "material": spec["material"], "params": spec["params"]}
    desc = WORK / f"{asset_id}.spec.json"
    desc.write_text(json.dumps(sp))
    r = subprocess.run(["blender", "-b", "--python", BUILD, "--", str(desc), out_glb],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not os.path.exists(out_glb):
        raise RuntimeError(f"GLB build failed: {(r.stderr or '')[-200:]}")


def _render_image(glb, out_png_dir):
    from visual.screenshot import capture_prop
    paths = capture_prop(glb, str(out_png_dir), angles=[0.7], radius=2.4, height=1.4)
    if not paths:
        raise RuntimeError("no render produced")
    return paths[0]


def prep_one(i: int) -> str:
    """Prep a single spec (build → proxy → image → enqueue). Run me in my OWN
    process: a hard crash (e.g. a trimesh containment segfault on a degenerate
    mesh) then loses only this asset, never the batch."""
    WORK.mkdir(parents=True, exist_ok=True)
    spec = SPECS[i]
    aid = f"{spec['category']}_{spec['material']}"
    glb = str(WORK / f"{aid}.glb")
    proxy_ply = str(WORK / f"{aid}.proxy.ply")
    _build_glb(spec, glb)
    proxy.voxelize_glb(glb, proxy_ply, resolution=64)
    img = _render_image(glb, WORK / f"{aid}_img")
    job = {"proxy_path": proxy_ply, "image": img,
           "category": spec["category"], "material": spec["material"],
           "target_dims": spec["target_dims"], "seed": 1234,
           "model_version": "omni-2.1", "priority": 100 + i}
    res = q.enqueue(job)
    _log(f"{i+1}/{len(SPECS)} {aid}: {res['status']}")
    return res["status"]


def prep(limit=0):
    """In-process prep of all specs (per-asset try/except). NOTE: a hard crash
    (segfault) bypasses this; the overnight runner uses one-process-per-asset."""
    n = limit or len(SPECS)
    for i in range(n):
        try:
            prep_one(i)
        except Exception as e:
            _log(f"{i+1}/{len(SPECS)}: SKIPPED — {e}")
            traceback.print_exc()
    _log(f"prep done: {len(q.pending_jobs())} pending")


if __name__ == "__main__":
    _configure_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prep", "one", "count"])
    ap.add_argument("index", nargs="?", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "count":
        print(len(SPECS))
    elif a.cmd == "one":
        prep_one(a.index)
    elif a.cmd == "prep":
        prep(limit=a.limit)
