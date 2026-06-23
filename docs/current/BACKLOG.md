# Forge Backlog (pre-roadmap capture)

Single place tracking everything open. **Plan:** when the 5-round audit finishes, synthesize
*everything below* + the audit findings into a **roadmap → milestone**, then step back and choose
direction. Nothing here is sequenced yet; this is the capture, not the plan.

_Last updated: 2026-06-24._

---

## A. Strategic / architectural (NEW — from the Q1/Q2 discussion)

- **Iterative editing loop** — modify an existing scene with follow-up prompts ("brighter", "add a
  window", "move the table") instead of regenerating from scratch. Needs: a *delta interpreter*
  (prompt → Brief modification), a *re-realize* step (reuse caches, stable seeds/ids), and
  persisted scene state. Architecturally a natural extension of the Brief-driven + deterministic +
  content-addressed design — not a rewrite. **Park a brainstorm for post-showcase.**
- **Brief + seed + plan persistence (do this SOON)** — treat the Brief/seed/plan as a first-class,
  re-loadable artifact per build (today the build is disposable). Cheap insurance that keeps
  iterative editing a "thread" not a "rewrite"; stop deepening single-shot-only assumptions.
- **Q1 dead-ends to outgrow (different solution, not refactor):** the "disposable Godot project per
  prompt" single-scene realization model; the narrow runtime capability layer (fetch-quest +
  dialogue only — the Capability pillar needs a general game-logic layer); string-built `.tscn`
  emission (ceiling); the hand-maintained Python→Godot data contract.

## B. Coherence stack (hybrid PBR + stylized roof) — in progress

- **CP‑1 + CP‑2** (palette contract + unified material system) — landed; palette harmony fix + wire
  palette into the build path are out as CLI prompts. Two-palette recolor render pending those.
- **CP‑3 — geometry/scale normalization + neural surface classification** (retopo/re-UV → triplanar
  funnel). Not started. Needed when neural assets arrive.
- **CP‑4 — NPR presentation roof** (stylized shader on PBR base + post: grade LUT / palette quantize
  / optional outline). Not started. The "look" that buys forgiveness.
- **CP‑5 — lighting integration** as the grounding base — mostly done (lighting_planner + bake).

## C. Scene feature threads

- **Exterior (#3)** — "wire the outside up." Direction locked (procedural-only flora/terrain,
  unified materials, neural-deferred). Spec NOT written; parked pending coherence/art-direction.
  Needs: terrain GLB generator + flora generators + class textures (foliage/rock/soil) + wiring +
  room↔exterior link. (Audit A5: collapse the two outdoor paths first.)
- **Lighting tuning** — the lit scene overshot (blown highlights); pull back torch/hearth energy +
  exposure. Deferred until palette harmony fix + palette wiring land (judge together).
- **Dialogue↔target consistency check (#4)** — extend the existing validator layer
  (dialogue_validator/quest_validator) to flag "ask references item X but target is class Y" (the
  4B "find my gem → bring a book" bug). Small.
- **Prop texture quality (#7)** — largely subsumed by CP‑2 (props now wear palette class materials);
  re-evaluate after the recolor render.
- **Level-design branch (#6)** — material/spatial variety, composition, zones. Large, future.
- **Per-class `foliage/rock/soil` textures** — deferred to the exterior thread.

## D. UI (re-surfaced — "got lost on the way")

- **UI thread — UNDERSPECIFIED, needs its own brainstorm to define WHAT.** Candidates that got
  conflated: (1) an **engine-driving UI** to enter prompts, watch the build, and *iterate* on a
  scene (ties directly to the iterative-editing loop in §A); (2) the **in-game HUD/legibility**
  surface (build_report_panel.gd exists); (3) the **hub** dev/ops panel (exists). Decide scope
  before designing.

## E. Engineering / quality (from the audit + known)

- **Audit Round 1 (architecture)** — `AUDIT-01-architecture.md`, 20 findings. Top leverage
  **A1+A2+A5**: decompose `scene_compiler.py` (2303 LOC) → ~6 modules; extract shared `tscn_writer.py`
  + unified bake contract; collapse the two outdoor emission paths. (A12/A13 need runtime
  verification; A16 `2^31` empty stray file — safe to rm.)
- **Audit Rounds 2–5** — correctness/determinism/robustness, code-quality/conventions, test health,
  targeted performance. Pending; findings fold into the roadmap.
- **Flaky test** `test_quest_lighting_wiring::test_plan_runs_before_shell` — isolation bug (CLI
  prompt C out).
- **Test-suite time** — `-m "not blender"` gate added (~110s); optional `pytest-xdist` after the
  flake is fixed.
- **Small chores** — game-mode wrapper into the repo (hub/bin/forge-gamemode tracked copy).

## F. Pre-existing parked

- MATURITY-LEAP-BACKLOG.md (maturity-leap audit) — parked.
- Earlier maturity audit (Worldbuilding / UX / Blindspots) — parked.

---

**Roadmap step (after audit):** merge §A–F + audit findings into a prioritized roadmap that defines
the next **milestone**, with UI explicitly scoped. Then assess the whole project from that milestone
and choose direction.
