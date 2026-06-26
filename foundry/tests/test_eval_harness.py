"""TDD tests for foundin.eval.harness — the autonomous eval harness core.

run_corpus drives NL requests through the planner (and optionally the
full forge chain), capturing structured RunRecords. Tests are pure /
injectable: they pass a fake llm and use build=False to skip the live
forge (no llm / no Blender in the test path).
"""

from __future__ import annotations

import json

import pytest

# ── Helpers: a valid spec WITHOUT a 'material' key (resolver drives it) ──


def _fake_llm_valid(_prompt: str, _grammar: str | None) -> str:
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
    from eval.harness import records_to_jsonl, run_corpus
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


# ═══════════════════════════════════════════════════════════════════════
#  P6: QuestRecord + run_quest_corpus
# ═══════════════════════════════════════════════════════════════════════

_MANIFEST = [
    {"id": "table_0", "category": "table", "material": "worn_oak",
     "x": 1.0, "y": 0.0, "z": -1.5},
    {"id": "shelf_0", "category": "shelf", "material": "rough_granite",
     "x": -2.0, "y": 0.0, "z": -3.0},
    {"id": "cabinet_0", "category": "cabinet", "material": "wrought_iron",
     "x": 2.5, "y": 0.0, "z": -2.0},
]


def _fake_quest_llm(_prompt: str, _grammar=None) -> str:
    """Stub LLM returning a valid quest spec JSON."""
    return json.dumps({
        "npc_role": "hermit",
        "target_entity": "shelf_0",
        "dialogue": {
            "greet": "Ah, a visitor! Welcome.",
            "ask": "Find my lost book on the shelf.",
            "wrong": "No, that is not my book.",
            "thank": "You found it! Thank you.",
        },
        "objective": {
            "type": "fetch",
            "target": "shelf_0",
            "giver": "npc",
        },
    })


def test_quest_record_dataclass_has_named_fields():
    """QuestRecord has all named fields."""
    from eval.harness import QuestRecord
    qr = QuestRecord(
        room_theme="a hermit's shack",
        quest_spec={"npc_role": "hermit"},
        decisions=[],
        compiled=True,
        scene_path="/tmp/test.tscn",
        manifest=_MANIFEST,
        error=None,
        seconds=0.42,
    )
    assert qr.room_theme == "a hermit's shack"
    assert qr.quest_spec == {"npc_role": "hermit"}
    assert qr.compiled is True
    assert qr.scene_path == "/tmp/test.tscn"
    assert qr.manifest == _MANIFEST
    assert qr.error is None
    assert qr.seconds == pytest.approx(0.42)


def test_run_quest_corpus_yields_one_record_per_theme(tmp_path):
    """With a fake LLM, one QuestRecord per room theme."""
    from eval.harness import run_quest_corpus

    themes = [
        "a hermit's shack",
        "a dusty workshop",
        "a wizard's study",
    ]
    records = run_quest_corpus(
        room_themes=themes,
        manifest=_MANIFEST,
        llm=_fake_quest_llm,
        scene_output_dir=str(tmp_path),
    )
    assert len(records) == 3
    for r, theme in zip(records, themes):
        assert r.room_theme == theme
        assert r.quest_spec is not None
        assert r.compiled is True
        assert r.scene_path is not None
        assert r.error is None
        assert r.seconds >= 0.0


def test_run_quest_corpus_failure_in_plan_captures_error(tmp_path):
    """A plan fn that raises → error captured, other records succeed."""
    from eval.harness import run_quest_corpus

    bad_theme = "this will explode"

    def flaky_plan(theme, manifest, llm):
        if theme == bad_theme:
            raise RuntimeError("simulated quest planner failure")
        from behaviour_gen import QuestBehaviourPlanner
        return QuestBehaviourPlanner().plan(theme, manifest, llm)

    themes = ["a hermit's shack", bad_theme, "a dusty workshop"]
    records = run_quest_corpus(
        room_themes=themes,
        manifest=_MANIFEST,
        llm=_fake_quest_llm,
        scene_output_dir=str(tmp_path),
        plan_quest=flaky_plan,
    )
    assert len(records) == 3
    assert records[0].error is None and records[0].compiled is True
    assert records[1].error is not None
    assert "simulated quest planner failure" in records[1].error
    assert records[1].compiled is False
    assert records[2].error is None and records[2].compiled is True


def test_quest_record_to_dict_returns_a_dict():
    from eval.harness import QuestRecord, quest_record_to_dict
    qr = QuestRecord(
        room_theme="a hermit's shack",
        quest_spec={"npc_role": "hermit"},
        decisions=[],
        compiled=True,
        scene_path="/tmp/test.tscn",
        manifest=_MANIFEST,
        error=None,
        seconds=0.01,
    )
    d = quest_record_to_dict(qr)
    assert isinstance(d, dict)
    assert d["room_theme"] == "a hermit's shack"
    assert d["compiled"] is True
    assert d["scene_path"] == "/tmp/test.tscn"


def test_quest_records_to_jsonl_round_trips(tmp_path):
    """quest_records_to_jsonl emits one JSON object per line."""
    from eval.harness import QuestRecord, quest_records_to_jsonl
    qrs = [
        QuestRecord(room_theme="a shack", quest_spec={"k": "v"},
                    decisions=[], compiled=True, scene_path="/tmp/a.tscn",
                    manifest=_MANIFEST, error=None, seconds=0.1),
        QuestRecord(room_theme="a study", quest_spec=None,
                    decisions=[], compiled=False, scene_path=None,
                    manifest=_MANIFEST, error="boom", seconds=0.2),
    ]
    out = quest_records_to_jsonl(qrs)
    lines = out.splitlines()
    assert len(lines) == 2
    for line, qr in zip(lines, qrs):
        loaded = json.loads(line)
        assert loaded["room_theme"] == qr.room_theme
        assert loaded["compiled"] == qr.compiled
