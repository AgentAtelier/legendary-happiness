"""Tests for foundry.palette — deterministic scene palette from anchors + harmony."""
from __future__ import annotations

import colorsys
from palette import build_palette


def _v(rgb):  # HSV value
    return colorsys.rgb_to_hsv(*rgb)[2]


def test_deterministic():
    assert build_palette("stone_keep", 0) == build_palette("stone_keep", 0)


def test_roles_present():
    r = build_palette("stone_keep", 0)["roles"]
    assert set(r) >= {"base", "shadow", "midtone", "highlight", "accent", "foliage", "sky"}


def test_shadow_darker_than_base():
    r = build_palette("stone_keep", 0)["roles"]
    assert _v(r["shadow"]) < _v(r["base"]) <= _v(r["highlight"])


def test_dark_key_is_lower_value_than_bright():
    dark = build_palette("dusk_crypt", 0)["roles"]["base"]
    bright = build_palette("sunlit_market", 0)["roles"]["base"]
    assert _v(dark) < _v(bright)


def test_unknown_theme_falls_back():
    r = build_palette("no_such_theme_xyz", 0)["roles"]
    assert set(r) >= {"base", "shadow"}  # generic default, no crash


def test_seed_varies_within_mood():
    a = build_palette("stone_keep", 0)["roles"]["base"]
    b = build_palette("stone_keep", 7)["roles"]["base"]
    assert a != b  # perturbed
    assert abs(_v(a) - _v(b)) < 0.25  # but stays near the mood value
