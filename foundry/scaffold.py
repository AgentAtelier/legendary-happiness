"""scaffold — disposable Godot project scaffolding.

Takes a compiled scene + manifest and stamps a fresh, version-pinned
Godot project into ``builds/<name>/``.  The project is an output, not a
hand-maintained artifact — every run produces a clean copy from the
template and discards it after use.

Public API:
    scaffold_project(name, quest_spec, manifest, *, ...) -> Path
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple

import room_shell
from publish import copy_asset_family
from scene_compiler import compile_scene, resolve_unique_glbs_with_npc


def _find_godot() -> str:
    """Locate the Godot 4.x binary.  Returns the path or raises FileNotFoundError."""
    env_bin = os.environ.get("GODOT_BIN")
    if env_bin and Path(env_bin).exists():
        return env_bin

    which_bin = shutil.which("godot")
    if which_bin:
        return which_bin

    candidates = [
        "/usr/bin/godot",
        "/usr/local/bin/godot",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    raise FileNotFoundError(
        "Godot binary not found.  Install Godot 4.x or set GODOT_BIN."
    )


def _set_main_scene(project_godot: Path, scene_path: str) -> None:
    """Set run/main_scene in a Godot project.godot file.

    Uses a simple text replacement to avoid configparser spacing issues
    (Godot expects ``key="value"`` without spaces around ``=``).
    """
    text = project_godot.read_text()
    line = f'run/main_scene="{scene_path}"'
    if "run/main_scene" in text:
        # Replace existing line
        text = re.sub(
            r'^run/main_scene\s*=.*$',
            line,
            text,
            flags=re.MULTILINE,
        )
    else:
        # Append line right after the [application] header
        text = re.sub(
            r'^\[application\]$',
            f'[application]\n{line}',
            text,
            flags=re.MULTILINE,
        )
    project_godot.write_text(text)


def _pre_import(build_path: Path, godot_bin: str, *, label: str = "first") -> None:
    """Run Godot headless import to build the .godot cache.

    Called twice in ``scaffold_project``: once before
    ``_copy_room_shell`` has run (``label="first"``) and once after
    (``label="after-shell"``).  The second pass is the import-ordering
    fix for the showcase2 batch: ``shell.glb`` (and its image-side
    textures) only land in ``builds/<name>/assets/`` AFTER the first
    pass, so without a second pass those files never reach
    ``.godot/imported/*.ctex`` — materials render magenta and the
    load log contains "Compressed texture file is corrupt".  The
    second pass is idempotent (Godot skips already-imported files).
    ``label`` appears in warnings to disambiguate which pass failed.

    """
    cmd = [
        godot_bin, "--headless",
        "--path", str(build_path),
        "--import", "--quit",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        # Non-zero import can happen on first open — the import cache
        # may still be usable.  Warn but don't fail.
        stderr_tail = result.stderr.strip()[-500:] if result.stderr else ""
        print(f"[scaffold] WARNING: godot --import ({label}) exited {result.returncode}")
        if stderr_tail:
            print(f"[scaffold]   {label} stderr: {stderr_tail}")





def _copy_room_shell(glb_path: str | None, dest_assets_dir: str) -> None:
    """Copy the per-room shell GLB into the build's assets as shell.glb.

    No-op when glb_path is None (compiler falls back to the inline box shell).
    """
    if not glb_path:
        return
    dest = Path(dest_assets_dir)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(glb_path, str(dest / "shell.glb"))


def scaffold_project(
    name: str,
    quest_specs: list[dict],
    manifest: List[dict],
    *,
    template_dir: str,
    library_dir: str,
    out_root: str = "builds",
    godot_bin: str | None = None,
    room_size: dict | None = None,
    theme: str | None = None,
    camera_mode: str = "first",
) -> Path:
    """Scaffold a fresh, disposable Godot project.

    Steps:
        1. Copy the template into ``<out_root>/<name>/``.
        2. Compile the quest scene → ``scenes/main.tscn``.
        3. Set ``main_scene`` in the build's ``project.godot``.
        4. Copy referenced assets (GLB + full family) from *library_dir*.
        5. Pre-import headlessly so the project opens clean.

    Args:
        name: Build directory name (e.g. ``"slice1_fetch"``).
        quest_specs: List of validated quest specs from
                     ``QuestBehaviourPlanner.plan_multi()`` (C-4).
                     For backward compat, a single dict is also accepted.
        manifest: Placed-entity manifest.
        template_dir: Path to ``foundry/godot_template/``.
        library_dir: Directory containing forged GLBs + their families.
        out_root: Where to place ``builds/`` (repo root by default).
        godot_bin: Path to Godot binary.  Auto-detected if None.

    Returns:
        The absolute Path to the scaffolded project.
    """
    template = Path(template_dir)
    build_path = Path(out_root).resolve() / name

    # ── 1. Copy template ────────────────────────────────────────
    if build_path.exists():
        shutil.rmtree(build_path)
    shutil.copytree(template, build_path)
    print(f"[scaffold] Template copied → {build_path}")

    # ── 2. Compile scene ────────────────────────────────────────
    scenes_dir = build_path / "scenes"
    scenes_dir.mkdir(exist_ok=True)
    scene_path = str(scenes_dir / "main.tscn")
    # C-4: Handle both single dict (backward compat) and list
    specs = quest_specs if isinstance(quest_specs, list) else [quest_specs]
    compile_scene(specs, manifest, scene_path, assets_subdir="assets",
                  room_size=room_size, theme=theme, camera_mode=camera_mode)
    print(f"[scaffold] Scene compiled → {scene_path}")

    # ── 3. Set main_scene ───────────────────────────────────────
    pg = build_path / "project.godot"
    _set_main_scene(pg, "res://scenes/main.tscn")
    print("[scaffold] main_scene set → res://scenes/main.tscn")

    # ── 4. Copy asset families ──────────────────────────────────
    unique_glbs = resolve_unique_glbs_with_npc(manifest)
    assets_dir = build_path / "assets"
    total_copied = 0
    for category, material in unique_glbs:
        copied = copy_asset_family(
            category, material,
            str(Path(library_dir)),
            str(assets_dir),
        )
        if copied:
            print(f"[scaffold] Copied {category}_{material}: {len(copied)} files")
        else:
            print(f"[scaffold] WARNING: no files for {category}_{material} in {library_dir}")
        total_copied += len(copied)
    print(f"[scaffold] Total asset files copied: {total_copied}")

    # ── 4b. Task 7: Copy per-room shell GLB if available ─────────
    # The shell textures (shell_{stone,timber}_*.png) ride in with the
    # template copy automatically.
    # Resolve the cached shell GLB via room_shell (same args
    # compile_scene uses internally).  Cache hit is cheap; Blender
    # runs only on first use for a given (w,d,theme) tuple.
    _room_w = 20.0
    _room_d = 20.0
    _room_h = 3.0
    if room_size:
        _room_w = float(room_size.get("w", _room_w))
        _room_d = float(room_size.get("d", _room_d))
    shell_path = room_shell.ensure_room_shell(_room_w, _room_d, _room_h, theme)
    _copy_room_shell(str(shell_path) if shell_path else None, str(assets_dir))

    # ── 5. Pre-import pass 1 ─────────────────────────────────────
    # Imports the template's bundled assets + the GLB families copied
    # in step 4.  At this point room_shell.glb may not yet be in
    # builds/<name>/assets/.
    gb = godot_bin or _find_godot()
    _pre_import(build_path, gb, label="first")

    # ── 5b. Pre-import pass 2 (after _copy_room_shell) ────────────
    # Import-ordering fix: anything copied in step 4b lands in
    # builds/<name>/assets/ AFTER pass 1, so without this second pass
    # those files never reach .godot/imported/*.ctex — materials render
    # magenta and the load log contains "Compressed texture file is
    # corrupt".  Idempotent: Godot skips already-imported files.
    _pre_import(build_path, gb, label="after-shell")
    print(f"[scaffold] Pre-imports done → {build_path}")

    return build_path
