"""Unit tests for foundry.visual.batch (V Task 5) — VLM + CLIP mocked.

All model calls are mocked.  Tests verify the orchestration produces
a catalog report, a scene report, a regression diff, and a worklist.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from visual.batch import run_batch

# ── Mock factories ──────────────────────────────────────────────

def _fake_capture_prop(glb_path, out_dir, angles=None):
    """Return a fake list of one PNG path."""
    p = Path(out_dir) / "capture_prop_0.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("fake png")
    return [str(p)]


def _fake_capture_scene(build_dir, out_dir, angles=None):
    p = Path(out_dir) / "capture_scene_0.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("fake png")
    return [str(p)]


def _fake_check_image_clean(png_path, schema, prompt="", **kw):
    """Return a clean check result based on schema type."""
    required = set(schema.get("required", []))
    if "floater" in required:
        return {
            "floater": False, "clipping": False,
            "ceiling_visible": True, "npcs_on_floor": True,
            "composition_ok": True, "theme_coherent": True,
            "notes": "all good",
        }
    return {
        "textured": True,
        "material_reads_right": True,
        "has_holes_or_deformity": False,
        "floating_bits": False,
        "notes": "clean prop",
    }


def _fake_aesthetic_score(png_path, **kw):
    return {"score": 7.5}


# ── Fixtures ────────────────────────────────────────────────────

@pytest.fixture
def prop_lib(tmp_path):
    """Create a fake prop library with two .glb files."""
    lib = tmp_path / "library"
    lib.mkdir()
    (lib / "table_worn_oak.glb").write_text("fake glb")
    (lib / "shelf_rough_granite.glb").write_text("fake glb")
    return str(lib)


@pytest.fixture
def builds_dir(tmp_path):
    """Create a fake builds directory with two Godot projects."""
    builds = tmp_path / "builds"
    builds.mkdir()
    for name in ("scene_hermit", "scene_shop"):
        bd = builds / name
        bd.mkdir()
        (bd / "project.godot").write_text("[application]\n\nconfig/name=\"test\"\n")
        (bd / "scenes").mkdir()
        (bd / "scenes" / "main.tscn").write_text("[gd_scene]\n")
        (bd / "scripts").mkdir()
    return str(builds)


@pytest.fixture
def baseline_path(tmp_path):
    """Create a baseline file with one scene that had 3 flags."""
    bp = tmp_path / "baseline.json"
    bp.write_text(json.dumps({
        "scene_hermit": {
            "flag_count": 3, "flagged": True,
            "aesthetic_score": 5.0,
            "no_floaters": False, "textured": True,
            "material_reads": True, "no_holes": True,
            "no_clipping": False, "ceiling_ok": True,
            "npcs_ok": True, "composition_ok": False,
            "theme_ok": True, "notes": "was bad before",
        },
    }))
    return str(bp)


# ── Tests: prop catalog ─────────────────────────────────────────

def test_batch_prop_catalog(prop_lib, tmp_path):
    """Catalog mode scans library, produces report + worklist."""
    out = str(tmp_path / "out")
    result = run_batch(
        out_dir=out,
        library_dir=prop_lib,
        builds_dir=None,
        catalog=True,
        scenes=False,
        _capture_prop=_fake_capture_prop,
        _check_image=_fake_check_image_clean,
        _aesthetic_score=_fake_aesthetic_score,
    )

    assert "catalog_report" in result
    j = result["catalog_report"]["json"]
    assert j["total"] == 2
    assert j["flagged_count"] == 0  # all clean
    assert result["worklist"] == []

    # Files written
    assert Path(out, "catalog_report.json").exists()
    assert Path(out, "catalog_report.md").exists()
    assert Path(out, "visual_worklist.json").exists()


def test_batch_prop_catalog_flagged(prop_lib, tmp_path):
    """Catalog with a bad prop → flagged + worklist."""

    def check_with_bad(png_path, schema, prompt="", **kw):
        required = set(schema.get("required", []))
        if "textured" in required:
            return {
                "textured": False,
                "material_reads_right": False,
                "has_holes_or_deformity": True,
                "floating_bits": True,
                "notes": "bad prop",
            }
        return _fake_check_image_clean(png_path, schema, prompt)

    out = str(tmp_path / "out")
    result = run_batch(
        out_dir=out,
        library_dir=prop_lib,
        catalog=True,
        scenes=False,
        _capture_prop=_fake_capture_prop,
        _check_image=check_with_bad,
        _aesthetic_score=_fake_aesthetic_score,
    )

    assert result["catalog_report"]["json"]["flagged_count"] == 2
    assert len(result["worklist"]) == 0  # no parse/load errors, but items are flagged


def test_batch_prop_catalog_capture_error(prop_lib, tmp_path):
    """Capture failure → worklist item."""

    def failing_capture(glb_path, out_dir, angles=None):
        raise RuntimeError("Godot not available")

    out = str(tmp_path / "out")
    result = run_batch(
        out_dir=out,
        library_dir=prop_lib,
        catalog=True,
        scenes=False,
        _capture_prop=failing_capture,
        _check_image=_fake_check_image_clean,
        _aesthetic_score=_fake_aesthetic_score,
    )

    assert len(result["worklist"]) == 2


# ── Tests: scene regression ─────────────────────────────────────

def test_batch_scene_regression(builds_dir, baseline_path, tmp_path):
    """Scene regression scans builds, produces report + regression diff."""
    out = str(tmp_path / "out")
    result = run_batch(
        out_dir=out,
        builds_dir=builds_dir,
        baseline_path=baseline_path,
        catalog=False,
        scenes=True,
        _capture_scene=_fake_capture_scene,
        _check_image=_fake_check_image_clean,
        _aesthetic_score=_fake_aesthetic_score,
    )

    assert "scene_report" in result
    assert "regression" in result

    # Regression: scene_hermit improved (was 3 flags, now 0)
    improved = result["regression"]["improved"]
    assert any(r["id"] == "scene_hermit" for r in improved)

    # scene_shop is new (not in baseline)
    assert any(r["id"] == "scene_shop" for r in result["regression"]["new"])

    # Baseline saved
    assert Path(out, "visual_baseline.json").exists()
    assert Path(out, "scene_report.json").exists()


def test_batch_scene_regression_new_baseline(builds_dir, tmp_path):
    """When no baseline provided, saves new baseline but no regression."""
    out = str(tmp_path / "out")
    result = run_batch(
        out_dir=out,
        builds_dir=builds_dir,
        baseline_path=None,
        catalog=False,
        scenes=True,
        _capture_scene=_fake_capture_scene,
        _check_image=_fake_check_image_clean,
        _aesthetic_score=_fake_aesthetic_score,
    )

    assert "scene_report" in result
    assert "regression" not in result
    assert Path(out, "visual_baseline.json").exists()


# ── Tests: full batch (catalog + scenes) ────────────────────────

def test_batch_full_run(prop_lib, builds_dir, tmp_path):
    """Full batch produces catalog + scene reports + worklist."""
    out = str(tmp_path / "out")
    result = run_batch(
        out_dir=out,
        library_dir=prop_lib,
        builds_dir=builds_dir,
        catalog=True,
        scenes=True,
        _capture_prop=_fake_capture_prop,
        _capture_scene=_fake_capture_scene,
        _check_image=_fake_check_image_clean,
        _aesthetic_score=_fake_aesthetic_score,
    )

    assert "catalog_report" in result
    assert "scene_report" in result
    assert "worklist" in result
    assert result["catalog_report"]["json"]["total"] == 2
    assert result["scene_report"]["json"]["total"] == 2


def test_batch_catalog_only(prop_lib, tmp_path):
    """catalog=True, scenes=False → only catalog report."""
    out = str(tmp_path / "out")
    result = run_batch(
        out_dir=out,
        library_dir=prop_lib,
        catalog=True,
        scenes=False,
        _capture_prop=_fake_capture_prop,
        _check_image=_fake_check_image_clean,
        _aesthetic_score=_fake_aesthetic_score,
    )

    assert "catalog_report" in result
    assert "scene_report" not in result
    assert "regression" not in result


def test_batch_no_glbs_empty_catalog(tmp_path):
    """Empty library → empty catalog."""
    lib = tmp_path / "empty_lib"
    lib.mkdir()
    out = str(tmp_path / "out")
    result = run_batch(
        out_dir=out,
        library_dir=str(lib),
        catalog=True,
        scenes=False,
        _capture_prop=_fake_capture_prop,
        _check_image=_fake_check_image_clean,
        _aesthetic_score=_fake_aesthetic_score,
    )

    assert "catalog_report" not in result
    assert result["worklist"] == []


def test_batch_no_builds_empty_scenes(tmp_path):
    """Empty builds dir → no scene regression."""
    builds = tmp_path / "empty_builds"
    builds.mkdir()
    out = str(tmp_path / "out")
    result = run_batch(
        out_dir=out,
        builds_dir=str(builds),
        catalog=False,
        scenes=True,
    )

    assert "scene_report" not in result
    assert result["worklist"] == []


def test_batch_worklist_includes_parse_errors(tmp_path):
    """VLM parse errors → worklist entries."""
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "bad_prop.glb").write_text("fake")

    def check_with_parse_error(png_path, schema, prompt="", **kw):
        return {"_parse_error": True, "textured": True, "notes": ""}

    out = str(tmp_path / "out")
    result = run_batch(
        out_dir=out,
        library_dir=str(lib),
        catalog=True,
        scenes=False,
        _capture_prop=_fake_capture_prop,
        _check_image=check_with_parse_error,
        _aesthetic_score=_fake_aesthetic_score,
    )

    assert "bad_prop" in result["worklist"]
