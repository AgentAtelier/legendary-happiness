# Forge-Hub UI Audit

**Date:** June 13, 2026 · **URL:** http://127.0.0.1:8003 · **Files audited:** `hub.py` (576 lines), `index.html` (565 lines), `forge_ops.py` (467 lines)

---

## 🔴 CRITICAL — Broken functionality

### 1. Swap is two competing code paths that diverge

| Path | Route | How it swaps |
|------|-------|-------------|
| Overview tab "Swap" button | `POST /api/swap` | Calls `swap_model()` from `forge_ops.py` directly — transactional, rollback, VRAM check, health poll, props verification |
| `POST /api/run {action: "model"}` | `POST /api/run` | Shells out to `stack model <fragment>` CLI — COMPLETELY DIFFERENT code path, no health poll, no props verification, no rollback |

These do NOT behave the same way. The `/api/run` path bypasses every safeguard in `forge_ops.py`. There is no button in the UI that uses this path for model swapping, but the endpoint exists and is callable. **Remove the `model` action from `/api/run` or route it through `swap_model()`.**

### 2. "Tool-call probes only" button ALWAYS fails with 400

**Repro:** Models tab → Score tab → click "Tool-call probes only"

**Root cause in `index.html`:**
```javascript
$('scoreTool').addEventListener('click', () =>
    runScore([], true, 'Tool-call probes'));  // empty ids array!
```
**Root cause in `hub.py`:**
```python
if not ids:
    raise HTTPException(400, "no scenarios selected")
```

The JS sends `ids: []` with `run_tools: true`. The server blocks it because `ids` is empty. **Fix:** either the server should accept empty ids when `run_tools` is true, or the JS should pass a sentinel.

### 3. Activity tab — timestamps are garbled

**Root cause in `index.html`:**
```javascript
const ts = a.ts ? new Date(a.ts * 1000).toISOString().slice(11,19) : '?';
```

`a.ts` is a string like `"2026-06-13 06:48:25"` (from `time.strftime` in `record_action()`). Multiplying a string by 1000 produces `NaN`. `new Date(NaN)` produces "Invalid Date". **Fix:** `a.ts` should either be a Unix epoch float, or the JS should parse the string with `new Date(a.ts)`.

---

## 🟠 HIGH — Swap flow is fragile and confusing

### 4. Models tab → Swap silently populates Overview tab and fires

When you click "Swap" on the Models tab, the JS does:
```javascript
$('modelArg').value = e.target.dataset.frag;  // populate Overview tab input
$('modelBtn').click();  // programmatically click Overview tab's Swap button
```

Problems:
- If the user is NOT on the Overview tab, they see nothing — the swap runs invisibly
- The streaming output goes to `$('term')` which is hidden if Overview tab isn't active
- `setBusy(true)` then disables ALL buttons on ALL tabs — user is locked out with no feedback
- **Fix:** when a Models tab swap is initiated, switch to the Overview tab automatically and scroll the term into view.

### 5. `setBusy()` disables tab navigation buttons

```javascript
function setBusy(b) {
    running = b;
    document.querySelectorAll('button').forEach(bt => bt.disabled = b);
}
```

This disables EVERY button including the nav tab buttons. During a swap/bench run, the user can't switch tabs to read docs, check config, or browse activity. **Fix:** only disable action buttons, not navigation.

### 6. `vram_fatal` in Models tab is wrong — doesn't credit reclaim

**In `hub.py` `api_models()`:**
```python
if need_gb > free_vram / GIB:
    m["vram_fatal"] = "Not enough free VRAM..."
```

This compares model need against CURRENT free VRAM. But `swap_model()` in `forge_ops.py` correctly credits back the current model's VRAM (reclaim). So the Models tab shows "⚠ Not enough free VRAM" even when the swap WOULD succeed because the old model gets unloaded. **Fix:** compute `available = free_vram + reclaim - RESERVE_BYTES` and compare against that.

### 7. No dry-run / preview for model swaps

The hub has no endpoint to show what WOULD happen if you swap. `forge_models.plan_apply()` already computes this (template change, context change, DevForge restart needed, fit status, env changes). **Fix:** expose `plan_apply()` via a `/api/models/plan?fragment=...` endpoint and show it in the Models tab as a hover tooltip or expandable row before the user commits.

---

## 🟡 MEDIUM — Architecture and UX issues

### 8. Five different job runner implementations

hub.py has five separate async runner functions with slightly different patterns:

| Endpoint | Runner |
|----------|--------|
| `/api/run` | `_job_runner(job, cmd)` — subprocess-based, iterates stdout |
| `/api/swap` | inline `_runner()` — calls `swap_model()` with emit callback |
| `/api/reconcile` | inline `_runner()` — calls `reconcile_model()` with emit callback |
| `/api/bench/run` | inline `_runner()` — calls `bench.run_tests()` with emit callback |
| `/api/scenarios/run` | inline `_runner()` — calls `scenarios.run_suite()` with emit callback |

Each duplicates the try/except pattern, `job["done"] = True`, `_job_lock.release()`. **Fix:** factor out a single `_run_with_emit(job, coro)` helper.

### 9. One global lock blocks everything

```python
_job_lock = asyncio.Lock()
```

All five endpoints share the same lock. A bench run blocks model swaps. A scenario run blocks stack doctor. A swap blocks reconcile. **Fix:** consider separate locks for read-heavy vs write-heavy operations, or at minimum separate locks for swap vs bench.

### 10. `/api/status` makes 6 sequential subprocess calls

Each `_run_capture()` call takes 1-5 seconds. The status endpoint runs sequentially:
1. `stack status` (subprocess)
2. `systemctl is-active forge-llama` (subprocess)
3. `systemctl is-active forge-devforge` (subprocess)
4. `systemctl is-active forge-godot-ai` (subprocess)
5. `systemctl is-active forge-godot` (subprocess)
6. `docker ps` (subprocess)

These are all independent and should use `asyncio.gather()`. Current response time is likely 3-8 seconds. Could be ~2 seconds.

### 11. Config save — no rollback on daemon-reload failure

`api_config_save()` writes the file first, THEN calls `systemctl daemon-reload`. If daemon-reload fails, the config is already on disk with no rollback. **Fix:** use a temp file + atomic rename, or write a backup BEFORE the write.

### 12. Config diff uses set comparison — loses line order

```python
old_lines = set(old_text.splitlines())
new_lines = set(text.splitlines())
diff_added = [l for l in new_lines - old_lines if l.strip() ...]
```

A set diff can't show which line changed to what, can't show removals, and fails on duplicate lines. **Fix:** use `difflib.unified_diff`.

### 13. Score tab selfcheck field is missing

`/api/selfcheck` lists expected API shapes for status, models, actions, version, config, bench_tests — but NOT scenarios or scorecards. If the Score tab APIs change, the frontend can't detect it.

### 14. `setBusy` applied to ALL buttons during stream completion

`streamJob()` calls `setBusy(false)` on completion. But:
```javascript
if (onDone) onDone();
setBusy(false);
```
`setBusy(false)` re-enables ALL buttons unconditionally, even if another job is still running. If two jobs were somehow running, the first one completing would re-enable everything. (Currently impossible due to global lock, but fragile.)

---

## 🟢 LOW — Cosmetic and minor issues

### 15. `.s-fail` and `.s-err` CSS classes are visually identical
Both use `color:var(--err)` (#e05050). Failed tests and errored tests look the same.

### 16. Score tab `showLatestScorecard()` fetches `/api/status` redundantly
The status is already refreshed every 8 seconds by `setInterval(refresh, 8000)`. The scorecard function re-fetches it and doesn't use the result.

### 17. Doc tab `loadDoc()` has no error handling
```javascript
async function loadDoc() { $('docpane').textContent = await (await api('/api/doc')).text(); }
```
If the fetch fails, the promise rejection is unhandled.

### 18. No confirmation dialog for destructive actions
"Stack down", "Down --all", and "Restart all" have no confirmation. A mis-click takes the whole stack offline.

### 19. `configSave` error handling swallows the actual error
```javascript
try {
    const err = await e.response?.json?.() || e.response;
```
`e.response.json()` returns a Promise — needs `await`. Currently it falls through to the second catch.

### 20. Score tab comparison input fields are tiny
The `cmpA` and `cmpB` inputs are `size="8"` which cuts off most model aliases. Should be `size="20"` or better.

### 21. `_job_runner` prunes old jobs but only when new jobs finish
The prune logic runs in `_job_runner.finally`, so stale job entries accumulate until the next job completes. If no jobs run for a while, memory grows.

---

## 📊 Summary

| Severity | Count | Key issues |
|----------|-------|-----------|
| 🔴 Critical | 3 | Broken tool-call button, garbled Activity timestamps, two swap code paths |
| 🟠 High | 4 | Silent Model-tab swap, global button disable, wrong VRAM fatal, no dry-run |
| 🟡 Medium | 7 | Five runner impls, global lock, sequential status, no config rollback, broken diff |
| 🟢 Low | 7 | CSS duplicates, redundant fetch, no error handling, no confirmations |

**Top 3 fixes to make first:**
1. Fix the "Tool-call probes only" button (empty ids → 400 error)
2. Fix Activity tab timestamp parsing (NaN → garbled display)
3. Swap flow: switch to Overview tab when triggered from Models tab, show progress
