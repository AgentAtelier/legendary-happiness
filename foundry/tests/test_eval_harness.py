"""TDD tests for foundin.eval.harness — the autonomous eval harness core.

run_corpus drives NL requests through the planner (and optionally the
full forge chain), capturing structured RunRecords. Tests are pure /
injectable: they pass a fake llm and use build=False to skip the live
forge (no llm / no Blender in the test path).
"""

from __future__ import annotations

import json
import socket
from dataclasses import asdict
from typing import List, Optional

import pytest


# ── Helpers: a valid spec WITHOUT a 'material' key (resolver drives it) ──


def _fake_llm_valid(_prompt: str, _grammar: Optional[str]) -> str:
    return json.dumps({
        "asset_id": "table",
        "generator": "table",
        # NO material key — the resolver owns material now (Slice 11).
        "params": {
            "top_width": 1.5,
            "top_depth": 0.8,
            "top_thickness": 0.06,
            "leg_height": 0.65,
            "leg_radius": 0.05,
            "leg_inset": 0.1,
        },
    })


# ── RunRecord shape ─────────────────────────────────────────────────────


def test_run_record_dataclass_has_named_fields():
    """RunRecord has all the named fields in the spec."""
    from eval.harness import RunRecord
    r = RunRecord(
        request="a low coffee table",
        spec=None,
        decisions=[],
        gate_passed=None,
        gate_reasons=[],
        built=False,
        error=None,
        glb_path=None,
        seconds=0.42,
    )
    assert r.request == "a low coffee table"
    assert r.spec is None
    assert r.decisions == []
    assert r.gate_passed is None
    assert r.gate_reasons == []
    assert r.built is False
    assert r.error is None
    assert r.glb_path is None
    assert r.seconds == pytest.approx(0.42)


# ── run_corpus: one record per request ─────────────────────────────────


def test_run_corpus_yields_one_record_per_request_build_false():
    """With a fake llm and build=False, one RunRecord per request — built
    False, error None, spec populated, no exception."""
    from eval.harness import run_corpus
    from planner import AssetPlanner

    requests = [
        "a low coffee table",
        "a tall wooden bookshelf",
        "a wrought iron cabinet",
    ]
    records = run_corpus(
        requests=requests,
        llm=_fake_llm_valid,
        lexicon_path="/tmp/does_not_matter.json",
        library_dir="/tmp/does_not_matter",
        build=False,
        plan=AssetPlanner().plan,
        forge=lambda *_args, **_kwargs: pytest.fail("build=False must not call forge"),
    )
    assert len(records) == 3
    for r, req in zip(records, requests):
        assert r.request == req
        assert r.spec is not None
        assert isinstance(r.spec, dict)
        assert r.built is False
        assert r.error is None
        assert r.gate_passed is None
        assert r.gate_reasons == []
        assert r.glb_path is None
        assert r.seconds >= 0.0


def test_run_corpus_no_exception_in_plan_returns_error_record():
    """A plan fn that raises for ONE request → that one record carries
    error=repr(e); the others succeed; run_corpus itself does NOT raise."""
    from eval.harness import run_corpus
    from planner import AssetPlanner

    bad_request = "this one will explode"

    def flaky_plan(req: str, _llm):
        if req == bad_request:
            raise RuntimeError("simulated planner failure")
        return AssetPlanner().plan(req, _llm)

    requests = ["a plain table", bad_request, "another plain table"]
    records = run_corpus(
        requests=requests,
        llm=_fake_llm_valid,
        lexicon_path="/tmp/x.json",
        library_dir="/tmp/x",
        build=False,
        plan=flaky_plan,
    )
    assert len(records) == 3
    # The bad one carried an error string, the others succeeded.
    assert records[0].error is None and records[0].spec is not None
    assert records[1].error is not None
    assert "simulated planner failure" in records[1].error
    assert records[1].spec is None  # spec was never produced
    assert records[2].error is None and records[2].spec is not None


# ── record_to_dict / records_to_jsonl ─────────────────────────────────-


def test_record_to_dict_returns_a_dict():
    from eval.harness import RunRecord, record_to_dict
    r = RunRecord(
        request="a table",
        spec={"asset_id": "table", "generator": "table"},
        decisions=[],
        gate_passed=None,
        gate_reasons=[],
        built=False,
        error=None,
        glb_path=None,
        seconds=0.01,
    )
    d = record_to_dict(r)
    assert isinstance(d, dict)
    assert d["request"] == "a table"
    assert d["spec"]["generator"] == "table"
    assert d["built"] is False
    assert d["seconds"] == 0.01


def test_records_to_jsonl_round_trips_per_line():
    """records_to_jsonl emits ONE JSON object per line, and each line loads
    back to its record's dict."""
    from eval.harness import RunRecord, records_to_jsonl
    rs = [
        RunRecord(request="a table", spec={"k": "v"}, decisions=[], gate_passed=None,
                  gate_reasons=[], built=False, error=None, glb_path=None, seconds=0.1),
        RunRecord(request="a chair", spec=None, decisions=[], gate_passed=False,
                  gate_reasons=["too tall"], built=True, error=None,
                  glb_path="/tmp/chair.glb", seconds=2.3),
    ]
    out = records_to_jsonl(rs)
    lines = out.splitlines()
    assert len(lines) == 2
    for line, r in zip(lines, rs):
        loaded = json.loads(line)
        assert loaded["request"] == r.request
        assert loaded["built"] == r.built


def test_run_corpus_writes_jsonl_with_one_line_per_record():
    """The records produced by run_corpus round-trip cleanly through
    records_to_jsonl."""
    from eval.harness import run_corpus, records_to_jsonl
    from planner import AssetPlanner

    requests = ["a table", "a chair"]
    records = run_corpus(
        requests=requests, llm=_fake_llm_valid,
        lexicon_path="/tmp/x.json", library_dir="/tmp/x",
        build=False, plan=AssetPlanner().plan, forge=None,
    )
    blob = records_to_jsonl(records)
    lines = [l for l in blob.splitlines() if l.strip()]
    assert len(lines) == len(records)
    for line, r in zip(lines, records):
        loaded = json.loads(line)
        assert loaded["request"] == r.request
