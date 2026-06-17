# Full-System Stress Test — Scenario + Hub Runner

**Date:** 2026-06-16
**Purpose:** visual + measurable confirmation across **every** subsystem — not
just Stage 4. One escalating run: tour each subsystem → build to the most
ambitious thing the stack should handle → step one or two past each limit to find
where it cracks. Every visual step is a Godot-editor screenshot.

**Two deliverables here:** Part A = the scenario (human-readable, the test
itself). Part B = the hub runner spec (the other AI implements: pick one-or-more
models, run the whole thing in a loop ×N, gallery the screenshots).

**Ground rules for a valid run:**
- Variety/repeat steps **must set `skip_cache=true`** or the plan cache replays
  one result and the test is void (Phase 2.5 finding).
- Run on **27B first, then 4B** for the Act III–IV A/B (apples-to-apples).
- Break steps (Act V) are *designed* to fail — the runner must time-out + catch
  per step and keep going (graceful-degrade vs. crash is the actual signal).

---

## Part A — The Scenario (Acts I–V)

Each step lists: **planner** · **prompt** · **what to watch**. `★` = take a screenshot.

### ACT I — Core pipeline (arch planner → compiler → validator → executor)
1. `arch` ★ — *"Under /Main build a small arena: a Node3D Arena containing a
   Player (capsule mesh, blue), five coins (gold spheres with colliders) under a
   Collectibles node, and a UI ScoreLabel reading 'Score: 0'."* → correct
   nesting, visible coloured meshes, label text.
2. `arch` ★ — *(on the same scene)* *"Add WASD movement to the Player and make
   each coin disappear and add score when the Player touches it."* → scripts
   attached, a **signal actually wired**.
3. `arch` ★ — *(same scene)* *"Delete two coins and rename the Player to Hero."*
   → right nodes removed/renamed, nothing else disturbed (edit-ops).
4. `arch` ★ — *(fresh scene)* *"Give a Camera3D a box mesh, put a node under a
   nonexistent 'Ghost', and also add 15 valid crates."* → the 15 crates build,
   the two bad ops are **rejected as errors, not a crash/empty scene** (graceful
   adversarial).

### ACT II — Every spatial engine at its best (one screenshot each)
5. `room` ★ — *"A cramped, abandoned rustic kitchen."*
6. `building` ★ — *"A house with a living room, a kitchen, and two bedrooms."*
7. `scatter` ★ — *"Scatter trees and bushes around the house, none inside it."*
8. `wfc` ★ — *"A 10×10 dungeon with rooms and connecting corridors."*
9. `voronoi` ★ — *"A village with 5 districts and roads between them."*
→ each produces its characteristic, **non-clipping** structure.

### ACT III — Prove the Stage 4 rebalance (variety + intent, `skip_cache=true`)
10. `room` ★×2 — build *"a cramped abandoned kitchen"* AND *"a spacious noble
    kitchen"* → **visibly different** size/colour/fullness.
11. `room` ★×3 — build *"a rustic kitchen"* **three times** → three **different**
    kitchens (the "3 houses" cure). *(This is what the loop-count ×N drives.)*
12. `room` ★×N — knob matrix, vary one axis at a time: size
    `cramped/normal/spacious`, style `rustic/industrial/noble/derelict`, clutter
    `0.1/0.5/1.0`, mood `cozy` vs `abandoned` → a contact sheet where **each knob
    visibly moves the output** (intent-coverage, made visual).

### ACT IV — The maximum (compose + make the model matter)
13. `building`+`room`+`scatter` ★ — *"A small noble manor — styled rooms inside,
    a garden of trees around it."* → a coherent, varied, complete place.
14. `room`/`arch` ★ (run on **both** 4B and 27B) — *"A noble's manor kitchen that
    is secretly a poisoner's workshop — elegant on the surface, hidden cabinets,
    a concealed back room."* → does the **27B look visibly richer** than the 4B?
    If identical, the interface is still too thin.

### ACT V — One or two steps past (break on purpose; prediction in italics)
15. `room` ★ — *"a cramped spacious cozy abandoned luxurious derelict kitchen."*
    *→ enums force a choice; watch for incoherent mush vs. sane resolution.*
16. `room` ★ — *"a neon cyberpunk kitchen with a plasma reactor and a lava moat."*
    *→ style collapses to one of the 4 allowed (intent LOST); off-lexicon props
    skipped gracefully (good) or error (bad) — exposes the rigid-enum ceiling.*
17. scale bomb ★ (×4): `building` *"a 40-room castle"* · `voronoi` *"a city with
    100 districts"* · `scatter` *"scatter 1000 trees"* · `wfc` *"a 24×24 dungeon"*.
    *→ first crack likely LLM truncation on the big prompt, then godot batch/perf
    on the 1000-tree & 100-district builds, maybe VRAM on 27B. Watch which fails
    first.*
18. `arch` ★ — *"build the concept of regret"* and *"a kitchen made of sound."*
    *→ degenerate/empty descriptor; watch graceful-empty vs. crash.*
19. `arch` ★ — *"a dungeon inside a kitchen on a floating island surrounded by a
    city."* *→ the single routed planner does its lane, ignores the rest —
    surfaces the missing compound/router planner as the next real gap.*

**How to read it:** Acts I–IV should *succeed and look right*; Act V should *fail
gracefully* (skip/log/empty), never crash or hang. The ranked next-work list will
fall out of Act V — my prediction: rigid enums lose intent (16), no compound
router (19), scale ceilings (17).

---

## Part B — Hub Runner Spec (the other AI implements)

Add a **Stress Test** runner to the hub: pick one-or-more models, set a loop
count, run the whole scenario, gallery the screenshots + status. Reuse
`harness.py`'s transactional multi-model swap (the fixed `swap_model`) and the
`apply_spec`/`editor_screenshot` paths.

### B1. Scenario data file — `hub/data/stress/stress-test-v1.json`
Drive the run from data, mirroring the gauntlet-set pattern. Structure:
```json
{
  "id": "stress-test-v1",
  "scenarios": [
    {
      "id": "A1_arena", "act": "I",
      "reset_before": true, "screenshot": true, "expect_break": false,
      "steps": [
        {"planner": "arch", "skip_cache": true,
         "prompt": "Under /Main build a small arena: ..."}
      ]
    },
    {
      "id": "A2_behavior", "act": "I",
      "reset_before": false,            // builds on A1's scene
      "screenshot": true, "expect_break": false,
      "steps": [{"planner": "arch", "skip_cache": true, "prompt": "Add WASD ..."}]
    }
    // ... one entry per Act step (1–19). Multi-build steps (e.g. Act III ×3,
    //     Act IV compose) carry multiple `steps`; variety steps set
    //     skip_cache:true; Act V entries set expect_break:true.
  ]
}
```
Field semantics: `reset_before` → reset the probe scene first (independent build)
vs. continue the previous (dependent chain — Act I 1→2→3, Act IV compose);
`screenshot` → `editor_screenshot` after the last step; `expect_break` → failures
are *expected*, recorded as "broke-gracefully" (pass) vs "crashed/timed-out"
(fail), and never abort the run.

### B2. The UI (the two options the user asked for)
A small control panel above the results:
- **Models** — a checkbox list of the available models (the 4 qwen, from
  `forge_models.scan()`); **one or more** selectable. Default: the loaded model.
  Run order: selected, small→big.
- **Loops (×N)** — a number input (1–N). Runs the *entire* scenario list N times
  per model. For the variety scenarios (Act III) the N iterations **are** the
  diversity sample; for the rest, N gives a stability/repeatability read.
- **(optional) Scope** — checkboxes to include/exclude Acts (so the user can run
  just Act III, or skip the slow Act V scale-bomb).
- **Run** → streams progress over the existing SSE job channel; one run at a time
  (`_job_lock`).

### B3. Run mechanism
```
for model in selected_models (small→big):
    swap_model(model)                      # harness.py's fixed transactional swap
    for i in 1..N:                         # loop count
        for sc in scenarios (filtered by scope):
            if sc.reset_before: probe_scene_reset()
            for step in sc.steps:
                apply_spec(prompt, planner=step.planner, skip_cache=step.skip_cache,
                           timeout=per-step)        # catch + timeout; never abort
            if sc.screenshot: shot = editor_screenshot(); save under model/i/sc.id
            record {model, i, sc.id, status, errors, node_count, latency_ms, shot_path}
persist artifact hub/data/stress/stress-<ts>.json  (+ screenshots on disk)
```
Resilience (critical — Act V *will* fail): per-step `try/except` + timeout; a
crash/timeout marks the scenario `broke` and continues. `expect_break:true`
scenarios invert the pass logic (graceful failure = pass).

### B4. Results view (the visual confirmation)
A **gallery grid**: rows = scenarios (grouped by Act), columns = model (× loop if
N>1), each cell a **screenshot thumbnail** + a status chip (built ✓ / broke ⚠ /
crashed ✗) + node-count + latency. Click a thumbnail → full screenshot.
- Act III variety rows: also show a **diversity number** across the N iterations
  (distinct-output ratio) — the "are the 3 kitchens different?" answer.
- Act IV row: 4B vs 27B **side-by-side** thumbnails for the eyeball A/B.
- Act V rows: green if it **degraded gracefully**, red if it crashed/hung.

### B5. Acceptance
- User selects ≥1 model + a loop count, clicks Run, and gets a screenshot gallery
  + per-scenario status without touching a terminal.
- A crash in any Act V step does **not** abort the run.
- The Act III diversity numbers and the Act IV 4B-vs-27B pair are visible at a
  glance.

> Note: `editor_screenshot` needs a live godot-ai plugin session (the recurring
> session-death caveat) — the runner should health-check the session before
> starting and warn if it's down rather than silently producing blank shots.
