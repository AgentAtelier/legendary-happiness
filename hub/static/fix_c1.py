#!/usr/bin/env python3
"""Fix C1: make /api/tools/history use in-memory cache."""

PATH = "/home/mrg/dev/games/Forge/hub/hub.py"

with open(PATH) as f:
    content = f.read()

changes = 0

# 1. Add module-level tool-call cache near the _jobs dict
old_jobs = "_jobs: dict[str, dict] = {}"
new_jobs = '_jobs: dict[str, dict] = {}\n_tool_results: dict = {"probes": [], "summary": {}, "ts": ""}'
if old_jobs in content:
    content = content.replace(old_jobs, new_jobs)
    changes += 1
    print("Added _tool_results cache")

# 2. In the /api/tools/run _runner, store result in cache
# Find "job[\"tool_result\"] = result" and add cache save
old_store = 'job["tool_result"] = result'
new_store = 'job["tool_result"] = result\n            _tool_results.update({"probes": result.get("probes", []), "summary": result.get("summary", {}), "ts": time.strftime("%Y-%m-%d %H:%M:%S")})'
if old_store in content:
    content = content.replace(old_store, new_store)
    changes += 1
    print("Added cache save to /api/tools/run")

# 3. Replace /api/tools/history body to prefer in-memory cache
# Find the endpoint and replace its body
old_hist_search = '@app.get("/api/tools/history")'
idx = content.find(old_hist_search)
if idx >= 0:
    # Find the end of this function (next @app or end of file)
    next_app = content.find("\n@app.", idx + 1)
    if next_app < 0:
        next_app = len(content)

    new_body = '''@app.get("/api/tools/history")
async def api_tools_history():
    """Return the most recent tool-call probe result."""
    # Prefer in-memory cache (populated by standalone tools suite)
    if _tool_results.get("probes"):
        return _tool_results
    # Fallback: scan scorecards for tool_calls from full-depth scenario runs
    cards = scenarios.list_scorecards()
    for c in cards:
        fp = scenarios.SCORECARD_DIR / c["file"]
        try:
            d = json.loads(fp.read_text())
            if d.get("tool_calls"):
                tc = d["tool_calls"]
                return {"model": c["model"], "ts": c["ts"],
                        "probes": tc.get("probes", []),
                        "summary": tc.get("summary", {})}
        except Exception:
            continue
    return {"probes": [], "summary": {}, "hint": "Run the tools suite or a scenario suite with full depth"}'''

    content = content[:idx] + new_body + content[next_app:]
    changes += 1
    print("Replaced /api/tools/history body")
else:
    print("WARNING: /api/tools/history not found")

with open(PATH, "w") as f:
    f.write(content)

print(f"Done: {changes} changes applied")
