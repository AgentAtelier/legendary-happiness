"""foundry.eval.harness — the autonomous eval harness core (slice 1).

``run_corpus`` drives a list of NL requests through the planner (and,
optionally, the full forge chain) and captures a ``RunRecord`` per
request.  ``llm``, ``plan``, and ``forge`` are injectable so tests can
exercise the whole flow with fakes — no llama.cpp, no Blender.

A failure in plan() or forge() for ONE request is captured into that
record's ``error`` field and the loop CONTINUES; ``run_corpus`` itself
never raises.  A failure is a *signal*, not a crash.
"""

from __future__ import annotations

import json
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple


# ── RunRecord ──────────────────────────────────────────────────────────


@dataclass
class RunRecord:
    """The structured outcome of one NL request through the chain."""

    request: str
    spec: Optional[dict]
    decisions: List[dict]
    gate_passed: Optional[bool]
    gate_reasons: List[str]
    built: bool
    error: Optional[str]
    glb_path: Optional[str]
    seconds: float


@dataclass
class QuestRecord:
    """The structured outcome of one room theme through the quest pipeline
    (behaviour-gen → scene-compile).  Mirrors RunRecord for the quest layer."""

    room_theme: str
    quest_spec: Optional[dict]
    decisions: List[dict]
    compiled: bool
    scene_path: Optional[str]
    manifest: List[dict]
    error: Optional[str]
    seconds: float


# ── JSON serialisation helpers ─────────────────────────────────────────


def record_to_dict(r: RunRecord) -> dict:
    """JSON-friendly dict view of a RunRecord."""
    return asdict(r)


def quest_record_to_dict(qr: QuestRecord) -> dict:
    """JSON-friendly dict view of a QuestRecord."""
    return asdict(qr)


def records_to_jsonl(records: List[RunRecord]) -> str:
    """One JSON object per line, newline-terminated, no trailing commas."""
    return "\n".join(json.dumps(record_to_dict(r)) for r in records) + "\n"


def quest_records_to_jsonl(records: List[QuestRecord]) -> str:
    """One JSON object per line for QuestRecords."""
    return "\n".join(json.dumps(quest_record_to_dict(qr)) for qr in records) + "\n"


# ── Defaults (lazy: not imported at module load) ───────────────────────


def _default_plan(
    request: str, llm: Callable[[str, Optional[str]], str]
) -> Tuple[dict, List]:
    """Import AssetPlanner lazily so tests injecting ``plan`` don't pull
    Blender/llama paths."""
    from planner import AssetPlanner
    return AssetPlanner().plan(request, llm)


def _default_forge(
    spec_path: str, lexicon_path: str, library_dir: str
):
    """Import runner lazily — same reason as _default_plan."""
    from runner import forge
    return forge(spec_path, lexicon_path, library_dir)


# ── Public entry point ─────────────────────────────────────────────────


def run_corpus(
    requests: List[str],
    llm: Callable[[str, Optional[str]], str],
    lexicon_path: str,
    library_dir: str,
    *,
    build: bool = True,
    plan: Optional[Callable[..., Tuple[dict, List]]] = None,
    forge: Optional[Callable[[str, str, str], Any]] = None,
) -> List[RunRecord]:
    """Run *requests* through the foundry pipeline, capturing structured
    records.  NEVER raises out of the per-request loop.

    Args:
        requests: NL asset descriptions.
        llm: Callable (prompt, grammar) -> str — injected for tests.
        lexicon_path: Path to the asset lexicon (for forge, when build=True).
        library_dir: Asset library dir (for forge, when build=True).
        build: When True, every spec is forged (calls Blender).  When
               False, only the planner runs — fast planner-only signal runs.
        plan: Optional override for the planner; defaults to
              ``AssetPlanner().plan``.  Must return ``(spec, decisions)``
              where ``decisions`` is an iterable of ``DecisionPoint`` instances.
        forge: Optional override for the forge fn; defaults to
               ``runner.forge``.

    Returns:
        One ``RunRecord`` per request (same order).  An exception for one
        request lands in that record's ``error`` field and the loop
        continues — ``run_corpus`` itself does NOT raise.
    """
    if plan is None:
        plan = _default_plan
    if forge is None:
        forge = _default_forge

    # Imported lazily so a caller passing ``decisions`` as already-dicts
    # (e.g. from a test fixture) still serialises cleanly.  The outer
    # try/except in the per-request body catches real failures.
    try:
        from decisions import to_dict as _decision_to_dict
        _serialize_decision = _decision_to_dict
    except ImportError:
        # tests injecting fake decisions without an engine stack can
        # pass through; if decisions aren't to_dict-able, the outer
        # try/except catches the per-record failure.
        _serialize_decision = lambda d: {"repr": repr(d)}  # noqa: E731

    records: List[RunRecord] = []
    for request in requests:
        t0 = time.perf_counter()
        record = RunRecord(
            request=request,
            spec=None,
            decisions=[],
            gate_passed=None,
            gate_reasons=[],
            built=False,
            error=None,
            glb_path=None,
            seconds=0.0,
        )

        try:
            spec, decisions = plan(request, llm)
            # Capture decisions as plain dicts so the record is JSON-safe.
            record.decisions = [_serialize_decision(d) for d in decisions]
            record.spec = spec

            if build:
                # Write the spec to a temp json file so forge() can read it.
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", delete=False, encoding="utf-8"
                ) as f:
                    json.dump(spec, f)
                    spec_path = f.name
                try:
                    forge_result = forge(spec_path, lexicon_path, library_dir)
                    gate = getattr(forge_result, "gate", None)
                    record.built = True
                    record.gate_passed = gate.passed if gate is not None else None
                    record.gate_reasons = list(gate.reasons) if gate is not None else []
                    record.glb_path = getattr(forge_result, "glb_path", None)
                finally:
                    Path(spec_path).unlink(missing_ok=True)

        except Exception as exc:
            # Wrap per-request failure into the record; never raise out.
            record.error = repr(exc)

        record.seconds = time.perf_counter() - t0
        records.append(record)

    return records


# ── Quest pipeline entry point (P6) ───────────────────────────────────

def run_quest_corpus(
    room_themes: List[str],
    manifest: List[dict],
    llm: Callable[[str, Optional[str]], str],
    scene_output_dir: str,
    *,
    plan_quest: Optional[Callable[..., Tuple[dict, List]]] = None,
    compile_scene_fn: Optional[Callable[..., str]] = None,
) -> List[QuestRecord]:
    """Run *room_themes* through the quest pipeline, capturing structured
    records.  NEVER raises out of the per-request loop.

    Args:
        room_themes: NL room descriptions (e.g. "a hermit's shack").
        manifest: Placed-entity manifest (list of dicts with id, category,
                  material, x/y/z).  Shared across all room themes.
        llm: Callable (prompt, grammar) -> str — injected for tests.
        scene_output_dir: Directory for compiled .tscn files.
        plan_quest: Optional override for QuestBehaviourPlanner().plan.
        compile_scene_fn: Optional override for compile_scene.

    Returns:
        One ``QuestRecord`` per room theme (same order).  An exception
        for one theme lands in that record's ``error`` field and the
        loop continues.
    """
    if plan_quest is None:
        from behaviour_gen import QuestBehaviourPlanner
        _planner = QuestBehaviourPlanner()
        plan_quest = _planner.plan
    if compile_scene_fn is None:
        from scene_compiler import compile_scene as _compile_scene
        compile_scene_fn = _compile_scene

    try:
        from decisions import to_dict as _decision_to_dict
        _serialize_decision = _decision_to_dict
    except ImportError:
        _serialize_decision = lambda d: {"repr": repr(d)}

    records: List[QuestRecord] = []
    for idx, theme in enumerate(room_themes):
        t0 = time.perf_counter()
        record = QuestRecord(
            room_theme=theme,
            quest_spec=None,
            decisions=[],
            compiled=False,
            scene_path=None,
            manifest=manifest,
            error=None,
            seconds=0.0,
        )

        try:
            spec, decisions = plan_quest(theme, manifest, llm)
            record.quest_spec = spec
            record.decisions = [_serialize_decision(d) for d in decisions]

            scene_path = str(Path(scene_output_dir) / f"quest_{idx}.tscn")
            compile_scene_fn(spec, manifest, scene_path)
            record.compiled = True
            record.scene_path = scene_path

        except Exception as exc:
            record.error = repr(exc)

        record.seconds = time.perf_counter() - t0
        records.append(record)

    return records
