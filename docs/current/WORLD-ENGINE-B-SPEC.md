# Sub-project (b) NL→patch interpreter — design spec

**Date:** 2026-06-26
**Status:** CANONICAL DESIGN (post-PROMPT 3-A review)
**Source:** synthesis of `docs/current/WORLD-ENGINE.md` §4–6 (the "source of truth is
operations, not prompts" tenet + the W2 semantic-grounding wall) + the existing W2
query layer at `foundry/world/query.py`.
**Scope:** integrate the pure-deterministic World Engine mechanics (operations,
op-log, validation gate, content-addressed caching — sub-project (a)) with the
LLM reasoning layer to support conversational world-editing. **No code in this
commit.** The implementation follows separately (PROMPT 3-B).

> *"Operations, not prompts, are the source of truth. NL is a patch generator;
> the operation log is what rebuilds the world."* — WORLD-ENGINE.md §4.

---

## 0. Status / scope

This spec closes sub-project **(b) NL → patch** of the World Engine build
(WORLD-ENGINE.md §6 decomposition). The preconditions are met by sub-project
(a) (units 1–4 complete; 151+ world tests green; PROMPT 2-A shipped the human-
patch CLI substrate). The postcondition is: a user can say *"add a courtyard
to the north of the hall"* and the world mutates *deterministic-ally* (off the
op-log) with a structured error if the patch is spatially impossible.

**Architectural contracts this spec inherits (do not re-litigate in PROMPT 3-B):**

- **Ops are durable; prompts are provenance.** Replaying ops reconstructs
  the world; replaying prompts does not. (WORLD-ENGINE §4, audit consensus.)
- **Validation gate is the source of truth on impossibility.** Every new op
  passes `world.validation.apply_op_checked`. (W3, the mechanical wall.)
- **W2 entity reference resolution is real and structural.** Stable entity
  IDs live in the Brief (`world/operations.py` uses these throughout).
- **Godot runtime is the mutable materialized instance, not the source of
  truth.** `addons/godot_ai` is out of scope.

---

## 1. The NL → patch loop

The user submits a natural-language edit. The LLM is **not** generating a
fresh world — it is generating a constrained sequence of JSON-patch ops from
the existing vocabulary. The loop is:

```
load world → prompt LLM (world_index + ops vocab + NL request)
    ↓
LLM either:
  (a) emits a `query_world` tool_call → engine evaluates → result fed back
  (b) emits a finalized ops array → gated by `apply_op_checked`
    ↓
on validation error: re-prompt with structured violations (bounded retries)
on exhaustion: emit a Decision Point, hand back to the human
```

**Prompt template (system message):**

```text
You are the Forge World Engine architect. The user wants to edit the
PERSISTENT world (an append-only operation log). You cannot freely rewrite
the world — you must emit a valid JSON ARRAY of operations from the
vocabulary below; the engine validates each op's spatial integrity
before committing.

AVAILABLE OPERATIONS (verbatim from foundry/world/operations.py):
  - add_space      {op, id, brief, footprint:{origin:[],size:[]}}
  - add_portal     {op, id, from_space, to_space, position:[], size:[]}
  - add_entity     {op, space, entity:{id, type, pos, properties?}}
  - move_entity    {op, space, entity_id, new_pos:[]}
  - set_property   {op, target_kind:space|entity, space, entity_id?,
                    path:[], value}
  - remove_entity  {op, space, entity_id}

CURRENT WORLD (compact LLM-consumable index):
  {world_index_json}

If you need more detail about relations ("what is north of hall?",
"which entities are &lt;type&gt; in &lt;space&gt;?"), use the `query_world`
tool BEFORE emitting ops.

USER REQUEST:
  {user_natural_language_request}

When your edits are ready, emit the JSON ARRAY of operations under the
`final_ops` key of your output schema. No prose; just the array.
```

**Output schema (`json_schema=` — never `grammar=None` per AGENTS.md):**

```json
{
  "type": "object",
  "properties": {
    "final_ops": {
      "type": "array",
      "items": {"$ref": "#/definitions/op"}
    },
    "thinking": {
      "type": "string",
      "description": "Optional brief rationale (NOT executed; logged as provenance only)."
    }
  },
  "required": ["final_ops"],
  "additionalProperties": false
}
```

**Concrete example — input→output:**

| NL request                          | Emitted `final_ops`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| "add a courtyard to the north"      | `[{"op":"add_space","id":"courtyard_01","brief":{"theme":"courtyard"},"footprint":{"origin":[hall_01_min_x,0.0,hall_01_min_z - 6.0],"size":[6.0,4.0,6.0]}},{"op":"add_portal","id":"portal_h_c","from_space":"hall_01","to_space":"courtyard_01","position":[hall_01_min_x + 1.0,1.5,hall_01_min_z],"size":[1.5,2.0]}]` |
| "make the hall darker"              | `[{"op":"set_property","target_kind":"space","space":"hall_01","path":["mood","lighting"],"value":"dim"}]`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| "have the alchemist give the book"  | `[{"op":"set_property","target_kind":"entity","space":"hall_01","entity_id":"thief_01","path":["inventory"],"value":["book_01"]}]`  *(multi-NPC plumbing — see §4.)*                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |

The LLM's `thinking` field is **not** executed. It is captured as provenance
("this user prompt produced these ops with this rationale") so a future
auditor can trace world state back to the conversation that produced it. The
op-log remains the authoritative source.

---

## 2. The `query_world` tool

**Design decision:** **OpenAI/Anthropic-style native `tool_calls`** (a
function-call response whose evaluation loops back as a user-role message).
Not "embed queries inline in the JSON op array" — the latter doesn't let the
LLM condition its op proposal on the query result.

The LLM emits a tool invocation; the engine evaluates it locally against the
current `world` (cheap, deterministic, pure); the result is fed back; the LLM
may then emit either another tool call (deeper ground truth) or a final ops
array.

**Tool signature:**

```json
{
  "name": "query_world",
  "description": "Ask a question about the current world state. Resolves\nreferences and explores spatial relations BEFORE you emit any ops.",
  "parameters": {
    "oneOf": [
      {"description": "Cardinal direction from one space to another",
       "required": ["from_space","to_space"],
       "properties": {
         "query_type": {"enum":["direction"], "const":"direction"},
         "from_space": {"type":"string"},
         "to_space":   {"type":"string"}}},
      {"description": "Find entities by type and/or space",
       "required": ["query_type"],
       "properties": {
         "query_type": {"enum":["find_entities"], "const":"find_entities"},
         "type":  {"type":"string"},
         "space": {"type":"string"}}},
      {"description": "List neighbor spaces (via portals) of a given space",
       "required": ["query_type","space"],
       "properties": {
         "query_type": {"enum":["neighbors"], "const":"neighbors"},
         "space": {"type":"string"}}},
      {"description": "Backing data for one space — used when\nworld_index summary is insufficient",
       "required": ["query_type","space"],
       "properties": {
         "query_type": {"enum":["space_summary"], "const":"space_summary"},
         "space": {"type":"string"}}}
    ]
  }
}
```

**Mapping onto `foundry/world/query.py`:** the engine's `call_query_world`
method dispatches `query_type` to the existing pure functions:

| `query_type`     | mapped onto                                                | return shape                                                |
| ---------------- | ---------------------------------------------------------- | ----------------------------------------------------------- |
| `direction`      | `world.query.direction(world, from_id, to_id)`             | `{"direction": "north"|"south"|"east"|"west"|"up"|"down"|"here"|"unknown"}` |
| `find_entities`  | `world.query.find_entities(world, type=…, space=…)`          | `{"entities": [{"space_id":…, "id":…, "type":…, "pos":[…]}]}` |
| `neighbors`      | `world.query.neighbors(world, space_id)`                    | `{"neighbors": [{"portal_id":…, "to_space":…}]}`           |
| `space_summary`  | `world.query.space_summary(world, space_id)`                | the existing `space_summary` dict verbatim                  |

**Loop semantics:** the interpreter loop terminates when the LLM's response
contains `final_ops` and no tool_calls. Empty `final_ops` is valid (the LLM
chose not to edit — e.g., it confirmed the user's request is already met).

---

## 3. The interpreter extension

**Design decision:** **new `foundry.world.interpreter.WorldInterpreter` —
NOT extending the existing `foundry.interpreter.Interpreter`.**

The existing `Interpreter.interpret(prompt, llm, seed)` returns
`(brief, decisions)` — it maps a free-form prompt to a single-Room Brief for
the *stateless* quest path. The new `WorldInterpreter` operates on a
**persistent** `World` (sub-project a's W-DAG) and emits ops against it. They
have orthogonal inputs and orthogonal output contracts; merging them would
collapse the Brief-vs-World distinction that WORLD-ENGINE.md §4 makes
explicit.

```python
# Pseudocode (NOT IMPLEMENTED IN THIS COMMIT):

class WorldInterpreter:
    def __init__(self, world: World, llm: LLM, *, max_retries: int = 3):
        self.world = world
        self.llm = llm
        self.tools = [_QUERY_WORLD_TOOL_SCHEMA]
        self.max_retries = max_retries

    def edit(self, nl_request: str) -> tuple[World, list[DecisionPoint]]:
        accumulated_corrections = 0
        history = [self._initial_messages(nl_request)]
        while True:
            resp = self.llm.complete(history, tools=self.tools,
                                     json_schema=FINAL_OPS_SCHEMA)
            if resp.tool_call.name == "query_world":
                tool_result = call_query_world(self.world, resp.tool_call.args)
                history.append(tool_result_message(resp, tool_result))
                continue
            ops = resp.final_ops
            try:
                for op in ops:
                    self.world = apply_op_checked(self.world, op)
            except WorldValidationError as e:
                if accumulated_corrections >= self.max_retries:
                    return self.world, [
                        make_decision(
                            code="world.edit_unresolvable",
                            stage="world", severity="error",
                            context={"violations": [v.__dict__ for v in e.violations],
                                     "last_nl": nl_request},
                            choices=(...))]  # shrink / reposition / cancel
                history.append(system_warning(e.violations))
                accumulated_corrections += 1
                continue  # re-prompt with same op-loop context
            return self.world, []  # atomic commit; new ops appended to op_log
```

### Decision-Point fallback strategy on `WorldValidationError`

**Tried first:** auto-re-prompt. `apply_op_checked` raises
`WorldValidationError(violations)` (carry `[code, message, details]` per
`foundry/world/validation.py`). The engine packages the structured
violations as a system warning and re-prompts:

```text
VALIDATION FAILED for your previous ops. Each violation is one of:
  [space.overlap]  new space courtyard_01 overlaps existing space hall_01
  [portal.not_adjacent]  spaces hall_01 and courtyard_01 are not face-adjacent

You may either (a) re-emit a corrected `final_ops` array, or
(b) call `query_world` first to inspect the actual footprints and
neighbor relations before retrying.
```

**Max retries: 3.** After exhaustion the engine **does not** commit and
**emits a Decision Point** via `foundry.decisions.make_decision(...)` with
code `world.edit_unresolvable` and three choices (matching the
existing `room.planner_parse_fallback` shape used by `_cmd_quest` in
`foundry/__main__.py`):

- *"Shrink / reposition"* — operator adjusts the NL request and retries.
- *"Cancel"* — world stays at pre-edit state (atomic guarantee; nothing
  on disk changed).
- *"Force-commit anyway"* — operator assumes the spatial violation is a
  test fixture quirk; the engine appends the ops as-is BUT stamps the
  log entry with a `forced: true` flag so downstream auditors can flag the
  world for cohesion-contract review.

The atomic-rollback guarantee from PROMPT 2-A carries forward: only
`save_world` runs after the full op loop commits. Any retry-loop failure
leaves the on-disk world byte-identical to pre-edit.

---

## 4. Entity-ID grounding (W2)

**Design decision:** **stable entity IDs come directly from
`world.nodes[space_id].entities[i].id`** (option (a) from the four
alternatives considered). They are already stable — `foundry/world/
operations.py` uses them throughout `_do_move_entity`, `_do_remove_entity`,
`_do_set_property` — and the W2 query layer (`world.query.space_summary`)
already exposes them inside `world_index(world)`.

**No separate "Read-State JSON"** is needed (option (b), rejected): it would
duplicate the same data and create two sources of truth.

**The LLM's prompt context always includes the full `world_index`** (option
(c) is moot once we choose (a) — the IDs are inside it). Cost is bounded:
`world_index` is the compact summary (id, theme, centre, size,
entity-list, neighbor-with-directions), not raw geometry. For worlds with
~10–20 spaces this fits comfortably inside any modern LLM context.

### Reference resolution pattern

When the NL request is *"add a torch near the throne"*, the interpreter:

1. **First pass** — sends the system prompt + request to the LLM along with
   the full `world_index`. The LLM either:
   - (a) emits the ops directly referencing `throne_001` (because the
     world_index shows it),
   - (b) emits a `query_world(find_entities)` tool call to confirm the
     throne's id (e.g., the user said *"that big chair thing"* instead),
   - (c) emits a `query_world(space_summary)` to inspect a candidate space
     before adding the torch there.
2. **Re-prompt loop** accumulates the query results and the LLM proposes
   the final ops.

**Multi-NPC / multi-quest worlds.** When the NL request says *"have the
alchemist give the book to the thief"*, the LLM must emit
`set_property` ops with explicit `entity_id` referencing both NPCs. If
NPC ids are missing or ambiguous, the LLM emits a `query_world(
find_entities)` to look them up. Stable NPC ids live in
`world.nodes[npc_space_id]` exactly the same way as other entity ids; the
interpreter makes no special case for NPC category. (This assumes the
quest-data convention is consistent — if it isn't, that's a W4 Cohesion
issue, addressed by the Cohesion Contract spec not this one.)

---

## 5. Module boundaries

**Rule:** `foundry/world/interpreter.py` may only import from:

- `foundry.world.*` (model, operations, validation, query, persistence,
  assembly — the deterministic mechanics this layer drives)
- `foundry.llm` (FoundryLLM client + `json_schema=...` structured output)
- `foundry.decisions` (Decision Point emission when the retry budget
  exhausts)

It MUST NOT import from:

- `addons.godot_ai` — forbidden by AGENTS.md ("Never touch addons/godot_ai")
- `foundry/godot_template/` — the Godot runtime executes the materialized
  state; it does not drive NL reasoning
- `foundry/interpreter.py` — Inspiration only; the brief-producing
  `Interpreter.interpret` runs once at quest-start and emits a single
  Brief; the `WorldInterpreter.edit` runs many times across the session and
  emits ops against the live `World`. Different lifecycles.

### Files to create (in PROMPT 3-B, NOT in this commit)

| File                                       | Purpose                                                                                                |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| `foundry/world/interpreter.py`              | `WorldInterpreter` class + `_QUERY_WORLD_TOOL_SCHEMA` + `_FINAL_OPS_SCHEMA` + `call_query_world`      |
| `foundry/world/__init__.py` *(update)*      | re-export `WorldInterpreter` so `python -m foundry world edit` can reach it                            |
| `foundry/tests/test_world_interpreter.py`  | unit tests with `MockLLM` stub (auto-correction, query-loop, decision-point emission, atomic rollback) |

### Files NOT touched (PROMPT 3-B scope rule)

- `foundry/world/operations.py` — vocabulary is fixed, no new ops needed
- `foundry/world/validation.py` — `apply_op_checked` is the gate; don't bypass
- `foundry/world/query.py` — pure read layer, no new queries for v1
- `foundry/world_cli.py` — human-patch CLI surface stays as-is; the new
  `forge world edit <world> "<NL>"` command routes through `WorldInterpreter`
  and lives in `__main__.py` next to the existing `forge world apply` routing.

---

## 6. Test strategy

### Unit tests — `MockLLM` stub at `foundry/tests/test_world_interpreter.py`

A `MockLLM` produces a deterministic script of message-response pairs.
Tests replay script fragments and assert:

1. `test_call_query_world_dispatch` — every `query_type` round-trips
   through `foundry.world.query.<fn>` correctly (handcrafted arg → return).
2. `test_world_interpreter_build_prompt_includes_index` — system prompt
   contains the `world_index_json` substring and the ops vocabulary block.
3. `test_interpreter_loop_handles_tool_then_patch` — given a script that
   issues one `query_world(direction)` and then emits `final_ops`, the
   interpreter responds with corrected ops and commits.
4. `test_interpreter_auto_corrects_world_validation_error` — given a
   script that emits spatially-overlapping ops on first try and corrected
   ops on second, the interpreter recovers and commits (atomic).
5. `test_interpreter_emits_decision_point_on_max_retries` — given a
   script that always-emits-overlapping-ops, the interpreter commits
   nothing and emits one `world.edit_unresolvable` DecisionPoint with
   three choices.
6. `test_apply_checked_atomic_rollback_on_exception` *(re-uses PROMPT 2-A
   semantics)* — applying an op-and-then-catching doesn't mutate the
   world on disk; secondary check confirms `load_world(world_dir)`
   returns the pre-edit state byte-identical.

### Live integration test — orchestrator only (gated)

```python
@pytest.mark.live
@pytest.mark.skipif(not _llm_online, reason="llama :8002 not running")
def test_live_interpret_add_room_small_spec():
    """ORCH-OWNED: hit local llama with a real prompt and assert the
    resulting world has new logical structure."""
```

The CLI agent does not run this; the orchestrator flips the live gate after
the unit suite is green. This is per AGENTS.md's split (`@pytest.mark.live`
is excluded from the fast gate).

---

## 7. Implementation task list (≤ 6)

Sequenced TDD-red → TDD-green per task; full suite + ruff at the end.
Each task delivers a working, tested slice.

1. **Tool definitions + `call_query_world` dispatch.**
   *Touch:* `foundry/world/interpreter.py` (new).
   Test: `tests/test_world_interpreter.py::test_call_query_world_dispatch`
   — round-trips `direction`, `find_entities`, `neighbors`,
   `space_summary` against a fixture world.

2. **`WorldInterpreter.__init__` + prompt construction.**
   *Touch:* `foundry/world/interpreter.py`.
   Test: `tests/test_world_interpreter.py::test_world_interpreter_build_prompt_*
   — system prompt contains `world_index_json`, the ops vocabulary, the
   NL request, and the tool schema (snapshot-style assertion).

3. **Tool-call evaluation loop + atomic commit on first success.**
   *Touch:* `foundry/world/interpreter.py`.
   Test: `tests/test_world_interpreter.py::test_interpreter_loop_handles_tool_then_patch`
   — `MockLLM` emits one `query_world(direction)` then `final_ops`; the
   interpreter commits the ops and returns `(world, [])` with zero
   DecisionPoints. Verify `save_world` was called exactly once.

4. **Auto-correction on `WorldValidationError` (bounded retry).**
   *Touch:* `foundry/world/interpreter.py`.
   Test: `tests/test_world_interpreter.py::test_interpreter_auto_corrects*
   — `MockLLM` script emits overlapping ops then corrected ops; the
   interpreter recovers, commits exactly once. Companion test
   `test_apply_checked_atomic_rollback_on_exception` confirms no partial
   writes on the failure-then-recover path (carries PROMPT 2-A's atomic
   guarantee forward).

5. **Decision-Point fallback after max retries exhausted.**
   *Touch:* `foundry/world/interpreter.py` + `foundry/decisions.py` *(add the
   `world.edit_unresolvable` decision template)*.
   Test: `tests/test_world_interpreter.py::test_interpreter_emits_decision_point_on_max_retries`
   — `MockLLM` always emits invalid ops; interpreter returns `(world, [dp])`
   with one DecisionPoint carrying the structured violations and three
   choices; the on-disk world is byte-identical to pre-edit.

6. **CLI wiring + the live integration test stub.**
   *Touch:* `foundry/__main__.py` (add `world edit <world> "<NL>"`
   subcommand routing; mirrors the dispatch shape of `forge world apply`
   from PROMPT 2-A) + `foundry/tests/test_world_interpreter.py` (add
   `@pytest.mark.live` stub).
   Test: `tests/test_world_cli.py::test_world_edit_routes_to_world_interpreter`
   (CLI smoke — uses a `MockLLM` baked into a stub hook so the test stays
   fast-gate compatible) + the @pytest.mark.live stub for orchestrator.

### Acceptance gate (PROMPT 3-B final)

- `pytest tests/test_world_interpreter.py -q` → all green
- `pytest tests/ -q` → no regression (last known: 1761 passed)
- `ruff check .` → exit 0
- `pytest tests/test_godot_smoke.py -q` → 5 passed / 3 godot_heavy-marked
  (no regression vs PROMPT 2-A baseline; godot_heavy stays separately
  tracked)

### Out of scope (queue-deferred, file as new tickets if needed)

- Live re-test against the running llama server (orchestrator-only)
- Cohesion (W4) integration — separate spec
- Cohesion override flagging in the op-log (separate)
- The exact wording of the prompt template — refined against real LLM
  outputs once the live test runs

---

*Authored 2026-06-26 by the CLI agent (DeepSeek V4 Pro) per queue PROMPT 3-A.
Implementation: PROMPT 3-B (next).*
