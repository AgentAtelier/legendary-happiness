# Grand Roadmap — Data-Driven Diagnostics & Open Work (for the next AI)

**Mandate from the human:** *stop fixing by intuition.* From here on the method is
**instrument → measure → isolate the variable → fix → re-measure.** Every claim must be backed
by data you collected, not a plausible story. Where this roadmap states a cause, treat it as a
**hypothesis to test**, not a fact — several of our prior "root causes" were revised 2–3 times.

This is intentionally **broad and open**. It is a roadmap, not a spec: you decide *what* to do,
*in what order*, and *how*. There is a lot here on purpose — pick the highest-leverage threads,
say why, and **write up what you find**. Documentation of findings is a first-class deliverable,
not an afterthought.

---

## 0. Ground rules (firm)
- **Odysseus (`~/dev/ai/odysseus`) and godot-ai (`~/dev/games/rpg/addons/godot_ai`) stay
  VANILLA.** Adapt only DevForge (`devforge_review_package/...`), the hub (`~/dev/games/Forge/hub`),
  `stack.env`/`forge-model`, or Odysseus *config*.
- The stack runs on `systemd --user` services (`forge-llama`, `forge-devforge`, `forge-godot-ai`,
  `forge-hub`) + the Godot editor. **Nothing may require an AI/daemon running permanently.**
- After ANY DevForge code change: `systemctl --user restart forge-devforge`. After hub.py:
  `systemctl --user restart forge-hub`. Frontend (`index.html`) is served from disk — no restart.
- **Verify with evidence.** A passing unit test ≠ a working feature. Run it live; read the data.
- `stack.env`/`forge-model` are the single source of truth; hub is loopback-only.

## 1. Read these first (the trail — don't re-derive)
In `hub/docs/`: `AUDIT-BRIEF-2026-06-14.md` (the whole saga + revision history),
`SCENARIO-FIXES-BRIEF`, `IMPLEMENTATION-PLAN-...-reliability-diagnostics`,
`IMPLEMENTATION-COMPLETE`, `FINDINGS-TACKLE`, `ROADMAP-...-reliability-and-diagnostics`.
The memory note `forge-hub` (in the human's agent memory) has the condensed timeline.

## 2. State of truth (what's done / verified / open — verify it yourself)
**Done + verified:** Main→Main2 cascade fixed (root resolution de-hardcoded in arch_compiler +
completeness); Bug 1 (invalid-property atomic rollback) fixed → `light_create`/`small_room`/
`batch_three` pass; scenario suite reached **75% (9/12)** on qwen3 with 0 errors; harness
hardened (bounce-reload reset + fail-loud probe-root health check); unified `/api/runs` +
`/api/runs/stability` + `/api/runs/compare` live; per-op `execution.errors` + `stage_latencies`
captured into scenario results.

**Done but NOT live-verified:** the edit-target **resolver fix** (`architecture_compiler.
_resolve_node_target` now strips punctuation + token-matches real node names) and the **seed
harness** + 3 edit-on-existing scenarios (`delete_existing`, `delete_existing_bare`,
`rename_existing`). Unit tests pass (371 DevForge + 151 hub). They are NOT validated live because
the planner truncates first (see Open Issue #1).

**Open (the meat — all framed as investigations below):** planner truncation on edit prompts;
same-batch create-then-edit semantics; unapplied thinking/reasoning config; recurring godot-ai
session death; and a backlog of grunt/hygiene.

---

## Workstream A — Diagnostic data retrieval (the human's PRIMARY interest)
*Goal: make the system's behavior observable so we look at the right thing first. Survey, decide
what's signal, wire the useful parts. Don't build all of it — build what changes how we debug.*

- **A1. `logs_read` (godot-ai's own error log).** Highest-priority unused source. It likely
  explains both the **session deaths** and whether truncated/failed builds leave bridge-side
  traces DevForge never sees. Wire a hub endpoint + a Testing-tab panel; capture it automatically
  on any scenario/gauntlet failure. *Question to answer with it: why does the godot-ai session
  drop, and is it correlated with model load / VRAM / specific ops?*
- **A2. Planner instrumentation (for Open Issue #1).** We currently see "plan truncated" but not
  *why*. Capture, per `apply_spec`: the **raw LLM output**, token count vs n_predict, the
  thinking-vs-JSON ratio, `plan_retries`, `repair_count`. Surface truncation **rate** over runs.
  This turns "it truncated" into "edit prompts spend N tokens thinking before emitting J tokens of
  JSON, truncating X% of the time." (DevForge already has `stage_latencies`, `plan_retries`,
  `repair_count` in the artifact — start there.)
- **A3. Runtime / play-mode data.** Everything we read is editor-time/static. `project_run` +
  `game_manage` + `logs_read` can capture what happens when the scene **plays**: runtime errors,
  FPS, script parse failures, missing resources. Decide whether a "smoke-play" probe (build →
  run → read runtime log → stop) is worth adding.
- **A4. Godot's error/warning stream.** Script parse errors, type errors, missing-resource
  warnings — currently caught only indirectly. Find where godot-ai exposes these (tool registry)
  and wire them.
- **A5. Surface what's already collected.** `stage_latencies` (planning/compilation/execution
  split) and per-op `execution.errors` are captured but barely shown. Put them in the Testing-tab
  UI so a slow/failed build is legible at a glance. The DevForge **journal**
  (`devforge/journal/`) tracks per-tool-call timing/outcome and is unread — evaluate it.
- **A6. `editor_screenshot`.** Cheap human ground truth (the "did the kitchen actually build?"
  question). Defer automated/vision use; a "show screenshot" button is low-cost, high-trust.
- **A7. Inventory the full tool surface.** Enumerate **every** godot-ai and DevForge MCP tool and
  the **fields each returns** (call the registries; don't trust memory). Produce a reference doc:
  "what data can we get, from where, how fresh." This is the map the rest of A is drawn from.

## Workstream B — Open issues, as scientific investigations
*For each: form a hypothesis, design a measurement that isolates ONE variable, run it, report.*

- **B1. Planner truncation on edit prompts (BLOCKER for the resolver verification).** Symptom:
  `"Architecture plan truncated — hit n_predict limit"` on trivial prompts like `"Delete Gizmo."`,
  **intermittently** (an ad-hoc `"Delete Victim."` completed; the scenario run truncated).
  Hypotheses to test, not assume: (a) the thinking/reasoning config (`--reasoning-budget 1024`,
  no `enable_thinking:false` — see B3) makes qwen3 burn n_predict on reasoning before emitting
  JSON; (b) the planner prompt, given a populated scene, tries to re-emit the whole scene as
  entities; (c) n_predict (6144) is simply too low for edit-class prompts. **Measure** (via A2)
  what the model actually emits on an edit prompt before deciding. This is the #1 thing blocking
  the edit-op score.
- **B2. Same-batch create-then-edit semantics.** `node_delete`/`node_rename` fail with
  `Op N (remove_node): node '/root/Main/ToDelete' not found` — the delete/rename op can't see a
  node created **earlier in the same batch** (godot-ai `batch_execute` is atomic + may resolve
  paths against the pre-batch snapshot). Hypotheses: (a) it's a genuine batch-snapshot limitation
  → the planner should split create-then-edit into ordered batches, or recognize the net-zero and
  emit nothing; (b) "create then delete it" is a degenerate test we shouldn't optimize for (the
  realistic case is editing existing nodes — that's what the new `*_existing` scenarios test).
  **Decide whether this is worth fixing or whether the test is wrong.**
- **B3. The unapplied thinking/reasoning config.** `forge-stack-chain.md` documents a PENDING
  change (remove `--reasoning-budget 1024`, add `LLAMA_ARG_CHAT_TEMPLATE_KWARGS='{"enable_thinking":
  false}'`) that the human deliberately hasn't applied. chain-health correctly flags it as
  `config-doc stale`. **This may be the cause of B1.** Design a clean A/B: run the edit scenarios
  with vs without the change (it's a `stack.env` edit + llama restart — reversible). Measure
  truncation rate + scenario score both ways. **Do NOT apply it as a default without the human;
  present the data and let them decide.** (Note: it affects shared chat + DevForge sampling.)
- **B4. Recurring godot-ai session death.** The dominant reliability blocker — it's halted
  verification 3+ times. Pattern: editor + bridge up, but `session_manage list` → 0 sessions, no
  auto-reconnect. Use A1 (`logs_read`) + timing to find *why* it drops (VRAM under qwen3? a
  specific op? idle timeout?). A reliable repro or a clear cause is worth more than another
  scenario %.
- **B5. Resolver fix live-validation.** Once B1 is unblocked, confirm the resolver actually
  resolves messy targets (`"Victim."`, `"the node named Victim from the scene."`) to real nodes —
  the `*_existing` scenarios are the test. If it doesn't, the token-match heuristic needs work.

## Workstream C — Measurement infrastructure (make "scientific" the default)
- **C1. Variable-isolation harness.** The central question (per `scenarios.py`'s own docstring) is
  *"is a failure the model, the setup, or DevForge?"* The pieces exist but aren't wired into one
  view: the **raw tool-call axis** (model-only, no DevForge — already in `scenarios.py`,
  underused) isolates model capability; the artifact `execution.errors` isolate DevForge/bridge.
  Build the harness/report that answers "model vs DevForge vs setup" **per failure**, automatically.
- **C2. A/B config testing.** Generalize B3 into a small capability: run a suite under config X vs
  config Y (model, reasoning-budget, n_predict, template) and diff the results via
  `/api/runs/compare` + `/api/runs/stability`. This is how config questions get answered with data
  instead of folklore.
- **C3. Stability over score.** We built `/api/runs/stability` (mean, stddev, trend, failure
  signature). Actually *use* it — track variance, not just the headline %. Surface "same failure
  repeating" vs "new failure" in the UI.

- **B6. Gauntlet G4_children LLM hallucination (investigated 2026-06-15).** See `FINDINGS-G4-CHILDREN.md`.

## Workstream D — Grunt work & hygiene (plenty of it; good usage sink)
- **D1. Dead code:** ~600 lines of the four old testing-tab bodies + their JS remain in
  `index.html`, hidden/unreachable. Remove them carefully (JS parses, internally consistent — see
  the audit brief's inventory) and re-verify the Testing tab.
- **D2. `main.tscn` pollution:** `/Main/ToDelete` + `/Main/OldName` are leftover test junk in the
  real scene. Clean to the baseline (Main/Camera3D/Ground/DirectionalLight). (Touch main.tscn only
  for this; everything else stays in the probe.)
- **D3. P6 — tests perturb live state:** `pytest hub/tests/` writes `swap`/`test`/`reconcile`
  entries to the live action log. Make the suite never dispatch against the running stack.
- **D4. Restart hygiene:** the "restart forge-devforge after a DevForge code change" step is
  manual and easy to forget (it caused a stale-code 0% once). Consider a hub affordance that
  detects code newer than the running service and warns, or a one-click restart in the panel.
- **D5. Config-doc reconciliation:** resolve every `config-doc stale` item (B3 is one) so
  chain-health goes green or the doc is updated to match reality.
- **D6. Test coherence pass (broad):** beyond the edit scenarios, audit the whole scenario +
  gauntlet + bench suite for conflated signals, hardcoded assumptions, and overlap. The human
  explicitly invited a coherence rework if it's the better approach.
- **D7. Shootout/compare result mapping** is best-effort (the shootout file shape was never fully
  read); and gauntlet "fast" depth doesn't actually subset. Tidy both.

## Workstream E — Deferred capability (lower priority; the human wants diagnostics now)
- **E1. The spatial "kitchen" has never been built live.** Code exists + is unit-tested; the live
  build never ran post-fix. Now that root resolution is fixed and the harness is reliable, it's a
  clean acceptance demo when capability work resumes.
- **E2. Behavior reliability (signals/scripts under load)** — the gauntlet's G5/G7 history.
- **E3. The Testing-tab UX polish / the deferred `editor_screenshot` button** (overlaps A6).

## 3. Things to actively challenge (don't inherit our blind spots)
- That **B1 = thinking config**. It's the leading hypothesis; prove it before fixing it.
- That **create-then-delete is worth fixing** at all (B2) vs. being a degenerate test.
- That **scenario % is the metric** — variance/corruption-rate/time-to-build may matter more.
- That the **scenario harness** is the right eval shape vs. the gauntlet's coverage model (keep
  them separate per prior analysis, but question whether either is measuring the real goal).
- Our entire **"model vs DevForge vs setup"** attribution — build C1 and let it referee, rather
  than us guessing per failure.

## 4. Deliverables we want back (documentation is first-class)
For whatever you tackle: a short writeup per thread — the **hypothesis**, the **measurement you
designed**, the **data**, what it **showed** (especially where it contradicted this roadmap), what
you **changed**, and the **re-measurement**. Plus the A7 tool-surface reference doc. The goal is
that the next person (AI or human) can see *why* a decision was made from the data, not the vibe.

## 5. Suggested first moves (your call, but if unsure)
1. **A7** (inventory the tool surface) + **A1** (`logs_read`) — cheap, and they unblock
   understanding B4 and B1.
2. **A2** (planner instrumentation) → then **B1/B3** with real data (the truncation is the
   current hard blocker on the edit-op score).
3. Then pick from D (grunt) and C (measurement infra) as the data suggests.
