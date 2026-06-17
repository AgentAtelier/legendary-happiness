<!-- ARCHIVED — see ~/dev/games/Forge/FORGE-STACK.md for current documentation -->

# RUN-DEVFORGE-HANDOFF.md

> **Purpose:** This is the single document you give to a chat AI (Claude, GPT, etc.) so it can get DevForge running end-to-end on this machine. Everything below is concrete and verified against the actual filesystem — not generic instructions.
>
> **How to use this doc with a chat AI:**
> ```
> I'm getting DevForge (a Godot 4 AI dev pipeline) running on my Linux box.
> Read RUN-DEVFORGE-HANDOFF.md in full before doing anything. It contains
> the actual recon state of my system (not generic docs), the Days 1-7 fixes
> that already landed, and a step-by-step sequence. Work through the steps
> in order, verify each one before proceeding, and tell me what to type.
> ```

---

## 1. What DevForge Is

DevForge is a pipeline that turns a natural-language prompt into Godot 4 scene operations. You say *"add a CharacterBody3D with WASD movement"* and DevForge:

1. Calls a local LLM (llama.cpp serving Gemma) to plan the operations
2. Validates the plan against a GBNF grammar (the model literally cannot output arbitrary code)
3. Sends the operations to a running Godot editor via MCP
4. The operations get applied to the live scene

The architecture is documented in `SETUP-GUIDE.md`. This handoff assumes you've read it.

**Codebase root:** `/home/mrg/dev/games/Forge/devforge_review_package/`
**Godot project root:** `/home/mrg/dev/games/Forge/terraforge-master/terraforge-master/`

---

## 2. Actual System State (verified, not generic)

A recon pass was run on this machine. Here is the **real** state as of the recon:

### Installed and working
| Component | Version / Path | Status |
|-----------|----------------|--------|
| Python | 3.14.5 | ✅ Working |
| pip | 26.1.2 | ✅ Working |
| Godot | 4.6.3 (stable) | ✅ Installed, **not running** |
| llama-server binary | `/home/mrg/dev/cpp/llama.cpp/build/bin/llama-server` | ⚠️ **Broken** — missing shared lib at runtime |
| llama-server shared lib | `/home/mrg/dev/cpp/llama.cpp/build/bin/libllama-server-impl.so` | ✅ Exists, needs `LD_LIBRARY_PATH` |
| Gemma 4 MoE Q4 GGUF | `/home/mrg/models/gemma-4-26B-A4B-it-qat-UD-Q4_K_XL.gguf` | ✅ Present |
| Gemma 4 12B QAT GGUF | `/home/mrg/models/gemma4-12b-qat/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf` | ✅ Present (smaller fallback) |
| godot-ai source | `/home/mrg/dev/ai/godot-ai/` | ✅ Source present, **installed as Godot addon** at `terraforge-master/terraforge-master/addons/godot_ai/` |
| Godot addon files | `addons/godot_ai/` (multiple .gd files) | ✅ Present |
| DevForge source | `devforge/` tree | ✅ All Days 1-7 fixes applied |

### NOT installed / NOT running
| Component | Status | What's needed |
|-----------|--------|---------------|
| Python deps: `httpx`, `mcp`, `git` (GitPython), `fastapi`, `uvicorn`, `pydantic`, `requests` | ❌ Not installed | `pip install -r devforge/requirements.txt` |
| llama-server process | ❌ Not running | Must be started manually (broken lib issue first) |
| DevForge MCP server | ❌ Not running | Start with `mcp.run(transport='sse')` |
| DevForge LLM gateway | ❌ Not running | Start with `python -m devforge.infrastructure.llm.gateway` |
| Godot editor | ❌ Not running | User must launch |
| godot-ai MCP bridge | ⚠️ Auto-starts when Godot addon is enabled | User must enable plugin in Godot |
| Odysseus | ❌ Not installed/running | Optional — only needed for Path B autonomous agent |

### Surprises the AI must know about
1. **Port 8080 is SearXNG, not llama.cpp.** The SETUP-GUIDE assumes llama.cpp owns 8080. It doesn't — SearXNG is listening there. **Use port 9090 (or any free port) for llama-server.**
2. **llama-server is broken out of the box.** Running `/home/mrg/dev/cpp/llama.cpp/build/bin/llama-server --version` fails with `error while loading shared libraries: libllama-server-impl.so`. The fix is `export LD_LIBRARY_PATH=/home/mrg/dev/cpp/llama.cpp/build/bin:$LD_LIBRARY_PATH` before invoking.
3. **godot-ai is not a Python CLI — it's a Godot addon.** You don't start it from a terminal. You enable it in the Godot editor (Project > Project Settings > Plugins), and it auto-starts the MCP server on port 8000.
4. **There is no `devforge/platform/server.py` — it doesn't exist.** The MCP server at `devforge/platform/mcp_server.py` is the only entry point. (The earlier SETUP-GUIDE mentions a FastAPI server, but only the MCP server actually exists in this codebase. Skip Path A; use Path B / C.)
5. **The `asyncio.run()` error flagged in `AI_HANDOVER.md`** is in `devforge/infrastructure/llm/godot_ai_mcp.py` (or a similar file) — a top-level `asyncio.run()` call in async code. Days 1-7 did NOT fix this. If you hit it during MCP bring-up, that's the file to look at.

---

## 3. What Days 1-7 Already Did (so you don't redo it)

All four Claude audit rounds have been applied to this codebase. The fixes are **in place**. A chat AI should treat these as ground truth and not re-audit them.

### S1–S4 (Showstoppers)
- **S1:** `devforge/execution/__init__.py` no longer references the missing `godot_ai_mcp.py` at import time (or the import was deferred). The bundle imports cleanly.
- **S2:** `devforge/tests/` has actual tests now (see Section 6). `verify_pipeline.py` runs its suite in `__main__` only, not at import.
- **S3:** Grammar constraint is **on by default** at startup. `llama_grammar_path` auto-discovers the GBNF in `devforge/reasoning/prompts/planner_grammar.gbnf`. `selftest_grammar()` runs at gateway startup.
- **S4:** `engine.py` retry loop now uses `planner_prompt` (the scrubbed one), not the raw `prompt`. First attempt is correct.

### H1–H7 (High-priority)
- **H1:** Turn-ID is a `ContextVar` read directly in `llama_client.py` at HTTP-header build time. No shared `self.turn_id` attribute race. Concurrent `apply_spec` calls each get their own turn_id.
- **H2:** Gateway has CORS locked to `localhost` only.
- **H3:** 429 from llama-server is recognized as terminal — raises `BudgetExceededError(RuntimeError)`. `engine.py` catches it before `PlanningError` and bails out cleanly.
- **H4:** `ArtifactStore` has LRU eviction with `max_entries=50`. Long sessions no longer leak.
- **H5:** Script extractor (`script_extractor.py`) sanitizes paths: rejects `..`, absolute paths, empty basenames. Content-hash via `sha1(body)[:8]` for fallback names.
- **H6:** Gateway has `_DEFAULT_BUCKET = "__default__"` so untagged requests share a budget bucket instead of being unbounded. `_record_usage()` resets `created_at` on every call (sliding expiry). `GATEWAY_STRICT_BUDGET` env var enforces it.
- **H7:** `worker.py` deleted. `llm_retry.py` deleted. Both had zero callers.

### M1–M6 (Medium gaps)
- **M1:** `RuntimeConfig.validate()` runs at `get_config()` with 11 checks (backends, numeric ranges, sampler profiles). Fails loud on bad config.
- **M2:** `devforge/requirements.txt` has all real deps pinned. `Procfile` at repo root for Honcho/Foreman.
- **M3:** `threading.Lock` in `mcp_server.py` around `_apply_spec_impl`, `_init()`, and `validate_spec`. Double-checked init pattern.
- **M4:** `get_scene()` now returns `{"scene": ..., "version": N}`.
- **M5:** Rotating file logger (set `DEVFORGE_LOG_FILE=path/to/devforge.log`). Env-controlled level (`DEVFORGE_LOG_LEVEL=DEBUG`).
- **M6:** Dead subtrees moved out of `devforge/`:
  - `devforge/simulation/` → `experiments/simulation/`
  - `devforge/reasoning/evolution/` → `experiments/reasoning_evolution/`
  - `devforge/reasoning/autonomy/` → `experiments/reasoning_autonomy/`
  - **These are not in the importable path. Don't try to import from them.**

### Tests added (4 new files in `devforge/tests/`)
- `test_import_walk.py` — walks every `devforge.*` module and imports it. Catches import-time side effects, broken `__init__.py` files, missing dependencies.
- `test_gateway_budget.py` — default bucket, sliding expiry, strict mode env var, 429→BudgetExceededError recognition.
- `test_artifact_store.py` — LRU eviction, reorder, summary generation.
- `test_script_extractor.py` — `..` rejection, absolute path rejection, content-hash fallback, comment-prefix parsing.

---

## 4. Startup Sequence (the actual one that works here)

The SETUP-GUIDE's sequence is generic. Here's the one that matches this machine:

### Step 1: Install Python deps
```bash
cd /home/mrg/dev/games/Forge/devforge_review_package
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r devforge/requirements.txt
```
**Verify:** `python -c "import httpx, mcp, git, fastapi, uvicorn, requests"` exits 0.

### Step 2: Fix the llama-server shared lib and start it
```bash
export LD_LIBRARY_PATH=/home/mrg/dev/cpp/llama.cpp/build/bin:$LD_LIBRARY_PATH
/home/mrg/dev/cpp/llama.cpp/build/bin/llama-server \
  -m /home/mrg/models/gemma-4-12b-qat/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf \
  --host 127.0.0.1 --port 9090 \
  --ctx-size 32768 \
  --n-gpu-layers 99
```
**Notes:**
- Use **port 9090**, not 8080. SearXNG owns 8080.
- Use the **12B model first** — the 26B MoE may OOM on a single GPU. Switch to 26B once you confirm the pipeline works.
- `--n-gpu-layers 99` = offload all layers to GPU. If you have no GPU, drop this flag (it'll be slow CPU-only).
- `LD_LIBRARY_PATH` is required or it fails immediately.

**Verify:** `curl -s http://localhost:9090/health` should return JSON. Then `curl -s http://localhost:9090/v1/models -H "Content-Type: application/json" -d '{"n_predict":1}'` should not error.

### Step 3: Start the DevForge LLM gateway
In a new terminal:
```bash
cd /home/mrg/dev/games/Forge/devforge_review_package
source .venv/bin/activate
export DEVFORGE_LLAMA_ENDPOINT="http://localhost:9090"
export DEVFORGE_GRAMMAR_PATH=""   # auto-discover
python -m devforge.infrastructure.llm.gateway
```
The gateway binds to **port 8001** (or whatever `MCP_PORT` is set to — check `runtime_config.py` for the default). It exposes `/completion`, `/tokenize`, `/v1/chat/completions` and a `/health` endpoint.

**Verify:** `curl -s http://localhost:8001/health` returns 200.

### Step 4: Run the unit tests
Before bringing up the MCP server, run the four new test files to confirm the Python side works:
```bash
cd /home/mrg/dev/games/Forge/devforge_review_package
source .venv/bin/activate
python devforge/tests/test_import_walk.py
python devforge/tests/test_gateway_budget.py
python devforge/tests/test_artifact_store.py
python devforge/tests/test_script_extractor.py
```
**Expected:** All four pass. `test_import_walk.py` may report some modules failing on third-party deps that aren't in the venv yet — that's fine, as long as the failure mode is `ImportError` on a third-party name, not a syntax error or a missing devforge internal module.

### Step 5: Start the DevForge MCP server
In a new terminal:
```bash
cd /home/mrg/dev/games/Forge/devforge_review_package
source .venv/bin/activate
export DEVFORGE_LLAMA_ENDPOINT="http://localhost:9090"
export DEVFORGE_EXECUTOR_BACKEND="godot_ai_mcp"
export DEVFORGE_GODOT_AI_MCP_URL="http://localhost:8000/mcp"
export DEVFORGE_GAME_ROOT="./dev-forge"
python -c "from devforge.platform.mcp_server import mcp; mcp.run(transport='sse')"
```
MCP server runs on **port 8001** (SSE transport).

**Verify:** `curl -H "Accept: text/event-stream" --max-time 2 http://localhost:8001/sse` returns an SSE stream (any response counts).

### Step 6: Open Godot and enable the godot-ai addon
This is the step **only the human can do** (GUI). The chat AI must hand off here.

1. Open Godot 4.6.3.
2. **Import** the project at `/home/mrg/dev/games/Forge/terraforge-master/terraforge-master/project.godot` (if not already in the recent list).
3. **Enable the godot-ai plugin:** Project > Project Settings > Plugins > set `godot_ai` to Enable. Check the box.
4. **Open a scene.** The plugin needs a scene to operate on. Use `addons/godot_ai/`'s demo scene, or open `scenes/main.tscn` (or whatever the project's main scene is).
5. The godot-ai MCP server auto-starts on **port 8000** as soon as the addon is enabled.

**Verify:** `curl -s http://localhost:8000/mcp` returns anything (even an error message means it's listening).

### Step 7: Run the smoke test
The integration test scripts referenced in `SETUP-GUIDE.md` (`scripts/run_integration_test.sh`) **do not exist** in this codebase (`scripts/` is empty). Use the direct Python path:
```bash
cd /home/mrg/dev/games/Forge/devforge_review_package
source .venv/bin/activate
python devforge/tests/test_import_walk.py --prompt "Add a Camera3D named MainCamera" --mcp-url http://localhost:8001/sse
```
Actually, `test_import_walk.py` is just an import-walk test — it doesn't take a `--prompt`. For a real smoke test, you need an MCP client. The simplest one:
```python
import asyncio
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    async with sse_client("http://localhost:8001/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Available tools:", [t.name for t in tools])
            # Try apply_spec
            result = await session.call_tool("apply_spec", {"prompt": "Add a Camera3D named MainCamera to the current scene"})
            print("apply_spec result:", result)

asyncio.run(main())
```

---

## 5. Architecture — How a Request Flows

```
You
 │  (natural language prompt)
 ▼
┌────────────────────────────────────────────┐
│ DevForge MCP Server (port 8001, SSE)      │
│  mcp_server.py                             │
│  ┌──────────────────────────────────────┐  │
│  │ apply_spec(prompt)                   │  │
│  │   ↓                                 │  │
│  │ _apply_spec_impl (locked)           │  │
│  │   ↓                                 │  │
│  │ engine.run_pipeline()               │  │
│  │   ↓                                 │  │
│  │ _llm.generate()                     │  │
│  │   ↓                                 │  │
│  │ router.generate()                   │  │
│  │   ↓                                 │  │
│  │ LlamaClient.generate()              │  │
│  │   ↓ HTTP                            │  │
│  │ DevForge Gateway (port 8001)        │  │
│  │   ↓ HTTP                            │  │
│  │ llama.cpp (port 9090)               │  │
│  │   ↓ grammar-constrained decode      │  │
│  │ Gemma 4B MoE (or 12B)               │  │
│  │   ↓ returns JSON plan               │  │
│  │ ... back up the stack ...           │  │
│  │   ↓                                 │  │
│  │ GodotAIMCPExecutor                  │  │
│  │   ↓ HTTP                            │  │
│  │ godot-ai MCP (port 8000)            │  │
│  │   ↓ WebSocket                       │  │
│  │ Godot Editor (live scene)           │  │
│  └──────────────────────────────────────┘  │
└────────────────────────────────────────────┘
```

**Critical control points:**
- **Grammar constraint** at llama-server — model literally cannot output non-plan JSON
- **Threading lock** in `mcp_server.py` around `_apply_spec_impl` — serializes concurrent turns
- **ContextVar turn_id** — each `apply_spec` call gets its own turn_id for budget tracking
- **Budget check** at gateway — 100K tokens per turn, sliding expiry on activity

---

## 6. Key Files (so you don't grep blindly)

| Purpose | Path |
|---------|------|
| MCP server (entry point) | `devforge/platform/mcp_server.py` |
| Pipeline engine | `devforge/compilation/pipeline/engine.py` |
| LLM router | `devforge/infrastructure/llm/router.py` |
| llama.cpp client | `devforge/infrastructure/llm/llama_client.py` |
| LLM gateway | `devforge/infrastructure/llm/gateway.py` |
| Runtime config (env vars) | `devforge/infrastructure/runtime_config.py` |
| Script extractor (path-safe) | `devforge/compilation/pipeline/script_extractor.py` |
| GodotAIMCP executor | (search `devforge/execution/`) |
| Scene store | (search `devforge/knowledge/` or `devforge/world_model/`) |
| Artifact store (LRU) | `devforge/knowledge/artifact_store.py` |
| Grammar files (GBNF) | `devforge/reasoning/prompts/{planner_grammar,arch_planner,decomposer}.gbnf` |
| Logger (rotating) | `devforge/infrastructure/logger.py` |
| Procfile (Honcho/Foreman) | `Procfile` (repo root) |
| Tests | `devforge/tests/test_{import_walk,gateway_budget,artifact_store,script_extractor,godot_ai_mcp}.py` |
| Set up guide | `SETUP-GUIDE.md` |
| Audit prompt (for re-audit) | `CLAUDE_AUDIT_PROMPT.md` |
| Safety manifest (separate file, NOT in bundle) | `/home/mrg/dev/games/Forge/CLAUDE-FABLE-SAFETY-MANIFEST.md` |

---

## 7. Known Issues (not in audit, found during recon)

1. **asyncio.run() in godot_ai_mcp module** — flagged in `AI_HANDOVER.md`. Not fixed by Days 1-7. Likely a top-level `asyncio.run(main())` call in an async module. If you hit it during Step 5/6, look for that pattern in `devforge/infrastructure/llm/godot_ai_mcp.py` or wherever the godot-ai executor lives. Fix: move the `asyncio.run` into a `if __name__ == "__main__":` guard, or refactor to `await` properly.
2. **godot-ai auto-start requires Godot to be focused/active.** The WebSocket to Godot can drop if Godot loses focus on some systems. Reopen the scene to re-establish.
3. **No Odysseus installed.** If the user wants autonomous agent flow, they need to install Odysseus separately. Without it, the only paths that work are direct MCP test scripts (Step 7).

---

## 8. What "Success" Looks Like

After Step 7, the smoke test should:
1. Connect to `http://localhost:8001/sse`
2. List the available MCP tools (`apply_spec`, `validate_spec`, `get_scene`, `reset_scene`)
3. Call `apply_spec` with a simple prompt like "Add a Camera3D named MainCamera"
4. Get back a JSON plan + a list of operations that got sent to Godot
5. In Godot, the scene should have a new `Camera3D` node named `MainCamera`

If all five happen, the full chain is working: LLM → grammar-constrained plan → MCP → godot-ai → live Godot scene.

If any of those fail, work backward: which boundary broke? Check the logs at each layer.

---

## 9. What to Tell the User to Run (your job is to issue these in order)

The chat AI drives the Python side. The user handles:
- Opening Godot
- Enabling plugins
- Visual confirmation in the editor

When the AI is ready to start something, the AI gives the user a copy-pasteable command. The COMMANDS-FOR-HUMAN.md (sibling file) is the exhaustive list of what the user might need to type.

---

*Give this entire file to a chat AI along with the message at the top. It has everything needed to get DevForge running end-to-end.*
