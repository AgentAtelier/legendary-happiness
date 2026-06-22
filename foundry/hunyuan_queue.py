"""foundry.hunyuan_queue — job queue + content-addressed cache for the idle server.

Decouples the fast foundry (which ENQUEUES asset-generation jobs and reads the
CACHE) from the slow GPU worker (the idle server, in the spike venv, which loads
the Hunyuan model once and DRAINS the queue). The foundry never blocks on the GPU:
it asks for an asset → gets the cached GLB if present, else a job is queued and a
procedural fallback is used until the neural base lands.

On-disk layout (default ``~/.cache/forge/hunyuan/``):
    queue/<priority>_<key>.json   pending jobs (lower priority number drained first)
    cache/<key>.glb               finished assets (content-addressed)
    done/<key>.json               archived job specs

A *job spec* is ``{proxy_path|proxy_hash, category, material, seed, model_version,
target_dims, priority, ...}``. ``key`` = ``content_cache_key`` of (proxy, seed,
model) → identical requests dedupe to one job and one cached asset (deterministic).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import List, Optional

from hunyuan_postprocess import content_cache_key

DEFAULT_ROOT = Path.home() / ".cache" / "forge" / "hunyuan"


def _root(root: Optional[str | Path]) -> Path:
    r = Path(root) if root else DEFAULT_ROOT
    for sub in ("queue", "cache", "done"):
        (r / sub).mkdir(parents=True, exist_ok=True)
    return r


def make_key(spec: dict) -> str:
    """Content-address a job spec (dedupe + cache key)."""
    return content_cache_key(
        proxy_hash=str(spec.get("proxy_hash") or spec.get("proxy_path") or ""),
        seed=int(spec.get("seed", 0)),
        model_version=str(spec.get("model_version", "omni-2.1")),
        extra=str(spec.get("extra", "")),
    )


def cache_path(key: str, *, root: Optional[str | Path] = None) -> Path:
    return _root(root) / "cache" / f"{key}.glb"


def is_cached(key: str, *, root: Optional[str | Path] = None) -> bool:
    return cache_path(key, root=root).exists()


def enqueue(spec: dict, *, root: Optional[str | Path] = None) -> dict:
    """Enqueue an asset job (idempotent). Returns ``{key, status, glb}`` where
    status is ``"cached"`` (already built) or ``"queued"``."""
    r = _root(root)
    key = make_key(spec)
    cp = cache_path(key, root=r)
    if cp.exists():
        return {"key": key, "status": "cached", "glb": str(cp)}
    full = {**spec, "key": key}
    prio = int(spec.get("priority", 100))
    job = r / "queue" / f"{prio:04d}_{key}.json"
    if not job.exists():
        job.write_text(json.dumps(full, indent=2))
    return {"key": key, "status": "queued", "glb": str(cp)}


def pending_jobs(*, root: Optional[str | Path] = None) -> List[dict]:
    """All queued jobs, priority-ordered (the filename's ``<prio>_<key>`` sorts)."""
    r = _root(root)
    out: List[dict] = []
    for f in sorted((r / "queue").glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def next_job(*, root: Optional[str | Path] = None) -> Optional[dict]:
    """The highest-priority pending job, or None (the server drains these)."""
    jobs = pending_jobs(root=root)
    return jobs[0] if jobs else None


def complete(key: str, *, root: Optional[str | Path] = None) -> None:
    """Archive a job after its ``cache/<key>.glb`` has been written."""
    r = _root(root)
    for f in (r / "queue").glob(f"*_{key}.json"):
        shutil.move(str(f), str(r / "done" / f.name))
