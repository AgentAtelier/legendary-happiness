# Spine Fix — Constrain structured LLM output with json_schema

> **For the CLI AI:** implement task-by-task, TDD red→green, one commit per task.
> Context: live 27b verification of Slice 3 showed the **soul system inert on capable
> models** — the Interpreter (and the multi-NPC quest call) are *ungrammared*
> (`grammar=""`), so verbose thinkers (14B/27B) ramble in prose instead of emitting JSON;
> the parse fails and `interpret()` falls back to `Brief.minimal` (no souls). 4B only
> "worked" because it doesn't ramble. **734 unit tests + 8/8 smoke passed while G1 was
> broken on the best models** — this is why live verification is the orchestrator's job.

**Goal:** make structured-output LLM calls reliable on every model by constraining them with
llama.cpp's native **`json_schema`** parameter (verified working on this server: it returns
clean JSON). Apply to the **Interpreter** and the **multi-NPC quest call** — the two
ungrammared call sites.

**Architecture:** `FoundryLLM` gains a `json_schema` parameter passed straight to
`/completion`; the Interpreter passes the Brief schema; `plan_multi` passes a per-`npc_count`
schema. Deterministic validation (`validate_brief`, role/dialogue validators) still runs on top.

## Global Constraints (verbatim)

- **Testing split:** **[CLI]** tasks run the *fast* gates (`pytest tests/ -q` + `pytest
  tests/test_godot_smoke.py -q`, both green) then hand off. **[ORCH]** live verification (≥9B
  re-run, showcase) is the orchestrator's — do NOT run it.
- LLM lessons still hold: `raw_decode` parsing stays (defense in depth); never `grammar=None`
  (asset-default footgun). `json_schema` is a *new* lever, not a replacement for validation.
- Every `make_decision(code=...)` registered (`test_every_make_decision_code_is_registered`).
- Eval-first. Never touch `addons/godot_ai`.

## Verified fact (build this on it)

`POST /completion` with `{"prompt":...,"json_schema":{...}}` returns JSON constrained to the
schema (tested: `{"name":"Felix"}`). So server-side `json_schema` is the mechanism — no
hand-written GBNF needed.

---

## Task 1 [CLI] — `FoundryLLM` json_schema support

**Files:** Modify `foundry/llm.py`; Create/extend `foundry/tests/test_llm.py`.

**Change:** `__call__(self, prompt: str, grammar: Optional[str] = None, json_schema: Optional[dict] = None)`.
- When `json_schema is not None`: set `payload["json_schema"] = json_schema` and do NOT set
  `payload["grammar"]` (json_schema wins; they're mutually exclusive).
- Otherwise: unchanged (existing grammar semantics — `""` = no grammar, `None` = asset default).

**Steps (TDD, mock `requests.post` like the existing tests):**
- [ ] Test: `_capture_payload` calling with `json_schema={"type":"object",...}` → payload has
  `json_schema` and NO `grammar` key.
- [ ] Test: existing grammar paths unchanged (`grammar=""` → no grammar/json_schema; explicit
  grammar still sent).
- [ ] Run `pytest tests/ -q`. Commit: `feat(foundry): FoundryLLM json_schema support`.

## Task 2 [CLI] — Interpreter uses the Brief json_schema

**Files:** Modify `foundry/interpreter.py`, `foundry/brief.py`; `tests/test_interpreter.py`.

**Add `BRIEF_JSON_SCHEMA`** (build it in `brief.py`, importing the live vocabularies so it never
drifts):
```python
# brief.py
def brief_json_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "setting": {"type": "string"},
            "mood": {"type": "array", "items": {"type": "string"}},
            "scale": {"enum": list(VALID_SCALES)},
            "theme_tag": {"enum": list(THEMES)},   # 12 themes + "*"
            "key_features": {"type": "array", "items": {"type": "object",
                "properties": {"text": {"type": "string"},
                               "category": {"type": ["string", "null"]}},
                "required": ["text"]}},
            "characters": {"type": "array", "items": {"type": "object",
                "properties": {
                    "role": {"type": "string"},
                    "note": {"type": ["string", "null"]},
                    "soul": {"type": "object", "properties": {"substrate": {"type": "object",
                        "properties": {"courage": {"type": "number"},
                                       "generosity": {"type": "number"},
                                       "stability": {"type": "number"}}}}}},
                "required": ["role"]}},
        },
        "required": ["setting", "scale", "theme_tag", "key_features", "characters"],
    }
```
**Interpreter:** in `interpret()`, call
`llm(self.build_prompt(prompt), json_schema=brief_json_schema())` instead of `llm(prompt, "")`.
Keep the `try/except → Brief.minimal + brief.parse_fallback` guard and the `raw_decode` parse
(now rarely needed, but defense in depth).

**Injected-llm contract:** the `llm` callable now may receive `json_schema=`. Update the test
stub signatures used for the interpreter to accept it, e.g.
`def stub(prompt, grammar=None, json_schema=None): ...`. A capturing stub can assert the schema
was passed.

**Steps (TDD, stub LLM):**
- [ ] Test: `interpret` calls the llm with `json_schema` set (capture via stub) — not `grammar=""`.
- [ ] Test: stub returns a clean Brief JSON (as a constrained model would) → souls survive into
  `brief["characters"][i]["soul"]` (no fallback).
- [ ] Test: `brief_json_schema()["properties"]["theme_tag"]["enum"]` equals `list(THEMES)` (stays
  in sync with the engine vocabulary).
- [ ] Run `pytest tests/ -q`. Commit: `feat(foundry): Interpreter constrains output via Brief json_schema`.

## Task 3 [CLI] — multi-NPC quest call uses a json_schema

**Files:** Modify `foundry/behaviour_gen.py`; `tests/test_behaviour_gen.py`.

**Build a per-`npc_count` schema** (a fixed property per NPC id, so the dict-of-dicts that
"didn't fit one GBNF" is expressible as a schema):
```python
def _multi_npc_json_schema(npc_ids: list[str]) -> dict:
    npc = {"type": "object", "properties": {
        "npc_role": {"type": "string"},
        "target_entity": {"type": "string"},
        "dialogue": {"type": "object", "properties": {
            "greet": {"type": "string"}, "ask": {"type": "string"},
            "wrong": {"type": "string"}, "thank": {"type": "string"}},
            "required": ["greet", "ask", "wrong", "thank"]},
        "idle_barks": {"type": "array", "items": {"type": "string"}},
    }, "required": ["npc_role", "target_entity", "dialogue"]}
    return {"type": "object",
            "properties": {nid: npc for nid in npc_ids},
            "required": list(npc_ids)}
```
**`plan_multi`:** replace the `llm(prompt, "")` multi-call with
`llm(prompt, json_schema=_multi_npc_json_schema(npc_ids))`. The per-NPC grammared fallback
(Slice 2) stays as the safety net but should now rarely fire on capable models.

**Steps (TDD, stub LLM):**
- [ ] Test: `plan_multi` calls the llm with a `json_schema` whose `required` lists all npc_ids
  (capture via stub).
- [ ] Test: back-compat — a stub returning a well-formed multi-NPC object → specs filled from the
  model (dialogue source `model`, not `grammared`).
- [ ] Run `pytest tests/ -q` AND `pytest tests/test_godot_smoke.py -q`. Commit:
  `feat(foundry): multi-NPC quest call constrained via json_schema`.

## Task 4 [CLI] — hand off

- [ ] Confirm full suite + Godot smoke green. Report commits. **Do NOT run live generation** —
  hand off to the orchestrator.

---

## [ORCH] Live verification — orchestrator only

After handoff, the orchestrator re-runs the 27b soul showcase:
`quest_compare --prompt "a fearful hermit and a proud, generous blacksmith share a workshop"
--models qwen3-6-27b --prefix showcase_soul --full-pipeline --run-playthrough --npc-count 2`
→ confirm `build_report.txt` shows two *souled* characters (non-zero substrates, e.g. "a timid
hermit" / "a bold, warm blacksmith"), `quest_data` souls are non-zero, dialogue source is now
`model` (not all `grammared`), greet lines read in different tones. Then write the showcase `.md`
(prompt + real results, build kept). Run-twice for stability.

> **Note on the contract ripple:** adding `json_schema=` to the `llm` callable means several test
> stubs (`lambda prompt, grammar=None: ...`) must grow `json_schema=None`. This is mechanical;
> update them as you touch each call site. If any llama.cpp build rejects `json_schema`, the
> fallback is to convert the schema to GBNF locally and pass via the existing `grammar` param —
> but this server accepts `json_schema` (verified), so prefer it.
