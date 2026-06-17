# DevForge Audit Implementation — Changelog

## What Changed

This update implements the core recommendations from the systems audit.
It wires existing components together into a unified pipeline for the
editor integration path.

---

## New Files

### `devforge/references/__init__.py` (290 lines)
**Godot 4 API reference data for LLM context injection.**

- 39 node-type reference entries (CharacterBody3D, Camera3D, Timer, Area3D, etc.)
- Each entry includes: properties, methods, signals, common script patterns
- Keyword → reference mapping (prompt says "player" → include CharacterBody3D docs)
- `get_reference_for_goal(goal)` returns relevant sections for any prompt
- Compact format designed to fit in LLM context without dominating it

### `devforge.core.planner.py` (rewritten, 210 lines)
**Core intelligence layer — now has validation, ordering, context, and repair.**

Changes from original:
- **Rich context assembly**: Scene tree + code signatures (ContextBuilder) + Godot API reference + session history
- **Operation validation**: Calls `OperationValidator.validate()` before returning ops
- **Operation ordering**: Sorts ops by dependency priority (create_file → add_node → attach_script → set_property → connect_signal → remove_node)
- **Structured system prompt**: Documents all 7 operation types with exact JSON schemas
- **Repair method**: `planner.repair()` asks the LLM to fix failed operations
- **Session history**: Tracks what prompts were sent and what they produced
- **Markdown fence stripping**: Handles LLMs that wrap JSON in ```json blocks
- **Graceful failure**: Returns empty plan on parse errors instead of crashing

### `devforge/server/server.py` (rewritten, 180 lines)
**Unified pipeline server with 4 endpoints.**

Changes from original:
- **`POST /generate`**: Now uses the full planner pipeline (context + validate + order)
- **`POST /report`**: NEW — receives execution results from the plugin (feedback loop)
- **`POST /repair`**: NEW — accepts a failed operation, asks LLM to fix it, validates the fix
- **`GET /status`**: NEW — returns session state for debugging
- **State tracking**: Updates WorldState on every generation, persists to disk
- **Session log**: Records every request with timing, file/op counts, and result reports

### `devforge.core.llm/worker.py` (rewritten, 45 lines)
**Uses the LLM router instead of direct llama.cpp calls.**

Changes from original:
- Routes through `LLMRouter` (respects `DEVFORGE_USE_CLAUDE` env var)
- Proper system message in every call
- Retry logic for transient failures
- Module-level singleton so router is reused

### `dev-forge/addons/devforge_ai/devforge_panel.gd` (rewritten, 330 lines)
**Godot editor plugin with feedback loop and repair.**

Changes from original:
- **Result reporting**: After executing operations, calls `POST /report` with per-operation success/failure
- **Automatic repair**: When an operation fails, calls `POST /repair` to get a corrected version, then applies it
- **Return values from operations**: Every `_op_*` method now returns `bool` so failures are detected
- **HTTPRequest isolation**: Separate HTTP channels for generate/report/repair (non-blocking)
- **Serialization fix**: Excludes HTTPRequest children from scene serialization
- **Fallback parent resolution**: If parent path not found, falls back to scene root instead of failing silently

### `tests/test_unified_pipeline.py` (200 lines)
**Tests for the entire new pipeline.**

- Reference data tests (keyword → correct nodes)
- Operation ordering (create_file < add_node < attach_script < set_property < connect_signal < remove_node)
- Planner integration with mock LLM (parse, validate, order)
- Invalid operation filtering (bad parent paths removed)
- Empty/garbage LLM response handling
- Markdown fence stripping
- Session history recording
- Repair method

### `tests/test_server_endpoints.py` (130 lines)
**FastAPI TestClient tests for all server endpoints.**

- `/generate` returns validated operations
- `/generate` filters invalid operations
- `/report` counts successes and failures
- `/repair` returns corrected operations
- `/status` returns session info

---

## Modified Files

### `devforge.core.llm/llama_client.py`
- `max_tokens`: 2048 → 4096
- `timeout`: 60 → 120 seconds
- `temperature`: 0.2 → 0.1 (more deterministic)

### `devforge/runtime/runtime.py`
- Simplified `run_prompt()` since the server now handles the full pipeline directly
- Execution engine (`run()`) and repair loop (`_attempt_repair()`) unchanged

### `pyproject.toml`
- Added `[project]` section with proper dependencies
- Added `fastapi`, `uvicorn`, `requests` to dependencies
- Added `[project.optional-dependencies]` for `claude` and `knowledge` extras
- Added `devforge-server` script entry point

---

## Architecture After This Update

```
Godot Plugin                          DevForge Server
┌─────────────────┐                 ┌──────────────────────────────────┐
│ Prompt Panel     │                 │                                  │
│                  │   POST          │  /generate                       │
│ [Run] ──────────────────────────▶ │   1. Build context               │
│                  │   /generate     │      - Scene graph               │
│                  │                 │      - Code signatures           │
│                  │                 │      - Godot API reference       │
│                  │                 │      - Session history            │
│                  │                 │   2. LLM generates plan          │
│ Execute ops  ◀──────────────────  │   3. Validate operations         │
│                  │   response      │   4. Order operations            │
│                  │                 │   5. Return                      │
│                  │   POST          │                                  │
│ Report results ─────────────────▶ │  /report                         │
│                  │   /report       │   - Log successes/failures       │
│                  │                 │                                  │
│ If failed:       │   POST          │  /repair                         │
│ Request repair ─────────────────▶ │   - Ask LLM to fix               │
│                  │   /repair       │   - Validate the fix             │
│ Apply fix  ◀────────────────────  │   - Return corrected ops         │
└─────────────────┘                 └──────────────────────────────────┘
```

---

## How to Use

### Start the server
```bash
# Using local LLM (default)
uvicorn devforge.server.server:app --host 0.0.0.0 --port 8000

# Using Claude API
DEVFORGE_USE_CLAUDE=true ANTHROPIC_API_KEY=sk-... uvicorn devforge.server.server:app --port 8000
```

### Enable the plugin
1. Copy `dev-forge/addons/devforge_ai/` into your Godot project's `addons/` directory
2. Enable the plugin in Project → Project Settings → Plugins
3. The DevForge panel appears in the right dock

### Run tests
```bash
pip install -e ".[dev]"
pytest tests/test_unified_pipeline.py -v
pytest tests/test_server_endpoints.py -v   # requires: pip install httpx
```
