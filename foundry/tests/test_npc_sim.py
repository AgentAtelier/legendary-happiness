"""Tests for npc_sim — G2 needs + utility-action loop (CB-3)."""

from npc_sim import (
    ACTION_CATALOGUE,
    NEED_DEFAULTS,
    NEED_NAMES,
    default_needs,
    generate_npc_needs,
    select_action,
    tick_needs,
    urgency,
)


class TestNeedsDefault:
    def test_all_seven_needs_present(self):
        assert len(NEED_NAMES) == 7
        assert "joy" in NEED_NAMES

    def test_default_needs_returns_all_seven(self):
        needs = default_needs()
        assert len(needs) == 7
        for name in NEED_NAMES:
            assert name in needs
            assert 0.0 <= needs[name] <= 100.0

    def test_need_defaults_have_three_tuple(self):
        for name in NEED_NAMES:
            assert name in NEED_DEFAULTS
            val, decay, thresh = NEED_DEFAULTS[name]
            assert 0.0 <= val <= 100.0
            assert decay >= 0.0
            assert 0.0 < thresh <= 100.0


class TestTickNeeds:
    def test_tick_reduces_all_needs(self):
        needs = default_needs()
        after = tick_needs(needs, 1.0)
        for name in NEED_NAMES:
            assert after[name] <= needs[name], f"{name} did not decay"
            assert after[name] >= 0.0

    def test_tick_does_not_mutate_original(self):
        needs = default_needs()
        original = dict(needs)
        tick_needs(needs, 1.0)
        assert needs == original

    def test_tick_clamps_at_zero(self):
        needs = {"food": 1.0, "water": 100.0, "shelter": 100.0,
                 "safety": 100.0, "sleep": 100.0, "companionship": 100.0,
                 "joy": 100.0}
        after = tick_needs(needs, 10.0)
        assert after["food"] == 0.0

    def test_tick_uses_correct_decay_rates(self):
        needs = default_needs()
        hours = 2.0
        after = tick_needs(needs, hours)
        for name in NEED_NAMES:
            _, rate, _ = NEED_DEFAULTS[name]
            expected = max(0.0, needs[name] - rate * hours)
            assert abs(after[name] - expected) < 0.001


class TestUrgency:
    def test_full_need_has_zero_urgency(self):
        needs = default_needs()
        for name in NEED_NAMES:
            assert urgency(name, needs[name]) == 0.0

    def test_depleted_need_has_high_urgency(self):
        assert urgency("food", 0.0) == 1.0
        assert urgency("water", 0.0) == 1.0

    def test_below_threshold_has_positive_urgency(self):
        _, _, thresh = NEED_DEFAULTS["food"]
        assert urgency("food", thresh * 0.5) > 0.0
        assert urgency("food", thresh * 0.5) < 1.0


class TestActionCatalogue:
    def test_has_at_least_twenty_one_actions(self):
        assert len(ACTION_CATALOGUE) >= 21

    def test_every_action_has_required_fields(self):
        required = {"id", "label", "primary_need", "fulfillment",
                     "duration_h", "coping_type", "time_preference",
                     "communal", "major", "location_tag"}
        for action in ACTION_CATALOGUE:
            for field in required:
                assert field in action, f"action {action.get('id','?')} missing {field}"

    def test_primary_needs_are_valid(self):
        for action in ACTION_CATALOGUE:
            assert action["primary_need"] in NEED_NAMES, (
                f"{action['id']}: invalid primary_need={action['primary_need']}"
            )

    def test_fulfillment_in_range(self):
        for action in ACTION_CATALOGUE:
            assert 0 <= action["fulfillment"] <= 100, (
                f"{action['id']}: fulfillment {action['fulfillment']} out of range"
            )


class TestSelectAction:
    def test_returns_action_when_needs_are_high(self):
        needs = default_needs()
        action = select_action(needs)
        assert action["id"] in {a["id"] for a in ACTION_CATALOGUE}

    def test_depleted_food_prefers_food_action(self):
        needs = default_needs()
        needs["food"] = 5.0  # very hungry
        action = select_action(needs)
        assert action["primary_need"] == "food"

    def test_communal_excluded_when_no_others(self):
        needs = default_needs()
        needs["companionship"] = 5.0  # lonely
        action = select_action(needs, other_npcs_nearby=False)
        # Should NOT pick a communal action
        assert not action["communal"]

    def test_communal_allowed_when_others_nearby(self):
        needs = default_needs()
        needs["companionship"] = 5.0
        action = select_action(needs, other_npcs_nearby=True)
        # With others nearby, communal actions are available
        assert isinstance(action["id"], str)

    def test_night_penalises_day_actions(self):
        needs = default_needs()
        # Make food low so there's a strong signal for eating
        needs["food"] = 10.0
        # cook_meal is day-only, eat_stored is any-time
        action = select_action(needs, time_of_day="night")
        # Should prefer eat_stored (any time) over cook_meal (day only, penalised)
        # eat_stored has fulfillment=60, cook_meal has 85 * 0.5 = 42.5
        # urgency(food, 10) = 1 - 10/30 = 0.667
        # eat_stored: 0.667 * 60 = 40
        # cook_meal: 0.667 * 85 * 0.5 = 28.3
        # So eat_stored should win
        assert action["id"] == "eat_stored"


class TestGenerateNpcNeeds:
    def test_generates_correct_count(self):
        needs_list = generate_npc_needs(3)
        assert len(needs_list) == 3

    def test_all_within_range(self):
        needs_list = generate_npc_needs(10)
        for needs in needs_list:
            for name in NEED_NAMES:
                assert 0.0 <= needs[name] <= 100.0

    def test_variation_exists(self):
        # With 10 NPCs, at least one need should vary
        needs_list = generate_npc_needs(10)
        food_values = {n["food"] for n in needs_list}
        assert len(food_values) > 1, "no variation in food needs across NPCs"

    def test_deterministic_with_same_seed(self):
        a = generate_npc_needs(5, seed=42)
        b = generate_npc_needs(5, seed=42)
        assert a == b
