"""forge-hub test bench — granular, bundleable diagnostics for the chain.

Every test checks exactly ONE thing and says in plain language what a
failure means. Tests are grouped by layer (llama / godot-ai / devforge /
odysseus) so a red result immediately localizes the problem:
  llama red      → model server / sampling / grammar
  godot-ai red   → editor bridge
  devforge red   → the pipeline (our code)
  odysseus red   → chat-side config, tool retrieval, container wiring

Results are saved to data/bench/run-<ts>.json so models/configs can be
compared over time. Bundles (named selections of test ids) live in
data/bench/bundles.json and can be created from the UI.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Awaitable

import httpx

HOME = Path.home()
ENVFILE = HOME / ".config/forge-stack/stack.env"
PRESETS = HOME / "dev/ai/odysseus/data/presets.json"
APPDB = HOME / "dev/ai/odysseus/data/app.db"
PLUGIN_CFG = HOME / "dev/games/rpg/addons/godot_ai/plugin.cfg"
DATA_DIR = Path(__file__).parent / "data" / "bench"
ODY_CONTAINER = "odysseus-odysseus-1"

CUBE_PROMPT = "create a cube in the middle of the existing ground"


def read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    try:
        for line in ENVFILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"')
    except OSError:
        pass
    return env


async def _sh(*cmd: str, timeout: float = 30.0) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        raw, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, f"timeout after {timeout}s"
    return proc.returncode or 0, raw.decode(errors="replace")


def _ok(detail: str = "") -> dict:
    return {"status": "pass", "detail": detail}


def _fail(detail: str) -> dict:
    return {"status": "fail", "detail": detail}


def _skip(detail: str) -> dict:
    return {"status": "skip", "detail": detail}


# ── MCP helpers ──────────────────────────────────────────────────


async def _godot_ai_call(tool: str, args: dict | None = None) -> Any:
    from mcp.client.streamable_http import streamablehttp_client
    from mcp import ClientSession

    async with streamablehttp_client("http://127.0.0.1:8000/mcp") as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            if tool == "__list__":
                return await s.list_tools()
            res = await s.call_tool(tool, args or {})
            return json.loads(res.content[0].text)


async def _devforge_call(tool: str, args: dict | None = None, timeout_s: int = 240) -> Any:
    from datetime import timedelta
    from mcp.client.sse import sse_client
    from mcp import ClientSession

    async with sse_client("http://127.0.0.1:8001/sse", timeout=10,
                          sse_read_timeout=timeout_s + 30) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            if tool == "__list__":
                return await s.list_tools()
            res = await s.call_tool(tool, args or {},
                                    read_timeout_seconds=timedelta(seconds=timeout_s))
            return json.loads(res.content[0].text)


# ── llama layer ──────────────────────────────────────────────────


async def t_llama_health() -> dict:
    env = read_env()
    port = env.get("LLAMA_PORT", "8002")
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.get(f"http://127.0.0.1:{port}/health")
    return _ok("server answers /health") if r.status_code == 200 else _fail(f"HTTP {r.status_code}")


async def t_llama_props() -> dict:
    env = read_env()
    port = env.get("LLAMA_PORT", "8002")
    async with httpx.AsyncClient(timeout=5) as c:
        p = (await c.get(f"http://127.0.0.1:{port}/props")).json()
    alias = p.get("model_alias")
    want = env.get("MODEL_ALIAS")
    if alias != want:
        return _fail(f"serving '{alias}' but stack.env says '{want}' — restart llama to apply config")
    nctx = (p.get("default_generation_settings") or {}).get("n_ctx") or p.get("n_ctx")
    return _ok(f"model={alias} ctx={nctx}")


async def t_llama_grammar() -> dict:
    env = read_env()
    port = env.get("LLAMA_PORT", "8002")
    payload = {
        "prompt": "<|im_start|>user\nSay anything.<|im_end|>\n<|im_start|>assistant\n",
        "n_predict": 16,
        "grammar": 'root ::= "BENCH-GRAMMAR-OK"',
        "temperature": 0.9,
    }
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"http://127.0.0.1:{port}/completion", json=payload)
    content = r.json().get("content", "")
    if content == "BENCH-GRAMMAR-OK":
        return _ok("grammar constrained the output exactly")
    return _fail(f"grammar NOT enforced — got {content!r}. DevForge plans would be unconstrained.")


async def t_llama_tools() -> dict:
    env = read_env()
    port = env.get("LLAMA_PORT", "8002")
    payload = {
        "model": env.get("MODEL_ALIAS", "model"),
        "messages": [{"role": "user", "content": "Read the scene hierarchy."}],
        "tools": [{"type": "function", "function": {
            "name": "mcp__godot-ai__scene_get_hierarchy",
            "description": "list scene nodes",
            "parameters": {"type": "object", "properties": {}}}}],
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=payload)
    ch = r.json()["choices"][0]
    if ch["finish_reason"] == "tool_calls" and ch["message"].get("tool_calls"):
        name = ch["message"]["tool_calls"][0]["function"]["name"]
        return _ok(f"model emitted a native tool call ({name})")
    return _fail("model did NOT emit a tool call for an obvious tool task — "
                 "this model may be unsuitable for agent mode")


async def t_llama_caps() -> dict:
    env = read_env()
    args = env.get("LLAMA_ARGS", "")
    missing = [f for f in ("--n-predict", "--reasoning-budget") if f not in args]
    if missing:
        return _fail(f"stack.env LLAMA_ARGS missing {missing} — one runaway request "
                     "can block the whole chain (seen June 12)")
    return _ok("runaway guards present in LLAMA_ARGS")


async def t_llama_nothink() -> dict:
    env = read_env()
    if "qwen" not in env.get("MODEL_ALIAS", "").lower():
        return _skip("only applies to Qwen models (current model has no /no_think switch)")
    port = env.get("LLAMA_PORT", "8002")
    payload = {"model": env.get("MODEL_ALIAS"), "temperature": 0.7,
               "messages": [{"role": "user", "content": "Name one Godot node type. /no_think"}]}
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=payload)
    msg = r.json()["choices"][0]["message"]
    if (msg.get("reasoning_content") or "") == "":
        return _ok("/no_think suppressed the thinking block")
    return _fail("/no_think ignored — every agent round will pay a thinking delay")


async def t_llama_chat_content() -> dict:
    """The thinking-trap test (June 13): a chat request must return actual
    content, not dump everything into reasoning_content and hit the length
    cap. On the OBLITERATED Gemma, --reasoning-budget forced think-first mode
    so the model wrote a planning essay into reasoning_content and emitted an
    EMPTY story. Fixed via LLAMA_ARG_CHAT_TEMPLATE_KWARGS={"enable_thinking":
    false}. This catches a regression instantly."""
    env = read_env()
    port = env.get("LLAMA_PORT", "8002")
    payload = {
        "model": env.get("MODEL_ALIAS", "model"),
        "messages": [
            {"role": "system", "content": "You are a fiction writer. Write the story directly."},
            {"role": "user", "content": "Write a short 120-word story about an old clockmaker."},
        ],
        "temperature": 1.0, "max_tokens": 400, "stream": False,
    }
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=payload)
    ch = r.json()["choices"][0]
    content = ch["message"].get("content") or ""
    reasoning = ch["message"].get("reasoning_content") or ""
    if len(content) > 50:
        return _ok(f"chat returned {len(content)} chars of content (finish={ch.get('finish_reason')})")
    if reasoning:
        return _fail(f"EMPTY content but {len(reasoning)} chars of reasoning — thinking trap. "
                     "The model is writing into the think channel and never answering. "
                     'Fix: LLAMA_ARG_CHAT_TEMPLATE_KWARGS=\'{"enable_thinking": false}\' in stack.env')
    return _fail(f"chat returned almost no content (finish={ch.get('finish_reason')})")


# ── godot-ai layer ───────────────────────────────────────────────


async def t_godotai_status() -> dict:
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.get("http://127.0.0.1:8000/godot-ai/status")
    if r.status_code != 200:
        return _fail(f"HTTP {r.status_code} — server down? (stack up)")
    ver = r.json().get("server_version", "?")
    m = re.search(r'^version="(.+)"$', PLUGIN_CFG.read_text(), re.M)
    want = m.group(1) if m else "?"
    if ver != want:
        return _fail(f"server {ver} != plugin {want} — editor will NOT adopt it; restart godot-ai")
    return _ok(f"server {ver} matches the editor plugin")


async def t_godotai_bind() -> dict:
    code, out = await _sh("ss", "-tln")
    if re.search(r"0\.0\.0\.0:8000\b", out):
        return _ok("listening on 0.0.0.0 (reachable from the Odysseus container)")
    if re.search(r"127\.0\.0\.1:8000\b", out):
        return _fail("loopback-only — Odysseus (docker) cannot reach it. A plugin-spawned "
                     "server won the race; run: stack up (it adopts/replaces it)")
    return _fail("nothing listening on :8000")


async def t_godotai_tools() -> dict:
    tools = await _godot_ai_call("__list__")
    n = len(tools.tools)
    return _ok(f"{n} tools") if n >= 40 else _fail(f"only {n} tools — expected ≥40")


async def t_godotai_editor() -> dict:
    code, _ = await _sh("pgrep", "-f", "godot.*--path.*rpg")
    if code != 0:
        return _skip("Godot editor not running (start with: stack godot)")
    es = await _godot_ai_call("editor_state", {})
    if es.get("readiness") == "ready":
        return _ok(f"editor adopted, scene {es.get('current_scene', '?')}")
    return _fail(f"editor not ready: {es}")


async def t_godotai_scene() -> dict:
    h = await _godot_ai_call("scene_get_hierarchy", {"depth": 2})
    nodes = h.get("nodes", [])
    if nodes:
        return _ok(f"{len(nodes)} nodes, root {nodes[0].get('path')}")
    return _fail("empty hierarchy — editor has no open scene, or the WS link is down")


async def t_godotai_guard() -> dict:
    code, _ = await _sh("docker", "ps", "-q", "-f", f"name={ODY_CONTAINER}")
    if not _:
        return _skip("Odysseus container not running")
    _, ip_out = await _sh("docker", "exec", ODY_CONTAINER, "curl", "-s", "-o", "/dev/null",
                          "-w", "%{http_code}", "-m", "5", "http://172.17.0.1:8000/godot-ai/status")
    _, dns_out = await _sh("docker", "exec", ODY_CONTAINER, "curl", "-s", "-o", "/dev/null",
                           "-w", "%{http_code}", "-m", "5",
                           "http://host.docker.internal:8000/godot-ai/status")
    if ip_out.strip() == "200" and dns_out.strip() == "403":
        return _ok("container reaches it via IP (200); DNS name correctly rejected (403)")
    return _fail(f"IP→{ip_out.strip()} (want 200), DNS→{dns_out.strip()} (want 403). "
                 "If IP failed: check GODOT_AI_ALLOW_HOSTS in stack.env")


# ── devforge layer ───────────────────────────────────────────────


async def t_devforge_tools() -> dict:
    tools = await _devforge_call("__list__")
    n = len(tools.tools)
    names = {t.name for t in tools.tools}
    if "apply_spec" not in names:
        return _fail(f"{n} tools but apply_spec missing")
    return _ok(f"{n} tools incl. apply_spec")


async def t_devforge_scene() -> dict:
    d = await _devforge_call("get_scene", {}, timeout_s=30)
    scene = d.get("scene", d)
    kids = scene.get("children")
    if isinstance(kids, list) and len(kids) > 0:
        return _ok(f"nested tree OK — root '{scene.get('name')}' with {len(kids)} children")
    return _fail("scene tree has no children array — flat-list regression "
                 "(DevForge would plan against an empty scene and duplicate cameras/lights)")


async def t_devforge_apply() -> dict:
    """Full write test: create a marker node via the LLM pipeline, verify it
    is visible (has a mesh) and that NOTHING unrequested was added, then
    delete it. Slow (one real LLM plan)."""
    d = await _devforge_call(
        "apply_spec", {"prompt": "Add a MeshInstance3D named BenchMarker to the current scene"},
        timeout_s=240)
    if d.get("error_count", 0) or d.get("errors"):
        return _fail(f"apply_spec errors: {d.get('errors')}")
    art = await _devforge_call("read_artifact", {"artifact_id": d["artifact_id"]}, timeout_s=30)
    ops = art.get("operations", [])
    extras = [o for o in ops if o.get("type") == "add_node"
              and o.get("name") not in ("BenchMarker",)]
    problems = []
    if extras:
        problems.append(f"unrequested nodes added: {[o.get('name') for o in extras]}")
    props = await _godot_ai_call("node_get_properties", {"path": "/Main/BenchMarker"})
    pdata = props.get("data", props)
    plist = pdata.get("properties", pdata)
    if isinstance(plist, list):
        plist = {x.get("name"): x.get("value") for x in plist if isinstance(x, dict)}
    if not plist.get("mesh"):
        problems.append("node created WITHOUT a mesh (invisible-node regression)")
    # cleanup regardless
    await _godot_ai_call("batch_execute", {"commands": [
        {"command": "delete_node", "params": {"path": "/Main/BenchMarker"}},
        {"command": "save_scene", "params": {}}], "undo": True})
    if problems:
        return _fail("; ".join(problems))
    return _ok(f"created visible node via LLM plan ({d.get('applied')} ops), cleaned up")


# ── odysseus layer ───────────────────────────────────────────────


async def t_ody_up() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get("http://127.0.0.1:7000/api/presets")
        return _ok(f"web app answers (HTTP {r.status_code})")
    except Exception as e:
        return _fail(f"not reachable: {e}")


async def t_ody_mcp() -> dict:
    code, started = await _sh("docker", "inspect", ODY_CONTAINER,
                              "--format", "{{.State.StartedAt}}")
    if code != 0:
        return _fail("container not running")
    code, logs = await _sh("docker", "logs", ODY_CONTAINER, "--since",
                           started.strip(), timeout=20)
    have_g = "MCP server connected: godot-ai" in logs
    have_d = "MCP server connected: DevForge" in logs
    if have_g and have_d:
        return _ok("godot-ai (41) and DevForge (30) connected this boot")
    missing = [n for n, ok_ in (("godot-ai", have_g), ("DevForge", have_d)) if not ok_]
    return _fail(f"{missing} NOT connected — Odysseus only connects at startup. "
                 f"Fix: make sure the servers are up, then docker restart {ODY_CONTAINER}")


async def t_ody_persona() -> dict:
    c = json.loads(PRESETS.read_text())["custom"]
    problems = []
    if not c.get("enabled"):
        problems.append("persona disabled (one UI click does this — see vault doc)")
    # The June 13 husk incident: enabled/temp/suffix all passed while the
    # system_prompt was EMPTY — the model had schemas but zero strategy and
    # looped on read-only tools. Check the prompt body too.
    if len(c.get("system_prompt") or "") < 1000:
        problems.append(f"system_prompt is {len(c.get('system_prompt') or '')} chars "
                        "(should be the ~3.9k Godot strategy prompt) — restore from the "
                        "'Godot Developer' template or the vault doc")
    if not c.get("character_name"):
        problems.append("character_name empty (persona chip won't show)")
    suf = c.get("inject_suffix", "")
    if "mcp" not in suf.lower():
        problems.append("'MCP' missing from inject_suffix — LOAD-BEARING: without it "
                        "tool retrieval never runs and the model gets 3 generic tools")
    if "/no_think" not in suf:
        problems.append("/no_think missing from inject_suffix (mandatory at low temp for Qwen)")
    t = float(c.get("temperature", 1.0))
    if t > 0.35:
        problems.append(f"temperature {t} > 0.35 — tool-call params get randomized")
    if int(c.get("max_tokens", 0)) != 0:
        problems.append("max_tokens should be 0 (server-side --n-predict already caps)")
    if problems:
        return _fail("; ".join(problems) + ". NOTE: an admin-UI persona save overwrites "
                     "presets.json — restore from Obsidian Vault/odysseus-godot-persona.md")
    return _ok(f"enabled, temp {t}, /no_think + 'MCP' present")


async def t_ody_endpoint() -> dict:
    code, out = await _sh("sqlite3", str(APPDB),
                          "SELECT base_url, supports_tools FROM model_endpoints;")
    if code != 0:
        return _fail(f"cannot read app.db: {out.strip()}")
    rows = [r for r in out.strip().splitlines() if r]
    problems = []
    for r in rows:
        url, _, flag = r.partition("|")
        if ":8003" in url:
            problems.append(f"bogus endpoint {url} (that's forge-hub, not a model server)")
        elif ":8002" in url and flag != "1":
            problems.append(f"{url} has supports_tools={flag or 'NULL'} (should be 1)")
    return _fail("; ".join(problems)) if problems else _ok(f"{len(rows)} endpoint(s) clean")


async def t_ody_reach() -> dict:
    env = read_env()
    port = env.get("LLAMA_PORT", "8002")
    code, out = await _sh("docker", "exec", ODY_CONTAINER, "curl", "-s", "-m", "5",
                          f"http://host.docker.internal:{port}/health")
    if code == 0 and "ok" in out:
        return _ok("container reaches llama via host.docker.internal")
    return _fail(f"container→llama failed: {out.strip()[:120]} — is llama bound to 0.0.0.0?")


async def t_ody_retrieval() -> dict:
    """THE roulette test: ask Odysseus's own tool index which tools it would
    surface for the cube request (with the live persona injects), exactly as
    the agent loop does. apply_spec must be in the result."""
    c = json.loads(PRESETS.read_text())["custom"]
    query = f"{c.get('inject_prefix', '')} {CUBE_PROMPT} {c.get('inject_suffix', '')}".strip()
    script = (
        "import sys, json; sys.path.insert(0, '/app')\n"
        "from src.tool_index import get_tool_index\n"
        "idx = get_tool_index()\n"
        f"tools = idx.get_tools_for_query({query!r}, 8) if idx else set()\n"
        "print(json.dumps(sorted(tools)))\n"
    )
    code, out = await _sh("docker", "exec", ODY_CONTAINER, "python", "-c", script,
                          timeout=90)
    if code != 0:
        return _fail(f"probe failed inside container: {out.strip()[:200]}")
    try:
        tools = json.loads(out.strip().splitlines()[-1])
    except Exception:
        return _fail(f"unparseable probe output: {out.strip()[:200]}")
    godot = [t for t in tools if t.startswith("mcp__")]
    if "mcp__devforge__apply_spec" in tools:
        return _ok(f"apply_spec retrieved. MCP tools in top-k: {godot}")
    return _fail(f"apply_spec NOT in retrieval for the cube request — the model won't see it. "
                 f"Retrieved MCP tools: {godot or 'NONE'}. "
                 f"Fix: enrich DevForge tool descriptions / persona inject vocabulary, "
                 f"then docker restart {ODY_CONTAINER}")


# ── registry ─────────────────────────────────────────────────────

TESTS: list[dict] = [
    # llama
    dict(id="llama.health", layer="llama", speed="fast", fn=t_llama_health,
         title="Server alive",
         desc="The model server answers on its port. Red = nothing else can work; run 'stack up'."),
    dict(id="llama.props", layer="llama", speed="fast", fn=t_llama_props,
         title="Serving the configured model",
         desc="The model in memory matches stack.env. Red = config was edited without a llama restart."),
    dict(id="llama.caps", layer="llama", speed="fast", fn=t_llama_caps,
         title="Runaway guards configured",
         desc="Generation and thinking caps are set. Red = one bad request can freeze every client for minutes."),
    dict(id="llama.grammar", layer="llama", speed="slow", fn=t_llama_grammar,
         title="Grammar enforcement",
         desc="The server can force exact output formats. Red = DevForge's plans become unconstrained text (silent corruption)."),
    dict(id="llama.tools", layer="llama", speed="slow", fn=t_llama_tools,
         title="Native tool calling",
         desc="The current model emits structured tool calls. Red = this model can't drive agent mode at all."),
    dict(id="llama.nothink", layer="llama", speed="slow", fn=t_llama_nothink,
         title="/no_think switch (Qwen only)",
         desc="The thinking-off switch works. Skipped on non-Qwen models."),
    dict(id="llama.chat_content", layer="llama", speed="slow", fn=t_llama_chat_content,
         title="Chat returns content, not a thinking essay",
         desc="A chat request must produce an actual answer, not dump everything into the "
              "hidden think channel and stall (the June 13 'empty story / corporate essay' bug). "
              "Red = enable thinking-off in stack.env."),
    # godot-ai
    dict(id="godotai.status", layer="godot-ai", speed="fast", fn=t_godotai_status,
         title="Server up + version matches plugin",
         desc="The editor bridge is running and version-compatible. Red = the editor won't adopt it."),
    dict(id="godotai.bind", layer="godot-ai", speed="fast", fn=t_godotai_bind,
         title="Reachable from Docker",
         desc="Bound to all interfaces, not just localhost. Red = Odysseus can't use any Godot tool."),
    dict(id="godotai.tools", layer="godot-ai", speed="fast", fn=t_godotai_tools,
         title="Tool surface complete",
         desc="All ~41 tools are registered."),
    dict(id="godotai.editor", layer="godot-ai", speed="fast", fn=t_godotai_editor,
         title="Editor adopted the server",
         desc="The Godot editor is connected and ready. Skipped if the editor isn't running."),
    dict(id="godotai.scene", layer="godot-ai", speed="fast", fn=t_godotai_scene,
         title="Live scene read",
         desc="A real scene tree comes back. Red = no scene open, or the editor link is broken."),
    dict(id="godotai.guard", layer="godot-ai", speed="fast", fn=t_godotai_guard,
         title="Container access + security guard",
         desc="The Odysseus container reaches godot-ai by IP, and DNS-name access is correctly blocked (anti-rebinding)."),
    # devforge
    dict(id="devforge.tools", layer="devforge", speed="fast", fn=t_devforge_tools,
         title="MCP server + apply_spec present",
         desc="DevForge answers over SSE with its full tool set."),
    dict(id="devforge.scene", layer="devforge", speed="fast", fn=t_devforge_scene,
         title="Scene tree is nested (not flat)",
         desc="Regression check: DevForge must see the real scene, or it duplicates cameras/lights."),
    dict(id="devforge.apply", layer="devforge", speed="slow", fn=t_devforge_apply,
         title="Full pipeline write (LLM plan → editor)",
         desc="Creates a test node via the real LLM pipeline, checks it's visible and nothing extra was added, deletes it. ~1 min."),
    # odysseus
    dict(id="odysseus.up", layer="odysseus", speed="fast", fn=t_ody_up,
         title="Web app running",
         desc="The Odysseus container answers on :7000."),
    dict(id="odysseus.mcp", layer="odysseus", speed="fast", fn=t_ody_mcp,
         title="Both MCP servers connected THIS boot",
         desc="Odysseus only connects at startup — if a server was down then, its tools are missing until a container restart."),
    dict(id="odysseus.persona", layer="odysseus", speed="fast", fn=t_ody_persona,
         title="Persona invariants",
         desc="Godot Developer preset enabled with the load-bearing settings ('MCP' word, /no_think, low temp). Red = a UI save clobbered it."),
    dict(id="odysseus.endpoint", layer="odysseus", speed="fast", fn=t_ody_endpoint,
         title="Model endpoint records clean",
         desc="supports_tools flag set; no bogus endpoints."),
    dict(id="odysseus.reach", layer="odysseus", speed="fast", fn=t_ody_reach,
         title="Container reaches llama",
         desc="Docker→host networking for the model server works."),
    dict(id="odysseus.retrieval", layer="odysseus", speed="slow", fn=t_ody_retrieval,
         title="Tool retrieval surfaces apply_spec",
         desc="Asks Odysseus's own tool index what it would give the model for a cube request (with the live persona). THE test for 'model never saw the right tools'. ~30 s."),
]

DEFAULT_BUNDLES = {
    "fast (all quick checks)": [t["id"] for t in TESTS if t["speed"] == "fast"],
    "llm layer": [t["id"] for t in TESTS if t["layer"] == "llama"],
    "scene write (pipeline proof)": ["devforge.scene", "devforge.apply"],
    "odysseus wiring": [t["id"] for t in TESTS if t["layer"] == "odysseus"],
    "everything": [t["id"] for t in TESTS],
}

BUNDLES_FILE = DATA_DIR / "bundles.json"


def load_bundles() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    user: dict = {}
    if BUNDLES_FILE.exists():
        try:
            user = json.loads(BUNDLES_FILE.read_text())
        except Exception:
            user = {}
    return {**DEFAULT_BUNDLES, **user}


def save_bundle(name: str, ids: list[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    user = {}
    if BUNDLES_FILE.exists():
        try:
            user = json.loads(BUNDLES_FILE.read_text())
        except Exception:
            user = {}
    user[name] = ids
    BUNDLES_FILE.write_text(json.dumps(user, indent=2))


async def run_tests(ids: list[str], emit: Callable[[str], None]) -> dict:
    """Run the selected tests sequentially, emit progress lines, save + return results."""
    by_id = {t["id"]: t for t in TESTS}
    env = read_env()
    run = {
        "kind": "bench",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": env.get("MODEL_ALIAS", "?"),
        "template": env.get("DEVFORGE_PROMPT_TEMPLATE", "?"),
        "tests": [],
    }
    counts = {"pass": 0, "fail": 0, "skip": 0, "error": 0}
    for tid in ids:
        t = by_id.get(tid)
        if not t:
            continue
        emit(f"▶ {tid} — {t['title']}")
        t0 = time.time()
        try:
            res = await asyncio.wait_for(t["fn"](), timeout=300)
        except Exception as e:
            res = {"status": "error", "detail": f"{type(e).__name__}: {e}"}
        ms = int((time.time() - t0) * 1000)
        res.update(id=tid, ms=ms, layer=t["layer"], title=t["title"])
        run["tests"].append(res)
        counts[res["status"]] = counts.get(res["status"], 0) + 1
        mark = {"pass": "PASS", "fail": "FAIL", "skip": "skip", "error": "ERR "}[res["status"]]
        emit(f"  {mark} ({ms} ms) {res['detail']}")
    run["counts"] = counts
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / f"run-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(run, indent=2))
    emit(f"— {counts['pass']} pass / {counts['fail']} fail / {counts['skip']} skip "
         f"({run['model']}) → saved {out.name} —")
    return run


def history(limit: int = 30) -> list[dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    runs = []
    for f in sorted(DATA_DIR.glob("run-*.json"), reverse=True)[:limit]:
        try:
            d = json.loads(f.read_text())
            runs.append({"file": f.name, "ts": d.get("ts"), "model": d.get("model"),
                         "counts": d.get("counts"),
                         "failed": [t["id"] for t in d.get("tests", [])
                                    if t.get("status") in ("fail", "error")]})
        except Exception:
            continue
    return runs


# ═════════════════════════════════════════════════════════════════
#  PROBE MODE — chain-ordered probes that emit interpretable DATA and
#  a 3-tier verdict (works / degraded / broken), not just pass/fail.
#  Separate registry + runner so the binary bench above is untouched.
#  See CHAIN-PROBES-DESIGN.md.
# ═════════════════════════════════════════════════════════════════

# Disposable probe scenes.
# probe.tscn: a Node3D root with baked Camera3D + DirectionalLight3D baseline.
#   The baked baseline means completeness sees a "complete" 3D scene and injects
#   nothing — scenarios build cleanly on top, and `no_extra_nodes` holds.
# probe_bounce.tscn: a throwaway scene used to force a real disk reload (scene_open
#   on an already-active scene is a no-op, which caused the stale-tab class of bugs).
PROBE_SCENE = "res://probe.tscn"
PROBE_BOUNCE_SCENE = "res://probe_bounce.tscn"
PROBE_BASE_SCENE = "res://scenes/main.tscn"
PROBE_BOUNCE_TSCN = (
    '[gd_scene format=3 uid="uid://cprobebounce0001"]\n\n'
    '[node name="_bounce" type="Node3D"]\n'
)
# Baseline: root + Camera3D + DirectionalLight3D — a "complete" 3D scene so
# completeness injects nothing, scenarios assert no_extra_nodes cleanly, and the
# accumulation-vs-injection tradeoff (the 50%↔58% flip-flop) is resolved.
PROBE_SCENE_TSCN = (
    '[gd_scene format=3 uid="uid://cprobebench0001"]\n\n'
    '[node name="Main" type="Node3D"]\n\n'
    '[node name="MainCamera" type="Camera3D" parent="."]\n'
    'transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 2, 10)\n\n'
    '[node name="DirectionalLight" type="DirectionalLight3D" parent="."]\n'
    'transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 10, 0)\n'
)
# Nodes that ARE expected in the baseline — everything else is a scenario artifact
# that gets removed on reset.
_PROBE_BASELINE_NODES = {"Main", "MainCamera", "DirectionalLight"}

# Fixed prompt for the Layer-2 pipeline capture — exercises planning (3
# entities, valid types), nested parenting (Eye/Body under Hero), and execution.
DEVFORGE_PROBE_PROMPT = (
    "Add a CharacterBody3D named Hero as a child of the scene root. "
    "Give Hero a Camera3D child named Eye and a MeshInstance3D child named Body."
)
# The node names the fixed prompt should produce — used to judge whether the
# pipeline fulfilled the REQUEST vs merely applied auto-injected scaffolding.
PROBE_EXPECTED = {"Hero", "Eye", "Body"}

_VERDICT_RANK = {"works": 0, "degraded": 1, "skip": 2, "broken": 3}


def _probe(verdict: str, summary: str, thresholds: str = "", **data: Any) -> dict:
    """A probe result: a 3-tier verdict + a one-line readout + structured data.

    verdict ∈ {works, degraded, broken, skip}. `data` is whatever numbers /
    samples / artifacts make the verdict interpretable.
    """
    return {"verdict": verdict, "summary": summary, "thresholds": thresholds,
            "data": data}


def _worst(verdicts: list[str]) -> str:
    """Roll up child verdicts to the worst real outcome (skip never dominates)."""
    real = [v for v in verdicts if v != "skip"] or ["skip"]
    return max(real, key=lambda v: _VERDICT_RANK.get(v, 0))


# ── probe scene helpers + per-run pipeline capture ────────────────

async def _scene_paths() -> set[str]:
    """Flat set of node paths in the live editor scene."""
    h = await _godot_ai_call("scene_get_hierarchy", {"depth": 10})
    return {n["path"] for n in h.get("nodes", []) if isinstance(n, dict) and n.get("path")}




async def _probe_scene_reset() -> None:
    """Reset the disposable probe scene to a pristine baseline.

    Godot keeps an opened scene in its tab with its UNSAVED in-memory nodes;
    `scene_open` on the already-active scene is a no-op and does NOT reload
    from disk, so re-writing the baseline file does not clear prior prompts'
    nodes — they ACCUMULATE. The only reliable reset is a BOUNCE RELOAD:
    open a different scene first, then the probe — this forces Godot to
    actually reload the probe from disk.

    The bounce trick is proven by the shootout (which already does it).
    """
    # Write BOTH disposable scenes to disk with cache-bust UIDs.
    # Godot tracks open scenes by UID — if a dirty tab with the old UID exists
    # (e.g. root renamed to "Main2"), scene_open matches the old UID and revives
    # the stale tab instead of loading from disk. Fresh UIDs on every reset force
    # a clean load.
    fresh_bounce_uid = f"uid://cbounce{uuid.uuid4().hex[:12]}"
    fresh_bounce_tscn = PROBE_BOUNCE_TSCN.replace(
        "uid://cprobebounce0001", fresh_bounce_uid)
    fresh_probe_uid = f"uid://cprobe{uuid.uuid4().hex[:12]}"
    fresh_probe_tscn = PROBE_SCENE_TSCN.replace(
        "uid://cprobebench0001", fresh_probe_uid)
    try:
        await _godot_ai_call("filesystem_manage", {
            "op": "write_text", "params": {"path": PROBE_BOUNCE_SCENE,
                                         "content": fresh_bounce_tscn},
        })
        await _godot_ai_call("filesystem_manage", {
            "op": "write_text", "params": {"path": PROBE_SCENE,
                                         "content": fresh_probe_tscn},
        })
    except Exception:
        pass

    # Bounce: open the throwaway scene FIRST, then the probe. This forces
    # Godot to actually reload the probe from disk (the bounce scene is
    # different from the current tab, so scene_open is NOT a no-op).
    # The shootout uses this exact pattern — it's the only way to guarantee
    # a genuinely fresh scene when the probe tab is stale/dirty.
    try:
        await _godot_ai_call("scene_open", {"path": PROBE_BOUNCE_SCENE})
    except Exception:
        pass
    try:
        await _godot_ai_call("scene_open", {"path": PROBE_SCENE})
    except Exception:
        pass

    # ── PROBE-ROOT HEALTH CHECK (Tier 1.1 — fail-loud, don't mask corruption) ──
    # The stale-Main2 tab is why a 0% can be a lie. Before ANY write, confirm
    # the probe root is actually clean. If the root is "Main2" (or anything
    # unexpected), the editor is serving a stale cache — refuse to run and tell
    # the user exactly what to do.
    try:
        h = await _godot_ai_call("scene_get_hierarchy", {"depth": 2})
        nodes = [n for n in h.get("nodes", []) if isinstance(n, dict)]
        roots = [n for n in nodes if n.get("path", "").count("/") == 1]
        if len(roots) != 1:
            raise RuntimeError(
                f"probe health check FAILED: expected exactly 1 root node, "
                f"found {len(roots)}. Root paths: {[r.get('path') for r in roots]}. "
                f"Close the probe.tscn tab in Godot and re-open it."
            )
        root = roots[0]
        root_name = root.get("name", "")
        root_type = root.get("type", "")
        if root_name != "Main":
            raise RuntimeError(
                f"probe health check FAILED: root name is '{root_name}', expected 'Main'. "
                f"The editor is serving a stale/corrupted probe tab. "
                f"Fix: close the probe.tscn tab in Godot WITHOUT saving, then re-run. "
                f"(This is the Main→Main2 stale-cache problem — the bounce reload "
                f"can't fix an already-named root.)"
            )
        if root_type != "Node3D":
            raise RuntimeError(
                f"probe health check FAILED: root type is '{root_type}', "
                f"expected 'Node3D'. Scene may be corrupted."
            )
        # Count baseline children — with baked Camera3D + DirectionalLight3D,
        # we expect exactly 2 children at depth 2. Uses depth=2 (above) so
        # children ARE included in the response.
        baseline_kids = [n for n in nodes
                         if n.get("path", "").startswith(root.get("path", "") + "/")
                         and n.get("path", "").count("/") == 2]
        baseline_names = {n.get("name") for n in baseline_kids}
        expected = _PROBE_BASELINE_NODES - {"Main"}  # Main is the root, not a child
        missing = expected - baseline_names
        if missing:
            raise RuntimeError(
                f"probe health check FAILED: baseline nodes missing: {sorted(missing)}. "
                f"Present: {sorted(baseline_names)}. "
                f"The probe scene may not have reloaded correctly — "
                f"close the probe.tscn tab in Godot and re-run."
            )
    except RuntimeError:
        raise  # re-raise our own diagnostics
    except Exception as e:
        raise RuntimeError(
            f"probe health check FAILED: could not read scene hierarchy: {e}. "
            f"Is the Godot editor running with the probe scene open?"
        )

    # ── SAFETY GUARD (do not remove) ──
    # We are about to DELETE nodes from the active scene. If Godot did not
    # actually switch to the disposable probe scene (e.g. a dirty tab kept
    # focus, or scene-tab desync), the active scene could be the user's REAL
    # game (main.tscn) — and the delete loop would destroy it. That is exactly
    # how main.tscn got its root renamed + filled with test junk earlier.
    # ABORT LOUDLY rather than touch a non-disposable scene.
    active = ""
    try:
        st = await _godot_ai_call("editor_state", {})
        active = st.get("current_scene", "")
    except Exception:
        pass
    if active != PROBE_SCENE:
        raise RuntimeError(
            f"probe reset ABORTED: active scene is '{active or '?'}', not the "
            f"disposable '{PROBE_SCENE}'. Refusing to modify a non-disposable "
            f"scene. Open {PROBE_SCENE} in the editor (or restart Godot) and retry."
        )

    # Clear everything that isn't baseline. Root is "Main" in the clean baseline;
    # delete its non-baseline direct children (deletion cascades subtrees).
    try:
        h = await _godot_ai_call("scene_get_hierarchy", {"depth": 2})
        nodes = [n for n in h.get("nodes", []) if isinstance(n, dict)]
        roots = [n.get("path", "") for n in nodes if n.get("path", "").count("/") == 1]
        root_path = roots[0] if roots else "/Main"
        for n in nodes:
            path = n.get("path", "")
            if path.startswith(root_path + "/") and path.count("/") == 2 \
                    and n.get("name") not in _PROBE_BASELINE_NODES:
                try:
                    await _godot_ai_call("node_manage", {"op": "delete", "params": {"path": path}})
                except Exception:
                    pass
    except Exception:
        pass


# One real apply_spec feeds several Layer-2 probes — cache it per run so we
# pay for only one LLM plan, not one per probe.
_PIPELINE_CACHE: dict[str, Any] = {"data": None}


def _reset_probe_caches() -> None:
    _PIPELINE_CACHE["data"] = None


async def _pipeline_capture() -> dict:
    """Run the fixed DevForge prompt against a pristine probe scene ONCE and
    capture every stage's artifact (delta, ops, errors, scene diff)."""
    if _PIPELINE_CACHE["data"] is not None:
        return _PIPELINE_CACHE["data"]
    await _probe_scene_reset()
    before = await _scene_paths()
    t0 = time.time()
    raw = await _devforge_call("apply_spec", {"prompt": DEVFORGE_PROBE_PROMPT}, timeout_s=300)
    apply_ms = int((time.time() - t0) * 1000)
    artifact = raw
    aid = raw.get("artifact_id")
    if aid:
        try:
            artifact = await _devforge_call("read_artifact", {"artifact_id": aid}, timeout_s=30)
        except Exception:
            artifact = raw
    after = await _scene_paths()
    data = {"raw": raw, "artifact": artifact, "before": before, "after": after,
            "apply_ms": apply_ms, "model": read_env().get("MODEL_ALIAS", "?")}
    _PIPELINE_CACHE["data"] = data
    return data


# ── Layer 1: llama ───────────────────────────────────────────────

async def p_llama_throughput() -> dict:
    env = read_env()
    port = env.get("LLAMA_PORT", "8002")
    payload = {"prompt": "<|im_start|>user\nWrite one paragraph about a blacksmith's forge."
                         "<|im_end|>\n<|im_start|>assistant\n",
               "n_predict": 200, "temperature": 0.7}
    async with httpx.AsyncClient(timeout=120) as c:
        j = (await c.post(f"http://127.0.0.1:{port}/completion", json=payload)).json()
    t = j.get("timings", {})
    tps = round(t.get("predicted_per_second", 0), 1)
    data = dict(tok_per_sec=tps, gen_tok=t.get("predicted_n"),
                prompt_tok=t.get("prompt_n"),
                ttft_ms=round(t.get("prompt_ms", 0)),
                gen_ms=round(t.get("predicted_ms", 0)))
    if not tps:
        return _probe("broken", "no timings — server did not generate", "tok/s ≥15 works", **data)
    v = "works" if tps >= 15 else ("degraded" if tps >= 5 else "broken")
    return _probe(v, f"{tps} tok/s, TTFT {data['ttft_ms']} ms", "≥15 works · 5–15 degraded · <5 broken", **data)


async def p_llama_context() -> dict:
    env = read_env()
    port = env.get("LLAMA_PORT", "8002")
    async with httpx.AsyncClient(timeout=5) as c:
        p = (await c.get(f"http://127.0.0.1:{port}/props")).json()
    alias = p.get("model_alias")
    want = env.get("MODEL_ALIAS")
    loaded = (p.get("default_generation_settings") or {}).get("n_ctx") or p.get("n_ctx") or 0
    m = re.search(r"--ctx-size\s+(\d+)", env.get("LLAMA_ARGS", ""))
    configured = int(m.group(1)) if m else None
    km = re.search(r"--cache-type-k\s+(\S+)", env.get("LLAMA_ARGS", ""))
    data = dict(n_ctx_loaded=loaded, configured_ctx=configured,
                kv_cache=(km.group(1) if km else "f16"),
                model_alias=alias)
    if alias != want:
        return _probe("broken", f"serving '{alias}', config wants '{want}'",
                      "alias must match", **data)
    if configured and loaded < configured:
        return _probe("degraded",
                      f"ctx clamped to {loaded} (config asked {configured})",
                      "loaded==configured", **data)
    return _probe("works", f"ctx {loaded} ({data['kv_cache']} KV)", "loaded==configured", **data)


async def p_llama_grammar() -> dict:
    env = read_env()
    port = env.get("LLAMA_PORT", "8002")
    # Single-line alternation (multi-line GBNF can be silently dropped on this
    # stack) — the model MUST emit exactly one of the two tokens.
    payload = {"prompt": "<|im_start|>user\nPick a word.<|im_end|>\n<|im_start|>assistant\n",
               "n_predict": 8, "temperature": 1.2,
               "grammar": 'root ::= "FORGE" | "ANVIL"'}
    async with httpx.AsyncClient(timeout=60) as c:
        out = (await c.post(f"http://127.0.0.1:{port}/completion", json=payload)).json().get("content", "")
    honored = out.strip() in ("FORGE", "ANVIL")
    data = dict(raw_output=out, honored=honored)
    if honored:
        return _probe("works", f"grammar enforced exactly → {out.strip()!r}",
                      "output ∈ {FORGE,ANVIL}", **data)
    return _probe("broken",
                  f"grammar NOT enforced → {out!r} — DevForge plans run unconstrained",
                  "output ∈ {FORGE,ANVIL}", **data)


async def p_llama_thinking() -> dict:
    """Tests the thinking-suppression mechanism the chat path actually relies on.

    Qwen3 thinks by default — that's expected, not a bug. What matters is that
    `/no_think` (which the Odysseus persona appends via inject_suffix) suppresses
    it so chat answers directly instead of stalling in the think channel.
    """
    env = read_env()
    port = env.get("LLAMA_PORT", "8002")
    is_qwen = "qwen" in env.get("MODEL_ALIAS", "").lower()
    # Append the same switch the persona uses; harmless on non-Qwen models.
    content_msg = "Name one Godot 3D node type in one word." + (" /no_think" if is_qwen else "")
    payload = {"model": env.get("MODEL_ALIAS", "model"), "temperature": 0.2, "max_tokens": 400,
               "messages": [{"role": "user", "content": content_msg}]}
    async with httpx.AsyncClient(timeout=120) as c:
        ch = (await c.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=payload)).json()["choices"][0]
    content = ch["message"].get("content") or ""
    reasoning = ch["message"].get("reasoning_content") or ""
    data = dict(model_is_qwen=is_qwen, no_think_sent=is_qwen,
                content_chars=len(content), reasoning_chars=len(reasoning),
                finish_reason=ch.get("finish_reason"), content_sample=content[:80])
    if len(content) < 3:
        return _probe("broken",
                      f"empty answer ({len(reasoning)} chars reasoning) — thinking trap even with "
                      f"{'/no_think' if is_qwen else 'plain chat'}",
                      "/no_think → direct answer, no reasoning leak", **data)
    if is_qwen and len(reasoning) > 50:
        return _probe("degraded",
                      f"/no_think ignored — {len(reasoning)} chars leaked to think channel",
                      "/no_think → direct answer, no reasoning leak", **data)
    return _probe("works", f"answered directly in {len(content)} chars (reasoning {len(reasoning)})",
                  "/no_think → direct answer, no reasoning leak", **data)


async def p_llama_tools() -> dict:
    env = read_env()
    port = env.get("LLAMA_PORT", "8002")
    payload = {"model": env.get("MODEL_ALIAS", "model"), "temperature": 0.2,
               "messages": [{"role": "user", "content": "Read the scene hierarchy."}],
               "tools": [{"type": "function", "function": {
                   "name": "scene_get_hierarchy", "description": "list scene nodes",
                   "parameters": {"type": "object", "properties": {}}}}]}
    async with httpx.AsyncClient(timeout=180) as c:
        ch = (await c.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=payload)).json()["choices"][0]
    calls = ch["message"].get("tool_calls") or []
    name = calls[0]["function"]["name"] if calls else None
    text = ch["message"].get("content") or ""
    data = dict(emitted_tool_call=bool(calls), tool_name=name,
                finish_reason=ch.get("finish_reason"))
    if calls:
        return _probe("works", f"native tool call → {name}", "structured tool_call", **data)
    if "scene_get_hierarchy" in text:
        return _probe("degraded", "named the tool in prose but no structured call",
                      "structured tool_call", **data)
    return _probe("broken", "no tool intent — unsuitable for agent mode",
                  "structured tool_call", **data)


# ── Layer 2: DevForge ────────────────────────────────────────────

async def p_devforge_plan() -> dict:
    cap = await _pipeline_capture()
    art = cap["artifact"] if isinstance(cap["artifact"], dict) else {}
    delta = art.get("arch_delta", {}) or {}
    entities = delta.get("entities", []) or []
    names = [e.get("name") for e in entities if isinstance(e, dict)]
    types = [e.get("type") for e in entities if isinstance(e, dict)]
    apply_ms = cap.get("apply_ms", 0)
    model = cap.get("model", "?")
    stages = art.get("stage_latencies", {}) or {}
    plan_stage_ms = stages.get("architecture_planning", 0)
    compile_ms = stages.get("compilation", 0)
    plan_retries_val = art.get("plan_retries", 0)
    truncated = art.get("truncated", False)
    data = dict(entity_count=len(entities), names=names, types=types,
                systems=len(delta.get("systems", []) or []), parents=delta.get("parents", {}),
                apply_ms=apply_ms, model=model,
                plan_stage_ms=plan_stage_ms, compile_ms=compile_ms,
                plan_retries=plan_retries_val, stage_latencies=stages,
                truncated=truncated)
    if not entities:
        return _probe("broken", "planner produced an EMPTY delta (0 entities)",
                      "≥3 entities w/ valid types, planning <60s", **data)
    if len(entities) < 3:
        return _probe("degraded", f"only {len(entities)} of 3 expected entities: {names}",
                      "≥3 entities w/ valid types, planning <60s", **data)
    # Correct, but flag a slow planner — the model/DevForge-fit mismatch. The
    # 22B prose model (Cydonia) plans correctly but takes ~100s; qwen3-14b is
    # ~3× faster. For heavy building, swap to qwen3 in the hub first.
    if apply_ms > 60000:
        return _probe("degraded",
                      f"planned {len(entities)} entities but SLOW ({apply_ms//1000}s on '{model}') — "
                      f"swap to qwen3-14b for fast building",
                      "≥3 entities w/ valid types, planning <60s", **data)
    return _probe("works", f"planned {len(entities)} entities in {apply_ms//1000}s: {names}",
                  "≥3 entities w/ valid types, planning <60s", **data)


async def p_devforge_compile() -> dict:
    cap = await _pipeline_capture()
    art = cap["artifact"] if isinstance(cap["artifact"], dict) else {}
    ops = [o for o in art.get("operations", []) if isinstance(o, dict)]
    adds = [o for o in ops if o.get("type") == "add_node"]
    scaffold = {"MainCamera", "DirectionalLight"}
    requested = [o for o in adds if o.get("name") not in scaffold]
    parents = {o.get("name"): o.get("parent") for o in adds}
    bad = {n: p for n, p in parents.items() if p and not str(p).startswith("/root/Main")}
    covered = sorted({o.get("name") for o in requested} & PROBE_EXPECTED)
    data = dict(op_count=len(ops), requested_ops=[o.get("name") for o in requested],
                scaffold_ops=[o.get("name") for o in adds if o.get("name") in scaffold],
                parents=parents, bad_parents=bad,
                coverage=f"{len(covered)}/{len(PROBE_EXPECTED)}")
    if bad:
        return _probe("degraded", f"{len(bad)} op(s) with non-/root/Main parents: {bad}",
                      "requested ops present, parented /root/Main", **data)
    if not requested:
        return _probe("broken",
                      "compiler emitted ONLY scaffolding (camera/light) — none of "
                      f"{sorted(PROBE_EXPECTED)} requested",
                      "requested ops present, parented /root/Main", **data)
    if set(covered) >= PROBE_EXPECTED:
        return _probe("works", f"all {sorted(PROBE_EXPECTED)} compiled under /root/Main",
                      "requested ops present, parented /root/Main", **data)
    return _probe("degraded", f"only {covered} of {sorted(PROBE_EXPECTED)} compiled",
                  "requested ops present, parented /root/Main", **data)


async def p_devforge_execute() -> dict:
    cap = await _pipeline_capture()
    raw = cap["raw"]
    art = cap["artifact"] if isinstance(cap["artifact"], dict) else {}
    applied = raw.get("applied")
    total = raw.get("operations_total")
    errors = raw.get("errors") or []
    added = sorted(cap["after"] - cap["before"])
    added_names = {p.rsplit("/", 1)[-1] for p in added}
    built = sorted(added_names & PROBE_EXPECTED)
    truncated = art.get("truncated", False)
    data = dict(applied=applied, operations_total=total, error_count=len(errors),
                errors=errors[:5], nodes_added=added,
                requested_built=built, coverage=f"{len(built)}/{len(PROBE_EXPECTED)}",
                before_n=len(cap["before"]), after_n=len(cap["after"]),
                plan_retries=art.get("plan_retries", 0),
                repair_count=art.get("repair_count", 0),
                completeness_added=art.get("completeness_added", 0),
                truncated=truncated)
    if errors:
        return _probe("broken" if not added else "degraded",
                      f"{len(errors)} execution error(s): {errors[:2]}",
                      "requested nodes built, 0 errors", **data)
    if set(built) >= PROBE_EXPECTED:
        return _probe("works", f"built all {built}, +{len(added)} nodes, 0 errors",
                      "requested nodes built, 0 errors", **data)
    if built:
        return _probe("degraded", f"built only {built} of {sorted(PROBE_EXPECTED)}",
                      "requested nodes built, 0 errors", **data)
    return _probe("degraded",
                  f"applied {applied} op(s) but NONE requested — only scaffolding "
                  f"(+{len(added)} nodes: {added})",
                  "requested nodes built, 0 errors", **data)


async def p_devforge_completeness() -> dict:
    """Regression guard for the /root/Camera3D injector bug: the bare probe
    scene has no DirectionalLight3D, so completeness must inject one with a
    VALID /root/Main parent (not an arbitrary child path)."""
    cap = await _pipeline_capture()
    art = cap["artifact"] if isinstance(cap["artifact"], dict) else {}
    ops = [o for o in art.get("operations", []) if isinstance(o, dict)]
    injected = [o for o in ops if o.get("type") == "add_node"
                and o.get("node_type") in ("DirectionalLight3D", "Camera3D")
                and o.get("name") in ("DirectionalLight", "MainCamera")]
    parents = {o.get("name"): o.get("parent") for o in injected}
    bad = {n: p for n, p in parents.items() if p and not str(p).startswith("/root/Main")}
    errors = cap["raw"].get("errors") or []
    root_errs = [e for e in errors if "not found in scene" in str(e)]
    data = dict(injected=parents, bad_parents=bad, parent_errors=root_errs,
                completeness_added=art.get("completeness_added", 0))
    if bad or root_errs:
        return _probe("broken", f"injected node with invalid parent: {bad or root_errs}",
                      "injected nodes parented at /root/Main", **data)
    if not injected:
        return _probe("degraded", "no auto-injection observed (light may already exist)",
                      "injected nodes parented at /root/Main", **data)
    return _probe("works", f"auto-injected {parents} at valid parent",
                  "injected nodes parented at /root/Main", **data)


async def p_devforge_validate() -> dict:
    """Deterministic — no LLM. Feed validate_spec one good op and one with a
    nonexistent parent; the validator must accept the first and reject the second."""
    scene = {"name": "Main", "type": "Node3D", "children": []}
    ops = [
        {"type": "add_node", "parent": "/root/Main", "node_type": "Node3D", "name": "Good"},
        {"type": "add_node", "parent": "/root/Ghost", "node_type": "Node3D", "name": "Bad"},
    ]
    res = await _devforge_call("validate_spec",
                               {"operations": ops, "scene_tree": scene}, timeout_s=30)
    valid_n = res.get("valid_count")
    err_n = res.get("error_count")
    errors = res.get("errors", [])
    caught = any("Ghost" in str(e) for e in errors)
    data = dict(valid_count=valid_n, error_count=err_n, errors=errors, caught_bad_parent=caught)
    if valid_n == 1 and caught:
        return _probe("works", "accepted the valid op, rejected the bad parent",
                      "good→valid, bad→error", **data)
    if valid_n == 2:
        return _probe("degraded", "accepted BOTH ops — missed the nonexistent parent",
                      "good→valid, bad→error", **data)
    return _probe("broken", f"validator rejected the valid op (valid={valid_n})",
                  "good→valid, bad→error", **data)


async def p_devforge_roundtrip() -> dict:
    """DevForge's scene view must match godot-ai's for the same live scene."""
    await _probe_scene_reset()
    godot = await _scene_paths()
    d = await _devforge_call("get_scene", {}, timeout_s=30)
    scene = d.get("scene", d)

    def _count(node):
        n = 1
        for ch in (node.get("children") or []):
            n += _count(ch)
        return n
    df_n = _count(scene) if isinstance(scene, dict) and scene.get("name") else 0
    data = dict(devforge_nodes=df_n, godot_nodes=len(godot),
                devforge_root=scene.get("name") if isinstance(scene, dict) else None)
    if df_n == 0:
        return _probe("broken", "DevForge returned no scene tree", "counts match", **data)
    if df_n == len(godot):
        return _probe("works", f"both see {df_n} nodes (root '{data['devforge_root']}')",
                      "counts match", **data)
    return _probe("degraded", f"DevForge sees {df_n}, godot-ai sees {len(godot)}",
                  "counts match", **data)


# ── Layer 3: godot-ai (editor bridge) ────────────────────────────

async def p_godotai_latency() -> dict:
    """Write round-trip: create a node, verify it, delete it — with timings."""
    await _probe_scene_reset()
    t0 = time.time()
    await _godot_ai_call("node_create", {"parent_path": "/Main", "type": "Node3D", "name": "ProbePing"})
    create_ms = int((time.time() - t0) * 1000)
    verified = "/Main/ProbePing" in await _scene_paths()
    t1 = time.time()
    await _godot_ai_call("node_manage", {"op": "delete", "params": {"path": "/Main/ProbePing"}})
    delete_ms = int((time.time() - t1) * 1000)
    rt = create_ms + delete_ms
    data = dict(create_ms=create_ms, delete_ms=delete_ms, verified=verified)
    if not verified:
        return _probe("broken", "node_create did not produce the node", "verified, <1.5s round-trip", **data)
    v = "works" if rt < 1500 else ("degraded" if rt < 5000 else "broken")
    return _probe(v, f"create {create_ms} + delete {delete_ms} ms round-trip",
                  "verified · <1.5s works · <5s degraded", **data)


async def p_godotai_fidelity() -> dict:
    """The editor returns a faithful, walkable scene tree."""
    await _probe_scene_reset()
    h = await _godot_ai_call("scene_get_hierarchy", {"depth": 10})
    nodes = h.get("nodes", [])
    root = nodes[0].get("name") if nodes else None
    data = dict(node_count=len(nodes), root=root, has_more=h.get("has_more"),
                sample=[n.get("path") for n in nodes[:5]])
    if not nodes:
        return _probe("broken", "empty hierarchy — no scene or broken editor link",
                      "≥1 node, named root", **data)
    if root != "Main":
        return _probe("degraded", f"root is '{root}', expected 'Main'", "≥1 node, named root", **data)
    return _probe("works", f"{len(nodes)} nodes, root '{root}'", "≥1 node, named root", **data)


# ── Layer 4: Godot runtime ───────────────────────────────────────

async def p_runtime_launch() -> dict:
    """Does the game actually RUN? Launch the disposable scene, poll FPS until
    the game has booted (capture isn't ready instantly after project_run)."""
    await _probe_scene_reset()
    launched = False
    fps = 0
    capture_ready = False
    polls = 0
    try:
        await _godot_ai_call("project_run",
                             {"mode": "custom", "scene": PROBE_SCENE, "autosave": False})
        launched = True
        # Poll up to ~9s: the running game needs a moment before its monitors
        # report and game_capture_ready flips true.
        for polls in range(1, 7):
            await asyncio.sleep(1.5)
            try:
                st = await _godot_ai_call("editor_state", {})
                capture_ready = bool(st.get("game_capture_ready"))
            except Exception:
                pass
            try:
                mon = await _godot_ai_call("editor_manage",
                                           {"op": "monitors_get", "params": {"monitors": ["time/fps"]}})
                mdata = mon.get("data", mon)
                if isinstance(mdata, dict):
                    fps = mdata.get("time/fps", 0) or 0
            except Exception:
                pass
            if fps and fps > 0:
                break
    except Exception as e:
        return _probe("broken", f"failed to launch: {e}", "FPS>0, no errors",
                      launched=launched, fps=fps)
    finally:
        try:
            await _godot_ai_call("project_manage", {"op": "stop"})
        except Exception:
            pass
    data = dict(launched=launched, fps=fps, capture_ready=capture_ready, polls=polls)
    if fps and fps > 0:
        return _probe("works", f"running at {fps} FPS (after {polls} poll(s))", "FPS>0, no errors", **data)
    if capture_ready or launched:
        return _probe("degraded",
                      "launched + capture ready but FPS monitor read 0 (editor monitor quirk)"
                      if capture_ready else "launched but FPS stayed 0",
                      "FPS>0, no errors", **data)
    return _probe("broken", "did not launch", "FPS>0, no errors", **data)


# ── Layer 5: Odysseus (product consumer) ─────────────────────────

async def p_ody_persona() -> dict:
    """The live persona is the configured strategy prompt, not a clobbered husk."""
    try:
        c = json.loads(PRESETS.read_text()).get("custom", {})
    except Exception as e:
        return _probe("broken", f"can't read presets.json: {e}", "enabled, ~3.9k prompt", )
    sp = c.get("system_prompt") or ""
    suf = c.get("inject_suffix", "") or ""
    temp = float(c.get("temperature", 1.0))
    data = dict(enabled=bool(c.get("enabled")), system_prompt_chars=len(sp),
                temperature=temp, has_mcp="mcp" in suf.lower(),
                has_nothink="/no_think" in suf, character_name=c.get("character_name"))
    if not c.get("enabled") or len(sp) < 1000:
        return _probe("broken",
                      f"persona husk — enabled={data['enabled']}, prompt {len(sp)} chars",
                      "enabled, ~3.9k prompt, 'MCP'+/no_think", **data)
    minor = []
    if not data["has_mcp"]:
        minor.append("'MCP' missing from inject_suffix (tool retrieval won't run)")
    if not data["has_nothink"]:
        minor.append("/no_think missing")
    if temp > 0.35:
        minor.append(f"temp {temp} > 0.35")
    if minor:
        return _probe("degraded", "; ".join(minor), "enabled, ~3.9k prompt, 'MCP'+/no_think", **data)
    return _probe("works", f"enabled, {len(sp)} char prompt, temp {temp}, MCP+/no_think",
                  "enabled, ~3.9k prompt, 'MCP'+/no_think", **data)


async def p_ody_retrieval() -> dict:
    """Odysseus's tool index should surface apply_spec for a build request.

    Note: MCP tools enter the persistent Chroma collection only when the live
    agent runs index_mcp_tools (on the first chat turn after a (re)start) — a
    fresh probe process can't trigger that. So we inspect the persistent
    collection AND run retrieval, and distinguish a real miss from a cold index.
    """
    try:
        c = json.loads(PRESETS.read_text()).get("custom", {})
    except Exception:
        c = {}
    query = f"{c.get('inject_prefix', '')} {CUBE_PROMPT} {c.get('inject_suffix', '')}".strip()
    script = (
        "import sys, json; sys.path.insert(0, '/app')\n"
        "out = {}\n"
        "try:\n"
        "    from src.tool_index import get_tool_index, COLLECTION_NAME\n"
        "    from src.embedding_lanes import build_embedding_lanes\n"
        "    mcp_in_coll = False; counts = {}\n"
        "    for ln in build_embedding_lanes(COLLECTION_NAME):\n"
        "        try:\n"
        "            ids = ln.collection.get().get('ids', [])\n"
        "            counts[ln.name] = len(ids)\n"
        "            if any('apply_spec' in str(i) or str(i).startswith('mcp__') for i in ids): mcp_in_coll = True\n"
        "        except Exception: pass\n"
        "    out['lane_counts'] = counts; out['mcp_in_collection'] = mcp_in_coll\n"
        "    idx = get_tool_index()\n"
        f"    out['retrieved'] = sorted(idx.get_tools_for_query({query!r}, 8)) if idx else []\n"
        "except Exception as e:\n"
        "    out['error'] = type(e).__name__ + ': ' + str(e)[:160]\n"
        "print(json.dumps(out))\n"
    )
    code, out = await _sh("docker", "exec", ODY_CONTAINER, "python", "-c", script, timeout=90)
    if code != 0:
        return _probe("broken", f"retrieval probe failed in container: {out.strip()[:120]}",
                      "apply_spec retrievable (or index warm)")
    try:
        res = json.loads(out.strip().splitlines()[-1])
    except Exception:
        return _probe("broken", f"unparseable retrieval output: {out.strip()[:120]}",
                      "apply_spec retrievable (or index warm)")
    tools = res.get("retrieved", [])
    mcp = [t for t in tools if t.startswith("mcp__")]
    data = dict(retrieved=tools, mcp_tools=mcp,
                apply_spec_present="mcp__devforge__apply_spec" in tools,
                mcp_in_collection=res.get("mcp_in_collection"),
                lane_counts=res.get("lane_counts"), error=res.get("error"))
    if data["apply_spec_present"]:
        return _probe("works", f"apply_spec retrieved (MCP in top-k: {mcp})",
                      "apply_spec retrievable", **data)
    if not res.get("mcp_in_collection"):
        return _probe("degraded",
                      "MCP tools not yet in the index — they index on the first agent chat "
                      "after a restart (run one chat turn to warm it)",
                      "apply_spec retrievable (or index warm)", **data)
    if mcp:
        return _probe("degraded", f"MCP tools indexed but apply_spec not in top-k: {mcp}",
                      "apply_spec retrievable", **data)
    return _probe("broken", "MCP tools indexed but none retrieved for a build query",
                  "apply_spec retrievable", **data)


# ── probe registry + runner ──────────────────────────────────────

PROBES: list[dict] = [
    # Layer 1 — llama
    dict(id="llama.throughput", layer="llama", speed="fast", fn=p_llama_throughput,
         title="Generation throughput",
         desc="Tokens/sec and time-to-first-token for a fixed completion."),
    dict(id="llama.context", layer="llama", speed="fast", fn=p_llama_context,
         title="Context window actually loaded",
         desc="The n_ctx in memory vs what stack.env configured (catches silent clamping)."),
    dict(id="llama.grammar", layer="llama", speed="fast", fn=p_llama_grammar,
         title="Grammar enforcement",
         desc="Does the server hold output to a GBNF grammar? The planner depends on it."),
    dict(id="llama.thinking", layer="llama", speed="slow", fn=p_llama_thinking,
         title="Answer vs hidden reasoning",
         desc="Content chars vs reasoning chars — catches the thinking-trap (empty answer)."),
    dict(id="llama.tools", layer="llama", speed="slow", fn=p_llama_tools,
         title="Native tool calling",
         desc="Does the model emit a structured tool call for an obvious tool task?"),
    # Layer 2 — DevForge
    dict(id="devforge.plan", layer="devforge", speed="slow", fn=p_devforge_plan,
         title="Planner architecture delta",
         desc="The entities/types the planner produces for a fixed prompt (shares one apply_spec)."),
    dict(id="devforge.compile", layer="devforge", speed="slow", fn=p_devforge_compile,
         title="Compiler operations + parent paths",
         desc="The add_node ops the compiler emits and whether they parent under /root/Main."),
    dict(id="devforge.completeness", layer="devforge", speed="slow", fn=p_devforge_completeness,
         title="Completeness injector parents",
         desc="Auto-injected camera/light must use a valid /root/Main parent (regression guard)."),
    dict(id="devforge.execute", layer="devforge", speed="slow", fn=p_devforge_execute,
         title="Full apply_spec execution",
         desc="ops applied, errors, and the actual nodes added to the scene."),
    dict(id="devforge.validate", layer="devforge", speed="fast", fn=p_devforge_validate,
         title="Validator accept/reject",
         desc="Deterministic: accepts a valid op, rejects a nonexistent parent. No LLM."),
    dict(id="devforge.roundtrip", layer="devforge", speed="fast", fn=p_devforge_roundtrip,
         title="Scene view parity",
         desc="DevForge's scene tree matches godot-ai's for the same live scene."),
    # Layer 3 — godot-ai
    dict(id="godotai.latency", layer="godot-ai", speed="fast", fn=p_godotai_latency,
         title="Write round-trip latency",
         desc="Time to create + verify + delete a node through the editor bridge."),
    dict(id="godotai.fidelity", layer="godot-ai", speed="fast", fn=p_godotai_fidelity,
         title="Scene tree fidelity",
         desc="The editor returns a faithful, walkable hierarchy with a named root."),
    # Layer 4 — runtime
    dict(id="runtime.launch", layer="runtime", speed="slow", fn=p_runtime_launch,
         title="Game actually runs",
         desc="Launches the disposable scene and reads FPS — proves the project boots."),
    # Layer 5 — odysseus
    dict(id="odysseus.persona", layer="odysseus", speed="fast", fn=p_ody_persona,
         title="Live persona is the real prompt",
         desc="The active persona is the full strategy prompt with MCP/no_think, not a husk."),
    dict(id="odysseus.retrieval", layer="odysseus", speed="slow", fn=p_ody_retrieval,
         title="Tool retrieval surfaces apply_spec",
         desc="Odysseus's tool index returns apply_spec for a build request (else the model can't build)."),
]


async def run_probes(ids: list[str], emit: Callable[[str], None]) -> dict:
    """Run selected probes in chain order, emit progress, save + return data."""
    by_id = {p["id"]: p for p in PROBES}
    env = read_env()
    _reset_probe_caches()
    run = {
        "kind": "probe",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": env.get("MODEL_ALIAS", "?"),
        "template": env.get("DEVFORGE_PROMPT_TEMPLATE", "?"),
        "probes": [],
    }
    # Preserve registry (chain) order regardless of selection order.
    ordered = [p["id"] for p in PROBES if p["id"] in set(ids)]
    counts = {"works": 0, "degraded": 0, "broken": 0, "skip": 0}
    by_layer: dict[str, list[str]] = {}
    total = len(ordered)
    for i, pid in enumerate(ordered):
        p = by_id[pid]
        emit(f"[probe:run] {i+1}/{total} {pid}")
        emit(f"▶ {pid} — {p['title']}")
        t0 = time.time()
        try:
            res = await asyncio.wait_for(p["fn"](), timeout=300)
        except Exception as e:
            res = _probe("broken", f"probe crashed: {type(e).__name__}: {e}")
        ms = int((time.time() - t0) * 1000)
        res.update(id=pid, ms=ms, layer=p["layer"], title=p["title"])
        run["probes"].append(res)
        v = res.get("verdict", "broken")
        counts[v] = counts.get(v, 0) + 1
        by_layer.setdefault(p["layer"], []).append(v)
        emit(f"  [{v.upper()}] ({ms} ms) {res.get('summary','')}")
    # If any DevForge/runtime probe touched the disposable probe scene, leave
    # the editor back on the real game scene.
    if any(by_id[i]["layer"] in ("devforge", "godot-ai", "runtime") for i in ordered):
        try:
            await _godot_ai_call("scene_open", {"path": PROBE_SCENE})
            await _godot_ai_call("scene_open", {"path": PROBE_BASE_SCENE})
        except Exception:
            pass
    run["counts"] = counts
    run["layer_rollup"] = {lyr: _worst(vs) for lyr, vs in by_layer.items()}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / f"probe-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(run, indent=2))
    emit(f"[probe:done] {counts['works']} works / {counts['degraded']} degraded / "
         f"{counts['broken']} broken → {out.name}")
    return run


def probe_history(limit: int = 30) -> list[dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    runs = []
    for f in sorted(DATA_DIR.glob("probe-*.json"), reverse=True)[:limit]:
        try:
            d = json.loads(f.read_text())
            runs.append({"file": f.name, "ts": d.get("ts"), "model": d.get("model"),
                         "counts": d.get("counts"), "layer_rollup": d.get("layer_rollup")})
        except Exception:
            continue
    return runs


PROBE_BUNDLES = {
    "llama layer": [p["id"] for p in PROBES if p["layer"] == "llama"],
    "devforge layer": [p["id"] for p in PROBES if p["layer"] == "devforge"],
    "fast probes": [p["id"] for p in PROBES if p["speed"] == "fast"],
    "everything": [p["id"] for p in PROBES],
}


# ── CLI ──────────────────────────────────────────────────────────

def _cli() -> None:
    """Standalone runner. Default action is the deep probe suite.

    Usage:
      python bench.py --probe [--layer llama|devforge|godot-ai|runtime|odysseus]
      python bench.py --probe --only llama.grammar,devforge.plan
      python bench.py --list
    """
    import sys
    args = sys.argv[1:]

    if "--list" in args:
        print("Probes (chain order):")
        for p in PROBES:
            print(f"  {p['id']:24s} [{p['layer']:9s}] {p['title']}")
        return

    # Default to --probe even if not passed, so `python bench.py` is useful.
    ids = [p["id"] for p in PROBES]
    if "--layer" in args:
        lyr = args[args.index("--layer") + 1]
        ids = [p["id"] for p in PROBES if p["layer"] == lyr]
    if "--only" in args:
        want = set(args[args.index("--only") + 1].split(","))
        ids = [p["id"] for p in PROBES if p["id"] in want]

    if not ids:
        print("no probes matched — try --list")
        return

    def emit(line: str) -> None:
        # Skip the control markers in CLI output; keep the human lines.
        if not line.startswith("[probe:run]"):
            print(line)

    run = asyncio.run(run_probes(ids, emit))
    roll = run.get("layer_rollup", {})
    print("\nLayer rollup:", ", ".join(f"{k}={v}" for k, v in roll.items()))


if __name__ == "__main__":
    _cli()
