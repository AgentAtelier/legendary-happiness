# Forge-Hub — Clean Fix Plan

## What the hub is

7-tab ops panel at :8003. Overview | Bench | Models | Score | Config | Activity | Doc.
The Score tab is the only thing added this session. Everything else was pre-existing.

## Category A: Bugs that affect the WHOLE hub (not Score-related)

These are real, user-facing, and would exist regardless of Stream A.

| # | Bug | Severity | Tab affected |
|---|-----|----------|--------------|
| A1 | `setBusy()` disables tab navigation — user locked out during any job | High | ALL |
| A2 | Activity tab timestamps show NaN — `new Date(string * 1000)` type error | High | Activity |
| A3 | Models tab `vram_fatal` doesn't credit reclaim — shows false "not enough VRAM" | High | Models |
| A4 | Config diff uses `set()` comparison — can't see what actually changed | Medium | Config |
| A5 | No confirmation on destructive buttons (Stack down, Restart all) | Medium | Overview |
| A6 | Config save writes file before daemon-reload — no rollback on failure | Medium | Config |
| A7 | `/api/status` makes 6 sequential subprocess calls — slow (3-8s) | Medium | Overview |
| A8 | Swap triggered from Models tab runs silently if Overview tab isn't active | Medium | Models |
| A9 | Five different job runner implementations with duplicated error handling | Low | All |
| A10 | One global `_job_lock` blocks bench during swap, swap during doctor, etc. | Low | All |
| A11 | Doc tab has no error handling on fetch | Low | Doc |
| A12 | `configSave` error handler swallows actual errors (missing `await`) | Low | Config |

## Category B: Bugs specific to the Score tab (my additions)

| # | Bug | Severity |
|---|-----|----------|
| B1 | "Tool-call probes only" button always 400s — sends empty `ids` | Critical |
| B2 | `rendScoreTable` says "Re-render comparison if there is one" — dead code comment | Low |
| B3 | `showLatestScorecard()` fetches `/api/status` redundantly (doesn't use result) | Low |
| B4 | `/api/selfcheck` missing Score API fields | Low |

## Category C: What works fine and should stay

| Tab | What works |
|-----|-----------|
| Overview | Status chips, drift banner, reconcile, all stack/restart buttons, streaming terminal |
| Bench | Test table, run all/fast/bundle, history, saved bundles |
| Models | Model list, fit status display, per-model swap buttons, current alias display |
| Score | Scenario list, run scenarios, streaming output, scorecard persistence, side-by-side comparison, one-button score, history |
| Config | Load/save/restore, backup rotation, validation |
| Activity | Action history with classifications (except NaN timestamps) |
| Doc | Chain doc display |

## Fix Plan (ordered by impact)

### Phase 1 — Universal fixes (1-2 hours)

1. **Fix Activity timestamps (A2).** Store Unix epoch in `record_action()`, parse in JS.
2. **Fix `setBusy()` to not disable nav (A1).** Scope it to `.actions button, #modelBtn, #benchAll, #benchFast, #benchBundle, #benchHist, #scoreAll` etc — not nav buttons.
3. **Fix Models tab vram_fatal (A3).** Ship `available = free_vram + reclaim - RESERVE` from the server.
4. **Fix Models tab → Overview switching (A8).** When swap clicked from Models, switch to Overview tab so streaming output is visible.
5. **Add confirmation on destructive actions (A5).** `confirm()` on Stack down, Down --all, Restart all.

### Phase 2 — Score tab fixes (30 min)

6. **Fix tool-call probes button (B1).** Server: accept empty ids when run_tools=true. JS: send a sentinel or let server handle it.
7. **Remove dead code comment (B2).** One-line fix.
8. **Remove redundant status fetch (B3).** Use the cached alias from the 8-second refresh.

### Phase 3 — Code quality (1 hour)

9. **Speed up `/api/status` (A7).** Use `asyncio.gather` for the 6 independent subprocess calls.
10. **Consolidate job runners (A9).** Single `_run_job(job, coro)` helper used by all 5 endpoints.
11. **Fix config diff (A4).** Replace `set()` with `difflib.unified_diff`.
12. **Fix `configSave` error handler (A12).** Add missing `await`.

### What I will NOT do

- Remove or rewrite the Score tab — the functionality is correct, the bugs are shallow
- Touch DevForge files
- Remove scenarios.py, calibrate_vram.py, or the live tests
- Restore hub.py to a previous state

### Verification after each phase

- `pytest tests/ -q` — must stay 119 passed
- `curl http://127.0.0.1:8003/api/status` — must return valid JSON
- Activity tab — timestamps must show real times
- Models tab — vram_fatal must not show false warnings
