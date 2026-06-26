"""Regression tests for _capture_strip_vulkan_features() — atomic write
+ sentinel restore survives an interrupted capture.

Roadmap-0.11 contract: if godot OOMs / is killed / raises between the
strip and the restore call, ``_capture_strip_vulkan_features()`` must
recover the project's real ``config/features`` line from the on-disk
sentinel rather than from the now-stripped project.godot.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, "/home/mrg/dev/games/Forge/foundry")
from visual.screenshot import _capture_strip_vulkan_features  # noqa: E402

_FORWARD_PLUS_LINE = (
    'config/features=PackedStringArray("4.7", "Forward Plus")\n'
)
_AFTER_STRIP_LINE = 'config/features=PackedStringArray("4.7")\n'


@pytest.fixture
def project_godot(tmp_path: Path) -> Path:
    pg = tmp_path / "project.godot"
    pg.write_text(
        "[application]\n"
        + _FORWARD_PLUS_LINE
        + "[physics]\n"
        + '3d/physics_engine="Jolt Physics"\n',
        encoding="utf-8",
    )
    return pg


def test_strip_returns_callable(project_godot: Path) -> None:
    restore = _capture_strip_vulkan_features(project_godot)
    assert callable(restore)


def test_strip_removes_forward_plus(project_godot: Path) -> None:
    _capture_strip_vulkan_features(project_godot)
    text = project_godot.read_text(encoding="utf-8")
    assert "Forward Plus" not in text
    assert '"4.7"' in text


def test_strip_is_no_op_when_feature_line_absent(tmp_path: Path) -> None:
    """The synthetic prop_capture project has no config/features= line."""
    pg = tmp_path / "project.godot"
    pg.write_text("[application]\nrun/main_scene=\"res://capture.tscn\"\n")
    original = pg.read_text(encoding="utf-8")
    restore = _capture_strip_vulkan_features(pg)
    # No strip => identical content.
    assert pg.read_text(encoding="utf-8") == original
    restore()
    assert pg.read_text(encoding="utf-8") == original


def test_restore_round_trips(project_godot: Path) -> None:
    """Strip succeeds, restore returns project.godot to original byte-for-byte."""
    original = project_godot.read_text(encoding="utf-8")
    restore = _capture_strip_vulkan_features(project_godot)
    # Sanity: stripped now.
    assert "Forward Plus" not in project_godot.read_text(encoding="utf-8")
    restore()
    assert project_godot.read_text(encoding="utf-8") == original


def test_restore_uses_sentinel_not_project_godot(project_godot: Path) -> None:
    """If the user manually clobbers project.godot during capture (between
    strip and restore), the restore still recovers the ORIGINAL feature
    line from the sentinel — not from the (now clobbered) project.godot.
    """
    original = project_godot.read_text(encoding="utf-8")
    restore = _capture_strip_vulkan_features(project_godot)
    # Simulate user (or another process) clobbering project.godot during
    # the capture window.
    project_godot.write_text("OVERWRITTEN-DURING-CAPTURE\n", encoding="utf-8")
    restore()
    assert project_godot.read_text(encoding="utf-8") == original


def test_strip_no_op_does_not_leave_sentinel(project_godot: Path) -> None:
    """When the regex doesn't match (no features line), no tmp or sentinel
    file should be left behind in build_dir."""
    project_godot.write_text(
        "[application]\nrun/main_scene=\"res://capture.tscn\"\n",
        encoding="utf-8",
    )
    _capture_strip_vulkan_features(project_godot)
    parent = project_godot.parent
    leaked = [
        p for p in parent.iterdir()
        if p.name.endswith(".capture_tmp")
        or p.name.endswith(".capture_features_snapshot")
        or p.name.endswith(".capture_features_snapshot.tmp")
    ]
    assert not leaked, f"unexpected leftover files: {leaked}"


def test_restore_cleans_up_sentinel(project_godot: Path) -> None:
    """After successful single-strip + restore, no sentinel/tmp file
    remains.  (The original draft had a test-side bug: it called the
    strip three times but only restored once, leaving two orphans on
    disk; the production code is correct — verify by a single
    strip-then-restore cycle.)"""
    snapshot = project_godot.with_name(
        project_godot.name + ".capture_features_snapshot"
    )
    snap_tmp = project_godot.with_name(
        project_godot.name + ".capture_features_snapshot.tmp"
    )
    tmp = project_godot.with_name(project_godot.name + ".capture_tmp")
    restore = _capture_strip_vulkan_features(project_godot)
    # Pre-condition: sentinel + snap_tmp files exist right after strip.
    assert snapshot.exists(), "sentinel must be on disk after strip"
    restore()
    # Post-condition: no leftover sentinel / tmp / snapshot files.
    leftovers = [
        p for p in project_godot.parent.iterdir()
        if p.name in (
            snapshot.name,
            snap_tmp.name,
            tmp.name,
        )
    ]
    assert not leftovers, f"left: {[p.name for p in leftovers]}"


def test_double_strip_then_double_restore(project_godot: Path) -> None:
    """Two captures back-to-back (with restore in between) must round-trip."""
    original = project_godot.read_text(encoding="utf-8")
    r1 = _capture_strip_vulkan_features(project_godot)
    r1()
    assert project_godot.read_text(encoding="utf-8") == original
    r2 = _capture_strip_vulkan_features(project_godot)
    r2()
    assert project_godot.read_text(encoding="utf-8") == original


def test_sentinel_exists_after_strip(project_godot: Path) -> None:
    """A regression guard: a future refactor that writes the sentinel
    AFTER the stripped write would survive the round-trip test on a
    happy path but lose original text if the process died between the
    strip and the atomic-rename.  This test asserts the invariant:
    after the strip returns, the on-disk sentinel must already exist
    (and contain the original text)."""
    original = project_godot.read_text(encoding="utf-8")
    snapshot = project_godot.with_name(
        project_godot.name + ".capture_features_snapshot"
    )
    _capture_strip_vulkan_features(project_godot)
    # Strip returned -> sentinel must already be on disk.
    assert snapshot.exists(), "sentinel must be written before strip return"
    assert snapshot.read_text(encoding="utf-8") == original
