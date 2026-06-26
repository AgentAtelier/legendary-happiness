"""Unit tests for foundry.hunyuan_worker — queue draining with a stub inference fn."""

from __future__ import annotations

import pytest

trimesh = pytest.importorskip("trimesh")

import hunyuan_queue as q  # noqa: E402
from hunyuan_worker import drain, process_job  # noqa: E402


def _stub_infer(job):
    """Pretend-Hunyuan: a unit sphere regardless of the spec."""
    return trimesh.creation.icosphere(subdivisions=2)


def _spec(proxy, prio=100, target=(0.8, 0.8, 0.8)):
    return {"proxy_path": proxy, "category": "rock", "material": "granite",
            "seed": 1, "model_version": "omni-2.1", "priority": prio,
            "target_dims": list(target)}


def test_process_job_caches_and_archives(tmp_path):
    r = q.enqueue(_spec("a.ply"), root=tmp_path)
    key = r["key"]
    job = q.next_job(root=tmp_path)
    out = process_job(job, _stub_infer, root=tmp_path)
    assert out.exists()
    assert q.is_cached(key, root=tmp_path)
    assert q.next_job(root=tmp_path) is None  # archived


def test_cached_mesh_fits_target_envelope(tmp_path):
    q.enqueue(_spec("a.ply", target=(0.5, 0.5, 0.5)), root=tmp_path)
    out = process_job(q.next_job(root=tmp_path), _stub_infer, root=tmp_path)
    mesh = trimesh.load(str(out), force="mesh")
    for e in mesh.extents:
        assert e <= 0.5 + 1e-4
    assert abs(mesh.bounds[0][1]) < 1e-4  # sits on ground


def test_drain_processes_all_in_priority_order(tmp_path):
    q.enqueue(_spec("low.ply", prio=200), root=tmp_path)
    q.enqueue(_spec("high.ply", prio=10), root=tmp_path)
    order = []
    n = drain(_stub_infer, root=tmp_path, on_done=lambda job, out: order.append(job["proxy_path"]))
    assert n == 2
    assert order == ["high.ply", "low.ply"]
    assert q.next_job(root=tmp_path) is None


def test_drain_respects_max_jobs(tmp_path):
    for i in range(3):
        q.enqueue(_spec(f"{i}.ply"), root=tmp_path)
    n = drain(_stub_infer, root=tmp_path, max_jobs=2)
    assert n == 2
    assert q.next_job(root=tmp_path) is not None  # one left


def test_drain_empty_queue_is_zero(tmp_path):
    assert drain(_stub_infer, root=tmp_path) == 0


def test_drain_isolates_a_failing_job(tmp_path):
    q.enqueue(_spec("bad.ply", prio=10), root=tmp_path)
    q.enqueue(_spec("good.ply", prio=20), root=tmp_path)
    errors = []

    def flaky(job):
        if "bad" in job["proxy_path"]:
            raise RuntimeError("boom")
        return trimesh.creation.icosphere(subdivisions=2)

    n = drain(flaky, root=tmp_path, on_error=lambda job, e: errors.append(job["proxy_path"]))
    assert n == 1  # the good one
    assert errors == ["bad.ply"]  # bad one isolated, logged
    assert q.next_job(root=tmp_path) is None  # both archived, no infinite loop
