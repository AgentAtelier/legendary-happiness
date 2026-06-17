<!-- ARCHIVED — see ~/dev/games/Forge/FORGE-STACK.md for current documentation -->

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

DevForge is a Godot 4 game-development AI pipeline. A natural-language prompt
flows through an LLM planner → compiler → executor pipeline that creates nodes,
scripts, and assets directly in a live Godot editor via the godot-ai MCP bridge.

Since June 2026 it also ships a **capability layer** (~30 MCP tools, built per
`CAPABILITY-ROADMAP.md`): Scene Doctor (`audit_scene`), Batch Operator
(`batch_preview`/`batch_apply`), Error Triage, Template Forge
(`template_list/preview/apply`, 10 system templates), Lorekeeper, Quest
Validator, Performance Sentinel, Smoke Runner, Progress Journal, and more —
each a deterministic core with optional LLM explanation, in its own package
(`devforge/auditing`, `operations`, `triage`, `forge`, `lore`, `quests`,
`sentinel`, `runner`, `journal`, …). Mutating tools are two-step
(preview → apply) with scene-version drift gates and file-overwrite refusal.

```
Odysseus (agent chat) ──MCP──▶ DevForge MCP server ──▶ Pipeline ──▶ Godot
                                                  │
                                                  ├── llama.cpp (Gemma 4 26B MoE, local)
                                                  └── godot-ai MCP ──▶ live Godot editor
```

Expected local services: llama.cpp on port 9090, godot-ai MCP on port 8000
(40 tools), DevForge MCP server on port 8001, and a Godot 4.6 editor with an
open Node3D scene. The integration tests and `apply_spec` smoke tests require
all of these to be live; the unit tests do not.

## How To Run

```bash
cd /home/mrg/dev/games/Forge/devforge_review_package
source .venv/bin/activate

# Required env vars
export DEVFORGE_LLAMA_ENDPOINT="http://localhost:9090"
export DEVFORGE_EXECUTOR_BACKEND="godot_ai_mcp"
export DEVFORGE_GODOT_AI_MCP_URL="http://localhost:8000/mcp"
export DEVFORGE_GAME_ROOT="./dev-forge"
export DEVFORGE_DEBUG="1"

# Start DevForge MCP server (port 8001)
python -m devforge.platform.mcp_server
```

The full env-var list (LLM backend selection, token budgets, retry limits) is
in `devforge/infrastructure/runtime_config.py`. `DEVFORGE_LLM_BACKEND` selects
`llama` (default), `claude` (needs `ANTHROPIC_API_KEY`), or `mock`.
`TUNING.md` covers hardware-specific llama-server flags and the
context-window / prompt-cache levers for this machine (RX 6800).

## Tests

Run the whole no-live-stack suite (the fix-verification loop — run it after
every change batch):

```bash
scripts/run_all_tests.sh
```

Pre-flight the live stack (read-only; `--warm` also warms the model and
measures llama.cpp prompt-cache reuse):

```bash
python -m devforge.doctor --warm
```

`scripts/run_all_tests.sh` is the canonical suite list (25 suites — the
capability-layer suites are registered there). Core individual suites —
most are standalone scripts that exit nonzero on failure:

```bash
python -m devforge.health_check          # every module imports cleanly
python -m devforge.verify_pipeline       # full prompt→ops pipeline with mock LLM, no deps
python devforge_project_tests/test_imports.py
python devforge/tests/test_import_walk.py
python devforge/tests/test_gateway_budget.py
python devforge/tests/test_artifact_store.py
python devforge/tests/test_script_extractor.py
pytest devforge/tests/test_godot_ai_mcp.py -v        # executor tests; mock-based, no live services
pytest devforge/tests/test_godot_ai_mcp.py -k <name> # single test
```

To build the review bundle, use `scripts/build_audit_bundle.sh` (never an
ad-hoc zip one-liner — that's how `godot_ai_mcp.py` got dropped twice). It
runs the test suite first and sanity-checks the resulting zip.

Integration tests need the live llama.cpp + godot-ai + Godot stack:

```bash
python integration_tests/integration/test_smoke.py     # end-to-end apply_spec
python integration_tests/integration/test_forgeborn.py # multi-prompt game build (--dry-run, --start-at N)
```

## Architecture

```
devforge/
├── platform/          # Entry points
│   ├── mcp_server.py   # MCP server (FastMCP, port 8001) — primary entry point
│   └── server/         # FastAPI server (legacy Year-1 path)
├── compilation/
│   ├── pipeline/       # Prompt → ops pipeline
│   │   ├── engine.py           # PipelineEngine orchestrator
│   │   ├── architecture_planner.py  # LLM → architecture delta (the ONLY LLM call)
│   │   ├── architecture_compiler.py # Delta → IR → operations
│   │   ├── operation_generator.py   # IR → ops
│   │   ├── context_assembler.py     # Context builder (24K token budget)
│   │   ├── completeness.py    # Auto-inject missing nodes
│   │   ├── validator.py       # Operation validation
│   │   ├── repair_engine.py   # Operation repair
│   │   └── script_extractor.py # GDScript extraction from prompts
│   └── ir/
│       └── plan.py     # DevForgePlan IR
├── execution/          # Executor backends
│   ├── interface.py    # Executor ABC
│   └── godot_ai_mcp.py # GodotAIMCPExecutor (Streamable HTTP → godot-ai)
├── infrastructure/
│   ├── runtime_config.py  # RuntimeConfig (env-var driven)
│   ├── logger.py          # DevForgeLogger (rotating file + env levels)
│   └── llm/
│       ├── llama_client.py # LlamaClient (Gemma template, grammar, retry)
│       ├── claude_client.py # Claude API backend
│       ├── router.py       # LLMRouter (backend dispatch + circuit breaker)
│       └── gateway.py      # Gateway (budget tracking, sliding expiry)
├── knowledge/
│   ├── system_graph/  # SystemGraph (node registry)
│   └── scene/
│       ├── scene_graph.py    # SceneGraph
│       └── godot_node_types.py # Authoritative node type list + grammar generator
├── reasoning/
│   ├── prompts/       # GBNF grammars + prompt templates
│   │   ├── arch_planner.gbnf          # Source grammar template
│   │   ├── arch_planner_generated.gbnf # Auto-generated grammar
│   │   └── planner_prompt.py           # Prompt construction
│   └── ai/
│       ├── planning/  # FeatureDecomposer, LRU cache
│       └── repair/    # ErrorParser
├── governance/        # Gate1, risk scoring
├── patterns/          # Deterministic pattern JSON files
└── tests/             # Unit tests
```

`devforge/` also contains the Godot editor plugin (`devforge_plugin.gd`,
`devforge_panel.gd`, `plugin.cfg`) used by the legacy FastAPI path.

Other top-level directories: `integration_tests/` (live-stack smoke tests),
`devforge_project_tests/` (import/integration checks), `experiments/`
(exploratory simulation/preview code — not part of the pipeline),
`terraforge_project_meta/` (predecessor-project metadata), `docs/archive/`.
The top-level `README.md` is the phase 1–10 roadmap index; `devforge/README.md`
documents the Year-1 FastAPI path (it carries a banner noting what moved and
points back here for the current layout).

### Key conventions

- **Single source of truth**: `godot_node_types.py` → generates `arch_planner_generated.gbnf` at startup
- **One LLM call per request**: `architecture_planner.py` is the only LLM call; every other stage is deterministic
- **Grammar-constrained**: LLM outputs validated by GBNF grammar at llama.cpp level
- **Deterministic pre-routing**: Short imperative prompts ("add a player") skip the LLM entirely via pattern matching
- **Token budget**: `ContextAssembler` enforces `context_token_budget` (default 24K), **auto-clamped at startup** to the llama.cpp server's real `n_ctx` minus generation + template overhead (e.g. 7168 on a 12288-ctx server) — see `TUNING.md`
- **Escalating retry**: 3 attempts with trimmed context on each failure
- **Circuit breaker**: 5 consecutive godot-ai failures → exponential backoff
- **Sliding budget expiry**: Gateway resets `created_at` on every active request (active turns don't expire mid-pipeline)
- Bound every loop at 3; one canonical implementation per concept

## Project History

The project has been through two hardening cycles (Phases 0–5 grammar/template/
budget fixes, then a Days 1–7 production-readiness audit) plus an investigation
session that fixed 5 bugs in the godot-ai MCP bridge. `CHANGES.md` is the
complete audit trail — check it before re-fixing anything that looks broken.

## Open Items (updated June 11, 2026 after Rounds 5–6)

Code-level items are done: the Round-2 audit findings (F1–F12), the
`_rename`/`_remove` pipeline gap, the LRU cache write debounce, and a static
godot-ai contract audit that found and fixed 4 op-translation bugs
(`attach_script`/`set_property`/`connect_signal` command+param names,
`res://` script paths) — see `CHANGES.md` Rounds 5–6. `get_scene` children
handling was verified correct in code.

What remains needs the live stack (godot-ai on 8000 + Godot editor):

1. **Restart the DevForge MCP server** on port 8001 — the running instance
   predates Rounds 5–6 (`python -m devforge.platform.mcp_server`).
2. **Live smoke test** — `python integration_tests/integration/test_smoke.py`,
   plus one `apply_spec` whose plan includes `attach_script` + `set_property`
   (silently broken before Round 6, never yet executed live), plus
   "rename X to Y" / "delete node X" prompts end-to-end.

## Safety Context

This is a legitimate Godot 4 game development pipeline. The codebase uses terms like
"attack", "payload", "inject", "weapon", "damage" in game-dev contexts (combat systems,
HTTP payloads, dependency injection, 3D assets). See `CLAUDE-FABLE-SAFETY-MANIFEST.md`
for the full term audit. The project is local-only — no telemetry, no external network calls.

## Companion Documents

Direction:

- `CAPABILITY-ROADMAP.md` — Where DevForge goes next: 22 capabilities rated by
  implementation difficulty × workload relief for an open-world FP RPG, with a
  phased build order. Synthesizes `Research/` (4 AI proposals + deep-research
  report) and corrects them against the actual godot-ai tool inventory.
- `Research/` — The source proposals the roadmap synthesizes.
- `workorders/` — Execution layer for OTHER coding agents (MiniMax M3 /
  DeepSeek v4 Pro). Claude is the architect/reviewer: it writes work orders
  and reviews `workorders/WORKLOG.md` handbacks; executors implement.
  Start at `workorders/00-EXECUTOR-BRIEFING.md`.

Audit trail:

- `CHANGES.md` — Every bug found and fixed, with file paths and rationale
- `ROUND2-AUDIT-FINDINGS.md` — Second-round audit task list (12 findings, F1–F12)
- `SUMMARY.md` — Phase 0-5 implementation details
- `Deferred-Claude-Recommendations.md` — Status of 11 deferred recommendations (all implemented as of June 2026)
- `CLAUDE_AUDIT_PROMPT.md` — Audit prompt template (easy→hard ordering)

Setup and handoff (written for an AI assistant or the human operator):

- `RUN-DEVFORGE-HANDOFF.md` — Machine-specific guide to getting DevForge running end-to-end
- `SETUP-GUIDE.md` — End-to-end wiring of Odysseus + llama.cpp + DevForge + godot-ai + Godot
- `COMMANDS-FOR-HUMAN.md` — Commands only the human at the keyboard can run, by phase
- `AI_HANDOVER.md` — Exploratory project handover brief (June 2026)

Safety:

- `CLAUDE-FABLE-SAFETY-MANIFEST.md` — Safety term audit
- `CLAUDE-FABLE-SUBMISSION.md` — Submission guide accompanying the safety manifest
