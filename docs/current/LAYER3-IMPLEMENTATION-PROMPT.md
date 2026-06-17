# Layer 3 — Implementation Prompt (for a code-writing CLI AI)

Paste the block below into a CLI AI that can modify the repo. Unlike the survey,
this task **writes code** — but only on a branch, behind smoke tests, never on
`main`.

---

```
============================ COPY FROM HERE ============================
IMPLEMENTATION TASK — you will modify code, but under strict guardrails.

AUTHORITATIVE DOCS — read these first and follow them exactly (they outrank your
own preferences):
- docs/current/GOD-FILE-SPLIT-PLAN.md   (the ordered plan — do what it says)
- docs/current/CONVENTIONS.md           (the rules every change must follow)
- docs/decisions/004-architecture-conventions-guardrails.md
- docs/decisions/005-legacy-test-runner-cutover.md

CONTEXT: a local toolchain that turns prompts into Godot scenes. `hub/` (FastAPI
ops panel) talks to `engine/devforge/` (generation engine) over an MCP boundary;
they never import each other. The owner is a non-programmer who reviews diffs.
`hub/forge_testbench/` is the reference for clean code — match its style.

GROUND RULES (non-negotiable):
1. BRANCH. `git checkout -b cleanup/layer3-code-health`. Do ALL work there. Do
   NOT commit to `main`. Do NOT merge. When done (or when you stop), push the
   branch: `git push -u origin cleanup/layer3-code-health`. The owner reviews
   before any merge.
2. SMALL COMMITS. One concern per commit, conventional message
   ("refactor:", "fix:", "chore:"). After each code change run
   `ruff format <changed paths> && ruff check --fix <changed paths>`.
3. SMOKE TEST EACH STEP. Each step in the plan names a smoke check. Run it. If it
   fails, or anything is ambiguous, STOP and write the problem into the report
   (below) — do NOT push through, do NOT paper over a failure.
4. THESE ARE REFACTORS — behavior must not change. Preserve every public MCP tool
   name and every HTTP route path exactly. Renames of files are allowed per the
   plan; keep a one-line import alias for one cycle where another module imports
   the old path (e.g. hub.py references the engine entry path).
5. DO NOT TOUCH the legacy runners (bench.py, shootout.py, scenarios.py,
   gauntlet.py, multi_model_bench.py, comprehensive_bench.py). They are being
   deleted separately. When deduping, repoint only the LIVE consumers
   (hub.py, hub/forge_testbench/, hub/diagnostics.py) and leave the legacy copies
   alone.
6. SCOPE: do the GUARDRAIL setup + Phase 0 + Phase 1 + the navigation aids ONLY.
   Do NOT do Phase 2 (the hub.py split) and do NOT delete legacy runners — both
   are gated on a separate testbench migration that is not finished. Stop after
   Phase 1 + navigation aids.
7. LIVE STACK: services run as systemd user units (forge-hub, forge-devforge,
   llama). Moving engine modules requires restarting forge-devforge to load them.
   Prefer cheap smoke checks you can run without the full stack (module imports,
   MCP registration loads, ruff clean). For end-to-end checks (apply_spec
   "add a red cube", get_scene) that need the live stack, attempt them if you
   can; otherwise list them explicitly as "owner must verify live" in the report.

DO THE WORK IN THIS ORDER:

STEP G — Guardrail.
- Add a root Ruff config (pyproject.toml or ruff.toml): format (Black-compatible)
  + check with rules F, I, B, plus a generous line length (~120). Disable noisy
  style-only rules.
- Run `ruff format` over hub/ and engine/ in ONE dedicated commit (pure
  formatting, no logic). Put that commit's hash in a new `.git-blame-ignore-revs`.
- Add `scripts/check.sh` (and/or a CI workflow) that runs: `ruff check`,
  `ruff format --check`, and a file-length gate that FAILS if any tracked
  hub/ or engine/ `.py` exceeds 500 lines.

STEP 0 — Phase 0 quick-wins (see plan; low risk, fixes live bugs):
  1. hub/mcp_client.py with devforge_call/godot_ai_call; repoint live callers.
  2. Make the live callers use forge_env.read_env — DELETE the naive quote-strip
     reimplementation in hub/forge_testbench/runner.py (it mangles single-quoted
     JSON values — a real bug).
  3. One shell helper (fix the stderr-loss divergence between _sh and
     forge_ops.run_cmd_capture).
  4. Extract the repeated job-runner block in hub.py into _start_job(...).
  5. Replace _HAS_SPATIAL/_HAS_GOVERNANCE silent try/except with one explicit,
     loud init.
  6. Trim engine/devforge/platform/monitor/__init__.py (502 lines → slim
     re-export); delete the dead incremental_context_builder.py stub.

STEP 1 — Phase 1 engine god-file splits (A → B → C, exactly as the plan
describes), each behind its named smoke test:
  A. execution/godot_ai_mcp.py → rename godot_ai_executor.py + mcp_session.py +
     op_translator.py.
  B. compilation/pipeline/engine.py → rename pipeline_orchestrator.py + result.py
     + planner_routing.py (collapse the 7 spatial wrappers to a dict dispatch) +
     post_planner.py.
  C. platform/mcp_server.py → thin server + platform/tools/*.py groups, each with
     register_tools(mcp, ctx). Highest API risk — verify registration after each.

STEP N — Navigation aids:
  - docs/current/CODE-ARCHITECTURE.md: one page, each key file → its one-line job.
  - Link docs/current/FORGE-STACK.md from the root README.md.
  - Add per-package __init__.py re-exports where missing; add engine/README.md
    noting the `devforge` package name is a historical fossil.

WHEN DONE OR STOPPED: write docs/reviews/layer3/IMPLEMENTATION-REPORT.md with —
per step: what you changed, which smoke checks passed, what you skipped or
flagged, and an explicit list of end-to-end checks the owner must run on the live
stack. Push the branch. Reply in chat with ONLY: the branch name + a one-line
status (e.g. "done through Phase 1; 3 live checks pending owner").
============================= TO HERE ==================================
```

---

## After this runs
The owner (with Claude) reviews the `cleanup/layer3-code-health` branch, runs the
pending live smoke checks, and merges. Phase 2 (`hub.py`) and the legacy deletion
wait on the separate testbench migration reaching parity (ADR-005).
