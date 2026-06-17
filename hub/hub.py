#!/usr/bin/env python3
"""forge-hub — local ops panel for the AI ⇄ Godot chain.

The hub is the WORKSHOP: it exists for when something is broken.
Odysseus is the product you use when everything works.

Design rules (do not erode them):
  * stack.env + the `stack` CLI stay the single source of truth.
    The hub shells out to `stack ...`; it never reimplements stack logic.
    The only direct file access is read/save of stack.env (with backups).
  * Binds 127.0.0.1 ONLY — it executes systemctl/docker commands.
  * Command whitelist: nothing from the browser reaches a shell;
    subprocesses are exec'd with fixed argv lists.
  * Host-header allowlist (DNS-rebinding guard) + custom-header
    requirement on POST (CSRF guard) — same philosophy as godot-ai's
    origin guard.
  * Independent of forge-stack.target: `stack down` must never kill
    the tool you use to bring the stack back up.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path

# Downstream modules imported here (not mid-file) — none import hub.py back,
# so there is no actual circular dependency.  The old mid-file placement was
# defensive but unnecessary.
import bench  # noqa: E402
import scenarios  # noqa: E402
import shootout  # noqa: E402
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    PlainTextResponse,
)
from forge_env import ENVFILE, read_env, validate_env, write_env
from forge_models import GIB, RESERVE, vram_total
from forge_ops import (
    check_drift,
    get_action_history,
    get_free_vram,
    reconcile_model,
    record_action,
)
from mcp_client import godot_ai_call as _godot_ai_call

HOME = Path.home()
STACK = str(HOME / ".local/bin/stack")
MODELS_DIR = HOME / "models"
DOC_FILE = HOME / "Obsidian Vault" / "forge-stack-chain.md"
STATIC_DIR = Path(__file__).parent / "static"

HOST = "127.0.0.1"
PORT = int(os.environ.get("FORGE_HUB_PORT", "8003"))
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
CSRF_HEADER = "x-forge-hub"

# Phase 5: API versioning — build ID changes when any source file changes
_BUILD_FILES = ["hub.py", "forge_env.py", "forge_models.py", "forge_ops.py", "scenarios.py", "static/index.html"]
_BUILD_HASH = hashlib.sha1()
for _bf in _BUILD_FILES:
    _fp = STATIC_DIR.parent / _bf
    if _fp.exists():
        _BUILD_HASH.update(_fp.read_bytes())
BUILD_ID = _BUILD_HASH.hexdigest()[:12]

ANSI = re.compile(r"\x1b\[[0-9;]*m")
MODEL_ARG = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
SERVICES = ("llama", "devforge", "godot-ai", "godot")

# Whitelisted long-running actions (everything the buttons can do).
# "model" additionally takes a validated name-fragment argument.
ACTIONS: dict[str, list[str]] = {
    "up": [STACK, "up"],
    "down": [STACK, "down"],
    "down-all": [STACK, "down", "--all"],
    "doctor": [STACK, "doctor"],
    "godot": [STACK, "godot"],
    "restart-all": [STACK, "restart", "all"],
    "restart-llama": [STACK, "restart", "llama"],
    "restart-devforge": [STACK, "restart", "devforge"],
    "restart-godot-ai": [STACK, "restart", "godot-ai"],
    "odysseus-restart": ["docker", "restart", "odysseus-odysseus-1"],
}

# Phase 3c: actions that should also trigger an Odysseus restart for MCP reconnect
_RECONNECT_ACTIONS: set[str] = {"restart-devforge", "restart-godot-ai"}

app = FastAPI(title="forge-hub", docs_url=None, redoc_url=None, openapi_url=None)

# One mutating job at a time; finished jobs kept briefly for stream pickup.
_job_lock = asyncio.Lock()
_jobs: dict[str, dict] = {}


@app.middleware("http")
async def origin_guard(request: Request, call_next):
    host = request.headers.get("host", "")
    if host not in ALLOWED_HOSTS:
        return PlainTextResponse("forbidden host", status_code=403)
    if request.method == "POST" and CSRF_HEADER not in request.headers:
        return PlainTextResponse("missing hub header", status_code=403)
    return await call_next(request)


# ── helpers ──────────────────────────────────────────────────────


async def _run_capture(cmd: list[str], timeout: float = 20.0) -> tuple[int, str]:
    """Run a short read-only command — delegates to forge_ops.run_cmd_capture."""
    from forge_ops import run_cmd_capture

    return await run_cmd_capture(*cmd, timeout=timeout)


async def _start_job(label: str, action_fn) -> str:
    """Acquire the job lock and start a streaming task.

    Used by every /api/* endpoint that runs a long-lived action.
    Returns the job_id (12-char hex) for the SSE stream.
    """
    if _job_lock.locked():
        raise HTTPException(409, "another command is still running")
    await _job_lock.acquire()

    job_id = uuid.uuid4().hex[:12]
    job = {"lines": [f"$ {label}"], "done": False, "exit": None, "t": time.time(), "label": label}
    _jobs[job_id] = job

    async def _runner():
        try:
            await action_fn(job)
        except Exception as e:
            job["lines"].append(f"[hub] job failed: {e}")
            job["exit"] = 1
        finally:
            job["done"] = True
            _job_lock.release()
            cutoff = time.time() - 600
            for jid in [j for j, v in _jobs.items() if v["done"] and v["t"] < cutoff]:
                _jobs.pop(jid, None)

    asyncio.get_running_loop().create_task(_runner())
    return job_idasync def _job_runner(job: dict, cmd: list[str], action: str = "") -> None:
    """Run a subprocess and stream output into the job dict.

    Does NOT manage the job lock — callers (_start_job, legacy endpoints)
    own the lock lifecycle.  Only the caller who acquired the lock should
    release it."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        async for raw in proc.stdout:
            job["lines"].append(ANSI.sub("", raw.decode(errors="replace")).rstrip("\n"))
        job["exit"] = await proc.wait()

        if job["exit"] == 0 and action in _RECONNECT_ACTIONS:
            job["lines"].append("[hub] DevForge/godot-ai restarted — restarting Odysseus to reconnect MCP...")
            recode, reout = await _run_capture(
                ["docker", "restart", "odysseus-odysseus-1"], timeout=30
            )
            if recode == 0:
                job["lines"].append("[hub] Odysseus restarted — MCP tools should reconnect")
            else:
                job["lines"].append(f"[hub] Odysseus restart failed (exit {recode}): {reout[:200]}")
    except Exception as e:
        job["lines"].append(f"[hub] job failed: {e}")
        job["exit"] = 1


# ── routes ───────────────────────────────────────────────────────


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/api/status")
async def status():
    _, raw = await _run_capture([STACK, "status"])
    chips: dict[str, str] = {}
    for svc in SERVICES:
        code, out = await _run_capture(["systemctl", "--user", "is-active", f"forge-{svc}.service"], timeout=5)
        chips[svc] = out.strip() or "unknown"
    code, out = await _run_capture(["docker", "ps", "--format", "{{.Names}}"], timeout=8)
    chips["odysseus"] = "active" if "odysseus-odysseus" in out else "inactive"
    env = read_env(ENVFILE)
    drift_info = await check_drift(env.get("LLAMA_PORT", "8002"))
    return {
        "raw": raw,
        "chips": chips,
        "model": Path(env.get("MODEL", "?")).name,
        "alias": env.get("MODEL_ALIAS", "?"),
        "template": env.get("DEVFORGE_PROMPT_TEMPLATE", "?"),
        "busy": _job_lock.locked(),
        "drift": drift_info,
        "build": BUILD_ID,
    }


@app.post("/api/run")
async def run(request: Request):
    body = await request.json()
    action = body.get("action", "")
    if action == "model":
        arg = body.get("arg", "")
        if not MODEL_ARG.match(arg):
            raise HTTPException(400, "invalid model fragment")
        cmd = [STACK, "model", arg]
    elif action in ACTIONS:
        cmd = ACTIONS[action]
    else:
        raise HTTPException(400, f"unknown action: {action}")

    if _job_lock.locked():
        raise HTTPException(409, "another command is still running")
    await _job_lock.acquire()

    job_id = uuid.uuid4().hex[:12]
    job = {
        "lines": [f"$ {' '.join(cmd)}"],
        "done": False,
        "exit": None,
        "t": time.time(),
        "label": f"{action} {' '.join(cmd[1:3]) if len(cmd) > 2 else ''}",
    }
    _jobs[job_id] = job
    asyncio.get_running_loop().create_task(_job_runner(job, cmd, action))
    return {"job": job_id}


@app.post("/api/swap")
async def swap(request: Request):
    """Transactional model swap with VRAM check and rollback (Phase 2).

    Accepts either 'fragment' (substring match via find()) or 'file'
    (exact GGUF filename, bypasses ambiguity). 'file' takes precedence.
    """
    body = await request.json()
    fragment = (body.get("fragment") or body.get("arg", "")).strip()
    exact_file = (body.get("file") or "").strip()
    if not fragment and not exact_file:
        raise HTTPException(400, "need fragment or file")
    if fragment and not MODEL_ARG.match(fragment):
        raise HTTPException(400, "invalid model fragment")

    # Resolve exact file if provided (bypasses find() ambiguity)
    if exact_file:
        from forge_models import scan as _scan

        models = _scan()
        match = next((m for m in models if m["file"] == exact_file), None)
        if not match:
            raise HTTPException(400, f"no model with file: {exact_file}")
        fragment = match["file"]  # use exact filename for find()

    if _job_lock.locked():
        raise HTTPException(409, "another command is still running")
    await _job_lock.acquire()

    from forge_ops import swap_model

    job_id = uuid.uuid4().hex[:12]
    job = {"lines": [f"$ swap {fragment}"], "done": False, "exit": None, "t": time.time()}
    _jobs[job_id] = job

    async def _runner() -> None:
        try:

            def emit(line: str) -> None:
                job["lines"].append(line)

            job["exit"] = await swap_model(fragment, emit)
        except Exception as e:
            job["lines"].append(f"[hub] swap failed: {e}")
            job["exit"] = 1
        finally:
            job["done"] = True
            _job_lock.release()

    asyncio.get_running_loop().create_task(_runner())
    return {"job": job_id}


@app.get("/api/stream/{job_id}")
async def stream(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")

    async def gen():
        sent = 0
        idle_ticks = 0
        while True:
            while sent < len(job["lines"]):
                # SSE data frames must not contain raw newlines (a multi-line
                # job entry would corrupt framing) — split into one frame/line.
                for part in str(job["lines"][sent]).split("\n"):
                    yield f"data: {part}\n\n"
                sent += 1
                idle_ticks = 0
            if job["done"]:
                yield f"event: done\ndata: {job['exit']}\n\n"
                return
            # Heartbeat: an SSE comment every ~3s of silence keeps the stream
            # visibly alive (and defeats proxy buffering) during the long,
            # output-free phases (model swap, 40s+ planner).
            idle_ticks += 1
            if idle_ticks % 15 == 0:
                yield ": ping\n\n"
            await asyncio.sleep(0.2)

    from fastapi.responses import StreamingResponse

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/models")
async def models():
    code, out = await _run_capture([str(HOME / ".local/bin/forge-model"), "list", "--json"], timeout=30)
    if code != 0:
        raise HTTPException(500, f"forge-model failed: {out[:300]}")
    import json as _json

    env = read_env(ENVFILE)
    data = _json.loads(out)
    free_vram = get_free_vram()
    # Credit back the current model's VRAM (freed on swap). Use the
    # estimator's fit.need_gb (not file size) — the model's runtime
    # VRAM includes KV cache and overhead beyond the GGUF file.
    cur_model_alias = env.get("MODEL_ALIAS", "")
    reclaim = 0
    if cur_model_alias:
        cur = next((m for m in data.get("models", []) if m.get("alias") == cur_model_alias), None)
        if cur:
            reclaim = int(cur["fit"]["need_gb"] * GIB)
    available = min(free_vram + reclaim, vram_total()) - RESERVE
    for m in data.get("models", []):
        need_gb = m.get("fit", {}).get("need_gb", 0)
        if need_gb > available / GIB:
            m["vram_fatal"] = (
                f"Not enough VRAM after swap: needs ~{need_gb} GiB, "
                f"but ~{available / GIB:.1f} GiB available. "
                f"Close apps or lower ctx."
            )
    return {
        "models": data["models"],
        "alias": env.get("MODEL_ALIAS", "?"),
        "template": env.get("DEVFORGE_PROMPT_TEMPLATE", "?"),
        "vram_free_gb": round(free_vram / GIB, 1),
    }


@app.get("/api/models/search")
async def models_search(q: str = ""):
    """Search models by fragment. Returns all matches (never errors on ambiguity).

    Frontend uses this to check for ambiguity before calling /api/swap.
    """
    if not q or len(q.strip()) < 2:
        return {"matches": [], "ambiguous": False, "hint": "need at least 2 characters"}
    from forge_models import scan as _scan

    models = _scan()
    q_lower = q.strip().lower()
    hits = [
        {"file": m["file"], "alias": m["alias"], "fit": m["fit"], "size_bytes": m["size_bytes"]}
        for m in models
        if q_lower in m["file"].lower() or q_lower in m["alias"]
    ]
    return {"matches": hits, "ambiguous": len(hits) > 1, "query": q.strip()}


@app.get("/api/config")
async def config_get():
    try:
        return PlainTextResponse(ENVFILE.read_text())
    except OSError as e:
        raise HTTPException(500, f"cannot read stack.env: {e}")


@app.post("/api/config")
async def config_save(request: Request):
    """Phase 6: save with schema validation and diff preview."""
    body = await request.json()
    text = body.get("text", "")

    # Phase 6: schema validation replaces old "LLAMA_BIN in text" check
    errors = validate_env(text)
    if errors:
        raise HTTPException(400, "validation failed: " + "; ".join(errors))

    # Generate diff for display
    old_text = ""
    try:
        old_text = ENVFILE.read_text()
    except OSError:
        pass
    old_lines = set(old_text.splitlines())
    new_lines = set(text.splitlines())
    diff_added = [l for l in new_lines - old_lines if l.strip() and not l.strip().startswith("#")]

    backup = ENVFILE.with_name(f"stack.env.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    backup.write_text(old_text)
    ENVFILE.write_text(text)
    code, _ = await _run_capture(["systemctl", "--user", "daemon-reload"], timeout=10)

    record_action(
        "config_save", ["save", "stack.env"], 0, 0, output=f"backup={backup.name} diff_added={len(diff_added)}"
    )

    return {
        "saved": True,
        "backup": backup.name,
        "diff_added": diff_added,
        "hint": "apply with Restart all (or the one service you changed)",
    }


@app.post("/api/config/restore")
async def config_restore(request: Request):
    """Phase 6: restore the most recent backup."""
    backups = sorted(ENVFILE.parent.glob("stack.env.bak-*"), reverse=True)
    if not backups:
        raise HTTPException(404, "no backups found")
    latest = backups[0]
    ENVFILE.write_text(latest.read_text())
    await _run_capture(["systemctl", "--user", "daemon-reload"], timeout=10)
    record_action("config_restore", ["restore", str(latest)], 0, 0, output=f"restored from {latest.name}")
    return {"restored": latest.name, "hint": "config restored — restart affected services"}


@app.get("/api/config/backups")
async def config_backups(request: Request):
    """Phase 6: list available backups."""
    backups = sorted(ENVFILE.parent.glob("stack.env.bak-*"), reverse=True)
    return {"backups": [b.name for b in backups]}


@app.post("/api/reconcile")
async def reconcile(request: Request):
    """Phase 3: restart llama to reconcile configured-vs-running drift."""
    if _job_lock.locked():
        raise HTTPException(409, "another command is still running")
    await _job_lock.acquire()

    job_id = uuid.uuid4().hex[:12]
    job = {"lines": ["$ reconcile (restart llama to match stack.env)"], "done": False, "exit": None, "t": time.time()}
    _jobs[job_id] = job

    async def _runner() -> None:
        try:

            def emit(line: str) -> None:
                job["lines"].append(line)

            job["exit"] = await reconcile_model(emit)
        except Exception as e:
            job["lines"].append(f"[hub] reconcile failed: {e}")
            job["exit"] = 1
        finally:
            job["done"] = True
            _job_lock.release()

    asyncio.get_running_loop().create_task(_runner())
    return {"job": job_id}


@app.get("/api/logs/{svc}")
async def logs(svc: str, n: int = 200):
    n = max(10, min(n, 1000))
    if svc in SERVICES:
        _, out = await _run_capture(
            ["journalctl", "--user", "-u", f"forge-{svc}", "-n", str(n), "--no-pager", "-o", "cat"], timeout=15
        )
    elif svc == "odysseus":
        _, out = await _run_capture(["docker", "logs", "--tail", str(n), "odysseus-odysseus-1"], timeout=15)
    else:
        raise HTTPException(400, "unknown service")
    return PlainTextResponse(out)


@app.get("/api/doc")
async def doc():
    try:
        return PlainTextResponse(DOC_FILE.read_text())
    except OSError:
        return PlainTextResponse("(chain doc not found)")


# ── Phase 4: activity log ────────────────────────────────────────


@app.get("/api/actions")
async def actions(n: int = 50):
    n = max(5, min(n, 200))
    return {"actions": get_action_history(n)}


# ── Phase 5: API versioning ──────────────────────────────────────


@app.get("/api/version")
async def version():
    return {"build": BUILD_ID}


@app.get("/api/selfcheck")
async def selfcheck():
    """Phase 5: confirm the JS's expected API shape matches the server.

    The frontend calls this on load. If fields are missing, the page
    shows a clear "reload me" banner instead of rendering undefined.
    """
    return {
        "build": BUILD_ID,
        "expected_fields": {
            "status": ["raw", "chips", "model", "alias", "template", "busy", "drift", "build"],
            "models": ["models", "alias", "template", "vram_free_gb"],
            "actions": ["actions"],
            "version": ["build"],
            "config": ["backups"],
            "bench_tests": ["tests", "bundles"],
            "scenarios": ["scenarios", "tool_call_probes"],
            "scorecards": ["scorecards"],
        },
    }


# ── Chain health (always-on sidebar) ─────────────────────────────


@app.get("/api/chain-health")
async def chain_health():
    """Check every link in the chain: llama → devforge → godot-ai → odysseus.

    Fast checks (HTTP) run first. Slow checks (docker exec) run in
    parallel with a 3-second aggregate timeout. The frontend sidebar
    polls this every 30 seconds and renders a color-coded chain diagram.
    """
    import httpx as _httpx

    env = read_env(ENVFILE)
    llama_port = env.get("LLAMA_PORT", "8002")
    devforge_port = env.get("MCP_PORT", "8001")
    godot_ai_port = env.get("GODOT_AI_PORT", "8000")
    configured_alias = env.get("MODEL_ALIAS", "?")

    links: list[dict] = []
    warnings: list[str] = []
    t0 = time.time()

    async with _httpx.AsyncClient(timeout=3.0) as client:
        # ── fast checks (all parallel) ──
        results = {}

        async def _check_http(label: str, url: str, expect_status: int = 200):
            # `ok`    → got the exact expected status (used for HTTP apps like llama /health).
            # `alive` → got ANY HTTP response, i.e. the port is up. MCP servers (DevForge,
            #           godot-ai) have no `/` route and legitimately answer 404 while fully
            #           healthy, so their liveness must key on `alive`, not `ok`. (Bug fix:
            #           they were falsely shown "down/unreachable" on their normal 404.)
            try:
                r = await client.get(url)
                return {"ok": r.status_code == expect_status, "alive": True, "status": r.status_code}
            except Exception:
                return {"ok": False, "alive": False, "status": None}

        # 1. llama /health + /props (single fetch for props)
        llama_health = await _check_http("llama", f"http://127.0.0.1:{llama_port}/health")
        llama_ok = llama_health["ok"]
        running_alias = "?"
        if llama_ok:
            try:
                r = await client.get(f"http://127.0.0.1:{llama_port}/props")
                if r.status_code == 200:
                    pdata = r.json()
                    running_alias = pdata.get("model_alias") or (pdata.get("default_generation_settings") or {}).get(
                        "model_alias", "?"
                    )
            except Exception:
                logging.debug("chain_health: /props fetch failed, using defaults")
                pass  # /props fetch is best-effort; chain-health still works without it

        links.append(
            {
                "id": "llama",
                "label": "llama.cpp",
                "port": int(llama_port),
                "status": "healthy" if llama_ok else "down",
                "detail": f"{running_alias}" if llama_ok else "unreachable",
                "fix": None if llama_ok else "stack up" if not llama_ok else None,
            }
        )
        if llama_ok and running_alias != configured_alias and running_alias != "?":
            links[-1]["status"] = "degraded"
            links[-1]["detail"] = f"{running_alias} ≠ {configured_alias} (drift)"
            links[-1]["fix"] = "Reconcile (restart llama)"
            warnings.append(f"Model drift: running {running_alias}, configured {configured_alias}")

        # 2. DevForge reachable — MCP server, 404 on `/` means UP (use `alive`).
        df = await _check_http("devforge", f"http://127.0.0.1:{devforge_port}")
        df_template = env.get("DEVFORGE_PROMPT_TEMPLATE", "?")
        links.append(
            {
                "id": "devforge",
                "label": "DevForge",
                "port": int(devforge_port),
                "status": "healthy" if df["alive"] else "down",
                "detail": f"template={df_template}" if df["alive"] else "unreachable",
                "fix": None if df["alive"] else "stack restart devforge",
            }
        )

        # 3. godot-ai reachable — MCP server, 404 on `/` means UP (use `alive`).
        ga = await _check_http("godot-ai", f"http://127.0.0.1:{godot_ai_port}")
        links.append(
            {
                "id": "godot-ai",
                "label": "godot-ai",
                "port": int(godot_ai_port),
                "status": "healthy" if ga["alive"] else "down",
                "detail": "connected" if ga["alive"] else "unreachable",
                "fix": None if ga["alive"] else "stack restart godot-ai",
            }
        )

        # 4. Odysseus HTTP
        ody_url = env.get("ODYSSEUS_URL", "http://127.0.0.1:7000")
        ody = await _check_http("odysseus", ody_url)
        links.append(
            {
                "id": "odysseus",
                "label": "Odysseus",
                "port": 7000,
                "status": "healthy" if ody["ok"] else "down",
                "detail": "responding" if ody["ok"] else "unreachable",
                "fix": None if ody["ok"] else "stack up (docker)",
            }
        )

        # ── slow checks (docker exec, parallel, 3s timeout) ──
        async def _docker_check(label: str, docker_cmd: list[str]) -> dict:
            try:
                code, out = await asyncio.wait_for(
                    _run_capture(["docker", "exec", "odysseus-odysseus-1"] + docker_cmd, timeout=8),
                    timeout=5.0,
                )
                return {"ok": code == 0, "output": out.strip()[:200]}
            except Exception:
                return {"ok": False, "output": "timeout"}

        # Only run docker checks if Odysseus container is running
        if ody["ok"]:
            d_llama, d_devf, d_mcp = await asyncio.gather(
                _docker_check(
                    "ody→llama", ["curl", "-s", "--max-time", "2", f"host.docker.internal:{llama_port}/health"]
                ),
                _docker_check(
                    "ody→DevForge", ["curl", "-s", "--max-time", "2", f"host.docker.internal:{devforge_port}"]
                ),
                _docker_check("mcp-keyword", ["grep", "-c", "MCP", "/app/data/presets.json"]),
            )

            # 5. Odysseus → llama
            links.append(
                {
                    "id": "ody-llama",
                    "label": "Odysseus→llama",
                    "status": "healthy" if d_llama["ok"] else "degraded",
                    "detail": "reachable" if d_llama["ok"] else "cannot reach llama from docker",
                    "fix": None if d_llama["ok"] else "Check host.docker.internal / firewall",
                }
            )

            # 6. Odysseus → DevForge
            links.append(
                {
                    "id": "ody-devforge",
                    "label": "Odysseus→DevForge",
                    "status": "healthy" if d_devf["ok"] else "degraded",
                    "detail": "reachable" if d_devf["ok"] else "cannot reach DevForge from docker",
                    "fix": None if d_devf["ok"] else "Check DevForge MCP_HOST=0.0.0.0",
                }
            )

            # 7. MCP keyword in persona
            mcp_ok = d_mcp["ok"] and int(d_mcp.get("output", "0") or "0") > 0
            links.append(
                {
                    "id": "mcp-keyword",
                    "label": "MCP keyword",
                    "status": "healthy" if mcp_ok else "stale",
                    "detail": "found in persona" if mcp_ok else "MISSING — godot-ai tools may not appear",
                    "fix": None if mcp_ok else "Add 'MCP' to persona inject_suffix in presets.json",
                }
            )
            if not mcp_ok:
                warnings.append("MCP keyword missing from persona — godot-ai tools may be disabled")
        else:
            for lid, lbl in [
                ("ody-llama", "Odysseus→llama"),
                ("ody-devforge", "Odysseus→DevForge"),
                ("mcp-keyword", "MCP keyword"),
            ]:
                links.append(
                    {
                        "id": lid,
                        "label": lbl,
                        "status": "unknown",
                        "detail": "Odysseus not running",
                        "fix": "stack up",
                    }
                )

        # 8. Config-doc consistency check
        doc_mismatches = []
        if DOC_FILE.exists():
            doc_text = DOC_FILE.read_text()
            if "--reasoning-budget" in env.get("LLAMA_BASE_ARGS", ""):
                doc_mismatches.append("reasoning-budget still in LLAMA_BASE_ARGS (doc says removed)")
            if "enable_thinking" not in env.get("LLAMA_ARG_CHAT_TEMPLATE_KWARGS", ""):
                if "enable_thinking" in doc_text:
                    doc_mismatches.append("LLAMA_ARG_CHAT_TEMPLATE_KWARGS missing (doc says needed for thinking)")
        links.append(
            {
                "id": "config-doc",
                "label": "Config↔Doc",
                "status": "healthy" if not doc_mismatches else "stale",
                "detail": "consistent" if not doc_mismatches else "; ".join(doc_mismatches),
                "fix": None if not doc_mismatches else "Edit stack.env or update forge-stack-chain.md",
            }
        )
    if doc_mismatches:
        warnings.extend(doc_mismatches)

    # 9. Probe-root health (Tier 1.1 — best-effort MCP check)
    # The stale-Main2 tab is why a 0% scenario score can be a lie.
    # Check the probe scene root via godot-ai; surface in the chain diagram.
    probe_root_status = "unknown"
    probe_root_detail = "godot-ai not reachable"
    probe_root_fix = None
    if ga["alive"]:
        try:
            h_result = await asyncio.wait_for(_godot_ai_call("scene_get_hierarchy", {"depth": 1}), timeout=5.0)
            nodes = [n for n in h_result.get("nodes", []) if isinstance(n, dict)]
            roots = [n for n in nodes if n.get("path", "").count("/") == 1]
            if len(roots) != 1:
                probe_root_status = "degraded"
                probe_root_detail = f"{len(roots)} root nodes — probe scene may not be open"
                probe_root_fix = "Open probe.tscn in Godot editor"
            else:
                root = roots[0]
                root_name = root.get("name", "")
                root_type = root.get("type", "")
                if root_name != "Main":
                    probe_root_status = "degraded"
                    probe_root_detail = f"root is '{root_name}' (expected 'Main') — stale Main2 cache"
                    probe_root_fix = "Close probe.tscn tab WITHOUT saving, then re-open it"
                    warnings.append(f"Probe root is '{root_name}', not 'Main' — scenario scores will be 0% until fixed")
                elif root_type != "Node3D":
                    probe_root_status = "degraded"
                    probe_root_detail = f"root type is '{root_type}' (expected Node3D)"
                    probe_root_fix = "Probe scene may be corrupted — re-create it"
                else:
                    probe_root_status = "healthy"
                    probe_root_detail = f"root '{root_name}' ({root_type})"
                    probe_root_fix = None
        except Exception as e:
            probe_root_detail = f"could not check: {type(e).__name__}"
            probe_root_fix = "Is the Godot editor running with probe.tscn open?"

    links.append(
        {
            "id": "probe-root",
            "label": "Probe root",
            "status": probe_root_status,
            "detail": probe_root_detail,
            "fix": probe_root_fix,
        }
    )

    # 10. Restart-staleness warning (D4): detect source files newer than running services.
    # Catches the "edited code but forgot to restart" class of bugs — a stale
    # DevForge caused a 0% scenario run before.
    for svc_id, svc_name, src_files in [
        ("restart-devforge", "DevForge", ["engine/devforge/compilation/pipeline/engine.py"]),
        ("restart-godot-ai", "godot-ai", ["dev/ai/godot-ai/src/godot_ai/server.py"]),
    ]:
        try:
            # Get wall-clock start time from systemd
            code, wall_ts = await _run_capture(
                ["systemctl", "--user", "show", f"forge-{svc_name}.service", "--property=ActiveEnterTimestamp"],
                timeout=5,
            )
            if code != 0 or not wall_ts.strip():
                continue
            # Parse "ActiveEnterTimestamp=Day YYYY-MM-DD HH:MM:SS TZ"
            ts_str = wall_ts.strip().split("=", 1)[-1]
            try:
                svc_start = time.mktime(time.strptime(ts_str.rsplit(" ", 1)[0], "%a %Y-%m-%d %H:%M:%S"))
            except ValueError:
                continue
            # Find newest source file mtime
            newest_src = 0
            for f in src_files:
                fp = HOME / f
                if fp.exists():
                    newest_src = max(newest_src, fp.stat().st_mtime)
            if newest_src > svc_start + 5:  # 5s grace for deployment
                staleness = int(newest_src - svc_start)
                links.append(
                    {
                        "id": svc_id,
                        "label": f"{svc_name} stale?",
                        "status": "degraded",
                        "detail": f"source newer than service by ~{staleness}s",
                        "fix": f"systemctl --user restart forge-{svc_name}",
                    }
                )
                warnings.append(
                    f"{svc_name} source files changed {staleness}s after last restart — "
                    f"code change may not be live. Run: systemctl --user restart forge-{svc_name}"
                )
        except Exception:
            pass

    # Post-swap staleness warning
    actions_list = get_action_history(5)
    last_swap = None
    for a in actions_list:
        if a.get("action") == "swap" and a.get("exit_code") == 0:
            last_swap = {"alias": a.get("output", "").replace("model=", ""), "ts": a.get("ts", "?")}
            break
    if last_swap:
        warnings.append(f"Last swap to {last_swap['alias']} at {last_swap['ts']} — reload Odysseus browser tab if open")

    return {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "links": links,
        "warnings": warnings,
        "last_swap": last_swap,
        "ms": round((time.time() - t0) * 1000),
    }


# ── Workstream A1: godot-ai logs proxy (diagnostic data retrieval) ─


@app.get("/api/logs-read")
async def api_logs_read(source: str = "plugin", count: int = 50, offset: int = 0):
    """Proxy godot-ai's logs_read tool — the highest-priority unused data source.

    Surfaces the bridge-side view: plugin traffic, game stdout/stderr,
    editor script errors. This is what explains session deaths (B4) and
    whether failed builds leave traces DevForge never sees (B1).

    Sources:
      plugin (default): MCP plugin recv/send/event traffic (buffer 500)
      game: stdout/stderr from playing game (buffer 2000, clears each project_run)
      editor: editor-process script errors — parse errors, push_error (buffer 500)
      all: plugin → editor → game lines with source per entry

    Query params:
      source: "plugin" | "game" | "editor" | "all"
      count: max lines (default 50, max 200)
      offset: lines to skip (for polling/tail pattern)
    """
    count = max(1, min(count, 200))
    offset = max(0, offset)
    try:
        result = await asyncio.wait_for(
            _godot_ai_call(
                "logs_read",
                {
                    "source": source,
                    "count": count,
                    "offset": offset,
                },
            ),
            timeout=8.0,
        )
        return result
    except asyncio.TimeoutError:
        return {"lines": [], "error": "godot-ai logs_read timed out (8s)", "stale_run_id": True}
    except Exception as e:
        return {"lines": [], "error": f"godot-ai not reachable: {type(e).__name__}", "stale_run_id": True}


# ── test bench ───────────────────────────────────────────────────


@app.get("/api/bench/tests")
async def bench_tests():
    return {
        "tests": [{k: t[k] for k in ("id", "layer", "speed", "title", "desc")} for t in bench.TESTS],
        "bundles": bench.load_bundles(),
    }


@app.post("/api/bench/run")
async def bench_run(request: Request):
    body = await request.json()
    ids = [i for i in body.get("ids", []) if isinstance(i, str)]
    if not ids:
        raise HTTPException(400, "no tests selected")
    if _job_lock.locked():
        raise HTTPException(409, "another command is still running")
    await _job_lock.acquire()

    job_id = uuid.uuid4().hex[:12]
    job = {"lines": [f"test bench — {len(ids)} test(s)"], "done": False, "exit": None, "t": time.time()}
    _jobs[job_id] = job

    async def _runner():
        try:
            result = await bench.run_tests(ids, lambda line: job["lines"].append(line))
            job["exit"] = 0 if result["counts"]["fail"] == 0 and result["counts"]["error"] == 0 else 1
        except Exception as e:
            job["lines"].append(f"[bench] crashed: {e}")
            job["exit"] = 1
        finally:
            job["done"] = True
            _job_lock.release()

    asyncio.get_running_loop().create_task(_runner())
    return {"job": job_id}


@app.post("/api/bench/bundle")
async def bench_save_bundle(request: Request):
    body = await request.json()
    name = (body.get("name") or "").strip()[:60]
    ids = [i for i in body.get("ids", []) if isinstance(i, str)]
    if not name or not ids:
        raise HTTPException(400, "need a name and at least one test")
    bench.save_bundle(name, ids)
    return {"saved": True}


@app.get("/api/bench/history")
async def bench_history():
    return {"runs": bench.history()}


# ── probe mode (chain probes with data + 3-tier verdicts) ─────────


@app.get("/api/bench/probes")
async def bench_probes():
    return {
        "probes": [{k: p[k] for k in ("id", "layer", "speed", "title", "desc")} for p in bench.PROBES],
        "bundles": bench.PROBE_BUNDLES,
    }


@app.post("/api/bench/probe")
async def bench_probe_run(request: Request):
    body = await request.json()
    ids = [i for i in body.get("ids", []) if isinstance(i, str)]
    if not ids:
        raise HTTPException(400, "no probes selected")
    if _job_lock.locked():
        raise HTTPException(409, "another command is still running")
    await _job_lock.acquire()

    job_id = uuid.uuid4().hex[:12]
    job = {"lines": [f"chain probe — {len(ids)} probe(s)"], "done": False, "exit": None, "t": time.time()}
    _jobs[job_id] = job

    async def _runner():
        try:
            result = await bench.run_probes(ids, lambda line: job["lines"].append(line))
            job["exit"] = 0 if result["counts"].get("broken", 0) == 0 else 1
            job["probe_result"] = result
        except Exception as e:
            job["lines"].append(f"[probe] crashed: {e}")
            job["exit"] = 1
        finally:
            job["done"] = True
            _job_lock.release()

    asyncio.get_running_loop().create_task(_runner())
    return {"job": job_id}


@app.get("/api/bench/probe/history")
async def bench_probe_history():
    return {"runs": bench.probe_history()}


@app.get("/api/bench/probe/{ts}")
async def bench_probe_detail(ts: str):
    if not re.match(r"^\d{8}-\d{6}$", ts):
        raise HTTPException(400, "invalid probe timestamp")
    fp = bench.DATA_DIR / f"probe-{ts}.json"
    if not fp.exists():
        raise HTTPException(404, "no such probe run")
    import json as _json

    return _json.loads(fp.read_text())


# ── Stream A: scenario suite + scorecards ────────────────────────

# ── Pipeline shootout (all models, one comprehensive test) ──────


@app.get("/api/scenarios")
async def api_scenarios():
    """List all available scenarios."""
    return {
        "scenarios": [s.to_dict() for s in scenarios.SCENARIOS],
        "tool_call_probes": [{"id": p["id"], "intent": p["intent"]} for p in scenarios.TOOL_CALL_PROBES],
    }


@app.post("/api/scenarios/run")
async def api_scenarios_run(request: Request):
    """Run one or more scenarios (SSE streaming). 'score' runs all."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "invalid or empty JSON body")
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be a JSON object")
    ids = [i for i in body.get("ids", []) if isinstance(i, str)]
    run_tools = body.get("run_tools", False)

    if not ids and not run_tools:
        raise HTTPException(400, "no scenarios selected")
    if _job_lock.locked():
        raise HTTPException(409, "another command is still running")
    await _job_lock.acquire()

    job_id = uuid.uuid4().hex[:12]
    n = len(ids)
    if run_tools:
        n += len(scenarios.TOOL_CALL_PROBES)
    job = {"lines": [f"scenario suite — {n} run(s)"], "done": False, "exit": None, "t": time.time()}
    _jobs[job_id] = job

    async def _runner():
        try:

            def emit(line: str) -> None:
                job["lines"].append(line)

            result = await scenarios.run_suite(ids, emit)
            if run_tools:
                tc_result = await scenarios.run_tool_call_suite(emit)
                result["tool_calls"] = tc_result
                # Merge summaries
                s = result["summary"]
                ts = tc_result["summary"]
                s["tool_pass"] = ts["pass"]
                s["tool_fail"] = ts["fail"]
                s["tool_total"] = ts["total"]
            fail = result["summary"]["fail"] + result["summary"]["error"]
            tc_fail = result.get("tool_calls", {}).get("summary", {}).get("fail", 0) + result.get("tool_calls", {}).get(
                "summary", {}
            ).get("error", 0)
            job["exit"] = 0 if fail == 0 and tc_fail == 0 else 1
        except Exception as e:
            job["lines"].append(f"[scenarios] crashed: {e}")
            job["exit"] = 1
        finally:
            job["done"] = True
            _job_lock.release()

    asyncio.get_running_loop().create_task(_runner())
    return {"job": job_id}


@app.get("/api/scorecards")
async def api_scorecards():
    """List all saved scorecards."""
    return {"scorecards": scenarios.list_scorecards()}


@app.get("/api/scorecards/compare")
async def api_scorecards_compare(model_a: str = "", model_b: str = ""):
    """Side-by-side comparison of two models' latest scorecards."""
    if not model_a or not model_b:
        raise HTTPException(400, "need model_a and model_b query params")
    return scenarios.compare_scorecards(model_a, model_b)


# ── Pipeline Shootout ────────────────────────────────────────────


@app.post("/api/shootout")
async def api_shootout(request: Request):
    """Run the full pipeline shootout against all available models.

    Optional JSON body: {"model": "qwen3"} to test a single model.

    Swaps through each model sequentially, runs the Interactive
    Collectible Arena test, scores with 22 static+runtime checks,
    and returns a composite scorecard with rankings.

    This is a long-running job (~8-10 min for 5 models). Progress
    is streamed via the standard SSE /api/stream/<job_id> endpoint.
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        logging.debug("api_shootout: empty/unparseable body, using defaults")
        pass  # empty or unparseable body is fine — shootout runs with defaults
    model_filter = (body.get("model") or "").strip() or None

    if _job_lock.locked():
        raise HTTPException(409, "another command is still running")
    await _job_lock.acquire()

    label = model_filter or "all models"
    job_id = uuid.uuid4().hex[:12]
    job = {"lines": [f"shootout — {label} — starting..."], "done": False, "exit": None, "t": time.time()}
    _jobs[job_id] = job

    async def _runner():
        try:

            def emit(line: str) -> None:
                job["lines"].append(line)

            result = await shootout.run_shootout(emit, model_filter=model_filter)
            if "error" in result:
                job["exit"] = 1
                job["lines"].append(f"[shootout] {result['error']}")
            else:
                job["exit"] = 0
                job["scorecard"] = result
        except Exception as e:
            job["lines"].append(f"[shootout] crashed: {e}")
            job["exit"] = 1
        finally:
            job["done"] = True
            _job_lock.release()

    asyncio.get_running_loop().create_task(_runner())
    return {"job": job_id}


@app.get("/api/shootout/preflight")
async def api_shootout_preflight():
    """Run pre-flight checks before a shootout."""
    return await shootout.preflight_check()


@app.get("/api/shootout/history")
async def api_shootout_history():
    """List all saved shootout scorecards."""
    return {"shootouts": shootout.list_shootouts()}


@app.get("/api/shootout/{ts}")
async def api_shootout_detail(ts: str):
    """Get a specific shootout scorecard by timestamp filename."""
    fp = shootout.SHOOTOUT_DIR / f"shootout-{ts}.json"
    if not fp.exists():
        raise HTTPException(404, "no such shootout")
    import json as _json

    return _json.loads(fp.read_text())


@app.get("/api/shootout/{ts}/log")
async def api_shootout_log(ts: str):
    """Get the companion log file for a shootout."""
    if not re.match(r"^\d{8}-\d{6}$", ts):
        raise HTTPException(400, "invalid shootout timestamp")
    fp = shootout.SHOOTOUT_DIR / f"shootout-{ts}.log"
    if not fp.exists():
        raise HTTPException(404, "no log for this shootout")
    return PlainTextResponse(fp.read_text())


# ── capability gauntlet (extensible prompt-set benchmark) ─────────

import gauntlet  # noqa: E402


@app.get("/api/gauntlet/sets")
async def api_gauntlet_sets():
    """List available (editable) prompt sets."""
    return {"sets": gauntlet.list_sets()}


@app.post("/api/gauntlet/run")
async def api_gauntlet_run(request: Request):
    """Run a prompt set against the CURRENT model.

    Body: {set, only?: [ids], runs?: int}. ``runs`` repeats each prompt N times
    and the gauntlet aggregates mean ± stddev coverage (clamped 1..20).
    """
    body = await request.json()
    set_id = (body.get("set") or "").strip()
    only = [i for i in (body.get("only") or []) if isinstance(i, str)] or None
    try:
        runs = max(1, min(int(body.get("runs", 1)), 20))
    except (TypeError, ValueError):
        runs = 1
    if not set_id:
        raise HTTPException(400, "no prompt set selected")
    if _job_lock.locked():
        raise HTTPException(409, "another command is still running")
    await _job_lock.acquire()

    job_id = uuid.uuid4().hex[:12]
    label = f"Gauntlet: {set_id}" + (f" ×{runs}" if runs > 1 else "")
    job = {
        "lines": [f"gauntlet — {set_id}{f' ×{runs}' if runs > 1 else ''} — starting..."],
        "done": False,
        "exit": None,
        "t": time.time(),
        "label": label,
    }
    _jobs[job_id] = job

    async def _runner():
        try:
            result = await gauntlet.run_gauntlet(set_id, job["lines"].append, only=only, runs=runs)
            job["exit"] = 0 if "error" not in result else 1
            if "error" in result:
                job["lines"].append(f"[gauntlet] {result['error']}")
        except Exception as e:
            job["lines"].append(f"[gauntlet] crashed: {e}")
            job["exit"] = 1
        finally:
            job["done"] = True
            _job_lock.release()

    asyncio.get_running_loop().create_task(_runner())
    return {"job": job_id}


@app.get("/api/gauntlet/history")
async def api_gauntlet_history():
    return {"runs": gauntlet.history()}


@app.get("/api/gauntlet/{ts}")
async def api_gauntlet_detail(ts: str):
    if not re.match(r"^\d{8}-\d{6}$", ts):
        raise HTTPException(400, "invalid gauntlet timestamp")
    run = gauntlet.get_run(ts)
    if not run:
        raise HTTPException(404, "no such gauntlet run")
    return run


# ── Tier 3: unified run aggregation (feeds Testing-tab history) ──

# Directories scanned by /api/runs
_RUN_DIRS = {
    "bench": bench.DATA_DIR,
    "scenarios": scenarios.SCORECARD_DIR,
    "gauntlet": gauntlet.GAUNTLET_DIR,
}

_RUN_PATTERNS = {
    "bench": "run-*.json",
    "probe": "probe-*.json",
    "scenarios": "*.json",
    "gauntlet": "gauntlet-*.json",
}


def _scan_runs(kind: str | None = None, limit: int = 50) -> list[dict]:
    """Scan all run directories and return unified run summaries, newest first.

    Each summary has the common envelope fields: kind, ts, model, config_hash,
    file, counts. The full run is one read_artifact / detail endpoint away.
    """
    import json as _json

    runs: list[dict] = []
    kinds = [kind] if kind and kind in _RUN_PATTERNS else list(_RUN_PATTERNS)
    for k in kinds:
        pattern = _RUN_PATTERNS[k]
        # probe runs live in bench.DATA_DIR alongside bench runs
        base = bench.DATA_DIR if k in ("bench", "probe") else _RUN_DIRS.get(k, bench.DATA_DIR)
        for f in sorted(base.glob(pattern), reverse=True):
            try:
                d = _json.loads(f.read_text())
            except Exception:
                continue
            run = {
                "kind": d.get("kind", k),
                "file": f.name,
                "ts": d.get("ts", ""),
                "model": d.get("model", "?"),
                "config_hash": d.get("config_hash", ""),
                "counts": d.get("counts", d.get("summary")),
            }
            # Gauntlet: surface set + coverage
            if k == "gauntlet" and d.get("summary"):
                run["set"] = d.get("set", "?")
                run["set_title"] = d.get("set_title", "?")
            runs.append(run)
    # Sort across ALL kinds by ts (newest first), then trim to limit
    runs.sort(key=lambda r: r["ts"], reverse=True)
    return runs[:limit]


@app.get("/api/runs")
async def api_runs(kind: str = "", limit: int = 50):
    """Unified run history — all kinds, newest first.

    Query params:
      kind: filter to one kind (bench, probe, scenarios, gauntlet)
      limit: max runs to return (default 50, max 200)

    Returns [{kind, file, ts, model, config_hash, counts}, ...].
    Full detail is at /api/runs/{kind}/{ts} or the existing per-kind endpoints.
    """

    limit = max(1, min(limit, 200))
    kf = kind.strip() if kind else None
    return {"runs": _scan_runs(kf, limit)}


@app.get("/api/runs/compare")
async def api_runs_compare(kind: str = "", a: str = "", b: str = ""):
    """Side-by-side comparison of two runs of the same kind.

    Query params:
      kind: bench | probe | scenarios | gauntlet (required)
      a: first run identifier — ts (20260614-223807) or config_hash (d5b393a2)
      b: second run identifier — same format

    If a or b matches a config_hash, selects the most recent run with that hash.
    If a or b is "latest" or "previous", selects the 1st/2nd most recent.

    Returns {kind, runs: [{ts, model, config_hash, counts}]} with up to 2 runs.
    """

    kf = kind.strip()
    if not kf or kf not in _RUN_PATTERNS:
        raise HTTPException(400, f"kind must be one of: {sorted(_RUN_PATTERNS)}")

    all_runs = _scan_runs(kf, 100)  # scan deeper for hash matching

    def _resolve(ident: str) -> dict | None:
        if not ident or ident == "latest":
            return all_runs[0] if all_runs else None
        if ident == "previous":
            return all_runs[1] if len(all_runs) > 1 else None
        # Try as config_hash first (8-char hex)
        if len(ident) == 8 and all(c in "0123456789abcdef" for c in ident):
            for r in all_runs:
                if r.get("config_hash") == ident:
                    return r
        # Try as timestamp (filename match)
        for r in all_runs:
            if ident in r.get("file", ""):
                return r
        return None

    run_a = _resolve(a)
    run_b = _resolve(b)
    if not run_a and not run_b:
        raise HTTPException(404, "no matching runs found")

    return {
        "kind": kf,
        "runs": [r for r in (run_a, run_b) if r],
    }


# ── Tier 3 #10: stability score / failure signature ────────────────

# ── B3: thinking-config toggle (A/B test: measure truncation with/without enable_thinking) ──

# ── A6: editor screenshot (visual ground truth) ──


@app.get("/api/screenshot")
async def api_screenshot(source: str = "editor"):
    """Capture a screenshot of the Godot editor viewport or running game.

    Returns a base64-encoded PNG suitable for <img src="data:image/png;base64,...">.
    Useful for answering "did it actually build?" without alt-tabbing to Godot.

    Query params:
      source: "editor" (viewport) | "game" (running project)
    """
    try:
        result = await _godot_ai_call("editor_screenshot", {"source": source})
        # godot-ai returns {"image": "base64...", "format": "png"}
        img_b64 = result.get("image", "") if isinstance(result, dict) else ""
        fmt = result.get("format", "png") if isinstance(result, dict) else "png"
        if not img_b64:
            return {"error": "godot-ai returned no image data"}
        return {"image": img_b64, "format": fmt, "source": source, "data_uri": f"data:image/{fmt};base64,{img_b64}"}
    except Exception as e:
        return {"error": f"screenshot failed: {type(e).__name__}: {e}"}


# ── C1: tool-call probes (model-only axis — isolates model capability from DevForge) ──


@app.post("/api/tools/run")
async def api_tools_run(request: Request):
    """Run the raw tool-call probe suite — isolates MODEL capability without DevForge.

    This is the missing half of the "model vs DevForge vs setup" isolation harness.
    Probes test whether the model can emit structured tool calls to the right tools
    for given intents, independently of DevForge's planning/compilation pipeline.
    """
    if _job_lock.locked():
        raise HTTPException(409, "another command is still running")
    await _job_lock.acquire()

    job_id = uuid.uuid4().hex[:12]
    job = {
        "lines": ["tool-call probe suite — testing model capability directly"],
        "done": False,
        "exit": None,
        "t": time.time(),
        "label": "Tool-call probes",
    }
    _jobs[job_id] = job

    async def _runner():
        try:
            result = await scenarios.run_tool_call_suite(lambda line: job["lines"].append(line))
            fail = result["summary"]["fail"] + result["summary"]["error"]
            job["exit"] = 0 if fail == 0 else 1
            job["tool_result"] = result
        except Exception as e:
            job["lines"].append(f"[tools] crashed: {e}")
            job["exit"] = 1
        finally:
            job["done"] = True
            _job_lock.release()

    asyncio.get_running_loop().create_task(_runner())
    return {"job": job_id}


@app.get("/api/tools/history")
async def api_tools_history():
    """Return the most recent tool-call probe result for the current model."""
    env = read_env(ENVFILE)
    model = env.get("MODEL_ALIAS", "?")
    # Check in-memory: most recent completed tools job with tool_result
    for jid in sorted(_jobs, key=lambda j: _jobs[j].get("t", 0), reverse=True):
        job = _jobs[jid]
        tr = job.get("tool_result")
        if tr and job.get("done"):
            return {
                "model": model,
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "probes": tr.get("probes", []),
                "summary": tr.get("summary", {}),
            }
    # Fallback: search scorecards for tool_calls data
    cards = scenarios.list_scorecards()
    for c in cards:
        fp = scenarios.SCORECARD_DIR / c["file"]
        try:
            d = json.loads(fp.read_text())
            if d.get("tool_calls"):
                tc = d["tool_calls"]
                return {
                    "model": c["model"],
                    "ts": c["ts"],
                    "probes": tc.get("probes", []),
                    "summary": tc.get("summary", {}),
                }
        except Exception:
            continue
    return {"probes": [], "summary": {}, "hint": "Run tool-call probes from Testing tab to populate data"}


# ── B3: thinking-config toggle continued...


@app.get("/api/thinking/status")
async def api_thinking_status():
    """Report current thinking-config state for the A/B test."""
    import json as _json

    env = read_env(ENVFILE)
    kwargs_raw = env.get("LLAMA_ARG_CHAT_TEMPLATE_KWARGS", "")
    thinking_enabled = True  # default: thinking is on
    if kwargs_raw:
        try:
            kwargs = _json.loads(kwargs_raw)
            if kwargs.get("enable_thinking") is False:
                thinking_enabled = False
        except Exception:
            pass
    return {
        "thinking_enabled": thinking_enabled,
        "LLAMA_ARG_CHAT_TEMPLATE_KWARGS": kwargs_raw or "(not set — thinking ON by default)",
    }


@app.post("/api/thinking/toggle")
async def api_thinking_toggle(request: Request):
    """Toggle enable_thinking for the A/B test. Writes stack.env, requires llama restart.

    Toggles between:
      - Thinking ON (default): no LLAMA_ARG_CHAT_TEMPLATE_KWARGS or remove it
      - Thinking OFF: LLAMA_ARG_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}'

    Returns the new state. Caller must restart llama for the change to take effect.
    """
    env = read_env(ENVFILE)
    kwargs_raw = env.get("LLAMA_ARG_CHAT_TEMPLATE_KWARGS", "")
    thinking_enabled = True
    if kwargs_raw:
        try:
            kwargs = _json.loads(kwargs_raw)
            if kwargs.get("enable_thinking") is False:
                thinking_enabled = False
        except Exception:
            pass

    if thinking_enabled:
        # Turn thinking OFF: add enable_thinking=false
        write_env(ENVFILE, {"LLAMA_ARG_CHAT_TEMPLATE_KWARGS": '{"enable_thinking": false}'})
        new_state = False
    else:
        # Turn thinking ON: remove the line entirely (write_env with "" creates KEY=""
        # which read_env still picks up as an empty-but-present key).
        text = ENVFILE.read_text()
        lines = [l for l in text.splitlines() if not l.strip().startswith("LLAMA_ARG_CHAT_TEMPLATE_KWARGS=")]
        ENVFILE.write_text("\n".join(lines) + "\n")
        new_state = True

    return {
        "thinking_enabled": new_state,
        "LLAMA_ARG_CHAT_TEMPLATE_KWARGS": "" if new_state else '{"enable_thinking": false}',
        "needs_restart": True,
        "hint": "Run 'stack restart llama' or click Restart Llama for the change to take effect.",
    }


@app.get("/api/runs/stability")
async def api_runs_stability(kind: str = "", n: int = 10):
    """Stability analysis across recent runs of a given kind.

    Query params:
      kind: bench | probe | scenarios | gauntlet (required)
      n: number of recent runs to analyze (default 10, max 30)

    Returns:
      stability_score: weighted average of per-run scores (0-100)
      variance: standard deviation of scores across runs
      trend: "improving" | "degrading" | "stable" based on last-3 slope
      failure_signature: hash of the set of failing items (stable hash = same failures)
      runs_analyzed: count of runs included
      scores: per-run [score, verdict] time series for sparkline rendering
      passes_attempts: for scenarios/bench, per-item pass÷attempt count
    """
    import json as _json
    import statistics as _stats

    kf = kind.strip()
    if not kf or kf not in _RUN_PATTERNS:
        raise HTTPException(400, f"kind must be one of: {sorted(_RUN_PATTERNS)}")

    n = max(3, min(n, 30))
    all_runs = _scan_runs(kf, n * 2)  # scan deeper for sufficient sample
    if len(all_runs) < 3:
        return {
            "stability_score": None,
            "variance": None,
            "trend": "insufficient data",
            "failure_signature": "",
            "runs_analyzed": len(all_runs),
            "scores": [],
            "passes_attempts": [],
            "hint": f"need at least 3 runs of kind '{kf}' — found {len(all_runs)}",
        }

    runs = all_runs[:n]
    scores: list[int] = []
    failure_items: set[str] = set()

    for run in runs:
        c = run.get("counts", {})
        score = 0
        if kf == "probe":
            # Probes use works/broken/degraded, not pass/fail
            total = c.get("works", 0) + c.get("broken", 0) + c.get("degraded", 0) + c.get("skip", 0)
            score = round(100 * c.get("works", 0) / total) if total else 0
            if c.get("broken", 0) or c.get("degraded", 0):
                failure_items.add(f"{c.get('broken', 0)}b+{c.get('degraded', 0)}d")
        elif kf == "bench":
            total = c.get("pass", 0) + c.get("fail", 0) + c.get("error", 0) + c.get("skip", 0)
            score = round(100 * c.get("pass", 0) / total) if total else 0
            # Envelope carries flat counts only; per-test detail is in the full
            # run JSON (available via detail endpoint). Failure signature uses
            # count string so eg. "3f+1e" → "2f+0e" is a detectable change.
            if c.get("fail", 0) or c.get("error", 0):
                failure_items.add(f"{c.get('fail', 0)}f+{c.get('error', 0)}e")
        elif kf == "scenarios":
            score = round(c.get("pass_rate", 0) * 100)
            # Envelope carries flat pass/fail/error/total; per-scenario detail
            # is in the full scorecard JSON (available via /api/scorecards).
            # Failure signature detects count shifts (eg. 5f→3f = fewer failures).
            if c.get("fail", 0) or c.get("error", 0):
                failure_items.add(f"{c.get('fail', 0)}f+{c.get('error', 0)}e")
        elif kf == "gauntlet":
            score = round(c.get("avg_coverage", 0))
            failure_items.add(f"F{c.get('full', 0)}P{c.get('partial', 0)}B{c.get('broke', 0)}")

        scores.append(score)

    # Stability score: mean of scores (higher = more consistent high performance)
    stability = round(sum(scores) / len(scores), 1)

    # Variance: standard deviation of scores
    variance = round(_stats.stdev(scores), 1) if len(scores) >= 3 else None

    # Trend: linear slope over last 3 runs
    trend = "stable"
    if len(scores) >= 3:
        recent = scores[:3]
        slope = recent[0] - recent[-1]  # newest minus 3rd-newest
        if slope >= 10:
            trend = "improving"
        elif slope <= -10:
            trend = "degrading"

    # Failure signature: hash of the sorted set of failing items
    sig_items = sorted(failure_items)
    failure_sig = hashlib.sha1(",".join(sig_items).encode()).hexdigest()[:12] if sig_items else ""

    # Per-run score time series for sparklines (newest first)
    score_series = [
        {
            "score": s,
            "verdict": "pass" if s >= 90 else ("partial" if s >= 60 else "fail"),
            "ts": runs[i].get("ts", "")[:16],
        }
        for i, s in enumerate(scores)
    ]

    # B3: compute truncation rate across recent runs
    trunc_count = 0
    trunc_scanned = 0
    for run in runs:
        try:
            fp = _RUN_DIRS.get(kf, bench.DATA_DIR) / run["file"]
            if fp.exists():
                d = _json.loads(fp.read_text())
                if kf == "scenarios":
                    for s in d.get("scenarios", []):
                        trunc_scanned += 1
                        if s.get("truncated"):
                            trunc_count += 1
                elif kf in ("bench", "probe"):
                    for t in d.get("tests", d.get("probes", [])):
                        data_block = t.get("data", {})
                        if isinstance(data_block, dict) and "truncated" in data_block:
                            trunc_scanned += 1
                            if data_block.get("truncated"):
                                trunc_count += 1
        except Exception:
            pass
    truncation_rate = round(100 * trunc_count / max(trunc_scanned, 1), 1)

    return {
        "kind": kf,
        "stability_score": stability,
        "variance": variance,
        "trend": trend,
        "failure_signature": failure_sig,
        "failure_items": sig_items if sig_items else [],
        "truncation_rate": truncation_rate,
        "truncation_scanned": trunc_scanned,
        "runs_analyzed": len(runs),
        "scores": score_series,
        "hint": "High stability + low variance = trustworthy. Signature change = different bugs.",
    }


# ── Phase 2a: job-lock visibility ─────────────────────────────────


@app.get("/api/job/active")
async def api_job_active():
    """Return info about the currently running job (if any).

    Frontend polls this to show a busy banner and disable controls.
    """
    if not _job_lock.locked():
        return {"active": False}
    # Find the active (not-done) job
    for jid, job in _jobs.items():
        if not job.get("done"):
            elapsed = round(time.time() - job.get("t", time.time()))
            return {
                "active": True,
                "job_id": jid,
                "label": job.get("label", "running"),
                "elapsed_s": elapsed,
                "line_count": len(job.get("lines", [])),
            }
    return {"active": True}  # locked but no job found (rare race)


# ── Phase 2d: one-click Build/Write mode ──────────────────────────

# Model aliases for the two modes
_BUILD_MODEL_FRAGMENT = "qwen3"
_WRITE_MODEL_FRAGMENT = "merged-22b"

PRESETS_PATH = HOME / "dev/ai/odysseus/data/presets.json"
PERSONA_VAULT = HOME / "Obsidian Vault" / "odysseus-godot-persona.md"


@app.post("/api/mode")
async def api_mode(request: Request):
    """One-click Build/Write mode toggle.

    Body: {"mode": "build"|"write"}
    - Build: swap to qwen3-14b, set persona temp 0.2, restart Odysseus
    - Write: swap to Cydonia-22B, set persona temp 1.0, restart Odysseus
    """
    body = await request.json()
    mode = (body.get("mode") or "").strip()
    if mode not in ("build", "write"):
        raise HTTPException(400, "mode must be 'build' or 'write'")

    if _job_lock.locked():
        raise HTTPException(409, "another command is still running")
    await _job_lock.acquire()

    job_id = uuid.uuid4().hex[:12]
    job = {
        "lines": [f"$ mode {mode}"],
        "done": False,
        "exit": None,
        "t": time.time(),
        "label": f"Mode: {'Build (qwen3)' if mode == 'build' else 'Write (Cydonia)'}",
    }
    _jobs[job_id] = job

    async def _runner():
        try:

            def emit(line: str) -> None:
                job["lines"].append(line)

            fragment = _BUILD_MODEL_FRAGMENT if mode == "build" else _WRITE_MODEL_FRAGMENT
            temp = 0.2 if mode == "build" else 1.0

            # Step 1: swap model
            emit(f"Step 1/3: swapping to {fragment}...")
            from forge_ops import swap_model

            swap_ok = await swap_model(fragment, emit)
            if swap_ok != 0:
                emit(f"[mode] swap returned exit {swap_ok}")
                job["exit"] = 1
                return

            # Step 2: update persona temperature in presets.json
            emit("Step 2/3: updating persona temperature...")
            try:
                import json as _json

                presets = _json.loads(PRESETS_PATH.read_text())
                if "custom" not in presets:
                    emit("  persona 'custom' preset missing — skipping temp update")
                else:
                    presets["custom"]["temperature"] = temp
                    PRESETS_PATH.write_text(_json.dumps(presets, indent=2))
                    emit(f"  persona temp set to {temp}")
            except Exception as e:
                emit(f"  persona update failed: {e}")

            # Step 3: restart Odysseus to pick up persona change + fresh MCP connections
            emit("Step 3/3: restarting Odysseus...")
            code, out = await _run_capture(["docker", "restart", "odysseus-odysseus-1"], timeout=30)
            if code == 0:
                emit(f"  Odysseus restarted — mode '{mode}' active")
                emit("  ⚠ Tool index is now cold — send ONE agent chat in Odysseus to warm it.")
                emit("    (e.g. 'Read the scene hierarchy' in agent mode with the Godot Developer persona)")
                job["exit"] = 0
            else:
                emit(f"  Odysseus restart failed (exit {code}): {out[:200]}")
                job["exit"] = 1
        except Exception as e:
            job["lines"].append(f"[mode] failed: {e}")
            job["exit"] = 1
        finally:
            job["done"] = True
            _job_lock.release()

    asyncio.get_running_loop().create_task(_runner())
    return {"job": job_id}


# ── Phase 3b: embedding lane status ───────────────────────────────

ODYSSEUS_APPDB = HOME / "dev/ai/odysseus/data/app.db"


@app.get("/api/odysseus/embedding-status")
async def api_embedding_status():
    """Report the current embedding lane configuration.

    Odysseus uses a configurable embedding lane for its tool retrieval
    Chroma index. When no remote embedding endpoint is configured, it
    falls back to FastEmbed (local) — which is the default and works fine.
    This endpoint reports the current state so you can tell whether
    retrieval is running locally or against a remote service.
    """
    import sqlite3

    result = {
        "lane": "FastEmbed (local)",
        "status": "ok",
        "remote_endpoints": [],
        "note": "FastEmbed runs locally — no remote endpoint needed. Retrieval uses local embeddings.",
    }
    try:
        db = sqlite3.connect(str(ODYSSEUS_APPDB))
        # Check if an embedding_endpoints table exists
        cur = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='embedding_endpoints'")
        if cur.fetchone():
            eps = db.execute("SELECT id, base_url FROM embedding_endpoints").fetchall()
            if eps:
                result["remote_endpoints"] = [{"id": ep[0], "url": ep[1]} for ep in eps]
                result["lane"] = "Remote (configured)"
                result["note"] = f"{len(eps)} remote embedding endpoint(s) configured"
        else:
            # No embedding_endpoints table — check model_endpoints for any endpoint_kind='embedding'
            cur2 = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='model_endpoints'")
            if cur2.fetchone():
                # Check schema for endpoint_kind column
                cols = [c[1] for c in db.execute("PRAGMA table_info(model_endpoints)").fetchall()]
                if "endpoint_kind" in cols:
                    eps = db.execute(
                        "SELECT id, base_url FROM model_endpoints WHERE endpoint_kind='embedding'"
                    ).fetchall()
                    if eps:
                        result["remote_endpoints"] = [{"id": ep[0], "url": ep[1]} for ep in eps]
                        result["lane"] = "Remote (model_endpoints)"
                        result["note"] = f"{len(eps)} embedding endpoint(s) found in model_endpoints"
        db.close()
    except Exception as e:
        result["note"] = f"Could not inspect app.db: {e}"
    return result


# ── Phase 3a: tool-index warmup (documented step) ─────────────────

ODYSSEUS_CHAT_URL = "http://127.0.0.1:7000"


@app.get("/api/odysseus/warmup")
async def api_odysseus_warmup():
    """Return instructions for warming the tool index.

    MCP tools enter Odysseus's Chroma index only on the FIRST agent chat
    after a (re)start. Since the chat API requires session/auth that the
    hub cannot satisfy from localhost, this endpoint documents the manual
    step instead of silently failing.

    Returns the Odysseus URL + instructions for the one-chat warmup.
    """
    return {
        "url": ODYSSEUS_CHAT_URL,
        "instruction": (
            "Send ONE agent-mode chat (e.g. 'Read the scene hierarchy') in "
            "Odysseus to warm the MCP tool index. After this, the "
            "odysseus.retrieval probe should show 'works'."
        ),
        "note": "Tool index is cold after any Odysseus restart — this is normal.",
    }


# ── Phase 3d: persona anti-clobber ────────────────────────────────


@app.get("/api/persona/check")
async def api_persona_check():
    """Check for persona drift vs the vault doc."""
    import json as _json

    try:
        presets = _json.loads(PRESETS_PATH.read_text())
    except Exception:
        return {"ok": False, "error": "cannot read presets.json"}

    c = presets.get("custom", {})
    issues = []

    if not c.get("enabled"):
        issues.append("persona disabled")
    sp_len = len(c.get("system_prompt") or "")
    if sp_len < 1000:
        issues.append(f"system_prompt is only {sp_len} chars (should be ~3900)")
    temp = float(c.get("temperature", 1.0))
    if temp > 0.35:
        issues.append(f"temperature {temp} > 0.35 (tool-call params get randomized)")
    suf = c.get("inject_suffix", "")
    if "mcp" not in suf.lower():
        issues.append("MCP missing from inject_suffix — tools won't load")
    if "/no_think" not in suf:
        issues.append("/no_think missing from inject_suffix")

    vault_exists = PERSONA_VAULT.exists()

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "enabled": bool(c.get("enabled")),
        "temp": temp,
        "system_prompt_chars": sp_len,
        "has_mcp": "mcp" in suf.lower(),
        "has_nothink": "/no_think" in suf,
        "vault_backup": vault_exists,
    }


@app.post("/api/persona/restore")
async def api_persona_restore(request: Request):
    """Restore the Godot Developer persona from the vault doc.

    Extracts the system_prompt from the vault markdown and writes it
    into presets.json, then restarts Odysseus to pick it up.
    """
    if not PERSONA_VAULT.exists():
        raise HTTPException(404, f"vault doc not found: {PERSONA_VAULT}")

    if _job_lock.locked():
        raise HTTPException(409, "another command is still running")
    await _job_lock.acquire()

    job_id = uuid.uuid4().hex[:12]
    job = {
        "lines": ["$ persona restore"],
        "done": False,
        "exit": None,
        "t": time.time(),
        "label": "Restore persona from vault",
    }
    _jobs[job_id] = job

    async def _runner():
        try:

            def emit(line: str) -> None:
                job["lines"].append(line)

            import json as _json

            # Parse the vault doc to extract system_prompt (between ``` fences)
            vault_text = PERSONA_VAULT.read_text()
            # Extract system prompt from the first code block under "## System Prompt"
            sp_start = vault_text.find("## System Prompt")
            if sp_start < 0:
                emit("Could not find '## System Prompt' section in vault doc")
                job["exit"] = 1
                return
            fence_start = vault_text.find("```", sp_start)
            if fence_start < 0:
                emit("Could not find code fence in System Prompt section")
                job["exit"] = 1
                return
            fence_end = vault_text.find("```", fence_start + 3)
            if fence_end < 0:
                emit("Unclosed code fence in System Prompt section")
                job["exit"] = 1
                return
            # Skip past the first line after opening fence (language tag)
            prompt_start = vault_text.find("\n", fence_start) + 1
            system_prompt = vault_text[prompt_start:fence_end].strip()

            emit(f"Extracted system_prompt: {len(system_prompt)} chars")
            if len(system_prompt) < 1000:
                emit("Extracted prompt too short (<1000 chars) — vault doc may have changed format. Aborting.")
                job["exit"] = 1
                return

            # Write into presets.json
            presets = _json.loads(PRESETS_PATH.read_text())
            presets.setdefault("custom", {})
            presets["custom"]["enabled"] = True
            presets["custom"]["system_prompt"] = system_prompt
            presets["custom"]["temperature"] = 0.2
            presets["custom"]["inject_prefix"] = ""
            presets["custom"]["inject_suffix"] = (
                "[Implement this with the Godot MCP tools and report what changed.] /no_think"
            )
            presets["custom"]["max_tokens"] = 0
            presets["custom"]["character_name"] = "Godot Developer"
            PRESETS_PATH.write_text(_json.dumps(presets, indent=2))
            emit("  presets.json updated")

            # Restart Odysseus to pick up changes
            emit("Restarting Odysseus...")
            code, out = await _run_capture(["docker", "restart", "odysseus-odysseus-1"], timeout=30)
            if code == 0:
                emit("  Persona restored — Odysseus restarting")
                job["exit"] = 0
            else:
                emit(f"  Odysseus restart failed (exit {code}): {out[:200]}")
                job["exit"] = 1
        except Exception as e:
            job["lines"].append(f"[persona] restore failed: {e}")
            job["exit"] = 1
        finally:
            job["done"] = True
            _job_lock.release()

    asyncio.get_running_loop().create_task(_runner())
    return {"job": job_id}


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, access_log=False, log_level="warning")
