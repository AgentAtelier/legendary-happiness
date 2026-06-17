<!-- ARCHIVED — see ~/dev/games/Forge/FORGE-STACK.md for current documentation -->

# COMMANDS-FOR-HUMAN.md

> **Purpose:** Every command or action that **I (the CLI AI) cannot run** but **you (the human at the keyboard) need to do** to get DevForge running. Organized by phase. Run them in order, or pick a section to debug.
>
> The chat AI driving RUN-DEVFORGE-HANDOFF.md will tell you *when* to run each of these. This file is your cheat sheet.

---

## Phase 0: Sanity Checks (one-time, ~2 minutes)

### 0.1 Confirm you're in the right place
```bash
pwd
# Should be: /home/mrg/dev/games/Forge/devforge_review_package
cd /home/mrg/dev/games/Forge/devforge_review_package
```

### 0.2 Confirm Python, Godot, llama.cpp exist
```bash
python3 --version    # 3.14.5 expected
godot4 --version     # 4.6.3 expected
ls /home/mrg/dev/cpp/llama.cpp/build/bin/llama-server
ls /home/mrg/models/*.gguf
```

### 0.3 Confirm SearXNG is what's on 8080 (so you know to avoid it)
```bash
curl -s http://localhost:8080/ | head -5
# Should show SearXNG HTML, not llama.cpp JSON
```
This confirms port 8080 is **taken**. Use 9090 for llama.cpp.

### 0.4 Confirm GPU is available (for `--n-gpu-layers 99`)
```bash
nvidia-smi 2>&1 | head -10
# If you see your GPU listed, you're good. If "command not found", you're CPU-only.
```

---

## Phase 1: Install Python Deps (one-time, ~2 minutes)

```bash
cd /home/mrg/dev/games/Forge/devforge_review_package
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r devforge/requirements.txt
```

**Verify:**
```bash
python -c "import httpx, mcp, git, fastapi, uvicorn, pydantic, requests; print('all deps OK')"
```
Should print `all deps OK`. If any fail, the venv is broken — delete `.venv` and retry.

---

## Phase 2: Start llama.cpp (every session, ~30 seconds to load model)

The llama-server binary is **broken without the shared lib**. The fix is the `LD_LIBRARY_PATH` line.

### 2.1 Open a dedicated terminal window
You'll want to watch this terminal for the rest of the session — llama-server logs go here.

### 2.2 Start with the smaller 12B model first
```bash
export LD_LIBRARY_PATH=/home/mrg/dev/cpp/llama.cpp/build/bin:$LD_LIBRARY_PATH
/home/mrg/dev/cpp/llama.cpp/build/bin/llama-server \
  -m /home/mrg/models/gemma4-12b-qat/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf \
  --host 127.0.0.1 \
  --port 9090 \
  --ctx-size 32768 \
  --n-gpu-layers 99
```

**What to watch for:**
- First ~5–10 seconds: prints "loading model"
- Then: "model loaded" and "listening on 127.0.0.1:9090"
- If you see `error while loading shared libraries: libllama-server-impl.so` → `LD_LIBRARY_PATH` not set correctly. Re-export.
- If you see `CUDA out of memory` → drop `--n-gpu-layers 99` to `--n-gpu-layers 20` (partial offload) or remove it entirely (CPU-only).
- If you see `address already in use` for 9090 → another process is on 9090. Try `--port 9091` (and remember to update the env var in subsequent steps).

### 2.3 Verify in a **separate** terminal
```bash
curl -s http://localhost:9090/health
# Should return JSON like {"status":"ok"}

curl -s http://localhost:9090/v1/models \
  -H "Content-Type: application/json" \
  -d '{"n_predict":1}'
# Should not error
```

### 2.4 (Optional) Swap to the larger 26B MoE model
If the 12B works but you want better plan quality:
- Ctrl-C the current llama-server
- Re-run with `-m /home/mrg/models/gemma-4-26B-A4B-it-qat-UD-Q4_K_XL.gguf`
- This needs ~20GB VRAM for full offload. If you have less, use `--n-gpu-layers 30` or stay on 12B.

---

## Phase 3: Start DevForge Gateway (every session)

In a **new terminal** (Phase 2 stays running):

```bash
cd /home/mrg/dev/games/Forge/devforge_review_package
source .venv/bin/activate
export DEVFORGE_LLAMA_ENDPOINT="http://localhost:9090"
export DEVFORGE_GRAMMAR_PATH=""
export DEVFORGE_DEBUG="1"
python -m devforge.infrastructure.llm.gateway
```

**What to watch for:**
- `Grammar self-test PASSED` — the GBNF grammar loaded and validates against the model
- `Gateway listening on 0.0.0.0:8001` (or similar)
- Any `BudgetExceededError` or `Config validation` errors mean config is bad — read them.

**Verify in another terminal:**
```bash
curl -s http://localhost:8001/health
# Should return 200 with {"status":"ok"} or similar
```

---

## Phase 4: Run the Unit Tests (one-time, before going further)

```bash
cd /home/mrg/dev/games/Forge/devforge_review_package
source .venv/bin/activate
echo "=== import walk ===" && python devforge/tests/test_import_walk.py
echo "=== gateway budget ===" && python devforge/tests/test_gateway_budget.py
echo "=== artifact store ===" && python devforge/tests/test_artifact_store.py
echo "=== script extractor ===" && python devforge/tests/test_script_extractor.py
```

**Expected:** All four pass. The import walk may show some third-party modules failing — that's fine if the failure is `ImportError` on `httpx`/`mcp`/`git`/etc. (you haven't activated the venv, or pip install failed). If a `devforge.*` module fails to import, that's a real bug — paste the traceback to the chat AI.

---

## Phase 5: Start the DevForge MCP Server (every session)

In a **new terminal**:

```bash
cd /home/mrg/dev/games/Forge/devforge_review_package
source .venv/bin/activate
export DEVFORGE_LLAMA_ENDPOINT="http://localhost:9090"
export DEVFORGE_EXECUTOR_BACKEND="godot_ai_mcp"
export DEVFORGE_GODOT_AI_MCP_URL="http://localhost:8000/mcp"
export DEVFORGE_GAME_ROOT="./dev-forge"
python -c "from devforge.platform.mcp_server import mcp; mcp.run(transport='sse')"
```

**Verify in another terminal:**
```bash
curl -H "Accept: text/event-stream" --max-time 2 http://localhost:8001/sse
# Should not refuse connection. May print SSE-formatted output.
```

**If you see an `asyncio.run()` error here** (the one flagged in `AI_HANDOVER.md`):
- It's likely in `devforge/infrastructure/llm/godot_ai_mcp.py` or wherever the GodotAIMCP executor lives
- Don't try to fix it blind — paste the full traceback to the chat AI

---

## Phase 6: Open Godot and Enable the Plugin (GUI step — I cannot do this)

This is the **only phase that requires the Godot GUI**. Do these steps in order.

### 6.1 Launch Godot
```bash
godot4 --editor /home/mrg/dev/games/Forge/terraforge-master/terraforge-master/project.godot
```
or just:
```bash
godot4
```
and pick the project from the recent list.

### 6.2 Import the project (first time only)
- Godot will scan `addons/` and import the godot-ai plugin
- This takes ~10–30 seconds the first time

### 6.3 Enable the godot-ai plugin
- Top menu: **Project → Project Settings → Plugins**
- Find `godot_ai` in the list
- Set **Enable** = checked
- The plugin status should change from "Inactive" to "Active"

### 6.4 Open (or create) a scene
- **File → Open Scene** and pick an existing scene from the project
- Or **Scene → New Scene** and save it as `main.tscn`
- The plugin needs *some* scene to operate on. A scene with a `Node3D` root is the typical starting point.

### 6.5 Verify the plugin's MCP server started
In a **new terminal**:
```bash
curl -s http://localhost:8000/mcp
# Should return *something* (even an error or 405). 
# Empty connection = plugin didn't auto-start.
```

If `curl` hangs or "connection refused":
- Make sure the plugin status is "Active" (not just enabled)
- Check Godot's Output panel (bottom) for plugin errors
- Try saving and reopening the scene

### 6.6 (Optional) Watch the godot-ai logs in Godot
- In Godot: **Output** panel at the bottom
- godot-ai prints MCP server startup messages there
- Look for: "godot-ai MCP server listening on 0.0.0.0:8000"

---

## Phase 7: Run the Smoke Test (Python — works from CLI)

In a new terminal:
```bash
cd /home/mrg/dev/games/Forge/devforge_review_package
source .venv/bin/activate
python <<'PY'
import asyncio
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    async with sse_client("http://localhost:8001/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Available MCP tools:", [t.name for t in tools])
            result = await session.call_tool(
                "apply_spec",
                {"prompt": "Add a Camera3D named MainCamera to the current scene"}
            )
            print("apply_spec result:", result)

asyncio.run(main())
PY
```

**Expected output:**
```
Available MCP tools: ['apply_spec', 'validate_spec', 'get_scene', 'reset_scene']
apply_spec result: ... (JSON-ish blob with operations and a confirmation that they were sent to Godot)
```

### 7.1 Visual confirmation
- Switch to Godot
- The Scene tree (left panel) should now show a new `Camera3D` node named `MainCamera`
- The 3D viewport should show the camera's frustum lines

If you see the camera in Godot — **the whole chain is working end-to-end**. 🎉

---

## Phase 8: Troubleshooting Commands

Use these when something breaks. Each one probes a specific boundary.

### 8.1 Is llama.cpp alive?
```bash
curl -s http://localhost:9090/health
# Should return JSON. If not: Phase 2 needs to be restarted.
```

### 8.2 Is the gateway alive?
```bash
curl -s http://localhost:8001/health
# Should return 200. If not: Phase 3 needs to be restarted.
```

### 8.3 Is godot-ai alive (Godot plugin started)?
```bash
curl -s http://localhost:8000/mcp
# Should respond (even with 405/400). Empty = Godot addon not running.
```

### 8.4 Is the MCP server alive?
```bash
ss -tlnp | grep 8001
# Should show a python process listening on 8001.
```

### 8.5 Is a `apply_spec` call actually reaching llama.cpp?
In the **gateway terminal** (Phase 3), look for log lines mentioning `POST /completion` and `POST /v1/chat/completions`. Each `apply_spec` call should produce one of these.

### 8.6 Is godot-ai receiving the operations?
In **Godot's Output panel**, look for `batch_execute` calls. Each `apply_spec` should produce one.

### 8.7 Did the scene actually change?
In **Godot**, look at the Scene tree. New nodes should appear within 1–2 seconds of the `apply_spec` call returning.

### 8.8 Are there CORS errors?
The gateway is locked to `localhost` (H2 fix). If you're hitting it from a different origin, you'll see CORS errors. Use `localhost`, not `127.0.0.1` mismatch, and don't use the IP from another machine.

### 8.9 Is the budget exhausted?
```bash
curl -s http://localhost:8001/health
# If it returns 429 or "budget exceeded" — wait 5 minutes or restart the gateway
# to reset the sliding window. Or set GATEWAY_STRICT_BUDGET=0 to skip enforcement.
```

### 8.10 Stuck on the asyncio error?
```bash
# Find the offending line:
grep -rn "asyncio.run" /home/mrg/dev/games/Forge/devforge_review_package/devforge/
```
If you see `asyncio.run` not under `if __name__ == "__main__":` — that's the bug. Paste it to the chat AI.

### 8.11 Model not loading? Try the other GGUF
```bash
# In the llama-server terminal, Ctrl-C, then:
/home/mrg/dev/cpp/llama.cpp/build/bin/llama-server \
  -m /home/mrg/models/gemma-4-26B-A4B-it-qat-UD-Q4_K_XL.gguf \
  --host 127.0.0.1 --port 9090 --ctx-size 32768 --n-gpu-layers 30
# Lower --n-gpu-layers if it OOMs.
```

### 8.12 Godot can't find the plugin?
```bash
ls /home/mrg/dev/games/Forge/terraforge-master/terraforge-master/addons/godot_ai/
# Should show plugin.cfg and .gd files. If empty, godot-ai wasn't symlinked/copied here.
```

---

## Phase 9: Tear Down (clean shutdown)

When you're done, kill the processes in **reverse order**:

1. **Godot**: just close the window
2. **MCP server terminal**: Ctrl-C
3. **Gateway terminal**: Ctrl-C
4. **llama.cpp terminal**: Ctrl-C
5. **Deactivate venv**: `deactivate` in any terminal where it's active

Optional: kill any stragglers
```bash
pkill -f llama-server
pkill -f "devforge.*mcp_server"
pkill -f "devforge.*gateway"
```

---

## Phase 10: One-Shot Helper Commands

### Reset everything (nuclear option)
```bash
pkill -f llama-server 2>/dev/null
pkill -f "devforge" 2>/dev/null
pkill -f godot 2>/dev/null
sleep 2
echo "all DevForge processes killed"
# Then restart from Phase 2.
```

### Re-run the unit tests after any change
```bash
cd /home/mrg/dev/games/Forge/devforge_review_package
source .venv/bin/activate
for t in devforge/tests/test_*.py; do
  echo "=== $t ===" && python "$t"
done
```

### Tail the gateway log (if you set DEVFORGE_LOG_FILE)
```bash
tail -f /tmp/devforge.log
# or wherever you exported DEVFORGE_LOG_FILE to
```

### Check the grammar is being used
```bash
# In the gateway terminal, look for:
# "Grammar self-test PASSED: <path to .gbnf>"
# If missing, the GBNF isn't being applied. Set DEVFORGE_GRAMMAR_PATH explicitly:
export DEVFORGE_GRAMMAR_PATH="/home/mrg/dev/games/Forge/devforge_review_package/devforge/reasoning/prompts/planner_grammar.gbnf"
```

### Verify the budget config
```bash
cd /home/mrg/dev/games/Forge/devforge_review_package
source .venv/bin/activate
python -c "from devforge.infrastructure.runtime_config import get_config; cfg = get_config(); print(f'llm_backend={cfg.llm_backend}, executor={cfg.executor_backend}, max_retries={cfg.max_plan_retries}')"
# If this errors, the config is broken. Read the error — it's now explicit per M1.
```

---

*This file is exhaustive. The chat AI may not need every command, but every command here is one you might be asked to run.*
