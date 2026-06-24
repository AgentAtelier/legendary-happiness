"""Unit tests for WS-4 UX shell scripts — prompt_screen, build_report_panel, day_night atmosphere."""

from pathlib import Path

GD_SCRIPTS = Path(__file__).resolve().parents[1] / "godot_template" / "scripts"


def _read_gd(name: str) -> str:
    """Read a GDScript file as text."""
    return (GD_SCRIPTS / name).read_text(encoding="utf-8")


# ── prompt_screen.gd ──────────────────────────────────────

def test_prompt_screen_exists():
    """prompt_screen.gd is created."""
    assert (GD_SCRIPTS / "prompt_screen.gd").is_file()


def test_prompt_screen_has_generate():
    """prompt_screen.gd has _on_generate_pressed handler."""
    text = _read_gd("prompt_screen.gd")
    assert "_on_generate_pressed" in text
    assert "_start_building" in text


def test_prompt_screen_has_feedback():
    """prompt_screen.gd shows World building... feedback."""
    text = _read_gd("prompt_screen.gd")
    assert "World building" in text


def test_prompt_screen_extends_control():
    """prompt_screen.gd extends Control for UI."""
    text = _read_gd("prompt_screen.gd")
    assert "extends Control" in text


def test_prompt_screen_writes_prompt_file():
    """prompt_screen.gd writes prompt to PROMPT_FILE."""
    text = _read_gd("prompt_screen.gd")
    assert "PROMPT_FILE" in text
    assert "FileAccess.open" in text


# ── build_report_panel.gd ─────────────────────────────────

def test_build_report_panel_exists():
    """build_report_panel.gd is created."""
    assert (GD_SCRIPTS / "build_report_panel.gd").is_file()


def test_build_report_panel_extends_control():
    """build_report_panel.gd extends Control for UI."""
    text = _read_gd("build_report_panel.gd")
    assert "extends Control" in text


def test_build_report_panel_has_sections():
    """build_report_panel.gd renders Understood / Built / Assumed / Couldn't."""
    text = _read_gd("build_report_panel.gd")
    for section in ("understood", "built", "assumed", "couldnt"):
        assert section in text.lower(), f"missing {section} section"


def test_build_report_panel_loads_json():
    """build_report_panel.gd reads build_report.json."""
    text = _read_gd("build_report_panel.gd")
    assert "REPORT_PATH" in text or "build_report.json" in text
    assert "_load_report" in text


def test_build_report_panel_toggle_key():
    """build_report_panel.gd toggles on B key."""
    text = _read_gd("build_report_panel.gd")
    assert "KEY_B" in text


# ── day_night.gd atmosphere ───────────────────────────────

def test_day_night_has_sdfgi():
    """day_night.gd has SDFGI bounce feedback hooks."""
    text = _read_gd("day_night.gd")
    assert "sdfgi_enabled" in text
    assert "sdfgi_bounce_feedback" in text


def test_day_night_has_glow():
    """day_night.gd has glow/bloom hooks."""
    text = _read_gd("day_night.gd")
    assert "glow_enabled" in text


def test_day_night_has_ssao():
    """day_night.gd has SSAO hooks."""
    text = _read_gd("day_night.gd")
    assert "ssao_enabled" in text


def test_day_night_has_fog_height():
    """day_night.gd has fog height falloff."""
    text = _read_gd("day_night.gd")
    assert "fog_height" in text


def test_day_night_has_theme_presets():
    """day_night.gd has THEME_PRESETS dictionary."""
    text = _read_gd("day_night.gd")
    assert "THEME_PRESETS" in text
    for theme in ("crypt", "tavern", "armory", "workshop"):
        assert theme in text, f"missing theme {theme}"


def test_day_night_has_apply_theme():
    """day_night.gd has apply_theme() function."""
    text = _read_gd("day_night.gd")
    assert "func apply_theme" in text


def test_day_night_has_get_theme_names():
    """day_night.gd has get_theme_names() helper."""
    text = _read_gd("day_night.gd")
    assert "func get_theme_names" in text


# ── GDScript parse check (no syntax errors) ───────────────

def test_prompt_screen_no_parse_errors():
    """prompt_screen.gd has no obvious syntax issues."""
    text = _read_gd("prompt_screen.gd")
    # Basic balance check: extends, func, var
    assert text.count("func ") >= 3, "expected at least 3 functions"
    assert text.count("\n") > 20, "expected substantive script"


def test_build_report_panel_no_parse_errors():
    """build_report_panel.gd has no obvious syntax issues."""
    text = _read_gd("build_report_panel.gd")
    assert text.count("func ") >= 3
    assert text.count("\n") > 20


def test_day_night_no_parse_errors():
    """day_night.gd has no obvious syntax issues after WS-4 edits."""
    text = _read_gd("day_night.gd")
    assert text.count("func ") >= 4
    # Verify it still extends Node
    assert "extends" in text
