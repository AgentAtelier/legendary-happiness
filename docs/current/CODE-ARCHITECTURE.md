# Code Architecture — file-by-file map

One-line jobs for every key file in the Forge project.  Use this to
find where a feature lives without reading every file.

## hub/ — ops panel (FastAPI)

| File | Job |
|------|-----|
| `hub/hub.py` | FastAPI server: status, model swap, test runners, chain health |
| `hub/mcp_client.py` | Shared DevForge + godot-ai MCP call wrappers |
| `hub/forge_env.py` | Single-source-of-truth parser for `stack.env` |
| `hub/forge_ops.py` | Transactional model swap, drift detection, shell helpers |
| `hub/forge_models.py` | Model catalog, VRAM estimation, swap plan |
| `hub/forge_score.py` | Scoring logic (shared by test runners) |
| `hub/diagnostics.py` | Move-1 diagnostics: repeat-diversity, intent-sensitivity, ceiling |
| `hub/bench.py` | Legacy test bench (being replaced by forge_testbench) |
| `hub/scenarios.py` | Legacy scenario runner (being replaced) |
| `hub/gauntlet.py` | Legacy gauntlet runner (being replaced) |
| `hub/shootout.py` | Legacy pipeline shootout (being replaced) |

### hub/forge_testbench/ — new test chassis (reference implementation)

| File | Job |
|------|-----|
| `runner.py` | Unified test engine (single/multi-model/repeat-N) |
| `context.py` | Injected runtime environment for tests |
| `artifact.py` | Persisted test run output |
| `result.py` | Single test result data class |
| `catalog.py` | Test suite catalog |
| `test.py` | Base test interface |
| `metric.py` | Score breakdown |
| `reporting.py` | Render artifacts as reports |

## engine/devforge/ — generation engine (MCP server)

| File | Job |
|------|-----|
| `platform/mcp_server.py` | MCP tool registration (apply_spec, get_scene, etc.) |
| `compilation/pipeline/engine.py` | Shared pipeline orchestrator (prompt → ops) |
| `execution/godot_ai_mcp.py` | MCP client/executor for godot-ai bridge |
| `execution/interface.py` | Executor abstract interface |
| `infrastructure/llm/` | LLM gateway, router, llama + Claude clients |
| `infrastructure/runtime_config.py` | Runtime config from stack.env |
| `knowledge/scene/scene_graph.py` | Live scene tree model |
| `knowledge/system_graph/system_graph.py` | Global game-architecture model |
| `compilation/pipeline/architecture_planner.py` | LLM-driven architecture planner |
| `compilation/pipeline/architecture_compiler.py` | Plan → DevForge IR compiler |
| `compilation/pipeline/operation_generator.py` | IR → Godot operations |
| `compilation/pipeline/validator.py` | Operation validator |
| `compilation/pipeline/repair_engine.py` | Auto-repair of failed operations |
| `compilation/pipeline/context_assembler.py` | Builds planner context from scene/graph/history |
| `spatial/` | Deterministic room/building/scatter/WFC/Voronoi planners |
| `reasoning/` | AI planning, repair, design companions |
| `platform/monitor/` | Event logging, request tracing, SQLite analytics |

## Architecture seam — the single rule

`hub/` and `engine/` **never import each other**.  They communicate
through MCP: flat dicts/JSON over HTTP.  No shared classes cross the seam.
