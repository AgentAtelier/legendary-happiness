<!-- ARCHIVED — see ~/dev/games/Forge/FORGE-STACK.md for current documentation -->

# WO-002 — Batch Operator (Phase A, capability #2)

**Read `00-EXECUTOR-BRIEFING.md` first.**
**Executor:** MiniMax M3. **DeepSeek steps:** step 3 review tag below.
**Est. effort:** 6–10h.
**Goal:** One command replaces 40 inspector clicks: filter nodes, preview the
change, confirm, apply. Deterministic filter parsing — no LLM in this WO.

## Deliverables

1. New package `devforge/operations/` (`__init__.py`, `batch_filter.py`)
2. Two MCP tools in `mcp_server.py`: `batch_preview`, `batch_apply`
3. Test suite `devforge/tests/test_batch_operator.py` (≥ 10 tests),
   registered in `scripts/run_all_tests.sh`

## Filter language (`devforge/operations/batch_filter.py`)

```python
@dataclass
class NodeFilter:
    node_type: str | None = None      # exact Godot type, e.g. "OmniLight3D"
    name_contains: str | None = None  # case-insensitive substring
    under_path: str | None = None     # subtree root, e.g. "/root/Main/Enemies"

def parse_query(query: str) -> NodeFilter: ...
def match_nodes(scene_tree: dict, f: NodeFilter) -> list[str]:  # node paths
```

`parse_query` accepts a **structured syntax** (primary, exact):

```
type:OmniLight3D
type:OmniLight3D name~lamp
type:CollisionShape3D under:/root/Main/Enemies
name~temp under:/root/Main
```

Tokens are space-separated; `type:`, `name~`, `under:` prefixes; unknown
tokens → raise `ValueError` with a message that lists the valid forms.
Additionally accept these **convenience phrasings** via regex (map to the
same NodeFilter; document each regex with an example):

```
"all OmniLight3Ds"            -> type:OmniLight3D    (strip trailing s)
"every Timer under /root/X"   -> type:Timer under:/root/X
"nodes named foo"             -> name~foo
```

If a convenience phrase doesn't match any pattern, raise ValueError telling
the caller to use the structured syntax. Do NOT attempt LLM parsing — that
is a later work order.

`match_nodes` uses `SceneGraph` (`devforge/knowledge/scene/scene_graph.py`):
type match is exact, name match case-insensitive substring, `under_path`
means the node's path starts with `under_path + "/"` (or equals it).
Matching is deterministic and ordered by node path.

## The two-step MCP flow

**`batch_preview(query: str, property: str, value: Any) -> dict`** — read-only.
`_init()`; fetch scene via `_scene_store.get_or_fetch(_executor)`; parse,
match; build one operation per matched node:

```python
{"type": "set_property", "node": path, "property": property, "value": value}
```

Store `{"operations": ops, "query": query, "scene_version": version}` in
`_artifact_store` (it returns a plan id). Return:

```json
{
  "plan_id": "ab12cd34ef56",
  "matched": ["/root/Main/Lamp1", "/root/Main/Lamp2"],
  "match_count": 2,
  "property": "light_energy",
  "value": 0.8,
  "scene_version": 12,
  "hint": "Review the matched paths, then call batch_apply with this plan_id to execute."
}
```

Zero matches is a valid result (`match_count: 0`, no plan stored,
`plan_id: null`) — say so in the hint.

**`batch_apply(plan_id: str) -> dict`** — mutating, but only with a plan_id
from a previous preview (this IS the confirmation step — document that in
the docstring). Behavior: `_init()`; fetch the plan from `_artifact_store`
(unknown id → `{"error": "unknown or expired plan_id"}`); re-fetch the scene
and **compare `scene_version`** — if the world moved since preview, return
`{"error": "scene changed since preview (version X -> Y), re-run batch_preview"}`
and do NOT execute. Otherwise run the operations through the existing
validator+executor path the same way `apply_spec` does (under
`_pipeline_lock`, call `_engine.validate_pipeline(ops, scene, [])` first;
refuse to execute if validation errors; then `_executor.execute(operations=valid_ops, files=[])`
and `_scene_store.note_writes()`). Return the executor's
`to_dict()` plus `applied_count`.

Value handling: MCP delivers JSON-typed values already (float/str/list) —
pass them through untouched. Do not stringify.

## Tests (`devforge/tests/test_batch_operator.py`)

No live stack: synthetic scene dicts; mock the executor with
`unittest.mock.MagicMock` where needed; test `parse_query` and `match_nodes`
directly (pure functions — most of the suite lives here). Minimum cases:

1. `parse_query("type:OmniLight3D")` → NodeFilter(node_type="OmniLight3D")
2. Combined query `type:X name~y under:/root/Z` parses all three fields
3. `"all OmniLight3Ds"` convenience phrasing → type filter (plural stripped)
4. Unknown token → ValueError naming the valid forms
5. `match_nodes` finds exactly the two `OmniLight3D`s in a 10-node tree
6. `under_path` excludes same-type nodes outside the subtree
7. `name_contains` is case-insensitive
8. Zero-match query returns empty list (not an error)
9. Operation dicts have exactly the shape `{"type": "set_property", "node": ..., "property": ..., "value": ...}`
10. Ordering: matched paths are sorted and stable across runs

`[DEEPSEEK ≤20min]` After all tests pass: re-read `batch_apply` against
`apply_spec` in `mcp_server.py` and confirm the lock/validate/execute/
note_writes sequence matches; fix discrepancies; log findings in WORKLOG.

## Acceptance checklist

- [ ] `.venv/bin/python devforge/tests/test_batch_operator.py` → all pass
- [ ] `scripts/run_all_tests.sh` → "All test suites passed."
- [ ] `batch_apply` refuses on scene-version drift (covered by a test with a mocked store)
- [ ] Both docstrings show literal JSON argument/return examples
- [ ] WORKLOG.md entry appended (incl. DeepSeek minutes)
