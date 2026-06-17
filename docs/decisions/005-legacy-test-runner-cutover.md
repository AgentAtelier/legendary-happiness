# ADR 005 — Legacy test runners: hard cut

**Date:** 2026-06-17
**Status:** Accepted

## Context
The hub carries six legacy test runners (`bench.py`, `shootout.py`,
`scenarios.py`, `gauntlet.py`, `multi_model_bench.py`, `comprehensive_bench.py`)
and the `hub.py` routes that drive them. They are being replaced by
`hub/forge_testbench/`. The Layer-3 review unanimously flagged them as a tax on
every `hub.py` change and the blocker to splitting that god file. Two options:
hard-delete once the new chassis reaches parity, or keep a deprecated shim.

## Decision
**Hard cut.** Once `forge_testbench` reaches parity (per
`docs/current/TESTBENCH-MIGRATION-HANDOFF.md` — Claude signs off each category),
delete the six legacy runners and their `hub.py` routes outright. No shim, no
deprecated tab. The point of this whole effort is *less surface*.

## Consequences
- The `hub.py` split (Phase 2 of `GOD-FILE-SPLIT-PLAN.md`) stays **gated** on this
  deletion, which is itself gated on the testbench migration finishing. Until
  then, do not split `hub.py` and do not touch the legacy runners.
- The dedup in Phase 0 must only repoint **live** consumers to shared helpers and
  leave the dying legacy copies untouched (they're about to be deleted).
- Nothing in the UI keeps the old test tabs alive after cutover; the testbench UI
  replaces them.
