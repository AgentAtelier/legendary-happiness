"""FastAPI app for the Forge UI MVP.

Endpoints:
  POST /forge      — start a forge job in a background thread
  GET  /jobs/{id}  — poll job status
  GET  /decisions  — recent Decision Points
  GET  /report     — latest harness report.json (if present)

All state is in-memory — no database.  The forge pipeline (planner,
runner, llm) is injectable so tests use fakes (no llama/Blender).
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Dict, List, Tuple

# ── Injectables (overridden in tests) ────────────────────────────────

#: Callable ``(request: str) -> (spec: dict, decisions: list)``.
#: Set via ``configure_forge()``; tests inject a fake that skips Blender.
_plan_fn: Callable[[str], Tuple[dict, List]] | None = None

#: Callable ``(spec: dict, decisions: list, library_dir: str) -> dict``.
#: Returns ``{glb_path, gate_passed, registered}``.
_forge_fn: Callable[[dict, List, str], dict] | None = None

#: Library directory for forge output.
_library_dir: str = ""

#: Path to the latest harness report.json (optional).
_report_path: str = ""


def configure_forge(
    *,
    plan_fn: Callable[[str], Tuple[dict, List]],
    forge_fn: Callable[[dict, List, str], dict],
    lexicon_path: str = "",
    library_dir: str = "",
    report_path: str = "",
):
    """Wire the forge pipeline injectables.  Call once at startup."""
    global _plan_fn, _forge_fn, _library_dir, _report_path
    _plan_fn = plan_fn
    _forge_fn = forge_fn
    _library_dir = library_dir
    _report_path = report_path


# ── In-memory state ──────────────────────────────────────────────────

_jobs: Dict[str, dict] = {}
_decisions_store: List[dict] = []

_MAX_DECISIONS = 100


# ── FastAPI app ──────────────────────────────────────────────────────

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Forge UI")

_STATIC_DIR = str(Path(__file__).resolve().parent / "static")


@app.post("/forge")
async def forge_endpoint(req: Request):
    """Start a forge job in a background thread.  Returns ``{job_id}``."""
    body = await req.json()
    request_text = body.get("request", "").strip()
    if not request_text:
        raise HTTPException(status_code=422, detail="Missing 'request' field")

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {"status": "pending", "result": None, "error": None}
    threading.Thread(target=_run_forge, args=(job_id, request_text), daemon=True).start()
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """Poll job status.  Returns ``{status, result, error}``."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return _jobs[job_id]


@app.get("/decisions")
async def get_decisions():
    """Return the most recent Decision Points (last 20)."""
    return {"decisions": _decisions_store[-20:]}


@app.get("/report")
async def get_report():
    """Return the latest harness report.json, or 404 if not configured."""
    if not _report_path or not os.path.exists(_report_path):
        raise HTTPException(status_code=404, detail="No report available")
    with open(_report_path, encoding="utf-8") as f:
        return JSONResponse(content=json.load(f))


# ── Re-run at layer ──────────────────────────────────────────────────

@app.post("/rerun")
async def rerun_endpoint(req: Request):
    """Re-run a spec at a chosen layer.

    Body: ``{spec, layer}`` where layer is one of:
      - ``"material-only"`` — re-resolve material from request text
      - ``"params"`` — re-plan params with LLM (keep material/age)
      - ``"full-prompt"`` — full re-plan via LLM
    """
    body = await req.json()
    spec = body.get("spec", {})
    layer = body.get("layer", "full-prompt")
    request_text = spec.get("request", "")

    if _plan_fn is None:
        raise HTTPException(status_code=500, detail="Forge not configured")

    if layer == "material-only":
        # Re-resolve material deterministically only
        from material_resolver import resolve_material
        material, mat_decisions = resolve_material(request_text or "")
        spec["material"] = material
        return {"spec": spec, "decisions": [d.to_dict() if hasattr(d, "to_dict") else d for d in mat_decisions]}

    elif layer == "params":
        # Keep material + age, re-plan geometry only via the LLM.
        # Note: for MVP this still calls the full plan_fn (which includes
        # LLM), then overrides material + age from the original spec.
        # A true "params-only" short-circuit would skip the LLM entirely.
        new_spec, decisions = _plan_fn(request_text)
        new_spec["material"] = spec.get("material", new_spec.get("material"))
        new_spec["age"] = spec.get("age", new_spec.get("age"))
        return {"spec": new_spec, "decisions": _serialize_decisions(decisions)}

    else:  # full-prompt
        new_spec, decisions = _plan_fn(request_text)
        return {"spec": new_spec, "decisions": _serialize_decisions(decisions)}


# ── Static file serving ──────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


# ── Internal helpers ─────────────────────────────────────────────────

def _run_forge(job_id: str, request_text: str):
    """Background job: plan → forge → store result."""
    try:
        if _plan_fn is None or _forge_fn is None:
            raise RuntimeError("Forge pipeline not configured")

        spec, decisions = _plan_fn(request_text)
        result = _forge_fn(spec, decisions, _library_dir)

        # Preserve the original request on the spec for the re-run editor.
        spec["request"] = request_text

        _jobs[job_id] = {
            "status": "done",
            "result": {
                "glb_path": result.get("glb_path", ""),
                "spec": spec,
                "decisions": _serialize_decisions(decisions),
            },
        }

        # Append to decisions store
        for d in _serialize_decisions(decisions):
            _decisions_store.append({**d, "request": request_text, "job_id": job_id})
            if len(_decisions_store) > _MAX_DECISIONS:
                _decisions_store.pop(0)

    except Exception as exc:
        _jobs[job_id] = {"status": "error", "error": str(exc)}


def _serialize_decisions(decisions: List) -> List[dict]:
    """Serialize DecisionPoint objects to plain dicts via decisions.to_dict."""
    from decisions import to_dict as _to_dict
    out = []
    for d in decisions:
        if hasattr(d, "code"):  # DecisionPoint dataclass
            out.append(_to_dict(d))
        elif isinstance(d, dict):
            out.append(d)
    return out
