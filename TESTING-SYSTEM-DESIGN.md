# Forge Testbench — Unified Testing System (Design)

**Date:** 2026-06-16
**Status:** Design for review. Implementation → the other AI; design + migration
review + sign-off → Claude.
**Supersedes:** the five separate runners (`bench.py` probes, `scenarios.py`,
`gauntlet.py`, `harness.py`, the `multi-model-bench` runner) and their five
incompatible result shapes.

---

## 0. Why this exists (the root cause, in one paragraph)

Every measurement effort has shipped a *different* bug — model-blind cache, the
harness never restarting llama, `spatial:assets` counting the wrong op, and most
recently diversity shown ×100 wrong, intent-coverage dropped, the gauntlet read
mid-run. **None were generation bugs. All were measurement-plumbing bugs**,
because we have five hand-rolled runners, each with its own ad-hoc scoring and
result shape. The fix is not more patches — it is **one coherent, extensible
chassis** that the existing test *content* plugs into. We keep the tests (they're
good); we replace the tape.

## North-star principle: self-describing data → reporting cannot lie

The recurring failure is the **reporting layer guessing** what a number means.
We make that structurally impossible: **every metric carries its own unit and
direction.** A `ratio` (0–1) and a `percent` (0–100) are *different units*; the
renderer formats each from its unit, so the ×100 bug *cannot happen*. Reporting
becomes a **pure function of stored results** — no live calls, no guessing, no
divergence between "what ran" and "what's shown."

---

## 1. The architecture (six pieces, one direction of data)

```
  TEST plug-ins  ──run()──►  raw observations
       │ score() (pure, co-located)
       ▼
  RESULT (one schema for everything: probe, scenario, capability, variety, …)
       │
  RUNNER (generic: models × tests × repeat-N, resilient, owns completion)
       │  persists ──►  ARTIFACT (a list of Results)
       ▼
  REPORTING (pure functions of the Artifact: matrix, scorecards, trends)
       ▲
  CATALOG + SUITES (registry of tests; suites = JSON lists of test ids)
       ▲
  UI (one Testing tab: reads the CATALOG for descriptions, the ARTIFACT for results)
```
Data flows one way: a test *observes* (`run`) → *scores itself* (`score`) → the
runner *collects + aggregates* → reporting *renders*. Nothing downstream
re-interprets; nothing upstream formats.

---

## 2. The uniform Result + self-describing Metric (the heart)

**Metric — every number is typed and self-describing:**
```jsonc
{
  "value": 0.71,
  "unit": "ratio",          // ratio(0–1) | percent(0–100) | count | ms | tok_s | bool | score
  "higher_is_better": true,
  "label": "repeat diversity"
}
```
The renderer formats from `unit` (a `ratio` prints `0.71` or `71%`, a `percent`
prints `71%`, a `count` prints `3`) and colours/stars from `higher_is_better`.
**The display is derived, never hand-passed** — this is the ×100/“broke is
better” bug-class, eliminated by construction.

**Result — one shape for probe, scenario, capability, variety, intent, latency:**
```jsonc
{
  "test_id": "cap.G7_integration", "category": "capability", "suite": "capability-v1",
  "model": "qwen3-5-9b", "ts": "...", "run_index": 1, "repeat_count": 10,
  "status": "ok",                 // ok | partial | broke | error  (uniform verdict)
  "score": 100,                   // canonical headline, ALWAYS 0–100 or null. One definition.
  "metrics": { "coverage": {Metric}, "diversity": {Metric}, "latency": {Metric}, ... },
  "raw": { "...": "test-specific observations (ops, nodes, assertions, probe data)" },
  "errors": [ ... ],
  "screenshot": "models/qwen3-5-9b/run-1/cap.G7.png"  // optional
}
```
Repeats aggregate into the *same* shape with `metrics.score` as `mean ± σ` and a
`diversity` metric — **aggregation lives in one place** (the runner), not in each
test.

---

## 3. The Test plug-in interface (adding a test = one small file)

A test is the atomic unit and owns *both* how it runs *and* how it scores —
**co-located scoring is what kills the central-aggregator bug.**
```python
class Test:
    id: str                 # "cap.G7_integration", "probe.llama_throughput", "var.repeat_kitchen"
    category: str           # probe | scenario | capability | variety | intent | ceiling
    title: str              # short UI label
    description: str        # the plain-language explainer (feeds the friendly Testing tab)
    suites: list[str]       # which suites include it
    # behaviour flags (the runner reads these — no per-test runner code):
    repeatable: bool = False
    needs_reset: bool = True
    skip_cache: bool = False
    screenshot: bool = False
    expect_break: bool = False

    async def run(self, ctx) -> dict:        # touches the live stack via ctx; returns RAW observations
        ...
    def score(self, raw) -> ScoredResult:    # PURE function raw → {status, score, metrics{}}; the ONLY scorer for this test
        ...
```
`ctx` is **injected** (the loaded model, `apply_spec`, godot-ai calls, scene
reset, screenshot) so tests never reach into globals — they're unit-testable in
isolation. `run` does *only* observation; `score` does *only* interpretation and
is a pure function (trivially unit-testable, which is how we stop scoring bugs
before they ship).

---

## 4. The Runner (one engine; single/multi-model/repeat are one code path)

```
run(test_ids, models[], repeat, opts) -> Artifact:
  for model in models:                      # 1 model = the trivial case; no special path
      swap(model)                           # the PROVEN transactional swap (pre-flight + llama restart + rollback)
      wait_healthy()
      for test in tests:
          if test.needs_reset: reset_scene()
          runs = []
          n = repeat if test.repeatable else 1
          for i in 1..n:
              raw   = await guard(test.run(ctx), timeout)   # resilient: catch+timeout, never abort the sweep
              runs.append(test.score(raw) | {raw, latency_ms})
          results.append(aggregate(test, runs))             # mean±σ, diversity — ONE aggregation
  persist(Artifact{results, manifest})                      # ONE artifact shape
  return Artifact
```
Properties that retire specific past bugs:
- **Owns completion** → never snapshots a job mid-run (kills the premature-read gauntlet bug).
- **Resilient** → a crash/timeout marks `status` and continues; `expect_break` inverts pass-logic (Act V stress tests don't abort the run).
- **One swap path** → the transactional swap with VRAM pre-flight (kills the never-restart-llama bug and protects the tight 27B).
- **`skip_cache` honoured per test** → variety/repeat tests run uncached (kills the model-blind-cache poisoning).

---

## 5. Catalog, Suites, Reporting

- **Catalog:** every Test self-registers. The UI reads it for `{id, category,
  title, description}` → the friendly, self-explaining picker (the descriptions I
  added to the Testing tab become a *property of the test*, not hard-coded HTML).
- **Suites = data, not code:** a suite is a JSON list of test ids
  (`chain-health`, `capability-v1`, `spatial-v1`, `variety-v1`, `everything`).
  Adding/curating a suite is editing JSON — no runner changes. (This is also
  where the noise-pruning lives: a suite is just which tests you include.)
- **Reporting = pure functions of the Artifact:** `matrix(artifact)`,
  `scorecards(artifact)`, `trend(artifacts)`, `stability(artifact)`. Because
  metrics are self-describing, every renderer formats correctly with zero
  test-specific knowledge. The model×score matrix, the scorecards, the latency
  strip, the diversity numbers — all one query each.

---

## 6. Migration map (keep the content, replace the plumbing)

Each existing thing becomes a plug-in; the runners are deleted.

| Today (scattered) | Becomes (plug-in category) |
|---|---|
| `bench.py` probes (throughput, ctx, bind, mcp…) | `probe.*` tests (score = verdict→0/100) |
| `scenarios.py` (cube/delete/rename + tool probes) | `scenario.*` tests (score = assertion pass-rate) |
| `gauntlet.py` sets (capability/spatial/building/…) | `cap.*` / `spatial.*` tests (score = coverage) |
| Move-1 diagnostics (repeat/intent/ceiling) | `variety.*` / `intent.*` / `ceiling.*` tests (typed diversity/intent metrics) |
| `harness.py` + `multi-model-bench` | **gone** — the Runner's `models[] × repeat` *is* this |

**Strategy — incremental, parity-checked (no big-bang):**
1. Build the chassis (Metric, Result, Test base, Runner, Catalog, Artifact, reporting).
2. Migrate **probes first** (simplest, no LLM) → run old vs new, confirm identical verdicts.
3. Migrate scenarios → gauntlet → diagnostics, one category at a time, parity-checking each.
4. Point the Testing tab at the new Artifact/Catalog.
5. **Delete** the old runners + result shapes once parity holds.
Each step ships green and reversible; nothing is thrown away blind.

---

## 7. The one Testing tab (UI)

The existing faceted tab stays, repointed at the new chassis:
- **Pick** suite *or* individual tests (the catalog gives titles + descriptions);
  **models** (up to 5, the existing picker); **repeat ×N**.
- **Run** → the Runner streams progress → on completion, reporting renders from
  the Artifact: the **model × score matrix** (already built), per-model
  scorecards, the latency strip, variety/intent numbers — all correctly formatted
  because the metrics are typed.
- History / stability / screenshots are queries over stored Artifacts.

---

## 8. Extensibility (the explicit goal — how you add things)

- **A new test:** one plug-in file (`run` + `score`), register it → it appears in
  the catalog and any suite that lists it. No runner/UI/reporting changes.
- **A new metric kind:** add a `unit` to the Metric vocabulary + its formatter
  once; every test and view gets it.
- **A new suite:** edit a JSON list of test ids.
- **A new model:** it's already in `forge_models.scan()` → appears in the picker.
- **A new run mode** (e.g. A/B temperature): it's `opts` on the Runner, not a new
  runner.

## 9. What dies (the cleanup you asked for)
`harness.py`, the `multi-model-bench` runner, the bespoke result shapes in
`gauntlet.py`/`bench.py`/`scenarios.py`, the scattered score-extraction in the
hub endpoints, `comparison.json`/`manifest.json`/scorecard/gauntlet-json as
*separate* formats → one Artifact. Dead/redundant tests get dropped at the *suite*
level (data), and the data-driven noise pruning (Phase 2.5) finally has a home.

## 10. Non-goals & boundaries
- **Not** touching the generation pipeline (DevForge + engines) — this is the
  *measurement* layer only. Greybox stays. DevForge-only; Odysseus + godot-ai
  vanilla.
- **Not** a big-bang rewrite — incremental migration with parity checks (§6).
- Test *content* is preserved; only the plumbing is rebuilt.

## 11. Division of labor & sequencing
- **Claude:** this design; the Metric/Result/Test/Artifact schemas; the migration
  parity checks; review/sign-off; the data-driven suite pruning.
- **Other AI:** build the chassis + migrate the plug-ins + repoint the UI + delete
  the old runners, one category at a time (§6).
- **Sequence:** chassis → probes (parity) → scenarios → gauntlet → diagnostics →
  UI repoint → delete old → re-run the multi-model bench on the new rig and
  confirm it finally tells the truth (the 9b-best / 27b-zero-variety story, with
  correct numbers).
