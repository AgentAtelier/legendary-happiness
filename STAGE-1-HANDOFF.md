# Stage 1 Handoff — Forge AI⇄Godot toolchain

Audience: a fresh CLI coding agent with **no prior context**. Read this whole
file before touching anything. Companion docs in this repo: `ROADMAP.md`,
`hub/MODEL-WORKFLOW.md`, `hub/README.md`, `hub/CHAIN-PROBES-DESIGN.md`.

---

## 0. HARD CONSTRAINTS — read first, never violate

1. **Odysseus and godot-ai stay VANILLA.** Do **not** edit source under:
   - `~/dev/ai/odysseus/**` (except *data/config* files — see below)
   - `~/dev/games/rpg/addons/godot_ai/**` (the Godot editor plugin)
   These are upstream projects we must be able to update. ALL adaptation goes
   through the surfaces we own:
   - **DevForge** — `~/dev/games/Forge/devforge_review_package/devforge/**`
   - **The hub** — `~/dev/games/Forge/hub/**`
   - **stack config** — `~/.config/forge-stack/stack.env` (via the `forge-model`
     and `stack` CLIs; `stack.env` is the single source of truth)
   - **Odysseus *config only*** — `~/dev/ai/odysseus/data/presets.json` and
     `data/app.db` are runtime config, safe to change. Source code is not.
   If a fix seems to need an Odysseus/godot-ai source change, STOP and solve it
   via config or orchestration (hub/stack) instead.
2. **Verify with evidence.** Run the relevant test suite / probe / shootout
   after every change and paste the output. Never claim "done" without it.
3. **Branch before committing.** Do not commit to the default branch. Do not put
   the human's personal email in git history; commits use the `AgentAtelier`
   identity if one is configured.
4. **DevForge bakes prompt template + grammar + context budget at startup** —
   after ANY change to those, `systemctl --user restart forge-devforge.service`
   and re-run the deep probe.

---

## 1. What this system is (orientation)

A local AI→Godot pipeline. Natural-language → a built Godot scene.

```
Odysseus chat UI (:7000, docker)         ← product/chat front-end (VANILLA)
      │  (MCP)
DevForge MCP (:8001)                      ← OUR pipeline (editable)
  apply_spec: prompt → architecture planner (LLM, GBNF-constrained)
              → compiler → validator → completeness → executor
      │  (MCP)
godot-ai MCP (:8000)  ── adopted by ──▶  Godot editor (live scene)  (VANILLA)
llama.cpp server (:8002)                  ← one shared local LLM
forge-hub (:8003, 127.0.0.1 only)         ← ops panel + benchmark (editable)
```

**One shared llama = one model at a time.** Swap per task:
- **Build / agent work →** `qwen3-14b-q6-k` (template `chatml`). Reliable
  grammar-constrained planning + native tool calls.
- **Prose / chat →** `merged-22b-q4-k-m` (Cydonia, also `chatml`). Great prose,
  weak/slow for planning.
Swap: `forge-model apply <fragment> && systemctl --user restart forge-llama.service`
(then restart `forge-devforge` if the template changed). See `MODEL-WORKFLOW.md`.

---

## 2. How to operate

```sh
# lifecycle
stack up            # bring the whole chain up (llama+devforge+godot-ai+odysseus)
stack status        # quick state ;  stack doctor  = deep verify
systemctl --user restart forge-{llama,devforge,godot-ai,hub}.service

# tests (keep these green)
cd ~/dev/games/Forge/devforge_review_package && .venv/bin/python -m pytest devforge/tests/ -q   # baseline 318 pass
cd ~/dev/games/Forge/hub                       && .venv/bin/python -m pytest tests/ -q            # baseline 133 pass

# benchmark (all from ~/dev/games/Forge/hub, using its .venv)
.venv/bin/python bench.py --probe              # deep chain probe (~2min on qwen3); data/bench/probe-*.json
.venv/bin/python bench.py --probe --layer llama
.venv/bin/python shootout.py --all             # 5-model sweep (~10min); data/shootouts/shootout-*.json
.venv/bin/python shootout.py --model qwen3      # one model

# Odysseus config change → must restart the container (config read at startup)
docker restart odysseus-odysseus-1
```

The hub serves the UI at http://127.0.0.1:8003 (Bench tab has "Deep Probe" +
"Shootout"). POST endpoints require header `x-forge-hub: 1`.

---

## 3. Current state (Stage 1, Phase 1 = DONE)

Latest verified shootout (`data/shootouts/shootout-20260614-034734.json`):
4/5 models genuinely tested — qwen3 **68/100**, gemma-12b 64, obliterated 64,
Cydonia 61; gemma-26b-MoE correctly `untested` (a real swap/VRAM limit, not a 0).
Deep probe all `works` except `runtime.launch` (`degraded` — editor FPS-monitor
quirk, not a real failure).

### Phase 1 — DONE (reference; do not redo). Files changed:
- `hub/shootout.py` — swap uses each model's **real** `forge-model` alias (the
  hardcoded `…-qat-ud-…` aliases had drifted and made 4/5 swaps fail in <1s and
  report fake 0s); swap failure → `untested` status (excluded from rankings);
  runtime phase polls FPS/`game_capture_ready`; runtime script checks read the
  artifact's **generated `.gd` content** instead of hardcoded `res://` paths.
- `hub/static/index.html` — terminals scroll (overflow), probe-card overlap
  fixed, untested models rendered separately.
- (Earlier capability fixes already in DevForge, context for you: grammar
  wiring in `platform/mcp_server.py`, context-budget cap in
  `compilation/pipeline/context_assembler.py`, planner-nesting prompt +
  compiler parent/attach-path in `compilation/pipeline/architecture_*.py`.)

### Known residuals to clean up as you start:
- **gemma-26b-MoE won't swap** ("tight @8k, 14.5 GiB"). Likely a real VRAM /
  health-timeout limit, not the alias bug. Investigate `forge_ops.swap_model`
  pre-flight + the `_wait_for_healthy` timeout; either make it fit (smaller ctx)
  or confirm it's a legitimate VRAM exclusion and document it.
- **`llama.caps` bench fail** — `LLAMA_BASE_ARGS` is missing `--reasoning-budget`
  (a runaway guard). Add it back in `stack.env` `LLAMA_BASE_ARGS` (then
  `forge-model apply <current> && stack restart llama`). Small, safe.

---

## 4. Phase 2 — Fast iteration + the two-model problem (TODO)

Goal: tighten the loop so capability work (Stage 2) is measurable in seconds.

- **2a — Non-blocking UI / job-lock.** The hub runs one mutating job at a time
  (`hub.py` `_job_lock`; a 2nd run returns HTTP 409). A 10-min shootout silently
  blocks the probe/bench. Make the UI show a clear "run in progress: <label>"
  banner and disable run buttons while busy (poll a `/api/job/active` you add, or
  reuse existing job state). *Acceptance:* starting a 2nd run shows a banner, not
  a console error. Files: `hub/hub.py`, `hub/static/index.html`.
- **2b — Quick chain health (<10s).** A "fast probes" bundle already exists
  (`bench.PROBE_BUNDLES["fast probes"]`: no-LLM/fast checks). Add a one-click
  "Quick health" button that runs it and shows the verdict rollup. *Acceptance:*
  returns < 10s with works/degraded/broken per layer.
- **2c — Planner latency.** qwen3 `apply_spec` varies 14–120s. Investigate: cold
  plan cache + large context + grammar. Try warming the cache, trimming context
  for short prompts, or capping planner `n_predict`. *Acceptance:* median
  apply_spec on the probe prompt < 30s on qwen3 (measure via `devforge.plan`
  probe's `apply_ms`). DevForge code only.
- **2d — One-click model mode.** Add a hub toggle "Build (qwen3)" / "Write
  (Cydonia)" that runs `forge-model apply` + restarts llama (+ devforge if
  template changed) + sets the Odysseus persona temperature (0.2 build / ~1.0
  write) by editing `presets.json` and restarting the container. *Acceptance:*
  one click puts the whole stack in the right mode. (Dual-serving two llama
  instances is out — 16 GB VRAM can't hold both. The toggle is the answer.)
  **No Odysseus/godot-ai source edits** — persona temp is `presets.json` config.

---

## 5. Phase 3 — Odysseus integration hardening (TODO — CONFIG/ORCHESTRATION ONLY)

Goal: the chat→build path is reliable. Odysseus stays vanilla; every fix is
config in `~/dev/ai/odysseus/data/**` or orchestration in the hub/stack.

- **3a — Tool-index warmup.** MCP tools (`apply_spec`, godot-ai) enter Odysseus's
  Chroma index only on the **first agent chat** after a restart
  (`odysseus/src/agent_loop.py:~1792` `index_mcp_tools` needs the live
  `mcp_mgr`). We can't patch that. Operational fix: after the container + MCP
  servers are up, have the hub/stack POST one trivial agent-mode chat to
  Odysseus's chat API to warm the index. (Read Odysseus's API to learn the
  endpoint — read-only; do not modify it.) *Acceptance:* the `odysseus.retrieval`
  probe is `works` right after a `stack up`, with no manual chat.
- **3b — Embedding endpoint.** The custom embedding lane falls back to FastEmbed
  because the configured endpoint URL lacks `http://` ("Request URL is missing
  an 'http://' or 'https://' protocol"). Fix the URL in Odysseus **config**
  (`data/app.db` model/endpoint settings or its settings file) — not source.
  *Acceptance:* no FastEmbed-fallback warning, or a documented decision that
  FastEmbed is acceptable.
- **3c — MCP reconnect ordering.** Odysseus connects to MCP servers only at
  container start (no auto-reconnect). If DevForge/godot-ai restart, Odysseus
  loses them. Fix in the hub/stack: when restarting DevForge or godot-ai, also
  restart `odysseus-odysseus-1` afterward (or surface a "reconnect needed"
  warning in the hub health sidebar). *Acceptance:* the chain self-heals or
  clearly warns. The bench test `t_ody_mcp` already detects the disconnected
  state — wire off it.
- **3d — Persona anti-clobber.** `presets.json` `custom` is the live persona;
  any Odysseus UI save clobbers it. Source of truth is
  `~/Obsidian Vault/odysseus-godot-persona.md`. Add a hub/stack command
  "restore persona from vault" + a drift warning (the bench `t_ody_persona`
  test already encodes the invariants — `inject_suffix` must contain "MCP" and
  "/no_think", temp ≤0.35 for agent use, system_prompt ~3.9k chars).
  *Acceptance:* one command restores it; drift is surfaced.

---

## 6. "Stage 1 complete" acceptance

- Shootout tests every model that physically fits; `untested` only for genuine
  VRAM/health limits; scores reflect what was actually built.
- A <10s quick-health check and a UI that never silently blocks.
- One-click Build/Write model-mode switch (model + template + persona temp).
- Odysseus retrieval `works` after a cold `stack up`; persona drift guarded;
  MCP reconnect handled; embedding lane decision made.
- `pytest` green: 318 DevForge, ≥133 hub. Deep probe all `works` except the
  known `runtime.launch` FPS quirk.

## 7. Definition-of-done checklist per task
- [ ] Change is in DevForge / hub / stack.env / Odysseus-config only (NOT
      Odysseus or godot-ai source).
- [ ] Relevant tests pass (paste output).
- [ ] If DevForge prompt/template/grammar/context changed: restarted
      forge-devforge + re-ran `bench.py --probe`.
- [ ] Verified the acceptance criterion with a command + its output.
