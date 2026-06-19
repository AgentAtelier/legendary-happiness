"""CLI for the foundry eval harness.

Usage (from the repo root):
    PYTHONPATH=. foundry/.venv/bin/python -m foundry.eval run \\
        foundry/eval/corpus/seed_requests.txt \\
        foundry/library/asset_lexicon.json \\
        /tmp/eval-out \\
        [--no-build] [--seed 1337] [--baseline 10]

Or from inside foundry/:
    .venv/bin/python -m foundry.eval run \\
        eval/corpus/seed_requests.txt \\
        library/asset_lexicon.json \\
        /tmp/eval-out

Mirrors foundry/__main__.py's sys.path pattern so bare imports
(`from compiler import ...`, `from planner import ...`, ...) resolve
under `python -m foundry.eval`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Mirror foundry/__main__.py: insert the package directory onto sys.path
# so bare imports resolve from BOTH `python -m foundry.eval` (repo root)
# and `cd foundry && python -m foundry.eval`.
_foundry_dir = str(Path(__file__).resolve().parent.parent)
if _foundry_dir not in sys.path:
    sys.path.insert(0, _foundry_dir)


# ── Subcommand: `run <corpus> <lexicon> <out_dir> ────────────────────


def _cmd_stability(args: argparse.Namespace) -> int:
    from eval.report import load_corpus
    from eval.stability import run_stability, build_report_dict, build_report_md

    requests = load_corpus(args.corpus)
    if not requests:
        print(f"error: corpus {args.corpus!r} is empty (after skipping "
              f"comments/blanks).", file=sys.stderr)
        return 2

    print(f"[stability] corpus={args.corpus}  requests={len(requests)}  "
          f"runs={args.runs}  seed={args.seed}")

    # Use stub LLM by default; --live wires in FoundryLLM for real
    # qwen variance measurement (the point of this lens).
    if args.live:
        try:
            from llm import FoundryLLM
        except Exception as exc:
            print(f"error: could not import FoundryLLM: {exc}", file=sys.stderr)
            return 3
        llm = FoundryLLM()
    else:
        llm = _stub_llm()

    per_request, score = run_stability(
        requests,
        runs=args.runs,
        seed=args.seed,
        llm=llm,
    )

    report_dict = build_report_dict(
        per_request, score, args.runs, args.seed, len(requests)
    )
    digest = build_report_md(report_dict)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(report_dict, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "report.md").write_text(digest, encoding="utf-8")

    print(f"[stability] score={score:.1%}  "
          f"stable={report_dict['stable_count']}/{report_dict['total']}")
    print(f"[stability] wrote {out_dir/'report.json'}")
    print(f"[stability] wrote {out_dir/'report.md'}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from eval.harness import run_corpus, records_to_jsonl
    from eval.signals import compute_signals
    from eval.sampler import stratify_and_sample
    from eval.report import build_friction_report, load_corpus

    # --no-build actually toggles (positive build=False).
    build = not args.no_build

    # Imports of production llm are lazy so a unit test that imports
    # only the parser (no run) doesn't require llama on :8002.
    if build:
        try:
            from llm import FoundryLLM  # type: ignore
        except Exception as exc:
            print(f"error: could not import FoundryLLM: {exc}", file=sys.stderr)
            return 3
        llm = FoundryLLM()
    else:
        # --no-build: the planner still needs an llm — pass a stub that
        # returns a known-good JSON spec.  No live network call required.
        llm = _stub_llm()

    requests = load_corpus(args.corpus)
    if not requests:
        print(f"error: corpus {args.corpus!r} is empty (after skipping "
              f"comments/blanks).", file=sys.stderr)
        return 2

    print(f"[eval] corpus={args.corpus}  requests={len(requests)}  "
          f"build={build}  seed={args.seed}  baseline={args.baseline}  "
          f"library_dir={args.library_dir}")

    records = run_corpus(
        requests=requests,
        llm=llm,
        lexicon_path=args.lexicon,
        library_dir=args.library_dir,
        build=build,
    )

    # We don't actually need the captures for `findry.eval`, but the
    # sampler needs the signals.  Pre-compute once here so we don't
    # re-derive under sampler.
    sample = stratify_and_sample(
        records,
        seed=args.seed,
        clean_baseline_n=args.baseline,
        signals_fn=compute_signals,
    )

    report_dict, digest = build_friction_report(records, sample)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if build:
        Path(args.library_dir).mkdir(parents=True, exist_ok=True)

    (out_dir / "capture.jsonl").write_text(records_to_jsonl(records), encoding="utf-8")
    (out_dir / "report.json").write_text(
        json.dumps(report_dict, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "report.md").write_text(digest, encoding="utf-8")
    (out_dir / "probes.json").write_text(
        json.dumps(report_dict["probes"], indent=2) + "\n", encoding="utf-8"
    )

    print(f"[eval] wrote {out_dir/'capture.jsonl'}")
    print(f"[eval] wrote {out_dir/'report.json'}")
    print(f"[eval] wrote {out_dir/'report.md'}")
    print(f"[eval] wrote {out_dir/'probes.json'}")
    return 0


def _stub_llm():
    """A trivial on-spec stub for `--no-build` runs.  Returns a table
    spec valid against ``compile_spec`` so the parser/clamp stages
    don't blow up.  Tests / fixture runs that go through this stub
    never hit llama.cpp."""
    import json as _json
    table_spec = _json.dumps({
        "asset_id": "table",
        "generator": "table",
        "params": {
            "top_width": 1.2, "top_depth": 0.7, "top_thickness": 0.05,
            "leg_height": 0.55, "leg_radius": 0.04, "leg_inset": 0.08,
        },
    })
    def _stub(prompt: str, grammar):
        return table_spec
    return _stub


# ── CLI definition ──────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m foundry.eval",
        description="Foundry eval harness (slice 1).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="drive a corpus through the harness")
    run.add_argument("corpus", help="path to a corpus file (one request per line, '#' = comment)")
    run.add_argument("lexicon", help="path to the asset lexicon JSON")
    run.add_argument("out_dir", help="directory to write capture.jsonl, report.json, report.md, probes.json")
    run.add_argument("--no-build", action="store_true",
                     help="skip the Blender build (planner-only signal runs)")
    run.add_argument("--seed", type=int, default=1337,
                     help="RNG seed for the sampler (default 1337)")
    run.add_argument("--baseline", type=int, default=10,
                     help="number of clean-stratum baseline probes (default 10)")
    run.add_argument("--library-dir", default="",
                     help="where forge writes .glb assets (default: <out_dir>/library)")
    run.set_defaults(func=_cmd_run)
    stab = sub.add_parser("stability", help="measure run-to-run planner variance")
    stab.add_argument("corpus", help="path to a corpus file (one request per line, '#' = comment)")
    stab.add_argument("lexicon", help="path to the asset lexicon JSON (not used — consistency with 'run')")
    stab.add_argument("out_dir", help="directory to write report.json and report.md")
    stab.add_argument("--runs", type=int, default=5,
                       help="number of planner runs per request (default 5)")
    stab.add_argument("--seed", type=int, default=1337,
                       help="RNG seed echoed in report (default 1337)")
    stab.add_argument("--live", action="store_true",
                       help="use FoundryLLM (default: stub — always-stable)")
    stab.set_defaults(func=_cmd_stability)
    return p


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    # Default library_dir (when the user did not pass --library-dir) to
    # <out_dir>/library so forge outputs land in a clean subdir, NOT
    # mixed with the report files.  Empties ("") from argparse defaults
    # trigger this fallback the same way as a missing flag.
    if not args.library_dir:
        args.library_dir = str(Path(args.out_dir) / "library")
    return args.func(args)


sys.exit(main())
