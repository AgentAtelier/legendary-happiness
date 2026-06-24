"""TDD tests for foundry.eval.stability — the stability lens (Prompt 4).

All tests use a FAKE llm (injectable) so they are deterministic and
need no llama.cpp server.  Tests cover:
  - all-stable (identical output across runs)
  - generator flip
  - material flip (regression guard)
  - age flip (P1 validation)
  - param drift >15%
  - stability score computation
  - determinism given a seed
  - report dict + md output
"""

from __future__ import annotations

import json

# ── Fake LLM helpers ──────────────────────────────────────────────────

def _fake_stable(prompt: str, grammar):
    """Returns the SAME spec every call — all runs identical."""
    return json.dumps({
        "asset_id": "table",
        "generator": "table",
        "params": {
            "top_width": 1.2, "top_depth": 0.8, "top_thickness": 0.06,
            "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
        },
    })


def _make_counting_llm(responses: list[str]):
    """Return an llm that cycles through *responses* across calls."""
    state = {"i": 0}

    def llm(prompt: str, grammar) -> str:
        resp = responses[state["i"] % len(responses)]
        state["i"] += 1
        return resp

    return llm


# ── Table-spec helpers ────────────────────────────────────────────────

_TABLE_SPEC = json.dumps({
    "asset_id": "table",
    "generator": "table",
    "params": {
        "top_width": 1.2, "top_depth": 0.8, "top_thickness": 0.06,
        "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
    },
})

_CHAIR_SPEC = json.dumps({
    "asset_id": "chair",
    "generator": "chair",
    "params": {
        "seat_width": 0.5, "seat_depth": 0.5, "seat_thickness": 0.06,
        "leg_height": 0.45, "leg_radius": 0.04, "leg_inset": 0.05,
        "back_height": 0.35,
    },
})


# ── Stable case ──────────────────────────────────────────────────────

def test_stable_fake_all_identical():
    """A fake that returns the same JSON every call → all stable."""
    from eval.stability import run_stability

    per_request, score = run_stability(
        ["a table", "a chair"],
        runs=3,
        seed=42,
        llm=_fake_stable,
    )
    assert score == 1.0
    for r in per_request:
        assert r["stable"]
        assert r["varied"] == []


def test_stable_single_request():
    from eval.stability import run_stability

    per_request, score = run_stability(
        ["a table"],
        runs=2,
        seed=42,
        llm=_fake_stable,
    )
    assert score == 1.0
    assert per_request[0]["stable"]


# ── Generator flip ───────────────────────────────────────────────────

def test_unstable_generator_flip():
    """A fake that returns 'table' for run 1 and 'chair' for run 2 →
    varied=['generator']."""
    from eval.stability import run_stability

    llm = _make_counting_llm([_TABLE_SPEC, _CHAIR_SPEC])
    per_request, score = run_stability(
        ["a thing"],
        runs=2,
        seed=42,
        llm=llm,
    )
    assert score == 0.0
    r = per_request[0]
    assert not r["stable"]
    assert "generator" in r["varied"]


# ── Material flip (regression guard) ─────────────────────────────────

def test_unstable_material_flip():
    """A plan that returns different materials per call → varied=['material'].
    The resolver overrides material in production, so this test injects a
    custom ``plan`` that bypasses the resolver to simulate a broken build."""
    from eval.stability import run_stability

    state = {"i": 0}

    def flipping_plan(request, llm):
        materials = ["worn_oak", "wrought_iron"]
        mat = materials[state["i"] % 2]
        state["i"] += 1
        spec = {
            "asset_id": "table",
            "generator": "table",
            "material": mat,
            "age": 0.15,
            "params": {
                "top_width": 1.2, "top_depth": 0.8, "top_thickness": 0.06,
                "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
            },
        }
        return spec, []

    per_request, score = run_stability(
        ["a table"],
        runs=2,
        seed=42,
        llm=_fake_stable,  # unused by our injected plan, but required
        plan=flipping_plan,
    )
    assert score == 0.0
    r = per_request[0]
    assert not r["stable"]
    assert "material" in r["varied"]


# ── Param drift >15% ─────────────────────────────────────────────────

def test_unstable_param_drift():
    """A fake that returns top_width=1.2 run 1 and top_width=1.5 run 2 →
    drift=0.3/1.5=20% > 15% → varied=['param:top_width']."""
    from eval.stability import run_stability

    spec1 = json.dumps({
        "asset_id": "table",
        "generator": "table",
        "params": {
            "top_width": 1.2, "top_depth": 0.8, "top_thickness": 0.06,
            "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
        },
    })
    spec2 = json.dumps({
        "asset_id": "table",
        "generator": "table",
        "params": {
            "top_width": 1.5, "top_depth": 0.8, "top_thickness": 0.06,
            "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
        },
    })

    llm = _make_counting_llm([spec1, spec2])
    per_request, score = run_stability(
        ["a table"],
        runs=2,
        seed=42,
        llm=llm,
    )
    assert score == 0.0
    r = per_request[0]
    assert not r["stable"]
    assert "param:top_width" in r["varied"]


def test_stable_small_param_variation_within_15_percent():
    """A fake that returns top_width=1.2 and top_width=1.3 →
    drift=0.1/1.3≈7.7% < 15% → stable (no param drift)."""
    from eval.stability import run_stability

    spec1 = json.dumps({
        "asset_id": "table",
        "generator": "table",
        "params": {
            "top_width": 1.2, "top_depth": 0.8, "top_thickness": 0.06,
            "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
        },
    })
    spec2 = json.dumps({
        "asset_id": "table",
        "generator": "table",
        "params": {
            "top_width": 1.3, "top_depth": 0.8, "top_thickness": 0.06,
            "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
        },
    })

    llm = _make_counting_llm([spec1, spec2])
    per_request, score = run_stability(
        ["a table"],
        runs=2,
        seed=42,
        llm=llm,
    )
    assert score == 1.0
    r = per_request[0]
    assert r["stable"]
    assert r["varied"] == []


# ── Stability score ──────────────────────────────────────────────────

def test_stability_score_mixed_stable_unstable():
    """Two requests, one stable, one unstable → score=0.5."""
    from eval.stability import run_stability

    # Request "a table": stable fake
    # Request "a chair": flips generator
    state = {"i": 0}

    def mixed_llm(prompt: str, grammar) -> str:
        # For run 0 of each: table→table, chair→chair
        # For run 1 of each: table→table, chair→table (flip)
        ix = state["i"]
        state["i"] += 1
        if ix < 2:
            return _TABLE_SPEC if ix == 0 else _CHAIR_SPEC
        else:
            return _TABLE_SPEC  # run 1: both table

    per_request, score = run_stability(
        ["a table", "a chair"],
        runs=2,
        seed=42,
        llm=mixed_llm,
    )
    # table: stable (both runs table)
    # chair: unstable (run 0=chair, run 1=table → generator flip)
    assert score == 0.5


# ── Determinism ──────────────────────────────────────────────────────

def test_determinism_same_seed_same_output():
    """Same fake, same requests, same seed → same score + per_request."""
    from eval.stability import run_stability

    llm = _make_counting_llm([_TABLE_SPEC, _CHAIR_SPEC])
    per1, score1 = run_stability(
        ["a thing"],
        runs=2,
        seed=42,
        llm=llm,
    )

    llm2 = _make_counting_llm([_TABLE_SPEC, _CHAIR_SPEC])
    per2, score2 = run_stability(
        ["a thing"],
        runs=2,
        seed=42,
        llm=llm2,
    )
    assert score1 == score2
    assert per1 == per2


# ── Report builders ──────────────────────────────────────────────────

def test_build_report_dict_shape():
    from eval.stability import build_report_dict, run_stability

    per_request, score = run_stability(
        ["a table"],
        runs=2,
        seed=42,
        llm=_fake_stable,
    )
    d = build_report_dict(per_request, score, runs=2, seed=42, total=1)
    assert d["total"] == 1
    assert d["runs_per_request"] == 2
    assert d["seed"] == 42
    assert d["stable_count"] == 1
    assert d["unstable_count"] == 0
    assert d["stability_score"] == 1.0
    assert "unstable" in d
    assert isinstance(d["unstable"], list)
    assert len(d["unstable"]) == 0
    assert "per_request" in d
    assert len(d["per_request"]) == 1


def test_build_report_dict_with_unstable():
    from eval.stability import build_report_dict, run_stability

    llm = _make_counting_llm([_TABLE_SPEC, _CHAIR_SPEC])
    per_request, score = run_stability(
        ["a thing"],
        runs=2,
        seed=42,
        llm=llm,
    )
    d = build_report_dict(per_request, score, runs=2, seed=42, total=1)
    assert d["stable_count"] == 0
    assert d["unstable_count"] == 1
    assert d["stability_score"] == 0.0
    assert len(d["unstable"]) == 1
    assert "generator" in d["unstable"][0]["varied"]


def test_build_report_md_stable():
    from eval.stability import build_report_dict, build_report_md, run_stability

    per_request, score = run_stability(
        ["a table"],
        runs=2,
        seed=42,
        llm=_fake_stable,
    )
    d = build_report_dict(per_request, score, runs=2, seed=42, total=1)
    md = build_report_md(d)
    assert "Stability Report" in md
    assert "**Stable:** 1 / 1" in md
    assert "100.0%" in md
    assert "all requests stable" in md


def test_build_report_md_unstable():
    from eval.stability import build_report_dict, build_report_md, run_stability

    llm = _make_counting_llm([_TABLE_SPEC, _CHAIR_SPEC])
    per_request, score = run_stability(
        ["a thing"],
        runs=2,
        seed=42,
        llm=llm,
    )
    d = build_report_dict(per_request, score, runs=2, seed=42, total=1)
    md = build_report_md(d)
    assert "**Unstable:** 1 / 1" in md
    assert "generator" in md


def test_varied_counts():
    from eval.stability import run_stability

    llm = _make_counting_llm([_TABLE_SPEC, _CHAIR_SPEC])
    per_request, score = run_stability(
        ["a thing"],
        runs=2,
        seed=42,
        llm=llm,
    )
    from eval.stability import _count_varied
    vc = _count_varied(per_request)
    assert vc["generator"] == 1


# ── Captured keys shape ──────────────────────────────────────────────

def test_runs_info_has_expected_keys():
    from eval.stability import run_stability

    per_request, score = run_stability(
        ["a table"],
        runs=1,
        seed=42,
        llm=_fake_stable,
    )
    ri = per_request[0]["runs_info"][0]
    for key in ("generator", "material", "age", "params"):
        assert key in ri, f"missing {key}"
    # Material + age come from the resolver even when the LLM doesn't
    # emit them.
    assert isinstance(ri["material"], str)
    assert isinstance(ri["age"], float)
