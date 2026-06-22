"""V Task 1: Offscreen screenshot harness for Godot scenes and props.

Uses Godot's SubViewport + EGL surfaceless rendering to capture PNGs
without a display (no X11/Wayland window needed).  Deterministic for a
fixed scene + seed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional


# ── Public API ────────────────────────────────────────────────────


def capture_scene(
    build_dir: str,
    out_dir: str,
    angles: Optional[List[float]] = None,
    *,
    radius: float = 8.0,
    height: float = 3.0,
    godot_bin: str = "godot",
    capture_script: Optional[str] = None,
) -> List[str]:
    """Capture screenshots of a compiled Godot scene from fixed camera angles.

    The *build_dir* must be a valid Godot project (scaffolded by
    ``foundry.scaffold``) with a ``res://scenes/main.tscn``.

    Args:
        build_dir: Path to the Godot project directory.
        out_dir: Directory to write PNGs into.
        angles: List of yaw angles in radians (default: [0.0, 1.5708, 3.1416]).
        radius: Camera orbit radius from origin.
        height: Camera Y height.
        godot_bin: Path to Godot binary.
        capture_script: Path to ``capture_screenshot.gd`` (auto-located if None).

    Returns:
        List of absolute paths to generated PNG files.
    """
    if angles is None:
        angles = [0.0, 1.5708, 3.1416]  # front, right, back

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    capture_scene_path = _ensure_capture_scene(build_dir, capture_script)
    config = {
        "mode": "scene",
        "out_dir": str(out_path.resolve()),
        "angles": [round(a, 4) for a in angles],
        "radius": radius,
        "height": height,
        "scene_path": "res://scenes/main.tscn",
    }
    _set_capture_config(build_dir, config)
    _run_godot_capture(build_dir, godot_bin)

    return _read_manifest(out_path)


def capture_prop(
    glb_path: str,
    out_dir: str,
    angles: Optional[List[float]] = None,
    *,
    radius: float = 2.5,
    height: float = 1.2,
    godot_bin: str = "godot",
    capture_script: Optional[str] = None,
) -> List[str]:
    """Capture a single prop GLB from turntable camera angles.

    Creates a temporary Godot project that instances the GLB, renders
    it with a SubViewport, and saves PNGs.

    Args:
        glb_path: Path to the prop ``.glb`` file.
        out_dir: Directory to write PNGs into.
        angles: List of yaw angles in radians (default: [0.0, 2.094, 4.189]).
        radius: Camera orbit radius.
        height: Camera Y height.
        godot_bin: Path to Godot binary.
        capture_script: Path to ``capture_screenshot.gd``.

    Returns:
        List of absolute paths to generated PNG files.
    """
    if angles is None:
        angles = [0.0, 2.094, 4.189]  # 0°, 120°, 240°

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Create a disposable Godot project for this prop capture
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _scaffold_minimal_project(tmp_path, glb_path, capture_script)

        config = {
            "mode": "prop",
            "out_dir": str(out_path.resolve()),
            "angles": [round(a, 4) for a in angles],
            "radius": radius,
            "height": height,
            "glb_path": "res://assets/prop.glb",
        }
        _set_capture_config(str(tmp_path), config)
        _run_godot_capture(str(tmp_path), godot_bin)

    return _read_manifest(out_path)


# ── Internal helpers ──────────────────────────────────────────────


def _find_capture_script() -> str:
    """Locate the capture_screenshot.gd script in the godot template."""
    candidate = Path(__file__).resolve().parents[1] / "godot_template" / "scripts" / "capture_screenshot.gd"
    if candidate.exists():
        return str(candidate)
    raise FileNotFoundError(
        "capture_screenshot.gd not found. Provide capture_script= to override."
    )


def _ensure_capture_scene(build_dir: str, script_path: Optional[str] = None) -> str:
    """Copy the capture script into the build and wire it as the main scene.

    Creates (or updates) ``capture.tscn`` which loads the capture script,
    and sets ``run/main_scene`` in ``project.godot`` so Godot runs it on
    startup.  The capture script then instances the target scene as a child
    of its offscreen SubViewport.
    """
    script = script_path or _find_capture_script()
    bd = Path(build_dir)

    # Copy the GDScript
    dest = bd / "scripts" / "capture_screenshot.gd"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or _file_changed(script, str(dest)):
        shutil.copy2(script, dest)

    # Write capture.tscn — a minimal scene that runs the capture script
    tscn = bd / "capture.tscn"
    tscn.write_text("""[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://scripts/capture_screenshot.gd" id="1_script"]

[node name="Root" type="Node"]
script = ExtResource("1_script")
""")

    # Point the project's main_scene at capture.tscn
    pg = bd / "project.godot"
    text = pg.read_text()
    capture_line = 'run/main_scene="res://capture.tscn"'
    if "run/main_scene" in text:
        text = re.sub(
            r'^run/main_scene\s*=.*$',
            capture_line,
            text,
            flags=re.MULTILINE,
        )
    else:
        text = re.sub(
            r'^\[application\]$',
            f'[application]\n{capture_line}',
            text,
            flags=re.MULTILINE,
        )
    pg.write_text(text)

    return str(dest)


def _file_changed(src: str, dst: str) -> bool:
    """Return True if *src* differs from *dst*."""
    try:
        return Path(src).read_bytes() != Path(dst).read_bytes()
    except FileNotFoundError:
        return True


def _set_capture_config(build_dir: str, config: dict) -> None:
    """Write capture config into project.godot as a metadata override.

    Godot reads project settings from project.godot at startup; we
    inject ``_forge_capture`` so the capture script can find it via
    ``ProjectSettings.get_setting()``.
    """
    pg = Path(build_dir) / "project.godot"
    text = pg.read_text()

    # Escape JSON for Godot config: inner double-quotes → \"
    # (Godot's INI-like parser unescapes them at load time.)
    config_json = json.dumps(config).replace('"', '\\"')
    line = f'_forge_capture="{config_json}"'

    if "_forge_capture" in text:
        # Replace existing line
        text = re.sub(
            r'^_forge_capture\s*=.*$',
            line,
            text,
            flags=re.MULTILINE,
        )
    else:
        # Append after [application] section
        text = re.sub(
            r'^\[application\]$',
            f'[application]\n{line}',
            text,
            flags=re.MULTILINE,
        )
    pg.write_text(text)


def _scaffold_minimal_project(tmp_path: Path, glb_path: str, script_path: Optional[str] = None) -> None:
    """Create a disposable Godot project with the prop GLB and capture script."""
    assets = tmp_path / "assets"
    assets.mkdir(parents=True)
    shutil.copy2(glb_path, assets / "prop.glb")

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script = script_path or _find_capture_script()
    shutil.copy2(script, scripts_dir / "capture_screenshot.gd")

    # Write project.godot
    pg = tmp_path / "project.godot"
    pg.write_text("""[application]
config/name="prop_capture"
run/main_scene="res://capture.tscn"

[rendering]
renderer/rendering_method="mobile"
""")

    # Write a minimal capture scene that runs the script
    tscn = tmp_path / "capture.tscn"
    tscn.write_text("""[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://scripts/capture_screenshot.gd" id="1_script"]

[node name="Root" type="Node"]
script = ExtResource("1_script")
""")


def _run_godot_capture(build_dir: str, godot_bin: str) -> None:
    """Run Godot with the capture scene, using software GL + EGL offscreen.

    Raises ``RuntimeError`` if Godot exits non-zero.
    """
    env = {
        **os.environ,
        "EGL_PLATFORM": "surfaceless",
        "LIBGL_ALWAYS_SOFTWARE": "1",
        "MESA_GL_VERSION_OVERRIDE": "4.5",
        "DISPLAY": "",  # explicitly no X11
    }
    result = subprocess.run(
        [
            godot_bin,
            "--path", build_dir,
            "--rendering-driver", "opengl3",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    if result.returncode != 0:
        stderr_tail = result.stderr.strip()[-500:] if result.stderr else ""
        raise RuntimeError(
            f"Godot capture failed (rc={result.returncode})\n{stderr_tail}"
        )


def _read_manifest(out_dir: Path) -> List[str]:
    """Read the capture manifest JSON and return the list of PNG paths."""
    manifest = out_dir / "capture_manifest.json"
    if not manifest.exists():
        return []
    try:
        data = json.loads(manifest.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    return data.get("paths", [])
