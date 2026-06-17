# Hub ↔ Odysseus: Refresh Dependencies

_Compiled June 13, 2026 — live audit of all links in the chain._

## The Chain

```
Browser ──▶ Odysseus (docker :7000)
              │  agent mode + "Godot Developer" persona
              ├──MCP/http──▶ godot-ai (:8000) ──WS :9500──▶ Godot editor
              └──MCP/sse───▶ DevForge (:8001)
                               │ pipeline: planner → compiler → executor
                               ├──HTTP──▶ llama.cpp (:8002)
                               └──MCP/http──▶ godot-ai (:8000) ──▶ editor
```

```
Hub (:8003) — ops panel
  ├── systemctl restart forge-llama
  ├── systemctl restart forge-devforge   (conditional)
  └── docker restart odysseus-odysseus-1 (manual button only)
```

## What the Hub Restarts on Model Swap

| Action | Service | Always? |
|--------|---------|---------|
| Write new `MODEL`, `MODEL_ALIAS`, `DEVFORGE_PROMPT_TEMPLATE`, `LLAMA_ARGS` | stack.env | ✅ Always |
| Restart | `forge-llama.service` | ✅ Always |
| Restart | `forge-devforge.service` | ⚠️ Only if template or context size changed |
| Restart | `forge-godot-ai.service` | ❌ Never (model-agnostic WebSocket bridge) |
| Restart / notify | Odysseus (docker) | ❌ **Never — this is a gap** |

DevForge restart trigger (in `forge_models.py:plan_apply`):
- Template changed (e.g. `gemma` → `chatml`)
- Context size changed (e.g. 32768 → 16384)
- No previous `--ctx-size` found in `LLAMA_ARGS`

## What Odysseus Needs After a Model Change

### 1. Browser Tab Reload (TRAP #1)

> **"Persona injects are applied client-side — an open Odysseus browser tab
> keeps sending the OLD prefix/suffix until reloaded."**
> — forge-stack-chain.md

The persona prefix/suffix (including `/no_think`, temperature, tool flags)
are injected by the **browser** at request time. If the persona file
(`presets.json`) changes — whether from a UI save or manual edit — an
already-open tab won't pick it up. **This invalidated the first
apply_spec-strategy test on June 13.**

**Fix:** After any persona change or model swap, reload the Odysseus browser tab.

### 2. MCP Server Connection (TRAP #2)

> **"Odysseus connects to its MCP servers only at boot."**
> — forge-stack-chain.md

When `forge-devforge.service` restarts (new template/context), its MCP
port (:8001) stays the same, but the server process is a new instance.
Odysseus's MCP SSE connections to the old instance are dead. Odysseus
won't reconnect until the **container is restarted** or the **Odysseus
server process** inside the container reconnects.

**Current behavior:** The hub has an "↻ Odysseus" button (docker restart),
but it's manual. The swap flow does NOT trigger it.

### 3. "MCP" Keyword in Persona (TRAP #3)

> **"The word 'MCP' in the persona `inject_suffix` is load-bearing — if removed,
> tool retrieval defaults to a 3-tool cascade, disabling Godot-specific tools."**
> — forge-stack-chain.md

`_classify_agent_request()` in Odysseus uses keyword matching. The "MCP"
keyword matches the `settings` domain regex and flips `low_signal=False`,
keeping all tools active. If a persona UI save removes "MCP", godot-ai
tools silently disappear.

### 4. UI Persona Clobber (TRAP #4)

> **"The admin UI persona save button overwrites `presets.json` directly.
> After any UI save, diff the file against the source of truth."**
> — forge-stack-chain.md

The source of truth is `Obsidian Vault/odysseus-godot-persona.md`.
The hub does not have visibility into Odysseus's persona file.

### 5. Thinking-Mode Config Drift

The forge-stack-chain.md documents:
```
LLAMA_ARG_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}'
```
This disables the thinking phase for Gemma chat-template clients (Odysseus).
**This line is NOT in the current stack.env.** The doc also says
`--reasoning-budget` was removed from `LLAMA_BASE_ARGS`, but it's still
present in the current config. This is a config-documentation mismatch.

## Refresh Decision Matrix

| Event | Reload Odysseus tab? | Restart Odysseus container? | Restart DevForge? | Restart llama? |
|-------|---------------------|---------------------------|-------------------|----------------|
| Model swap (same arch) | ❌ Usually not needed | ❌ | ❌ (if template/ctx unchanged) | ✅ Auto |
| Model swap (different arch) | ✅ Template changed | ⚠️ May be needed | ✅ Auto | ✅ Auto |
| Context size changed | ❌ | ❌ | ✅ Auto | ✅ Auto |
| Persona edited (UI) | ✅ Must reload | ❌ | ❌ | ❌ |
| Persona edited (source .md) | ✅ Must reload | ❌ | ❌ | ❌ |
| MCP keyword removed | ✅ Must reload | ❌ | ❌ | ❌ |
| DevForge code changed | ❌ | ⚠️ May need reconnect | ✅ Manual | ❌ |
| Godot editor restarted | ❌ | ❌ | ❌ | ❌ |
| Hub code changed | ❌ (auto-detects via build ID) | ❌ | ❌ | ❌ |
| stack.env edited (Config tab) | ❌ | ❌ | ❌ | ❌ (until user restarts) |

## Hub Auto-Refresh Behavior

| Mechanism | What | Interval |
|-----------|------|----------|
| `setInterval(refresh, 8000)` | Service chips, drift banner, busy state | Every 8s |
| Tab switch → `loadModels()` | Model list + VRAM estimates | On tab click |
| Tab switch → `loadConfig()` | stack.env editor | On tab click |
| Tab switch → `loadActivity()` | Action log | On tab click |
| `versionCheck()` on load | Build ID mismatch → "Reload now" banner | Once on page load |

No manual browser refresh is needed for the hub — it polls. But the hub's
polling has no visibility into Odysseus's internal state (persona, MCP
connections, tool availability).

## Gaps Found

1. **Odysseus not restarted on model swap** — The swap flow knows when
   template/context changes (it already restarts DevForge), but doesn't
   restart Odysseus. If the persona references model-specific features
   (thinking mode, tool calling format), Odysseus keeps using the old model's
   assumptions.

2. **No post-swap Odysseus health check** — The hub verifies llama is up via
   `/health` and `/props`, but doesn't verify Odysseus can actually reach
   llama (Odysseus uses `host.docker.internal`, which can break after Docker
   network changes).

3. **Config-doc mismatch** — `LLAMA_ARG_CHAT_TEMPLATE_KWARGS` (disable
   thinking) is documented but not in stack.env. `--reasoning-budget` is
   documented as removed but still present.

4. **No Odysseus persona visibility** — The hub can't see or validate
   Odysseus's `presets.json`. If the MCP keyword is missing, the hub has
   no way to detect it.

5. **The "MCP" keyword trap has no automated guard** — If a future UI save
   removes "MCP" from the persona suffix, godot-ai tools silently stop
   working. The test bench has `odysseus.retrieval` to catch this, but it
   must be run manually.
