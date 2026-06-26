# Forge Interpretation Spine — Design

**Date:** 2026-06-21. **Status:** approved direction (brainstormed with user).
**Supersedes the framing of:** `ROADMAP-BUNDLES.md` (bundles now *ride* this spine; see end).

---

## 1. Why this exists (the drift, named)

Forge's goal, stated by the user: **a general tool that builds embodied 3D games at
the quality you'd get from building one bespoke game** — on the bet that aggressive
automation pays back the extra effort over time.

The drift we caught: we were building *the* blacksmith-fetch-quest RPG, welding one
game into the core. The asset layer (~37 composable generators) and room layer
(12 composable themes) are genuinely general. The **gameplay layer is not** —
`behaviour_gen` *is* "fetch quest," one mechanic hardwired in.

But the deeper risk the user named is not internal generality — it's the
**user-facing failure mode**: a future user doesn't know our prompt vocabulary, has
an idea that's perfect for the tool, and it *misses* because of word choice — silently.
A few of those → "AI slop" reputation → the tool dies regardless of how powerful it is.

## 2. The vision: three co-evolving pillars

1. **Capability** — a composable library of mechanics/assets/themes (internal generality).
2. **Interpretation** — map free-form user imagination onto the engine's vocabulary,
   so the user never learns a secret grammar.
3. **Legibility** — reflect back *what was understood, assumed, and couldn't be done*,
   so a miss is **visible and correctable**, never silent.

**Governing principle (the new definition-of-done):** every capability ships with its
interpretation *and* legibility from day one — the way nothing today is "done" until it
passes the Godot gate. The three pillars constrain each other; that intersection is
where robustness is forged.

**Scope boundary:** *embodied 3D games* — a first- or third-person avatar in generated
3D space. Includes RPGs/immersive-sims/survival/walking-sims/horror. Excludes 2D and
god-view strategy (different paradigm → separate project). RPG is the first, richest
*bundle of mechanics*, not the engine's definition.

## 3. The spine: a shared Brief + a build report

One structured **Brief** sits between the prompt and every generator. One **Interpreter**
produces it; every generator consumes it; a **Build Report** reflects it back.

```
TODAY:   prompt ─► RoomPlanner.plan(prompt) ─► room_control/layout ─► build   (re-parses raw text)

SPINE:   prompt ─► Interpreter ─► Brief ─► RoomPlanner.plan(brief) ─► room_control/layout ─► build
                       │            │                                                          │
                       └ assumptions┘                                                          │
                         + unmapped ───────────► Decision Points ◄────────────── clamps/drops ─┘
                                                       │
                                                 Build Report ─► user
                                       "understood / built / assumed / couldn't-do"
```

- **+1 stage in front, 1 consumer rewired, +1 view on the end.** Nothing else moves.
- Decision Points already thread the whole pipeline and already have a CLI renderer —
  so the report is largely a *new view over data we already produce*.
- The Brief is **internal**; the user always writes free text. Structuring the Brief does
  **not** recreate the secret-vocabulary trap — it moves that job to the Interpreter LLM,
  which is where it belongs.

## 4. This document specs SLICE 1 only — "the spine, proven on rooms"

Decomposed deliberately. Slice 1 proves the spine carries the *existing* room pipeline,
end-to-end, with a legible report. **No new game mechanics.** Quests ride the spine in
Slice 2; mechanics in later slices.

**Slice 1 in scope:** Brief schema v1 · Interpreter (prompt → Brief) · retrofit
`RoomPlanner` to consume the Brief · Build Report (Brief + Decision Points).

**Out of scope for Slice 1:** quests/dialogue/NPCs (still take the raw prompt — unchanged,
Slice 2), new mechanics, third-person camera, conversational refinement loop (Approach B),
capability-catalog UI (Approach C), exteriors.

---

## 5. Brief schema v1

A dict of **optional sections** so future slices add sections without breaking consumers.
Slice 1 defines only what rooms need plus the two legibility channels.

```jsonc
{
  "schema_version": 1,
  "source_prompt": "<raw user text, verbatim — provenance>",
  "setting":   "<short place label, e.g. \"a blacksmith's forge\">",
  "mood":      ["industrious", "smoky", "warm"],   // free-text atmosphere descriptors
  "scale":     "small | medium | large",            // enum → room-size band (intent, not metres)
  "theme_tag": "blacksmith",                         // ONE of the 12 known themes or "*" (closed set)
  "key_features": [                                  // notable things the user explicitly named
    {"text": "anvil",        "status": "mapped",   "category": "table"},   // mapped → will be placed
    {"text": "many tools",   "status": "mapped",   "category": "shelf"},
    {"text": "a lava river", "status": "unmapped", "category": null}       // can't honor → report it
  ],
  "unmapped": ["a lava river"]                       // top-level anti-slop channel (mirrors unmapped features)
}
```

**Vocabularies (closed, validated against real capability):**
- `theme_tag` ∈ the 12 `room_control.THEME_TABLE` themes (hermit, blacksmith, wizard,
  kitchen, noble, dungeon, attic, ship, crypt, armory, workshop, tavern) or `"*"`.
- `key_features[].category` ∈ `room_planner.CATEGORIES` (~37 placeable categories) or `null`.
- `scale` ∈ {small, medium, large} → size bands (small ≈ 4–6 m, medium ≈ 6–9, large ≈ 9–12).

**Validation rules (each deviation → a Decision Point, see §8):**
- `theme_tag` not in the known set → map to nearest / `"*"` + `brief.theme_unmapped`.
- `scale` missing/invalid → default `medium` + `brief.scale_defaulted`.
- `key_features[].text` that matches no category → `status:"unmapped"`, also appended to
  `unmapped` + `brief.feature_unmapped`.
- Empty `setting` → derive from `theme_tag` + `brief.setting_defaulted`.

**A tiny constructor for tests / back-compat:** `Brief.minimal(prompt)` builds a valid
Brief from a raw string (setting=prompt, theme_tag inferred or `"*"`, no key_features),
so existing room tests/callers can pass through without the LLM.

## 6. Interpreter (prompt → Brief)

New module `foundry/interpreter.py`, mirroring the planner pattern (injectable LLM,
single-line GBNF, deterministic post-validation → Decision Points):

```python
class Interpreter:
    def build_prompt(self, prompt: str) -> str: ...      # injects the closed vocabularies
    def parse(self, text: str) -> dict: ...               # raw_decode (ignore trailing prose) — see lessons
    def interpret(self, prompt, llm, seed=None) -> tuple[dict, list[DecisionPoint]]: ...
```

- The build_prompt **gives the LLM the engine's vocabulary**: the 12 theme tags and the
  list of placeable categories, and asks it to (a) pick a `theme_tag`, `scale`, `setting`,
  `mood`; (b) extract `key_features` the user named and tag each with the closest category
  or `null`. This is what makes interpretation *capability-aware*.
- **Parsing follows the hard lessons from 2026-06-21** (see `canned-npc-means-pipeline-bug`
  memory): use `JSONDecoder().raw_decode()` (never `json.loads(text[start:])`); if grammared,
  pass an explicit grammar string, never rely on `grammar=None` (that is FoundryLLM's *asset*
  default). Grammar: a single-line GBNF (`grammar/brief.gbnf`) constraining the closed fields;
  free-text fields (`mood`, `key_features[].text`) stay permissive; post-validate everything.
- On parse failure → return `Brief.minimal(prompt)` + `brief.parse_fallback` (graceful, never crash).

## 7. Room retrofit

`RoomPlanner.plan` changes its input from `request: str` to `brief: dict`:

- `build_prompt(brief)` formats the **normalized** intent (setting + theme_tag + scale band +
  the mapped key_features) into the room-planning prompt — a cleaner, more consistent signal
  than raw user prose.
- **Mapped `key_features` become required props**: a named "anvil" (→ category) is injected
  into the plan so the thing the user asked for actually appears. This is interpretation
  feeding the build, and it measurably raises "the user's named things showed up."
- All existing `room.*` clamps / Decision Points are unchanged.
- `__main__` wiring: `prompt → Interpreter.interpret → Brief → RoomPlanner.plan(brief)`.
  The quest path is untouched in Slice 1 (still takes the raw prompt).

## 8. Build Report (legibility)

New `foundry/report.py`: `render_build_report(brief, decisions, manifest) -> str` (+ a JSON
form). Four sections, written to stdout at command end **and** saved as
`builds/<scene>/build_report.{txt,json}` for the harness and a future UI:

- **Understood** — setting, mood, scale, theme_tag, mapped key_features.
- **Built** — room size, props placed (from manifest), which key_features made it in.
- **Assumed** — `severity in {assumption, ambiguous}` Decision Points (clamps, defaults,
  nearest-theme), each in plain register.
- **Couldn't do** — `unmapped` + `severity == error` Decision Points.

This is the anti-slop surface: the engine stating what it understood and what it couldn't,
so the user can see a miss instead of being surprised by it.

## 9. New Decision Point codes (register in `decisions._TEMPLATES`)

`brief.theme_unmapped` · `brief.scale_defaulted` · `brief.feature_unmapped` ·
`brief.setting_defaulted` · `brief.parse_fallback`. The AST meta-test added 2026-06-21
(`test_every_make_decision_code_is_registered`) will fail the build if any is forgotten.

## 10. Testing (eval-first; standing rules apply)

- **Interpreter unit tests (stub LLM, no llama):** valid prompt → valid Brief; unknown theme
  → nearest/`*` + DP; invalid scale → medium + DP; named-but-unsupported feature → unmapped
  + DP; malformed JSON / trailing prose → `Brief.minimal` + `brief.parse_fallback`.
- **Brief schema tests:** `Brief.minimal` round-trips; validation enforces closed vocabularies.
- **Room retrofit tests:** existing room tests adapted to Brief input; mapped key_feature →
  required prop appears in the plan.
- **Report tests:** all four sections render; an unmapped feature shows under "Couldn't do";
  an assumption DP shows under "Assumed".
- **Eval signal** (`foundry/eval/`): "Brief valid + key_feature mapped-status correct + report
  has four sections." 
- **Godot gate unchanged** — rooms still build; run `test_godot_smoke.py` explicitly.
- **Live run-twice** (qwen stochastic) for the generation change; ≥9B for a faithful read.
- Full suite + Godot smoke green, no exceptions. Never touch `addons/godot_ai`.

## 11. How this reframes the roadmap

The spine is **Slice 0** of everything. After Slice 1 proves it on rooms:

- **Slice 2:** quests ride the spine — `behaviour_gen` consumes a `Brief.npcs`/`Brief.quest`
  section; the parked **per-NPC grammared dialogue fallback** (agreed fix, 2026-06-21) lands
  here so quest dialogue is reliable *and* legible.
- **Every `ROADMAP-BUNDLES.md` bundle thereafter** (atmosphere, item verbs, Anvil Soul/needs/
  events, combat, multi-room, exteriors) becomes "add a Brief section + a generator that
  consumes it + its Decision Points + its report lines." A bundle is not done until its
  capability is interpretable and legible. The bundle *content* survives; the *definition of
  done* expands. ROADMAP-BUNDLES.md gets a preamble pointing here.
