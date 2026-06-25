"""Multi-space composition — sub-project (a), unit 3 end-to-end.

Turns a whole ``World`` into a walkable Godot scene by reusing the proven
per-space ``scene_compiler`` path and instancing each space at its footprint
origin (see the design spec
``docs/superpowers/specs/2026-06-25-world-unit3-multispace-assembly.md``).

This module starts with the de-risking kernel: **portal → wall-opening
geometry** — for each portal touching a space, which FACE of that space's
shell it opens, and the opening rect. The shell generator consumes this to
leave a walkable gap (v1), so adjacent spaces actually connect. Pure geometry,
fully unit-testable; the Blender shell-cut + Godot load are verified with the
stack.

Face convention matches ``world.query`` (Godot-aligned): the face whose outward
normal points +X is "east", -X "west", -Z "north", +Z "south", +Y "up"
(ceiling), -Y "down" (floor).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

# Build-stack modules imported as modules (not names) so the stack-free test
# can monkeypatch them on this module's namespace. The pure kernels below
# (space_openings, build_world_tscn) do not touch them.
import asset_ensure
import publish
import room_shell
import scaffold
import scene_compiler
import tscn_writer as tw
from world.assembly import footprint_centre, space_to_compile_inputs
from world.model import World
from world.query import neighbors
from world.validation import EPS, aabb

logger = logging.getLogger(__name__)

_IDENTITY = (1, 0, 0, 0, 1, 0, 0, 0, 1)

# axis index -> (face at the MAX side, face at the MIN side)
_AXIS_FACES = {0: ("east", "west"), 1: ("up", "down"), 2: ("south", "north")}


def _shared_face(s, n, eps: float = EPS) -> str | None:
    """The face of AABB ``s`` that touches AABB ``n``. ``None`` if they don't
    share exactly one face (not face-adjacent)."""
    (slo, shi), (nlo, nhi) = s, n
    hits = []
    for axis in range(3):
        max_face, min_face = _AXIS_FACES[axis]
        if abs(shi[axis] - nlo[axis]) <= eps:   # s's MAX face meets n
            hits.append(max_face)
        elif abs(slo[axis] - nhi[axis]) <= eps:  # s's MIN face meets n
            hits.append(min_face)
    return hits[0] if len(hits) == 1 else None


def space_openings(world: World, space_id: str) -> list[dict]:
    """For every portal touching ``space_id``, the opening to cut in that
    space's shell: ``{portal, to, face, center, size}`` (deterministic order,
    by portal id). ``center`` is the portal's world position; ``size`` its
    ``(w, h)``. Spaces with malformed footprints / non-adjacent neighbours are
    skipped (the validation gate already rejects those on add_portal)."""
    node = world.nodes.get(space_id)
    if node is None:
        return []
    s = aabb(node.footprint)
    if s is None:
        return []
    out = []
    for pid, other in neighbors(world, space_id):
        on = world.nodes.get(other)
        nb = aabb(on.footprint) if on is not None else None
        if nb is None:
            continue
        face = _shared_face(s, nb)
        if face is None:
            continue
        portal = world.portals[pid]
        out.append({
            "portal": pid,
            "to": other,
            "face": face,
            "center": list(portal.position),
            "size": list(portal.size),
        })
    return out


def build_world_tscn(
    world: World, scene_paths: dict[str, str], *, spawn_space: str | None = None
) -> str:
    """The parent ``world.tscn``: instance each space's PackedScene at its
    footprint CENTRE (the per-space scene is centred on its own origin, so
    translating by the centre lands it correctly in world space) + a
    ``PlayerSpawn`` marker at the spawn space's centre.

    ``scene_paths`` maps ``space_id -> "res://…"`` for the per-space scenes
    (produced by the stack-gated compile step). This kernel is PURE and
    deterministic — given the same world + paths it returns byte-identical
    text — so it is fully testable without Godot. Spaces sorted by id.
    """
    spaces = [sid for sid in sorted(world.nodes) if sid in scene_paths]
    if not spaces:
        raise ValueError("build_world_tscn: no spaces with scene paths")
    spawn = spawn_space if spawn_space in spaces else spaces[0]

    lines = [f"[gd_scene load_steps={len(spaces) + 1} format=3]", ""]
    ext_ids = {sid: f"{i}_{sid}" for i, sid in enumerate(spaces, start=1)}
    for sid in spaces:
        lines.append(tw.ext_resource("PackedScene", scene_paths[sid], ext_ids[sid]))
    lines += ["", '[node name="World" type="Node3D"]', ""]
    for sid in spaces:
        lines.append(tw.node_header(sid, parent=".", instance=ext_ids[sid]))
        lines.append(f"transform = {tw.transform3d(_IDENTITY, footprint_centre(world.nodes[sid].footprint))}")
        lines.append("")
    lines.append(tw.node_header("PlayerSpawn", type="Marker3D", parent="."))
    lines.append(f"transform = {tw.transform3d(_IDENTITY, footprint_centre(world.nodes[spawn].footprint))}")
    lines.append("")
    return "\n".join(lines)


# ── full multi-space build orchestration ──────────────────────────────

def compose_world(
    world: World,
    out_dir,
    *,
    library_dir: str,
    lexicon: str,
    template_dir: str,
    spawn_space: str | None = None,
    godot_bin: str | None = None,
) -> Path:
    """Build a whole ``World`` into one runnable Godot project at ``out_dir``.

    Reuses the proven single-space path (``space_to_compile_inputs`` →
    ``ensure_assets`` → ``compile_scene``) once PER space, instancing every
    space into a parent ``world.tscn`` (the ``build_world_tscn`` kernel).

    Steps:
        1. Copy the template into ``out_dir``.
        2. For each space (sorted by id):
             a. ``space_to_compile_inputs`` → manifest / room_size / theme.
             b. ``ensure_assets`` so the space's GLBs exist in *library_dir*.
             c. Build (or fetch the cached) per-space shell; copy it into the
                build as ``shell_<sid>.glb`` (compile_scene references it by
                basename, so each space gets its own shell).
             d. ``compile_scene`` → ``scenes/<sid>.tscn``.
             e. Copy the space's referenced asset families into ``assets/``.
        3. Write ``scenes/world.tscn`` (``build_world_tscn``) and point
           ``main_scene`` at it.
        4. Pre-import once, after everything is on disk.

    Walkable portal openings are a follow-up (``space_openings`` already
    computes the geometry); v1 places fully-walled rooms at their offsets.

    Returns the absolute build path.
    """
    template = Path(template_dir)
    build_path = Path(out_dir).resolve()

    # 1. Template (fresh copy each run — the project is an output, not edited).
    if build_path.exists():
        shutil.rmtree(build_path)
    shutil.copytree(template, build_path)
    scenes_dir = build_path / "scenes"
    scenes_dir.mkdir(exist_ok=True)
    assets_dir = build_path / "assets"
    assets_dir.mkdir(exist_ok=True)
    logger.info("Template copied → %s", build_path)

    scene_paths: dict[str, str] = {}
    for sid in sorted(world.nodes):
        node = world.nodes[sid]
        ins = space_to_compile_inputs(node)
        manifest, room_size, theme = ins["manifest"], ins["room_size"], ins["theme"]
        specs = ins["quest_specs"]

        # 2b. Forge the space's props.
        asset_ensure.ensure_assets(manifest, library_dir, lexicon)

        # 2c. Per-space shell, copied under a space-unique basename so the
        # scenes don't collide on a shared "shell.glb".
        shell_ref = None
        shell_dec = None
        try:
            shell_src, shell_dec = room_shell.ensure_room_shell(
                float(room_size["w"]), float(room_size["d"]), float(room_size["h"]),
                theme, seed=node.seed,
            )
        except TypeError:
            shell_src, shell_dec = room_shell.ensure_room_shell(
                float(room_size["w"]), float(room_size["d"]), float(room_size["h"]), theme,
            )
        if shell_src:
            dest = assets_dir / f"shell_{sid}.glb"
            shutil.copy(str(shell_src), str(dest))
            shell_ref = str(dest)   # basename → res://assets/shell_<sid>.glb

        # 2d. Compile the space into its own scene.
        scene_file = scenes_dir / f"{sid}.tscn"
        scene_compiler.compile_scene(
            specs, manifest, str(scene_file), assets_subdir="assets",
            room_size=room_size, theme=theme,
            shell_glb_path=shell_ref, shell_decisions=shell_dec,
        )
        scene_paths[sid] = f"res://scenes/{sid}.tscn"
        logger.info("Space compiled → %s", scene_file)

        # 2e. Copy the space's referenced asset families (shared assets/).
        for category, material in scene_compiler.resolve_unique_glbs_with_npc(manifest):
            publish.copy_asset_family(category, material, str(library_dir), str(assets_dir))

    # 3. Parent world scene + main_scene.
    world_tscn = build_world_tscn(world, scene_paths, spawn_space=spawn_space)
    (scenes_dir / "world.tscn").write_text(world_tscn)
    scaffold._set_main_scene(build_path / "project.godot", "res://scenes/world.tscn")
    logger.info("world.tscn written; main_scene set")

    # 4. Single pre-import pass.
    gb = godot_bin or scaffold._find_godot()
    scaffold._pre_import(build_path, gb)
    logger.info("Multi-space build complete → %s", build_path)

    return build_path
