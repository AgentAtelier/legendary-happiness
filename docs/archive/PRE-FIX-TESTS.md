# Forge-Hub — Final Pre-Fix Test Results

**Date:** June 13, 2026 · **Hub status:** Running but STALE (started 05:39, code modified 05:54+)

---

## ✅ What I tested (with live results)

| Test | Result | Notes |
|------|--------|-------|
| Hub unit tests | **119 passed, 0 failed, 11 skipped** | Full `pytest tests/ -q` |
| Hub live tests | **9/10 passed, 1 skipped** | `pytest -m live -v` against real stack |
| `/api/status` | 200 — chips correct, all services active | |
| `/api/actions` | 200 — timestamps are STRINGS like `"2026-06-13 07:06:32"` | **CONFIRMS bug A2** — JS multiplies string by 1000 → NaN |
| `/api/models` | 200 — ALL 5 models show `vram_fatal` | **CONFIRMS bug A3** — doesn't credit reclaim |
| `/api/scenarios` | **404** — hub started before code was modified | **ROOT CAUSE: hub needs restart** |
| `/api/scorecards` | 200 — 0 scorecards (never run) | Works after hub restart |
| `/api/selfcheck` | 200 — missing `scenarios`/`scorecards` fields | **CONFIRMS bug B4** |
| `/api/config` | 200 — responds | |
| `/api/bench/tests` | 200 — 22 tests, 5 bundles | |
| `scenarios.py` direct import | Loads — 12 scenarios, 5 probes | Module is correct, just not registered |

---

## ❌ What I CANNOT test without a browser or code change

| Fix | What needs testing | Why can't test now |
|-----|-------------------|--------------------|
| **A1** setBusy scoping | Does setBusy(false) re-enable nav buttons after a job? | Needs browser — Chrome not installed |
| **A4** Config diff | Does difflib output render in the Config tab? | Needs browser |
| **A5** Confirmations | Does `confirm()` fire on Stack down / Restart all? | Needs browser |
| **A8** Models tab switching | Does clicking Swap on Models switch to Overview? | Needs browser |
| **B1** Tool-call probes | Does button work after server fix? | Needs hub restart first, then browser |
| **A7** Parallel status | Does `asyncio.gather` speed up /api/status? | Needs code change deployed |
| **A9** Runner consolidation | Do all 5 endpoints still work after refactor? | Needs code change deployed |
| **A12** Config save errors | Does error handler show actual message? | Needs code change + simulated failure |
| **A11** Doc tab errors | Does doc load handle fetch failure? | Needs simulated network failure |

---

## 🔗 How untestable items touch the fix plan

| Can't test | Blocks fix? | Workaround |
|------------|-------------|------------|
| A1 setBusy | Partially — can verify JS logic by inspection, can't verify visual | Unit test the JS button selector scope |
| A4 Config diff | Partially — difflib output is predictable | Unit test difflib output format |
| A5 Confirmations | No — confirm() is a browser builtin | Verify `onclick` attribute contains `confirm()` |
| A8 Tab switching | Partially — can verify JS logic | Unit test the tab-switching code path |
| B1 Tool-call probes | No — purely server-side + JS | `curl -X POST /api/scenarios/run -d '{"ids":[],"run_tools":true}'` after restart |
| A7 Parallel status | No — purely server-side | `time curl /api/status` before vs after |
| A9 Runners | No — unit tests cover all 5 endpoints indirectly | Server-side refactor, covered by existing tests |
| A12 Config save | Partially — can test server response | `curl -X POST /api/config -d '{"text":"bad"}'` to trigger validation |
| A11 Doc tab | No — purely JS | `.catch()` wrapping is visible in code review |

**No fix is blocked by the inability to use a browser.** All fixes are verifiable through either server-side curl testing or unit tests.

---

## 🔴 Critical finding: Hub is serving stale code

The hub was started at 05:39. hub.py was modified at 05:54, scenarios.py at 06:00. The `/api/scenarios` endpoint returns 404 because the running process predates the code. **The hub must be restarted before the Score tab can work.**

This means the Score tab has NEVER been tested live — all unit tests pass but the running server has never registered the routes.
