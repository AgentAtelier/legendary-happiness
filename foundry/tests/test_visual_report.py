"""Unit tests for foundry.visual.report (V Task 4) — canned inputs.

Tests cover: report ranking (worst-first), JSON/MD output structure,
baseline save/load, and regression_delta comparison.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from visual.report import (
    load_baseline,
    regression_delta,
    render_visual_report,
    save_baseline,
)


# ── Canned test data ─────────────────────────────────────────────

def _make_item(item_id: str, checks: dict, aesthetic: dict | None = None):
    return {"id": item_id, "checks": checks, "aesthetic": aesthetic}


def _clean_prop(item_id: str = "table_worn_oak"):
    return _make_item(item_id, {
        "textured": True,
        "material_reads_right": True,
        "has_holes_or_deformity": False,
        "floating_bits": False,
        "notes": "clean",
    }, {"score": 8.2})


def _bad_prop(item_id: str = "shelf_rough_granite"):
    return _make_item(item_id, {
        "textured": False,
        "material_reads_right": False,
        "has_holes_or_deformity": True,
        "floating_bits": True,
        "notes": "rough shape",
    }, {"score": 3.1})


def _clean_scene(item_id: str = "scene_hermit_shack"):
    return _make_item(item_id, {
        "floater": False,
        "clipping": False,
        "ceiling_visible": True,
        "npcs_on_floor": True,
        "composition_ok": True,
        "theme_coherent": True,
        "notes": "solid",
    }, {"score": 7.5})


def _bad_scene(item_id: str = "scene_shop"):
    return _make_item(item_id, {
        "floater": True,
        "clipping": True,
        "ceiling_visible": False,
        "npcs_on_floor": False,
        "composition_ok": False,
        "theme_coherent": False,
        "notes": "terrible",
    }, {"score": 2.0})


# ── render_visual_report ─────────────────────────────────────────

def test_report_json_has_keys():
    items = [_clean_prop(), _bad_prop()]
    result = render_visual_report(items)
    j = result["json"]
    assert j["title"] == "Visual Eval Report"
    assert j["total"] == 2
    assert j["flagged_count"] == 1


def test_report_worst_first():
    """Flagged item appears before clean item."""
    items = [_clean_prop("clean1"), _bad_prop("bad1")]
    result = render_visual_report(items)
    j = result["json"]
    assert j["items"][0]["id"] == "bad1"
    assert j["items"][1]["id"] == "clean1"


def test_report_multiple_flagged_ranked_by_count():
    """More flags = earlier in the list."""
    mildly_bad = _make_item("mild", {
        "floater": True,
        "clipping": False,
        "ceiling_visible": True,
        "npcs_on_floor": True,
        "composition_ok": True,
        "theme_coherent": True,
        "notes": "mild",
    })
    very_bad = _bad_scene("awful")
    items = [mildly_bad, very_bad]
    result = render_visual_report(items)
    j = result["json"]
    assert j["items"][0]["id"] == "awful"  # 5 flags
    assert j["items"][1]["id"] == "mild"   # 1 flag


def test_report_md_has_sections():
    items = [_clean_prop(), _bad_prop()]
    result = render_visual_report(items)
    md = result["md"]
    assert "Visual Eval Report" in md
    assert "Flagged" in md
    assert "Clean" in md
    assert "**Total items:** 2" in md
    assert "**Flagged:** 1" in md


def test_report_md_no_flagged_section_when_all_clean():
    items = [_clean_prop(), _clean_scene()]
    result = render_visual_report(items)
    md = result["md"]
    assert "## Flagged" not in md
    assert "Clean" in md


def test_report_md_no_clean_section_when_all_flagged():
    items = [_bad_prop(), _bad_scene()]
    result = render_visual_report(items)
    md = result["md"]
    assert "Flagged" in md
    assert "## Clean" not in md


def test_report_custom_title():
    items = [_clean_prop()]
    result = render_visual_report(items, title="Prop Catalog Report")
    assert result["json"]["title"] == "Prop Catalog Report"
    assert "Prop Catalog Report" in result["md"]


def test_report_sorts_by_aesthetic_when_same_flag_count():
    """When flag counts tie, lower aesthetic comes first."""
    item_a = _make_item("a", {
        "floater": True, "clipping": False,
        "ceiling_visible": True, "npcs_on_floor": True,
        "composition_ok": True, "theme_coherent": True,
        "notes": "",
    }, {"score": 4.0})  # 1 flag, aesthetic 4.0

    item_b = _make_item("b", {
        "floater": True, "clipping": False,
        "ceiling_visible": True, "npcs_on_floor": True,
        "composition_ok": True, "theme_coherent": True,
        "notes": "",
    }, {"score": 6.0})  # 1 flag, aesthetic 6.0

    result = render_visual_report([item_b, item_a])  # b first in input
    j = result["json"]
    assert j["items"][0]["id"] == "a"  # lower aesthetic → worse → first


def test_report_empty_items():
    result = render_visual_report([])
    assert result["json"]["total"] == 0
    assert result["json"]["flagged_count"] == 0
    assert "**Total items:** 0" in result["md"]


# ── Baseline save/load ───────────────────────────────────────────

def test_save_and_load_baseline(tmp_path):
    items = [_clean_prop("p1"), _bad_prop("p2")]
    path = str(tmp_path / "baseline.json")

    save_baseline(items, path)
    assert Path(path).exists()

    loaded = load_baseline(path)
    assert "p1" in loaded
    assert "p2" in loaded
    assert loaded["p1"]["flagged"] is False
    assert loaded["p2"]["flagged"] is True
    assert loaded["p2"]["flag_count"] == 4


def test_load_baseline_missing_returns_empty():
    loaded = load_baseline("/nonexistent/baseline.json")
    assert loaded == {}


# ── regression_delta ─────────────────────────────────────────────

def test_regression_delta_regressed_item():
    """An item with more flags than baseline → regressed."""
    baseline = {
        "table": {
            "flag_count": 0,
            "flagged": False,
            "aesthetic_score": 8.0,
            "no_floaters": True,
            "textured": True,
            "material_reads": True,
            "no_holes": True,
            "no_clipping": True,
            "ceiling_ok": True,
            "npcs_ok": True,
            "composition_ok": True,
            "theme_ok": True,
            "notes": "",
        },
    }

    current = [_bad_prop("table")]  # 4 flags now
    delta = regression_delta(current, baseline)

    assert len(delta["regressed"]) == 1
    assert delta["regressed"][0]["id"] == "table"
    assert delta["regressed"][0]["flag_count_delta"] == 4
    assert len(delta["improved"]) == 0
    assert len(delta["new"]) == 0
    assert len(delta["removed"]) == 0


def test_regression_delta_improved_item():
    """An item with fewer flags than baseline → improved."""
    baseline = {
        "table": {
            "flag_count": 4,
            "flagged": True,
            "aesthetic_score": 3.0,
            "no_floaters": False,
            "textured": False,
            "material_reads": False,
            "no_holes": False,
            "no_clipping": True,
            "ceiling_ok": True,
            "npcs_ok": True,
            "composition_ok": True,
            "theme_ok": True,
            "notes": "",
        },
    }

    current = [_clean_prop("table")]  # 0 flags now
    delta = regression_delta(current, baseline)

    assert len(delta["improved"]) == 1
    assert delta["improved"][0]["id"] == "table"
    assert delta["improved"][0]["flag_count_delta"] == -4
    assert len(delta["regressed"]) == 0


def test_regression_delta_new_item():
    """Item in current but not baseline → new."""
    baseline = {}
    current = [_clean_prop("new_prop")]
    delta = regression_delta(current, baseline)

    assert len(delta["new"]) == 1
    assert delta["new"][0]["id"] == "new_prop"
    assert len(delta["regressed"]) == 0
    assert len(delta["improved"]) == 0


def test_regression_delta_removed_item():
    """Item in baseline but not current → removed."""
    baseline = {
        "old_prop": {
            "flag_count": 0,
            "flagged": False,
            "aesthetic_score": 5.0,
            "no_floaters": True, "textured": True, "material_reads": True,
            "no_holes": True, "no_clipping": True, "ceiling_ok": True,
            "npcs_ok": True, "composition_ok": True, "theme_ok": True,
            "notes": "",
        },
    }
    current: list = []
    delta = regression_delta(current, baseline)

    assert len(delta["removed"]) == 1
    assert delta["removed"][0]["id"] == "old_prop"


def test_regression_delta_aesthetic_regression():
    """Aesthetic drop > 0.5 with same flag count → regressed."""
    baseline = {
        "prop": {
            "flag_count": 1,
            "flagged": True,
            "aesthetic_score": 8.0,
            "no_floaters": False, "textured": True, "material_reads": True,
            "no_holes": True, "no_clipping": True, "ceiling_ok": True,
            "npcs_ok": True, "composition_ok": True, "theme_ok": True,
            "notes": "",
        },
    }

    current = [_make_item("prop", {
        "floating_bits": True,
        "notes": "",
    }, {"score": 6.0})]  # aesthetic dropped by 2.0

    delta = regression_delta(current, baseline)

    assert len(delta["regressed"]) == 1
    assert delta["regressed"][0]["aesthetic_delta"] == -2.0


def test_regression_delta_aesthetic_deltas():
    """aesthetic_deltas includes all shared items."""
    baseline = {
        "a": {"flag_count": 0, "flagged": False, "aesthetic_score": 7.0,
              "no_floaters": True, "textured": True, "material_reads": True,
              "no_holes": True, "no_clipping": True, "ceiling_ok": True,
              "npcs_ok": True, "composition_ok": True, "theme_ok": True, "notes": ""},
        "b": {"flag_count": 0, "flagged": False, "aesthetic_score": 5.0,
              "no_floaters": True, "textured": True, "material_reads": True,
              "no_holes": True, "no_clipping": True, "ceiling_ok": True,
              "npcs_ok": True, "composition_ok": True, "theme_ok": True, "notes": ""},
    }

    current = [
        _make_item("a", {"notes": ""}, {"score": 9.0}),
        _make_item("b", {"notes": ""}),  # no aesthetic
    ]
    delta = regression_delta(current, baseline)

    assert delta["aesthetic_deltas"]["a"]["delta"] == 2.0
    assert delta["aesthetic_deltas"]["b"]["delta"] is None  # no current aesthetic
