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
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from decisions import make_decision
from hunyuan_postprocess import content_cache_key

# baker(scene_desc, out_dir) -> list[str] of artifact paths written under out_dir.
Baker = Callable[[dict, str], list[str]]

DEFAULT_ROOT = Path.home() / ".cache" / "forge"


def _placements_sig(placements: list) -> list:
    return [
        [p.get("glb"),
         [round(float(x), 4) for x in p.get("transform", [])],
         bool(p.get("static", True))]
        for p in placements
    ]


# ═══════════════════════════════════════════════════════════════════
#  Phase 1.2: Canonical bake contract builder
# ═══════════════════════════════════════════════════════════════════

def build_scene_desc(
    lighting_plan: dict,
    placements: list,
    tier: int,
    samples: int,
) -> dict:
    """Build the canonical scene_desc dict from a lighting plan.

    This is the ONE place that builds the bake contract.  All three
    call sites (scene_compiler, exterior_compiler, scaffold) feed
    through here.

    C2 (Phase 0.2): interior-light pos is swizzled from Godot-Y-up to
    Blender-Z-up at the bake boundary — this remap lives ONLY here.
    The realtime rig path keeps Y-up; the bake path feeds Blender's
    Z-up scene.  Without it Cycles buries emitters under the floor.

    The sky dict is the SUPERSET: horizon is always present (defaults
    to fog_color from environment if not explicitly set in sky).
    """
    sun = lighting_plan.get("sun", {})
    sky = dict(lighting_plan.get("sky", {}))

    # Superset: ensure horizon is present in the sky payload.
    # The exterior path sets it explicitly; the interior path may not.
    if "horizon" not in sky:
        env = lighting_plan.get("environment", {})
        sky["horizon"] = list(env.get("fog_color", [0.5, 0.5, 0.5]))

    _interior_lights: list[dict] = []
    for src in lighting_plan.get("sources", []) or []:
        _p = src.get("pos", (0, 0, 0))
        # Bake boundary: Godot-Y-up → Blender-Z-up, (x, z, y).
        _swizzled = dict(src)
        _swizzled["pos"] = (_p[0], _p[2], _p[1])
        _interior_lights.append(_swizzled)

    return {
        "tier": int(tier), "samples": int(samples),
        "placements": placements,
        "sun": sun, "sky": sky,
        "interior_lights": _interior_lights,
    }


def bake_and_apply(scene_desc: dict, build_dir: str, *,
                   baker: Baker | None = None,
                   cache_root: str | Path | None = None) -> dict:
    """Run the lighting bake for *scene_desc* and (tier≥1) apply artifacts.

    Tier 0 short-circuits — no bake, no side effects.  Tier ≥1 calls
    ``bake_scene`` with the provided *baker* (or a stub).

    *baker* can be injected by the orchestrator; the real baker shells
    out to ``blender/bake_lighting.py``.

    Dev override: if ``FORGE_BAKE_TIER`` is set in the environment
    (e.g. ``"0"``), its value replaces the tier in *scene_desc* so
    fast iteration never waits on Cycles.

    Returns:
        ``{"tier", "status", "artifacts"}``.
    """
    env_tier = os.environ.get("FORGE_BAKE_TIER")
    if env_tier is not None:
        scene_desc = dict(scene_desc)
        scene_desc["tier"] = int(env_tier)

    if int(scene_desc.get("tier", 0)) == 0:
        return {"tier": 0, "status": "realtime", "artifacts": []}

    result = bake_scene(
        scene_desc,
        baker=baker or (lambda _desc, _out_dir: []),
        cache_root=cache_root,
    )
    if result.get("artifacts") and result.get("tier", 0) >= 1:
        _apply_bake_artifacts(result, build_dir)
    return result


def _apply_bake_artifacts(bake_result: dict, build_dir: str) -> None:
    """Placeholder — orchestrator wires the real artifact copy.

    The contract: bake_and_apply calls this after a successful bake,
    and the artifacts dict carries the file paths.  Tier 1 needs
    COLOR_0 render-active vertex colours; tier 2 needs lightmap.
    """
    pass


def bake_key(scene_desc: dict) -> str:
    """Stable content-address for a lighting bake (layout + sun + sky + tier + samples + interior lights + palette + GLB mtimes)."""
    # Phase 0.8: include palette hash + per-placement GLB mtime so a
    # recolour or regenerated GLB invalidates the bake.
    glb_signals: list = []
    for p in scene_desc.get("placements", []):
        glb_path = p.get("glb", "")
        try:
            glb_signals.append(Path(glb_path).stat().st_mtime_ns)
        except OSError:
            glb_signals.append(0)
    payload = json.dumps(
        {
            "p": _placements_sig(scene_desc.get("placements", [])),
            "sun": scene_desc.get("sun"),
            "sky": scene_desc.get("sky"),
            "tier": scene_desc.get("tier"),
            "samples": scene_desc.get("samples"),
            "il": [[l.get("type"),
                    [round(float(x),4) for x in l.get("pos", ())],
                    [round(float(c),4) for c in l.get("color", ())],
                    round(float(l.get("energy",0.0)),4)]
                   for l in scene_desc.get("interior_lights", [])],
            "palette": scene_desc.get("palette"),
            "glb_mtimes": glb_signals,
        },
        sort_keys=True,
    )
    return content_cache_key(proxy_hash=payload, seed=0, model_version="bake-2")


def _cache_dir(root: Path, key: str) -> Path:
    return root / "lighting" / key


def is_cached(scene_desc: dict, *, cache_root: str | Path | None = None) -> bool:
    """True if this scene's bake is already cached."""
    root = Path(cache_root) if cache_root else DEFAULT_ROOT
    cd = _cache_dir(root, bake_key(scene_desc))
    return cd.exists() and any(cd.iterdir())


def bake_scene(scene_desc: dict, *, baker: Baker,
               cache_root: str | Path | None = None) -> dict:
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
        out: list[str] = []
        for a in artifacts:
            dst = cache_dir / Path(a).name
            shutil.move(str(a), str(dst))
            out.append(str(dst))
        return {"tier": tier, "status": "baked", "artifacts": sorted(out)}
    except Exception as exc:
        # Bake failed (HIP OOM, unwrap error, …) → realtime, scene still renders.
        # Phase 0.3: emit a loud Decision Point — no more silent degradation.
        dp = make_decision(
            code="bake.cycles_failed",
            stage="bake",
            severity="error",
            context={
                "exception_class": type(exc).__name__,
                "exception_reason": str(exc)[:200],
            },
            choices=(),
        )
        return {
            "tier": 0, "status": "fallback", "artifacts": [],
            "decisions": [dp],
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
