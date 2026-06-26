# Spine · Slice 2 (quests) — Implementation Plan / Delegation Prompts

> **For the CLI AI:** implement task-by-task, TDD red→green, one commit per task.
> Spec context: `SPINE-DESIGN.md` §11 (quests ride the spine) + `SPINE-SLICE1-PROMPTS.md`
> (the Brief pattern, now extended). Slice 1 already wired
> `prompt → Interpreter → Brief → RoomPlanner → … → Build Report`; quests still take the
> **raw request**. This slice puts quests on the spine **and** lands the parked per-NPC
> grammared dialogue fix so dialogue is reliable across models.

**Goal:** `behaviour_gen.plan_multi` consumes the Brief (not the raw prompt), the user's
named characters drive NPC roles, and any NPC the ungrammared multi-call fails to produce
falls back to the **reliable single-NPC grammared path** (themed) before canned.

**Architecture:** extend the Brief with a `characters` section (interpreter fills it);
`plan_multi(brief, …)` reads theme/setting/characters; on per-NPC parse miss, retry that NPC
via the existing grammar-constrained `plan()`; the build report gains a quest section.

**Tech Stack:** Python 3.14, pytest, injectable LLM, Decision Points, Godot 4.7 gate.

## Global Constraints (verbatim — same as Slice 1)

- Standing rules (`EASY-BATCH-PROMPTS.md` header). Dedicated branch/worktree. TDD red→green.
  Run **both** `pytest tests/ -q` **and** `pytest tests/test_godot_smoke.py -q` green. Commit per task.
- **LLM lessons (memory `canned-npc-means-pipeline-bug`):** free-form call → `llm(prompt, "")`
  never `None`; parse with `JSONDecoder().raw_decode(...)` never `json.loads(text[start:])`.
- Every `make_decision(code=...)` MUST be registered in `decisions._TEMPLATES`
  (`test_every_make_decision_code_is_registered` enforces it).
- Eval-first; qwen stochastic → verify live twice. Never touch `addons/godot_ai`.

## Current signatures (do not break)

- `RoomPlanner.plan(brief: dict | str, llm, seed=None)` — already on the Brief (Slice 1).
- `behaviour_gen.QuestBehaviourPlanner.plan(room_theme: str, manifest, llm, seed=None, carryable_ids=None)`
  — **single-NPC, grammar-constrained (`_GRAMMAR`), reliable.** This is the fallback engine.
- `behaviour_gen.QuestBehaviourPlanner.plan_multi(room_theme: str, manifest, llm, npc_count, seed, carryable_ids)`
  — multi-NPC, ungrammared. Retrofit target.
- `brief.minimal(prompt) -> dict`, `brief.validate_brief(raw, themes, categories) -> (brief, decisions)`.
- `__main__._cmd_quest` calls `plan_multi(parsed.request, manifest, llm, …)` at the raw-prompt line — rewire to pass the Brief.

---

## Task 1 — Brief v2: `characters` section (interpreter fills it)

**Files:** Modify `foundry/brief.py`, `foundry/interpreter.py`, `foundry/decisions.py`;
`foundry/tests/test_brief.py`, `foundry/tests/test_interpreter.py`.

**Schema add:** `characters: list[{role: str, note: str | None}]` — NPCs/people the user named or
clearly implied. `brief.minimal()` sets `characters: []`. `validate_brief` drops entries whose
`role` is empty/non-str; if a role survives, keep it verbatim (roles are open vocabulary — no
closed set). `schema_version` → 2.

**Interpreter add:** `build_prompt` also asks for `characters` ("people/NPCs the description implies,
each with a short role like 'blacksmith' and an optional note"). Parsed via the same `raw_decode`.
No new closed vocab. If the model returns none, `characters` stays `[]` (downstream defaults handle it).

**Steps (TDD, stub LLM):**
- [ ] Test: `brief.minimal("x")["characters"] == []` and `schema_version == 2`.
- [ ] Test: `validate_brief({"characters":[{"role":"blacksmith","note":null},{"role":""}]}, …)` →
  keeps the blacksmith, drops the empty-role entry.
- [ ] Test: interpreter stub returning `characters:[{"role":"apprentice"}]` → that survives into the Brief.
- [ ] Run `pytest tests/ -q`. Commit: `feat(foundry): Brief v2 characters section (spine slice 2)`.

## Task 2 — `plan_multi` consumes the Brief

**Files:** Modify `foundry/behaviour_gen.py`; `foundry/tests/test_behaviour_gen.py`.

**Change:** `plan_multi(brief: dict | str, manifest, llm, npc_count, seed, carryable_ids)`:
- Accept `dict | str`; if `str`, wrap via `brief.minimal(...)` (back-compat for existing tests).
- Build the multi-prompt from `brief["setting"]` + `brief["theme_tag"]` (normalized intent) instead of
  the raw string.
- **Seed NPC roles from `brief["characters"]`**: NPC *i* gets `characters[i].role` when present
  (so "a blacksmith and his apprentice" → roles blacksmith/apprentice, not two "villager"s). When the
  model also returns a role, prefer the model's only if non-empty *and* the brief had no character for
  that slot; otherwise the brief character wins. Emit `quest.role_from_brief` (ctx: `npc_id`, `role`)
  when a brief character sets the role.

**Steps (TDD):**
- [ ] Test: `plan_multi(brief.minimal("a tavern"), _MANIFEST_4, fake_llm, npc_count=2)` — back-compat,
  returns 2 specs with distinct targets (unchanged behaviour).
- [ ] Test: a Brief with `characters=[{"role":"blacksmith"},{"role":"apprentice"}]` + a stub LLM that
  returns empty roles → specs get roles blacksmith/apprentice + `quest.role_from_brief` decisions.
- [ ] Register `quest.role_from_brief`; meta-test green.
- [ ] Run `pytest tests/ -q`. Commit: `feat(foundry): plan_multi consumes Brief + brief-seeded roles (spine slice 2)`.

## Task 3 — Per-NPC grammared fallback (the parked reliability fix)

**Files:** Modify `foundry/behaviour_gen.py`; `foundry/tests/test_behaviour_gen.py`.

**Problem (from the 4-model run):** the ungrammared multi-call sometimes yields missing/garbled data
for an NPC → today that NPC gets a *canned* "villager / Hello there traveler". Instead, retry that one
NPC through the **grammar-constrained single-NPC `plan()`**, which is reliable, to get themed dialogue.

**Change:** inside `plan_multi`'s per-NPC loop, where it currently routes a missing/empty NPC to the
canned default (the `quest.missing_npc` path), first attempt:
```
spec, dpx = self.plan(room_theme_str, manifest, llm, seed=seed, carryable_ids=carryable_ids)
```
Use that spec's role (unless a brief character overrides) + dialogue; then enforce a **distinct** carryable
target vs already-used ones (reuse the existing distinct-target logic). Emit `quest.npc_grammared_fallback`
(ctx: `npc_id`). Only if `plan()` itself fails/raises → fall through to the existing canned default.
Keep `quest.missing_npc` for the truly-canned case.

**Steps (TDD, no llama — stub LLMs):**
- [ ] Test: a stub whose multi-call returns `{}` for npc_1 but whose single-NPC call returns a valid
  themed spec → npc_1 ends with the themed role/dialogue (NOT "villager"/"Hello there, traveler.") and a
  `quest.npc_grammared_fallback` decision; targets stay distinct across NPCs.
- [ ] Test: when BOTH the multi-call and the single-NPC `plan()` fail for an NPC → canned default +
  `quest.missing_npc` (graceful, unchanged).
- [ ] Register `quest.npc_grammared_fallback`; meta-test green.
- [ ] Run `pytest tests/ -q`. Commit: `feat(foundry): per-NPC grammared dialogue fallback (spine slice 2)`.

## Task 4 — Build report covers quests + wire `__main__`

**Files:** Modify `foundry/report.py`, `foundry/__main__.py`; `foundry/tests/test_report.py`.

**Report add:** the report sections gain quest content:
- **understood:** add `characters` (roles from the Brief).
- **built:** add per-NPC `role → target` and a **dialogue source** tag per NPC: `model` (from the
  multi-call), `grammared` (the Task-3 fallback), or `canned` (`quest.missing_npc`). Derive the tag from
  the decisions present for that npc_id.
- **couldnt_do:** unchanged (unmapped + errors).

**Wire:** in `__main__._cmd_quest`, change the `plan_multi(parsed.request, …)` call to
`plan_multi(brief, …)` (pass the Brief built earlier in the spine). Nothing else moves.

**Steps (TDD):**
- [ ] Test: `build_report_dict` with a Brief having `characters` and decisions including
  `quest.npc_grammared_fallback` for npc_1 → "understood" lists the characters, "built" tags npc_1's
  dialogue source as `grammared`.
- [ ] Run `pytest tests/ -q`. Commit: `feat(foundry): build report covers quests + wire Brief into plan_multi (spine slice 2)`.

## Task 5 — eval signal + live verify

**Files:** Modify `foundry/eval/signals.py`, `foundry/tests/test_eval_signals.py`.

**Eval add:** `check_dialogue_not_all_canned(record)` — positive when at least one NPC's dialogue source
is `model` or `grammared` (i.e. the build is not 100% canned fallbacks). Negative when every NPC is canned.

**Steps (TDD + live):**
- [ ] Test: a record with one `grammared` NPC → positive; a record where every NPC has `quest.missing_npc`
  → negative.
- [ ] Run `pytest tests/ -q` AND `pytest tests/test_godot_smoke.py -q` — both green.
- [ ] **Live (≥9B):** `python -m foundry quest --request "a blacksmith's forge with an apprentice"
  --scene chk_spine2 --npc-count 2` → `build_report.txt` shows characters blacksmith/apprentice under
  "understood", each NPC's dialogue source under "built", and **no NPC is canned** (themed greet, not
  "Hello there, traveler."). Headless-load clean. **Run twice** (stochastic) — both non-canned + clean.
- [ ] Commit: `feat(foundry): dialogue-not-canned eval + slice-2 live verify (spine slice 2)`.

---

## Verify (slice-level checkpoint, then hand back)

Run the multi-model comparison again
(`quest_compare --full-pipeline --run-playthrough --npc-count 2`, 9b/14b/27b): every model should now
read **themed, not canned**, and each build's `build_report.txt` should make the quest legible
(characters understood, dialogue source per NPC). This closes the original "canned villager" complaint
through the spine. Next: pick the first roadmap bundle and run it through the spine (interpretation +
legibility from day one).
