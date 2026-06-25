"""Tests for foundry.world_cli — the human-patch World CLI.

Encodes the acceptance criteria:
    - add-space then show prints the space
    - overlapping add-space prints space.overlap + exits nonzero
    - load/replay round-trips
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add foundry/ to path so the CLI module can import world.*
_foundry_dir = str(Path(__file__).resolve().parent.parent)
if _foundry_dir not in sys.path:
    sys.path.insert(0, _foundry_dir)

from world.model import World
from world.persistence import load_world
from world_cli import main


def _run(*args: str) -> tuple[int, str, str]:
    """Run the CLI with given args; return (exit_code, stdout, stderr)."""
    import io

    old_out, old_err = sys.stdout, sys.stderr
    try:
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        sys.stdout = out_buf
        sys.stderr = err_buf
        exit_code = main(list(args))
        return exit_code, out_buf.getvalue(), err_buf.getvalue()
    except SystemExit as e:
        return (e.code if isinstance(e.code, int) else 1,
                out_buf.getvalue(), err_buf.getvalue())
    finally:
        sys.stdout = old_out
        sys.stderr = old_err


@pytest.fixture
def world_dir(tmp_path: Path) -> str:
    """A fresh directory for a world."""
    return str(tmp_path / "world")


# ── add-space then show ─────────────────────────────────────────────


def test_add_space_then_show(world_dir: str):
    """add-space creates a space; show prints it."""
    exit_code, out, err = _run("add-space", "--dir", world_dir,
                               "--id", "hall", "--size", "4", "3", "4")
    assert exit_code == 0, err
    assert "add_space applied" in out
    assert "1 space(s)" in out

    exit_code2, out2, err2 = _run("show", "--dir", world_dir)
    assert exit_code2 == 0, err2
    assert "[hall]" in out2
    assert "origin=" in out2
    assert "size=" in out2

    # Op count
    assert "Op count: 1" in out2


# ── overlapping add-space prints violation + exits nonzero ───────────


def test_overlapping_add_space_rejected(world_dir: str):
    """Two spaces that overlap → violation printed + exit 1."""
    # First space at origin, 4x3x4
    exit_code, out, err = _run("add-space", "--dir", world_dir,
                               "--id", "hall", "--size", "4", "3", "4")
    assert exit_code == 0, err

    # Second space that overlaps: origin (2,0,2), size 4x3x4 → overlaps hall
    exit_code2, out2, err2 = _run("add-space", "--dir", world_dir,
                                  "--id", "overlap", "--size", "4", "3", "4",
                                  "--origin", "2", "0", "2")
    assert exit_code2 == 1, f"expected nonzero exit, got {exit_code2}; stderr={err2}"
    assert "space.overlap" in err2
    assert "Violation" in err2


# ── add-space with theme ────────────────────────────────────────────


def test_add_space_with_theme(world_dir: str):
    """Theme is stored in the brief and visible in show."""
    exit_code, out, err = _run("add-space", "--dir", world_dir,
                               "--id", "throneroom", "--size", "6", "5", "6",
                               "--theme", "throne_room")
    assert exit_code == 0, err

    exit_code2, out2, err2 = _run("show", "--dir", world_dir)
    assert exit_code2 == 0, err2
    assert "theme=throne_room" in out2


# ── add-portal ──────────────────────────────────────────────────────


def test_add_portal_between_adjacent_spaces(world_dir: str):
    """Portal between two adjacent spaces succeeds."""
    # Space A at (0,0,0) 4x3x4
    _run("add-space", "--dir", world_dir, "--id", "a",
         "--size", "4", "3", "4")
    # Space B at (4,0,0) 4x3x4 — adjacent at x=4
    _run("add-space", "--dir", world_dir, "--id", "b",
         "--size", "4", "3", "4", "--origin", "4", "0", "0")

    exit_code, out, err = _run("add-portal", "--dir", world_dir,
                               "--id", "p_ab",
                               "--from", "a", "--to", "b",
                               "--pos", "4", "1.5", "2",
                               "--size", "1.5", "2")
    assert exit_code == 0, err
    assert "add_portal applied" in out
    assert "1 portal(s)" in out


# ── add-entity ──────────────────────────────────────────────────────


def test_add_entity_in_bounds(world_dir: str):
    """Entity placed inside its space succeeds."""
    _run("add-space", "--dir", world_dir, "--id", "hall",
         "--size", "4", "3", "4")

    exit_code, out, err = _run("add-entity", "--dir", world_dir,
                               "--space", "hall",
                               "--id", "throne", "--type", "throne",
                               "--pos", "2", "0", "2")
    assert exit_code == 0, err
    assert "add_entity applied" in out

    exit_code2, out2, err2 = _run("show", "--dir", world_dir)
    assert exit_code2 == 0, err2
    assert "id='throne'" in out2
    assert "type='throne'" in out2


def test_add_entity_out_of_bounds_rejected(world_dir: str):
    """Entity outside its space footprint → violation."""
    _run("add-space", "--dir", world_dir, "--id", "hall",
         "--size", "4", "3", "4")

    exit_code, out, err = _run("add-entity", "--dir", world_dir,
                               "--space", "hall",
                               "--id", "ghost", "--type", "ghost",
                               "--pos", "99", "0", "0")
    assert exit_code == 1, err
    assert "entity.out_of_bounds" in err


# ── move-entity ─────────────────────────────────────────────────────


def test_move_entity(world_dir: str):
    """Move an entity to a new position."""
    _run("add-space", "--dir", world_dir, "--id", "hall",
         "--size", "4", "3", "4")
    _run("add-entity", "--dir", world_dir, "--space", "hall",
         "--id", "candle", "--type", "candle",
         "--pos", "1", "1", "1")

    exit_code, out, err = _run("move-entity", "--dir", world_dir,
                               "--space", "hall",
                               "--id", "candle",
                               "--pos", "2", "1", "2")
    assert exit_code == 0, err
    assert "move_entity applied" in out


# ── replay round-trip ───────────────────────────────────────────────


def test_load_replay_round_trip(world_dir: str):
    """Save a world via CLI, then replay → same state."""
    _run("add-space", "--dir", world_dir, "--id", "hall",
         "--size", "4", "3", "4")
    _run("add-space", "--dir", world_dir, "--id", "keep",
         "--size", "4", "3", "4", "--origin", "4", "0", "0")

    exit_code, out, err = _run("replay", "--dir", world_dir)
    assert exit_code == 0, err
    assert "Reconstructed" in out
    assert "2 op(s)" in out
    assert "Spaces: 2" in out

    # Verify via load_world directly
    w = load_world(world_dir)
    assert set(w.nodes) == {"hall", "keep"}
    assert len(w.op_log) == 2


# ── error: missing world directory ──────────────────────────────────


def test_show_nonexistent_world_exits_nonzero(world_dir: str):
    """show/replay on a nonexistent world → nonzero exit + friendly error."""
    exit_code, out, err = _run("show", "--dir", world_dir)
    assert exit_code == 1
    assert "no world found" in err.lower()


def test_replay_nonexistent_world_exits_nonzero(world_dir: str):
    """replay on a nonexistent world → nonzero exit + friendly error."""
    exit_code, out, err = _run("replay", "--dir", world_dir)
    assert exit_code == 1
    assert "no world found" in err.lower()


# ── referential error ───────────────────────────────────────────────


def test_add_entity_missing_space_exits_nonzero(world_dir: str):
    """Adding an entity to a nonexistent space → nonzero exit."""
    exit_code, out, err = _run("add-entity", "--dir", world_dir,
                               "--space", "ghost",
                               "--id", "x", "--type", "x",
                               "--pos", "0", "0", "0")
    assert exit_code == 1
    # Referential error from apply_op, passed through WorldOpError
    assert "space not found" in err.lower() or "Error" in err
