# Implementation Plan — Reliability & Diagnostics (agreed + refined)

Built on `FINDINGS-TACKLE-2026-06-14.md`. **Most of the findings are endorsed** — the analysis is
good and two linchpin data claims were independently verified (artifact `execution.errors` +
`stage_latencies` both exist and are already collected). Below: 6 refinements, then a clear,
sequenced build order with acceptance criteria. Where the findings doc already specifies a
sensible "how," follow it; this plan governs **what, in what order, and the decisions to make.**

## Constraints (firm)
Odysseus + godot-ai stay VANILLA; DevForge/hub/stack.env are adaptable; loopback-only; nothing
needs an AI/daemon running permanently; verify with evidence. **Before trusting ANY scenario
run, confirm the probe root reads "Main"** (the stale-Main2 tab is why a 0% can be a lie).

---

## 6 refinements to the findings

### R1 — The bounce-scene reload IS the per-scenario reset fix. Move it to Tier 1.
The findings list "bounce-scene trick" as medium-term (#7), separate from the per-scenario
isolation question. They're the **same fix**. The recurring stale-tab incidents (including the 0%
that triggered this whole thread) come from `scene_open` being a no-op on a dirty tab. A real
bounce reload (open a throwaway scene first, then the probe) is the ONLY thing that gives each
scenario a genuinely fresh scene. It's proven — the shootout already does it. This is the cure for
the harness's most painful failure mode; it belongs first, not last.

### R2 — Health-check must run REGARDLESS of root-agnostic assertions (don't let resilience hide corruption).
Root-agnostic assertions (resolve the live root instead of hardcoding `/Main`) are good for
resilience to legitimate root-name variation. But if assertions silently pass against a "Main2"
root, we'd **mask** the corruption we spent days chasing. So: the probe-root health check
(fail-loud when the root isn't the single clean Node3D we expect) runs **first and always**;
root-agnostic assertions are defense-in-depth, not a substitute. Order matters: detect-and-shout
before tolerate.

### R3 — Decide the probe BASELINE; it resolves the accumulation-vs-injection mess.
This is the open design decision under the per-scenario reset. Evidence from this week:
- With NO per-scenario reset → completeness-injected `MainCamera`/`DirectionalLight` **accumulate**
  across scenarios; a later scenario's light gets skipped because a light already exists.
- With a per-scenario reset to a BARE root → completeness **injects** camera/light every time, and
  scenarios asserting `no_extra_nodes` (e.g. `batch_three`) fail on the injected extras.
**Recommended decision:** give the disposable probe a real baseline — root + `Camera3D` +
`DirectionalLight3D` (+ `Ground` if useful) — bake it into `PROBE_SCENE_TSCN`, add those names to
each scenario's excluded/baseline set, and **bounce-reload to that baseline per scenario**. Then
completeness sees a "complete" 3D scene and injects nothing, scenarios build cleanly on top, and
`no_extra_nodes` holds. (If you find a cleaner primitive, justify it — but resolve this explicitly;
leaving it implicit is what caused the 50%↔58% flip-flop.)

### R4 — Thread C's envelope MUST align with the existing `forge_score` schema (don't fork it).
The Testing-tab rework already introduced a unified result shape:
`forge_score.normalize_result(suite, raw, target, label) → {suite, target, label, score, verdict,
metrics:[{label,value,good}]}`, and the Testing tab renders history from it. The findings' proposed
`{kind, model, config_hash, counts}` envelope overlaps this. **Make them one schema:** extend the
common envelope to carry `forge_score`'s fields (or have `/api/runs` emit `normalize_result`
shape), and feed the Testing tab's history view from `/api/runs` rather than the current per-tool
history calls + localStorage. One schema, one history surface — not two.

### R5 — `editor_screenshot`: defer *automated* use, but add a cheap human "screenshot" button.
The findings say skip (needs a vision model). For *automation*, agreed. But the value is **human
ground truth** — the user literally couldn't tell whether a "kitchen" built. A one-call "show
current editor screenshot" button in the hub needs no vision model and directly answers "did it
actually build?" Low cost, high trust. Add it when convenient; don't gate it on a vision model.

### R6 — Endorsed without change.
Stability/failure-signature over raw `pass_rate`; scenarios and gauntlet stay **separate** (don't
converge); instrumentation = surface-what's-collected, not new collection; artifact
`execution.errors` + `stage_latencies` are the top unused data. These calls are right.

---

## Build order (refined)

### Tier 1 — harness trust (do first; low risk; stops the recurring pain)
1. **Probe-root health check** (R2). At suite/gauntlet start: `scene_get_hierarchy` depth=1; require
   exactly one root, a `Node3D`, named as expected. If not, emit a clear, actionable diagnostic and
   **refuse to run** (don't produce a misleading score). 
2. **Bounce-scene reload in `_probe_scene_reset()`** (R1+R3). Open a throwaway scene
   (`res://probe_bounce.tscn`) then the probe, forcing a real disk reload; reload to the decided
   baseline (R3). This makes per-scenario isolation actually work and kills the stale-tab class.
3. **Surface artifact `execution.errors` in scenario failures.** When a scenario fails, read the
   artifact's per-op `execution.errors`/`results` and report *which ops failed and why*, not just
   `error_count`. (The data's already there via `read_artifact`.)

**Tier 1 acceptance:** a corrupted probe root makes the suite refuse with a clear message (never a
silent 0%); a fresh full run on qwen3 produces a trustworthy number; a failing scenario names the
exact failing op.

### Tier 2 — resilience + visibility
4. **Root-agnostic scenario assertions** (R2 defense-in-depth) — resolve the live root, build
   assertion paths dynamically. Runs *after* the health check, never instead of it.
5. **Expose `stage_latencies`** (planning / compilation / execution split) in run results + the hub
   UI, so "the model is slow" vs "the bridge is slow" vs "retries are thrashing" is visible at a
   glance.
6. **Unified results envelope aligned to `forge_score`** (R4) — common header on every run kind,
   sharing `normalize_result`'s shape.

**Tier 2 acceptance:** scenarios pass against a legitimately different root name; a timing
breakdown is visible per build; all run kinds emit one schema.

### Tier 3 — the data-driven layer (only if Tier 1–2 prove useful)
7. **`/api/runs` aggregation** feeding the **Testing-tab history** (R4) — last N runs across kinds,
   one route, one render path.
8. **`/api/runs/compare`** — time-series diff for the same model across config_hashes (generalize
   the existing `/api/scorecards/compare`).
9. **Stability score / failure signature** (R6) — hash the set of failing assertions; track
   passes÷attempts over recent runs; surface variance, not just a percentage.

### Deferred
- `editor_screenshot` **button** (R5) — cheap, do whenever; automated interpretation stays deferred.
- `logs_read` — wire reactively when a bridge-level post-mortem needs it.
- DevForge journal — only if artifacts get LRU-evicted before you read them.

---

## One thing to re-examine while implementing (avoid our blind spot)
We've assumed the remaining scenario failures (`node_delete`/`node_rename` editing ops, and the
"requested-named-node not built" cases) are fully explained by Bug 1/Bug 2. Once Tier 1.3 surfaces
per-op `execution.errors` on a clean probe, **re-read the actual failures** — they may reveal a
different story than our reconstruction. Let the data correct us.

## Prerequisite (human, ~30s)
Reload the Godot `probe.tscn` tab (restart Godot, or close the tab without saving) so the probe
root reads "Main" before the first verification run. Tier 1.1 will enforce this going forward.
