"""Unit tests for foundry.eval.visual (V Task 4) — canned inputs.

All tests use hard-coded check dicts; no VLM or model involved.
"""

from __future__ import annotations

from eval.visual import compute_visual_signals

# ── compute_visual_signals ────────────────────────────────────────

def test_clean_prop():
    """A perfectly clean prop produces 0 flags."""
    checks = {
        "textured": True,
        "material_reads_right": True,
        "has_holes_or_deformity": False,
        "floating_bits": False,
        "notes": "looks good",
    }
    aesthetic = {"score": 7.5}
    signals = compute_visual_signals(checks, aesthetic)

    assert signals["no_floaters"] is True
    assert signals["textured"] is True
    assert signals["material_reads"] is True
    assert signals["no_holes"] is True
    assert signals["flagged"] is False
    assert signals["flag_count"] == 0
    assert signals["aesthetic_score"] == 7.5
    assert signals["notes"] == "looks good"


def test_clean_scene():
    """A perfectly clean scene produces 0 flags."""
    checks = {
        "floater": False,
        "clipping": False,
        "ceiling_visible": True,
        "npcs_on_floor": True,
        "composition_ok": True,
        "theme_coherent": True,
        "notes": "all clear",
    }
    signals = compute_visual_signals(checks)

    assert signals["no_floaters"] is True
    assert signals["no_clipping"] is True
    assert signals["ceiling_ok"] is True
    assert signals["npcs_ok"] is True
    assert signals["composition_ok"] is True
    assert signals["theme_ok"] is True
    assert signals["flagged"] is False
    assert signals["flag_count"] == 0


def test_flagged_prop_floaters_and_holes():
    """Floaters + holes → 2 flags."""
    checks = {
        "textured": True,
        "material_reads_right": True,
        "has_holes_or_deformity": True,  # BAD
        "floating_bits": True,           # BAD
        "notes": "rough",
    }
    signals = compute_visual_signals(checks)

    assert signals["no_floaters"] is False
    assert signals["no_holes"] is False
    assert signals["textured"] is True
    assert signals["material_reads"] is True
    assert signals["flagged"] is True
    assert signals["flag_count"] == 2


def test_flagged_scene():
    """Multiple scene issues → flagging."""
    checks = {
        "floater": True,              # BAD
        "clipping": True,             # BAD
        "ceiling_visible": False,     # BAD
        "npcs_on_floor": True,
        "composition_ok": False,       # BAD
        "theme_coherent": False,       # BAD
        "notes": "multiple problems",
    }
    signals = compute_visual_signals(checks)

    assert signals["no_floaters"] is False
    assert signals["no_clipping"] is False
    assert signals["ceiling_ok"] is False
    assert signals["composition_ok"] is False
    assert signals["theme_ok"] is False
    assert signals["flag_count"] == 5
    assert signals["flagged"] is True


def test_no_aesthetic():
    """Missing aesthetic → score is None."""
    checks = {"floater": False, "notes": ""}
    signals = compute_visual_signals(checks)
    assert signals["aesthetic_score"] is None


def test_aesthetic_none_dict():
    """None aesthetic → score is None."""
    checks = {"floater": False, "notes": ""}
    signals = compute_visual_signals(checks, None)
    assert signals["aesthetic_score"] is None


def test_aesthetic_score_is_none():
    """Aesthetic dict with None score → score is None."""
    checks = {"floater": False, "notes": ""}
    signals = compute_visual_signals(checks, {"score": None})
    assert signals["aesthetic_score"] is None


def test_no_floaters_combines_prop_and_scene():
    """If both floating_bits and floater are True, no_floaters is False."""
    checks = {
        "floating_bits": True,
        "floater": True,
        "notes": "",
    }
    signals = compute_visual_signals(checks)
    assert signals["no_floaters"] is False


def test_no_floaters_false_only_if_both_clean():
    """no_floaters is True only when both floating_bits and floater are clean."""
    checks = {
        "floating_bits": False,
        "floater": False,
        "notes": "",
    }
    signals = compute_visual_signals(checks)
    assert signals["no_floaters"] is True


def test_defaults_when_missing_keys():
    """Missing keys in checks → defaults applied (optimistic)."""
    checks: dict = {}  # no keys at all
    signals = compute_visual_signals(checks)

    assert signals["no_floaters"] is True  # default: no floaters
    assert signals["textured"] is True     # default: textured
    assert signals["material_reads"] is True
    assert signals["no_holes"] is True
    assert signals["no_clipping"] is True
    assert signals["ceiling_ok"] is True
    assert signals["flagged"] is False
