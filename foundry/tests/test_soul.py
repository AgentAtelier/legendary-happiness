"""Tests for soul.py — Substrate+axes shape, validation, tone."""

from __future__ import annotations

import pytest

from soul import (
    AXES,
    SUBSTRATE_TRAITS,
    default_soul,
    tone_descriptor,
    validate_soul,
)


# ── default_soul ──────────────────────────────────────────────────

def test_default_soul_has_all_keys_at_zero():
    """default_soul() returns all 7 keys at 0.0."""
    s = default_soul()
    assert s["substrate"] == {"courage": 0.0, "generosity": 0.0, "stability": 0.0}
    assert s["axes"] == {"security": 0.0, "belonging": 0.0, "agency": 0.0, "satiation": 0.0}


def test_default_soul_tone_is_even_tempered():
    """default_soul() gives 'even-tempered' tone."""
    assert tone_descriptor(default_soul()) == "even-tempered"


# ── validate_soul ─────────────────────────────────────────────────

def test_validate_soul_preserves_valid_values():
    """Valid values are kept as-is."""
    raw = {"substrate": {"courage": -0.8, "generosity": 0.6, "stability": 0.0}}
    soul, decisions = validate_soul(raw)
    assert soul["substrate"]["courage"] == -0.8
    assert soul["substrate"]["generosity"] == 0.6
    assert soul["substrate"]["stability"] == 0.0
    assert soul["axes"]["security"] == 0.0  # defaulted
    assert len(decisions) == 4  # 4 axes defaulted


def test_validate_soul_clamps_out_of_range():
    """Values outside [-1, 1] are clamped + soul.clamped DP."""
    raw = {"substrate": {"courage": -0.8, "generosity": 2.0}}
    soul, decisions = validate_soul(raw)
    assert soul["substrate"]["courage"] == -0.8
    assert soul["substrate"]["generosity"] == 1.0  # clamped
    assert soul["substrate"]["stability"] == 0.0  # defaulted

    clamped_dps = [d for d in decisions if d.code == "soul.clamped"]
    defaulted_dps = [d for d in decisions if d.code == "soul.defaulted"]
    assert len(clamped_dps) == 1
    assert clamped_dps[0].context["field"] == "substrate.generosity"
    assert clamped_dps[0].context["raw"] == 2.0
    assert clamped_dps[0].context["clamped"] == 1.0
    assert len(defaulted_dps) >= 1  # stability + 4 axes


def test_validate_soul_clamps_below_minus_one():
    """Values below -1.0 are clamped to -1.0."""
    raw = {"substrate": {"courage": -2.5, "generosity": -0.1, "stability": 0.0}}
    soul, decisions = validate_soul(raw)
    assert soul["substrate"]["courage"] == -1.0

    clamped = [d for d in decisions if d.code == "soul.clamped"]
    assert len(clamped) == 1
    assert clamped[0].context["raw"] == -2.5
    assert clamped[0].context["clamped"] == -1.0


def test_validate_soul_defaults_missing_fields():
    """Missing substrate trait → 0.0 + soul.defaulted DP."""
    raw = {"substrate": {"courage": 0.5}}
    soul, decisions = validate_soul(raw)
    assert soul["substrate"]["generosity"] == 0.0
    assert soul["substrate"]["stability"] == 0.0

    defaulted = [d for d in decisions if d.code == "soul.defaulted"]
    fields = {d.context["field"] for d in defaulted}
    assert "substrate.generosity" in fields
    assert "substrate.stability" in fields


def test_validate_soul_defaults_non_numeric():
    """Non-numeric value → 0.0 + soul.defaulted DP."""
    raw = {"substrate": {"courage": "brave", "generosity": 0.0, "stability": 0.0}}
    soul, decisions = validate_soul(raw)
    assert soul["substrate"]["courage"] == 0.0

    defaulted = [d for d in decisions if d.code == "soul.defaulted"]
    courage_dp = [d for d in defaulted if d.context["field"] == "substrate.courage"]
    assert len(courage_dp) == 1


def test_validate_soul_always_returns_full_shape():
    """Even garbage input returns the full 7-key shape."""
    soul, _ = validate_soul({})
    assert soul["substrate"].keys() == set(SUBSTRATE_TRAITS)
    assert soul["axes"].keys() == set(AXES)
    for v in soul["substrate"].values():
        assert v == 0.0
    for v in soul["axes"].values():
        assert v == 0.0


def test_validate_soul_null_trait_is_defaulted():
    """Explicit None → 0.0 + soul.defaulted."""
    raw = {"substrate": {"courage": None}}
    soul, decisions = validate_soul(raw)
    assert soul["substrate"]["courage"] == 0.0
    defaulted = [d for d in decisions if d.code == "soul.defaulted"
                 and d.context["field"] == "substrate.courage"]
    assert len(defaulted) == 1


def test_validate_soul_axes_clamped():
    """Axes values are clamped and defaulted the same as substrate."""
    raw = {"axes": {"security": 1.5, "belonging": -2.0}}
    soul, decisions = validate_soul(raw)
    assert soul["axes"]["security"] == 1.0
    assert soul["axes"]["belonging"] == -1.0
    assert soul["axes"]["agency"] == 0.0
    assert soul["axes"]["satiation"] == 0.0


# ── tone_descriptor ───────────────────────────────────────────────

def test_tone_descriptor_timid():
    """courage ≤ -0.33 → 'timid'."""
    s = default_soul()
    s["substrate"]["courage"] = -0.5
    assert "timid" in tone_descriptor(s)


def test_tone_descriptor_bold():
    """courage ≥ 0.33 → 'bold'."""
    s = default_soul()
    s["substrate"]["courage"] = 0.7
    assert "bold" in tone_descriptor(s)


def test_tone_descriptor_guarded():
    """generosity ≤ -0.33 → 'guarded'."""
    s = default_soul()
    s["substrate"]["generosity"] = -0.4
    assert "guarded" in tone_descriptor(s)


def test_tone_descriptor_warm():
    """generosity ≥ 0.33 → 'warm'."""
    s = default_soul()
    s["substrate"]["generosity"] = 0.6
    assert "warm" in tone_descriptor(s)


def test_tone_descriptor_anxious():
    """stability ≤ -0.33 → 'anxious'."""
    s = default_soul()
    s["substrate"]["stability"] = -0.8
    assert "anxious" in tone_descriptor(s)


def test_tone_descriptor_steady():
    """stability ≥ 0.33 → 'steady'."""
    s = default_soul()
    s["substrate"]["stability"] = 0.5
    assert "steady" in tone_descriptor(s)


def test_tone_descriptor_multiple():
    """Multiple traits crossing threshold → joined with ', '."""
    s = default_soul()
    s["substrate"]["courage"] = -0.5
    s["substrate"]["generosity"] = 0.6
    s["substrate"]["stability"] = 0.0  # below threshold
    assert tone_descriptor(s) == "timid, warm"


def test_tone_descriptor_just_below_threshold_stays_even():
    """courage at -0.33 exactly → 'timid' (≥ threshold in absolute)."""
    s = default_soul()
    s["substrate"]["courage"] = -0.33
    assert tone_descriptor(s) == "timid"


def test_tone_descriptor_just_above_threshold_below_stays_even():
    """courage at -0.32 → below threshold → not tagged."""
    s = default_soul()
    s["substrate"]["courage"] = -0.32
    assert tone_descriptor(s) == "even-tempered"


def test_tone_descriptor_all_three():
    """All three traits crossing thresholds."""
    s = default_soul()
    s["substrate"]["courage"] = -0.8
    s["substrate"]["generosity"] = 0.7
    s["substrate"]["stability"] = -0.5
    assert tone_descriptor(s) == "timid, warm, anxious"


def test_tone_descriptor_non_dict_substrate():
    """Graceful with non-dict substrate."""
    s = {"substrate": "nonsense"}
    assert tone_descriptor(s) == "even-tempered"
