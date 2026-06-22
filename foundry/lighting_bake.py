"""foundry.lighting_bake — the baked-lighting orchestrator.

Content-addresses a scene's lighting bake, checks the cache, routes by tier, and
owns the fallback to realtime. The actual Blender Cycles bake is INJECTED as
``baker`` (the real one shells out to ``blender/bake_lighting.py``; tests pass a
stub) — so this loop is pure and fully testable without a GPU.

Tiers: 0 realtime (no bake), 1 fast vertex-color indirect bake, 2 full lightmap.
Any bake failure degrades to tier 0 so the scene always renders.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable, List, Optional

from hunyuan_postprocess import content_cache_key

# baker(scene_desc, out_dir) -> list[str] of artifact paths written under out_dir.
Baker = Callable[[dict, str], List[str]]

DEFAULT_ROOT = Path.home() / ".cache" / "forge"


def _placements_sig(placements: list) -> list:
    return [
        [p.get("glb"),
         [round(float(x), 4) for x in p.get("transform", [])],
         bool(p.get("static", True))]
        for p in placements
    ]


def bake_key(scene_desc: dict) -> str:
    """Stable content-address for a lighting bake (layout + sun + sky + tier + samples)."""
    payload = json.dumps(
        {
            "p": _placements_sig(scene_desc.get("placements", [])),
            "sun": scene_desc.get("sun"),
            "sky": scene_desc.get("sky"),
            "tier": scene_desc.get("tier"),
            "samples": scene_desc.get("samples"),
        },
        sort_keys=True,
    )
    return content_cache_key(proxy_hash=payload, seed=0, model_version="bake-1")


def _cache_dir(root: Path, key: str) -> Path:
    return root / "lighting" / key


def bake_scene(scene_desc: dict, *, baker: Baker,
               cache_root: Optional[str | Path] = None) -> dict:
    """Return ``{tier, status, artifacts}``.

    status ∈ {"realtime" (tier 0), "cached", "baked", "fallback"}.
    """
    tier = int(scene_desc.get("tier", 0))
    if tier == 0:
        return {"tier": 0, "status": "realtime", "artifacts": []}

    root = Path(cache_root) if cache_root else DEFAULT_ROOT
    key = bake_key(scene_desc)
    cache_dir = _cache_dir(root, key)
    if cache_dir.exists() and any(cache_dir.iterdir()):
        return {"tier": tier, "status": "cached",
                "artifacts": [str(p) for p in sorted(cache_dir.iterdir())]}

    tmp = root / "lighting" / f"{key}.tmp"
    try:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        artifacts = baker(scene_desc, str(tmp))
        cache_dir.mkdir(parents=True, exist_ok=True)
        out: List[str] = []
        for a in artifacts:
            dst = cache_dir / Path(a).name
            shutil.move(str(a), str(dst))
            out.append(str(dst))
        return {"tier": tier, "status": "baked", "artifacts": sorted(out)}
    except Exception:
        # Bake failed (HIP OOM, unwrap error, …) → realtime, scene still renders.
        return {"tier": 0, "status": "fallback", "artifacts": []}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
