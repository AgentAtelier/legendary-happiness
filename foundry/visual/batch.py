"""V Task 5: Batch driver for the visual-eval loop.

Orchestrates one session that:
  (A) Iterates the prop library → capture → VLM check + CLIP score →
      catalog report (worst-first).
  (B) Renders a golden scene set (+ sampled new) → capture → check +
      score → regression diff vs baseline.

Amortizes the VLM by loading Qwen3-VL once.  Flags → regen worklist
(``visual_worklist.json``).

CB-8 / V Task 6: ``reroll_flagged()`` reads the worklist and regenerates
flagged props through the forge pipeline, creating a closed auto-reroll
loop (each rerun reduces the worklist until max_rerolls is hit).

CLI entry: ``python -m foundry visual-eval``
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

# Inspection prompts. Phrased to make the VLM report what it ACTUALLY sees
# (rather than rubber-stamp "looks fine"), and to flag an empty/blank frame —
# the failure mode a broken render produces.
PROP_PROMPT = (
    "You are inspecting a single 3D prop render on a plain background. "
    "Report only what you actually see. If the frame is blank or no object is "
    "visible, set textured=false and material_reads_right=false and note 'blank'. "
    "Flag holes or deformities, missing/incorrect texture, and floating "
    "disconnected bits."
)
SCENE_PROMPT = (
    "You are inspecting a screenshot of a generated 3D room. Report only what "
    "you actually see. Flag floating objects, geometry clipping through walls or "
    "floor, a missing or broken ceiling, characters not standing on the floor, "
    "an incoherent theme, and poor composition."
)


# ── Public API ───────────────────────────────────────────────────

def run_batch(
    *,
    out_dir: str,
    library_dir: str | None = None,
    builds_dir: str | None = None,
    baseline_path: str | None = None,
    angles: List[float] | None = None,
    catalog: bool = True,
    scenes: bool = True,
    # Injectables for testing (default = real modules)
    _capture_prop=None,
    _capture_scene=None,
    _check_image=None,
    _aesthetic_score=None,
    _render_report=None,
    _save_baseline=None,
    _load_baseline=None,
    _regression_delta=None,
) -> Dict[str, Any]:
    """Run the full visual-eval batch.

    Returns a dict with:
      - ``catalog_report``: {json, md} (if catalog=True)
      - ``regression``: regression_delta dict (if scenes=True)
      - ``worklist``: list of flagged item ids
    """
    # Lazy imports so tests can inject mocks
    if _capture_prop is None:
        from visual.screenshot import capture_prop as _capture_prop
    if _capture_scene is None:
        from visual.screenshot import capture_scene as _capture_scene
    if _check_image is None:
        from visual.vlm import check_image as _check_image
    if _aesthetic_score is None:
        from visual.aesthetic import aesthetic_score as _aesthetic_score
    if _render_report is None:
        from visual.report import render_visual_report as _render_report
    if _save_baseline is None:
        from visual.report import save_baseline as _save_baseline
    if _load_baseline is None:
        from visual.report import load_baseline as _load_baseline
    if _regression_delta is None:
        from visual.report import regression_delta as _regression_delta

    from visual.vlm import PROP_SCHEMA, SCENE_SCHEMA

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    worklist: List[str] = []

    result: Dict[str, Any] = {}

    # ── (A) Prop catalog ──────────────────────────────────────
    if catalog and library_dir:
        lib = Path(library_dir)
        prop_items = _run_prop_catalog(
            lib, out_path, angles,
            _capture_prop, _check_image, _aesthetic_score,
            PROP_SCHEMA, worklist,
        )
        if prop_items:
            catalog_report = _render_report(prop_items, title="Prop Catalog Report")
            (out_path / "catalog_report.json").write_text(
                json.dumps(catalog_report["json"], indent=2))
            (out_path / "catalog_report.md").write_text(catalog_report["md"])
            result["catalog_report"] = catalog_report

    # ── (B) Scene regression ──────────────────────────────────
    if scenes and builds_dir:
        bd = Path(builds_dir)
        scene_items = _run_scene_regression(
            bd, out_path, angles,
            _capture_scene, _check_image, _aesthetic_score,
            SCENE_SCHEMA, worklist,
        )
        if scene_items:
            # Compare against baseline if provided
            regression = None
            if baseline_path:
                prev = _load_baseline(baseline_path)
                regression = _regression_delta(scene_items, prev)

            # Save new baseline
            _save_baseline(scene_items, str(out_path / "visual_baseline.json"))

            report_title = "Scene Regression Report"
            scene_report = _render_report(scene_items, title=report_title)
            (out_path / "scene_report.json").write_text(
                json.dumps(scene_report["json"], indent=2))
            (out_path / "scene_report.md").write_text(scene_report["md"])

            result["scene_report"] = scene_report
            if regression:
                result["regression"] = regression

    # ── Worklist ──────────────────────────────────────────────
    worklist_path = out_path / "visual_worklist.json"
    worklist_path.write_text(json.dumps(worklist, indent=2))
    result["worklist"] = worklist

    return result


# ── Internal: prop catalog scan ──────────────────────────────────

def _run_prop_catalog(
    lib: Path,
    out_path: Path,
    angles: List[float] | None,
    capture_prop,
    check_image,
    aesthetic_score_fn,
    prop_schema: dict,
    worklist: List[str],
) -> List[Dict[str, Any]]:
    """Scan *lib* for GLB files, capture + score each, return items."""
    # Scan all .glb files (top-level + subdirectories), excluding .import sidecars
    glbs = sorted(p for p in lib.rglob("*.glb") if not p.name.endswith(".glb.import"))

    items: List[Dict[str, Any]] = []
    prop_out = out_path / "props"
    prop_out.mkdir(parents=True, exist_ok=True)

    for glb in glbs:
        prop_id = glb.stem
        item: Dict[str, Any] = {"id": prop_id}

        # Capture screenshots
        try:
            pngs = capture_prop(str(glb), str(prop_out / prop_id), angles=angles)
        except Exception as e:
            item["checks"] = {"notes": f"capture error: {e}"}
            item["aesthetic"] = {"score": None, "_load_error": True}
            item["error"] = str(e)
            items.append(item)
            worklist.append(prop_id)
            continue

        if not pngs:
            item["checks"] = {"notes": "no screenshots captured"}
            item["aesthetic"] = {"score": None}
            items.append(item)
            worklist.append(prop_id)
            continue

        # Use first angle for VLM + aesthetic
        primary_png = pngs[0]
        checks = check_image(primary_png, prop_schema, PROP_PROMPT)
        aesthetic = aesthetic_score_fn(primary_png)

        item["checks"] = checks
        item["aesthetic"] = aesthetic
        item["pngs"] = pngs

        if checks.get("_parse_error") or aesthetic.get("_load_error"):
            worklist.append(prop_id)

        items.append(item)

    return items


# ── Internal: scene regression scan ──────────────────────────────

def _run_scene_regression(
    builds_dir: Path,
    out_path: Path,
    angles: List[float] | None,
    capture_scene,
    check_image,
    aesthetic_score_fn,
    scene_schema: dict,
    worklist: List[str],
) -> List[Dict[str, Any]]:
    """Scan *builds_dir* for Godot projects, capture + score each."""
    builds = sorted(
        d for d in builds_dir.iterdir()
        if d.is_dir() and (d / "project.godot").exists()
    )
    if not builds:
        return []

    items: List[Dict[str, Any]] = []
    scene_out = out_path / "scenes"
    scene_out.mkdir(parents=True, exist_ok=True)

    for build in builds:
        scene_id = build.name
        item: Dict[str, Any] = {"id": scene_id}

        try:
            pngs = capture_scene(
                str(build), str(scene_out / scene_id), angles=angles,
            )
        except Exception as e:
            item["checks"] = {"notes": f"capture error: {e}"}
            item["aesthetic"] = {"score": None, "_load_error": True}
            item["error"] = str(e)
            items.append(item)
            worklist.append(scene_id)
            continue

        if not pngs:
            item["checks"] = {"notes": "no screenshots captured"}
            item["aesthetic"] = {"score": None}
            items.append(item)
            worklist.append(scene_id)
            continue

        primary_png = pngs[0]
        checks = check_image(primary_png, scene_schema, SCENE_PROMPT)
        aesthetic = aesthetic_score_fn(primary_png)

        item["checks"] = checks
        item["aesthetic"] = aesthetic
        item["pngs"] = pngs

        if checks.get("_parse_error") or aesthetic.get("_load_error"):
            worklist.append(scene_id)

        items.append(item)

    return items


# ── V Task 6: Closed auto-reroll ──────────────────────────────

def reroll_flagged(
    worklist_path: str,
    *,
    lexicon_path: str,
    library_dir: str,
    max_rerolls: int = 3,
) -> list:
    """CB-8 / V Task 6: Regenerate props flagged in the visual worklist.

    Reads ``visual_worklist.json`` from a previous ``run_batch()``,
    filters to prop IDs (skip scene-only IDs), and re-runs the forge
    pipeline for each.  Returns a list of reroll outcomes.

    The caller is expected to run ``run_batch()`` again afterward to
    verify the re-generated props now pass.

    Args:
        worklist_path: Path to ``visual_worklist.json`` from ``run_batch()``.
        lexicon_path: Path to the asset lexicon for forge.
        library_dir: Asset library dir (where GLBs live).
        max_rerolls: Maximum attempts per prop (default 3).

    Returns:
        List of ``{"prop_id": ..., "rerolls": N, "last_result": ...}``
        per flagged prop.
    """
    wl_path = Path(worklist_path)
    if not wl_path.exists():
        return []

    worklist = json.loads(wl_path.read_text())
    if not worklist:
        return []

    from runner import forge_from_request

    outcomes = []
    for prop_id in worklist:
        if not isinstance(prop_id, str):
            continue
        # CB-8: Skip scene IDs — they don't map to forgeable props.
        # Prop IDs follow the `category_material` convention (contain underscore);
        # scene IDs are build directory names without this pattern.
        if "_" not in prop_id:
            outcomes.append({
                "prop_id": prop_id,
                "rerolls": 0,
                "last_result": {"skipped": "not a forgeable prop — scene IDs require full quest re-scaffold"},
            })
            continue
        # Map prop ID → NL request — use the prop_id as a stand-in
        # (the forge pipeline requires an NL request; we use the ID
        # as a minimal description for re-generation).
        request = prop_id.replace("_", " ")

        attempt = 0
        last_result = None
        while attempt < max_rerolls:
            attempt += 1
            try:
                result = forge_from_request(request, lexicon_path, library_dir)
                last_result = {
                    "glb_path": result.glb_path,
                    "gate_passed": result.gate.passed,
                    "gate_reasons": list(result.gate.reasons),
                    "attempt": attempt,
                }
                if result.gate.passed:
                    break
            except Exception as e:
                last_result = {"error": str(e), "attempt": attempt}

        outcomes.append({
            "prop_id": prop_id,
            "rerolls": attempt,
            "last_result": last_result,
        })

    return outcomes
