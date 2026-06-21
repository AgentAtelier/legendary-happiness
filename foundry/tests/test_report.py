"""TDD tests for foundry.report — build report (spine slice 1 task 4).

Tests the four-section build report: understood, built, assumed, couldnt_do.
"""
from __future__ import annotations

import pytest

from decisions import Choice, DecisionPoint, make_decision


def _dp(code: str, severity: str, plain: str) -> DecisionPoint:
    """Build a minimal DecisionPoint for testing."""
    return make_decision(
        code=code,
        stage="test",
        severity=severity,
        context={},
        choices=(),
    )


# ── build_report_dict ──────────────────────────────────────────────


def test_report_dict_all_four_sections_present():
    """build_report_dict always returns all four keys."""
    from report import build_report_dict

    brief = {
        "setting": "test room",
        "mood": [],
        "scale": "medium",
        "theme_tag": "hermit",
        "key_features": [],
        "unmapped": [],
    }
    rpt = build_report_dict(brief, [])

    for key in ("understood", "built", "assumed", "couldnt_do"):
        assert key in rpt, f"Missing key: {key}"


def test_report_understood_section():
    """Understood section reflects Brief contents."""
    from report import build_report_dict

    brief = {
        "setting": "a wizard's tower",
        "mood": ["mystical", "ancient"],
        "scale": "large",
        "theme_tag": "wizard",
        "key_features": [
            {"text": "bookshelf", "status": "mapped", "category": "shelf"},
            {"text": "portal", "status": "unmapped", "category": None},
        ],
        "unmapped": ["portal"],
    }
    rpt = build_report_dict(brief, [])

    u = rpt["understood"]
    assert u["setting"] == "a wizard's tower"
    assert u["mood"] == ["mystical", "ancient"]
    assert u["scale"] == "large"
    assert u["theme_tag"] == "wizard"
    assert u["key_features"] == ["bookshelf"]  # only mapped


def test_report_built_section():
    """Built section reports prop count, categories, and which features
    made it into the manifest."""
    from report import build_report_dict

    brief = {
        "setting": "a blacksmith's forge",
        "mood": [],
        "scale": "medium",
        "theme_tag": "blacksmith",
        "key_features": [
            {"text": "anvil", "status": "mapped", "category": "table"},
            {"text": "tool rack", "status": "mapped", "category": "shelf"},
        ],
        "unmapped": [],
    }
    manifest = [
        {"id": "table_0", "category": "table", "material": "wrought_iron"},
        {"id": "chair_0", "category": "chair", "material": "worn_oak"},
        {"id": "shelf_0", "category": "shelf", "material": "worn_oak"},
    ]
    rpt = build_report_dict(brief, [], manifest)

    b = rpt["built"]
    assert b["prop_count"] == 3
    assert "table" in b["categories"]
    assert "shelf" in b["categories"]
    assert "chair" in b["categories"]
    assert "anvil" in b["key_features_built"]
    assert "tool rack" in b["key_features_built"]


def test_report_features_missing_from_manifest_not_in_built():
    """A mapped feature whose category isn't in the manifest is NOT
    listed under built."""
    from report import build_report_dict

    brief = {
        "setting": "test",
        "mood": [],
        "scale": "small",
        "theme_tag": "hermit",
        "key_features": [
            {"text": "anvil", "status": "mapped", "category": "table"},
        ],
        "unmapped": [],
    }
    manifest = [
        {"id": "chair_0", "category": "chair", "material": "worn_oak"},
    ]
    rpt = build_report_dict(brief, [], manifest)

    assert "anvil" not in rpt["built"]["key_features_built"]


def test_report_assumed_section():
    """Assumed section collects assumption/ambiguous DPs."""
    from report import build_report_dict
    import decisions as dec

    brief = {
        "setting": "test", "mood": [], "scale": "medium",
        "theme_tag": "hermit", "key_features": [], "unmapped": [],
    }
    dp1 = dec.make_decision("room.size_clamped", "room", "assumption",
                            {"axis": "w", "raw": 99, "clamped": 12, "lo": 4, "hi": 12},
                            choices=())
    dp2 = dec.make_decision("room.empty", "room", "ambiguous", {},
                            choices=())
    rpt = build_report_dict(brief, [dp1, dp2])

    assert len(rpt["assumed"]) == 2
    assert any("nudged" in a for a in rpt["assumed"])


def test_report_couldnt_do_section():
    """Couldn't do = unmapped features + error-severity DPs."""
    from report import build_report_dict
    import decisions as dec

    brief = {
        "setting": "test", "mood": [], "scale": "medium",
        "theme_tag": "wizard",
        "key_features": [
            {"text": "a lava river", "status": "unmapped", "category": None},
        ],
        "unmapped": ["a lava river", "magic portal"],
    }
    dp_err = dec.make_decision("brief.parse_fallback", "interpreter", "error",
                               {"error": "Invalid JSON"}, choices=())
    dp_info = dec.make_decision("room.size_clamped", "room", "assumption",
                                {"axis": "w", "raw": 99, "clamped": 12, "lo": 4, "hi": 12},
                                choices=())

    rpt = build_report_dict(brief, [dp_err, dp_info])

    # Unmapped features from brief
    assert "a lava river" in rpt["couldnt_do"]
    assert "magic portal" in rpt["couldnt_do"]
    # Error DP
    assert any("couldn't understand" in c.lower() for c in rpt["couldnt_do"])
    # Assumption DPs NOT in couldn't_do
    assert not any("nudged" in c for c in rpt["couldnt_do"])


def test_report_empty_manifest_is_safe():
    """Empty manifest → built shows 0 props."""
    from report import build_report_dict

    brief = {
        "setting": "empty room", "mood": [], "scale": "medium",
        "theme_tag": "hermit", "key_features": [], "unmapped": [],
    }
    rpt = build_report_dict(brief, [], [])
    assert rpt["built"]["prop_count"] == 0
    assert rpt["built"]["categories"] == []


def test_report_empty_manifest_none_is_safe():
    """None manifest → same as empty."""
    from report import build_report_dict

    brief = {
        "setting": "test", "mood": [], "scale": "medium",
        "theme_tag": "hermit", "key_features": [], "unmapped": [],
    }
    rpt = build_report_dict(brief, [], None)
    assert rpt["built"]["prop_count"] == 0


# ── render_build_report ────────────────────────────────────────────


def test_render_build_report_has_four_section_headers():
    """The rendered string contains all four section headers."""
    from report import render_build_report

    brief = {
        "setting": "a cozy tavern",
        "mood": ["warm", "dim"],
        "scale": "medium",
        "theme_tag": "tavern",
        "key_features": [
            {"text": "bar counter", "status": "mapped", "category": "table"},
        ],
        "unmapped": [],
    }
    manifest = [
        {"id": "table_0", "category": "table", "material": "worn_oak"},
        {"id": "chair_0", "category": "chair", "material": "worn_oak"},
    ]
    text = render_build_report(brief, [], manifest)

    assert "═══ Understood ═══" in text
    assert "═══ Built ═══" in text
    assert "a cozy tavern" in text
    assert "tavern" in text
    assert "bar counter" in text


def test_render_build_report_includes_unmapped_in_couldnt_do():
    """An unmapped feature appears under Couldn't do in the rendered string."""
    from report import render_build_report
    import decisions as dec

    brief = {
        "setting": "test", "mood": [], "scale": "medium",
        "theme_tag": "wizard",
        "key_features": [
            {"text": "a lava river", "status": "unmapped", "category": None},
        ],
        "unmapped": ["a lava river"],
    }
    dp_err = dec.make_decision("brief.feature_unmapped", "interpreter", "error",
                               {"text": "a lava river"}, choices=())
    text = render_build_report(brief, [dp_err], [])

    assert "═══ Couldn't do ═══" in text
    assert "a lava river" in text


def test_render_build_report_omits_empty_sections():
    """Assumed and Couldn't do sections are omitted when empty."""
    from report import render_build_report

    brief = {
        "setting": "clean room", "mood": [], "scale": "small",
        "theme_tag": "hermit", "key_features": [], "unmapped": [],
    }
    text = render_build_report(brief, [], [])

    assert "═══ Assumed ═══" not in text
    assert "═══ Couldn't do ═══" not in text
    assert "═══ Understood ═══" in text
    assert "═══ Built ═══" in text


# ── Spine Slice 2: Quest sections in build report ───────────────────

def test_report_understood_includes_characters():
    """Brief with characters → 'understood' lists their roles with soul tone."""
    from report import build_report_dict

    brief = {
        "setting": "a blacksmith's forge",
        "mood": [],
        "scale": "medium",
        "theme_tag": "blacksmith",
        "key_features": [],
        "unmapped": [],
        "characters": [
            {"role": "blacksmith", "note": "master"},
            {"role": "apprentice"},
        ],
    }
    rpt = build_report_dict(brief, [])
    chars = rpt["understood"]["characters"]
    assert len(chars) == 2
    assert all("blacksmith" in c for c in [chars[0]])
    assert all("apprentice" in c for c in [chars[1]])


def test_report_characters_show_soul_tone():
    """Brief character with a timid/warm soul → 'understood' shows 'timid, warm <role>'."""
    from report import build_report_dict

    brief = {
        "setting": "a forge",
        "mood": [],
        "scale": "medium",
        "theme_tag": "blacksmith",
        "key_features": [],
        "unmapped": [],
        "characters": [{
            "role": "blacksmith",
            "soul": {"substrate": {"courage": -0.5, "generosity": 0.6, "stability": 0.1}},
        }],
    }
    rpt = build_report_dict(brief, [])
    assert rpt["understood"]["characters"][0] == "timid, warm blacksmith"


def test_report_built_npc_dialogue_sources_grammared():
    """When a grammared fallback DP fires for npc_1 → that NPC's dialogue
    source is 'grammared'."""
    from report import build_report_dict
    from decisions import make_decision

    brief = {
        "setting": "test", "mood": [], "scale": "medium",
        "theme_tag": "hermit", "key_features": [], "unmapped": [],
        "characters": [{"role": "hermit"}, {"role": "apprentice"}],
    }
    dp_grammared = make_decision(
        "quest.npc_grammared_fallback", "planner", "assumption",
        {"npc_id": "npc_1"}, choices=(),
    )
    rpt = build_report_dict(brief, [dp_grammared])
    sources = rpt["built"].get("npc_dialogue_sources", {})
    assert sources.get("npc_1") == "grammared"


def test_report_built_npc_dialogue_sources_canned():
    """When quest.missing_npc fires for npc_0 → dialogue source 'canned'."""
    from report import build_report_dict
    from decisions import make_decision

    brief = {
        "setting": "test", "mood": [], "scale": "medium",
        "theme_tag": "hermit", "key_features": [], "unmapped": [],
        "characters": [{"role": "hermit"}],
    }
    dp_canned = make_decision(
        "quest.missing_npc", "planner", "assumption",
        {"npc_id": "npc_0"}, choices=(),
    )
    rpt = build_report_dict(brief, [dp_canned])
    sources = rpt["built"].get("npc_dialogue_sources", {})
    assert sources.get("npc_0") == "canned"


def test_report_built_npc_dialogue_sources_model_default():
    """NPCs with no decisions default to 'model' source."""
    from report import build_report_dict

    brief = {
        "setting": "test", "mood": [], "scale": "medium",
        "theme_tag": "hermit", "key_features": [], "unmapped": [],
        "characters": [{"role": "hermit"}],
    }
    rpt = build_report_dict(brief, [])
    sources = rpt["built"].get("npc_dialogue_sources", {})
    assert sources.get("npc_0") == "model"


def test_render_report_includes_characters_and_sources():
    """Rendered report includes characters (with soul tone) and NPC dialogue sources."""
    from report import render_build_report
    from decisions import make_decision

    brief = {
        "setting": "a blacksmith's forge",
        "mood": ["hot"],
        "scale": "medium",
        "theme_tag": "blacksmith",
        "key_features": [],
        "unmapped": [],
        "characters": [{"role": "blacksmith"}, {"role": "apprentice"}],
    }
    dp = make_decision(
        "quest.npc_grammared_fallback", "planner", "assumption",
        {"npc_id": "npc_1"}, choices=(),
    )
    text = render_build_report(brief, [dp], [])

    assert "blacksmith" in text
    assert "apprentice" in text
    assert "npc_0: model" in text
    assert "npc_1: grammared" in text
