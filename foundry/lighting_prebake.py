"""foundry.lighting_prebake — idle-time pre-baking of scene lighting.

The same decoupling as the Hunyuan asset queue, for lighting: the foundry
ENQUEUES scene bakes (keyed by the deterministic ``bake_key``); the idle server
DRAINS them during free GPU time, populating the lighting cache so live assembly
gets instant cache hits. A novel layout that isn't pre-baked simply falls back to
realtime until its bake lands.

Layout (default ``~/.cache/forge/lighting_queue/``):
    <bake_key>.json   — a queued scene_desc
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import lighting_bake

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """0.9b: configure the root logger once at CLI entry."""
    logging.basicConfig(
        level=os.environ.get("FORGE_LOG_LEVEL", "INFO"),
        format="%(levelname)s:%(name)s:%(message)s",
    )

DEFAULT_QUEUE = Path.home() / ".cache" / "forge" / "lighting_queue"


def _qroot(queue_root: str | Path | None) -> Path:
    r = Path(queue_root) if queue_root else DEFAULT_QUEUE
    r.mkdir(parents=True, exist_ok=True)
    return r


def enqueue_bake(scene_desc: dict, *, cache_root=None, queue_root=None) -> dict:
    """Queue a scene bake (idempotent). Returns ``{key, status}`` where status is
    ``"cached"`` (already baked) or ``"queued"``."""
    key = lighting_bake.bake_key(scene_desc)
    if lighting_bake.is_cached(scene_desc, cache_root=cache_root):
        return {"key": key, "status": "cached"}
    q = _qroot(queue_root)
    job = q / f"{key}.json"
    if not job.exists():
        job.write_text(json.dumps(scene_desc, sort_keys=True))
    return {"key": key, "status": "queued"}


def pending_bakes(*, queue_root=None) -> list[dict]:
    q = _qroot(queue_root)
    out: list[dict] = []
    for f in sorted(q.glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def drain_bakes(*, baker, cache_root=None, queue_root=None, max_jobs: int = 0) -> int:
    """Bake each queued scene (populating the lighting cache) and archive the job.
    Returns the count processed. ``baker`` is injected (real Blender / a stub)."""
    q = _qroot(queue_root)
    done = 0
    for f in sorted(q.glob("*.json")):
        try:
            desc = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        lighting_bake.bake_scene(desc, baker=baker, cache_root=cache_root)
        f.unlink(missing_ok=True)  # archive (drop the job once cached)
        done += 1
        if max_jobs and done >= max_jobs:
            break
    return done


if __name__ == "__main__":  # idle-drain entry: python -m lighting_prebake [max]
    import sys

    from exterior_compiler import _blender_baker

    _configure_logging()
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    n = drain_bakes(baker=_blender_baker, max_jobs=limit)
    logger.info("baked %d queued scene(s)", n)
