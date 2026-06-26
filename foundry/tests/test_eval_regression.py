"""TDD tests for foundry.eval.regression — golden-master regression lens (Prompt 5).

All tests use FAKE llms (injectable) so deterministic — no llama.cpp.
Tests cover:
  - matching golden → pass
  - changed material → HARD fail with diff
  - changed age → HARD fail with diff
  - changed generator → tracked only (not HARD fail)
  - --update rewrites expectation → next run passes
  - aggregate score correct
"""

from __future__ import annotations

import json

# ── Fake LLM ─────────────────────────────────────────────────────────

_TABLE_SPEC = json.dumps({
    "asset_id": "table",
    "generator": "table",
    "params": {
        "top_width": 1.2, "top_depth": 0.8, "top_thickness": 0.06,
        "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
    },
})


def _fake_llm(prompt: str, grammar) -> str:
    return _TABLE_SPEC


# ── Matching golden → pass ───────────────────────────────────────────

def test_match_golden_passes(tmp_path):
    """Output matching the golden expectation → passed=True, score=1.0."""
    from eval.regression import run_regression

    exp_dir = tmp_path / "expectations"
    exp_dir.mkdir()

    # Save a golden expectation matching what the fake LLM + resolver produce.
    # The stub LLM returns a table spec; resolver for "a table" → worn_oak, age=0.15.
    from eval.regression import _request_hash, _save_expectation
    req_hash = _request_hash("a table")
    _save_expectation(
        str(exp_dir), req_hash,
        {"generator": "table", "material": "worn_oak", "age": 0.15},
    )

    results, score = run_regression(
        ["a table"],
        str(exp_dir),
        llm=_fake_llm,
    )
    assert results[0]["passed"] is True
    assert results[0]["diffs"] is None
    assert score["hard_pass"] == 1
    assert score["hard_fail"] == 0
    assert score["score"] == 1.0


# ── Changed material → HARD fail ─────────────────────────────────────

def test_material_mismatch_hard_fail(tmp_path):
    """A golden expecting worn_oak but got wrought_iron → HARD fail."""
    from eval.regression import run_regression

    exp_dir = tmp_path / "expectations"
    exp_dir.mkdir()
    from eval.regression import _request_hash, _save_expectation

    # Golden says wrought_iron, but resolver for "a table" → worn_oak.
    req_hash = _request_hash("a table")
    _save_expectation(
        str(exp_dir), req_hash,
        {"generator": "table", "material": "wrought_iron", "age": 0.15},
    )

    results, score = run_regression(
        ["a table"],
        str(exp_dir),
        llm=_fake_llm,
    )
    assert results[0]["passed"] is False
    assert results[0]["diffs"] is not None
    assert results[0]["diffs"]["material"]["expected"] == "wrought_iron"
    assert results[0]["diffs"]["material"]["got"] == "worn_oak"
    assert score["hard_fail"] == 1
    assert score["score"] == 0.0


# ── Changed age → HARD fail ──────────────────────────────────────────

def test_age_mismatch_hard_fail(tmp_path):
    """A golden expecting age=0.8 but got 0.15 → HARD fail."""
    from eval.regression import run_regression

    exp_dir = tmp_path / "expectations"
    exp_dir.mkdir()
    from eval.regression import _request_hash, _save_expectation

    # Golden says age=0.8, but planner for "a table" (no wear word) → age=0.15.
    req_hash = _request_hash("a table")
    _save_expectation(
        str(exp_dir), req_hash,
        {"generator": "table", "material": "worn_oak", "age": 0.8},
    )

    results, score = run_regression(
        ["a table"],
        str(exp_dir),
        llm=_fake_llm,
    )
    assert results[0]["passed"] is False
    assert results[0]["diffs"]["age"]["expected"] == 0.8
    assert results[0]["diffs"]["age"]["got"] == 0.15
    assert score["score"] == 0.0


# ── Changed generator → tracked only (not HARD fail) ─────────────────

def test_generator_mismatch_tracked_only(tmp_path):
    """A golden expecting chair but got table → tracked, NOT a HARD fail."""
    from eval.regression import run_regression

    exp_dir = tmp_path / "expectations"
    exp_dir.mkdir()
    from eval.regression import _request_hash, _save_expectation

    # Golden says chair, but stub LLM returns table.
    req_hash = _request_hash("a table")
    _save_expectation(
        str(exp_dir), req_hash,
        {"generator": "chair", "material": "worn_oak", "age": 0.15},
    )

    results, score = run_regression(
        ["a table"],
        str(exp_dir),
        llm=_fake_llm,
    )
    # Generator mismatch is tracked, not a HARD failure.
    assert results[0]["passed"] is True
    assert results[0]["diffs"] is not None
    assert "generator" in results[0]["diffs"]
    assert "material" not in results[0]["diffs"]
    assert score["generator_mismatches"] == 1
    assert score["hard_pass"] == 1
    assert score["score"] == 1.0


# ── --update rewrites expectation → next run passes ──────────────────

def test_update_rewrites_expectation(tmp_path):
    """--update saves current output; next run (without update) passes."""
    from eval.regression import run_regression

    exp_dir = tmp_path / "expectations"
    exp_dir.mkdir()

    # First: save a WRONG golden.
    from eval.regression import _request_hash, _save_expectation
    req_hash = _request_hash("a table")
    _save_expectation(
        str(exp_dir), req_hash,
        {"generator": "table", "material": "wrought_iron", "age": 0.8},
    )

    # Run with update → re-blesses to the actual output.
    results, score = run_regression(
        ["a table"],
        str(exp_dir),
        llm=_fake_llm,
        update=True,
    )

    # Second run (no update) → should pass now.
    results2, score2 = run_regression(
        ["a table"],
        str(exp_dir),
        llm=_fake_llm,
        update=False,
    )
    assert results2[0]["passed"] is True
    assert results2[0]["diffs"] is None
    assert score2["score"] == 1.0


# ── Aggregate score ──────────────────────────────────────────────────

def test_aggregate_score_mixed(tmp_path):
    """Two requests: one passes, one fails → score=0.5."""
    from eval.regression import run_regression

    exp_dir = tmp_path / "expectations"
    exp_dir.mkdir()
    from eval.regression import _request_hash, _save_expectation

    # Request 1: correct golden → passes
    _save_expectation(
        str(exp_dir), _request_hash("a table"),
        {"generator": "table", "material": "worn_oak", "age": 0.15},
    )
    # Request 2: wrong golden → fails
    _save_expectation(
        str(exp_dir), _request_hash("a chair"),
        {"generator": "chair", "material": "wrought_iron", "age": 0.8},
    )

    results, score = run_regression(
        ["a table", "a chair"],
        str(exp_dir),
        llm=_fake_llm,
    )
    assert score["hard_pass"] == 1
    assert score["hard_fail"] == 1
    assert score["score"] == 0.5


# ── No expectation → passed=None ─────────────────────────────────────

def test_no_expectation_passed_is_none(tmp_path):
    """A request with no golden file → passed=None (first run marker)."""
    from eval.regression import run_regression

    exp_dir = tmp_path / "expectations"
    exp_dir.mkdir()

    results, score = run_regression(
        ["a table"],
        str(exp_dir),
        llm=_fake_llm,
    )
    assert results[0]["passed"] is None
    assert results[0]["expected"] is None
    # Score unaffected by items with no expectation
    assert score["with_expectations"] == 0
    assert score["score"] == 1.0


# ── Report builders ──────────────────────────────────────────────────

def test_build_report_dict_shape(tmp_path):
    from eval.regression import build_report_dict, run_regression

    exp_dir = tmp_path / "expectations"
    exp_dir.mkdir()
    from eval.regression import _request_hash, _save_expectation
    _save_expectation(
        str(exp_dir), _request_hash("a table"),
        {"generator": "table", "material": "worn_oak", "age": 0.15},
    )

    results, score = run_regression(
        ["a table"],
        str(exp_dir),
        llm=_fake_llm,
    )
    d = build_report_dict(results, score)
    assert d["total"] == 1
    assert d["hard_pass"] == 1
    assert d["hard_fail"] == 0
    assert d["score"] == 1.0
    assert isinstance(d["failed"], list)
    assert len(d["failed"]) == 0
    assert "per_request" in d


def test_build_report_md_pass(tmp_path):
    from eval.regression import build_report_dict, build_report_md, run_regression

    exp_dir = tmp_path / "expectations"
    exp_dir.mkdir()
    from eval.regression import _request_hash, _save_expectation
    _save_expectation(
        str(exp_dir), _request_hash("a table"),
        {"generator": "table", "material": "worn_oak", "age": 0.15},
    )

    results, score = run_regression(
        ["a table"],
        str(exp_dir),
        llm=_fake_llm,
    )
    d = build_report_dict(results, score)
    md = build_report_md(d)
    assert "Regression Report" in md
    assert "100.0%" in md
    assert "HARD pass:" in md
    assert "HARD fail:" in md


def test_build_report_md_fail(tmp_path):
    from eval.regression import build_report_dict, build_report_md, run_regression

    exp_dir = tmp_path / "expectations"
    exp_dir.mkdir()
    from eval.regression import _request_hash, _save_expectation
    _save_expectation(
        str(exp_dir), _request_hash("a table"),
        {"generator": "table", "material": "wrought_iron", "age": 0.8},
    )

    results, score = run_regression(
        ["a table"],
        str(exp_dir),
        llm=_fake_llm,
    )
    d = build_report_dict(results, score)
    md = build_report_md(d)
    assert "HARD failures" in md
    assert "wrought_iron" in md
    assert "worn_oak" in md


# ── Request hash determinism ─────────────────────────────────────────

def test_request_hash_deterministic():
    from eval.regression import _request_hash
    assert _request_hash("a table") == _request_hash("a table")
    assert _request_hash("A TABLE") == _request_hash("a table")
    assert _request_hash("  a table  ") == _request_hash("a table")
    assert _request_hash("a table") != _request_hash("a chair")
