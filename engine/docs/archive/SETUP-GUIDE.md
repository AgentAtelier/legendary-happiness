<!-- ARCHIVED — see ~/dev/games/Forge/FORGE-STACK.md for current documentation -->

# DevForge End-to-End Setup Guide

> **🤖 AI Handoff:** This document is designed to be given to a chat AI. Copy this entire file into your chat and say:
> *"Follow this SETUP-GUIDE.md to help me start DevForge end-to-end. I have llama.cpp, Godot, godot-ai, and Odysseus installed but not yet wired together. Walk me through each step, checking connections as we go. Start by asking me what's already running."*

**Goal:** Bring Odysseus, llama.cpp, DevForge, godot-ai, and Godot together so you can type a natural-language prompt and see it become a running Godot game.

**Last updated:** June 10, 2026

---

## 1. Architecture — How the Pieces Connect

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│  ┌──────────┐     MCP (SSE)      ┌───────────────────┐          │
│  │ Odysseus │ ────────────────── │ DevForge MCP Srv  │          │
│  │ (agent)  │   apply_spec()     │ (mcp_server.py)   │          │
│  └──────────┘                    │ port 8001         │          │
│                                  └───────┬───────────┘          │
│                                          │                       │
│                          ┌───────────────┼───────────────┐      │
│                          │               │               │      │
│                          ▼               ▼               ▼      │
│                   ┌──────────┐  ┌──────────────┐ ┌───────────┐ │
│                   │ llama.cpp│  │ PipelineEng. │ │ GodotAIMCP │ │
│                   │ :8080    │  │ (planning)   │ │ Executor   │ │
│                   └──────────┘  └──────────────┘ └─────┬─────┘ │
│                                                        │       │
│                                          MCP (SSE)     │       │
│                                          batch_execute │       │
│                                                        ▼       │
│                                            ┌─────────────────┐ │
│                                            │ godot-ai MCP    │ │
│                                            │ :8000/mcp       │ │
│                                            └────────┬────────┘ │
│                                                     │          │
│                                                     ▼          │
│                                            ┌─────────────────┐ │
│                                            │ Godot Engine    │ │
│                                            │ (live scene)    │ │
│                                            └─────────────────┘ │
│                                                                  │
│  Alternative path (no Odysseus):                                 │
│  Godot Plugin (devforge_panel.gd) ──HTTP── DevForge FastAPI     │
│  (in-editor panel)                   :8000   (server.py)        │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### What Each System Does

| System | Role | Port | How to check it's running |
|--------|------|------|---------------------------|
| **llama.cpp** | LLM inference backend (runs the Gemma 4B model) | 8080 | `curl localhost:8080/health` |
| **Godot** | Game engine — runs the scene, executes operations | N/A | Godot editor window with a scene open |
| **godot-ai** | MCP bridge between external tools and Godot | 8000 | `curl localhost:8000/mcp` |
| **DevForge MCP** | Pipeline as MCP tools (for Odysseus) | 8001 | `curl -H "Accept: text/event-stream" --max-time 2 localhost:8001/sse` |
| **DevForge FastAPI** | Pipeline as HTTP API (for Godot plugin) | 8000 | `curl localhost:8000/` |
| **Odysseus** | AI agent framework — discovers & calls MCP tools | varies | Odysseus admin UI |

> **⚠️ Port conflict note:** DevForge FastAPI and godot-ai both default to port 8000. If running the FastAPI server, either change its port or use the MCP server on 8001 instead. The MCP server is what Odysseus connects to.

### The Two Paths

**Path A — Godot Plugin (simpler):**
```
Godot Panel → HTTP → DevForge FastAPI :8000 → Pipeline → PluginExecutor → Godot Plugin executes ops
```
Used for: direct in-editor usage. You type a prompt in the DevForge panel in Godot, it sends it to the server, receives operations, and executes them in the editor.

**Path B — MCP/Odysseus (autonomous):**
```
Odysseus → MCP → DevForge MCP :8001 → Pipeline → GodotAIMCPExecutor → godot-ai MCP :8000 → Godot
```
Used for: agent-driven game building. Odysseus calls `apply_spec` with a prompt, DevForge plans and generates operations, sends them to godot-ai which executes them in the live Godot engine.

**Path C — Direct test script:**
```
Python → MCP → DevForge MCP :8001 → Pipeline → GodotAIMCPExecutor → godot-ai → Godot
```
Used for: automated testing. Our `tests/integration/test_smoke.py` and `test_forgeborn.py` use this path.

---

## 2. Prerequisites — What Must Be Installed

### On your machine

| Tool | How to check | Install if missing |
|------|-------------|-------------------|
| Python 3.10+ | `python --version` | `apt install python3.11` or pyenv |
| Godot 4.x | `godot --version` | [godotengine.org](https://godotengine.org/download) |
| Git | `git --version` | `apt install git` |
| curl | `curl --version` | `apt install curl` |
| lsof | `lsof -v` | `apt install lsof` |

### Python packages (in DevForge's venv)

```bash
cd terraforge-master/terraforge-master
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# If mcp/fastapi/uvicorn are NOT in requirements.txt, add them:
pip install mcp fastapi uvicorn
```

### llama.cpp

You need the llama.cpp server running with the Gemma 4B MoE model. This is separate from DevForge.

**What I know:** The server needs to be running on `localhost:8080` with the `/completion` and `/tokenize` endpoints available. The model is `unsloth/gemma-4-26B-A4B-it-qat-GGUF` (MoE, 26B total, 4B active, QAT 4-bit quantized).

**What I'm not 100% sure about:**
- The exact `llama-server` command line used to start it (model path, context size, GPU layers)
- Whether it needs `--grammar` support compiled in (most builds include it)
- The exact GGUF file path on your system

You can check if it's running:
```bash
curl localhost:8080/health
# Should return {"status": "ok"} or similar
```

### godot-ai

This is the MCP bridge that lets external tools talk to Godot. It runs as an MCP server that connects to a running Godot instance.

**What I know:** It runs on port 8000, exposes an MCP endpoint at `/mcp`, and provides tools like `batch_execute`, `godot://scene/hierarchy`, `logs_read`, and `node_get_properties`. DevForge's `GodotAIMCPExecutor` connects to it via SSE.

**What I'm not 100% sure about:**
- How godot-ai connects to Godot (WebSocket? Editor plugin? Headless runner?)
- The exact command to start godot-ai
- Whether it needs Godot to be running in editor mode or if it can work headless

You can check if it's running:
```bash
curl localhost:8000/mcp
# Should return something (even an error is good — means it's listening)
```

### Odysseus

The AI agent framework. It discovers MCP servers and calls their tools.

**What I know:** Odysseus registers MCP servers via its admin Settings UI (not a static JSON file). The DevForge MCP server needs to be registered with the URL `http://localhost:8001/sse`.

**What I'm not 100% sure about:**
- How Odysseus is started/run on your system
- The exact UI path for registering an MCP server
- Whether Odysseus has any special configuration for DevForge

---

## 3. Environment Variables

Set these before starting any DevForge server:

```bash
# Required — LLM backend
export DEVFORGE_LLAMA_ENDPOINT="http://localhost:8080"

# Required for Path B (MCP/Odysseus) — use godot-ai executor
export DEVFORGE_EXECUTOR_BACKEND="godot_ai_mcp"
export DEVFORGE_GODOT_AI_MCP_URL="http://localhost:8000/mcp"

# Optional — grammar path (auto-discovered if not set)
export DEVFORGE_GRAMMAR_PATH=""

# Optional — game root for file creation
export DEVFORGE_GAME_ROOT="./dev-forge"

# Optional — debug logging
export DEVFORGE_DEBUG="1"
```

**For Path A (Godot Plugin):** Use the default executor backend:
```bash
export DEVFORGE_EXECUTOR_BACKEND="devforge_plugin"
```

---

## 4. Step-by-Step Startup Sequence

Start these in order. Each depends on the previous.

### Step 1: Start llama.cpp

```bash
# Your llama.cpp server command — this is what I'm UNSURE about
# Something like:
llama-server \
  -m /path/to/gemma-4-26B-A4B-it-qat.gguf \
  --host 0.0.0.0 --port 8080 \
  --ctx-size 32768 \
  --n-gpu-layers 99
```

Verify: `curl localhost:8080/health`

### Step 2: Start Godot

Open your Godot project (the one at `terraforge-master/terraforge-master/`). Make sure a scene is open in the editor.

> **⚠️ Important:** The DevForge plugin needs a scene to work with. If no scene is open, operations can't be applied.

### Step 3: Start godot-ai

```bash
# This is what I'm UNSURE about — the exact command
# Something like:
cd /path/to/godot-ai
python -m godot_ai --mcp --port 8000
```

Verify: `curl localhost:8000/mcp` (should respond, even with an error)

### Step 4: Start DevForge

> **⚠️ Port 8000 conflict:** godot-ai already uses port 8000. If you try to start DevForge FastAPI on 8000 too, it will fail with "address already in use." Either use the MCP server on port 8001 (Option B below), or start FastAPI on a different port: `uvicorn ... --port 8002`.

**Option A — FastAPI server (for Godot plugin, Path A):**

```bash
cd terraforge-master/terraforge-master
source .venv/bin/activate
export DEVFORGE_EXECUTOR_BACKEND="devforge_plugin"
uvicorn devforge.platform.server.server:app --reload --port 8000
```

Then in Godot, open the DevForge panel and type a prompt.

**Option B — MCP server (for Odysseus/test scripts, Path B):**

```bash
cd terraforge-master/terraforge-master
source .venv/bin/activate
export DEVFORGE_EXECUTOR_BACKEND="godot_ai_mcp"
export DEVFORGE_GODOT_AI_MCP_URL="http://localhost:8000/mcp"
python -c "
from devforge.platform.mcp_server import mcp
mcp.run(transport='sse')
"
```

Or use our launcher script:
```bash
cd /path/to/Forge
./scripts/run_integration_test.sh smoke
```

### Step 5: Register with Odysseus (Path B only)

In the Odysseus admin UI:
1. Go to Settings → MCP Servers
2. Add a new server with URL: `http://localhost:8001/sse`
3. Name it "DevForge"

> **⚠️ This is what I'm UNSURE about:** The exact Odysseus UI path and configuration format. The DevForge MCP server docs say "Registered in Odysseus via its admin Settings UI (not a static JSON file)."

### Step 6: Test the full chain

**Smoke test (Path B):**
```bash
cd /path/to/Forge
./scripts/run_integration_test.sh smoke
```

**Forgeborn game build (Path B):**
```bash
./scripts/run_integration_test.sh forgeborn --stop-on-failure
```

**Single custom prompt (Path B):**
```bash
cd terraforge-master/terraforge-master
source .venv/bin/activate
python tests/integration/test_smoke.py --prompt "Add a Camera3D named MainCamera to the scene" --mcp-url http://localhost:8001/sse
```

---

## 5. Testing Each Connection Point

Before running the full chain, verify each connection works:

| Connection | Test command | Expected result |
|-----------|-------------|-----------------|
| llama.cpp | `curl localhost:8080/health` | `{"status": "ok"}` |
| Godot running | Check editor window | Scene visible in editor |
| godot-ai → Godot | `curl localhost:8000/mcp` | MCP endpoint responds |
| DevForge → llama.cpp | `curl localhost:8000/` | `{"status": "ok", "llm_configured": true}` |
| DevForge → godot-ai | Run smoke test | Operations executed |
| Odysseus → DevForge | Call `apply_spec` from Odysseus | Operations returned |

---

## 6. The Forgeborn Game Build

Once everything is running, the game build is an 8-step prompt sequence:

```bash
./scripts/run_integration_test.sh forgeborn --stop-on-failure
```

This builds the "First Cold" game step by step:
1. Scene Setup (ground, lighting, world environment)
2. Player Character (CharacterBody3D with WASD movement)
3. UI (warmth bar)
4. Campfire with Heat Zone
5. Warmth System (drain/recover, lose condition)
6. Cabin (win condition)
7. Win/Lose Screens
8. Atmosphere Tuning (fog, lighting)

Each step builds on the previous. If a step fails, `--stop-on-failure` prevents cascading failures.

You can also resume from a specific step:
```bash
./scripts/run_integration_test.sh forgeborn --start-at 4
```

Or preview the prompts without executing:
```bash
./scripts/run_integration_test.sh forgeborn --dry-run
```

---

## 7. Troubleshooting

### "LLM backend not configured"
- llama.cpp is not running or not reachable at `localhost:8080`
- Check with `curl localhost:8080/health`

### "Cannot connect to llama.cpp"
- llama.cpp server crashed or port changed
- Check the llama.cpp server logs

### "MCP connection error"
- godot-ai is not running at the configured URL
- Check `DEVFORGE_GODOT_AI_MCP_URL` env var
- Try `curl localhost:8000/mcp`

### "No game scene open"
- Godot editor doesn't have a scene open
- Open or create a scene in the Godot editor

### "DevForgePluginExecutor is not supported via MCP"
- You're using the MCP server with the wrong executor backend
- Set `DEVFORGE_EXECUTOR_BACKEND=godot_ai_mcp`

### "Grammar self-test FAILED"
- The GBNF grammar has an error that llama.cpp silently ignores
- Check the grammar files in `devforge/reasoning/prompts/`
- Try a simpler grammar to isolate the issue

### "Operations generated but nothing changed in Godot"
- `DEVFORGE_EXECUTOR_BACKEND` is set to `devforge_plugin` but you're using the MCP server → change to `godot_ai_mcp`
- godot-ai is running but not actually connected to a live Godot instance → check godot-ai logs for Godot connection status
- The Godot DevForge plugin isn't enabled → check Project Settings → Plugins → DevForge AI

### Port conflicts
- godot-ai uses port 8000
- DevForge FastAPI defaults to 8000 (conflict!)
- DevForge MCP defaults to 8001 (safe)
- If running both, use MCP server on 8001, or change FastAPI with `--port 8002`

---

## 8. What I Know vs What I'm Unsure About

### ✅ I'm confident about:
- The DevForge pipeline works (38/38 tests pass)
- The grammar files are correct and loaded properly
- The MCP server exposes the right tools (`apply_spec`, `validate_spec`, `get_scene`)
- The GodotAIMCPExecutor correctly calls godot-ai's `batch_execute`, `scene/hierarchy`, and `logs_read`
- The integration test scripts work (compile clean, use correct MCP SSE protocol)
- The escalating retry logic works in both engine.py and preview_api.py
- All 11 Claude Opus recommendations are implemented
- The env vars and config are correct (`DEVFORGE_EXECUTOR_BACKEND`, `DEVFORGE_GODOT_AI_MCP_URL`, etc.)

### ⚠️ I'm less sure about:
- **llama.cpp startup command** — the exact model path, context size, GPU layer count, and any special flags needed
- **godot-ai startup** — the exact command, how it connects to Godot (WebSocket? plugin?), whether it needs Godot in editor mode
- **Odysseus MCP registration** — the exact UI path, configuration format, and whether any extra setup is needed
- **Godot project configuration** — whether the DevForge plugin is enabled in the Godot project, whether the project.godot file needs updating
- **File paths** — whether the game root (`./dev-forge`) exists and has the right structure, whether scripts get created in the right place

---

## 9. Quick Reference — Commands

```bash
# Start everything (all in separate terminals)
# Terminal 1: llama.cpp
llama-server -m /path/to/model.gguf --port 8080 --ctx-size 32768

# Terminal 2: Godot (open project, enable DevForge plugin)
godot --editor /path/to/terraforge-master/terraforge-master/project.godot

# Terminal 3: godot-ai
cd /path/to/godot-ai && python -m godot_ai --mcp --port 8000

# Terminal 4: DevForge MCP server
cd /path/to/Forge && ./scripts/run_integration_test.sh smoke

# Terminal 5: Run tests
cd /path/to/Forge && ./scripts/run_integration_test.sh forgeborn --stop-on-failure
```

---

*Give this guide to your chat AI. It has enough context to help you set everything up and debug issues.*
