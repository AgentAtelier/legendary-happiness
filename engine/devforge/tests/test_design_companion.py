"""Design Companion tests — pattern matching, category coverage, edge cases."""

from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

def test_analyze_matches_stamina() -> None:
    from devforge.companion.companion import DesignCompanion
    c = DesignCompanion()
    result = c.analyze(["stamina", "sprint", "crouch"])
    assert result["patterns_total"] == 18
    present_ids = [p["id"] for p in result["present"]]
    assert "stamina_gating" in present_ids
    assert "crouch_stealth" in present_ids

def test_analyze_finds_missing_essentials() -> None:
    from devforge.companion.companion import DesignCompanion
    c = DesignCompanion()
    result = c.analyze(["inventory"])  # only one feature
    missing_ids = [p["id"] for p in result["missing_essential"]]
    assert len(missing_ids) > 0

def test_coverage_by_category() -> None:
    from devforge.companion.companion import DesignCompanion
    c = DesignCompanion()
    result = c.analyze(["stamina", "inventory", "day_night", "loot", "interact"])
    cats = result["by_category"]
    assert "player_mechanics" in cats
    assert "ui_ux" in cats
    assert cats["player_mechanics"]["coverage"] > 0

def test_requires_dependency_check() -> None:
    from devforge.companion.companion import DesignCompanion
    c = DesignCompanion()
    result = c.analyze(["weather"])  # weather requires day_night_cycle
    missing = result["missing_essential"] + result["missing_important"]
    weather = [m for m in missing if m["id"] == "weather_system"]
    if weather:
        assert weather[0]["is_present"] == False
        deps = weather[0].get("missing_dependencies", [])
        if deps:
            assert any("Day/Night" in d for d in deps)

def test_analyze_design_wrapper() -> None:
    from devforge.companion.companion import analyze_design
    result = analyze_design(["quest_log", "journal", "interact", "prompt"])
    assert result["patterns_present"] >= 2

def test_empty_features() -> None:
    from devforge.companion.companion import DesignCompanion
    c = DesignCompanion()
    result = c.analyze([])
    assert result["patterns_present"] == 0
    assert result["patterns_missing"] == 18

def test_all_categories_present() -> None:
    from devforge.companion.companion import DesignCompanion
    c = DesignCompanion()
    result = c.analyze(["stamina", "day_night", "interact", "xp", "loot"])
    cats = set(result["by_category"].keys())
    assert "player_mechanics" in cats
    assert "world_systems" in cats
    assert "ui_ux" in cats
    assert "progression" in cats
    assert "content" in cats

if __name__ == "__main__":
    tests = [test_analyze_matches_stamina, test_analyze_finds_missing_essentials, test_coverage_by_category, test_requires_dependency_check, test_analyze_design_wrapper, test_empty_features, test_all_categories_present]
    passed = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}"); passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)
