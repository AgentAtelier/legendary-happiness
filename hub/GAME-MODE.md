# Game Mode — Free the box for Steam

A one-click toggle that stops GPU/CPU-heavy Forge services so Steam games (The Witcher, etc.) get the full machine back.

## TL;DR — Steam Launch Options

For each game in your library, set Launch Options to:

```
forge-gamemode on; %command%; forge-gamemode off
```

- `forge-gamemode on` runs before the game — frees ~14 GB VRAM (forge-llama) and stops the Godot editor + any running Hunyuan/bake drainers.
- `%command%` is your game's executable.
- `forge-gamemode off` runs after you close the game — restarts forge-llama and forge-godot.
- `;` (not `&&`) means the game still launches if the toggle hiccups, and `off` still runs even if launch errored.

## What stops when you "Enter Game Mode"

User-confirmed stop list (aggressive — see commit log 2026-06-23):

| Service / process                              | Stopped?   | Why                                                    |
|------------------------------------------------|------------|--------------------------------------------------------|
| `forge-llama.service`                          | **yes**    | **Frees the ~14 GB VRAM that holds the current model** (the load-bearing reason this feature exists) |
| `forge-godot.service` (Godot Editor)           | **yes**    | Editor holds MCP connections that need llama alive; MCPs reconnect automatically when llama comes back |
| `asset_server.py` (Hunyuan spike drainer)      | yes (if running) | Spike-side `--swap-llama` task; only killed if it was active |
| `python -m lighting_prebake`                   | yes (if running) | Only killed if a bake drain was active |
| `forge-hub.service`                            | **no**     | Must stay up so the resume call can be heard by something localhost-reachable |
| `forge-devforge.service`                       | **no**     | CPU-heavy only; MCP clients that were talking to llama just reconnect when llama comes back |
| `forge-godot-ai.service`                       | **no**     | CPU-heavy only; same reason as devforge |
| `odysseus-odysseus-1` (docker container)       | **no**     | Lots of cached state (persona, history); cheaper to leave it warm than restart it |

If a systemd stop fails, Game Mode aborts cleanly: no state file is written, and a later `resume` is a no-op (so a Steam launch that already failed the toggle won't claim llama is "stopped" when it isn't). Always fix the service first, re-run Game Mode.

If a `pkill` (script kill) returns exit code 0 or 1 it's fine — those mean "killed something" or "no match." Exit code ≥ 2 means the pattern itself is broken and we surface a warning but don't block (the script was never load-bearing for VRAM).

## What resume does NOT auto-restart

The two ad-hoc Python scripts (`asset_server.py`, `lighting_prebake`) are **NOT** auto-restarted on resume. The user picked this explicitly so a Steam crash or laptop sleep during gaming doesn't spawn zombie background processes. Start them by hand if you want them back:

```bash
# Hunyuan overnight drain (only if you queued jobs today)
cd /home/mrg/dev/hunyuan-spike/Hunyuan3D-Omni
nohup .venv/bin/python asset_server.py --swap-llama --max 1 &

# Lighting pre-bake (idle-time drain)
cd /home/mrg/dev/games/Forge/foundry
.venv/bin/python -m lighting_prebake    # one-shot, exits when queue empty
```

## How to toggle

### From the hub UI

Open <http://127.0.0.1:8003> → Overview → 🎮 Game Mode button.

The button's label and color reflect state:
- Idle: `🎮 Game Mode` (default look) — click → "Enter Game Mode?" → POSTs `mode=game`.
- Active: `⏵ Resume Stack` (green) — click → "Resume the Forge stack?" → POSTs `mode=resume`.

The chip row in the header shows `🎮 GAME` (amber/warn) while active — important because the regular service chips (`godot`, `llama`) will show `inactive` on purpose. The `🎮 GAME` chip tells you it's by design.

### From the CLI

```bash
forge-gamemode on      # free the machine, aim ~10–30s depending on what was running
forge-gamemode off     # restore the stack, aim ~10–30s for llama to reach /health
```

The script first does a quick `<3s` reachability check via `/api/version`. Override the hub URL with `FORGE_HUB_URL` (default: `http://127.0.0.1:8003`). For SSH-from-laptop usage, set `FORGE_HUB_URL=http://127.0.0.1:8003` after `ssh -L 8003:127.0.0.1:8003`.

### From the hub endpoint

```bash
curl -X POST -H "Content-Type: application/json" -H "x-forge-hub: 1" \
  -d '{"mode":"game"}' http://127.0.0.1:8003/api/mode
# {"job":"<12-char-hex>"}
# then poll /api/job/active or stream /api/stream/{job_id}
```

The same endpoint also accepts `mode=build` and `mode=write` for the existing Build/Write persona toggle (qwen3-14b vs. Cydonia-22B).

## Idempotency + race conditions

- `mode=game` called twice in a row — second call returns immediately with "Already in game mode" and exit 0.
- `mode=resume` called when stack is normal — returns immediately with "Stack is normal" and exit 0.
- During a Steam session, if the hub restarts, the persistent state file at `~/.local/state/forge_gamemode.json` is the source of truth — `resume` still works.
- A Steam crash mid-session is safe — the next `forge-gamemode off` (your launch line) runs `mode=resume`; if state file is intact, it restarts llama+godot; if it's gone, it's a no-op.

## Files

- `hub/hub.py` — `/api/mode` handler + state helpers (`_gamemode_load/active/set/clear`)
- `hub/static/index.html` — 🎮 Game Mode button + state-aware label + `🎮 GAME` chip
- `~/.local/bin/forge-gamemode` — CLI wrapper (chmod +x, in PATH)
- `~/.local/state/forge_gamemode.json` — persisted state (auto-written on game, auto-cleared on resume)

State file format:
```json
{
  "active": true,
  "entered_at": "2026-06-23 14:32:18",
  "stopped_services": ["forge-llama.service", "forge-godot.service"],
  "stopped_scripts": ["asset_server.py", "foundry/lighting_prebake.py"]
}
```
