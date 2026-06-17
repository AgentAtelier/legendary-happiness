# DevForge — Year 1 Stable Prototype

> **⚠️ Partly historical.** This documents the Year-1 FastAPI + Godot-plugin
> path. The primary entry point today is the MCP server
> (`python -m devforge.platform.mcp_server`, port 8001) with the godot-ai
> executor — see the repo-root `CLAUDE.md` for the current layout, tests,
> and ports. Layout changes since this was written: `tools/verify_pipeline.py`
> → `devforge/verify_pipeline.py`, `tools/health_check.py` →
> `devforge/health_check.py`, `tests/` → `devforge/tests/`, plugin files
> moved from `addons/devforge_ai/` to `devforge/`.

AI-assisted game development for Godot 4.

## What This Is

DevForge is a system that converts natural language prompts into Godot scene modifications.
You type "Add a patrolling NPC" in the editor and DevForge creates the nodes, scripts, and
connections automatically.

This is the **Year 1 stabilized prototype** — a clean, tested, architecturally sound foundation
for the rest of the project.

## Architecture

```
Godot Editor Plugin                    Python Backend
┌──────────────┐                    ┌──────────────────────────────┐
│ PromptInput  │──POST /generate──> │ Context Assembler            │
│ RunButton    │                    │   ↓                          │
│ StatusLabel  │                    │ Architecture Planner (LLM)   │
│ LogOutput    │                    │   ↓                          │
│              │                    │ Architecture Compiler (det.) │
│              │                    │   ↓                          │
│              │<── {files, ops} ── │ Completeness → Validator     │
│              │                    │   ↓                          │
│ Execute ops  │──POST /report───> │ Repair Engine                │
│ Write files  │                    └──────────────────────────────┘
└──────────────┘
```

**Key design principle:** Only ONE LLM call per request. Everything else is deterministic.

## Pipeline Flow

1. **Context Assembly** — gathers scene tree, system graph, existing code, prompt history
2. **Architecture Planner** — LLM generates a delta: `{systems, entities, connections}`
3. **Architecture Compiler** — deterministically converts delta into IR plan steps
4. **Operation Generator** — compiles IR steps into `{files, operations}`
5. **Completeness Checker** — injects required nodes (CollisionShape3D, Camera3D, etc.)
6. **Validator** — filters out invalid operations (wrong paths, bad types)
7. **Repair Engine** — fixes common issues (missing /root prefix, wrong script paths)

## Quick Start

### 1. Install Python Dependencies

```bash
cd devforge-y1
pip install -r requirements.txt
```

### 2. Start the Server

With llama.cpp (local):
```bash
# First start llama.cpp server with your model
# Then (port 8002 — 8000 is taken by godot-ai, 8001 by the MCP server):
uvicorn devforge.platform.server.server:app --port 8002
```

With Claude API:
```bash
export DEVFORGE_LLM_BACKEND=claude
export ANTHROPIC_API_KEY=your-key-here
uvicorn devforge.platform.server.server:app --port 8002
```

### 3. Install the Godot Plugin

Copy the `addons/devforge_ai/` folder into your Godot project's `addons/` directory.
Enable the plugin in Project → Project Settings → Plugins.

### 4. Use It

1. Open a scene in Godot (Node3D root recommended)
2. Type a prompt in the DevForge panel
3. Click "Generate"
4. Watch nodes and scripts appear

## Project Structure

```
devforge-y1/
├── devforge/                          # Python backend
│   ├── infrastructure/                # Foundation layer
│   │   ├── logger.py                  # Structured logging
│   │   ├── runtime_config.py          # Configuration
│   │   └── llm/                       # LLM abstraction
│   │       ├── router.py              # Routes to llama/claude/mock
│   │       ├── llama_client.py        # llama.cpp client
│   │       └── claude_client.py       # Claude API client
│   ├── knowledge/                     # Domain knowledge
│   │   ├── system_graph/              # Game architecture graph
│   │   │   ├── system_graph.py        # Nodes + edges
│   │   │   └── graph_updater.py       # Updates from operations
│   │   └── scene/                     # Godot scene understanding
│   │       └── scene_graph.py         # Parsed scene tree
│   ├── compilation/                   # Deterministic pipeline
│   │   ├── ir/                        # Intermediate representation
│   │   │   └── plan.py                # Plan + Step dataclasses
│   │   └── pipeline/                  # Pipeline stages
│   │       ├── context_assembler.py   # Builds LLM context
│   │       ├── architecture_planner.py # LLM call (the only one)
│   │       ├── architecture_compiler.py # Delta → IR steps
│   │       ├── operation_generator.py # IR → operations
│   │       ├── completeness.py        # Auto-inject nodes
│   │       ├── validator.py           # Filter invalid ops
│   │       └── repair_engine.py       # Fix common issues
│   └── platform/                      # Server + monitoring
│       ├── server/
│       │   └── server.py              # FastAPI server
│       └── monitor/
│           └── monitor.py             # Tracing/telemetry
├── addons/devforge_ai/                # Godot plugin
│   ├── devforge_plugin.gd             # EditorPlugin entry
│   ├── devforge_panel.gd              # UI + operation execution
│   ├── devforge_panel.tscn            # Panel scene
│   └── plugin.cfg                     # Plugin config
├── tests/                             # Test suites
│   ├── test_pipeline.py               # Pipeline unit tests (pytest)
│   └── test_server.py                 # Server integration tests
├── tools/                             # Dev tools
│   ├── verify_pipeline.py             # Standalone verification (no deps)
│   └── health_check.py               # Module import checker
└── requirements.txt
```

## Testing

Standalone verification (no external deps):
```bash
python -m devforge.verify_pipeline
```

Full test suite (see also `scripts/run_all_tests.sh` at the repo root):
```bash
pytest devforge/tests/ -v
```

Health check:
```bash
python -m devforge.health_check
```

## Debug Endpoints

While the server is running:

- `GET /` — health check
- `GET /status` — system graph, session info, monitor stats
- `GET /traces` — recent pipeline traces with timing
- `GET /logs` — structured log entries

## What Changed from the Original Codebase

### Bugs Fixed
- **LlamaClient**: `print(payload["grammar"][:200])` ran before grammar was added to payload
- **LLMRouter**: `generate()` was called as static method but wasn't one
- **Scene serialization**: now filters out DevForge's own UI nodes (HTTPRequest, etc.)
- **OperationValidator**: was expecting `SceneGraph` object but server passed raw dicts
- **Broken imports**: many cross-layer import issues resolved
- **Report endpoint**: now properly handles the `{operation, success, error}` format

### Architecture Improvements
- **Single LLM call**: architecture planner is the only LLM call; everything else is deterministic
- **Scene graph validation**: validates Godot types against a known-good set
- **Operation chaining**: validator tracks "pending" nodes from earlier ops in the same batch
- **Structured logging**: every component logs through a central logger
- **Tracing**: every request gets a trace with step-by-step timing
- **Error propagation**: errors from the server are now visible in the Godot panel

### Godot Plugin Improvements
- **node.owner = edited_scene_root**: added nodes now save with the scene
- **ClassDB.class_exists()** check before instantiation
- **Detailed error messages**: each operation returns `[success, error_message]`
- **Status label + log output** in the panel UI
- **Busy state** prevents double-submissions

## Year 1 → Year 2 Roadmap

What's stable now (Year 1):
- Core pipeline from prompt to operations
- Scene serialization and filtering
- Operation validation and repair
- Structured logging and tracing
- LLM routing (local + cloud)

What to build next (Year 2):
- **Script generation with actual game logic** (current scripts are stubs)
- **Multi-step intent decomposition** (the `INTENT_TEMPLATES` system from your codebase)
- **Godot headless validation** (run GDScript checks before sending to editor)
- **Git-based transactions** (snapshot/rollback on failure)
- **Dashboard web UI** (the infrastructure is there, needs frontend)
- **Learning from past operations** (the learning engine skeleton exists)

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEVFORGE_LLM_BACKEND` | `llama` | `llama`, `claude`, or `mock` |
| `DEVFORGE_LLAMA_ENDPOINT` | `http://localhost:9090` | llama.cpp server URL |
| `DEVFORGE_GRAMMAR_PATH` | `` | Path to GBNF grammar file |
| `DEVFORGE_GAME_ROOT` | `./dev-forge` | Path to Godot project |
| `DEVFORGE_DEBUG` | `0` | Enable verbose logging |
| `ANTHROPIC_API_KEY` | `` | Required for Claude backend |
