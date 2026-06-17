"""Tests for shootout scene-isolation — the guarantee that the benchmark
runs in a disposable scene and never contaminates the real game.

These guard the Stream-E fix: a missing shootout.tscn + project_run(mode=main,
autosave=True) was running every model against the real main.tscn (capping
runtime at 0/32 and persisting junk into the user's RPG on disk).
"""

from unittest.mock import patch

import pytest
import shootout


def test_baseline_scene_has_main_root():
    """The canonical baseline must define a Node3D root named 'Main' so the
    prompt's '/Main' paths resolve exactly as against the real game scene."""
    tscn = shootout.SHOOTOUT_SCENE_TSCN
    assert '[node name="Main" type="Node3D"]' in tscn
    assert 'type="Camera3D"' in tscn
    assert 'type="StaticBody3D"' in tscn  # Ground


def test_base_scene_differs_from_shootout_scene():
    """The bounce scene must differ from the shootout scene, else scene_open
    can't force a fresh disk re-read (it's a no-op on the active scene)."""
    assert shootout.BASE_SCENE != shootout.SHOOTOUT_SCENE


@pytest.mark.asyncio
async def test_open_fresh_bounces_through_other_scene():
    """_open_fresh must open a DIFFERENT scene first, then the target — so
    unsaved model mutations are discarded and the file is re-read from disk."""
    calls = []

    async def fake_call(tool, args):
        calls.append((tool, args.get("path")))
        return {}

    with patch.object(shootout, "_godot_ai_call", side_effect=fake_call):
        await shootout._open_fresh(shootout.SHOOTOUT_SCENE)

    assert [t for t, _ in calls] == ["scene_open", "scene_open"]
    bounce, target = calls[0][1], calls[1][1]
    assert bounce == shootout.BASE_SCENE  # bounced away first
    assert target == shootout.SHOOTOUT_SCENE  # then re-opened target
    assert bounce != target


@pytest.mark.asyncio
async def test_with_heartbeat_ticks_and_returns_value():
    """_with_heartbeat must emit elapsed-time ticks while a slow coro runs and
    still return the coro's result — this is what keeps long phases (swap, 40s+
    planner) from looking frozen in the UI."""
    import asyncio

    beats = []

    async def slow():
        await asyncio.sleep(0.35)
        return "result"

    out = await shootout._with_heartbeat(slow(), beats.append, "work", interval=0.1)
    assert out == "result"
    assert beats, "expected at least one heartbeat tick"
    assert all("work still running" in b for b in beats)


@pytest.mark.asyncio
async def test_with_heartbeat_no_ticks_for_fast_coro():
    """A coro that finishes before the first interval emits no noise."""

    async def fast():
        return 42

    beats = []
    out = await shootout._with_heartbeat(fast(), beats.append, "x", interval=5.0)
    assert out == 42
    assert beats == []


@pytest.mark.asyncio
async def test_reset_scene_rewrites_baseline_then_opens():
    """_reset_scene must rewrite the pristine baseline to disk BEFORE opening,
    guaranteeing a clean scene regardless of what a prior run left behind."""
    seq = []

    async def fake_call(tool, args):
        if tool == "filesystem_manage":
            seq.append(("write", args["params"]["path"], args["params"]["content"]))
        elif tool == "scene_open":
            seq.append(("open", args["path"]))
        return {}

    with patch.object(shootout, "_godot_ai_call", side_effect=fake_call):
        await shootout._reset_scene()

    # First action is the baseline write to the shootout scene…
    assert seq[0][0] == "write"
    assert seq[0][1] == shootout.SHOOTOUT_SCENE
    assert '[node name="Main" type="Node3D"]' in seq[0][2]
    # …and the target ends up opened.
    assert seq[-1] == ("open", shootout.SHOOTOUT_SCENE)
