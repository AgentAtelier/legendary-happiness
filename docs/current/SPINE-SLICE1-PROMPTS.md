# Spine · Slice 1 (rooms) — Implementation Plan / Delegation Prompts

> **For the CLI AI:** implement task-by-task, TDD red→green, one commit per task.
> Spec: `SPINE-DESIGN.md` (read §5–§10 first). Direction context: the three pillars
> (Capability + Interpretation + Legibility). This slice proves the spine on the **room**
> pipeline only — quests are untouched (Slice 2).

**Goal:** insert a shared `Brief` between the prompt and the room generator, and emit a
user-facing build report — proving "+1 stage, 1 consumer rewired, +1 view."

**Architecture:** new `interpreter.py` turns the free prompt into a validated structured
`Brief` (closed vocabularies, capability-aware); `room_planner.py` consumes the Brief instead
of the raw string; new `report.py` renders Brief + Decision Points as understood/built/
assumed/couldn't-do. Quests still take the raw prompt this slice.

**Tech Stack:** Python 3.14, pytest, injectable LLM (`FoundryLLM`), Decision Points, Godot 4.7 gate.

## Global Constraints (verbatim, apply to every task)

- **Standing rules:** see `EASY-BATCH-PROMPTS.md` header. Dedicated branch/worktree. TDD red→green.
  Run **both** `cd foundry && .venv/bin/python -m pytest tests/ -q` **and**
  `... tests/test_godot_smoke.py -q`; both green, no exceptions. Commit per task with proof.
- **Two hard-won LLM lessons (memory: `canned-npc-means-pipeline-bug`) — DO NOT REPEAT:**
  1. Never call `llm(prompt, None)` for free-form output — `None` makes `FoundryLLM` apply its
     **default asset grammar**. Pass `""` for no grammar.
  2. Never parse with `json.loads(text[start:])` — use `json.JSONDecoder().raw_decode(text[start:])`
     so trailing prose / unclosed `<think>` blocks don't blow up the parse.
- **DP discipline:** every `make_decision(code=...)` code MUST be registered in
  `decisions._TEMPLATES`. The meta-test `test_every_make_decision_code_is_registered` enforces it.
- **Eval-first:** generation changes add/extend a `foundry/eval/` signal. Single-line GBNF only if
  used. Never mutate real `asset_lexicon.json` in tests. qwen is stochastic → verify live claims twice.
- Never touch `addons/godot_ai`.

## Closed vocabularies (use these exact values)

- **THEMES** (from `room_control.THEME_TABLE`): `hermit, blacksmith, wizard, kitchen, noble,
  dungeon, attic, ship, crypt, armory, workshop, tavern` + `"*"` fallback.
  Import live: `[r["theme"] for r in room_control.THEME_TABLE]` — do NOT hardcode a copy.
- **CATEGORIES** (placeable, ~37): import `from room_planner import CATEGORIES`.
- **SCALE** → size band: `small`→(4,6), `medium`→(6,9), `large`→(9,12).

## File structure

| File | Responsibility |
|---|---|
| `foundry/brief.py` (new) | `Brief` schema v1: closed-vocab constants, `Brief.minimal(prompt)`, `validate_brief(raw, themes, categories) -> (brief, decisions)`. |
| `foundry/interpreter.py` (new) | `Interpreter`: `build_prompt`, `parse` (raw_decode), `interpret(prompt, llm, seed) -> (brief, decisions)`. |
| `foundry/report.py` (new) | `render_build_report(brief, decisions, manifest) -> str` + `build_report_dict(...) -> dict`. |
| `foundry/room_planner.py` (modify) | `plan(brief, llm, seed)` consumes Brief; `build_prompt(brief)`; inject mapped key_features as required props. |
| `foundry/__main__.py` (modify) | wire `prompt → interpret → Brief → RoomPlanner.plan(brief)`; write report files. |
| `foundry/decisions.py` (modify) | register 5 `brief.*` templates. |
| `foundry/eval/signals.py` (modify) | add `brief_valid` / report-completeness signal. |

---

## Task 1 — `brief.py`: schema v1 + validation + DP templates

**Files:** Create `foundry/brief.py`, `foundry/tests/test_brief.py`; Modify `foundry/decisions.py`.

**Produces:**
- `Brief.minimal(prompt: str) -> dict` — valid Brief from raw text (setting=prompt, theme_tag inferred
  by substring match against THEMES else `"*"`, scale=`"medium"`, mood=[], key_features=[], unmapped=[],
  schema_version=1, source_prompt=prompt).
- `validate_brief(raw: dict, themes: tuple[str,...], categories: tuple[str,...]) -> tuple[dict, list[DecisionPoint]]`
  — normalizes/validates a raw dict into a clean Brief, emitting Decision Points.

**Brief shape (dict):** `schema_version:int=1, source_prompt:str, setting:str, mood:list[str],
scale:"small|medium|large", theme_tag:str, key_features:list[{text:str,status:"mapped|unmapped",
category:str|None}], unmapped:list[str]`.

**Validation rules → Decision Points (register all 5 in `decisions._TEMPLATES`):**
- `theme_tag` not in `themes` → set to `"*"` + `brief.theme_unmapped` (ctx: `requested`, `resolved`).
- `scale` not in {small,medium,large} → `"medium"` + `brief.scale_defaulted` (ctx: `requested`).
- each `key_features[].category` not in `categories` → `status="unmapped"`, `category=None`, append
  `text` to `unmapped`, + `brief.feature_unmapped` (ctx: `text`).
- empty/missing `setting` → derive `f"a {theme_tag} room"` + `brief.setting_defaulted` (ctx: `resolved`).
- `brief.parse_fallback` (ctx: `error`) — registered here, used by Task 2.

**Steps (TDD):**
- [ ] Test: `Brief.minimal("a blacksmith's forge")` → `theme_tag=="blacksmith"`, `scale=="medium"`,
  `schema_version==1`, `source_prompt` preserved. (RED → impl → GREEN)
- [ ] Test: `validate_brief({"theme_tag":"lava_cave",...}, THEMES, CATEGORIES)` → `theme_tag=="*"` and a
  `brief.theme_unmapped` decision present.
- [ ] Test: invalid scale → `"medium"` + `brief.scale_defaulted`.
- [ ] Test: key_feature `{"text":"lava river","category":"lava"}` → `status=="unmapped"`, `category is None`,
  `"lava river" in brief["unmapped"]`, `brief.feature_unmapped` present.
- [ ] Test: key_feature `{"text":"anvil","category":"table"}` → `status=="mapped"`, kept.
- [ ] Register the 5 templates in `decisions.py`; run `test_decisions.py` (meta-test stays green).
- [ ] Run full `pytest tests/ -q`. Commit: `feat(foundry): Brief schema v1 + validation (spine slice 1)`.

## Task 2 — `interpreter.py`: prompt → Brief

**Files:** Create `foundry/interpreter.py`, `foundry/tests/test_interpreter.py`.

**Consumes:** `brief.validate_brief`, `brief.Brief.minimal` (Task 1).
**Produces:** `Interpreter.interpret(prompt: str, llm: Callable[[str,Optional[str]],str], seed=None)
-> tuple[dict, list[DecisionPoint]]`.

**Behaviour:**
- `build_prompt(prompt)` injects the vocabularies: lists the 12 THEMES and asks the LLM to choose one;
  asks for `scale` ∈ {small,medium,large}; `setting`; `mood` (2–4 words); and to extract `key_features`
  the user named, each tagged with the closest CATEGORY or null. Output ONLY JSON.
- `parse(text)` — strip ```` ``` ```` fences and `<think>…</think>`; then
  `json.JSONDecoder().raw_decode(text[text.find("{"):])` (NOT `json.loads`).
- `interpret` calls `llm(self.build_prompt(prompt), "")` (empty string — NO grammar), parses, then
  `validate_brief(raw, THEMES, CATEGORIES)`; sets `source_prompt=prompt`. On any parse error →
  `Brief.minimal(prompt)` + a `brief.parse_fallback` decision. Never raises.

**Steps (TDD, stub LLM — no llama):**
- [ ] Test: stub returns valid JSON with `theme_tag:"blacksmith"` → interpret yields that theme,
  `source_prompt` set, 0 error decisions.
- [ ] Test: stub returns good JSON + trailing `<think>unclosed prose` → parses fine (raw_decode proof).
- [ ] Test: stub returns `"not json"` → `Brief.minimal` returned + `brief.parse_fallback` decision; no raise.
- [ ] Test: `interpret` passes `""` (not `None`) as grammar — assert via a capturing stub
  (`seen["grammar"]==""`). (Mirrors `test_plan_multi_calls_llm_with_no_grammar_not_none`.)
- [ ] Run full `pytest tests/ -q`. Commit: `feat(foundry): Interpreter prompt->Brief (spine slice 1)`.

## Task 3 — retrofit `RoomPlanner` to consume the Brief

**Files:** Modify `foundry/room_planner.py`; Modify `foundry/tests/test_room_planner.py`.

**Consumes:** Brief dict (Task 1).
**Produces:** `RoomPlanner.plan(brief: dict, llm, seed=None) -> tuple[dict, list[DecisionPoint]]`
(same `{room_size, props}` output as today).

**Changes:**
- `build_prompt(self, brief: dict) -> str` — format normalized intent: `setting`, `theme_tag`, the
  `scale` band (metres), and the **mapped** key_features. Keep the existing room-plan output contract.
- After producing `props`, **inject each mapped key_feature** (`status=="mapped"`, `category` in CATEGORIES)
  as a required prop if absent — count 1, material from theme palette default — emit
  `room.key_feature_injected` (register template; ctx: `text`, `category`). This makes named things appear.
- Keep all existing `room.size_clamped` / `room.prop_clamped` / `room.empty` logic unchanged.
- Update existing room_planner tests to pass `Brief.minimal("…")` instead of a raw string.

**Steps (TDD):**
- [ ] Test: `plan(Brief.minimal("a hermit's shack"), fake_llm, seed=1)` → returns `{room_size, props}`,
  back-compat shape intact.
- [ ] Test: a Brief with `key_features=[{"text":"anvil","status":"mapped","category":"table"}]` → a `table`
  prop is present in the plan + `room.key_feature_injected` decision.
- [ ] Register `room.key_feature_injected`; meta-test green.
- [ ] Adapt remaining `test_room_planner.py` cases to Brief input. Run full `pytest tests/ -q`.
- [ ] Commit: `feat(foundry): RoomPlanner consumes Brief + injects named features (spine slice 1)`.

## Task 4 — `report.py`: the build report (legibility)

**Files:** Create `foundry/report.py`, `foundry/tests/test_report.py`.

**Consumes:** Brief (Task 1), `list[DecisionPoint]`, manifest (`list[dict]` with `id`/`category`).
**Produces:** `render_build_report(brief, decisions, manifest) -> str` and
`build_report_dict(brief, decisions, manifest) -> dict` with keys `understood`, `built`, `assumed`, `couldnt_do`.

**Section rules:**
- **understood:** `setting`, `mood`, `scale`, `theme_tag`, mapped key_feature texts.
- **built:** room size (from manifest if present else brief), prop categories placed (from manifest),
  which key_features made it in.
- **assumed:** decisions with `severity in {"assumption","ambiguous"}` → their `plain` text.
- **couldnt_do:** `brief["unmapped"]` + decisions with `severity=="error"` → `plain` text.

**Steps (TDD):**
- [ ] Test: a Brief with one unmapped feature + one `assumption` DP → `build_report_dict` puts the unmapped
  item under `couldnt_do` and the DP under `assumed`; all four keys present.
- [ ] Test: `render_build_report` string contains the four section headers and the mapped feature.
- [ ] Run full `pytest tests/ -q`. Commit: `feat(foundry): build report — understood/built/assumed/couldnt-do (spine slice 1)`.

## Task 5 — wire `__main__` + eval signal + live verify

**Files:** Modify `foundry/__main__.py`; Modify `foundry/eval/signals.py`; Modify `foundry/tests/test_eval_signals.py`.

**Changes:**
- In `_cmd_quest` (or the room path): before room planning, `brief, bdec = Interpreter().interpret(request, llm, seed)`;
  collect `bdec` into the pipeline decisions; call `RoomPlanner().plan(brief, llm, seed)`. Quest path unchanged.
- After build, write `builds/<scene>/build_report.txt` and `build_report.json` via `report.py`, and print the
  text report to stdout.
- Eval: add `brief_valid` signal in `eval/signals.py` — positive when the Brief has a valid `theme_tag`
  (∈ THEMES ∪ {"*"}), valid `scale`, and every `key_features[].status` is consistent with its `category`.

**Steps (TDD + live):**
- [ ] Test: `eval/signals.py` `brief_valid` returns positive for a `Brief.minimal(...)`, negative for a Brief
  with `theme_tag` outside the set.
- [ ] Run full `pytest tests/ -q` AND `pytest tests/test_godot_smoke.py -q` — both green.
- [ ] **Live (≥9B model):** `python -m foundry quest --request "a wizard's tower study" --scene chk_spine --npc-count 1`
  → confirm `build_report.txt` exists with four sections; confirm a named feature in the prompt appears under
  "built"; headless-load the build clean. **Run twice** (qwen stochastic) — both produce a valid report + clean build.
- [ ] Commit: `feat(foundry): wire interpreter+report into pipeline + brief_valid eval (spine slice 1)`.

---

## Verify (slice-level checkpoint, then hand back)

Generate 2–3 prompts across ≥9B, headless-load + read each `build_report.txt`: the report should make each
generation **legible** (what was understood, what couldn't be done). Then we review before Slice 2 (quests ride
the spine + the parked per-NPC grammared dialogue fix).
