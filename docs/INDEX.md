# Documentation Index

The single entry point. If a doc isn't reachable from here, it's either local to
a service (see below) or it should be filed into `current/` or `archive/`.

**Rule:** location is status. `current/` = true now. `archive/` = history, kept
for context, not for execution. When a doc is superseded, move it to `archive/`.

---

## 🟢 Current — the project as it is now

### Orientation & planning
- [current/FORGE-STACK.md](current/FORGE-STACK.md) — the system map: how hub, engine, llama, and Godot connect
- [current/ROADMAP.md](current/ROADMAP.md) — what's next
- [current/FORGE-BACKLOG.md](current/FORGE-BACKLOG.md) — backlog
- [current/LAYER1-SURVEY-PROMPTS.md](current/LAYER1-SURVEY-PROMPTS.md) — the workspace-cleanup survey prompts (active)

### Generation engine
- [current/SPATIAL-GENERATION-ARCHITECTURE.md](current/SPATIAL-GENERATION-ARCHITECTURE.md) — the spatial engines and how generation is routed

### Testing (active rebuild)
- [current/TESTING-SYSTEM-DESIGN.md](current/TESTING-SYSTEM-DESIGN.md) — the unified testbench design
- [current/TESTBENCH-MIGRATION-HANDOFF.md](current/TESTBENCH-MIGRATION-HANDOFF.md) — open migration work (handoff to the other AI)
- [current/STRESS-TEST-SCENARIO.md](current/STRESS-TEST-SCENARIO.md) — full-system stress scenario

## 🗄️ Archive
Superseded plans, completed stage handoffs, old audits, and one-off results live
in [archive/](archive/). Git preserves full history; nothing is lost.

## 📐 Decisions (ADRs) — the "why"
- [decisions/001-monorepo-and-engine-rename.md](decisions/001-monorepo-and-engine-rename.md)
- [decisions/002-flat-layout-and-doc-structure.md](decisions/002-flat-layout-and-doc-structure.md)
- [decisions/003-approach-survey-and-world-state-gap.md](decisions/003-approach-survey-and-world-state-gap.md)

---

## Docs that live next to their code (not centralized, on purpose)
These stay local because they describe a specific service and travel with it:
- **`hub/docs/`** — hub session-changes, findings, roadmaps, audits, the testing-rework specs
- **`hub/README.md`** — how to run the hub
- **`engine/docs/archive/`** — the engine's own historical docs and work orders
- **`engine/README.md`**, `engine/CHANGES.md`, `engine/TUNING.md`, etc. — engine-local reference

## Maintenance habit
When a plan is finished or superseded, `git mv` it from `current/` to `archive/`
and update this index — ideally in the same commit as the code change it
describes. Keep `current/` lean (a handful of live docs).
