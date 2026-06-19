"""foundry.eval.report — friction report builder (slice 1).

``build_friction_report(records, sample) -> (dict, str)`` aggregates the
outcomes of one corpus run into:

    - a machine dict with a known schema (for tooling, regression tests,
      and downstream layers to consume programmatically)
    - a markdown digest ENDS with the probe list ("Eyeball these N:")

``load_corpus(path)`` strips `#` comments and blanks, returning the
list of NL requests the CLI will feed to ``run_corpus``.

Lenses stack: this is lens 1 (the cheapest).  Future slices add
quality, regression, and journey lenses on top of the same core.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import List, Tuple

from eval.harness import RunRecord
from eval.sampler import SampleResult
from eval.signals import (
    age_mismatch_detail,
    compute_signals,
    decision_codes,
    material_conflict_detail,
    size_mismatch_detail,
)


# ── Public entry points ───────────────────────────────────────────────


def build_friction_report(
    records: List[RunRecord], sample: SampleResult
) -> Tuple[dict, str]:
    """Build the (machine dict, markdown digest) pair for one run.

    Args:
        records: Full population of RunRecords from ``run_corpus``.
        sample: ``SampleResult`` from ``stratify_and_sample`` — used
            for stratum_sizes, seed, and the probe list.

    Returns:
        Tuple of (report_dict, digest_str).  See ``_build_dict`` for
        the dict schema; ``_build_digest`` for the markdown sections.
    """
    report_dict = _build_dict(records, sample)
    digest = _build_digest(report_dict)
    return report_dict, digest


def load_corpus(path: str) -> List[str]:
    """Read the corpus file at *path*.  Skip blank lines and lines whose
    first non-whitespace character is ``#``.  Strip each kept line.

    Returns the NL requests to feed to ``run_corpus``.
    """
    out: List[str] = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


# ── Dict assembly ─────────────────────────────────────────────────────


def _build_dict(records: List[RunRecord], sample: SampleResult) -> dict:
    """Compute every named key in the spec's report schema."""

    # ── signal_counts: tag → how-many records carry it ───────────────
    signal_counter: Counter[str] = Counter()
    for rec in records:
        for tag in compute_signals(rec):
            signal_counter[tag] += 1

    # ── decision_code_freq: code → how-many decisions have that code ─
    decision_counter: Counter[str] = Counter()
    for rec in records:
        decision_counter.update(decision_codes(rec))

    # ── gate_reason_freq: reason → how-many records list it in gate_reasons
    reason_counter: Counter[str] = Counter()
    for rec in records:
        for r in (rec.gate_reasons or []):
            reason_counter[r] += 1

    # ── build_errors: per-record summary {request, error, index} ─────
    build_errors: List[dict] = []
    for idx, rec in enumerate(records):
        if rec.error:
            build_errors.append({
                "index": idx,
                "request": rec.request,
                "error": rec.error,
            })

    # ── size_mismatches: per-record detail from signals helper ───────
    size_mismatches: List[dict] = []
    for idx, rec in enumerate(records):
        if rec.spec is None:
            continue
        detail = size_mismatch_detail(rec.request, rec.spec)
        if detail is None:
            continue
        size_mismatches.append({
            "index": idx,
            "request": rec.request,
            **detail,
        })

    # ── age_mismatches (slice 2): per-record detail from signals helper
    age_mismatches: List[dict] = []
    for idx, rec in enumerate(records):
        if rec.spec is None:
            continue
        detail = age_mismatch_detail(rec.request, rec.spec)
        if detail is None:
            continue
        age_mismatches.append({
            "index": idx,
            "request": rec.request,
            **detail,
        })

    # ── material_conflicts (slice 2): per-record detail from signals
    #    helper.  Pure request-level — no spec gating required.
    material_conflicts: List[dict] = []
    for idx, rec in enumerate(records):
        detail = material_conflict_detail(rec.request)
        if detail is None:
            continue
        material_conflicts.append({
            "index": idx,
            **detail,
        })

    # ── probes: enrich the SampleResult's probe objects with the
    #      actual request text so the digest is self-contained.
    probes = []
    for p in sample.probes:
        idx = p["index"]
        probes.append({
            **p,
            "index": idx,
            "request": records[idx].request if 0 <= idx < len(records) else "",
        })

    return {
        "total":               len(records),
        "signal_counts":       dict(signal_counter),
        "decision_code_freq":  dict(decision_counter),
        "gate_reason_freq":    dict(reason_counter),
        "build_errors":        build_errors,
        "size_mismatches":     size_mismatches,
        "age_mismatches":      age_mismatches,
        "material_conflicts":  material_conflicts,
        "probes":              probes,
        "stratum_sizes":       dict(sample.stratum_sizes),
        "seed":                sample.seed,
    }


# ── Digest assembly ───────────────────────────────────────────────────


def _build_digest(d: dict) -> str:
    """Render an *human-readable* markdown digest of *d*.  Sections in
    fixed order, the probe list CLOSES the digest per spec."""
    lines: List[str] = []
    lines.append("# Foundry Eval — Friction Report")
    lines.append("")
    lines.append(f"- **Total runs:** {d['total']}")
    lines.append(f"- **Seed:** {d['seed']}")
    lines.append(f"- **Probes selected:** {len(d['probes'])}")
    if d.get("stratum_sizes"):
        joined = ", ".join(f"{k}={v}" for k, v in sorted(d["stratum_sizes"].items()))
        lines.append(f"- **Stratum sizes:** {joined}")
    lines.append("")

    # Signal counts
    lines.append("## Signal counts")
    sc = d.get("signal_counts") or {}
    if not sc:
        lines.append("_(no signals computed)_")
    else:
        for tag in sorted(sc):
            lines.append(f"- {tag} — {sc[tag]}")
    lines.append("")

    # Decision-Point frequency
    lines.append("## Decision-Point frequency")
    dcf = d.get("decision_code_freq") or {}
    if not dcf:
        lines.append("_(no Decision Points fired)_")
    else:
        for code in sorted(dcf):
            lines.append(f"- {code} — {dcf[code]}")
    lines.append("")

    # Gate-reason histogram
    lines.append("## Gate-rejection reasons")
    grf = d.get("gate_reason_freq") or {}
    if not grf:
        lines.append("_(no gate rejections)_")
    else:
        for reason in sorted(grf, key=lambda r: (-grf[r], r)):
            lines.append(f"- {reason} — {grf[reason]}")
    lines.append("")

    # Build errors
    lines.append("## Build errors")
    errs = d.get("build_errors") or []
    if not errs:
        lines.append("_(none)_")
    else:
        for e in errs:
            lines.append(f"- `\"{e['request']}\"` — `{e['error']}`")
    lines.append("")

    # Size mismatches (human-auditable detail)
    lines.append("## Size mismatches")
    sms = d.get("size_mismatches") or []
    if not sms:
        lines.append("_(none)_")
    else:
        for sm in sms:
            lo, hi = sm["range"][0], sm["range"][1]
            lines.append(
                f"- `\"{sm['request']}\"` — word `{sm['word']}` expects "
                f"`{sm['expected_direction'].upper()}` on `{sm['dimension']}` "
                f"(generator={sm['generator']}), but got {sm['value']:.3f} "
                f"(range [{lo:.2f}, {hi:.2f}])."
            )
    lines.append("")

    # Age mismatches (slice 2) — paired request + wear-class + age.
    lines.append("## Age mismatches")
    ams = d.get("age_mismatches") or []
    if not ams:
        lines.append("_(none)_")
    else:
        for am in ams:
            lines.append(
                f"- `\"{am['request']}\"` — wear={am['wear_class']}, "
                f"but age={am['age']:.3f}."
            )
    lines.append("")

    # Material conflicts (slice 2) — competing cues + planner's resolution.
    lines.append("## Material conflicts")
    mcs = d.get("material_conflicts") or []
    if not mcs:
        lines.append("_(none)_")
    else:
        for mc in mcs:
            cue_str = ", ".join(f"{kw}→{fam}" for kw, fam in mc["cues"])
            lines.append(
                f"- `\"{mc['request']}\"` — competing cues ({cue_str}); "
                f"resolved to {mc['resolved']}."
            )
    lines.append("")

    # Probe list — ALWAYS LAST per spec
    lines.append(f"## Eyeball these {len(d['probes'])} (probe set)")
    lines.append("")
    for i, p in enumerate(d["probes"], start=1):
        strata_desc = ", ".join(p["strata"]) if p.get("strata") else "—"
        lines.append(f"{i}. `\"{p['request']}\"` — why: {p.get('reason', strata_desc)}")

    return "\n".join(lines) + "\n"
