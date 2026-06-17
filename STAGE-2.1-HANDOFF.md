# Stage 2.1 Handoff — Behavior reliability

Fresh agent: read `STAGE-1-HANDOFF.md` §0–2 first (hard constraints, orientation,
how to operate). This stage makes the scenes the pipeline builds actually *do*
something. **DevForge-only work; Odysseus + godot-ai stay vanilla.**

## Why this stage exists (evidence)
The Capability Gauntlet (`hub/gauntlet.py`, set `capability-v1`, run on qwen3)
mapped the limits precisely. Structure & properties are **maxed (100%)**: nesting
depth, breadth (24+ nodes), every prop type, collider/mesh children, mixed
2D/3D/UI. **Behavior is the ceiling:**

| Gauntlet probe | Coverage | The gap |
|---|---|---|
| G5 scripts+signals | 50% | scripts generate + attach, but **`connect_signal` = 0** (signals never wire) and entity nodes drop |
| G7 integration | 75% | structure+props perfect (26 nodes), but **scripts vanish under load** (0 generated in the big prompt) |
| G8 adversarial | 33% (broke) | bad-op input produces **nothing and no error** — no partial-build + graceful reject |

Re-run anytime: hub **Gauntlet tab → Run set**, or `python gauntlet.py --run
capability-v1`. Every fix should move these numbers; that's the acceptance gate.

## Tracks (priority order)

### T1 — Signal wiring (highest value, cleanest gap)
`connect_signal` fires **zero** times even when a prompt explicitly asks to
connect a Timer's `timeout` to a handler. The schema (`connections`) and the GBNF
(`connect_signal`) exist, so the break is downstream. Trace:
`architecture_planner.py` (does the LLM emit `connections`?) →
`architecture_compiler.py` (are connections compiled into `connect_signal`
ops?) → executor (does godot-ai wire them?). Fix the broken link.
*Acceptance:* G5 `signals ≥ 1`; a `SpawnTimer.timeout → spawner` connection
actually exists in the built scene (verify via godot-ai `signal_manage(op=list)`).

### T2 — Scripts under load
In isolation a coin gets a collect script; in the big G7 arena **0 scripts** are
generated. The planner sheds `systems` when the entity list grows (token
budget / attention). Trace whether systems are *planned* but script-gen is
skipped, or whether the planner drops systems entirely under a long prompt.
Likely levers: ensure systems survive the planner output for large deltas; or a
dedicated script-gen pass per system independent of delta size.
*Acceptance:* G7 generates **≥2 scripts** (player movement + collect) and they
attach; scripts don't vanish as scene size grows.

### T3 — Graceful adversarial handling
G8 (set a mesh on a `Camera3D`, a node under nonexistent `Ghost`, plus 20 valid
fillers) builds **nothing** and reports **no error**. One bad op nukes the whole
plan. The validator should reject bad ops **individually** and let the valid ones
through (partial success), surfacing the rejected ops as errors.
*Acceptance:* G8 builds the 20 fillers **and** reports the camera-mesh + Ghost-
parent ops as rejected (errors). Gauntlet `expect_errors` + `min_nodes` both met.

### T4 — Gauntlet upkeep (do alongside)
- Add a **`behavior-v1.json`** prompt set (signal-heavy, script-heavy, and
  adversarial variants) so this stage has a dedicated tracker, separate from the
  structural `capability-v1`.
- Fix the probe scene's **`Main2` root corruption**: prior runs left the disposable
  `res://probe.tscn` editor root renamed `Main2`. The reset (`bench._probe_scene_reset`)
  now cleans *content* reliably (deletes children — Godot won't reload an open
  dirty tab), but the root name is cosmetically wrong. Restore a clean `Main`
  root (a one-time editor scene reload, or a robust reload mechanism). Low
  urgency — the pipeline maps `/Main`→root correctly — but worth a clean baseline.

## Ops planner — DECIDED (June 14, 2026)

**Decision: SHELVED.** Phase 6's `DEVFORGE_PLANNER=ops` path A/B'd at **14/100 vs
arch 61** (qwen3, `shootout.py --all-planners`). Root cause is not a fixable bug —
the shootout data shows the ops planner produced **2 operations** (both auto-injected
camera+light from completeness) vs the arch path's **45 operations** (arena, player,
5 coins with colliders/meshes/colors, UI). The LLM simply cannot emit 45+ detailed
JSON operation objects in a single GBNF-constrained call for a complex prompt.

The arch path's multi-step pipeline (plan entities/systems → compiler → ops) is the
correct architecture. The ops path is an architectural dead end — the compiler does
work the LLM can't. The `--all-planners` flag, planner-switching infrastructure, and
`ops_planner.py` remain in place but untested. The `ops` mode is marked EXPERIMENTAL
in `FORGE-STACK.md`'s env var docs.

## IMPLEMENTATION STATUS (June 14, second pass)

- **T2 — DONE & verified.** Deterministic system inference recovers the systems
  the LLM sheds under load. `ArchitectureCompiler.infer_systems(prompt, entities,
  systems)` scans the prompt for template intents and, for each intent with a
  matching entity type, synthesizes a system so the systems→script→attach
  pipeline runs. Wired in `engine._run_arch_path` before compile. **Verified:**
  G7 went from **0 → 4 generated scripts**.
- **T1 — IMPLEMENTED.** Compiler now (a) resolves connection endpoints that name
  a *system* to the node its script attaches to (`system_attach` map), and
  (b) derives the signal from the source node's type (`_DEFAULT_SIGNAL_BY_TYPE`:
  Timer→`timeout`, Area3D→`body_entered`, Button→`pressed`) instead of always
  defaulting to `body_entered`. Build verified landing nodes; in-scene signal
  *wiring* not yet re-confirmed (see blocker below).
- **T3 — DEFERRED with root cause.** G8 builds nothing because godot-ai's
  `batch_execute` is **atomic** — one bad op (`mesh` on a `Camera3D` that slips
  past validation) rolls the whole batch back. The executor only falls back to
  per-op on an *exception*, not a failure *result*. Safe fix: add property-type
  validation (mesh→MeshInstance3D, shape→CollisionShape3D, with pending-node
  types) so the bad op is filtered pre-batch and the batch stays clean. The
  result-based per-op fallback is risky (double-apply if the batch isn't truly
  atomic) — prefer the validation route.

**⚠ Verification blocker:** the Godot editor's disposable `probe.tscn` got its
root renamed to `Main2` with scene-tab desync (accumulated from today's reset
cycles), so the **gauntlet's before/after node diff is unreliable right now** —
it reports `nodes 0` even when the build applies (verified: 35 ops applied, real
nodes land). 318 DevForge tests pass and a clean-scene apply confirms the code.
**To get trustworthy gauntlet numbers, restart the Godot editor** (reloads
probe.tscn fresh from the clean disk file) then re-run `gauntlet.py --run
capability-v1`. The reset deletes children reliably but cannot rename a root the
editor holds open — a true editor reload is the only clean fix (T4 item).

## ⚠ RE-VERIFICATION (June 14) — original sharpened root causes

A first implementation pass changed the right files and kept tests green, but the
**gauntlet metrics did not move** (capability-v1 behavior probes still 50/75/33%).
"Tests pass" ≠ "behavior works" — this is exactly why the gauntlet exists. Verified
root causes (from inspecting the live `arch_delta` on qwen3), per track:

**T1 — signals.** The LLM **does** emit connections (G5 delta:
`{"from":"SpawnTimer","to":"Spawner","type":"signal"}`), so the gap is NOT the
prompt. Two real bugs: (a) the connection targets a **system name** ("Spawner",
a script) not a **node** — the compiler can't resolve a node path to connect to;
(b) the connection schema has **no signal name** (which signal? `timeout`). Fix:
connections must be **node→node** with an explicit signal (extend schema/grammar
to `{"from_node","signal","to_node","method"}`), and the compiler resolves both
ends to real node paths before emitting `connect_signal`. Verify the signal
actually exists in the built scene via godot-ai `signal_manage(op=list)`.

**T2 — scripts under load.** For the big G7 prompt the LLM emits **24 entities but
0 systems and 0 connections** — it drops the entire `systems`/`connections`
sections under load. Lowering the intent-detection threshold is irrelevant when
there are zero systems to detect. Fix where systems are *produced*: e.g. a
dedicated second planner call that generates `systems` for the already-planned
entities (so script-gen is independent of entity-list size), or restructure the
single call so systems aren't crowded out. Acceptance: G7 delta has ≥2 systems →
≥2 scripts attached.

**T3 — adversarial.** G8 applied **1/47 ops with 0 errors** — the per-op fallback
(`_execute_ops_individually`) is not letting the 20 valid filler nodes through,
and the bad ops surface no error. Investigate whether the **validator filters the
fillers pre-execution** (so the fallback never sees them) and why nothing is
reported. Acceptance: G8 builds the 20 fillers AND reports the camera-mesh +
Ghost-parent ops as rejected.

**Also G5:** 5 entities planned but **0 land** (applied 5/14, built 0). Separate
from signals — investigate why G5's entities don't reach the scene while G7's 24 do.

## Stage 2.1 done =
- Gauntlet `capability-v1` average **≥ 95%** on qwen3 (G5/G7/G8 climb).
- Signals wire; scripts survive load; adversarial = partial build + clear reject.
- `behavior-v1` set committed; ops-planner decision made + documented.
- 318 DevForge + ≥133 hub tests green; chain probe green (`llama.grammar` still
  `works`); no Odysseus/godot-ai source touched.
