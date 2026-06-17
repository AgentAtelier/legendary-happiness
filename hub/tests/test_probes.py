"""Tests for the chain-probe framework in bench.py — verdict model, registry
integrity, and the runner's roll-up/persistence. No live stack needed.

⚠ DEPRECATED (Guide 1 Category G, June 2026): bench.py has been removed after
all probe tests migrated to forge_testbench/tests/probes.py.
These tests will fail — import `bench` no longer resolves.
"""

import json

import bench
import pytest


def test_probe_shape():
    r = bench._probe("works", "all good", "rule", a=1, b="x")
    assert r["verdict"] == "works"
    assert r["summary"] == "all good"
    assert r["thresholds"] == "rule"
    assert r["data"] == {"a": 1, "b": "x"}


def test_worst_rollup_orders_broken_above_degraded_above_works():
    assert bench._worst(["works", "works"]) == "works"
    assert bench._worst(["works", "degraded"]) == "degraded"
    assert bench._worst(["degraded", "broken"]) == "broken"
    # skip never dominates a real verdict…
    assert bench._worst(["skip", "works"]) == "works"
    # …but an all-skip layer rolls up to skip.
    assert bench._worst(["skip", "skip"]) == "skip"


def test_registry_integrity():
    ids = [p["id"] for p in bench.PROBES]
    assert len(ids) == len(set(ids)), "duplicate probe ids"
    valid_layers = {"llama", "devforge", "godot-ai", "runtime", "odysseus"}
    for p in bench.PROBES:
        assert p["layer"] in valid_layers, f"{p['id']} bad layer {p['layer']}"
        assert p["speed"] in ("fast", "slow")
        assert callable(p["fn"])
        assert p["title"] and p["desc"]


def test_bundles_reference_real_ids():
    ids = {p["id"] for p in bench.PROBES}
    for name, members in bench.PROBE_BUNDLES.items():
        assert members, f"bundle {name} empty"
        assert set(members) <= ids, f"bundle {name} has unknown ids"


@pytest.mark.asyncio
async def test_run_probes_rollup_counts_and_persist(tmp_path, monkeypatch):
    async def ok():
        return bench._probe("works", "ok")

    async def deg():
        return bench._probe("degraded", "meh")

    async def boom():
        raise RuntimeError("kaboom")

    fake = [
        dict(id="llama.x", layer="llama", speed="fast", fn=ok, title="X", desc="d"),
        dict(id="llama.y", layer="llama", speed="fast", fn=deg, title="Y", desc="d"),
        dict(id="devforge.z", layer="devforge", speed="slow", fn=boom, title="Z", desc="d"),
    ]
    monkeypatch.setattr(bench, "PROBES", fake)
    monkeypatch.setattr(bench, "DATA_DIR", tmp_path)
    # Don't let the runner try to restore a Godot scene (no live stack).
    fake_layers = {p["id"]: p for p in fake}
    monkeypatch.setattr(bench, "_reset_probe_caches", lambda: None)

    lines = []
    # Only llama probes → no devforge/godot/runtime → no scene restore attempted.
    run = await bench.run_probes(["llama.x", "llama.y"], lines.append)

    assert run["counts"] == {"works": 1, "degraded": 1, "broken": 0, "skip": 0}
    assert run["layer_rollup"] == {"llama": "degraded"}
    # Probe order follows the registry, not the call order.
    assert [p["id"] for p in run["probes"]] == ["llama.x", "llama.y"]
    # A scorecard file was written.
    files = list(tmp_path.glob("probe-*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text())
    assert saved["counts"]["works"] == 1


@pytest.mark.asyncio
async def test_run_probes_crash_becomes_broken(tmp_path, monkeypatch):
    async def boom():
        raise RuntimeError("kaboom")

    fake = [dict(id="llama.boom", layer="llama", speed="fast", fn=boom, title="B", desc="d")]
    monkeypatch.setattr(bench, "PROBES", fake)
    monkeypatch.setattr(bench, "DATA_DIR", tmp_path)
    run = await bench.run_probes(["llama.boom"], lambda _l: None)
    assert run["counts"]["broken"] == 1
    assert run["probes"][0]["verdict"] == "broken"
    assert "kaboom" in run["probes"][0]["summary"]
