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
from collections.abc import Callable
from pathlib import Path
from typing import List

# ── Public API ────────────────────────────────────────────────────


def capture_scene(
    build_dir: str,
    out_dir: str,
    angles: List[float] | None = None,
    *,
    radius: float = 5.0,
    height: float = 1.7,
    hardware_gpu: bool = False,
    godot_bin: str = "godot",
    capture_script: str | None = None,
) -> List[str]:
    """Capture screenshots of a compiled Godot scene from fixed camera angles.

    CB-8: Default radius reduced from 8.0→5.0 and height from 3.0→1.7
    (player-eye framing — stays inside the room instead of seeing through walls).

    **Software-render requirement (roadmap 0.11):** on a Mesa-only
    headless box, ``capture_scene`` requires Mesa's software Vulkan
    (``vulkan-swrast`` / lavapipe) to be installed — Arch Linux:
    ``sudo pacman -S vulkan-swrast``.  Without lavapipe, Godot 4.7
    in --headless mode silently falls back to the DUMMY renderer for
    SubViewport textures and every PNG comes back blank (~2 KB).
    If your box has a real GPU and AMD/NVIDIA ICD, no software install
    is needed.

    **Determinism (MESA env vars):** callers who need byte-identical
    captures across runs MUST ensure none of
    ``MESA_LOADER_DRIVER_OVERRIDE``, ``MESA_GL_VERSION_OVERRIDE``,
    ``MESA_GLSL_VERSION_OVERRIDE``, or ``LIBGL_ALWAYS_SOFTWARE`` is set
    in their CI environment — a stray override can re-introduce the
    original dummy-renderer fallback.  See ``_capture_env`` for the
    harness defaults.

    The *build_dir* must be a valid Godot project (scaffolded by
    ``foundry.scaffold``) with a ``res://scenes/main.tscn``.

    Args:
        build_dir: Path to the Godot project directory.
        out_dir: Directory to write PNGs into.
        angles: List of yaw angles in radians (default: [0.0, 1.5708, 3.1416]).
        radius: Camera orbit radius from origin (default 5.0 — player-eye interior).
        height: Camera Y height (default 1.7 — player eye-level).
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
        "radius": round(radius, 2),
        "height": round(height, 2),
        "scene_path": "res://scenes/main.tscn",
        # capture_screenshot.gd reads this to decide whether to triple-arm
        # UPDATE_ONCE (software Mesa warm-up) or single-arm (hardware GPU).
        "hardware_gpu": bool(hardware_gpu),
    }
    _set_capture_config(build_dir, config)
    _run_godot_capture(build_dir, godot_bin)

    return _read_manifest(out_path)


def capture_prop(
    glb_path: str,
    out_dir: str,
    angles: List[float] | None = None,
    *,
    radius: float = 2.5,
    height: float = 1.2,
    godot_bin: str = "godot",
    capture_script: str | None = None,
) -> List[str]:
    """Capture a single prop GLB from turntable camera angles.

    Creates a temporary Godot project that instances the GLB, renders
    it with a SubViewport, and saves PNGs.

    Note: prop capture always uses the software-Mesa warm-up triple-arm
    path, since props are usually tested on small displays with limited
    GPU access.

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
            # capture_screenshot.gd reads this to decide triple vs single
            # UPDATE_ONCE re-arm.  Props always use triple-arm (software Mesa
            # warm-up) since they hit the small-display path.
            "hardware_gpu": False,
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


def _ensure_capture_scene(build_dir: str, script_path: str | None = None) -> str:
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


def _scaffold_minimal_project(tmp_path: Path, glb_path: str, script_path: str | None = None) -> None:
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


# Vulkan-only project features that *require* the Vulkan driver at runtime.
# In a software-only mesa build (where lavapipe/Vulkan-ICD isn't installed
# and only llvmpipe/GL is available), Godot silently falls back to the
# DUMMY renderer when the project advertises one of these in its feature
# set.  Roadmap 0.11 regression root cause (forward plus features not
# stripped from generated project.godot).
_VULKAN_ONLY_FEATURES = frozenset({"Forward Plus", "Mobile"})


def _has_lavapipe_icd_at(icd_dir: Path) -> bool:
    """Return True if *icd_dir* contains a Mesa software-Vulkan (lavapipe) ICD.

    Splits the probe so unit tests can lay out a fixture directory and
    exercise it without monkeypatching ``pathlib.Path``.  Caller passes the
    resolved absolute path; patterns match the lavapipe filenames installed
    by Debian/Ubuntu (``lvp_icd.x86_64.json``), Fedora
    (``swrast_icd.x86_64.json``), and Arch (``lvp_icd.x86_64.json``).
    """
    if not icd_dir.exists():
        return False
    for pattern in ("*lvp_icd*", "*swrast*"):
        if next(iter(icd_dir.glob(pattern)), None) is not None:
            return True
    return False


def _has_lavapipe_icd() -> bool:
    """Return True if Mesa's software-Vulkan ICD (lavapipe) is installed.

    Vendor-neutral: scans the standard Vulkan ICD directory used by
    Debian/Ubuntu/Fedora/Arch, AND validates that any explicit
    ``VK_ICD_FILENAMES`` env override points to existing files (so a
    stale or typo'd path doesn't falsely claim "Vulkan OK").

    Currently advisory — included as a captured diagnostic in the
    dummy-renderer RuntimeError.  Callers wanting fail-fast can call
    this directly.
    """
    raw = os.environ.get("VK_ICD_FILENAMES", "")
    tokens = [t.strip() for t in raw.split(":") if t.strip()]
    if tokens:
        # Honour only well-formed entries; a single typo'd or whitespace-
        # only token in the colon list invalidates the whole override
        # (don't lie to the caller that Vulkan is configured when one
        # path is bogus).
        return all(Path(t).expanduser().is_file() for t in tokens)
    return _has_lavapipe_icd_at(Path("/usr/share/vulkan/icd.d"))


def _capture_strip_vulkan_features(project_godot: Path) -> Callable[[], None]:
    """Strip Vulkan-only features from ``project.godot`` for headless capture.

    Reads the project file, removes every Vulkan-only entry from
    ``config/features=PackedStringArray(...)``, writes it back, and returns
    a restore callable.  If the features are already absent (or no
    ``config/features`` line is present), the strip is a no-op and the
    returned restore callable is also a no-op.

    Why (``roadmap 0.11``): ``foundry/godot_template/project.godot`` ships
    with ``config/features=PackedStringArray("4.7", "Forward Plus")``.
    On a headless box where ``lvp_icd.x86_64.json`` (Mesa's software Vulkan
    / lavapipe) is not installed, the only available Vulkan driver is
    ``radeon_icd.json`` (or similar), which can't acquire a context on a
    process with no GPU access.  Godot then silently picks the dummy
    renderer and ``SubViewport.get_texture().get_image()`` returns null.
    The dummy-renderer guard in ``_run_godot_capture`` would catch it,
    but the captures are silently blank.  Forward Plus strip lets the
    build run with opengl3 + llvmpipe + EGL surfaceless, acquiring a real
    GL context and producing real PNGs.
    """
    if not project_godot.exists():
        return lambda: None
    original = project_godot.read_text(encoding="utf-8")

    def _clean(match: re.Match[str]) -> str:
        # Inside the parens: a comma-separated list of quoted entries, possibly
        # with arbitrary whitespace.  Parse each entry into a list of tokens
        # (no commas / no parens; Godot feature tokens are simple identifiers).
        items: list[str] = []
        for raw in match.group(1).split(","):
            tok = raw.strip().strip('"').strip("'")
            if tok:
                items.append(tok)
        kept = [s for s in items if s not in _VULKAN_ONLY_FEATURES]
        # Godot's INI parser requires double-quoted strings (Python's repr()
        # would emit single quotes — don't use it).
        inner = ", ".join(f'"{s}"' for s in kept)
        return f"config/features=PackedStringArray({inner})"

    stripped = re.sub(
        r"config/features=PackedStringArray\((.*?)\)",
        _clean,
        original,
        flags=re.DOTALL,
    )
    if stripped == original:
        return lambda: None
    # Atomic-write + sentinel.  POSIX rename() is atomic on same-fs;
    # the capture_tmp lives next to project.godot in build_dir so the
    # rename is same-volume and atomic.
    #
    # Order of writes is critical when a godot OOM/signal crashes
    # mid-strip:
    #   1. Write original -> .capture_features_snapshot.tmp, rename to
    #      .capture_features_snapshot (atomic).  Sentinel now on disk.
    #   2. Write stripped  -> .capture_tmp, rename to project.godot
    #      (atomic).  project.godot now stripped.
    # If killed between (1) and (2): sentinel exists, project.godot
    # unchanged — restore is trivial (or no-op).
    # If killed after (2): sentinel + stripped — restore reads sentinel.
    name = project_godot.name
    parent = project_godot.parent
    tmp = parent / (name + ".capture_tmp")
    snapshot = parent / (name + ".capture_features_snapshot")
    snap_tmp = parent / (name + ".capture_features_snapshot.tmp")
    # 1. Write sentinel BEFORE we touch project.godot.
    snap_tmp.write_text(original, encoding="utf-8")
    os.replace(snap_tmp, snapshot)
    # 2. Strip project.godot (still recoverable via the sentinel).
    tmp.write_text(stripped, encoding="utf-8")
    os.replace(tmp, project_godot)

    def _restore() -> None:
        # Always restore from the on-disk sentinel so a re-entry to
        # this function can't read the already-stripped project.godot
        # as the "original" and clobber the user's real features list.
        try:
            snap_text = snapshot.read_text(encoding="utf-8")
        except OSError:
            # No sentinel ⇒ no strip happened OR a previous restore
            # already ran.  Either way project.godot is the source of
            # truth; if it equals *stripped* we can't help.
            return
        try:
            tmp.write_text(snap_text, encoding="utf-8")
            os.replace(tmp, project_godot)
        except OSError:
            try:
                project_godot.write_text(snap_text, encoding="utf-8")
            except OSError:
                # Best-effort: at least don't leave a stripped file
                # when we couldn't restore.
                pass
            return  # Don't unlink sentinel on restore failure.
        # Restore succeeded -> safe to clean up the sentinel + tmp.
        try:
            snapshot.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            snap_tmp.unlink(missing_ok=True)
        except OSError:
            pass

    return _restore


def _capture_env() -> dict:
    """Environment for headless Godot: EGL surfaceless + software GL.

    Without a display, the only way to get a non-dummy renderer is
    EGL surfaceless with software Mesa.  The dummy renderer returns
    null SubViewport textures.  Software GL IS slow (~10-30 s per
    frame for complex scenes) but correct — the ``_run_godot_capture``
    timeout (240 s) is set accordingly.

    Why the explicit overrides (``roadmap 0.11``)?

    - ``MESA_LOADER_DRIVER_OVERRIDE=llvmpipe``: forces Mesa's EGL loader
      to dispatch through llvmpipe explicitly, bypassing ambiguous driver
      probing (e.g. on multi-driver systems where the loader defaults to
      a non-llvmpipe driver and then fails the context probe).

    - ``MESA_GL_VERSION_OVERRIDE=4.5`` plus ``MESA_GLSL_VERSION_OVERRIDE=450``
      plus ``LIBGL_ALWAYS_SOFTWARE=1``: pins Mesa to llvmpipe AND forces a
      GL 4.5 / GLSL 450 profile up-front.  Without the version override,
      llvmpipe's surfaceless EGL probe returns a pre-3.3 profile that
      Godot's GL3 driver rejects.

    - Pop ``DISPLAY`` / ``WAYLAND_DISPLAY`` / ``WAYLAND_SOCKET`` /
      ``XDG_SESSION_TYPE``: block the parent process's display-session vars
      from leaking into the subprocess.  In Godot 4.7, inherited
      ``WAYLAND_DISPLAY=wayland-*`` overrides ``EGL_PLATFORM=surfaceless``
      and Mesa tries Wayland first, failing back to the dummy renderer
      when it can't acquire a surface.  Popping is stronger than empty-
      string overrides — future Mesa builds may stop honouring
      ``WAYLAND_DISPLAY=""`` as unset.

    User-supplied env vars (e.g. ``MESA_GL_VERSION_OVERRIDE=4.6`` set in
    the calling shell for diagnostic experiments) take precedence over
    the harness defaults via ``os.environ.get(KEY, default)`` semantics.

    Determinism note: callers who need byte-identical captures across
    runs MUST ensure none of ``MESA_LOADER_DRIVER_OVERRIDE``,
    ``MESA_GL_VERSION_OVERRIDE``, ``MESA_GLSL_VERSION_OVERRIDE``, or
    ``LIBGL_ALWAYS_SOFTWARE`` is set in their CI environment — a stray
    override can re-introduce the original dummy-renderer fallback.
    """
    env = dict(os.environ)
    for k in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "XDG_SESSION_TYPE"):
        env.pop(k, None)
    env.update({
        # EGL backend: no surface, no display server required.
        "EGL_PLATFORM": "surfaceless",
        # Mesa: pin to llvmpipe (required for surfaceless EGL on a
        # headless box) with a profile Godot's GL3 driver accepts.
        # Honour any user override at the calling shell (lets users
        # experiment with e.g. MESA_GL_VERSION_OVERRIDE=4.6).
        "MESA_LOADER_DRIVER_OVERRIDE": os.environ.get(
            "MESA_LOADER_DRIVER_OVERRIDE", "llvmpipe"),
        "LIBGL_ALWAYS_SOFTWARE": os.environ.get("LIBGL_ALWAYS_SOFTWARE", "1"),
        "MESA_GL_VERSION_OVERRIDE": os.environ.get(
            "MESA_GL_VERSION_OVERRIDE", "4.5"),
        "MESA_GLSL_VERSION_OVERRIDE": os.environ.get(
            "MESA_GLSL_VERSION_OVERRIDE", "450"),
    })
    return env


def _run_godot_import(build_dir: str, godot_bin: str) -> None:
    """Import the project's resources (headless) before capture.

    A fresh/disposable project has no ``.godot/imported`` cache, so
    ``load("res://...glb")`` returns null ("No loader found for resource")
    until the editor import pass has generated the ``.import`` sidecars and
    the ``.scn`` for each GLB.  Running the project directly does NOT import
    new assets — this pass must run first.  Import warnings are tolerated
    (non-zero exit is not fatal); a genuinely failed import surfaces later
    as a load error in the capture run.
    """
    subprocess.run(
        [godot_bin, "--headless", "--path", build_dir, "--import"],
        capture_output=True,
        text=True,
        timeout=_CAPTURE_TIMEOUT_S,
        env=_capture_env(),
    )


# Capture timeout.  Raise it past 120 s because software Mesa (llvmpipe) is
# 5-10 s per frame on a complex room, and we render 3 angles × 3 frame-waits
# each — measured ~150-200 s on builds/m1_lit on this box.
_CAPTURE_TIMEOUT_S = 240


def _run_godot_capture(build_dir: str, godot_bin: str) -> None:
    """Run Godot with the capture scene, using software GL + EGL offscreen.

    Raises ``RuntimeError`` if the capture run exits non-zero OR stderr
    contains a Parse Error (missing assets that silently produce blank PNGs
    otherwise).  Vulkan-only features (``Forward Plus``, ``Mobile``) are
    stripped from ``project.godot`` for the duration of capture and
    restored afterwards — see ``_capture_strip_vulkan_features`` for why.

    On a Mesa-only headless box, if Mesa's software Vulkan (lavapipe)
    isn't installed Godot 4.7 silently falls back to the DUMMY renderer
    and produce blank PNGs.  We surface that as a loud
    ``RuntimeError`` rather than silently returning a list of 2 KB files
    — see ``capture_scene`` docstring for the install command.
    """
    project_godot = Path(build_dir) / "project.godot"
    restore_features = _capture_strip_vulkan_features(project_godot)
    try:
        _run_godot_import(build_dir, godot_bin)
        env = _capture_env()
        result = subprocess.run(
            [
                godot_bin,
                "--headless",
                "--path", build_dir,
                "--rendering-driver", "opengl3",
            ],
            capture_output=True,
            text=True,
            timeout=_CAPTURE_TIMEOUT_S,
            env=env,
        )
        stderr = result.stderr or ""
        if result.returncode != 0:
            _dump_godot_stderr(build_dir, stderr)  # diagnostic aid on failure only
            stderr_tail = stderr.strip()[-500:]
            # Detect dummy renderer — clear actionable error
            if "texture_2d_get" in stderr or "rendering/dummy" in stderr:
                raise RuntimeError(
                    "Godot capture failed: dummy renderer active — "
                    "SubViewport texture comes from the DUMMY storage path "
                    "and `get_image()` returned null.\n"
                    "FIRST: install Mesa's software Vulkan (lavapipe) "
                    "— Arch: `sudo pacman -S vulkan-swrast`; "
                    "Debian/Ubuntu: `sudo apt install mesa-vulkan-drivers`; "
                    "Fedora: `sudo dnf install mesa-vulkan-drivers`.\n"
                    "Full stderr was written to " + _stderr_log_path(build_dir) + "\n"
                    "Run `grep -E \"texture_2d_get|SDFGI\" "
                    + _stderr_log_path(build_dir) + "` for the Godot complaint."
                )
            raise RuntimeError(
                f"Godot capture failed (rc={result.returncode})\n{stderr_tail}"
            )
        # Even when exit code is 0, a Parse Error or load failure in stderr
        # means the scene loaded nothing and all captures are blank 2 KB PNGs.
        # Surface those as an error so the caller doesn't silently get blanks.
        _PARSE_ERROR_PATTERN = re.compile(r"Parse Error")
        _FAILED_LOAD_PATTERN = re.compile(r"Failed to load resource")
        if _PARSE_ERROR_PATTERN.search(stderr) or _FAILED_LOAD_PATTERN.search(stderr):
            _dump_godot_stderr(build_dir, stderr)
            stderr_tail = stderr.strip()[-500:]
            raise RuntimeError(
                f"Godot capture produced errors — scene may be blank\n{stderr_tail}"
            )
    finally:
        restore_features()


def _stderr_log_path(build_dir: str) -> str:
    return str(Path(build_dir) / ".godot_capture.stderr.log")


def _dump_godot_stderr(build_dir: str, stderr: str) -> None:
    """Append Godot's stderr to a build-local log for post-mortem analysis.

    The existing dummy-renderer RuntimeError mentions this path so users can
    attach it when reporting capture failures (especially useful for the
    roadmap-0.11 EGL/Wayland/Mesa interaction drift regressions).
    """
    try:
        Path(_stderr_log_path(build_dir)).write_text(stderr or "")
    except OSError:
        # Best-effort — never itself raise out of the capture path.
        pass


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
