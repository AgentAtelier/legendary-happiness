# SESSION-CHANGES-2026-06-15 — Slice 2: Edit-Op Reliability Cluster

**Date:** 2026-06-15  
**Slice:** 2/4  
**Status:** ✅ Complete  
**Impact:** All three edit-op scenarios (node_delete, node_rename, rename_existing) fixed — 0 errors, all ops applied

---

## Summary

The scenario suite had 3 failing edit-op scenarios (12/15 pass). All three shared the B2 cluster: edit operations on existing nodes — delete, rename, and rename-existing. Each had a different root cause, all fixed in this session.

---

## Before vs After

| Scenario | Before | After |
|----------|--------|-------|
| `node_delete` | ❌ 1 error (remove_node not found), 0 nodes | ✅ 4/4 applied, 0 errors |
| `node_rename` | ❌ 1 error (rename_node not found), 0 nodes | ✅ 7/7 applied, 0 errors |
| `rename_existing` | ❌ 0/1 applied, Origin persisted, rename never executed | ✅ 1/1 applied, Origin→Renamed |

**Note:** `node_delete` has a net-zero scene change (create then delete in same batch). The scenario suite correctly reports PASS based on assertions (`node_not_exists` + `no_errors`), not scene changes. A temporary test script incorrectly used `(added or removed)` as the status check — this script has been deleted; the real `run_scenario` was never affected.

---

## Root Cause #1: Validator Ignores Same-Batch Pending Paths

### Affected: `node_delete`, `node_rename`

**Symptom:**
```
Op 3 (remove_node): node '/root/Main/ToDelete' not found
Op 6 (rename_node): node '/root/Main/OldName' not found
```

Both prompts say "create X then delete/rename it" — the deterministic pre-pass correctly injects `_remove`/`_rename` markers. The architecture compiler correctly emits `RemoveNodeStep`/`RenameNodeStep` with the right node paths (Bug 2.1 already fixed the ordering — entities are now processed before markers).

But the **validator** (`validator.py`) only checked the live scene:

```python
# _validate_remove_node (old):
if not scene.has_path(node):
    return False, f"node '{node}' not found"

# _validate_rename_node (old):
if not scene.has_path(node):
    return False, f"node '{node}' not found"
```

The node was just created by an `add_node` in the same batch — it exists in `pending` paths but NOT in the live scene. The validator rejected it → pipeline error → atomic batch rolls back → 0 nodes.

**Irony:** `_validate_add_node` already checks both `scene.has_path(parent)` AND `parent in pending`. The remove/rename validators simply forgot to check `pending`.

### Evidence (artifact capture)

```
node_delete:  applied=3/17 → only the 3 add_node ops before the remove_node
node_rename:  applied=0 → entire batch rolled back
```

### Fix

**File:** `devforge/compilation/pipeline/validator.py`

Added `node not in pending` to both validators:

```python
# _validate_remove_node (new):
if not scene.has_path(node) and node not in pending:
    return False, f"node '{node}' not found"

# _validate_rename_node (new):
if not scene.has_path(node) and node not in pending:
    return False, f"node '{node}' not found"
```

---

## Root Cause #2: Regex Captures Articles and Qualifiers

### Affected: `rename_existing`

**Symptom:** The deterministic pre-pass's `_RENAME_TO_RE` captured leading articles and trailing qualifiers as part of the target name. For "Rename the Origin node to Renamed." the old regex captured:
- `old = "the Origin node"` (includes article "the" and qualifier "node")
- `new = "Renamed."` (includes trailing period)

The `_resolve_node_target` token-matching did find the node, but the dirty name made the path resolution fragile.

### Old Regex

```python
_RENAME_TO_RE = _re.compile(
    r"(?:then|and)?\s*rename\s+(?:the\s+(?:node|entity)\s+)?(.+?)\s+to\s+(.+?)(?:$|[.,;])",
    _re.IGNORECASE,
)
```

The optional group `(?:the\s+(?:node|entity)\s+)?` required BOTH "the" and "node/entity" to appear together — for "the Origin node", "Origin" is neither "node" nor "entity", so the entire optional group was skipped. The non-greedy `(.+?)` then captured everything up to " to " — which included both "the" and "node".

### Fix

**File:** `devforge/compilation/pipeline/engine.py`

Made "the" and the "node/entity" qualifier independently optional, with the qualifier AFTER the capture group:

```python
_RENAME_TO_RE = _re.compile(
    r"(?:then|and)?\s*rename\s+(?:the\s+)?(.+?)(?:\s+(?:node|entity))?\s+to\s+(.+?)(?:$|[.,;])",
    _re.IGNORECASE,
)
```

Added post-processing strip for defense-in-depth:

```python
if old:
    old = _re.sub(r'^(?:the|a|an)\s+', '', old, flags=_re.IGNORECASE)
    old = _re.sub(r'\s+(?:node|entity)$', '', old, flags=_re.IGNORECASE).strip()
```

---

## Root Cause #3: Planner Emits `_rename` Directly (Bypassing Pre-pass)

### Affected: `rename_existing`

**Symptom:** Even after Fix #2 (regex + strip), the arch_delta still showed `_rename={'from': 'the Origin node', 'to': 'Renamed.'}`. The new regex was correct, the strip was correct — but neither was ever invoked.

**Root cause:** The deterministic pre-pass only INJECTS `_rename` when the planner DOESN'T have one:

```python
if _rename_match and not arch_delta.get("_rename"):
    # ... inject clean _rename
```

For `rename_existing`, the LLM planner itself emitted `_rename` in its plan output with dirty names. The guard `not arch_delta.get("_rename")` was False → the entire injection block was skipped → the regex + strip were never applied.

The planner's `_rename` passed through unmodified: `{'from': 'the Origin node', 'to': 'Renamed.'}` → `rename_node node='/root/Main/Origin' new_name='Renamed.'` → executor received `new_name` with trailing period → godot-ai bridge rejected the rename silently → 0/1 applied.

### Fix

**File:** `devforge/compilation/pipeline/engine.py`

Added a unified `_clean_rename_target()` helper and in-place cleaning that runs regardless of whether the pre-pass injected a new `_rename`:

```python
def _clean_rename_target(name: str) -> str:
    """Strip leading articles, trailing qualifiers, and punctuation from
    a rename from/to name."""
    if not name:
        return ""
    name = name.strip()
    name = _re.sub(r'^(?:the|a|an)\s+', '', name, flags=_re.IGNORECASE)
    name = _re.sub(r'\s+(?:node|entity|object)$', '', name, flags=_re.IGNORECASE)
    name = _re.sub(r'[.,;:]+$', '', name)
    return name.strip()
```

In-place cleaning after the injection block:

```python
# Bug 2.3: clean the planner's _rename in-place when it emitted
# its own (dirty) _rename
if arch_delta.get("_rename") and isinstance(arch_delta["_rename"], dict):
    rn = arch_delta["_rename"]
    old_clean = _clean_rename_target(rn.get("from", ""))
    new_clean = _clean_rename_target(rn.get("to", ""))
    if old_clean != rn.get("from") or new_clean != rn.get("to"):
        rn["from"] = old_clean
        rn["to"] = new_clean
        logger.info("pipeline.engine",
            f"Cleaned planner _rename: '{rn.get('from')}'→'{old_clean}', "
            f"'{rn.get('to')}'→'{new_clean}'")
```

This handles all three cases:
1. **Planner emitted _rename, regex didn't match:** In-place clean fires
2. **Planner didn't emit _rename, regex matched:** Pre-pass injects clean _rename
3. **Both:** Pre-pass injects clean _rename (planner's is overwritten), in-place clean is a no-op

---

## Files Changed

| File | Change |
|------|--------|
| `engine.py` | Added `_clean_rename_target()` helper; tightened `_RENAME_TO_RE` regex; in-place cleaning of planner-emitted `_rename`; unified name stripping |
| `validator.py` | `_validate_remove_node` + `_validate_rename_node` now check `pending` paths |

---

## Diagnostic Trail

1. Read scenario scorecards → all three edit scenarios failing with `coverage: None`
2. Ran `node_delete` live with artifact capture → `Op 3 (remove_node): node not found` error from validator
3. Traced `_validate_remove_node` → only checks `scene.has_path()`, not `pending`
4. Applied fix → `node_delete` + `node_rename` pass (4/4 and 7/7 applied)
5. `rename_existing` still at 0/1 — ran with artifact capture → `_rename={'from': 'the Origin node', 'to': 'Renamed.'}` still present
6. Debugged regex cache issue (stale .pyc, killed+restarted process, cleared all caches)
7. Realized regex+strip were correct on disk but `not arch_delta.get("_rename")` guard skipped them
8. Confirmed: LLM planner emits `_rename` directly — pre-pass never fires for this case
9. Added in-place cleaning → `rename_existing` passes (1/1 applied, Origin→Renamed)

---

## Lessons

1. **Validator parity:** When adding a new check to one validator method (e.g. `pending` in `_validate_add_node`), check ALL sibling validators that reference the same data.
2. **Planner output can bypass deterministic fixes:** Any guard condition that skips post-processing based on planner output (`not arch_delta.get("_rename")`) must also handle the case where the planner's output is dirty.
3. **Python bytecode caching is real:** `.pyc` files in `__pycache__` survive service restarts. When a hot-reload doesn't pick up a code change, delete the `__pycache__` and kill the process completely.
