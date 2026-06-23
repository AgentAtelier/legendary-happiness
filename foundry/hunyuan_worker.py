"""foundry.hunyuan_worker — GPU-independent job draining for the idle asset server.

The draining LOGIC (dequeue → infer → post-process → cache → archive) lives here
so it's testable with a stub inference fn. The spike-side ``asset_server.py``
injects the REAL inference (Hunyuan model loaded once) + the forge-llama GPU swap,
and calls ``drain``. Keeping the loop here means the only untested code in the
server is the model load itself.
"""

from __future__ import annotations

from typing import Callable, Optional

import trimesh

import hunyuan_queue as q
from hunyuan_postprocess import decimate, scale_normalize, sit_on_ground

# A job spec → raw generated mesh. The server passes a Hunyuan-backed impl; tests
# pass a stub.
InferFn = Callable[[dict], trimesh.Trimesh]

POLY_BUDGET = 2000


def process_job(job: dict, infer_fn: InferFn, *, root=None,
                poly_budget: int = POLY_BUDGET):
    """Generate → post-process → cache → archive one job. Returns the cache path."""
    key = job["key"]
    mesh = infer_fn(job)
    mesh = decimate(mesh, poly_budget)
    target = tuple(job.get("target_dims", (1.0, 1.0, 1.0)))
    scale_normalize(mesh, target)
    sit_on_ground(mesh)
    out = q.cache_path(key, root=root)
    mesh.export(str(out))
    q.complete(key, root=root)
    return out


def drain(infer_fn: InferFn, *, root=None, max_jobs: int = 0,
          on_done: Optional[Callable[[dict, str], None]] = None,
          on_error: Optional[Callable[[dict, Exception], None]] = None) -> int:
    """Drain the queue (highest priority first) until empty or *max_jobs* reached.
    Returns the number of jobs processed.

    Per-job failures are ISOLATED: a job that raises is archived (so it is never
    retried or able to loop) and draining continues — essential for unattended
    overnight runs where one bad asset must not halt the batch."""
    done = 0
    while True:
        job = q.next_job(root=root)
        if job is None:
            break
        try:
            out = process_job(job, infer_fn, root=root)
            done += 1
            if on_done is not None:
                on_done(job, str(out))
        except Exception as e:  # isolate: archive the bad job, keep going
            q.complete(job.get("key", ""), root=root)
            if on_error is not None:
                on_error(job, e)
        if max_jobs and done >= max_jobs:
            break
    return done
