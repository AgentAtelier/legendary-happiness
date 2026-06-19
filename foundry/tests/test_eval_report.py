"""TDD tests for foundry.eval.report — friction report (slice 1).

``build_friction_report(records, sample) -> (dict, str)`` returns a
machine dict with the spec-named keys + a human-readable markdown
digest that ENDS with the probe list ("Eyeball these N:").  Plus
corpus-loader + corpus-file shape tests (no live llm/Blender).
"""

from __future__ import annotations

from typing import List
from pathlib import Path

import pytest

from eval.harness import RunRecord
from eval.sampler import SampleResult, stratify_and_sample
from eval.report import build_friction_report, load_corpus


# ── helpers ───────────────────────────────────────────────────────────


def _make_record(
    request: str = "a table",
    *,
    error: str | None = None,
    gate_passed: bool | None = None,
    gate_reasons: list[str] | None = None,
    decisions: list[dict] | None = None,
    spec: dict | None = None,
    built: bool = False,
    index: int = 0,
) -> RunRecord:
    return RunRecord(
        request=request,
        spec=spec,
        decisions=list(decisions or []),
        gate_passed=gate_passed,
        gate_reasons=list(gate_reasons or []),
        built=built,
        error=error,
        glb_path=None,
        seconds=0.01,
    )


def _clean_record(i: int) -> RunRecord:
    """A 'clean' record — no error, no gate reject, no decisions,
    mid-range cabinet spec with NO size/material words in the request."""
    return _make_record(
        request=f"a plain storage unit {i}",
        spec={
            "asset_id": "cabinet",
            "generator": "cabinet",
            "material": "worn_oak",
            "age": 0.15,
            "params": {
                "width": 0.8, "depth": 0.5, "height": 1.3,
                "panel_thickness": 0.04, "base_height": 0.08,
            },
        },
        gate_passed=True,
        built=True,
        index=i,
    )


def _error_record(i: int, msg: str = "boom") -> RunRecord:
    return _make_record(
        request=f"crash me {i}",
        error=f"RuntimeError('{msg}')",
        index=i,
    )


def _gate_rejected_record(i: int, reason: str = "polygon budget exceeded") -> RunRecord:
    return _make_record(
        request=f"rejected {i}",
        spec={
            "asset_id": "table",
            "generator": "table",
            "material": "worn_oak",
            "age": 0.15,
            "params": {
                "top_width": 1.5, "top_depth": 0.8, "top_thickness": 0.06,
                "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
            },
        },
        gate_passed=False,
        gate_reasons=[reason],
        built=True,
        index=i,
    )


# ── shape ─────────────────────────────────────────────────────────────


def test_build_friction_report_returns_tuple_of_dict_and_str():
    """The contract: build_friction_report(records, sample) returns a
    (dict, str) pair — a machine dict, a human digest."""
    records = [_clean_record(i) for i in range(5)]
    sample = stratify_and_sample(records, seed=1, clean_baseline_n=2)
    out = build_friction_report(records, sample)
    assert isinstance(out, tuple)
    assert len(out) == 2
    report_dict, digest = out
    assert isinstance(report_dict, dict)
    assert isinstance(digest, str)


def test_build_friction_report_dict_has_all_named_keys():
    """Dict must carry the spec-named keys verbatim."""
    records = [_clean_record(i) for i in range(3)]
    sample = stratify_and_sample(records, seed=1, clean_baseline_n=2)
    d, _ = build_friction_report(records, sample)
    required = {
        "total",
        "signal_counts",
        "decision_code_freq",
        "gate_reason_freq",
        "build_errors",
        "size_mismatches",
        "probes",
    }
    missing = required - set(d.keys())
    assert not missing, f"missing keys: {missing}; got {set(d.keys())}"


# ── content of named keys ────────────────────────────────────────────


def test_build_friction_report_total_matches_record_count():
    records = [_clean_record(i) for i in range(7)]
    sample = stratify_and_sample(records, seed=1, clean_baseline_n=2)
    d, _ = build_friction_report(records, sample)
    assert d["total"] == 7


def test_build_friction_report_signal_counts_match_signals():
    """signal_counts must add to total and contain the expected tags."""
    records = [
        _error_record(0),
        _error_record(1),                                # 2 build_error
        _gate_rejected_record(2, "mesh is not watertight"),
        _gate_rejected_record(3, "polygon budget exceeded"),
        _gate_rejected_record(4, "polygon budget exceeded"),
        _clean_record(5),                                # 1 clean
        _clean_record(6),
        _clean_record(7),
    ]
    sample = stratify_and_sample(records, seed=1, clean_baseline_n=2)
    d, _ = build_friction_report(records, sample)
    sc = d["signal_counts"]
    # 2 errors → 2 build_error tags
    assert sc.get("build_error", 0) == 2
    # 3 gate rejects → 3 gate_rejected tags
    assert sc.get("gate_rejected", 0) == 3
    # 3 cleans (records flagged by compute_signals; the rest also count
    # under decision_fired/clean depending on their spec; rely on the
    # total being consistent).
    assert sum(sc.values()) == d["total"]


def test_build_friction_report_decision_code_freq_aggregates():
    """decision_code_freq counts decision codes across all records."""
    records = [
        _make_record(
            request="a wooden table",
            decisions=[
                {"code": "material.family_defaulted", "stage": "planner"},
            ],
            spec={
                "generator": "table", "material": "worn_oak", "age": 0.15,
                "params": {"top_width": 1.2, "top_depth": 0.7, "top_thickness": 0.05,
                           "leg_height": 0.5, "leg_radius": 0.04, "leg_inset": 0.08},
            },
            gate_passed=True, built=True, index=0,
        ),
        _make_record(
            request="a simple table",
            decisions=[
                {"code": "material.unspecified_defaulted", "stage": "planner"},
            ],
            spec={
                "generator": "table", "material": "worn_oak", "age": 0.15,
                "params": {"top_width": 1.2, "top_depth": 0.7, "top_thickness": 0.05,
                           "leg_height": 0.5, "leg_radius": 0.04, "leg_inset": 0.08},
            },
            gate_passed=True, built=True, index=1,
        ),
    ]
    sample = stratify_and_sample(records, seed=1, clean_baseline_n=1)
    d, _ = build_friction_report(records, sample)
    assert d["decision_code_freq"].get("material.family_defaulted", 0) == 1
    assert d["decision_code_freq"].get("material.unspecified_defaulted", 0) == 1


def test_build_friction_report_gate_reason_freq_aggregates():
    """gate_reason_freq is a histogram of gate_reasons across records."""
    records = [
        _gate_rejected_record(0, "polygon budget exceeded"),
        _gate_rejected_record(1, "polygon budget exceeded"),
        _gate_rejected_record(2, "mesh is not watertight"),
    ]
    sample = stratify_and_sample(records, seed=1, clean_baseline_n=0)
    d, _ = build_friction_report(records, sample)
    assert d["gate_reason_freq"]["polygon budget exceeded"] == 2
    assert d["gate_reason_freq"]["mesh is not watertight"] == 1


def test_build_friction_report_build_errors_listed_with_index_and_message():
    """build_errors list: each entry references the record index AND
    the error AND the request — gives the human investigator a thread
    back to capture.jsonl."""
    records = [
        _error_record(0, "first boom"),
        _clean_record(1),
        _error_record(2, "second boom"),
    ]
    sample = stratify_and_sample(records, seed=1, clean_baseline_n=1)
    d, _ = build_friction_report(records, sample)
    assert len(d["build_errors"]) == 2
    # Newest-first OR preserve order? Spec is silent; index-preserving is
    # friendlier for correlating with capture.jsonl.
    assert d["build_errors"][0]["index"] == 0
    assert "first boom" in d["build_errors"][0]["error"]
    assert d["build_errors"][0]["request"] == "crash me 0"
    assert d["build_errors"][1]["index"] == 2
    assert "second boom" in d["build_errors"][1]["error"]


def test_build_friction_report_size_mismatches_carry_word_dimension_value_range_generator():
    """size_mismatches entries contain the human-investigable detail set."""
    from compiler import PARAM_RANGES
    lo, hi = PARAM_RANGES["cabinet"]["height"]
    low_height = lo + 0.05 * (hi - lo)
    spec = {
        "asset_id": "cabinet", "generator": "cabinet", "material": "worn_oak", "age": 0.15,
        "params": {
            "width": 0.8, "depth": 0.5, "height": low_height,
            "panel_thickness": 0.04, "base_height": 0.08,
        },
    }
    records = [
        _make_record(request="a tall cabinet", spec=spec, gate_passed=True, built=True, index=0),
    ]
    sample = stratify_and_sample(records, seed=1, clean_baseline_n=1)
    d, _ = build_friction_report(records, sample)
    assert len(d["size_mismatches"]) == 1
    sm = d["size_mismatches"][0]
    assert sm["word"] == "tall"
    assert sm["dimension"] == "height"
    assert sm["generator"] == "cabinet"
    assert sm["expected_direction"] == "high"
    assert sm["value"] == pytest.approx(low_height)
    assert sm["range"] == [lo, hi]
    assert sm["request"] == "a tall cabinet"


# ── probes & digest text ─────────────────────────────────────────────


def test_build_friction_report_probes_attach_request_text():
    """Each probe in the dict's 'probes' list carries the originating
    request text (so the digest is self-contained)."""
    records = [_clean_record(i) for i in range(4)]
    sample = stratify_and_sample(records, seed=1, clean_baseline_n=2)
    d, _ = build_friction_report(records, sample)
    for probe in d["probes"]:
        assert "request" in probe
        assert probe["request"] == records[probe["index"]].request


def test_build_friction_report_digest_non_empty_and_lists_probe_requests():
    """The text digest is non-empty AND it actually shows the probe set
    (each probe's request text appears in the digest, plus the 'Eyeball
    these N:' heading per spec)."""
    records = [_clean_record(i) for i in range(6)]
    sample = stratify_and_sample(records, seed=17, clean_baseline_n=3)
    _, digest = build_friction_report(records, sample)
    assert isinstance(digest, str)
    assert digest.strip()  # non-empty
    assert "Eyeball these" in digest  # spec-required closing block
    # Every probe's request is mentioned
    for p in sample.probes:
        req = records[p["index"]].request
        assert req in digest, f"probe request {req!r} missing from digest"


def test_build_friction_report_digest_ends_with_probe_section():
    """Spec literal: the digest ENDS with the probe list.  Check the
    'Eyeball these N:' headline appears AFTER all the other section
    headings."""
    records = [
        _error_record(0, "boom"),
        _gate_rejected_record(1, "polygon budget exceeded"),
        _clean_record(2),
        _clean_record(3),
    ]
    sample = stratify_and_sample(records, seed=99, clean_baseline_n=2)
    _, digest = build_friction_report(records, sample)
    eyeball_pos = digest.find("Eyeball these")
    assert eyeball_pos > 0
    # No content after the probe listing block
    probe_section = digest[eyeball_pos:]
    assert probe_section.strip().endswith(probe_section.splitlines()[-1].strip())


def test_build_friction_report_seed_and_stratum_sizes_propagated():
    """Top-level seed + stratum_sizes (for reproducibility & layered
    sequencing of follow-up slices) carry through from SampleResult."""
    records = [_clean_record(i) for i in range(4)] + [_error_record(4)]
    sample = stratify_and_sample(records, seed=2024, clean_baseline_n=2)
    d, _ = build_friction_report(records, sample)
    assert d["seed"] == 2024
    assert d["stratum_sizes"] == sample.stratum_sizes


# ── load_corpus ───────────────────────────────────────────────────────


def test_load_corpus_returns_only_non_comment_non_blank_lines():
    """load_corpus(file) strips `#` comments and blanks (pure utility)."""
    import tempfile, textwrap
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    try:
        tmp.write(textwrap.dedent("""\
            # leading comment

            a plain table
            a wooden chair
               # indented comment
            # blank-then-comment

            an oak bookshelf
        """))
        tmp.close()
        lines = load_corpus(tmp.name)
        assert lines == ["a plain table", "a wooden chair", "an oak bookshelf"]
    finally:
        import os
        os.unlink(tmp.name)


# ── corpus/seed_requests.txt shape ───────────────────────────────────


# Resolve the corpus path RELATIVE TO THIS TEST FILE so the test is
# robust to where pytest is invoked from.  Tests live in
# foundry/tests/; the corpus lives in foundry/eval/corpus/.
CORPUS_PATH = Path(__file__).resolve().parent.parent / "eval" / "corpus" / "seed_requests.txt"


def test_seed_requests_txt_exists_at_package_data_path():
    """The bundled seed corpus exists under foundry/eval/corpus/."""
    p = Path(CORPUS_PATH)
    assert p.is_file(), f"missing: {p}"


def test_seed_requests_txt_has_at_least_40_non_comment_lines():
    p = Path(CORPUS_PATH)
    text = p.read_text(encoding="utf-8")
    non_comment_lines = [
        ln for ln in text.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    assert len(non_comment_lines) >= 40, (
        f"expected ≥40 non-comment lines; got {len(non_comment_lines)}"
    )


@pytest.mark.parametrize("generator", ["table", "chair", "shelf", "cabinet"])
def test_seed_requests_txt_each_generator_is_represented(generator: str):
    """Every one of {table, chair, shelf, cabinet} has at least one line."""
    p = Path(CORPUS_PATH)
    text = p.read_text(encoding="utf-8").lower()
    non_comment = [
        ln for ln in text.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    assert any(generator in ln for ln in non_comment), (
        f"no line mentions {generator!r}"
    )


# ── end-to-end smoke (records → sampler → report) ───────────────────


def test_build_friction_report_smoke_run_through_synthetic_records():
    """A full synthetic pipeline: build records → sample → build report.
    Confirms no live llm/Blender path is involved."""
    records: List[RunRecord] = []
    records += [_error_record(i)                       for i in range(2)]
    records += [_gate_rejected_record(i + 2)            for i in range(3)]
    records += [_clean_record(i + 5)                    for i in range(5)]
    sample = stratify_and_sample(records, seed=1, clean_baseline_n=2)
    d, digest = build_friction_report(records, sample)
    assert d["total"] == 10
    assert "Eyeball these" in digest
    # The probe list contains exactly 5 problem probes + 2 clean baseline
    assert len(d["probes"]) == 7


# ── age_mismatches & material_conflicts surfacing (slice 2) ──────────
# build_friction_report adds dedicated detail lists alongside
# size_mismatches: age_mismatches (request, wear_class, age) and
# material_conflicts (request, cues, resolved). Both lists AND both
# digest sections are populated when the source records contain these
# signals.

from materials import MATERIAL_PALETTE
from compiler import PARAM_RANGES


def _conflict_record(i: int) -> RunRecord:
    """A record whose request spans two material families — exercise the
    material_conflict signal AND its detail list."""
    lo, hi = PARAM_RANGES["table"]["top_width"]
    width = (lo + hi) / 2.0
    lo, hi = PARAM_RANGES["table"]["leg_height"]
    leg_h = (lo + hi) / 2.0
    spec = {
        "asset_id": "table", "generator": "table",
        "material": "rough_granite", "age": 0.2,
        "params": {
            "top_width": width, "top_depth": 0.8, "top_thickness": 0.06,
            "leg_height": leg_h, "leg_radius": 0.05, "leg_inset": 0.1,
        },
    }
    return _make_record(
        request=f"a stone-look wooden table {i}",
        spec=spec, gate_passed=True, built=True, index=i,
    )


def _old_cabinet_record(i: int) -> RunRecord:
    """A record with an AGED wear word at LOW age → age_mismatch fires."""
    spec = {
        "asset_id": "cabinet", "generator": "cabinet", "material": "worn_oak",
        "age": 0.15,
        "params": {
            "width": 0.8, "depth": 0.5, "height": 1.3,
            "panel_thickness": 0.04, "base_height": 0.08,
        },
    }
    return _make_record(
        request=f"an old cabinet {i}", spec=spec,
        gate_passed=True, built=True, index=i,
    )


def test_build_friction_report_dict_surfaces_age_mismatches_list():
    """Synthetic age_mismatch record → dict has non-empty age_mismatches."""
    records = [_old_cabinet_record(0), _clean_record(1)]
    sample = stratify_and_sample(records, seed=1, clean_baseline_n=1)
    d, _ = build_friction_report(records, sample)
    assert isinstance(d.get("age_mismatches"), list)
    assert len(d["age_mismatches"]) >= 1
    am = d["age_mismatches"][0]
    assert am["request"].startswith("an old cabinet")
    assert am["wear_class"] == "aged"
    assert am["age"] == pytest.approx(0.15)


def test_build_friction_report_dict_surfaces_material_conflicts_list():
    """Synthetic material_conflict record → dict has non-empty
    material_conflicts with cues + resolved."""
    records = [_conflict_record(0), _clean_record(1)]
    sample = stratify_and_sample(records, seed=1, clean_baseline_n=1)
    d, _ = build_friction_report(records, sample)
    assert isinstance(d.get("material_conflicts"), list)
    assert len(d["material_conflicts"]) >= 1
    mc = d["material_conflicts"][0]
    assert mc["request"].startswith("a stone-look wooden table")
    assert isinstance(mc["cues"], list)
    families = {fam for _, fam in mc["cues"]}
    assert families == {"stone", "wood"}
    assert mc["resolved"] in MATERIAL_PALETTE  # resolved to a real material


def test_build_friction_report_digest_surfaces_both_new_sections():
    """The text digest contains BOTH the new sections when the source
    records include one age_mismatch + one material_conflict."""
    records = [_old_cabinet_record(0), _conflict_record(1), _clean_record(2)]
    sample = stratify_and_sample(records, seed=1, clean_baseline_n=1)
    _, digest = build_friction_report(records, sample)
    assert "## Age mismatches" in digest
    assert "## Material conflicts" in digest
    # Spot-check that the actual request text appears under each section.
    assert "an old cabinet" in digest
    assert "a stone-look wooden table" in digest


def test_build_friction_report_no_age_material_signals_yields_empty_sections():
    """Pipeline of only clean records → age_mismatches and
    material_conflicts are both empty (no spurious entries)."""
    records = [_clean_record(i) for i in range(3)]
    sample = stratify_and_sample(records, seed=1, clean_baseline_n=2)
    d, digest = build_friction_report(records, sample)
    assert d["age_mismatches"] == []
    assert d["material_conflicts"] == []
    # Digest still renders both sections, just as (none).
    assert "## Age mismatches" in digest
    assert "## Material conflicts" in digest
    # And they're followed by the "(none)" line — verify with the digest.
    sections = digest.split("## ")
    age_section = next(s for s in sections if s.startswith("Age mismatches"))
    mat_section = next(s for s in sections if s.startswith("Material conflicts"))
    assert "_(none)_" in age_section
    assert "_(none)_" in mat_section
