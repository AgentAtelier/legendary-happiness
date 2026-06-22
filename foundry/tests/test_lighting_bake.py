"""Unit tests for foundry.lighting_bake — the bake orchestrator (cache/tier/fallback).

Pure-Python; the Blender bake is injected as a stub.
"""

from __future__ import annotations

import os

from lighting_bake import bake_key, bake_scene


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
