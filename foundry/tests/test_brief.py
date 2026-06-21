"""TDD tests for foundry.brief — Brief schema v1 (spine slice 1).

Tests the shared structured Brief that sits between the prompt and
every generator: the schema shape, closed-vocab constants, minimal()
constructor, and validate_brief() with Decision Point emission.
"""

from __future__ import annotations

import pytest


# ── Constants shape ────────────────────────────────────────────────


def test_themes_and_categories_are_imported_live():
    """THEMES and CATEGORIES come from the engine, not hardcoded."""
    from brief import THEMES, CATEGORIES

    assert isinstance(THEMES, tuple)
    assert len(THEMES) >= 12  # at least the 12 known
    assert "*" in THEMES
    assert isinstance(CATEGORIES, tuple)
    assert len(CATEGORIES) >= 20  # ~37 placeable categories


def test_valid_scales_are_three():
    from brief import VALID_SCALES

    assert set(VALID_SCALES) == {"small", "medium", "large"}


def test_scale_bands_map_to_ranges():
    from brief import SCALE_BANDS

    assert SCALE_BANDS["small"] == (4, 6)
    assert SCALE_BANDS["medium"] == (6, 9)
    assert SCALE_BANDS["large"] == (9, 12)


# ── Brief.minimal ──────────────────────────────────────────────────


def test_minimal_blacksmith_forge():
    """Brief.minimal infers theme_tag from the prompt by substring match."""
    from brief import minimal

    b = minimal("a blacksmith's forge")
    assert b["schema_version"] == 2
    assert b["source_prompt"] == "a blacksmith's forge"
    assert b["theme_tag"] == "blacksmith"
    assert b["scale"] == "medium"
    assert b["mood"] == []
    assert b["key_features"] == []
    assert b["unmapped"] == []
    assert b["characters"] == []


def test_minimal_unknown_theme_falls_back_to_star():
    """No keyword match → theme_tag is '*'."""
    from brief import minimal

    b = minimal("a completely unknown and strange place")
    assert b["theme_tag"] == "*"


def test_minimal_setting_is_the_prompt():
    from brief import minimal

    b = minimal("wizard tower")
    assert b["setting"] == "wizard tower"


# ── validate_brief — theme_tag ─────────────────────────────────────


def test_validate_theme_unmapped():
    """Unknown theme → '*' + brief.theme_unmapped decision."""
    from brief import validate_brief

    raw = {"theme_tag": "lava_cave", "scale": "medium"}
    brief, decs = validate_brief(raw)

    assert brief["theme_tag"] == "*"
    assert any(d.code == "brief.theme_unmapped" for d in decs)
    dp = next(d for d in decs if d.code == "brief.theme_unmapped")
    assert dp.severity == "assumption"
    assert "lava_cave" in dp.context["requested"]


def test_validate_theme_unknown_empty():
    """Empty theme_tag → '*' + DP."""
    from brief import validate_brief

    raw = {"theme_tag": "", "scale": "medium"}
    brief, decs = validate_brief(raw)

    assert brief["theme_tag"] == "*"
    assert any(d.code == "brief.theme_unmapped" for d in decs)


def test_validate_theme_valid_passes_through():
    """Known theme is kept as-is, no theme DP."""
    from brief import validate_brief

    raw = {"theme_tag": "blacksmith", "scale": "medium"}
    brief, decs = validate_brief(raw)

    assert brief["theme_tag"] == "blacksmith"
    assert not any(d.code == "brief.theme_unmapped" for d in decs)


# ── validate_brief — scale ─────────────────────────────────────────


def test_validate_scale_defaulted():
    """Invalid scale → 'medium' + brief.scale_defaulted."""
    from brief import validate_brief

    raw = {"scale": "tiny", "theme_tag": "hermit"}
    brief, decs = validate_brief(raw)

    assert brief["scale"] == "medium"
    assert any(d.code == "brief.scale_defaulted" for d in decs)
    dp = next(d for d in decs if d.code == "brief.scale_defaulted")
    assert dp.severity == "assumption"
    assert dp.context["requested"] == "tiny"


def test_validate_scale_missing_defaulted():
    """Missing scale → 'medium' + brief.scale_defaulted."""
    from brief import validate_brief

    raw: dict = {"theme_tag": "wizard"}
    brief, decs = validate_brief(raw)

    assert brief["scale"] == "medium"
    assert any(d.code == "brief.scale_defaulted" for d in decs)


def test_validate_scale_valid_passes_through():
    """Valid scale is kept, no scale DP."""
    from brief import validate_brief

    for s in ("small", "medium", "large"):
        brief, decs = validate_brief({"scale": s, "theme_tag": "wizard"})
        assert brief["scale"] == s
        assert not any(d.code == "brief.scale_defaulted" for d in decs)


# ── validate_brief — setting ───────────────────────────────────────


def test_validate_setting_defaulted():
    """Empty setting → derived from theme + brief.setting_defaulted."""
    from brief import validate_brief

    raw: dict = {"theme_tag": "blacksmith", "scale": "medium"}
    brief, decs = validate_brief(raw)

    assert brief["setting"] == "a blacksmith room"
    assert any(d.code == "brief.setting_defaulted" for d in decs)
    dp = next(d for d in decs if d.code == "brief.setting_defaulted")
    assert dp.context["resolved"] == "a blacksmith room"


def test_validate_setting_star_theme():
    """Empty setting with '*' theme → 'a room'."""
    from brief import validate_brief

    raw: dict = {"theme_tag": "*", "scale": "medium"}
    brief, decs = validate_brief(raw)

    assert brief["setting"] == "a room"


def test_validate_setting_provided_is_kept():
    """Provided setting passes through, no DP."""
    from brief import validate_brief

    raw = {"setting": "the grand hall", "theme_tag": "noble", "scale": "large"}
    brief, decs = validate_brief(raw)

    assert brief["setting"] == "the grand hall"
    assert not any(d.code == "brief.setting_defaulted" for d in decs)


# ── validate_brief — key_features ──────────────────────────────────


def test_validate_feature_unmapped_bad_category():
    """key_feature with unknown category → unmapped + DP."""
    from brief import validate_brief

    raw = {
        "theme_tag": "blacksmith",
        "scale": "medium",
        "key_features": [{"text": "a lava river", "category": "lava"}],
    }
    brief, decs = validate_brief(raw)

    feat = brief["key_features"][0]
    assert feat["text"] == "a lava river"
    assert feat["status"] == "unmapped"
    assert feat["category"] is None
    assert "a lava river" in brief["unmapped"]
    assert any(d.code == "brief.feature_unmapped" for d in decs)
    dp = next(d for d in decs if d.code == "brief.feature_unmapped")
    assert dp.severity == "error"
    assert dp.context["text"] == "a lava river"


def test_validate_feature_unmapped_no_category():
    """key_feature with no category at all → unmapped + DP."""
    from brief import validate_brief

    raw = {
        "theme_tag": "wizard",
        "scale": "medium",
        "key_features": [{"text": "floating books"}],
    }
    brief, decs = validate_brief(raw)

    feat = brief["key_features"][0]
    assert feat["status"] == "unmapped"
    assert feat["category"] is None
    assert "floating books" in brief["unmapped"]


def test_validate_feature_mapped_is_kept():
    """key_feature with valid category → mapped, no DP, kept."""
    from brief import validate_brief

    raw = {
        "theme_tag": "blacksmith",
        "scale": "medium",
        "key_features": [{"text": "anvil", "category": "table"}],
    }
    brief, decs = validate_brief(raw)

    feat = brief["key_features"][0]
    assert feat["text"] == "anvil"
    assert feat["status"] == "mapped"
    assert feat["category"] == "table"
    assert "anvil" not in brief["unmapped"]
    assert not any(d.code == "brief.feature_unmapped" for d in decs)


def test_validate_multiple_features_mixed():
    """Mix of mapped and unmapped features works correctly."""
    from brief import validate_brief

    raw = {
        "theme_tag": "kitchen",
        "scale": "medium",
        "key_features": [
            {"text": "a large table", "category": "table"},
            {"text": "magic wallpaper", "category": "unknown"},
            {"text": "chairs for guests", "category": "chair"},
        ],
    }
    brief, decs = validate_brief(raw)

    assert len(brief["key_features"]) == 3
    # first: mapped
    assert brief["key_features"][0]["status"] == "mapped"
    # second: unmapped (unknown category)
    assert brief["key_features"][1]["status"] == "unmapped"
    assert "magic wallpaper" in brief["unmapped"]
    # third: mapped
    assert brief["key_features"][2]["status"] == "mapped"

    # Exactly one feature_unmapped DP (for the unknown category)
    bad_dps = [d for d in decs if d.code == "brief.feature_unmapped"]
    assert len(bad_dps) == 1


# ── Round-trip: minimal + validate ─────────────────────────────────


def test_minimal_validates_cleanly():
    """Brief.minimal output passes validate_brief with no decisions."""
    from brief import minimal, validate_brief

    b = minimal("a hermit's shack")
    assert b["theme_tag"] == "hermit"

    brief2, decs = validate_brief(b)
    # No error/assumption decisions for a clean minimal Brief
    error_or_assumption = [d for d in decs if d.severity in ("error", "assumption")]
    assert not error_or_assumption, (
        f"Unexpected decisions on minimal Brief: "
        f"{[d.code for d in error_or_assumption]}"
    )


# ── Edge cases ─────────────────────────────────────────────────────


def test_validate_preserves_source_prompt():
    """source_prompt is always copied through."""
    from brief import validate_brief

    raw = {"source_prompt": "make me a creepy dungeon", "theme_tag": "dungeon", "scale": "small"}
    brief, _ = validate_brief(raw)

    assert brief["source_prompt"] == "make me a creepy dungeon"


def test_validate_schema_version_defaults():
    """Missing schema_version → 1 (raw passes through as-is)."""
    from brief import validate_brief

    brief, _ = validate_brief({"theme_tag": "wizard", "scale": "medium"})
    assert brief["schema_version"] == 1

def test_validate_characters_keeps_valid_roles():
    """Characters with valid roles are preserved verbatim."""
    from brief import validate_brief

    raw = {
        "theme_tag": "blacksmith",
        "scale": "medium",
        "characters": [
            {"role": "blacksmith", "note": "the master of the forge"},
            {"role": "apprentice"},
        ],
    }
    brief, decs = validate_brief(raw)
    assert brief["characters"] == [
        {"role": "blacksmith", "note": "the master of the forge"},
        {"role": "apprentice", "note": None},
    ]

def test_validate_characters_drops_empty_role():
    """Characters with empty role are dropped."""
    from brief import validate_brief

    raw = {
        "theme_tag": "tavern",
        "scale": "medium",
        "characters": [
            {"role": "blacksmith"},
            {"role": "", "note": "nothing"},
            {"role": None},
        ],
    }
    brief, decs = validate_brief(raw)
    assert len(brief["characters"]) == 1
    assert brief["characters"][0]["role"] == "blacksmith"

def test_validate_characters_none_or_missing():
    """Missing or None characters → empty list."""
    from brief import validate_brief

    brief1, _ = validate_brief({"theme_tag": "hermit", "scale": "medium"})
    assert brief1["characters"] == []

    brief2, _ = validate_brief({"theme_tag": "hermit", "scale": "medium", "characters": None})
    assert brief2["characters"] == []


def test_validate_mood_is_preserved():
    """Mood list passes through unchanged."""
    from brief import validate_brief

    raw = {
        "theme_tag": "tavern",
        "scale": "medium",
        "mood": ["cozy", "dim", "lively"],
    }
    brief, _ = validate_brief(raw)
    assert brief["mood"] == ["cozy", "dim", "lively"]


def test_validate_unmapped_top_level_is_preserved():
    """Pre-existing unmapped list is carried forward."""
    from brief import validate_brief

    raw = {
        "theme_tag": "wizard",
        "scale": "medium",
        "unmapped": ["dragon", "portal"],
        "key_features": [
            {"text": "magic carpet", "category": "flying"},
        ],
    }
    brief, decs = validate_brief(raw)

    assert "dragon" in brief["unmapped"]
    assert "portal" in brief["unmapped"]
    assert "magic carpet" in brief["unmapped"]  # added by validation
    assert len(brief["unmapped"]) == 3


def test_validate_key_features_empty_is_safe():
    """Empty/missing key_features → empty list, no crash."""
    from brief import validate_brief

    brief, _ = validate_brief({"theme_tag": "armory", "scale": "large"})
    assert brief["key_features"] == []


def test_validate_key_features_none_is_safe():
    """None key_features → empty list."""
    from brief import validate_brief

    brief, _ = validate_brief({"theme_tag": "armory", "scale": "large", "key_features": None})
    assert brief["key_features"] == []


def test_validate_brief_drops_features_subsumed_by_theme_or_characters():
    """An 'unmapped' feature that merely restates the setting/theme/a character
    (e.g. 'blacksmith's forge', 'an apprentice') must NOT reach `unmapped` —
    otherwise the build report contradicts itself ('can't build a blacksmith's
    forge' right after building one). A genuinely novel feature still surfaces."""
    from brief import validate_brief, THEMES, CATEGORIES
    raw = {
        "theme_tag": "blacksmith",
        "setting": "a blacksmith's forge",
        "scale": "medium",
        "characters": [{"role": "apprentice", "note": None}],
        "key_features": [
            {"text": "blacksmith's forge", "category": None},  # restates setting/theme
            {"text": "an apprentice", "category": None},       # restates a character
            {"text": "a lava river", "category": None},        # genuinely unsupported
        ],
    }
    brief, _ = validate_brief(raw, THEMES, CATEGORIES)
    assert "blacksmith's forge" not in brief["unmapped"]
    assert "an apprentice" not in brief["unmapped"]
    assert "a lava river" in brief["unmapped"]
