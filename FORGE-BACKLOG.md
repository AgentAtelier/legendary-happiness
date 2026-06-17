# Forge — Backlog & Delegation Index

The single map of what's left. Each item says **what**, **where the detail
lives**, **acceptance**, and **priority**. All work obeys the hard constraints in
`STAGE-1-HANDOFF.md` §0 — chiefly: **Odysseus and godot-ai stay vanilla source**;
adapt only DevForge, the hub, `stack.env`/`forge-model`, and Odysseus *config*.

## Status snapshot (June 14, 2026)
Done: Stage 1 (Phases 1–3 + Stage 1.1), Stage 2 (Phases 4–6), gruntwork +
diagnostics (Stream F), the Capability Gauntlet (extensible hub benchmark).
qwen3 shootout ~77–82/100; gauntlet structure/props **100%**, behavior the
ceiling. Pipeline today = a solid **scene builder**; the goal is a **game
builder** (open-world RPG + weather/day-night/terrain/quests/NPCs).

---

## P1 — Stage 2.1: Behavior reliability  → `STAGE-2.1-HANDOFF.md`
Make built scenes *do* something. The gauntlet found the exact gaps: **signals
never wire** (`connect_signal`=0), **scripts vanish under load**, **adversarial
input builds nothing + no error**. Plus the **ops-planner decision** (it A/B'd
14/100 vs arch 61 — fix or shelve). *Acceptance:* gauntlet `capability-v1` avg
≥95%; signals wire; scripts survive load; adversarial = partial+reject.

## P2 — Stage 3: Scene-builder → game-builder  → `CAPABILITIES-REPORT.md` Part 2–3
The pipeline generates only **7 op types**; godot-ai exposes **41+ tools across
11 domains** (particles, audio, animation, environments/sky, input maps,
autoloads, materials/shaders, navigation, …) that are **unreachable** through
DevForge's planner→compiler. This is the gap between "build a scene" and "build a
game." Each domain added = a new op type + GBNF rule + compiler mapping + planner
prompt + a gauntlet set to track it. **No Odysseus/godot-ai changes** — godot-ai
already exposes the tools.
- **Start: Phase A — weather vertical slice** (particles + audio + WorldEnvironment/
  sky + a day-night autoload). Proves the "system generation" pattern end-to-end.
- Then Phase B (RPG foundations: NPCs, inventory, dialogue, save) and Phase C
  (open world: terrain, streaming, navigation) — sequenced in the report.
*Acceptance per domain:* a gauntlet set exercising it hits ≥80% coverage; the
op type round-trips planner→compiler→executor→scene.

## P3 — Doc reconciliation & gauntlet upkeep
- **Docs are drifting.** `ROADMAP.md` still marks Stage 1 Phase 2/3 ⬜ though
  they're done. There are now ~11 overlapping docs (STAGE-1/1.1/2/2.1,
  CAPABILITIES, TEST-RESULTS, ROADMAP, HUB-AUDIT/FIX-PLAN, MODEL-WORKFLOW,
  CHAIN-PROBES). Reconcile statuses and add a one-screen **index** (this file can
  be it) so a newcomer isn't lost. *Acceptance:* ROADMAP accurate; one index that
  links the rest.
- **Gauntlet:** add `behavior-v1` (P1) and per-domain sets (P2); fix the probe
  scene's cosmetic `Main2` root (clean `Main` baseline). Detail in
  `STAGE-2.1-HANDOFF.md` T4.

## P4 — Residuals (low priority, mostly cosmetic)
- **gemma-26b-MoE** doesn't fit at default ctx (~15.5 GB on a 17.2 GB card).
  Optional: `forge-model set gemma-4-26b ctx=4096` to include it in shootouts.
- **`runtime.launch` FPS=0** is an editor monitor-capture quirk, not a failure —
  the probe already credits a clean launch (`degraded`, not `broke`). Leave it.
- **Odysseus tool-index warmup** can't auto-authenticate (no API token, chat API
  returns 401). The 🔥 button opens the chat UI with a one-chat instruction; the
  manual step is acceptable. Only revisit if auto-warmup becomes necessary.
- **`~/.config/forge-stack/stack.env` is a real file, not a stow symlink.** Live
  edits don't sync to `~/dotfiles`, and a future `stow -R forge-stack` could
  clobber live config. Re-stow cleanly sometime (back up the live file first).

---

## How to pick up any item
1. Read `STAGE-1-HANDOFF.md` §0–2 (constraints + how to run the stack/tests/probes).
2. Use **qwen3** for build/agent work (`forge-model apply qwen3 && stack restart
   llama`, or the hub ⚒ Build button).
3. Gate every change with the gauntlet (`python gauntlet.py --run <set>`) and/or
   the shootout — paste before/after numbers.
4. Keep 318 DevForge + ≥133 hub tests green; restart `forge-devforge` after any
   prompt/grammar/template/context change; confirm `llama.grammar` probe stays
   `works` (grammar not silently disabled).
