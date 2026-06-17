# ADR 002 — Flat service layout + `current`/`archive` docs

**Date:** 2026-06-17
**Status:** Accepted

## Context
We surveyed four external AIs on directory structure and documentation. On
structure they unanimously rejected a Python `src/` layout in favour of a flat,
service-oriented monorepo. Several proposed additions (`shared/`, `godot/`,
`pyproject.toml` editable install, a single merged venv) that do not match this
project's actual architecture.

On docs, all four converged on: one top-level `docs/` split into `current/` and
`archive/` (location = status), a single `INDEX.md` dashboard, date-ordered
archives, and ADRs for the "why."

## Decision

### Structure
- **Flat service layout:** `hub/`, `engine/` at the top. Adopt.
- **Reject `shared/`:** hub and engine communicate via the DevForge MCP /
  subprocess boundary, not Python imports — there is nothing to share, and an
  empty `shared/` invites a dumping ground.
- **Reject `godot/`:** the Godot game project lives outside this repo at
  `~/dev/games/rpg`.
- **Reject `pyproject.toml` + `pip install -e .`:** only needed for cross-package
  imports we don't have.
- **Keep two virtualenvs:** engine (heavy) and hub (light) are isolated and both
  work; consolidation is risk without benefit.
- **Defer moving the one-off bench scripts** out of `hub/`: the in-flight
  testbench migration deletes most of them, so moving now is churn it will redo.

### Documentation
- Top-level `docs/` with `current/`, `archive/`, `decisions/`.
- `docs/INDEX.md` is the single entry point and points at everything, including
  service-local docs that intentionally stay next to their code (`hub/docs/`,
  `engine/docs/`).
- Status is folder location, not in-file markers. No `v2`/`final` filenames —
  git is the version history.

## Consequences
- The 22 scattered root-level docs were classified into `current/` and
  `archive/`; three loose `hub/`-root docs moved into `hub/docs/`.
- Already-organized subtrees (`hub/docs/`, `engine/docs/archive/`) were left in
  place and linked from the index, not forcibly centralized.
- The structural code reorg is intentionally **not** done here; it is folded into
  the testbench migration where it actually pays off.
