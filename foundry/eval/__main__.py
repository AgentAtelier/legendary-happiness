"""CLI for the foundry eval harness.

Usage (from the repo root):
    PYTHONPATH=. foundry/.venv/bin/python -m foundry.eval run \\
        foundry/eval/corpus/seed_requests.txt \\
        foundry/library/asset_lexicon.json \\
        /tmp/eval-out \\
        [--no-build] [--seed 1337] [--baseline 10]

Subcommands: run | stability | regression | augment.

Mirrors foundry/__main__.py's sys.path pattern so bare imports
(`from compiler import ...`, `from planner import ...`, ...) resolve
under `python -m foundry.eval`.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Mirror foundry/__main__.py: insert the package directory onto sys.path
# so bare imports resolve from BOTH `python -m foundry.eval` (repo root)
# and `cd foundry && python -m foundry.eval`.
_foundry_dir = str(Path(__file__).resolve().parent.parent)
if _foundry_dir not in sys.path:
    sys.path.insert(0, _foundry_dir)


def _configure_logging() -> None:
    """0.9b: configure the root logger once at CLI entry.

    Honours ``FORGE_LOG_LEVEL`` so operators can dial verbosity without
    code changes; default INFO.  Safe to call multiple times — basicConfig
    is a no-op once a handler is attached (sub-entry-points inherit the
    level set here).
    """
    logging.basicConfig(
        level=os.environ.get("FORGE_LOG_LEVEL", "INFO"),
        format="%(levelname)s:%(name)s:%(message)s",
    )


def _cmd_augment(args: argparse.Namespace) -> int:
    from eval.augment import augment_corpus

    logger.info(
        "target=%d  seed=%d  dry_run=%s",
        args.target, args.seed, args.dry_run,
    )

    requests, stats = augment_corpus(
        args.out_file,
        target=args.target,
        seed=args.seed,
        dry_run=args.dry_run,
    )

    logger.info(
        "generated %d raw, %d unique, %d valid (%d rejected)",
        stats['raw_generated'], stats['unique_after_dedup'],
        stats['valid'], stats['rejected_by_validity'],
    )
    logger.info("decision firers: %d", stats['decision_firers'])
    logger.info("dedup rate: %.1f%%", stats['dedup_rate'] * 100)
    logger.info("generator counts: %s", stats['generator_counts'])
    if not args.dry_run:
        logger.info("wrote %s", args.out_file)
    return 0


def _cmd_augment_quest(args: argparse.Namespace) -> int:
    """Generate a fetch-quest corpus — room-themed prompts for the full
    quest pipeline (P6)."""
    from eval.augment import _NPC_ROLES, augment_quest_corpus

    logger.info(
        "target=%d  seed=%d  dry_run=%s",
        args.target, args.seed, args.dry_run,
    )

    # Build a default manifest from the existing test fixture so the CLI
    # works standalone without a live asset-gen run.
    manifest = [
        {"id": "table_0", "category": "table", "material": "worn_oak",
         "x": 1.0, "y": 0.0, "z": -1.5},
        {"id": "shelf_0", "category": "shelf", "material": "rough_granite",
         "x": -2.0, "y": 0.0, "z": -3.0},
        {"id": "cabinet_0", "category": "cabinet", "material": "wrought_iron",
         "x": 2.5, "y": 0.0, "z": -2.0},
        {"id": "table_1", "category": "table", "material": "worn_oak",
         "x": -1.0, "y": 0.0, "z": -0.5},
    ]

    requests, stats = augment_quest_corpus(
        args.out_file,
        manifest=manifest,
        target=args.target,
        seed=args.seed,
        dry_run=args.dry_run,
    )

    logger.info(
        "generated %d raw, %d unique, %d valid (%d rejected)",
        stats['raw_generated'], stats['unique_after_dedup'],
        stats['valid'], stats['rejected_by_validity'],
    )
    logger.info("decision firers: %d", stats['decision_firers'])
    logger.info("dedup rate: %.1f%%", stats['dedup_rate'] * 100)
    logger.info(
        "role coverage: %d/%d roles",
        len(stats['role_counts']), len(_NPC_ROLES),
    )
    if not args.dry_run:
        logger.info("wrote %s", args.out_file)
    return 0


def _cmd_stability(args: argparse.Namespace) -> int:
    from eval.report import load_corpus
    from eval.stability import build_report_dict, build_report_md, run_stability

    requests = load_corpus(args.corpus)
    if not requests:
        print(f"error: corpus {args.corpus!r} is empty (after skipping "
              f"comments/blanks).", file=sys.stderr)
        return 2

    logger.info(
        "corpus=%s  requests=%d  runs=%d  seed=%d",
        args.corpus, len(requests), args.runs, args.seed,
    )

    # Stub LLM by default; --live wires in FoundryLLM for real qwen
    # variance measurement (the point of this lens).
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

    logger.info(
        "score=%.1f%%  stable=%d/%d",
        score * 100, report_dict['stable_count'], report_dict['total'],
    )
    logger.info("wrote %s", out_dir / 'report.json')
    logger.info("wrote %s", out_dir / 'report.md')
    return 0


def _cmd_regression(args: argparse.Namespace) -> int:
    from eval.regression import build_report_dict, build_report_md, run_regression
    from eval.report import load_corpus

    requests = load_corpus(args.corpus)
    if not requests:
        print(f"error: corpus {args.corpus!r} is empty (after skipping "
              f"comments/blanks).", file=sys.stderr)
        return 2

    expectations_dir = args.expectations or str(Path(args.out_dir) / "expectations")

    if args.live:
        try:
            from llm import FoundryLLM
        except Exception as exc:
            print(f"error: could not import FoundryLLM: {exc}", file=sys.stderr)
            return 3
        llm = FoundryLLM()
    else:
        llm = _stub_llm()

    logger.info(
        "corpus=%s  requests=%d  expectations=%s  update=%s",
        args.corpus, len(requests), expectations_dir, args.update,
    )

    results, score = run_regression(
        requests,
        expectations_dir,
        llm=llm,
        update=args.update,
    )

    report_dict = build_report_dict(results, score)
    digest = build_report_md(report_dict)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(report_dict, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "report.md").write_text(digest, encoding="utf-8")

    logger.info(
        "score=%.1f%%  hard_pass=%d  hard_fail=%d",
        score['score'] * 100, score['hard_pass'], score['hard_fail'],
    )
    logger.info("wrote %s", out_dir / 'report.json')
    logger.info("wrote %s", out_dir / 'report.md')
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from eval.harness import records_to_jsonl, run_corpus
    from eval.report import build_friction_report, load_corpus
    from eval.sampler import stratify_and_sample
    from eval.signals import compute_signals

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

    logger.info(
        "corpus=%s  requests=%d  build=%s  seed=%d  baseline=%d  library_dir=%s",
        args.corpus, len(requests), build, args.seed, args.baseline, args.library_dir,
    )

    records = run_corpus(
        requests=requests,
        llm=llm,
        lexicon_path=args.lexicon,
        library_dir=args.library_dir,
        build=build,
    )

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

    logger.info("wrote %s", out_dir / 'capture.jsonl')
    logger.info("wrote %s", out_dir / 'report.json')
    logger.info("wrote %s", out_dir / 'report.md')
    logger.info("wrote %s", out_dir / 'probes.json')
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
        description="Foundry eval harness.",
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

    reg = sub.add_parser("regression", help="compare planner output against golden expectations")
    reg.add_argument("corpus", help="path to a corpus file (one request per line, '#' = comment)")
    reg.add_argument("lexicon", help="path to the asset lexicon JSON (not used — consistency)")
    reg.add_argument("out_dir", help="directory to write report.json and report.md")
    reg.add_argument("--expectations", default=None,
                     help="expectations directory (default: <out_dir>/expectations)")
    reg.add_argument("--update", action="store_true",
                     help="re-bless expectations from current planner output")
    reg.add_argument("--live", action="store_true",
                     help="use FoundryLLM (default: stub)")
    reg.set_defaults(func=_cmd_regression)

    aug = sub.add_parser("augment", help="generate augmented corpus via slot-filling")
    aug.add_argument("out_file", help="path to write the augmented corpus .txt")
    aug.add_argument("--target", type=int, default=250,
                     help="max requests to produce (default 250)")
    aug.add_argument("--seed", type=int, default=1337,
                     help="RNG seed (default 1337)")
    aug.add_argument("--dry-run", action="store_true",
                     help="print stats without writing")
    aug.set_defaults(func=_cmd_augment)

    aug_quest = sub.add_parser("augment-quest",
                               help="generate fetch-quest corpus (room-themed prompts)")
    aug_quest.add_argument("out_file",
                           help="path to write the quest corpus .txt")
    aug_quest.add_argument("--target", type=int, default=60,
                           help="max room themes to produce (default 60)")
    aug_quest.add_argument("--seed", type=int, default=1337,
                           help="RNG seed (default 1337)")
    aug_quest.add_argument("--dry-run", action="store_true",
                           help="print stats without writing")
    aug_quest.set_defaults(func=_cmd_augment_quest)

    return p


def main() -> int:
    _configure_logging()
    parser = _build_parser()
    args = parser.parse_args()
    # Default library_dir (when not passed) to <out_dir>/library so forge
    # outputs land in a clean subdir, NOT mixed with the report files.
    if getattr(args, "library_dir", None) is not None and not args.library_dir:
        args.library_dir = str(Path(args.out_dir) / "library")
    return args.func(args)


sys.exit(main())
