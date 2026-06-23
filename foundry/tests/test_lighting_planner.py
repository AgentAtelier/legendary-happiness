"""Tests for foundry.lighting_planner — deterministic motivated-lighting plan."""
from __future__ import annotations

from lighting_planner import plan_lighting

BRIEF = {"theme_tag": "stone_keep", "setting": "dusk study"}


def _plan(w=8, d=6, manifest=None):
    return plan_lighting(BRIEF, {"w": w, "d": d}, manifest or [], seed=0)


def test_exactly_one_hearth():
    p = _plan()
    hearths = [s for s in p["sources"] if s["type"] == "hearth"]
    assert len(hearths) == 1


def test_torch_count_scales_with_perimeter():
    small = sum(s["type"] == "torch" for s in _plan(6, 4)["sources"])
    big = sum(s["type"] == "torch" for s in _plan(14, 12)["sources"])
    assert big > small >= 2


def test_candles_only_on_tables():
    m = [{"id": "table_0", "category": "table", "x": 1.0, "z": 1.0},
         {"id": "rug_0", "category": "rug", "x": 0.0, "z": 0.0}]
    cands = [s for s in _plan(manifest=m)["sources"] if s["type"] == "candle"]
    assert len(cands) == 1
    assert abs(cands[0]["pos"][0] - 1.0) < 1e-6 and abs(cands[0]["pos"][2] - 1.0) < 1e-6


def test_windows_avoid_hearth_wall():
    p = _plan()
    hearth_wall = p["_hearth_wall"]
    assert p["windows"]
    assert all(wnd["wall"] != hearth_wall for wnd in p["windows"])


def test_environment_is_readable():
    env = _plan()["environment"]
    assert env["ambient_energy"] >= 0.5   # not the old near-black 0.4


def test_determinism():
    assert _plan() == _plan()
