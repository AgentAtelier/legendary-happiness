"""Unit tests for foundry.build_state — Brief+seed+plan round-trip.

Covers the contract from ROADMAP phase 0.10:

- A build writes build_state.json with the brief + seed + palette.
- load_build_state round-trips it.
- Deterministic JSON (sorted keys), missing file returns None,
  seed=None survives as JSON null.
"""

from __future__ import annotations

import json
from pathlib import Path

from brief import minimal
from build_state import SAVE_FILENAME, load_build_state, save_build_state
from palette import build_palette

# ── fixture builders ─────────────────────────────────────────────────


def _state(tmp_path: Path, *, seed: int | None = 42, theme: str = "sunlit_market") -> dict:
    """Build a representative state dict using only real foundry modules."""
    brief = minimal("a sunlit market with a wooden stall")
    return {
        "brief": brief,
        "seed": seed,
        "theme": theme,
        "room_size": {"w": 8.0, "d": 7.0, "h": 3.0},
        "lighting_plan": {
            "sources": [
                {"type": "hearth", "pos": [0.0, 0.5, -3.4],
                 "color": [1.0, 0.6, 0.3], "energy": 6.0, "range": 6.0,
                 "flicker": True},
            ],
            "windows": [{"wall": "E", "center": 0.5,
                         "width": 1.2, "height": 1.4, "sill": 1.2}],
            "sun": {"color": [0.5, 0.6, 0.85], "energy": 0.8,
                    "direction": [-0.3, -0.6, -0.5]},
            "sky": {"top": [0.4, 0.45, 0.6], "ambient_energy": 0.4},
            "environment": {"ambient_color": [0.4, 0.4, 0.45],
                            "ambient_energy": 0.6,
                            "fog_color": [0.15, 0.15, 0.2],
                            "fog_energy": 0.1,
                            "tonemap": 2, "exposure": 1.2},
            "_hearth_wall": "N",
        },
        "palette": build_palette(theme, seed if seed is not None else 0),
        "manifest_ref": "scenes/main_manifest.json",
    }


# ── save ─────────────────────────────────────────────────────────────


def test_save_writes_build_state_json(tmp_path):
    """save_build_state writes <build_dir>/build_state.json with all keys."""
    state = _state(tmp_path)
    out = save_build_state(tmp_path, **state)

    assert out == tmp_path / SAVE_FILENAME
    assert out.exists()

    loaded = json.loads(out.read_text())
    for k in ("brief", "seed", "theme", "room_size",
              "lighting_plan", "palette", "manifest_ref"):
        assert k in loaded, f"missing required key {k!r} in saved state"


def test_save_uses_sorted_keys(tmp_path):
    """The top-level keys in build_state.json are in sorted order."""
    state = _state(tmp_path)
    save_build_state(tmp_path, **state)
    loaded = json.loads((tmp_path / SAVE_FILENAME).read_text())
    assert list(loaded.keys()) == sorted(loaded.keys())


def test_save_is_byte_deterministic(tmp_path):
    """Two saves with identical inputs produce byte-identical files."""
    state = _state(tmp_path, seed=7)
    save_build_state(tmp_path, **state)
    a = (tmp_path / SAVE_FILENAME).read_text()
    save_build_state(tmp_path, **state)
    b = (tmp_path / SAVE_FILENAME).read_text()
    assert a == b


# ── load ─────────────────────────────────────────────────────────────


def test_load_round_trips_state(tmp_path):
    """load_build_state returns the JSON-serialised input verbatim.

    We compare both sides after a JSON round-trip so the test is honest
    about the fact that tuples → lists on the wire (palette/lighting
    RGB tuples). The contract is "the JSON form is canonical".
    """
    state = _state(tmp_path, seed=123)
    save_build_state(tmp_path, **state)

    loaded = load_build_state(tmp_path)
    assert loaded is not None

    # What we wrote is the JSON form of what we passed in.
    expected = json.loads(json.dumps(state))
    assert loaded == expected

    # Spot-check the headline fields are present with the right types.
    assert loaded["brief"]["setting"] == state["brief"]["setting"]
    assert loaded["brief"]["theme_tag"] == state["brief"]["theme_tag"]
    assert loaded["seed"] == 123
    assert loaded["theme"] == "sunlit_market"
    assert loaded["room_size"]["w"] == 8.0
    assert loaded["palette"]["theme"] == "sunlit_market"
    assert loaded["palette"]["seed"] == 123
    assert loaded["manifest_ref"] == "scenes/main_manifest.json"


def test_load_missing_file_returns_none(tmp_path):
    """A directory without build_state.json returns None (not {})."""
    assert load_build_state(tmp_path) is None


def test_load_accepts_string_path(tmp_path):
    """Path | str both work (callers often pass strings)."""
    state = _state(tmp_path)
    save_build_state(tmp_path, **state)
    loaded = load_build_state(str(tmp_path))
    assert loaded is not None
    assert loaded["theme"] == "sunlit_market"


# ── edge cases ───────────────────────────────────────────────────────


def test_seed_none_round_trips_as_null(tmp_path):
    """An unspecified seed serialises to JSON null and re-loads as None."""
    state = _state(tmp_path, seed=None)
    save_build_state(tmp_path, **state)

    raw = (tmp_path / SAVE_FILENAME).read_text()
    # Verify on-disk form: "seed": null with one space of indent
    assert '"seed": null' in raw

    loaded = load_build_state(tmp_path)
    assert loaded is not None
    assert loaded["seed"] is None


def test_save_creates_parent_directory(tmp_path):
    """save_build_state mkdirs the parent if missing (defensive)."""
    nested = tmp_path / "deep" / "nested" / "build"
    state = _state(nested)
    out = save_build_state(nested, **state)
    assert out.exists()
    assert load_build_state(nested) is not None
