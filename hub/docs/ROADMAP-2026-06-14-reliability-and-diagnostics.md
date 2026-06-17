# Roadmap — Scenario Reliability & Diagnostic Capacity (for the next AI)

**This is a roadmap, not a spec.** You decide *how* and *what* to implement. It deliberately
leaves room for your judgment — the point is an **outside perspective** to break a tunnel-vision
pattern: the prior diagnoses on this work were revised several times, and we'd rather you
re-derive than inherit. **Treat every conclusion below as a hypothesis to verify, not a fact.**

## Why you're getting a roadmap instead of a task list
The previous handoffs (`AUDIT-BRIEF-2026-06-14.md`, `SCENARIO-FIXES-BRIEF-2026-06-14.md`) were
precise file:line specs. They worked, but they also steered. For this next phase we want your
own read of the problem and your own choices about approach, sequencing, and even whether the
goals below are the right goals. Push back where you disagree.

## Constraints (these are firm — everything else is open)
- **Odysseus (`~/dev/ai/odysseus`) and godot-ai (`~/dev/games/rpg/addons/godot_ai`) stay VANILLA.**
  Adapt only DevForge (`devforge_review_package/...`), the hub (`~/dev/games/Forge/hub`),
  `stack.env`/`forge-model`, or Odysseus config.
- `stack.env` + `forge-model` are the single source of truth; hub is loopback-only.
- Verify with evidence; never report a number you didn't measure.
- The Forge stack runs on `systemd --user` services + the Godot editor — independent of any AI
  harness. Don't introduce anything that needs an AI running permanently.

## Where things stand (context, briefly — verify it yourself)
- The **Main→Main2 root corruption was diagnosed as a cascade** from hardcoded `/root/Main` and
  fixed by making the arch path resolve the live root (`architecture_compiler.py`,
  `completeness.py`). The **scenario build/edit failures** (invalid-property atomic rollback;
  dropped delete/rename intent) were then fixed by another AI (validator, compiler, engine,
  planner, `godot_node_types.py`). Unit suites pass (DevForge ~371, hub 151, spatial 30).
- **Verification is currently blocked by a stale-editor artifact:** the Godot editor's
  `probe.tscn` tab is cached at root "Main2" (from old code that ran before forge-devforge was
  restarted). The live build is correct — all nodes build — but they land under the cached
  "Main2", so assertions checking `/Main` read 0%. Clearing it needs a **Godot reload** (the
  no-op `scene_open` on a dirty tab won't reload, and a scene root can't be renamed via MCP).
- Full context + the revision history of the diagnoses: the two briefs above.

## The real problem this roadmap is about
We keep debugging **blind and ad-hoc**: from scorecards + manual scene inspection, one hypothesis
at a time, several of them wrong before they were right. The deeper goals:
1. Get a **trustworthy** scenario score (which means a trustworthy *harness* first).
2. Start using the **diagnostic data the system already emits** instead of inferring.
3. Decide whether it's time to **instrument for the future** so debugging becomes data-driven.

---

## Thread A — Verify, and decide whether the harness can even be trusted
Run the full battery once the probe scene is healed (you decide what "full battery" includes —
DevForge/hub/spatial unit suites, the scenario suite, the gauntlet set(s), the chain probes,
godot-ai GUT tests, smoke runs…). But the **open question is more interesting than the numbers:**

> Is the scenario harness itself trustworthy enough that its score means anything?

The Main2-cache incident suggests the harness is fragile: one corrupted editor tab silently
poisons every run; `scene_open` is a no-op on a dirty tab; probe isolation depends on a reset
that can't heal a renamed root. You might conclude the **harness needs hardening (or rethinking)
before its numbers are worth trusting** — e.g. fail-loud when the probe root isn't what's
expected, make assertions root-agnostic, use a fresh disposable scene per run, or something we
haven't thought of. Your call. Or you might conclude the current harness is fine and this was a
one-off. Either way, justify it.

## Thread B — Data the project emits that we are NOT using
We've leaned almost entirely on scorecards and `scene_get_hierarchy`. The system exposes a lot
more. **Survey what's actually available, decide what's genuinely useful for diagnostics, and
wire the useful parts into the workflow** (hub UI, a debug command, whatever fits). Candidates we
have barely or never touched — not a checklist, a starting point for your own survey:
- **`read_artifact`** — full per-operation details *and execution diagnostics* for every
  `apply_spec`. We inferred build outcomes from scene snapshots; the artifact has the actual
  per-op results. This is probably the highest-value unused source — but confirm that yourself.
- **`editor_screenshot`** — visual ground truth. (The user once couldn't tell whether a "kitchen"
  built; a screenshot answers that directly. Worth considering for any visual verification.)
- **`triage_errors`**, **`smoke_run`**, **`audit_scene`**, **`signal_map`**, **`validate_spec`**,
  **`perf_sample` / `perf_history`**, **`journal_entries` / `journal_summary`**, godot-ai
  **`logs_read`** and **`test_run`/`test_manage`** (GUT tests in-editor).
- **Historical data already on disk:** `hub/data/` holds many scorecards, gauntlet runs, bench
  runs, probe history. Trends across these may reveal regressions/variance we can't see in a
  single run. The action log too.
- Decide what's signal vs. noise. We don't need all of it — we need the few that change how we
  debug.

## Thread C — Is it time to instrument for the future? (your judgment on timing)
The user raised: maybe pivot toward **systematically collecting performance/issue data for later
analysis — *if it isn't too early.*** That "if" is a real decision, and it's yours:
- If the system is still firefighting/unstable, heavy instrumentation is premature overhead.
- If it's stabilizing, a lightweight, durable record (per-build artifacts retained, perf samples
  over time, a failure/issue log that accrues) turns future debugging from archaeology into
  query.
Decide, justify, and if you proceed, keep it **lightweight and self-contained** (no permanent
AI/daemon dependency; fits the existing `hub/data/` + systemd model).

---

## Things to actively challenge (don't inherit our blind spots)
- **The Main2 root-cause story.** Re-derive it. Is "hardcoded `/root/Main` → cascade" actually
  complete, or is there a more fundamental reason builds ever produced a second "Main"?
- **The per-scenario isolation model.** Reset-between-scenarios caused bare scenes; no-reset
  causes node accumulation. Maybe both are wrong and there's a cleaner isolation primitive.
- **Whether scenario-assertions are even the right eval.** The gauntlet uses a coverage model;
  scenarios use pass/fail assertions on exact paths. Which actually predicts "the tool builds
  what the user asked"? Maybe they should converge, or one should go.
- **Our framing of "score."** We've fixated on a percentage. Is that the metric that matters, or
  is variance / corruption-rate / time-to-build more important to the user's real goal?

## What we'd like back from you
Not just merged fixes — a short writeup of: what you found (especially where you disagreed with
the above), what you chose to do and why, what data you decided was worth wiring in, your call on
Thread C's timing, and what you'd do next. The outside perspective is the deliverable.

## Immediate prerequisite (human, ~30s)
The Godot editor's `probe.tscn` tab must be reloaded (restart Godot, or close the probe tab
without saving) before any scenario run reports real numbers — otherwise you'll measure the stale
"Main2" cache and get a misleading 0%. Confirm the probe root reads "Main" before trusting a run.
