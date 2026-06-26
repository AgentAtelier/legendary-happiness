"""Unit tests for foundry.hunyuan_queue — the idle-server job queue + cache."""

from __future__ import annotations

from hunyuan_queue import (
    cache_path,
    complete,
    enqueue,
    is_cached,
    make_key,
    next_job,
    pending_jobs,
)


def _spec(proxy="table.ply", seed=1, prio=100, **kw):
    return {"proxy_path": proxy, "category": "table", "material": "worn_oak",
            "seed": seed, "model_version": "omni-2.1", "priority": prio, **kw}


def test_make_key_deterministic_and_distinct():
    assert make_key(_spec()) == make_key(_spec())
    assert make_key(_spec(seed=1)) != make_key(_spec(seed=2))


def test_enqueue_creates_a_queued_job(tmp_path):
    r = enqueue(_spec(), root=tmp_path)
    assert r["status"] == "queued"
    assert len(pending_jobs(root=tmp_path)) == 1


def test_enqueue_is_idempotent(tmp_path):
    enqueue(_spec(), root=tmp_path)
    enqueue(_spec(), root=tmp_path)
    assert len(pending_jobs(root=tmp_path)) == 1  # deduped by key


def test_cached_asset_short_circuits_enqueue(tmp_path):
    key = make_key(_spec())
    cache_path(key, root=tmp_path).write_text("fake glb")  # pretend it's built
    r = enqueue(_spec(), root=tmp_path)
    assert r["status"] == "cached"
    assert is_cached(key, root=tmp_path)
    assert len(pending_jobs(root=tmp_path)) == 0  # not re-queued


def test_priority_ordering(tmp_path):
    enqueue(_spec(proxy="a.ply", prio=200), root=tmp_path)
    enqueue(_spec(proxy="b.ply", prio=10), root=tmp_path)
    assert next_job(root=tmp_path)["proxy_path"] == "b.ply"  # lower prio first


def test_complete_archives_job(tmp_path):
    enqueue(_spec(), root=tmp_path)
    key = make_key(_spec())
    complete(key, root=tmp_path)
    assert len(pending_jobs(root=tmp_path)) == 0


def test_next_job_none_when_empty(tmp_path):
    assert next_job(root=tmp_path) is None
