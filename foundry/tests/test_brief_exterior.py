"""Brief exterior fold-in: the exterior block + place_names ride the Brief
(light normalize here; biome_recipe/exterior_planner do the heavy validation)."""

from __future__ import annotations

from brief import brief_json_schema, minimal, validate_brief


def test_minimal_has_exterior_disabled_and_place_names():
    b = minimal("a cabin in the woods")
    assert b["exterior"] == {"enabled": False}
    assert b["place_names"] == {"scene_name": "", "landmark_lore": []}


def test_schema_exposes_exterior_and_place_names():
    props = brief_json_schema()["properties"]
    assert "exterior" in props and "biome_recipe" in props["exterior"]["properties"]
    assert "place_names" in props


def test_validate_missing_exterior_defaults_disabled():
    b, _ = validate_brief({"theme_tag": "hermit", "scale": "small",
                           "setting": "x", "key_features": [], "characters": []})
    assert b["exterior"] == {"enabled": False}
    assert b["place_names"] == {"scene_name": "", "landmark_lore": []}


def test_validate_preserves_enabled_exterior():
    raw = {
        "theme_tag": "hermit", "scale": "medium", "setting": "snowy cabin",
        "key_features": [], "characters": [],
        "exterior": {"enabled": True, "structure": "cabin",
                     "biome_recipe": {"base_biome": "snow_forest", "density": "high"}},
        "place_names": {"scene_name": "Hollowpine Rest",
                        "landmark_lore": [{"landmark_id": "building", "line": "An old trapper's cabin."}]},
    }
    b, _ = validate_brief(raw)
    assert b["exterior"]["enabled"] is True
    assert b["exterior"]["structure"] == "cabin"
    assert b["exterior"]["biome_recipe"]["base_biome"] == "snow_forest"
    assert b["place_names"]["scene_name"] == "Hollowpine Rest"
    assert b["place_names"]["landmark_lore"][0]["landmark_id"] == "building"


def test_validate_non_dict_exterior_is_safe():
    b, _ = validate_brief({"theme_tag": "hermit", "scale": "small", "setting": "x",
                           "key_features": [], "characters": [],
                           "exterior": "nonsense", "place_names": 42})
    assert b["exterior"] == {"enabled": False}
    assert b["place_names"] == {"scene_name": "", "landmark_lore": []}


def test_lighting_tier_defaults_zero():
    assert minimal("a cabin")["lighting_tier"] == 0
    b, _ = validate_brief({"theme_tag": "hermit", "scale": "small", "setting": "x",
                           "key_features": [], "characters": []})
    assert b["lighting_tier"] == 0


def test_lighting_tier_preserved_and_clamped():
    base = {"theme_tag": "hermit", "scale": "small", "setting": "x",
            "key_features": [], "characters": []}
    assert validate_brief({**base, "lighting_tier": 2})[0]["lighting_tier"] == 2
    assert validate_brief({**base, "lighting_tier": 9})[0]["lighting_tier"] == 0  # out of range
    assert validate_brief({**base, "lighting_tier": "x"})[0]["lighting_tier"] == 0  # non-int


def test_schema_has_lighting_tier():
    assert "lighting_tier" in brief_json_schema()["properties"]
