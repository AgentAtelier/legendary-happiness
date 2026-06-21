# Spine · Slice 3 — G1 Layered Soul (through the spine) — Delegation Prompts

> **For the CLI AI:** implement task-by-task, TDD red→green, one commit per task.
> Context: `ANVIL-PORT-ASSESSMENT.md` §G1 (the design), `SPINE-DESIGN.md` (the three
> pillars), `SPINE-SLICE2-PROMPTS.md` (the `Brief.characters` pattern this extends).
> This is the **first Anvil port** and the first *new capability* to ride the spine — so it
> ships with its **interpretation** (soul inferred from the prompt) and **legibility** (soul
> shown in the build report) from day one. Honour `python-builds-godot-lives`: Python decides
> the soul at build time; Godot reads it.

**Goal:** every NPC gets a **Soul** — a Substrate (3 stable traits) + 4 emotional axes — the
Interpreter infers from the prompt, stored in `Brief.characters[].soul`, baked into
`quest_data`, used to bias **dialogue tone**, and surfaced plainly in the build report. This
turns interchangeable NPCs into *characters* (the exact "canned villager" gap).

**Architecture:** new `soul.py` (shape + validation + deterministic `tone_descriptor`); the
Interpreter assigns a soul per character; `behaviour_gen` injects the tone into dialogue
prompts and stores the soul on each spec; `scene_compiler` writes it into `quest_data`;
`npc.gd` reads it (for future runtime use + idle-tone); the report explains it.

**Tech Stack:** Python 3.14, pytest, injectable LLM, Decision Points, Godot 4.7 gate.

## Global Constraints (verbatim — same as Slices 1–2)

- **Testing split (standing rule):** the **CLI AI** runs the *fast* gates per task — the unit suite
  (`pytest tests/ -q`) and the Godot smoke gate (`pytest tests/test_godot_smoke.py -q`) — both green
  before each commit, then hands off. The **ORCHESTRATOR** (not the CLI AI) owns all *time-intensive*
  verification: live ≥9B generation, run-twice, and the multi-model comparison. CLI-AI tasks below are
  marked **[CLI]**; orchestrator verification is marked **[ORCH]** — do NOT run the [ORCH] steps.
- Standing rules (`EASY-BATCH-PROMPTS.md` header). Dedicated branch/worktree. TDD red→green.
  Run **both** `pytest tests/ -q` **and** `pytest tests/test_godot_smoke.py -q` green. Commit per task.
- **LLM lessons (`canned-npc-means-pipeline-bug`):** free-form call → `llm(prompt, "")` never `None`;
  parse with `JSONDecoder().raw_decode(...)` never `json.loads(text[start:])`.
- Every `make_decision(code=...)` MUST be registered in `decisions._TEMPLATES`
  (`test_every_make_decision_code_is_registered` enforces it).
- **`python-builds-godot-lives`:** the soul is decided in Python at build time and baked into
  `quest_data`; Godot reads it. NO runtime soul *mutation* this slice (events nudge axes later, B8) —
  axes are stored as initial state only.
- Eval-first; qwen stochastic → verify live twice (≥9B). Never touch `addons/godot_ai`.

## Data model (use exactly these)

```jsonc
// Soul (per NPC). All values are floats in [-1.0, 1.0].
{
  "substrate": { "courage": 0.0, "generosity": 0.0, "stability": 0.0 },
  "axes":      { "security": 0.0, "belonging": 0.0, "agency": 0.0, "satiation": 0.0 }
}
```
- **Substrate** (stable traits): courage(↔fear), generosity(↔selfishness), stability(↔anxiety).
- **Axes** (emotional state, for future event-nudging): security, belonging, agency, satiation.
- `Brief.characters[i]` gains a `"soul"` key. NPC *i* uses `characters[i].soul` (matches the Slice-2
  role-by-index rule); NPCs with no named character get `default_soul()`.

---

## Task 1 — `soul.py`: shape + validation + tone

**Files:** Create `foundry/soul.py`, `foundry/tests/test_soul.py`; Modify `foundry/decisions.py`.

**Produces:**
- `SUBSTRATE_TRAITS = ("courage","generosity","stability")`, `AXES = ("security","belonging","agency","satiation")`.
- `default_soul() -> dict` — all values 0.0, full shape above.
- `validate_soul(raw: dict) -> tuple[dict, list[DecisionPoint]]` — coerce to floats; **clamp** each to
  [-1,1] (→ `soul.clamped`, ctx: `field`, `raw`, `clamped`); **default** missing/non-numeric to 0.0
  (→ `soul.defaulted`, ctx: `field`). Always returns the full shape.
- `tone_descriptor(soul: dict) -> str` — DETERMINISTIC adjective phrase from the substrate, used by
  both the dialogue prompt and the report. Thresholds (±0.33):
  - courage: ≤ -0.33 → "timid"; ≥ 0.33 → "bold".
  - generosity: ≤ -0.33 → "guarded"; ≥ 0.33 → "warm".
  - stability: ≤ -0.33 → "anxious"; ≥ 0.33 → "steady".
  - Join present adjectives with ", "; if none cross the threshold → "even-tempered".

**Register 2 DP templates** in `decisions.py`: `soul.clamped`, `soul.defaulted`.

**Steps (TDD):**
- [ ] Test: `default_soul()` has all 7 keys at 0.0; `tone_descriptor(default_soul()) == "even-tempered"`.
- [ ] Test: `validate_soul({"substrate":{"courage":-0.8,"generosity":2.0}})` → courage kept, generosity
  **clamped to 1.0** + `soul.clamped`, stability **defaulted to 0.0** + `soul.defaulted`; axes all 0.0.
- [ ] Test: `tone_descriptor({"substrate":{"courage":-0.5,"generosity":0.6,"stability":0.0},"axes":{...}})`
  → `"timid, warm"`.
- [ ] Register `soul.clamped`/`soul.defaulted`; meta-test green.
- [ ] Run `pytest tests/ -q`. Commit: `feat(foundry): soul.py — Substrate+axes shape, validation, tone (spine slice 3)`.

## Task 2 — Interpreter assigns a soul per character

**Files:** Modify `foundry/interpreter.py`, `foundry/brief.py`; `foundry/tests/test_interpreter.py`, `tests/test_brief.py`.

**Interpreter prompt:** extend the `characters` instruction to also ask for a `soul.substrate`
inferred from the **personality cues in the prompt** — "a *wary* blacksmith" → low courage; "a
*generous* hermit" → high generosity; "a *nervous* apprentice" → low stability. Give the model the
trait names and the −1..1 range; if the prompt implies nothing, return zeros. (Optionally a few
`axes`; default 0.0.) Parsed via the same `raw_decode`.

**Brief validation:** in `validate_brief`, for each kept character run
`soul.validate_soul(ch.get("soul", {}))` and store the result on `character["soul"]` (always present,
defaulted if absent). `brief.minimal()` gives each character (there are none) nothing to do, but a
character with no soul must end up with `default_soul()`.

**Steps (TDD, stub LLM):**
- [ ] Test (`test_brief`): `validate_brief` with a character lacking `soul` → that character gets
  `default_soul()` (all 0.0, full shape).
- [ ] Test (`test_brief`): a character with `soul.substrate.courage = -0.9` → preserved (within range).
- [ ] Test (`test_interpreter`): stub returns a character with `soul.substrate.generosity = 0.7` →
  survives into `brief["characters"][0]["soul"]`.
- [ ] Run `pytest tests/ -q`. Commit: `feat(foundry): Interpreter assigns soul per character (spine slice 3)`.

## Task 3 — `behaviour_gen` uses tone + stores soul on each spec

**Files:** Modify `foundry/behaviour_gen.py`; `foundry/tests/test_behaviour_gen.py`.

**Changes in `plan_multi`:**
- For NPC *i*, resolve `soul = brief_characters[i]["soul"]` if present else `soul.default_soul()`.
  **Store `spec["soul"] = soul`** on every produced spec.
- Build a per-NPC **tone hint** from `soul.tone_descriptor(soul)` and inject it into the dialogue
  prompt. Extend the existing character-hint block (around the `brief_characters` hint, ~line 610):
  e.g. `"npc_0 is a timid, warm blacksmith; npc_1 is a bold apprentice. Write each NPC's lines in
  that tone."`
- In the **per-NPC grammared fallback** (Slice 2, the `plan()` retry), prepend the tone to the
  `room_theme` string passed to `plan()` (e.g. `f"{tone} — {room_theme}"`) so the fallback dialogue
  also reflects the soul. Still store `spec["soul"]`.

**Steps (TDD, stub LLMs):**
- [ ] Test: a Brief with `characters[0].soul.substrate.courage = -0.6` → the prompt passed to the stub
  LLM contains `"timid"` (assert via a capturing stub).
- [ ] Test: every spec returned by `plan_multi` has a `"soul"` key with the full shape (incl. NPCs
  with no named character → `default_soul()`).
- [ ] Test: two characters with opposite courage (-0.8 vs +0.8) → their tone hints in the prompt differ
  ("timid" vs "bold").
- [ ] Run `pytest tests/ -q`. Commit: `feat(foundry): dialogue tone + soul on specs from Brief souls (spine slice 3)`.

## Task 4 — bake soul into `quest_data`, read in `npc.gd`, surface in report

**Files:** Modify `foundry/scene_compiler.py`, `foundry/report.py`,
`foundry/godot_template/scripts/npc.gd`; `foundry/tests/test_report.py` + a smoke assertion.

**scene_compiler:** in the `npcs_data[npc_id] = {...}` block (~line 683), add
`"soul": spec.get("soul", {})` so each NPC's soul is written to `*_quest_data.json`.

**npc.gd:** in `_load_quest_data`, read `var _soul: Dictionary = _quest_data.get("soul", {})` (no crash
when absent). Minimal runtime use this slice: if `_soul.substrate.courage <= -0.33`, lengthen the idle
look-at distance / pick the lower-energy idle bark variant — a *small* visible nuance. (Keep it a
1-line behavioural tweak; the dialogue tone is already baked. No soul mutation.)

**report.py:** in `build_report_dict`, the **understood** section's character list shows each
character with its tone: `f"{tone_descriptor(ch['soul'])} {ch['role']}"` → e.g. "a timid, warm
blacksmith". (Import `soul.tone_descriptor`.)

**Steps (TDD + gate):**
- [ ] Test (`test_report`): a Brief character with a timid/warm soul → "understood" contains
  `"timid, warm <role>"`.
- [ ] Generate a build (or extend a smoke fixture) and assert `*_quest_data.json` NPCs carry a `soul`
  object; headless-load clean (`npc.gd` reads soul without error).
- [ ] Run `pytest tests/ -q` AND `pytest tests/test_godot_smoke.py -q` — both green.
- [ ] Commit: `feat(foundry): bake soul into quest_data + npc.gd reads it + report shows tone (spine slice 3)`.

## Task 5 [CLI] — eval signals (unit only)

**Files:** Modify `foundry/eval/signals.py`, `foundry/tests/test_eval_signals.py`.

**Eval add:** `check_every_npc_has_valid_soul(record)` — positive when every NPC spec has a `soul` with
all 7 values in [-1,1]. Plus `check_soul_tones_vary(record)` — positive when ≥2 NPCs exist and their
`tone_descriptor` strings are not all identical (souls actually differentiate characters).

**Steps (TDD — fast gates only, then hand off):**
- [ ] Test: a record with two NPCs whose souls give different tones → both signals positive; a record
  where every NPC has `default_soul()` → `check_soul_tones_vary` negative (all "even-tempered").
- [ ] Run `pytest tests/ -q` AND `pytest tests/test_godot_smoke.py -q` — both green.
- [ ] Commit: `feat(foundry): soul eval signals (spine slice 3)`. **Then hand off to the orchestrator** —
  do NOT run live generation.

---

## [ORCH] Live verification — orchestrator only (do NOT run as the CLI AI)

The orchestrator runs the time-intensive checks after the CLI AI hands off green:
- **Live (≥9B):** `python -m foundry quest --request "a fearful hermit and a proud, generous blacksmith
  share a workshop" --scene chk_soul --npc-count 2` → `build_report.txt` "understood" shows two
  *distinct* souled characters (e.g. "a timid hermit", "a bold, warm blacksmith"); the two NPCs' greet
  lines read in **different tones**; `quest_data` NPCs carry souls; headless-load clean. **Run twice**
  (stochastic) — both produce distinct, valid souls + clean build.
- **4-model comparison:** `quest_compare --full-pipeline --run-playthrough --npc-count 2` (9b/14b/27b)
  on the personality-rich prompt — every model's two NPCs should read as **distinct characters** (tone
  varies with substrate), each `build_report.txt` describing the souls in plain words.

This is the first proof that a *new capability* (Anvil G1) ships with its interpretation + legibility
through the spine. Next candidates: G2 needs/utility (the living-NPC loop, where the axes start getting
used) or a lighter bundle (item verbs / atmosphere) through the spine.
