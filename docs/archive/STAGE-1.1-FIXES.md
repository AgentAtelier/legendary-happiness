# Stage 1.1 — fix-list (review of the Phase 2 & 3 work)

Read `STAGE-1-HANDOFF.md` §0 first — the **vanilla Odysseus/godot-ai** rule and
the verify-with-evidence rule still apply to every item here. Do these before /
alongside Stage 2.

## What already works (do not touch)
2a busy banner + `/api/job/active`; 2b Quick Health; 2d Build/Write `/api/mode`;
3c MCP-reconnect in `_job_runner`; 3d `/api/persona/check` + `/api/persona/restore`;
`--reasoning-budget 1024` in `stack.env` (the `llama.caps` bench test passes now,
verified). gemma-26b-MoE is a genuine VRAM limit — correctly `untested`.

## Bugs to fix (priority order)

### F1 — `/api/odysseus/embedding-fix` is built on a false premise  ★ decide first
Evidence: `app.db` has **no `embedding_endpoints` table** (the query throws
"no such table"); the real table is `model_endpoints`, which holds only the chat
endpoint `http://host.docker.internal:8002/v1` — already `http://`-prefixed.
There is **no protocol-less URL to fix**. The embedding lane falls back to
FastEmbed because **no embedding endpoint is configured at all**, which is the
default and is acceptable (FastEmbed works locally; retrieval functions).
**Fix:** drop the "fix" framing. Either (a) replace the endpoint with a
read-only `/api/odysseus/embedding-status` that reports the configured lane and
says "FastEmbed (local) — OK" when no remote endpoint exists, or (b) if you want
a remote embedding lane, INSERT a proper `model_endpoints` row
(`endpoint_kind='embedding'`, a real `http://` URL) — but only if the user wants
that. Default recommendation: (a) + document that FastEmbed is fine.
*Acceptance:* the endpoint never errors; it accurately reports the embedding lane.

### F2 — `/api/odysseus/warmup` gets 401 (never warms the index)
Evidence: `POST http://127.0.0.1:7000/api/chat` returns **401** (auth required),
and `api_tokens` is empty — so the warmup chat is rejected and the tool index
stays cold. **Fix:** authenticate the warmup call. Investigate Odysseus's auth
(read-only — do NOT patch Odysseus): is there a localhost/session bypass, a
header, or a token you can mint via its own API/CLI? If warmup can't be
authenticated cleanly, fall back to a documented manual step ("send one agent
chat after a (re)start") and make the button instead OPEN the chat UI + show the
instruction, rather than silently 401.
*Acceptance:* after warmup (or the documented step), `bench.py --probe --layer
odysseus` shows `odysseus.retrieval = works`. Evidence required.

### F3 — dead `ACTIONS["warmup"]`
`hub.py` line ~84 registers `"warmup": [STACK, "warmup"]`, but `stack` has no
`warmup` subcommand (verified). It's unused by the real endpoint. **Remove the
ACTIONS entry** (and its `# Phase 3a` comment) to avoid a 127 "not found" if any
button ever calls `/api/run {action:"warmup"}`.

### F4 — mode toggle leaves the tool index cold (enhancement)
`/api/mode` restarts Odysseus (correct, for persona + MCP), which drops the warm
index. After the restart step, call the (F2-fixed) warmup so retrieval is hot
once the toggle finishes. *Acceptance:* after a Build/Write toggle, retrieval is
`works` without a manual chat.

### F5 — `/api/persona/restore` KeyErrors if `custom` is missing
Line ~1250 does `presets["custom"]["enabled"] = True` directly. `/api/mode`
guards this (`if "custom" not in presets`), but restore does not. **Fix:**
`presets.setdefault("custom", {})` before assigning, so a wiped presets.json can
be fully reconstructed from the vault. *Acceptance:* restore works even when
`custom` was deleted.

## Verification for Stage 1.1 done
- `embedding-status`/`embedding-fix` never errors; reports the real lane.
- `odysseus.retrieval` probe = `works` after warmup (or documented step) AND
  after a Build/Write toggle.
- `pytest tests/ -q` still 133 pass; hub restarts clean; no Odysseus/godot-ai
  source modified (`find ~/dev/ai/odysseus/src ~/dev/games/rpg/addons/godot_ai
  -newermt <today>` is empty).
