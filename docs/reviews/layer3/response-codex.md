# Layer-3 Code-Health Review — Codex
*2026-06-17 · Tasks 1, 2, and 3 all answered.*

> **Reading note for the owner.** Each Task 1–3 ends with a short "what
> you're not asking that you should be" — that is the most useful section
> in the whole report. The Cross-Cutting section at the end is the one-page
> summary; if you read only one section, read that one.

---

## Task 1 — Architecture + god-file splits

### Recommended architecture

A spoken-sentence version the owner can hold in their head:

> *The hub is the dashboard. The engine is the worker. They talk over a
> post-office (MCP), never directly. The engine hands work to a Godot
> editor wrapper (godot-ai) the same way. The local LLM (llama.cpp) is a
> supply closet the engine borrows from. Tests are their own small
> workshop (`hub/forge_testbench`). Everything else is one-purpose
> scripts.*

Concretely, the layering the code should stay close to:

| Layer | Concrete in repo | Single job |
|---|---|---|
| **Ops UI / Orchestrator** | `hub/hub.py` (and small `hub/*.py` helpers) | Show live state, run a CLI, expose a thin REST surface |
| **Service-local helpers** *(boundary on hub side)* | `hub/forge_env.py`, `hub/forge_models.py`, `hub/forge_ops.py`, `hub/diagnostics.py` | One helper per concern; hub `import`s them, no I/O living in `hub.py` |
| **Test workshop** | `hub/forge_testbench/` | Self-describing test plug-ins → typed `Metric` → Artifact → reporting as pure function |
| **MCP boundary (engine)** | `engine/devforge/platform/mcp_server.py` + `tools_*.py` | Translate MCP tool calls into pipeline calls; do not contain pipeline logic |
| **Engine pipeline** | `engine/devforge/compilation/pipeline/pipeline_orchestrator.py` + planner modules | Plan → compile → execute; route to one planner; emit ops |
| **Planners** (one per strategy) | `engine/devforge/spatial/planners/room.py`, `…/arch.py`, `…/ssp.py`, `…/wfc.py`, … | Each planner is "given an intent, returns a plan" — nothing else |
| **Compilers / validators** | `engine/devforge/compilation/validator/`, `engine/devforge/compilation/ir/` | Turn a plan into the internal ops IR; validate and normalize |
| **Execution** | `engine/devforge/execution/godot_ai_mcp_client.py` + `godot_ai_executor.py` | Hold an MCP session to godot-ai; translate normalized ops into godot-ai commands |
| **Domain subsystems** | `engine/devforge/lore/`, `…/journal/`, `…/quests/`, `…/dialogue/`, `…/patterns/`, … | One folder, one concern; each registers its own MCP tools |
| **Cross-cutting infra** | `engine/devforge/infrastructure/`, `…/governance/`, `…/operations/` | Things that every layer needs (caching, retries, gates) but only these |

**MCP boundary discipline (most important non-obvious rule):**
The hub and engine do *not* import each other. They cross an MCP / HTTP / stdio
seam. Anything inside `engine/devforge/` should be reachable through an MCP
tool, an internal helper module, or a planner strategy — not by direct
cross-package import. ADR 002 already commits to "no `shared/`"; this review
extends that: **no `hub` import in `engine/`, no `engine` import in `hub/`.**

### Where the code follows it vs. muddies it

**Follows it:**
- The architectural *flow* is intact: hub → MCP → engine → MCP → godot-ai
  → editor, and llama.cpp as a side dependency (`docs/current/FORGE-STACK.md`,
  lines 22–34).
- The new test chassis (`hub/forge_testbench/`) already obeys the spirit
  of "one job per file": runner 519 lines, probes 964 lines, reporting 229
  lines, schemas ≤145 lines. Tests-as-plugins, metrics typed, reporting as
  pure function (`docs/current/TESTING-SYSTEM-DESIGN.md` §1–5).
- The "DevForge plan → compile → execute" stages are real in
  `engine/devforge/compilation/pipeline/engine.py` (`PipelineEngine.run_pipeline`
  at line 283 → `_run_governance_gates` at 590).
- The hub genuinely is just an ops panel at the top (`hub.py:1-15` docstring),
  and the chain-health side bar attaches at exactly the right layer.

**Muddies it:**
- **`hub/hub.py` is the test system + chain health + config editor + persona
  manager, all in one.** Routes for the dying legacy runners
  (`/api/scenarios`, `/api/gauntlet/...`, `/api/shootout`, `/api/bench/...`)
  clog the file (`hub.py:838-1183`) and import the legacy modules at module
  level (`hub.py:50-65`). Hub should be an orchestrator, not an orchestrator
  plus a dead test runner.
- **`mcp_server.py` is not a pipeline gateway — it's a toolbox.** It registers
  30+ tools covering lore, dialogue, journaling, perf sampling, linting,
  polishing, balance sim, and scaffolding tests alongside the actual pipeline
  entry points. Most of these are domain subsystems pretending to be MCP
  tool definitions (see `engine/devforge/platform/mcp_server.py` tools).
- **`engine.py` is a router pretending to be a pipeline.** The
  `PipelineEngine` class embeds 10 planner strategies directly
  (`_run_ops_path` 679, `_run_arch_path` 785, `_run_spatial_path` 1078,
  `_run_layout_path` 1214, `_run_building_path` 1239, `_run_scatter_path`
  1264, `_run_ssp_path` 1289, `_run_voronoi_path` 1314, `_run_wfc_path` 1339,
  `_run_room_path` 1364). These should be pluggable strategy modules, not
  methods on the orchestrator.
- **`godot_ai_mcp.py` mixes three concerns.** MCP transport plumbing
  (sessions, retries, circuit breaker, async loop), Godot-command translation,
  and scene-tree parsing all live in one 1,076-line class
  (`engine/devforge/execution/godot_ai_mcp.py:30-1076`).

Net picture: the *flow* is clean; the *code layout* is cluttered. A solo
non-coder owner can't tell from a diff whether a change touched the
pipeline, a planner, the test rig, or domain tooling — they have to read
the file.

### God-file split plan

> **Order principle: lowest risk first.** Each split is sized so a single
> AI session can do it, leave existing behaviour green, and not break the
> test parity gate. Risk is *blast radius if a regression slips past
> tests*, not amount of code moved.

#### 1. `engine/devforge/execution/godot_ai_mcp.py` — 1,076 lines · **LOWEST RISK** ✅ do this first

Three concerns live in one `GodotAIMCPExecutor` class:

```
mcp_transport_client.py    # asyncio session lifecycle, streamable_http_client,
                           # circuit breaker, reconnect backoff.
                           # Methods moved: _ensure_session (l.295), _close_session
                           # (l.351), _run (l.275), _record_mcp_failure (l.385).
godot_ai_executor.py       # Godot command translation + scene rebuild. Depends on
                           # transport client.
                           # Methods moved: execute (l.125), get_scene (l.158),
                           # read_logs (l.170), resolve_node_properties (l.186),
                           # get_performance_monitors (l.204), find_symbols (l.228),
                           # search_filesystem (l.246), run_project (l.407),
                           # stop_project (l.421), game_eval (l.434),
                           # take_screenshot (l.448), shutdown (l.463),
                           # _execute_async (l.483).
godot_ai_ops.py            # Pure op-translation and parsing: translate_ops_to_commands
                           # (l.957), _execute_ops_individually (l.711),
                           # _normalize_op_result (l.1013), _parse_tool_result (l.1029),
                           # _res_path (l.1001), _unwrap_scene_hierarchy (l.646),
                           # _tree_from_flat (l.681).
```

- **Safe order:** 3a extract `god god_ai_ops.py` (pure functions, no I/O) →
  3b extract `mcp_transport_client.py` → 3c shrink the executor to a thin
  coordinator.
- **Why first:** the broken behaviour here (a stale session, a circuit
  breaker firing) shows up immediately in dev-loop testing, and a tiny
  test already exists at `engine/devforge/tests/test_godot_ai_mcp.py` (1,011
  lines) that locks behaviour. Low blast radius if you're careful.

#### 2. `engine/devforge/compilation/pipeline/engine.py` — 1,444 lines · **MEDIUM RISK**

Keep `PipelineEngine` as orchestrator; lift the planner bodies out.

```
pipeline_orchestrator.py   # Renamed from engine.py. Contains: PipelineEngine
                           # (now ~400 lines), run_pipeline, governance gates,
                           # validate_pipeline, _normalize_scene, _dedupe_files,
                           # _dedupe_operations, cache_stats, grammar, update_history.
                           # Keeps GateResult, PipelineResult dataclasses.
planners/                  # New directory.
  __init__.py              # registry: {"arch": arch.run, "room": room.run, …}
  arch.py                  # _run_arch_path (l.785) becomes arch.run(intent, ctx).
  ops.py                   # _run_ops_path (l.679) — kept but isolated.
  room.py                  # l.1364.
  layout.py                # l.1214.
  building.py              # l.1239.
  scatter.py               # l.1264.
  ssp.py                   # l.1289.
  voronoi.py               # l.1314.
  wfc.py                   # l.1339.
spatial_router.py          # _run_spatial_path (l.1078) + the planner-registry
                           # call. The orchestrator no longer knows individual
                           # planners; it asks the router.
```

- **Why second:** the file already centralizes the planner dispatch, so
  the move mostly shifts code, not behaviour. Tests at
  `engine/devforge/tests/test_ssp.py` (859 lines),
  `engine/devforge/tests/test_bsp.py` (713 lines),
  `engine/devforge/tests/test_template_forge.py` (634 lines) lock the
  spatial paths. The risk is the import graph: `engine.py` is referenced
  by reference in `hub/hub.py:738` for service-restart tracking, so the
  rename needs a one-line alias kept for one release.
- **Naming fix included:** file becomes `pipeline_orchestrator.py` (matches
  the class name `PipelineEngine`, fits the convention in §Task 2 (c)).

#### 3. `engine/devforge/platform/mcp_server.py` — 2,143 lines · **HIGH RISK (API surface)**

FastMCP supports importing tools from other modules and re-registering
them. Split by concern, not by file size:

```
mcp_server.py              # ~80 lines. Builds FastMCP, imports tools_*.py,
                           # wires shared state (pipeline lock, init).
tools_pipeline.py          # apply_spec, _apply_spec_impl, validate_spec,
                           # batch_preview, batch_apply, get_scene, audit_scene.
                           # The hot path.
tools_diagnostics.py       # perf_sample, perf_history, lint_content,
                           # polish_pass, smoke_run, signal_map, triage_errors,
                           # balance_sim, test_scaffold.
tools_knowledge.py         # lore_*, journal_*, quest_validate,
                           # dialogue_validate, project_search.
tools_templates.py         # template_list, template_preview, template_apply,
                           # read_artifact, scene_extract, scene_list_extractable,
                           # design_companion.
```

- **Order:** 3a extract `tools_pipeline.py` → 3b `tools_diagnostics.py`
  → 3c `tools_templates.py` → 3d `tools_knowledge.py` last (largest,
  least-trafficked surface, most "soft" failures). Each step ships green
  before the next.
- **Why third:** this file exposes a public MCP surface. The risk is
  tool-name drift or missing imports breaking registration. Test the
  registration is intact (`pip install -e engine/...` style smoke
  test) after each extraction.

#### 4. `hub/hub.py` — 1,940 lines · **HIGHEST RISK (entangled with dying code)**

This one needs a different tactic. Half the file is endpoints for the
legacy test runners that are scheduled for deletion. Don't move the rot —
move the **good code out of the rot**.

```
hub.py                     # Becomes a slim FastAPI app. Imports routers,
                           # exposes mount points, defines shared helpers
                           # (logging, build_id), and serves /api/chain-health
                           # (which is genuinely infrastructure).
hub_routes_ops.py          # /api/run, /api/swap, /api/models, /api/models/search,
                           # /api/config/*, /api/logs, /api/actions,
                           # /api/version, /api/selfcheck. Imports forge_* helpers.
hub_routes_testbench.py    # /api/testbench/run, /api/testbench/catalog.
                           # Talks only to forge_testbench/. NOT legacy runners.
_legacy_routes.py          # All /api/bench / /api/scenarios / /api/gauntlet
                           # /api/shootout /api/runs endpoints, kept in a
                           # single sidebar file. DELIBERATELY marked for
                           # deletion once forge_testbench parity holds.
                           # Optional: gate behind a feature flag so the UI
                           # can hide them.
persona_thinking.py        # /api/thinking/* and /api/persona/* routes
                           # separated out (hub.py:1409-1864) — only the
                           # persona-restore + think-toggle bits belong to
                           # ops; the warm-up / persona-edit logic could
                           # live near its data source.
```

- **Order:** 4a copy the legacy endpoints into `_legacy_routes.py`
  unchanged (zero risk; deletion-bound) → 4b extract persona/thinking →
  4c extract ops routes into `hub_routes_ops.py` → 4d leave hub.py as
  ~250 lines of "import + assemble routers".
- **Why last:** any split that happens before the testbench parity gates
  pass risks cutting live endpoints before the replacement is trusted.
  The testbench migration handoff (`docs/current/TESTBENCH-MIGRATION-HANDOFF.md`,
  §"THE RULE") is the gate.

### What you're not asking that you should be

- **One concrete seam to clarify before any split: dependency direction at
  the MCP boundary.** Right now the engine's pipeline lock and shared
  state live in `mcp_server.py`. If you split tools into files, do you
  keep that lock in the entry-point file, or move it into a small
  `engine/devforge/platform/lock.py` that everything imports? Pick
  *before* splitting the god file; otherwise, every extraction creates
  a new circular-import risk and the AI will "fix" it by stashing
  state in module globals — exactly what you're trying to leave behind.
- **You haven't defined what "non-coder approval" looks like in a code
  review.** Right now the owner is the bottleneck because the AI presents
  them raw Python. The fix isn't a style guide — it's a *review tool*
  that shows only the diff of `*.md` docstrings + the directory tree
  change. Worth scoping before any split lands.
- **You're not asking about the engine sub-folder whales.** Beyond the
  four god files, `engine/devforge/spatial/ssp.py` is 774 lines,
  `engine/devforge/simulator/simulator.py` is 630, and
  `engine/devforge/governance/analyzer.py` is 614. They're not god
  files, but they're getting close. A 300-line per-file rule (see Task
  2) would catch them before they become the next round of splits.

---

## Task 2 — Conventions guide

Deliberately short. The owner is non-coder and AI-directed; a "style
bible" will be ignored within a month. Every rule below has a one-line
rationale and an early signal that it's failing.

### File & function length (+ offenders with line counts)

**Rules.**
- **File length: ≤ 300 lines** for **new and edited** long-lived files.
  *Why:* at ~400 lines you stop seeing the structure of the file in
  one editor-fold; at ~1000 you can't tell from a diff which concern
  changed. Megabyte cognitive cost.
- **Function length: ≤ 60 lines, ≤ 25 lines ideally.** *Why:* your AI
  loses the thread past ~60 lines and starts splitting things wrong
  mid-function; the diff becomes unreadable.

**Offenders (verified `wc -l` 2026-06-17):**

| File | Lines | Severity |
|---|---|---|
| `engine/devforge/platform/mcp_server.py` | **2,143** | god (Task 1 #3) |
| `hub/hub.py` | **1,940** | god (Task 1 #4) |
| `engine/devforge/compilation/pipeline/engine.py` | **1,444** | god (Task 1 #2) |
| `engine/devforge/execution/godot_ai_mcp.py` | **1,076** | god (Task 1 #1) |
| `engine/devforge/tests/test_godot_ai_mcp.py` | 1,011 | near-god test — split alongside the executor split |
| `engine/devforge/tests/test_ssp.py` | 859 | tests usually OK but past 800 lines, split by scenario |
| `engine/devforge/spatial/ssp.py` | 774 | watch list (Task 1 #5) |
| `engine/devforge/tests/test_bsp.py` | 713 | tests, split by scenario |
| `engine/devforge/tests/test_template_forge.py` | 634 | tests, split by scenario |
| `engine/devforge/simulator/simulator.py` | 630 | watch list |
| `engine/devforge/governance/analyzer.py` | 614 | watch list |
| `hub/forge_testbench/tests/probes.py` | 964 | OK as a stable test set, but if it keeps growing, split by probe category like the testbench plan called for |

`hub/forge_testbench/runner.py` at 519 is acceptable — it's the engine of
the test chassis and benefits from being one file.

### Duplication to collapse (real path:line examples)

Three duplications are doing the owner measurable harm (the same bug
shows up in three different files). Anything below this tier — fix only
when you touch the file, not by policy.

1. **MCP client boilerplate** — the
   `streamable_http_client` / `sse_client` + `ClientSession` + `initialize()`
   + `call_tool()` + `json.loads(content[0].text)` pattern is duplicated
   in *at least 8 places*:
   - `hub/hub.py` (the `_devforge_call` and `_godot_ai_call` helpers used by ~20 endpoints)
   - `hub/forge_testbench/runner.py` (`_devforge_call`/`_godot_ai_call`)
   - `hub/diagnostics.py`
   - `hub/bench.py` *(legacy, will die)*
   - `hub/shootout.py` *(legacy)*
   - `hub/scenarios.py` *(legacy)*
   - `engine/devforge/execution/godot_ai_mcp.py` (`_ensure_session` l.295)
   - `engine/integration_tests/integration/mcp_client.py`

   **Collapse into** `hub/mcp_client.py` exporting
   `devforge_call(tool, args)` and `godot_ai_call(tool, args)` — both
   consume the engine URLs from `stack.env`. Bonus: every caller stops
   re-deriving the JSON-parse dance.

2. **Config / build-id hashing** —
   `hub.py:~59-67` builds `BUILD_ID` by hashing source files; the chain
   health endpoint does a similar hash for stale-service detection in
   `hub/hub.py` near the `chain-health` handler (~1500+ range).
   **Collapse into** `hub/forge_env.py:config_hash(files)` so the two
   stay in lock-step. Already half-existing — `forge_env.py` is the
   right home.

3. **Json normalization on tool results** —
   `_normalize_op_result` (`godot_ai_mcp.py:1013`), `_parse_tool_result`
   (`godot_ai_mcp.py:1029`), and the equivalent inline in
   `hub/forge_testbench/runner.py` and `hub/diagnostics.py`. *Why it
   matters:* three places means three definitions of "what does a
   tool-call error look like". If the engine changes an error shape,
   all three need to be updated. **Collapse once** when the executor
   splits (Task 1 #1); the executor module owns the result-shape
   contract and the hub trusts it.

(Don't-pursue list: small helpers like `_acquire_pipeline_lock_ctx` —
under 20 lines, fine to live where used until something needs them
elsewhere.)

### Naming convention (+ fossil names to fix)

**Conventions (few, enforced):**

- **Files: noun describing the role**, in `snake_case.py`. Architectural
  role suffixes carry meaning:
  - `*_client.py` — talks to an external MCP/HTTP service
  - `*_router.py` — picks one of N implementations based on input
  - `*_executor.py` — runs something (no UI, no decision)
  - `*_orchestrator.py` — coordinates several executors
  - `*_tools.py` — MCP/FastAPI tool definitions only (no logic)
  - `*_planner.py` (in `planners/`) — implements a single planning strategy
  - `*_validator.py` — checks invariants, returns a verdict, never mutates
- **Functions: verb phrase.** `run_pipeline`, `pick_planner`, `acquire_lock`.
- **Classes: noun.** One class per file when reasonable.
- **Modules: prefer one short purpose per file**, ≤ 300 lines (see above).

**Fossil names to fix** (each creates a moment of confusion for the
non-coder and the AI):

- `engine/devforge/compilation/pipeline/engine.py` — file is named
  `engine.py` inside a folder named `pipeline/` inside a package named
  `engine/`. The class inside is `PipelineEngine`. **Rename to
  `pipeline_orchestrator.py`.** Also resolves your "?" moment every time
  the owner types `engine.py` into search and gets three different files.
- `engine/devforge/execution/godot_ai_mcp.py` — implies it's an MCP
  *server* (one runs MCP, the other is an MCP client). The class is
  `GodotAIMCPExecutor` but the file name says it's the server. **Rename
  to `godot_ai_executor.py`.**
- `engine/devforge/devforge_panel.gd` / `devforge_plugin.gd` — fine,
  but `engine/devforge/plugin.cfg` is the file a non-coder will likely
  open first. Leave a `README.md` at this top level pointing those down.
- `hub/calibrate_vram.py`, `hub/forge_*.py` cluster — the `forge_`
  prefix denotes "service-local helper to hub." Worth keeping; one
  occurrence in `hub/docs/` will tell the owner "these are hub's own
  helpers, not imports of the engine." Document this in `hub/README.md`
  (it's currently a stub).
- `engine/devforge/foo.py` patterns spread across `engine/devforge/` —
  the top-level `__init__.py` is empty, but the folder list reads like
  alphabet soup to a non-coder (`auditing`, `companion`, `dialogue`,
  `execution`, `forge`, `governance`, `harness`, `infrastructure`,
  `journal`, `knowledge`, `lint`, `lore`, `mapper`, `navigator`,
  `operations`, `patch`, `patterns`, `platform`, `polish`, `quest`,
  `reasoning`, `refactorer`, `runner`, `sentinel`, `simulator`, `spatial`,
  `tests`, `triage`, `transaction`, `validation`, `world_model` ).

  **This is the one place a non-coder has to fight the file tree.**
  Suggest grouping them under three top-level dirs:
  - `engine/devforge/pipeline/` (compilation, validation, ir, execution,
    platform, spatial, patterns, simulator)
  - `engine/devforge/subsystems/` (lore, dialogue, journal, quests,
    mapper, world_model)
  - `engine/devforge/platform_infra/` (governance, operations, lint,
    audit, harness, runner, infrastructure, transaction)
  - and one **empty `_why.md`** at the devforge top explaining the move.

  Note: defer this reorg — it's high churn and low payoff compared to
  the four god-file splits. Just fact that you're not asking but should be.

### Minimal loose rules (each + one-line rationale)

> Each rule has to earn its keep — assume any one of these would be
> the only one you adopt, and ask "would the project still be
> better?"

1. **Flat dicts cross the MCP boundary; classes stay inside one
   process.** *Why:* serialization bugs go away, the hub and engine
   can't accidentally drift into requiring the same class definition.
2. **Max indent depth of 3.** *Why:* forces extraction of helpers (and
   therefore smaller diffs), without imposing a function-length ruler.
3. **Every module starts with a 3–6 line docstring: what this file is,
   what it isn't.** *Why:* the AI already writes these — codify them so
   that when the owner opens a file to ask "what's this?", the answer
   is on line 1.
4. **One public entry point per module** (`main()` / `run()` / `build()`).
   *Why:* a diff message of "I changed `run()`" tells the owner
   *where* the change happened without opening the file.
5. **Tests live next to what they test** (`engine/devforge/foo/` has
   `tests/test_foo.py` next to it). *Why:* the owner's mental model
   "file changed → test next to it changed" already works; preserve it.
   The new testbench (`hub/forge_testbench/tests/`) follows this. Score
   the *engine* on whether its tests do too.
6. **No silent global state.** Module-level constants are OK; module-level
   `dict` / `list` mutation and module-level singletons are not.
   *Why:* this is the failure mode that produced every "stale cache"
   bug in the test history (`docs/current/TESTBENCH-MIGRATION-HANDOFF.md`).
7. **Repeat yourself but loudly, never silently.** Tolerate one
   duplicated small helper if its copy is clearly named; collapse only
   when you have a third copy. *Why:* premature collapsing wastes
   review attention on extraction diffs rather than behaviour.

Drop any of these without ceremony if it ever starts feeling heavy.
Add nothing else — adding a rule has a maintenance tax.

### What you're not asking that you should be

- **You haven't decided what to do about the "engine = folder AND engine
  = file AND engine = orchestrator-class-also-named-PipelineEngine"
  collision.** Address it with the rename in §Task 2(c), but commit the
  rule *"the word `engine` in path or filename refers to the top-level
  folder only"* in `docs/decisions/004-engine-naming.md` so a future AI
  doesn't quietly re-introduce a fourth `engine.py`.
- **You're not asking about docstring style.** Without one rule,
  docstrings will drift between Google, NumPy, and reST formats in
  three sessions. Adopt one — Google-style is the lowest-friction
  default and matches what most AI models emit *when* asked. One
  sentence: "Use Google-style docstrings." Done.
- **You're not asking about type hints.** MyPy is overkill for your
  setup (high setup tax, low perceived value on a small project).
  Plain type *hints on public function signatures* are worth the
  ~30-second cost, though — they let the AI keep contract and
  implementation in sync. A future review can flip this on.

---

## Task 3 — Review & navigation environment

> The goal: the owner can open a PR, see *one English sentence*
> describing the change, and approve. The rest is automated.

### Structural signals

Already half in place — give it teeth. Each item has a one-file
owner and is small enough that the AI can do it in one pass.

1. **A top-of-repo architecture map**, auto-attached to every AI prompt.
   - You have `docs/current/FORGE-STACK.md` (the existing system map).
   - Add a **`docs/IN_30_SECONDS.md`** at the repo root: a single page
     with one diagram, three sentences, and the layer table from
     §Task 1. ~80 lines, no fluff. *Why:* a non-coder has to be able
     to ask "what does this project do?" and get an answer in 30s.
   - Reference this from `.github/workflows/...` system-prompt files
     if you add CI in the future.

2. **Module docstrings, enforced by convention** *(not by tooling)*.
   - Each of the four god files already has a one-paragraph header
     (`engine/devforge/platform/mcp_server.py`, `engine/devforge/execution/godot_ai_mcp.py`,
     `engine/devforge/compilation/pipeline/engine.py:1-13`,
     `hub/hub.py:1-15`). These are *exactly* the signal a non-coder
     needs. Make this the rule (Task 2 §3). The AI will then keep it.

3. **Predictable file placement** — extends Task 2's naming convention
   to *directories*. Two clear directories to commit to:
   - `hub/` — only the FastAPI app and its direct helpers. Anything
     that talks to engine, llama, godot-ai is here.
   - `engine/devforge/<subsystem>/` — only what the engine owns.
   - No `shared/`, no `common/`, no `utils/` — ADR 002 already rejected
     this. The hub and engine cross MCP, not import.

4. **An `ARCHITECTURE.md` per god file *after* the split**.
   - After Task 1 step 3 (`mcp_server.py` split), the directory
     `engine/devforge/platform/` should contain a one-page
     `ARCHITECTURE.md` showing: what each `tools_*.py` does, what
     state they share, what their public MCP names are. *Why:* the
     owner can ask a new AI "what does `tools_knowledge.py` do?" and
     get the answer from the file listing.

### Reviewable diffs for a non-coder

The owner can't read code deeply — so make the diff of *non-code*
signals do the work:

- **Diff titles.** Every commit / PR title should be one English
  sentence: "Move lore tools out of `mcp_server.py` into
  `tools_knowledge.py`." If the AI can't write that sentence clean,
  the split is wrong.
- **`docs/current/CHANGELOG-decisions.md`** — a low-friction ADR.
  When a big split happens, drop a 6-line entry:
  - **What:** the split.
  - **Why:** the one-line rationale.
  - **Risk:** what could regress.
  - **Reversible?** yes / no / one-line.
  This is *not* ADRs — keep ADRs for "why we picked one approach over
  another." This is for "what changed and why." Maintenance: zero,
  because the AI already writes the prose.
- **Diff the directory tree, not just the file.**
  Encoded by structural signals: if `tools_*.py` always live under
  `engine/devforge/platform/`, then a PR titled "Move lore tools" should
  show *add `tools_knowledge.py`, delete lines from `mcp_server.py`*.
  The directory diff is what tells the owner "files moved," and that's
  the most reviewable thing in the world for a non-coder.
- **One-line "what does the diff *do*" notes for new files.**
  After every split, the new file's *module docstring* should describe
  what it does *and what it doesn't*. If a reviewer sees "Single
  responsibility: the lore knowledge base." on line 1, the diff is
  reviewable.

### Automated guardrails (most relief per setup)

The owner can't babysit tooling. Pick the *one tool* that gives the
most relief; defer anything else.

**Pick this:** **Ruff** (`ruff check --fix . && ruff format .`).
- Single binary install, single command, no config file required.
- Formats (Black-compatible), catches unused imports / undefined names /
  bare `except`s / dead code in one go.
- Runs in <1s on the entire repo.
- Already maintained by the Python ecosystem; not a project-specific
  tool the owner would have to babysit.
- The AI can be instructed: "after every code change, run `ruff check
  --fix . && ruff format .`". This *is* the post-edit hook.

**Defer everything else.** Specifically:
- **MyPy / Pyright:** high setup tax; little relief while the codebase
  is still being carved into modules. Reconsider post-split.
- **pytest pre-commit:** your test runtime is *too long* for a
  pre-commit. Run tests in CI / nightly, not on the AI's edit.
- **Pre-commit framework + many hooks:** the additive tax of
  "another tool to babysit" compounds fast for a non-coder. Ruff is
  the only one.

**One trick worth its weight:** tell your AI assistant
*"edit code → run `ruff format . && ruff check --fix .` before
declaring the change done."* This single instruction is more valuable
than a style wiki.

### What you're not asking that you should be

- **You haven't asked how the AI will *find* the right file when you
  say "fix the planner."** That's a navigation problem, not a search
  problem. After the splits in Task 1, "the planner" becomes
  ten files under `engine/devforge/spatial/planners/`. Two cheap
  mitigations worth doing now, before any split:
  - **Per-directory `__init__.py` exports** — make `from
    engine.devforge.spatial.planners import arch, ssp, room` work.
  - **An `INDEX.md` per top-level directory** the AI can ingest
    (`hub/INDEX.md`, `engine/devforge/INDEX.md`, `engine/devforge/spatial/INDEX.md`).
    Same idea as `docs/INDEX.md`, just at the code-tree level.
- **You haven't decided whether the tests live "in the same file"
  or "next to the file."** `engine/devforge/tests/` keeps them in
  one tree; some subsystems have `engine/devforge/spatial/` with no
  test folder. Decide now: "one `tests/` tree per service" is the
  cleaner default that matches your new testbench. Co-locate the
  files you split if and only if the test count for that file is
  over 200 lines.
- **You haven't asked about logs.** Each split creates more log paths;
  the owner already has a chain-health sidebar. A small, consistent
  log line format per module (`[mcp_server.apply_spec] took 1.3s,
  ops=12, retry=0`) is worth more than another guardrail.

---

## Cross-cutting / anything else

**One-page summary.** Three things to ship, in order:

1. **Split the four god files, lowest risk first.**
   Executor (1,076) → Pipeline (1,444) → MCP server (2,143) →
   Hub (1,940). Each one is a chain of small AI-edits behind a
   parity gate. Don't touch the legacy runners.
2. **Adopt Ruff + the seven-rule conventions guide.** That's the
   whole "make AI write clean code" story. Don't add anything else.
3. **Add the navigation aids** (`IN_30_SECONDS.md`, per-folder
   `ARCHITECTURE.md` after the splits, and a `CHANGELOG-decisions.md`).
   This is the owner-side relief.

**What I'd push back on if you tried to add it to the report:**
- A formal "style guide" doc, longer than 30 lines. Won't survive.
- A pre-commit pipeline with more than Ruff + format. Babysitting tax.
- Strict MyPy on a project still being carved up. Wrong time.
- Reorganizing `engine/devforge/`'s subfolder alphabet soup
  *before* the god-file splits. Wrong order — splits need the
  existing folders to stay put.

**Open question for the owner to decide (don't duck this):**
The legacy test runners will die when `forge_testbench` reaches
parity (`docs/current/TESTBENCH-MIGRATION-HANDOFF.md` lays out the
gate). The owner needs to commit, on the record, to one of two
positions: (a) cut over hard once parity holds, removing the legacy
endpoints; (b) keep legacy endpoints as a deprecated _legacy_routes
shim for N months. This *single decision* blocks the highest-risk
split (#4, `hub.hub.py`) and you can't review this review without
making it. ADR materials provided; pick one and write a half-page
note in `docs/decisions/005-legacy-test-cutover.md`.
