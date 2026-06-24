"""scaffold — disposable Godot project scaffolding.

Takes a compiled scene + manifest and stamps a fresh, version-pinned
Godot project into ``builds/<name>/``.  The project is an output, not a
hand-maintained artifact — every run produces a clean copy from the
template and discards it after use.

Public API:
    scaffold_project(name, quest_spec, manifest, *, ...) -> Path
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

import room_shell
from publish import copy_asset_family
from scene_compiler import compile_scene, resolve_unique_glbs_with_npc

logger = logging.getLogger(__name__)


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


def _pre_import(build_path: Path, godot_bin: str) -> None:
    """Run Godot headless import to build the .godot cache.

    Called exactly once in ``scaffold_project`` AFTER all assets
    (template, asset families, shell GLB, class textures) are in
    place — a single pass is sufficient when everything lands before
    the import.
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
        logger.warning("godot --import exited %d", result.returncode)
        if stderr_tail:
            logger.warning("  stderr: %s", stderr_tail)





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
    manifest: list[dict],
    *,
    template_dir: str,
    library_dir: str,
    out_root: str = "builds",
    godot_bin: str | None = None,
    room_size: dict | None = None,
    theme: str | None = None,
    camera_mode: str = "first",
    lighting_plan: dict | None = None,  # Task 6: generative lighting plan
    palette: dict | None = None,        # Scene palette for per-class material override
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
    logger.info("Template copied → %s", build_path)

    # ── 4b. Task 7: Copy per-room shell GLB if available ─────────
    # P12 (AUDIT-05 de-dup): resolve the cached shell GLB BEFORE
    # compile_scene() so the kwarg bindings (shell_glb_path,
    # shell_decisions) are bound when compile_scene() reads them.
    # compile_scene no longer calls room_shell.ensure_room_shell
    # itself — scaffold_project owns the cache write site (single
    # call, deterministic ordering).
    # Task 6: pass windows= from the lighting plan (Task 2 adds the kwarg).
    _room_w = 20.0
    _room_d = 20.0
    _room_h = 3.0
    if room_size:
        _room_w = float(room_size.get("w", _room_w))
        _room_d = float(room_size.get("d", _room_d))
    _windows = lighting_plan.get("windows", []) if lighting_plan else []
    try:
        shell_path, _shell_d = room_shell.ensure_room_shell(_room_w, _room_d, _room_h, theme,
                                                   windows=_windows)
    except TypeError:
        # windows= kwarg not accepted yet (Task 2 adds it)
        shell_path, _shell_d = room_shell.ensure_room_shell(_room_w, _room_d, _room_h, theme)
    # ── 2. Compile scene ────────────────────────────────────────
    scenes_dir = build_path / "scenes"
    scenes_dir.mkdir(exist_ok=True)
    scene_path = str(scenes_dir / "main.tscn")
    # C-4: Handle both single dict (backward compat) and list
    specs = quest_specs if isinstance(quest_specs, list) else [quest_specs]
    # P12 (AUDIT-05 de-dup): scene_compiler.compile_scene no longer
    # calls room_shell.ensure_room_shell internally — we resolved
    # the cached GLB above (the only call site) and thread both
    # the path + decision points in.  Default behaviour unchanged:
    # None keeps the inline box-shell fallback for callers that
    # never hit the cache.
    compile_scene(specs, manifest, scene_path, assets_subdir="assets",
                  room_size=room_size, theme=theme, camera_mode=camera_mode,
                  lighting_plan=lighting_plan,
                  palette=palette,
                  shell_glb_path=(str(shell_path) if shell_path else None),
                  shell_decisions=_shell_d)
    logger.info("Scene compiled → %s", scene_path)

    # ── 2b. Generate palette class textures (0.6b fix) ────────────
    # The scene compiler emits ext_resource Texture2D refs to
    # class_{cls}_albedo.png / class_{cls}_normal.png.  Without
    # those files on disk Godot's scene loader fatally Parse
    # Errors and the SubViewport capture produces blank PNGs.
    if palette is not None:
        from material_classes import class_for
        from palette import generate_class_textures
        class_set: set = set()
        for entry in manifest:
            cls = class_for(entry.get("material", "default"))
            class_set.add(cls)
        # Shell classes are always stone + wood (when GLB shell exists)
        class_set.add("stone")
        class_set.add("wood")
        assets_dir = build_path / "assets"
        n = generate_class_textures(palette, class_set, str(assets_dir))
        if n:
            logger.info("Palette class textures written: %d PNG(s)", n)

    # ── 3. Set main_scene ───────────────────────────────────────
    pg = build_path / "project.godot"
    _set_main_scene(pg, "res://scenes/main.tscn")
    logger.info("main_scene set → res://scenes/main.tscn")

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
            logger.info("Copied %s_%s: %d files", category, material, len(copied))
        else:
            logger.warning("no files for %s_%s in %s", category, material, library_dir)
        total_copied += len(copied)
    logger.info("Total asset files copied: %d", total_copied)

    _copy_room_shell(str(shell_path) if shell_path else None, str(assets_dir))

    # ── Task 6: Bake-and-apply lighting (tier ≥ 1) ────────────────
    if lighting_plan:
        import lighting_bake
        _blender_available = shutil.which("blender") is not None
        _tier = 2 if _blender_available else 0
        placements = [{"glb": f"{e.get('category','?')}_{e.get('material','?')}.glb",
                       "transform": [1, 0, 0, 0, 1, 0, 0, 0, 1,
                                     e.get("x", 0), e.get("y", 0), e.get("z", 0)],
                       "static": not e.get("decor", False)}
                      for e in manifest]
        scene_desc = lighting_bake.build_scene_desc(
            lighting_plan, placements, tier=_tier, samples=64,
        )
        result = lighting_bake.bake_and_apply(scene_desc, str(build_path))
        logger.info("Lighting bake: tier=%s status=%s", result['tier'], result['status'])

    # ── 6. Pre-import (single pass) ──────────────────────────────
    # All assets (template, families, shell GLB, class textures,
    # baked lighting results) are now in place — one import pass
    # is sufficient to build the complete .godot/imported cache.
    gb = godot_bin or _find_godot()
    _pre_import(build_path, gb)
    logger.info("Pre-import done → %s", build_path)

    return build_path
