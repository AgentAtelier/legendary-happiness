# Stage 4 — Rebalance: Giving the LLM Its Voice Back

**Date:** 2026-06-16
**Status:** Plan (approved in principle). Diagnostics + analysis = Claude;
implementation = the other AI.
**Origin:** the multi-model harness (Phase 2.5) showed a 4B model scoring
identically to a 27B — because our generators became hardcoded recipes and the
LLM was reduced to a label-picker. Four independent outside AI reviews
*unanimously* confirmed the diagnosis and the fix (see `OtherAI.md`).

---

## 0. The reframe (the whole point)

"Determinism vs. variety" is a **false fight** — they live on different layers:

- **The LLM writes the creative *brief*** — function, mood, style, clutter,
  relationships, special features, "make these three *different*." **Variety
  lives here.**
- **The engine *builds* the brief** — valid geometry, no clipping, reproducible.
  **Reliability lives here.**

We drifted because the engine swallowed the brief-writing (the "creative
middle"), shrinking the LLM to a label + two numbers. **The deterministic core is
an asset, not a mistake — we keep all of it.** We move the line: give the brief
back to the LLM, and teach the engine to *resolve a rich brief* instead of
running one fixed recipe. The 4B≈27B result is not efficiency — it is
**capability suppression** (all four reviews agreed): the task we hand the model
requires no reasoning, so a tiny model saturates it.

**The contract this stage establishes:** the LLM emits a structured **Intent
Descriptor**; the engine is a **parameterized generator** that honors every field
of it (validity guaranteed, variation from the descriptor + a seed). When that
holds, variety returns, model size starts to matter again, and reliability is
untouched.

---

## Division of labor (unchanged)
| Move | PLAN/ANALYZE (Claude) | IMPLEMENT (other AI) |
|---|---|---|
| 1 Diagnostic | design + interpret the baseline | (human runs the prompts) |
| 2 Interface | spec the Intent Descriptor schema | build planner + GBNF + engine intake |
| 3 Generators | spec the resolution behavior | parameterized generator + seeded RNG |
| 4 Variety metrics | define the metrics + scorecard | build the checks + dashboard |
| 5 Re-benchmark | analyze the sweep | (human runs the sweep) |

**Firm rules carried forward:** DevForge-only (Odysseus + godot-ai vanilla);
the human runs gauntlets/sweeps; the other AI keeps the full unit suite green;
**greybox variety is enough — no art pipeline** (variation comes from
dimensions/colors/counts/placement, not 50 meshes).

---

## Move 1 — Prove the bottleneck FIRST (diagnostic)  ★ do before any rebuild

We do not rebuild on a hunch. We measure the disease, get a baseline, and have a
number to beat. **Claude designs + interprets; the human runs the `apply_spec`
prompts and pastes the built scenes.**

Three measurements on the *current* room pipeline:
1. **Repeat-diversity** — `apply_spec "build a kitchen"` ×10. Measure how many of
   the 10 outputs are *distinct* (node set + asset multiset + positions).
   *Hypothesis:* ~1 distinct / 10 (your "3 identical houses", confirmed).
2. **Intent-sensitivity** — run four prompts that *should* diverge: "a **cramped**
   kitchen", "a **spacious** kitchen", "an **abandoned** kitchen", "a **luxurious**
   kitchen". Measure pairwise output difference. *Hypothesis:* ~0 — the adjective
   is ignored; all four produce the same kitchen. This is the **intent-coverage**
   smoking gun.
3. **Model ceiling** — one hard relational prompt ("a wizard's tower where the
   wizard grew afraid of heights — upper floors sealed and dusty, living area
   migrated down") on 4B vs 27B. *Hypothesis:* both collapse to a generic room —
   proving the *interface*, not the model, is the ceiling.

**Also fold in here (cheap, unblocks all future measurement):** fix the
**model-blind plan cache** from Phase 2.5 — add `model_alias` to the cache key
(or a `no_cache` flag the harness/diagnostics set). Without this, no sweep or
repeat-diversity test is valid (the cache replays one plan).

**Deliverable:** a one-page baseline (Claude) — the three numbers — that the
rebuild must move. If, surprisingly, intent-sensitivity is already high, we stop
and rethink. (It won't be.)

---

## Move 2 — Richen the interface: the Intent Descriptor (rooms slice)

Replace the SSP archetype *label* with a structured brief the LLM authors and the
engine resolves. **Other AI implements; schema specced here.**

**The Intent Descriptor (rooms v1) — GBNF-constrained, bounded but rich:**
```json
{
  "room_type": "kitchen",                  // base function (required slots)
  "size": "cramped|normal|spacious",       // → dimensions
  "style": "rustic|industrial|noble|derelict", // → asset pool + palette
  "clutter": 0.0,                          // 0..1 → number + placement of props
  "mood_tags": ["abandoned", "cozy"],      // → greybox modifiers (color/intact/scatter)
  "must_have": ["stove", "poison_cabinet"],// LLM-chosen required assets (lexicon)
  "special_features": ["secret_passage"],  // engine handles known, degrades unknown
  "seed": 12345                            // engine variation (LLM may set or omit)
}
```
Design constraints (the reliability guarantee):
- **Enumerated where it must validate** (`size`, `style`) so the GBNF stays
  finite; **free-but-grounded where it must vary** (`must_have` drawn from the
  lexicon; `mood_tags`/`special_features` open but degrade gracefully).
- **Every field must be honored by Move 3** — a field the engine ignores is dead
  intent (Move 4's intent-coverage metric will catch any that are).
- **Graceful fallback** (rule 4): unknown style/mood/feature → nearest match or
  skip + log, never crash.
- New planner `RoomIntentPlanner` (+ `room_intent.gbnf`), routed via the existing
  per-request planner param (`planner="room"`), reusing the validator/executor.

**Acceptance:** the LLM emits valid descriptors; "a cramped abandoned kitchen"
and "a spacious noble kitchen" produce *structurally different* descriptors.

---

## Move 3 — Recipes → parameterized generators + entropy (rooms slice)

The room engine stops being "kitchen = stove+fridge+counter+table" and becomes a
resolver of the descriptor. **Other AI implements; behavior specced here.**

Resolution map (each descriptor field → engine action):
- `room_type` → base required asset categories (a kitchen needs a cooking surface).
- `size` → room dimensions (cramped ≈3×3, normal ≈5×4, spacious ≈8×6).
- `style` → which **asset pool**/variant + color palette (rustic = warm browns,
  industrial = greys, derelict = desaturated).
- `clutter` (0..1) → **number** of non-essential props + placement bias
  (low = essentials only; high = many, biased to walls/corners).
- `mood_tags` → greybox modifiers: `abandoned` → darker/desaturated, fewer intact
  props, scattered; `cozy` → warmer, denser, centered.
- `must_have` → guarantee those assets present (override pool defaults).
- `special_features` → known handled (e.g. `secret_passage` → a concealed node);
  unknown → log + skip.
- `seed` → a **seeded RNG** threaded through selection + placement + greybox
  jitter (dimensions/color/rotation).

Two sources of variety, both deterministic-given-inputs:
- **Across descriptors** (the LLM's job): different briefs → different rooms.
- **Across seeds** (the engine's job): same brief, seed `[1,2,3]` → three
  *different* valid rooms. **This is what makes "build 3 houses" yield 3
  different houses** — the planner emits 3 descriptors and/or 3 seeds.

Lexicon: expand to *parameterized greybox* — multiple size/color/count variants
per category and `style` tags, **no new meshes required** (jitter + palette +
count give the variety cheaply).

**Acceptance:** same prompt ×10 → mostly distinct outputs; each descriptor field
visibly changes the build; "3 kitchens" are three different kitchens.

---

## Move 4 — Build the variety dashboard (the missing instrument)

Correctness was our only metric, so creativity starved (Goodhart's Law — every
review named it). Add the metrics that see meaning. **Claude defines; other AI
builds as new `gauntlet.py` check types + a hub view.**

- `variety:repeat_diversity` — N runs of one prompt → distinct-output ratio
  (node/asset/layout distance). Target: high.
- `variety:intent_coverage` — vary **one descriptor field at a time** → % of
  fields that measurably change the output. **The killer metric** (your "identical
  houses" made automatic). Target: ~100% (every field matters).
- `variety:descriptor_entropy` — distinct descriptors the LLM emits over N runs
  (measures the LLM's expressiveness, not the engine's).
- `fidelity:llm_judge` — a judge model (the 27B locally, or Claude) rates 1–5
  "does the built scene match the intent?" with a short justification.
- **Rebalanced scorecard:** correctness 40 / diversity 40 / fidelity 20 (a
  starting weighting; tune later). Correctness stays a *gate* (must be valid), but
  no longer the *target*.

**Acceptance:** the hub shows variety + fidelity beside correctness; we can watch
all three move as Move 2/3 land.

---

## Move 5 — Re-benchmark the 4 models (the payoff test)

With the rooms slice rebuilt, the cache fixed (Move 1), and the new metrics
(Move 4), re-run the 4-model sweep on the **hard relational prompts** — now
scoring diversity + fidelity, not just correctness. **Claude analyzes; human
runs.**

The question this finally answers honestly: **does the 27B now earn its keep?**
A healthy result: the 27B produces richer, more coherent descriptors → higher
variety + fidelity than the 4B, *without* losing correctness. If it still
doesn't, the interface is still too thin and we iterate the schema (Move 2). If
it does, we have our model recommendation and proof the rebalance worked.

**Deliverable:** `HARNESS-ANALYSIS` (the real one this time) + the model call.

---

## Sequencing
1. **Move 1** diagnostic + cache fix → baseline numbers (the disease, measured).
2. **Move 2 + Move 3** together → the rooms vertical slice (interface + generator).
3. **Move 4** variety metrics → make the improvement visible.
4. **Move 5** re-benchmark → prove the model matters again.
5. **(Future)** roll the descriptor+generator pattern to buildings, scatter,
   dungeons; explore Quality-Diversity / MAP-Elites and "LLM writes the WFC
   *rules*" (all flagged by the reviews) — only once rooms proves the pattern.

## What we explicitly are NOT doing now
Tearing down the deterministic engines (they're the asset); an art pipeline
(greybox variety suffices); all engines at once (rooms first); full QD/evolutionary
search (future). Reliability stays a hard gate throughout — we are adding a
voice, not removing the guardrails.
