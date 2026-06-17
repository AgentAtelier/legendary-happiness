# Documentation Index

The single entry point. If a doc isn't reachable from here, it's either local to
a service (see below) or it should be filed into `current/` or `archive/`.

**Rule:** location is status. `current/` = true now. `archive/` = history, kept
for context, not for execution. When a doc is superseded, move it to `archive/`.

---

## 🟢 Current — the project as it is now

### Orientation & planning
- [current/FORGE-STACK.md](current/FORGE-STACK.md) — the system map: how hub, engine, llama, and Godot connect
- [current/NEXT-PHASE-RECONCILED-DIRECTION.md](current/NEXT-PHASE-RECONCILED-DIRECTION.md) — **the next direction** (deterministic eval + reliability loop; VLM demoted) after reconciling the survey
- [current/NEXT-PHASE-VISUAL-EVAL-SURVEY.md](current/NEXT-PHASE-VISUAL-EVAL-SURVEY.md) — the survey prompts that produced it (input/history)
- [current/CONVENTIONS.md](current/CONVENTIONS.md) — the few coding rules (read at session start)
- [current/GOD-FILE-SPLIT-PLAN.md](current/GOD-FILE-SPLIT-PLAN.md) — handoff plan to split the god files + quick-win bug fixes
- [current/LAYER3-IMPLEMENTATION-PROMPT.md](current/LAYER3-IMPLEMENTATION-PROMPT.md) — the prompt handing the Layer-3 work to a code-writing CLI AI
- [current/IMPL-GUIDE-1-testbench-migration.md](current/IMPL-GUIDE-1-testbench-migration.md) — CLI-AI guide: finish the testbench migration (parity-gated)
- [current/IMPL-GUIDE-2-world-state-experiment.md](current/IMPL-GUIDE-2-world-state-experiment.md) — CLI-AI guide: the world-state slice + 4B-vs-27B richness test (design-first)
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
- [decisions/004-architecture-conventions-guardrails.md](decisions/004-architecture-conventions-guardrails.md)
- [decisions/005-legacy-test-runner-cutover.md](decisions/005-legacy-test-runner-cutover.md)

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
