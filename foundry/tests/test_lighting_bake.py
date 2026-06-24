"""Unit tests for foundry.lighting_bake — the bake orchestrator (cache/tier/fallback).

Pure-Python; the Blender bake is injected as a stub.
"""

from __future__ import annotations

import os

from lighting_bake import bake_and_apply, bake_key, bake_scene


def _desc(tier=1, sun_dir=(0.0, -1.0, 0.0)):
    return {
        "placements": [{"glb": "a.glb",
                        "transform": [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
                        "static": True}],
        "sun": {"direction": list(sun_dir), "energy": 1.0, "color": [1, 1, 1]},
        "sky": {"top": [0.5, 0.6, 0.8], "horizon": [0.6, 0.6, 0.6], "ambient_energy": 0.4},
        "tier": tier, "samples": 16,
    }


def test_bake_key_deterministic_and_varies():
    assert bake_key(_desc()) == bake_key(_desc())
    assert bake_key(_desc(sun_dir=(0, -1, 0))) != bake_key(_desc(sun_dir=(1, -1, 0)))
    assert bake_key(_desc(tier=1)) != bake_key(_desc(tier=2))


def test_tier0_short_circuits(tmp_path):
    calls = []
    r = bake_scene(_desc(tier=0), baker=lambda d, o: calls.append(1) or [], cache_root=tmp_path)
    assert r["status"] == "realtime" and r["tier"] == 0
    assert calls == []  # no bake for realtime


def test_cache_miss_then_hit(tmp_path):
    calls = []

    def baker(desc, out_dir):
        p = os.path.join(out_dir, "baked.glb")
        with open(p, "w") as f:
            f.write("glb")
        calls.append(1)
        return [p]

    r1 = bake_scene(_desc(), baker=baker, cache_root=tmp_path)
    assert r1["status"] == "baked"
    assert len(calls) == 1
    assert os.path.exists(r1["artifacts"][0])

    r2 = bake_scene(_desc(), baker=baker, cache_root=tmp_path)
    assert r2["status"] == "cached"
    assert len(calls) == 1  # baker NOT called again
    assert r2["artifacts"] == r1["artifacts"]


def test_baker_failure_falls_back_to_realtime(tmp_path):
    def baker(desc, out_dir):
        raise RuntimeError("hip oom")

    r = bake_scene(_desc(), baker=baker, cache_root=tmp_path)
    assert r["status"] == "fallback"
    assert r["tier"] == 0  # always renders


def test_bake_key_depends_on_interior_lights():
    base = {"tier":2,"samples":64,"placements":[],"sun":{},"sky":{},"interior_lights":[]}
    lit  = {**base, "interior_lights":[{"type":"hearth","pos":(0,0.5,-3),"color":(1,0.6,0.3),"energy":6}]}
    assert bake_key(base) != bake_key(lit)


# ═════════════════════════════════════════════════════════════════
#  Phase 2.3: FORGE_BAKE_TIER dev override + bake_and_apply caching
# ═════════════════════════════════════════════════════════════════

def test_forge_bake_tier_override_short_circuits(monkeypatch, tmp_path):
    """FORGE_BAKE_TIER=0 → bake_and_apply returns tier-0 realtime and the baker
    is NEVER called, even when the incoming scene_desc has tier=2."""
    monkeypatch.setenv("FORGE_BAKE_TIER", "0")
    calls = []

    def baker(desc, out_dir):
        calls.append(1)
        return []

    r = bake_and_apply(_desc(tier=2), str(tmp_path), baker=baker, cache_root=tmp_path)
    assert r["tier"] == 0
    assert r["status"] == "realtime"
    assert calls == []


def test_forge_bake_tier_unset_no_override(monkeypatch, tmp_path):
    """When FORGE_BAKE_TIER is NOT set, the incoming scene_desc tier is honoured."""
    # Ensure the env var is absent
    monkeypatch.delenv("FORGE_BAKE_TIER", raising=False)
    calls = []

    def baker(desc, out_dir):
        p = os.path.join(out_dir, "baked.glb")
        with open(p, "w") as f:
            f.write("glb")
        calls.append(1)
        return [p]

    r = bake_and_apply(_desc(tier=1), str(tmp_path), baker=baker, cache_root=tmp_path)
    assert r["tier"] == 1
    assert r["status"] == "baked"
    assert len(calls) == 1


def test_bake_and_apply_cache_hit(tmp_path):
    """Phase 2.3: bake_and_apply reuses the cached artifact on a second identical
    call — the baker is called exactly once."""
    calls = []

    def baker(desc, out_dir):
        p = os.path.join(out_dir, "baked.glb")
        with open(p, "w") as f:
            f.write("glb")
        calls.append(1)
        return [p]

    desc = _desc(tier=1)
    r1 = bake_and_apply(desc, str(tmp_path), baker=baker, cache_root=tmp_path)
    assert r1["status"] == "baked"
    assert len(calls) == 1

    r2 = bake_and_apply(desc, str(tmp_path), baker=baker, cache_root=tmp_path)
    assert r2["status"] == "cached"
    assert len(calls) == 1  # baker NOT called again
    assert r2["artifacts"] == r1["artifacts"]


def test_bake_and_apply_tier0_no_bake(tmp_path):
    """bake_and_apply with tier=0 short-circuits without calling the baker."""
    calls = []

    def baker(desc, out_dir):
        calls.append(1)
        return []

    r = bake_and_apply(_desc(tier=0), str(tmp_path), baker=baker, cache_root=tmp_path)
    assert r["tier"] == 0
    assert r["status"] == "realtime"
    assert calls == []


# ═════════════════════════════════════════════════════════════════
#  Phase 0.4 guard tests: palette + cross-process determinism
# ═════════════════════════════════════════════════════════════════

def test_bake_key_varies_with_palette():
    """Phase 0.4 guard: bake_key must change when palette changes.

    A scene_desc with palette_A must produce a different cache key than
    the same scene_desc with palette_B — otherwise changing the palette
    would silently re-use a stale bake with wrong colours.
    """
    from palette import build_palette
    palette_a = build_palette("stone_keep", 0)
    palette_b = build_palette("woodland", 0)
    base = {"tier":2,"samples":64,"placements":[],"sun":{},"sky":{},"interior_lights":[]}
    a = bake_key({**base, "palette": palette_a})
    b = bake_key({**base, "palette": palette_b})
    assert a != b, (
        f"bake_key must differ with different palettes; "
        f"stone_keep key={a[:16]}... vs woodland key={b[:16]}..."
    )
    # Same palette → same key
    assert bake_key({**base, "palette": palette_a}) == a


def test_cross_process_determinism_bake_key():
    """Phase 0.4 guard (AUDIT-04 T5/T19): bake_key must produce the
    same output regardless of PYTHONHASHSEED, when called in SEPARATE
    subprocesses — proving module-level dict-iteration order doesn't leak
    into the content-address.
    """
    import subprocess
    import sys
    from pathlib import Path as _Path
    scene_desc_repr = (
        "{'tier':1,'samples':32,'placements':[],'sun':"
        "{'direction':[0,-1,0],'energy':1.0,'color':[1,1,1]},"
        "'sky':{'top':[0.5,0.6,0.8],'horizon':[0.6,0.6,0.6],"
        "'ambient_energy':0.4},'interior_lights':[],"
        "'palette':{'roles':{'base':(0.5,0.48,0.45)},"
        "'theme':'stone_keep','seed':0}}"
    )
    code = (
        "import sys; sys.path.insert(0, 'foundry'); "
        "from lighting_bake import bake_key; "
        f"print(bake_key({scene_desc_repr}))"
    )
    env0 = {**os.environ, "PYTHONHASHSEED": "0"}
    env42 = {**os.environ, "PYTHONHASHSEED": "42"}
    # Run from repo root so 'foundry' import works
    proj_root = str(_Path(__file__).resolve().parent.parent.parent)
    r0 = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=10,
        cwd=proj_root, env=env0,
    )
    r42 = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=10,
        cwd=proj_root, env=env42,
    )
    assert r0.returncode == 0, f"subprocess failed: {r0.stderr}"
    assert r42.returncode == 0, f"subprocess failed: {r42.stderr}"
    key0 = r0.stdout.strip()
    key42 = r42.stdout.strip()
    assert key0 == key42, (
        f"bake_key must be PYTHONHASHSEED-independent: "
        f"seed=0 → {key0[:16]}... vs seed=42 → {key42[:16]}..."
    )
