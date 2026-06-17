<!-- ARCHIVED — see ~/dev/games/Forge/FORGE-STACK.md for current documentation -->

# WO-003 — Error Triage (Phase A, capability #3)

**Read `00-EXECUTOR-BRIEFING.md` first.**
**Executor:** MiniMax M3. **DeepSeek steps:** knowledge-table review tag below.
**Est. effort:** 4–6h.
**Goal:** Godot's error log → parsed, classified, explained findings with
file/line and a concrete fix hint. Triage only — NO auto-fixing. No LLM
calls (tier 0); the knowledge table provides the explanations.

## Deliverables

1. New package `devforge/triage/` (`__init__.py`, `knowledge.py`, `triage.py`)
2. New public method `read_logs()` on `GodotAIMCPExecutor`
3. New MCP tool `triage_errors` in `mcp_server.py`
4. Test suite `devforge/tests/test_error_triage.py` (≥ 10 tests),
   registered in `scripts/run_all_tests.sh`

## Reuse, don't rebuild

`devforge/reasoning/ai/repair/error_parser.py` already parses raw Godot
output into structured errors:

```python
from devforge.reasoning.ai.repair.error_parser import ErrorParser, ParsedError
# ParsedError: file: str, line: int, message: str, error_type: str, symbol: str | None
errors = ErrorParser().parse_report_from_text(raw_log_text)
```

Your triage layer classifies each `ParsedError` against a knowledge table
and falls back gracefully for unrecognized messages.

## Knowledge table (`devforge/triage/knowledge.py`)

```python
@dataclass(frozen=True)
class KnownError:
    id: str            # "E01".."E20"
    pattern: str       # regex, matched (re.IGNORECASE) against ParsedError.message
    category: str      # "null_access" | "missing_member" | "type_error" | "parse_error" | "node_path" | "signal" | "physics" | "resource" | "other"
    explanation: str   # 1-2 sentences: what this means in Godot terms
    fix_hint: str      # 1 sentence: the usual fix

KNOWN_ERRORS: list[KnownError] = [...]  # ≥ 20 entries
```

Seed the table with at least these (write the regexes from the canonical
Godot 4 wording; keep them loose enough to survive minor version changes):

| id | matches messages like | category |
|---|---|---|
| E01 | `Invalid call. Nonexistent function 'X' in base 'Y'` | missing_member |
| E02 | `Invalid get index 'X' (on base: 'Nil')` / attempt to call function on a null instance | null_access |
| E03 | `Identifier "X" not declared in the current scope` | parse_error |
| E04 | `Cannot find member "X" in base "Y"` | missing_member |
| E05 | `Node not found: "X"` (get_node / NodePath failures) | node_path |
| E06 | `Signal "X" is already connected` | signal |
| E07 | `Invalid type in function 'X'... Cannot convert argument` | type_error |
| E08 | `Parse Error: Expected ...` | parse_error |
| E09 | `move_and_slide` / physics call outside `_physics_process` warnings | physics |
| E10 | `Cannot load resource` / `No loader found for resource` | resource |
| E11 | `Attempt to call function 'X' in base 'previously freed'` | null_access |
| E12 | `The function 'X()' returns a value, but this value is never used` | other |
| E13 | `Cyclic reference` / `Could not resolve class` | parse_error |
| E14 | `emit_signal: Signal "X" doesn't exist` | signal |
| E15 | `Division by zero` | type_error |
| E16 | `Out of bounds get index` | type_error |
| E17 | `setget`/`@onready` misuse (`Cannot assign ... onready`) | parse_error |
| E18 | `Viewport Texture must be set to use it` / black-screen camera issues | resource |
| E19 | `RID allocation leak` / `ObjectDB instances leaked at exit` | other |
| E20 | `Condition "!is_inside_tree()" is true` | node_path |

Every `explanation`/`fix_hint` must be specific ("the node path in
`get_node()` doesn't exist relative to this script's node — check the path
or use `%UniqueName`"), not generic ("there is an error").

## Triage engine (`devforge/triage/triage.py`)

```python
@dataclass
class TriagedError:
    file: str; line: int; raw_message: str
    category: str        # from the table, or "unrecognized"
    known_id: str | None # E01.. or None
    explanation: str     # table entry, or "Unrecognized — read the raw message" fallback
    fix_hint: str | None
    def to_dict(self) -> dict: ...

def triage_text(raw_log: str) -> dict:
    """parse → classify → dedupe (same file+line+known_id counted once,
    with an occurrence count) → return {"total_raw": N, "findings": [...],
    "by_category": {...}} sorted by (file, line)."""
```

First matching table entry wins; iterate the table in order.

## Executor method (`devforge/execution/godot_ai_mcp.py`)

Add a public `read_logs(self) -> str | None` mirroring the structure of the
existing `get_scene()` (circuit breaker via `self._run(...)`, returns None
on failure). Internally an async `_read_logs_async()` that calls
`self._call_tool_safe(session, name=self.TOOL_LOGS_READ, arguments={})` and
returns the parsed text (`self._parse_tool_result(...)`; if the result is a
dict, get `"text"` or `"logs"` key, else `str()` it). Add 1–2 mock-based
tests to `devforge/tests/test_godot_ai_mcp.py` following its existing
fixture (`mock_transport`).

## MCP tool (in `mcp_server.py`)

```python
@mcp.tool()
def triage_errors(log_text: str | None = None) -> Dict[str, Any]:
    """<docstring per house style. Read-only. If log_text is omitted, the
    tool pulls the live editor log via godot-ai logs_read; pass log_text
    explicitly to triage any log offline.>"""
```

Behavior: `_init()`; if `log_text is None`, call `_executor.read_logs()`
(if that returns None → `{"error": "no live editor log available; pass log_text"}`);
return `triage_text(...)` output plus `{"source": "live" | "provided"}`.

## Tests (`devforge/tests/test_error_triage.py`)

Synthetic logs only. Minimum cases:

1. A log with `player.gd:42 - Invalid call. Nonexistent function 'move' in base 'Node3D'.` → one finding, category `missing_member`, known_id E01, file/line correct
2. Null-instance message → `null_access`
3. Unknown message → category `unrecognized`, explanation fallback, `fix_hint` None
4. Three identical errors → one finding with occurrence count 3
5. Two different files → two findings sorted by file then line
6. Empty log → `{"total_raw": 0, "findings": []}` (no crash)
7. `by_category` counts sum to the number of findings
8. Every `KNOWN_ERRORS` regex compiles (loop the table, `re.compile` each)
9. Every table entry has non-empty explanation and fix_hint
10. Table ids are unique

`[DEEPSEEK ≤25min]` Review the 20 regexes against real Godot 4 error
wording (from training knowledge): tighten any that would false-positive on
common log noise, loosen any that hard-code volatile parts (quotes,
specific class names). Log changed entries in WORKLOG.

## Acceptance checklist

- [ ] `.venv/bin/python devforge/tests/test_error_triage.py` → all pass
- [ ] `.venv/bin/python -m pytest devforge/tests/test_godot_ai_mcp.py -q` → all pass (incl. your new read_logs tests)
- [ ] `scripts/run_all_tests.sh` → "All test suites passed."
- [ ] `triage_errors` docstring shows the literal return JSON
- [ ] WORKLOG.md entry appended (incl. DeepSeek minutes)
