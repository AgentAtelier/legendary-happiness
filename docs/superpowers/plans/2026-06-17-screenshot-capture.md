# Framed Screenshot Capture — Implementation Plan

> **For agentic workers:** Execute task-by-task on a branch. Steps use checkbox
> (`- [ ]`) syntax. Self-contained; read referenced files for context.

**Goal:** Make `/api/screenshot` (and a reusable helper) return a **framed** PNG of
the built scene, so the owner can actually *see* what was generated — closing the
"empty viewport" gap. The human eye is the project's real judge (the surveys
rejected a VLM gate); this gives it eyes.

**Architecture:** `editor_screenshot` already supports framing
(`view_target`/`coverage`/`elevation`/`azimuth`/`fov` — confirmed live) and returns
the PNG in a *separate* MCP content block (`.data`) that the current code never
reads. A new `capture_screenshot()` helper in `hub/mcp_client.py` frames the editor
camera on the scene root and extracts that image block; the hub endpoint calls it.
Slice = the screenshot piece of `docs/current/NEXT-PHASE-RECONCILED-DIRECTION.md`.

**Tech Stack:** Python 3.12, FastAPI, pytest, ruff, MCP. **Hub-side** change — the
endpoint runs in `forge-hub`, so restart THAT service (not devforge).

## Global Constraints

- **Branch only.** `git checkout main && git checkout -b feat/screenshot-capture`.
  NEVER commit to `main`; NEVER merge. Push + report.
- **`scripts/check.sh` GREEN** after every task. New files ≤ 500 lines.
- **Hub imports are BARE** (the hub runs with `hub/` on `sys.path`):
  `from mcp_client import capture_screenshot`, never `from hub.mcp_client import`.
- **Commit after each task.** If an expected result doesn't occur, **STOP and report.**
- **Tooling:** ruff = `hub/.venv/bin/ruff`. Hub tests: `cd hub &&
  .venv/bin/python -m pytest tests/<f>.py -v`. The Godot editor must be open on
  `res://probe.tscn` (readiness `ready`) for the live task.
- **Confirmed-working framing recipe** (verified live; use exactly these):
  `editor_screenshot(source="viewport", include_image=True, coverage=True,
  view_target=<scene root path>, elevation=25, azimuth=35, fov=50,
  max_resolution=1100)`.

---

### Task 1: Image-extraction helper + framed capture in `mcp_client`

**Files:**
- Modify: `hub/mcp_client.py` (add two functions at the end of the godot-ai section).
- Test: `hub/tests/test_mcp_client.py`

**Interfaces:**
- Produces:
  - `_extract_image_b64(content) -> str | None` — returns the first content block's
    `.data` (the base64 PNG), else None.
  - `capture_screenshot(*, view_target=None, elevation=25, azimuth=35, fov=50,
    max_resolution=1100) -> dict` — frames + captures; returns
    `{"image": <b64>, "format": "png", "width": int, "height": int,
    "view_target": str}` or `{"error": str}`.

- [ ] **Step 1: Write the failing test** at `hub/tests/test_mcp_client.py`:

```python
from mcp_client import _extract_image_b64


class _Block:
    def __init__(self, text=None, data=None):
        if text is not None:
            self.text = text
        if data is not None:
            self.data = data


def test_extract_image_from_image_block():
    content = [_Block(text='{"format":"png"}'), _Block(data="ABC123")]
    assert _extract_image_b64(content) == "ABC123"


def test_extract_image_none_when_absent():
    assert _extract_image_b64([_Block(text='{"format":"png"}')]) is None


def test_extract_image_empty_content():
    assert _extract_image_b64([]) is None
    assert _extract_image_b64(None) is None
```

- [ ] **Step 2: Run it to confirm it fails**

  Run: `cd hub && .venv/bin/python -m pytest tests/test_mcp_client.py -v`
  Expected: FAIL — `ImportError: cannot import name '_extract_image_b64'`.

- [ ] **Step 3: Add both functions** to the end of `hub/mcp_client.py` (after
  `godot_ai_call`):

```python
def _extract_image_b64(content) -> str | None:
    """Pull the base64 PNG out of an MCP tool result's content blocks.

    godot-ai returns the image as a SEPARATE block carrying ``.data`` — not in the
    text block — so the usual ``content[0].text`` parse misses it. Return the first
    block that carries image data, else None.
    """
    for block in content or []:
        data = getattr(block, "data", None)
        if data:
            return data
    return None


async def capture_screenshot(
    *,
    view_target: str | None = None,
    elevation: float = 25,
    azimuth: float = 35,
    fov: float = 50,
    max_resolution: int = 1100,
) -> dict:
    """Capture a FRAMED screenshot of the editor viewport, with the image.

    A bare editor_screenshot points wherever the user left the editor camera —
    usually empty. This frames the camera on the scene root so the built content
    is visible. Returns {"image": <b64 png>, "format", "width", "height",
    "view_target"} or {"error": ...}.
    """
    async with streamablehttp_client(GODOT_AI_URL) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            target = view_target
            if target is None:
                hier = await s.call_tool("scene_get_hierarchy", {"depth": 2})
                try:
                    data = _json.loads(hier.content[0].text)
                except Exception:
                    data = {}
                roots = [
                    n.get("path")
                    for n in data.get("nodes", [])
                    if isinstance(n, dict) and n.get("path", "").count("/") == 1
                ]
                target = roots[0] if roots else "/Main"
            res = await s.call_tool(
                "editor_screenshot",
                {
                    "source": "viewport",
                    "include_image": True,
                    "coverage": True,
                    "view_target": target,
                    "elevation": elevation,
                    "azimuth": azimuth,
                    "fov": fov,
                    "max_resolution": max_resolution,
                },
            )
            img = _extract_image_b64(res.content)
            if not img:
                return {"error": "godot-ai returned no image data"}
            meta = {}
            for block in res.content:
                text = getattr(block, "text", None)
                if text:
                    try:
                        meta = _json.loads(text)
                        break
                    except Exception:
                        pass
            return {
                "image": img,
                "format": meta.get("format", "png"),
                "width": meta.get("width"),
                "height": meta.get("height"),
                "view_target": target,
            }
```

- [ ] **Step 4: Run the test to confirm it passes**

  Run: `cd hub && .venv/bin/python -m pytest tests/test_mcp_client.py -v`
  Expected: PASS (3 passed).

- [ ] **Step 5: Lint + gate**

  Run: `hub/.venv/bin/ruff format hub/mcp_client.py hub/tests/test_mcp_client.py && hub/.venv/bin/ruff check hub/mcp_client.py hub/tests/test_mcp_client.py && bash scripts/check.sh`
  Expected: ruff clean; "All checks passed."

- [ ] **Step 6: Commit**

```bash
git add hub/mcp_client.py hub/tests/test_mcp_client.py
git commit -m "feat(hub): framed screenshot capture + image-block extraction in mcp_client"
```

---

### Task 2: Fix the `/api/screenshot` endpoint to frame

**Files:**
- Modify: `hub/hub.py` — replace the body of `api_screenshot` (at `@app.get("/api/screenshot")`).

**Interfaces:**
- Consumes: `capture_screenshot` from Task 1.

- [ ] **Step 1: Replace the endpoint body.** Find `@app.get("/api/screenshot")`
  and replace the whole function with:

```python
@app.get("/api/screenshot")
async def api_screenshot(source: str = "editor"):
    """Capture a FRAMED screenshot of the Godot editor viewport.

    Returns a base64 PNG (and a data_uri) of the built scene, with the editor
    camera framed on the scene so content is visible — answers "did it build?"
    without alt-tabbing to Godot. (``source`` is accepted for compatibility but the
    capture always frames the editor viewport.)
    """
    try:
        from mcp_client import capture_screenshot

        result = await capture_screenshot()
        img_b64 = result.get("image", "")
        if result.get("error") or not img_b64:
            return {"error": result.get("error", "godot-ai returned no image data")}
        fmt = result.get("format", "png")
        return {
            "image": img_b64,
            "format": fmt,
            "source": "viewport",
            "view_target": result.get("view_target"),
            "data_uri": f"data:image/{fmt};base64,{img_b64}",
        }
    except Exception as e:
        return {"error": f"screenshot failed: {type(e).__name__}: {e}"}
```

- [ ] **Step 2: Lint + gate + import-smoke**

  Run:
  ```bash
  hub/.venv/bin/ruff format hub/hub.py && hub/.venv/bin/ruff check hub/hub.py && bash scripts/check.sh
  cd hub && .venv/bin/python -c "import ast; ast.parse(open('hub.py').read()); print('hub.py parses OK')"; cd ..
  ```
  Expected: green; "hub.py parses OK".

- [ ] **Step 3: Commit**

```bash
git add hub/hub.py
git commit -m "fix(hub): /api/screenshot returns a framed PNG of the built scene"
```

---

### Task 3: Prove it live (the owner can see the scene)

- [ ] **Step 1: Restart the HUB** (this is a hub-side change).
  ```bash
  systemctl --user restart forge-hub.service && sleep 3
  systemctl --user is-active forge-hub.service   # expect: active
  ```

- [ ] **Step 2: Build a scene, then capture via the endpoint, and SAVE the PNG.**
  (Editor must be ready.)

```bash
cd hub && timeout 150 .venv/bin/python -c "
import asyncio, base64
from mcp_client import apply_spec, godot_ai_call
async def m():
    st = await godot_ai_call('editor_state', {})
    if st.get('readiness') != 'ready':
        print('editor not ready — STOP (env, not code)'); return
    r = await apply_spec('A cozy room: a wooden table, four chairs, a rug, a bookshelf, and a hanging lamp.')
    print('built:', {k: r.get(k) for k in ('applied','error_count')})
asyncio.run(m())
"; cd ..
# capture via the live endpoint and save the image to a file
curl -s http://127.0.0.1:8003/api/screenshot | python3 -c "
import sys, json, base64
d = json.load(sys.stdin)
if d.get('error'):
    print('ENDPOINT ERROR:', d['error']); sys.exit(1)
img = d['image']
open('/tmp/api_screenshot.png','wb').write(base64.b64decode(img))
print('saved /tmp/api_screenshot.png; base64 len =', len(img), 'view_target =', d.get('view_target'))
"
ls -la /tmp/api_screenshot.png
```
  Expected: a non-trivial base64 length (the old empty/broken path returned an
  error or tiny image); a saved `/tmp/api_screenshot.png`. If `ENDPOINT ERROR`,
  STOP and report.

- [ ] **Step 3: Owner-visible verification.** The PNG at `/tmp/api_screenshot.png`
  should show the framed scene (a room with content), NOT an empty grid. Write a
  one-line note plus the base64 length to `docs/reviews/screenshot/RESULT.md`, and
  state that the file is ready for the owner to open. (The owner opens the PNG to
  confirm framing — a machine can't judge "looks right".)

- [ ] **Step 4: Commit + push**

```bash
git add docs/reviews/screenshot/RESULT.md
git commit -m "docs: /api/screenshot framed-capture verified (non-empty PNG of built scene)"
git push -u origin feat/screenshot-capture
```

- [ ] **Step 5: Report** — branch name, the base64 length from Step 2, all gates
  passed, and that `/tmp/api_screenshot.png` awaits the owner's eyes. Do NOT merge.

---

## Self-Review
- **Spec coverage:** "frame the editor camera so `editor_screenshot source=viewport`
  shows the built scene." Task 1 (capture helper + image extraction, with the
  confirmed framing recipe), Task 2 (endpoint), Task 3 (live proof + owner view). ✓
- **Placeholder scan:** All code shown. ✓
- **Type consistency:** `capture_screenshot(...) -> dict` with `"image"`/`"error"`
  keys used consistently in helper, endpoint, and tests; `_extract_image_b64` same
  signature in module and test. ✓
- **Scope:** Owner-facing capture only. Wiring the helper into the testbench
  (`Context.capture_screenshot` + `Result.screenshot`, for the eventual VLM) is a
  small follow-on, not this plan.
