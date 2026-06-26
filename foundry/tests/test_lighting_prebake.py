"""Unit tests for foundry.lighting_prebake — idle-time bake queue + drain."""

from __future__ import annotations

import os

import lighting_bake
from lighting_prebake import drain_bakes, enqueue_bake, pending_bakes


def _desc(sun=(0.3, -0.6, -0.7)):
    return {
        "placements": [{"glb": "terrain.glb", "transform": [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
                        "static": True}],
        "sun": {"direction": list(sun), "energy": 1.1, "color": [1, 1, 1]},
        "sky": {"top": [0.5, 0.6, 0.8], "horizon": [0.6, 0.6, 0.6], "ambient_energy": 0.5},
        "tier": 1, "samples": 24,
    }


def _stub_baker(desc, out_dir):
    p = os.path.join(out_dir, "baked.glb")
    with open(p, "w") as f:
        f.write("glb")
    return [p]


def test_enqueue_queues_a_bake(tmp_path):
    r = enqueue_bake(_desc(), cache_root=tmp_path / "c", queue_root=tmp_path / "q")
    assert r["status"] == "queued"
    assert len(pending_bakes(queue_root=tmp_path / "q")) == 1


def test_drain_bakes_populates_cache_and_archives(tmp_path):
    c, q = tmp_path / "c", tmp_path / "q"
    desc = _desc()
    enqueue_bake(desc, cache_root=c, queue_root=q)
    n = drain_bakes(baker=_stub_baker, cache_root=c, queue_root=q)
    assert n == 1
    assert lighting_bake.is_cached(desc, cache_root=c)
    assert len(pending_bakes(queue_root=q)) == 0  # archived


def test_enqueue_skips_already_cached(tmp_path):
    c, q = tmp_path / "c", tmp_path / "q"
    desc = _desc()
    enqueue_bake(desc, cache_root=c, queue_root=q)
    drain_bakes(baker=_stub_baker, cache_root=c, queue_root=q)
    r = enqueue_bake(desc, cache_root=c, queue_root=q)  # now cached
    assert r["status"] == "cached"
    assert len(pending_bakes(queue_root=q)) == 0


def test_enqueue_is_idempotent(tmp_path):
    c, q = tmp_path / "c", tmp_path / "q"
    enqueue_bake(_desc(), cache_root=c, queue_root=q)
    enqueue_bake(_desc(), cache_root=c, queue_root=q)
    assert len(pending_bakes(queue_root=q)) == 1  # deduped by bake_key


def test_drain_respects_max_jobs(tmp_path):
    c, q = tmp_path / "c", tmp_path / "q"
    enqueue_bake(_desc(sun=(0.1, -0.9, 0.1)), cache_root=c, queue_root=q)
    enqueue_bake(_desc(sun=(0.5, -0.5, 0.5)), cache_root=c, queue_root=q)
    assert drain_bakes(baker=_stub_baker, cache_root=c, queue_root=q, max_jobs=1) == 1
    assert len(pending_bakes(queue_root=q)) == 1
