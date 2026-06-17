<!-- ARCHIVED — see ~/dev/games/Forge/FORGE-STACK.md for current documentation -->

# AI Handover — DevForge / TerraForge / WorldForge

**Date:** June 10, 2026
**Purpose:** Hand the project to a premium SOTA AI for review and unblocking.
**Mode:** Exploratory. The AI is invited to roam freely — read whatever it needs, form its own opinions, and propose a path forward.

---

## 1. What this project is (one paragraph)

A Godot 4 game-development AI pipeline called **DevForge**. A natural-language
prompt ("add a player with WASD movement") flows through:

```
Odysseus (agent chat) ──MCP──▶ DevForge MCP server ──▶ Pipeline ──▶ Godot
                                                 │
                                                 ├── llama.cpp (Gemma 4-26B-A4B-it, local)
                                                 └── godot-ai MCP ──▶ live Godot editor
```

The repo also contains a sibling system **WorldForge** (procedural assets/biomes)
and the integration layer **TerraForge**. The two attached manifests describe
those in detail. The bulk of the code in this package is DevForge.

The user has had one previous AI review (Claude Opus) implement 37 changes
across 22 files, and one brief session with Claude Fable 5 contribute 3 of
those fixes. The 38/38 smoke test suite passes locally. The integration
tests (`tests/integration/`) pass *on paper* but fail in the user's live
run. That gap — green tests, red wall — is what prompted this handover.

## 2. The six known issues (the user's observations)

These are the symptoms the user has seen in their live system. They are
the AI's starting brief; the AI is free to disagree, reframe, or ignore
any of them and follow its own thread.

### Issue 1 — `asyncio.run() cannot be called from a running event loop` (execution crash)

`devforge/execution/godot_ai_mcp.py` uses `asyncio.run()` at three
call sites (lines ~70, ~83, ~230) inside a *synchronous* `execute()` /
`get_scene()` / `resolve_property_types()` method. When the executor is
invoked from inside a context that already has a running event loop
(any async caller, any pytest-asyncio test, anything FastMCP itself),
`asyncio.run()` raises and the entire apply_spec returns zero operations.

**Likely root cause:** the executor's public API is sync, but the
`mcp` Python client is async-only. The author wrapped `asyncio.run()`
as a shim, which only works in a thread that *doesn't* already have a
loop. There is no `asyncio.iscoroutine` detection, no thread-pool
fallback, no `nest_asyncio`.

**Files most relevant to the diagnosis:**
- `devforge/execution/godot_ai_mcp.py` — has all three `asyncio.run` sites
- `devforge/platform/mcp_server.py` — calls `_executor.execute(...)` synchronously from inside an `@mcp.tool()` function
- `devforge/execution/interface.py` — `Executor` is declared as a sync ABC
- `tests/integration/mcp_client.py` — async test caller that exercises the same code path

### Issue 2 — Planning only produced 5 of ~10 expected operations

For a large multi-entity prompt (Player + Ground + WorldEnvironment +
Campfire + Cabin + UI + signals), the planner only returned the
Player, one CollisionShape3D, a MainCamera, and a DirectionalLight.

**Likely root causes (in order of plausibility):**
1. The architecture planner only models *entities + systems +
   connections*; the prompt's request for `WorldEnvironment`, `UI`
   (CanvasLayer/ProgressBar), and the `connect_signal` operations is
   expressible but the LLM has to remember to emit it. For a 4B
   active-param model, this is well above its natural recall budget.
2. `engine.py` line ~245 trims to `assemble(..., minimal=True)` on
   retry attempt 2+, which *removes* the code-context section — this
   may be the only place the LLM sees what scripts already exist.
3. The `arch_delta["entities"]` list is hard-capped at 15 by the
   grammar (`{0,15}`). 15 isn't the issue here, but it suggests
   the model was *allowed* to emit more, and didn't.
4. The `deterministic dedup` step in `engine.py` drops entities whose
   name appears in `system_graph.nodes` — if the LLM reuses a name
   from an earlier prompt, the entity is silently dropped with only
   an info-level log.

**Files most relevant:**
- `devforge/compilation/pipeline/architecture_planner.py` — `_build_prompt` has the prompt
- `devforge/compilation/pipeline/engine.py` — `run_pipeline`, retry/escalation logic
- `devforge/reasoning/prompts/arch_planner.gbnf` — grammar (caps at 15)
- `devforge/knowledge/system_graph/system_graph.py` — node list used for dedup

### Issue 3 — Explicit GDScript content in the prompt was ignored

The user pasted full `Player.gd`, `Campfire.gd`, `Cabin.gd` into the
prompt. DevForge emitted a placeholder script (`extends Node`,
empty `_ready()` and `_process()`) from
`architecture_compiler._generate_system_script()`.

**Root cause is structural, not a model bug.** The current pipeline
has no path from *prompt text* to *script content*. The compiler
generates a stub for *every* system it sees; the LLM's only output
is `{name, description}` per system. The "where does the actual code
come from?" question has no answer in the current architecture —
there is no step that takes "the user wrote me 80 lines of GDScript
in the prompt" and emits them as a `create_file` operation.

**Files most relevant:**
- `devforge/compilation/pipeline/architecture_planner.py::_build_prompt` — instructs the LLM to emit `description` only
- `devforge/compilation/pipeline/architecture_compiler.py::_generate_system_script` — the placeholder generator
- `devforge/compilation/ir/plan.py` — the IR has no `ScriptSourceStep` for "code that came from the prompt"
- `devforge/reasoning/prompts/planner_grammar.gbnf` — operation grammar does include `create_file`, but the architecture planner never produces the trigger to use it

### Issue 4 — Camera and DirectionalLight parented to `/root` instead of `Main`

The user expected `MainCamera` to be a child of `Player` (third-person
follow) and `DirectionalLight` to be a sibling of `Player` under `Main`.
Both ended up at `/root` (or `/root/Main`, depending on the run).

**Root cause** is in two places:

1. `architecture_compiler.py` always sets `entity_path = f"{root_path}/{name}"`
   where `root_path` is whatever `SceneGraph.root.path` returns. The
   planner output's *intent* (which entity should parent which) is
   in `delta["connections"]` but the compiler only uses `connections`
   for signals — not for parenting.
2. `completeness.py` *injects* a Camera3D and DirectionalLight3D when
   missing, and parents them to `_find_root(node_index)` — which
   returns `/root` if `/root/Main` isn't in the index yet.

The grammar (`planner_grammar.gbnf`) has a `node-path` rule that
*forces* `/root/Main/...` for the operations, so the issue manifests
in the *delta* stage, not the *operation* stage. The LLM is being asked
to produce a flat list with no parent field at all.

**Files most relevant:**
- `devforge/compilation/pipeline/architecture_compiler.py` — `compile()` line ~30, `root_path = scene.root.path`
- `devforge/compilation/pipeline/completeness.py` — `_find_root()` and the auto-injection
- `devforge/reasoning/prompts/arch_planner.gbnf` — entities have no `parent` field; only `name` and `type`

### Issue 5 — llama.cpp context window growth from ~1.8K to >13K tokens per turn

The Odysseus agent loop accumulates prompt content rapidly. Each
failed retry appends the previous error to the prompt; the engine
also does `assemble(..., minimal=False)` on attempt 1 but doesn't
actually *shrink* the context between retries (the `minimal=True`
flag is a flag, not an upper bound on the existing context).

**Likely root cause:** the retry escalation in `engine.py` re-assembles
context but doesn't *reset* it, and the conversation history inside
Odysseus itself isn't being truncated. Each retry sees:
the original context + the previous failure's error message + the
trimmed-but-still-15K-char "minimal" context, all wrapped in Gemma's
chat template twice if the same prompt is re-sent.

**Files most relevant:**
- `devforge/compilation/pipeline/engine.py` — retry loop around `planner.plan(...)`
- `devforge/compilation/pipeline/context_assembler.py` — `assemble(minimal=True)` and the budget math
- `devforge/infrastructure/llm/llama_client.py` — Gemma template wrapper; the `chat()` method's NOTE warns multi-turn is single-turn
- `devforge/infrastructure/llm/router.py` — circuit breaker / failure tracking

### Issue 6 — Initial tool hallucination in Odysseus

The LLM, on first exposure to the DevForge MCP server, tried
`{"action": "endpoints", "filter": "DevForge"}` — an internal
Odysseus API call — before eventually discovering the correct
`mcp__...__apply_spec` tool. Odysseus is the agent framework; the
LLM is supposed to learn about MCP tools from the tool discovery
handshake. Something in that handshake (or its absence) caused the
model to fall back to a remembered pattern.

**Why this is in scope:** the user observed it; it's reproducible
across their runs; and a fix may live in the prompt scaffolding
we hand to the LLM (system instructions / tool descriptions) or in
how DevForge presents its tools. The actual Odysseus internals are
out of scope (we don't have the source), but the *symptom* in
DevForge's MCP tool descriptions is fair game.

**Files most relevant:**
- `devforge/platform/mcp_server.py` — the `@mcp.tool()` decorators and their docstrings. These docstrings are what the LLM sees in the tool-discovery handshake.
- `devforge/execution/godot_ai_mcp.py` — same situation for the *downstream* godot-ai tools that DevForge's executor calls.

## 3. What the user has NOT asked for

To preserve creative freedom, the user has explicitly **not** constrained:
- Which order to tackle the issues (fix 1 first, fix 5 last, etc.)
- Whether to rewrite from scratch, patch, or wrap
- Whether to keep the MCP transport, switch to plain HTTP, or merge the two servers
- Whether to abandon GBNF grammars (4B model is fragile without them)
- Whether to add new dependencies (anthropic SDK, pydantic, langgraph, …)
- Whether to recommend a model upgrade (e.g. swap Gemma 4B for Qwen Coder 32B)
- Whether to fix things in the DevForge code, in the Godot plugin code, in the prompts, or in the runtime configuration

The user is looking for the AI to think like a senior engineer who
sees a partially-built system and tells them where the real leverage
is.

## 4. Suggested reading order (not mandatory)

If the AI wants a starting sequence:

1. `README.md` (project root) — high-level phase index
2. `SETUP-GUIDE.md` — runtime topology (the diagram in §1)
3. `SUMMARY.md` — what the 37 changes did
4. `CLAUDE-FABLE-SAFETY-MANIFEST.md` — term audit so false-positive terms don't surprise you
5. `devforge/platform/mcp_server.py` — the tool surface Odysseus sees
6. `devforge/compilation/pipeline/engine.py` — the orchestration
7. `devforge/compilation/pipeline/architecture_planner.py` + `arch_planner.gbnf` — the LLM interface
8. `devforge/compilation/pipeline/architecture_compiler.py` — the IR→ops translation
9. `devforge/execution/godot_ai_mcp.py` — the asyncio bug location
10. `tests/integration/test_forgeborn.py` — the *actual* prompts the user is running (this is the "large prompt" in Issue 2)
11. `devforge/patterns/player.json` + `npc.json` + `enemy.json` — the deterministic pre-routing tables

## 5. Verified facts (so the AI doesn't re-investigate these)

- **38/38 pipeline tests pass locally** (`devforge/verify_pipeline.py`)
- **All Claude Opus recommendations are implemented** — see `Deferred-Claude-Recommendations.md`
- **The GBNF grammar is actually enforced** — `llama_client.selftest_grammar()` runs at startup
- **Port 8000 is occupied by godot-ai; DevForge MCP must use 8001** — see SETUP-GUIDE §1
- **The `godot-ai` MCP server is a separate project** — not in this repo, can't be patched here
- **Odysseus is also a separate project** — same situation
- **No new dependencies have been added recently** — `requirements.txt` is the source of truth
- **The project is local-only** — no telemetry, no network calls except `localhost:8080` (llama.cpp) and `localhost:8000` (godot-ai)

## 6. What the user wants back from the AI

A written analysis covering, at minimum:
- **Diagnosis** — agree/refine/reject the six issues above
- **Leverage points** — where is the cheapest, highest-impact change?
- **Risk assessment** — what's likely to break if we change it?
- **Concrete proposal** — code-level changes, ordered by ROI
- **Open questions** — anything the user must answer before the proposal is actionable

Length and format are up to the AI. The user reads carefully.

---

*The user has the budget for a deep review. Take your time. The project is real and the issues are real — none of this is synthetic.*
