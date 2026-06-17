# Forge Stack — System Overview & Operations Guide

**This is the single entry point for the Forge stack.** Read this first.
For deep chain internals, see `~/Obsidian Vault/forge-stack-chain.md`.

> Last updated: June 14, 2026. All ports/paths verified against live config.
> Includes Phase 4–6 completion, gruntwork cleanup, diagnostic integration,
> A/B planner comparison, and regression detection.

---

## What is this?

The Forge stack is a local AI → Godot game engine pipeline. You talk to an AI
agent (Odysseus) that uses tools to create and modify scenes in the Godot editor.

```
Browser ──▶ Odysseus (docker :7000)
              │  agent mode + "Godot Developer" persona
              ├──MCP/http──▶ godot-ai (:8000) ──WS :9500──▶ Godot editor (rpg)
              └──MCP/sse───▶ DevForge (:8001)
                               │ pipeline: planner → compiler → executor
                               ├──HTTP──▶ llama.cpp (:8002)
                               └──MCP/http──▶ godot-ai (:8000) ──▶ editor
```

---

## Components & Ports

| Component | Port | Purpose | Config |
|-----------|------|---------|--------|
| **Odysseus** (Docker) | :7000 | AI agent in browser | `~/dev/ai/odysseus/docker-compose.yml` |
| **godot-ai** | :8000 | MCP server wrapping Godot editor | `~/dev/ai/godot-ai/` |
| Godot Editor (rpg) | :9500 (WS) | The game editor itself | `~/dev/games/Forge/` project |
| **DevForge** | :8001 | Pipeline: plan → compile → execute | `systemctl --user status forge-devforge` |
| **llama.cpp** | :8002 | LLM inference server | `systemctl --user status forge-llama` |
| **forge-hub** | :8003 | Web UI for managing everything | `systemctl --user status forge-hub` → http://127.0.0.1:8003 |

**Common misconception:** Port 8003 is the **hub web UI** (ops panel), NOT a
model server. Port 8080 is NOT part of the forge stack (was a legacy aichat
port). The ONLY model server is :8002.

---

## Single Source of Truth

**`~/.config/forge-stack/stack.env`** (stowed from `~/dotfiles/forge-stack`).
Everything — model path, context size, prompt template, port numbers — lives
here. The `stack` CLI and `forge-model` CLI both read/write this file.
The hub (`:8003`) shells out to these CLIs; it never reimplements their logic.

**Key env vars:**
- `MODEL` / `MODEL_ALIAS` — the current GGUF and its computed alias
- `LLAMA_BASE_ARGS` — the base args template (edit THIS, never `LLAMA_ARGS`)
- `LLAMA_ARGS` — generated from BASE + per-model extras (auto-regenerated on swap)
- `LLAMA_PORT` — always 8002
- `DEVFORGE_PROMPT_TEMPLATE` — chatml / gemma (set per-model on swap)
- `DEVFORGE_PLANNER` — `arch` (default, architecture-based) or `ops`
  (EXPERIMENTAL — shelved June 14, 2026). The ops planner emits operations
  directly under a GBNF grammar, bypassing the entities→systems→compiler path.
  **It scored 14/100 vs arch's 61/100 on the shootout** — the LLM cannot emit
  45+ detailed JSON operations in a single constrained call for complex prompts.
  The arch path remains the only viable planner. The `--all-planners` flag and
  planner-switching infrastructure remain in place for future revisit.
- `DEVFORGE_DEBUG=0` — debug verbosity off (chain is stable)

---

## How to Operate

### Start / stop everything

```bash
stack up       # start all services (llama → godot-ai → DevForge → hub)
stack down     # stop all services (hub survives independently)
stack status   # check every component
stack doctor   # run the chain integrity check
```

### Check the chain

```bash
stack doctor   # validates all ports, config, and model integrity
```

Or open **http://127.0.0.1:8003** — the hub shows live status chips for every
component with drift detection (configured ≠ running → red banner).

### View logs

```bash
journalctl --user -u forge-llama -f     # llama server
journalctl --user -u forge-devforge -f  # DevForge pipeline
journalctl --user -u forge-hub -f       # hub web UI
```

---

## Model Management

### Adding a model

Drop a `.gguf` file into `~/models/`. Everything else is read from the GGUF
metadata — architecture, layers, KV heads, trained context. No filename guessing.

```bash
forge-model list          # see all detected models and their fit estimates
```

### Swapping models

```bash
forge-model plan <model>   # dry-run: see what WOULD change (VRAM, ctx, template)
stack model <model>        # full swap: writes config, restarts llama + DevForge
```

Or use the hub: **Models tab → click a model → confirm**. The hub shows a
streaming output of the swap with progress.

**The swap is transactional:** it snapshots `stack.env`, writes new config,
restarts llama, polls `/health`, verifies `/props` matches, and rolls back on
ANY failure. If llama crashes mid-swap, the old config is restored and the
failure is classified (cudaMalloc OOM, segfault, port conflict, etc.).

### Model fit statuses

- **fits** — comfortably within VRAM budget (safe)
- **tight** — fits but close to the limit (still safe, but watch it)
- **spills** — exceeds VRAM; will use system RAM and run slower

The estimator uses a 0.6 GiB safety margin to prevent F1 regressions (where
fit said "fits" but cudaMalloc OOMed at runtime).

### Per-model overrides

```bash
forge-model set <model> ctx=8192          # force a specific context size
forge-model set <model> template=chatml   # override the prompt template
forge-model set <model> alias=my-name     # give it a custom alias
```

Overrides are stored in `~/.config/forge-stack/models.json`.

---

## Persona Model: Godot vs Author

Odysseus supports multiple personas via `presets.json`. The two critical ones:

### Godot Developer persona
- **Purpose:** Scene work → routes through DevForge's `apply_spec`
- **Temperature:** 0.2 (safe for tool calling)
- **Inject suffix** contains `/no_think` (mandatory at temp 0.2) and the word
  **"MCP"** (load-bearing — see below)
- **Primary path:** `apply_spec` (plans + validates + executes + verifies)

### Author persona
- **Purpose:** Creative writing, story generation
- **Temperature:** 1.0 (Gemma native — don't drop below 0.6 for creative)

### Known trap: the "MCP" word in the persona suffix

The domain classifier in Odysseus uses keyword matching to decide which tools
to surface. The word **"MCP"** in the persona's `inject_suffix` is what keeps
the DevForge and godot-ai tools reachable. If saved from the Odysseus admin UI,
the UI can clobber the persona file — **always diff against**
`~/Obsidian Vault/odysseus-godot-persona.md` after any UI save.

### Known trap: stale browser tabs

An open Odysseus browser tab keeps sending the OLD persona prefix/suffix until
reloaded. Always **reload the Odysseus tab** after changing personas.

---

## The Hub (http://127.0.0.1:8003)

The hub is the workshop for problems and experiments. Key features:

| Tab | What it does |
|-----|-------------|
| **Status** | Live chips for each component + drift detection |
| **Models** | One-click model swap with streaming output |
| **Config** | stack.env editor with validation + diff + backups |
| **Bench** | 21-layer chain test bench + shootout summary (latest scorecard) |
| **Score** | Scenario suite for model quality scoring (Stream A) |
| **Shootout** | Full model → Godot pipeline test: apply_spec + artifact verification, with file-based logging per run |
| **Activity** | Durable action log with failure classifications |

**The hub survives `stack down`** — it runs its own `forge-hub.service`.
It binds 127.0.0.1 only (must never be LAN-reachable — it executes systemctl).

---

## Chain Health Sidebar

The hub has an always-on right sidebar (230px, collapsible to 28px) that shows
the health of every link in the chain. It auto-refreshes every 30 seconds.

**What it checks (8 links):**
| Link | Check |
|------|-------|
| llama.cpp | HTTP /health + /props (model alias match) |
| DevForge | HTTP reachable on :8001 |
| godot-ai | HTTP reachable on :8000 |
| Odysseus | HTTP reachable on :7000 |
| Odysseus→llama | `docker exec` curl host.docker.internal:8002/health |
| Odysseus→DevForge | `docker exec` curl host.docker.internal:8001 |
| MCP keyword | `docker exec` grep presets.json for "MCP" |
| Config↔Doc | Compare stack.env against forge-stack-chain.md |

**Color code:** green = healthy, yellow = degraded/stale, red = down, gray = unknown.
Click any link to expand detail + a specific fix suggestion. The sidebar also
shows warnings for: model drift, config-doc mismatches, MCP keyword missing,
and post-swap staleness ("reload Odysseus tab").

Collapse to 28px for a mini-chain view — colored dots stacked vertically with
thin connecting lines. Hover any dot for the link name and status. A "↻ Check
now" button forces an immediate refresh.

Endpoint: `GET /api/chain-health`. The frontend sidebar polls this every 30s;
the button lets you force a manual refresh immediately.

---

## Swap Progress Bar

When a model swap is triggered (from the Models tab or the Overview text input),
the Overview tab shows a phase-driven progress bar:

| Phase | Progress | Stream keyword |
|-------|----------|----------------|
| VRAM check | 10-25% | `checking VRAM…` → `VRAM ok` |
| Config write | 35-45% | `snapshot taken` → `writing config…` |
| Llama restart | 55% | `restarting llama…` |
| Health poll | 55-85% | `waiting for /health (attempt N)` |
| Verification | 90% | `verified: model=<alias>` |
| DevForge restart | 95% | `template/context changed — restarting devforge…` |
| Done | 100% | `event: done` |

The bar fills smoothly via CSS transition and auto-hides 1.5s after completion.
A phase label below the bar shows the current step in plain language.

---

## Shootout (Model → Godot Pipeline Test)

The Shootout tab runs a single model through the full apply_spec pipeline:
plan → compile → execute in the Godot editor, then scores the result against
static assertions (node existence, property checks) and runtime assertions
(correct nodes, no crashes). Each run produces:

- **Scorecard** (`data/shootouts/shootout-<ts>.json`) — per-model results with
  static/runtime scores, assertion detail, raw DevForge response, and
  scene-before/after snapshots
- **Log file** (`data/shootouts/shootout-<ts>.log`) — timestamped step-by-step
  trace: model swap, apply_spec request, assertion results, full exception
  tracebacks. Every message is also emitted to the SSE stream so the UI sees
  progress in real time.
- **History** — past scorecards are listed in the shootout tab with one-click
  detail view and a "📄 View detailed log" button to see the full log inline.
- **Bench integration** — the bench tab shows the latest shootout summary with
  a "📄 log" link to the companion log file.

### Preflight check

`GET /api/shootout/preflight` verifies the chain is ready before a shootout:
godot-ai MCP reachable, Godot scene loaded (accepts `Ground` from test_project
OR `Arena`/`Collectibles` from a shootout scene), DevForge reachable, llama
healthy, models available. Leftover Arena nodes from previous runs are
automatically cleaned up.

### A/B Planner Comparison (`--all-planners`)

The `--all-planners` flag runs each model through **both** planner modes:
1. **arch** (default) — architecture-based: entities → systems → compiler → ops
2. **ops** — direct operation generation under a GBNF grammar

Between modes, the shootout modifies `DEVFORGE_PLANNER` in `stack.env` and
restarts the DevForge service (`forge-devforge`). Results are compared
side-by-side in the scorecard with per-model delta and winner (`arch` / `ops` /
`tie`). In the hub, add `--all-planners` to the shootout URL query or use the
CLI:

```bash
python hub/shootout.py --all-planners          # all models, both planners
python hub/shootout.py --model qwen3 --all-planners  # one model, both planners
```

### Regression Detection

Every shootout scorecard now includes a `regression_flags` field. After scoring,
the shootout compares each model's total_score against its **best previous score**
across all past shootouts. Any model that drops more than 10 points is flagged:

```json
{
  "model": "Qwen3 14B",
  "current_score": 55,
  "previous_best": 77,
  "delta": -22
}
```

This makes model regressions immediately visible without manual diffing.

### Scorecard fields (per model)

| Field | Purpose |
|-------|--------|
| `static_score` / `runtime_score` | Assertion scores (68 + 32 = 100 max) |
| `planner_mode` | `arch` or `ops` — which planner generated this result |
| `raw_apply_spec` | Complete DevForge pipeline response (truncated at 2000 chars) |
| `raw_artifact` | Full artifact after `read_artifact` |
| `scene_before` / `scene_after` | Node path → type mappings for debugging scene mutations |
| `stage_latencies` | Per-stage timing: planning, compilation, execution (ms) |
| `plan_retries` | How many planning retries before success |
| `repair_count` | How many repair passes ran after completeness |
| `failure_attribution` | Per-failing-assertion root cause (plan / compile / execute / completeness / runtime) |
| `log_ts` | File timestamp linking scorecard to its companion `.log` file |
| `errors` | Per-assertion failure messages |

### Log endpoint

`GET /api/shootout/{ts}/log` returns the full shootout log as plain text.
Path traversal is blocked (only `\d{8}-\d{6}` timestamps are accepted).

---

## Scan Cache

`scan()` in `forge_models.py` caches its results with a 2-second TTL. A single
model swap calls `scan()` three times (file resolution → `plan_apply` → reclaim
lookup), but with the cache only the first call reads GGUF headers from disk:

- Cold scan: ~0.7s (reads GGUF metadata from all files)
- Warm scan: ~0.02s (returns cached results)

This eliminates redundant work within a request. The 2s TTL is long enough for
a swap but short enough to pick up newly-added models quickly. The cache stores
a shallow copy of results so future callers can't mutate the shared list.

No caller changes needed — the cache is transparent to all `scan()` consumers.

---

## Testing

```bash
# Hub unit tests (fast, safe)
cd ~/dev/games/Forge/hub && .venv/bin/python -m pytest tests/ -v

# Hub live integration tests (needs real stack — use -m live)
cd ~/dev/games/Forge/hub && .venv/bin/python -m pytest tests/ -v -m live

# DevForge tests
cd ~/dev/games/Forge/devforge_review_package && python -m pytest devforge/tests/ -v

# VRAM estimator calibration (needs real stack, ~10 min)
cd ~/dev/games/Forge/hub && python calibrate_vram.py
```

---

## Where Everything Lives

| What | Where |
|------|-------|
| **This doc** | `~/dev/games/Forge/FORGE-STACK.md` |
| **Capabilities report** | `~/dev/games/Forge/CAPABILITIES-REPORT.md` |
| **Roadmap** | `~/dev/games/Forge/ROADMAP.md` |
| **Stage 2 handoff** | `~/dev/games/Forge/STAGE-2-HANDOFF.md` |
| **Test results** | `~/dev/games/Forge/TEST-RESULTS.md` |
| **Chain deep reference** | `~/Obsidian Vault/forge-stack-chain.md` |
| **Config** | `~/.config/forge-stack/stack.env` |
| **Model files** | `~/models/*.gguf` |
| **Model registry** | `~/.config/forge-stack/models.json` |
| **Hub (web UI)** | `~/dev/games/Forge/hub/` |
| **DevForge (pipeline)** | `~/dev/games/Forge/devforge_review_package/` |
| **godot-ai (MCP server)** | `~/dev/ai/godot-ai/` |
| **Odysseus (agent)** | `~/dev/ai/odysseus/` |
| **Persona source of truth** | `~/Obsidian Vault/odysseus-godot-persona.md` |
| **Action log** | `~/dev/games/Forge/hub/data/actions/` |
| **Shootout data** | `~/dev/games/Forge/hub/data/shootouts/` |
| **Stack CLI scripts** | `~/dotfiles/forge-stack/` |
| **Grunt-work roadmap** | `~/Downloads/forge-grunt-work-roadmap.md` |
| **DevForge changelog** | `~/dev/games/Forge/devforge_review_package/CHANGES.md` |

---

## Archived Documentation

Most of the 28 markdown files in `~/Downloads/` from the June 9-12
investigation and pre-rebuild planning phase have been archived to
`~/Downloads/archive/`. They include:

- `01-grammars.md` through `06-misc-bugs.md` — the 6-part DevForge hardening
  investigation (June 9, 2026). Findings were addressed in subsequent rounds.
- `DEVFORGE_BUILD_MANUAL.md`, `DEVFORGE_FINAL_ROADMAP.md`,
  `DEVFORGE_REBUILD_ROADMAP.md` — superseded by `DEVFORGE_FINAL_ROADMAP_v2.md`
  and the grunt-work roadmap.
- `Claude-*.md` — Claude-specific investigation documents (caching, context
  budget, prompts, retry). Historical reference only.
- `odysseus-godot-pipeline-*` — 4 investigation documents. Findings catalogued
  in the v2 report; Stream E PRs capture the actionable ones.

**Only 3 docs remain current in `~/Downloads/`:**
- `forge-grunt-work-roadmap.md` — the 5-stream execution plan (being executed now)
- `AGENTS.md` — AI agent operating rules (still relevant for future sessions)
- `forgeborn-local-ai-setup-FINAL.md` — standalone aichat setup (not Forge stack,
  but useful reference for non-Odysseus LLM chat)

---

## Cardinal Rules (learned the hard way)

1. **Verify LIVE, not just with unit tests.** Green unit tests lied while every
   model swap was broken (a double-quote bug + a VRAM check that refused swaps).
2. **Never fork Odysseus or godot-ai.** They stay stock upstream. Fix our code
   or send upstream PRs.
3. **`stack.env` + CLIs are the single source of truth.** The hub shells out;
   it never reimplements stack logic.
4. **Don't break what works.** Run tests before AND after every change batch.
5. **One concept, one implementation.** Consolidate duplication; don't add a
   third copy.
