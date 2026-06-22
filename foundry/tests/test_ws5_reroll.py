"""Unit tests for WS-5 V auto-reroll integration (foundry/__main__.py + visual/batch.py)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from visual.batch import reroll_flagged


# ── reroll_flagged ──────────────────────────────────────────────

def test_reroll_flagged_no_worklist_file(tmp_path):
    """Returns empty list when worklist file does not exist."""
    result = reroll_flagged(
        str(tmp_path / "nonexistent.json"),
        lexicon_path="lexicon.json",
        library_dir="assets",
    )
    assert result == []


def test_reroll_flagged_empty_worklist(tmp_path):
    """Returns empty list when worklist is empty."""
    wl_path = tmp_path / "wl.json"
    wl_path.write_text("[]")
    result = reroll_flagged(
        str(wl_path),
        lexicon_path="lexicon.json",
        library_dir="assets",
    )
    assert result == []


def test_reroll_flagged_skips_scene_ids(tmp_path):
    """CB-8: Scene IDs (no underscore) are skipped with a 'skipped' reason."""
    wl_path = tmp_path / "wl.json"
    wl_path.write_text(json.dumps(["crypt_03", "myscene"]))

    # Mock forge_from_request so the prop ID doesn't try to call real forge
    mock_result = MagicMock()
    mock_result.glb_path = "assets/crypt_03.glb"
    mock_result.gate.passed = True
    mock_result.gate.reasons = []
    mock_result.registered = True

    with patch("runner.forge_from_request", return_value=mock_result):
        result = reroll_flagged(
            str(wl_path),
            lexicon_path="lexicon.json",
            library_dir="assets",
            max_rerolls=1,
        )

    # Scene ID should be skipped
    scene_entry = [r for r in result if r["prop_id"] == "myscene"]
    assert len(scene_entry) == 1
    assert scene_entry[0]["rerolls"] == 0
    assert "skipped" in scene_entry[0]["last_result"]


def test_reroll_flagged_attempts_forge_for_props(tmp_path):
    """Prop IDs (with underscore) trigger forge_from_request calls."""
    wl_path = tmp_path / "wl.json"
    wl_path.write_text(json.dumps(["table_worn_oak"]))

    mock_result = MagicMock()
    mock_result.glb_path = "assets/table_worn_oak.glb"
    mock_result.gate.passed = True
    mock_result.gate.reasons = []
    mock_result.registered = True

    with patch("runner.forge_from_request", return_value=mock_result) as mock_forge:
        result = reroll_flagged(
            str(wl_path),
            lexicon_path="lexicon.json",
            library_dir="assets",
            max_rerolls=3,
        )

    assert len(result) == 1
    assert result[0]["rerolls"] == 1
    assert result[0]["last_result"]["gate_passed"] is True
    mock_forge.assert_called_once_with("table worn oak", "lexicon.json", "assets")


def test_reroll_flagged_retries_on_failure(tmp_path):
    """Failed gate triggers retries up to max_rerolls."""
    wl_path = tmp_path / "wl.json"
    wl_path.write_text(json.dumps(["chair_iron"]))

    fail_result = MagicMock()
    fail_result.glb_path = "assets/chair_iron.glb"
    fail_result.gate.passed = False
    fail_result.gate.reasons = ["polycount exceeded"]
    fail_result.registered = False

    with patch("runner.forge_from_request", return_value=fail_result) as mock_forge:
        result = reroll_flagged(
            str(wl_path),
            lexicon_path="lexicon.json",
            library_dir="assets",
            max_rerolls=2,
        )

    assert len(result) == 1
    assert result[0]["rerolls"] == 2  # tried twice, both failed
    assert result[0]["last_result"]["gate_passed"] is False
    assert mock_forge.call_count == 2


def test_reroll_flagged_handles_exceptions(tmp_path):
    """Exceptions during forge are caught and recorded."""
    wl_path = tmp_path / "wl.json"
    wl_path.write_text(json.dumps(["cup_brass"]))

    with patch("runner.forge_from_request", side_effect=RuntimeError("LLM timeout")):
        result = reroll_flagged(
            str(wl_path),
            lexicon_path="lexicon.json",
            library_dir="assets",
            max_rerolls=1,
        )

    assert len(result) == 1
    assert result[0]["rerolls"] == 1
    assert "error" in result[0]["last_result"]


def test_reroll_flagged_max_rerolls_honored(tmp_path):
    """max_rerolls parameter caps the number of attempts."""
    wl_path = tmp_path / "wl.json"
    wl_path.write_text(json.dumps(["book_leather"]))

    fail_result = MagicMock()
    fail_result.glb_path = "assets/book_leather.glb"
    fail_result.gate.passed = False
    fail_result.gate.reasons = []
    fail_result.registered = False

    with patch("runner.forge_from_request", return_value=fail_result) as mock_forge:
        result = reroll_flagged(
            str(wl_path),
            lexicon_path="lexicon.json",
            library_dir="assets",
            max_rerolls=5,
        )

    assert mock_forge.call_count == 5
    assert result[0]["rerolls"] == 5
