# ADR 004 — Code architecture, conventions, and guardrails

**Date:** 2026-06-17
**Status:** Accepted
**Source:** Layer-3 survey — six CLI AIs reviewing the real repo, read-only
(`docs/reviews/layer3/`), reconciled against the code.

## Context
The codebase grew via AI assistants and accumulated ~8 large files (four genuine
god files) and heavy duplication. The owner is a non-programmer who reviews but
can't read code deeply; maintainability and reviewability are first-class goals.
Six independent reviews converged almost completely on the same diagnosis.

## Decision

### 1. Name the architecture (and make the seam a rule)
**Three services, two MCP seams.** `hub/` (ops panel) ⇄ MCP ⇄ `engine/devforge/`
(generation pipeline) ⇄ MCP ⇄ `godot-ai` (Godot bridge); llama.cpp beside the
engine. **Rule: `hub/` and `engine/` never import each other; only flat
dicts/JSON cross an MCP seam, never shared classes.** This is already true —
codify it so a future AI can't quietly break it.

### 2. Adopt the conventions in `docs/current/CONVENTIONS.md`
A short, fixed rule-set (file/function length, one class per file, mandatory
one-line module docstring, no third copy, single config source, section
dividers, no silent feature-disabling). `hub/forge_testbench/` is the reference
implementation.

### 3. Guardrail = Ruff + a file-length CI gate
Ruff format+check is the post-edit hook the AI runs and the CI check; a
length-gate fails any tracked `.py` over 500 lines. Reject mypy-strict, pylint,
coverage gates, lockfiles, and multi-hook pre-commit for now.

### 4. Fossil renames (when each file is next touched)
- `engine/devforge/compilation/pipeline/engine.py` → `pipeline_orchestrator.py`
  (a file named `engine.py`, inside `pipeline/`, inside `engine/`, holding class
  `PipelineEngine` — four collisions).
- `engine/devforge/execution/godot_ai_mcp.py` → `godot_ai_executor.py` (it's an
  MCP *client/executor*, not a server).
- The `devforge` package name stays (renaming touches 200+ imports for no gain) —
  documented as a known fossil in `engine/README.md`.

### 5. Deferred (explicitly not now)
- Reorganizing `engine/devforge/`'s ~30 top-level packages into 5–6 groups —
  high churn, low payoff; revisit after the god-file splits.
- The `hub.py` split is **gated** on deleting the legacy test runners first (see
  `docs/current/GOD-FILE-SPLIT-PLAN.md`).

## Consequences
- A standing conventions doc + Ruff makes "AI writes clean code" a system, not a
  hope. The owner's review job shrinks to reading small, one-concern diffs.
- Several real bugs the review surfaced (the `read_env` quote-strip in the test
  runner, the `_sh` stderr loss, silent `_HAS_*` disabling) are scheduled as the
  first quick-wins in the split plan.
- One owner decision still open: **legacy cutover** — hard-delete the legacy test
  routes once `forge_testbench` reaches parity, vs. keep a deprecated shim. This
  blocks the highest-risk split (`hub.py`).
