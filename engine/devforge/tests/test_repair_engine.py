"""Regression tests for RepairEngine convergence-state handling.

The engine instance is reused across apply_spec calls, so the convergence
guard's per-run state MUST be reset between runs — otherwise a second run
that happens to produce the same error set as a prior run trips the guard
and skips repair entirely (finding D5).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from devforge.compilation.pipeline.repair_engine import RepairEngine


def _op_missing_root():
    # set_property whose node path lacks the /root prefix — a deterministic
    # repair target (repair_engine rewrites it to /root/Main/...).
    return [{"type": "set_property", "node": "Player", "property": "speed", "value": 5}]


def test_repair_fixes_missing_root_prefix():
    eng = RepairEngine()
    out = eng.repair(_op_missing_root(), errors=[], scene_tree={}, files=[])
    assert out[0]["node"].startswith("/root"), "missing-root repair should fire"


def test_reset_clears_convergence_state():
    eng = RepairEngine()
    # Simulate a prior run that left convergence state populated (as would
    # happen if a future LLM repair loop converged on a stable error set).
    eng._previous_errors = frozenset({"some error"})
    eng._convergence_count = 5
    eng.reset()
    assert eng._previous_errors == []
    assert eng._convergence_count == 0


def test_repair_still_fires_after_prior_run_left_state():
    """The D5 bug: without reset(), a fresh run whose errors match a prior
    run's converged error set returns operations UNCHANGED. After reset()
    (called by the engine at the top of every run), repair fires normally."""
    eng = RepairEngine()
    same_errors = ["err-A"]

    # Drive the guard to its tripped state with a repeated error set, the way
    # a multi-attempt loop would (>=2 identical sets → guard returns unchanged).
    eng.repair(_op_missing_root(), errors=same_errors, scene_tree={}, files=[])
    eng.repair(_op_missing_root(), errors=same_errors, scene_tree={}, files=[])
    tripped = eng.repair(_op_missing_root(), errors=same_errors, scene_tree={}, files=[])
    assert tripped[0]["node"] == "Player", "guard should have returned ops unchanged"

    # A fresh pipeline run resets state → repair fires again.
    eng.reset()
    fixed = eng.repair(_op_missing_root(), errors=same_errors, scene_tree={}, files=[])
    assert fixed[0]["node"].startswith("/root"), "after reset, repair must fire again"


if __name__ == "__main__":
    test_repair_fixes_missing_root_prefix()
    test_reset_clears_convergence_state()
    test_repair_still_fires_after_prior_run_left_state()
    print("PASS: repair engine convergence-reset regression tests")
