"""Run INSIDE Blender:
    blender --background --python build_room_shell.py -- <out_glb> <w> <d> <wall_h> <theme> <seed>

Generates the interior room shell as one GLB: timber floor, 4 stone walls, and a
king-post truss roof (timber rafters/tie-beams/king-posts + ridge, stone roof
boards). Two material slots named 'stone' and 'timber' — scene_compiler applies
the real world-space triplanar StandardMaterial3D per slot. Geometry only.

Blender is Z-up; export converts to glTF Y-up. Origin at room centre, floor top
at z=0. All shape knobs default sensibly (see _DEFAULTS) and may be overridden.
"""

import math
import sys

import bmesh
import bpy
from mathutils import Matrix

_DEFAULTS = dict(pitch_ratio=0.4, beam=0.15, wall_t=0.2, floor_t=0.1,
                 trusses_per_m=0.6, board_t=0.05, bevel=0.0)


def _args():
    import json
    a = sys.argv
    a = a[a.index("--") + 1:]
    windows = json.loads(a[6]) if len(a) > 6 and a[6] else []
    return a[0], float(a[1]), float(a[2]), float(a[3]), a[4], float(a[5]), windows


def _mat(name, rgb):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = False
    m.diffuse_color = (*rgb, 1.0)
    return m


def _beam(bm, center, size, ry=0.0):
    """Add a box of `size`=(sx,sy,sz) rotated `ry` about Y, centred at `center`."""
    M = (Matrix.Translation(center)
         @ Matrix.Rotation(ry, 4, "Y")
         @ Matrix.Diagonal((size[0], size[1], size[2], 1.0)))
    bmesh.ops.create_cube(bm, size=1.0, matrix=M)


def _emit_wall(bm, wall, w, d, wall_h, wall_t, win):
    """Emit one stone wall; if `win` (a Window dict) is given, frame a rectangular
    opening (below band + above band + two side jambs) instead of a solid box.
    N/S run along X (at y=∓d/2); E/W run along Z-height at x=±w/2 (along Y)."""
    along_x = wall in ("N", "S")
    y0 = (-d / 2 if wall == "N" else d / 2) if along_x else 0.0
    x0 = 0.0 if along_x else (w / 2 if wall == "E" else -w / 2)
    length = w if along_x else d

    if not win:
        size = (w, wall_t, wall_h) if along_x else (wall_t, d, wall_h)
        _beam(bm, (x0, y0, wall_h / 2), size)
        return

    win_w = float(win["width"]); sill = float(win["sill"])
    head = sill + float(win["height"])
    c = (float(win.get("center", 0.5)) - 0.5) * length   # opening centre along wall axis
    half = win_w / 2.0
    lo, hi = -length / 2, length / 2

    # below + above full-width bands
    if along_x:
        _beam(bm, (x0, y0, sill / 2), (w, wall_t, sill))
        _beam(bm, (x0, y0, (head + wall_h) / 2), (w, wall_t, wall_h - head))
    else:
        _beam(bm, (x0, y0, sill / 2), (wall_t, d, sill))
        _beam(bm, (x0, y0, (head + wall_h) / 2), (wall_t, d, wall_h - head))

    # side jambs spanning sill..head
    band_h = head - sill
    for seg_lo, seg_hi in ((lo, c - half), (c + half, hi)):
        seg_len = seg_hi - seg_lo
        if seg_len <= 1e-3:
            continue
        mid = (seg_lo + seg_hi) / 2
        if along_x:
            _beam(bm, (x0 + mid, y0, (sill + head) / 2), (seg_len, wall_t, band_h))
        else:
            _beam(bm, (x0, y0 + mid, (sill + head) / 2), (wall_t, seg_len, band_h))


def build_shell(w, d, wall_h, seed=0.0, windows=(), **kw):
    p = {**_DEFAULTS, **kw}
    beam, wall_t, floor_t, board_t = p["beam"], p["wall_t"], p["floor_t"], p["board_t"]
    apex = wall_h + w * p["pitch_ratio"]
    n_truss = max(2, int(round(d * p["trusses_per_m"])))
    rlen = math.hypot(w / 2.0, apex - wall_h)
    rang = math.atan2(apex - wall_h, w / 2.0)

    stone = bmesh.new()
    timber = bmesh.new()

    # floor (timber): top at z=0
    _beam(timber, (0, 0, -floor_t / 2), (w, d, floor_t))

    # 4 walls (stone) to plate height — framed openings where windows are planned
    win_by_wall = {}
    for win in (windows or []):
        win_by_wall.setdefault(win.get("wall"), win)   # first window per wall
    for wall in ("N", "S", "E", "W"):
        _emit_wall(stone, wall, w, d, wall_h, wall_t, win_by_wall.get(wall))

    # trusses (timber) along Y
    span = d - 2 * wall_t
    ys = [(-d / 2 + wall_t) + i * (span / (n_truss - 1)) for i in range(n_truss)]
    zc = (wall_h + apex) / 2.0
    for y in ys:
        _beam(timber, (0, y, wall_h), (w, beam, beam))            # tie-beam
        _beam(timber, (0, y, zc), (beam, beam, apex - wall_h))    # king-post
        _beam(timber, (-w / 4, y, zc), (rlen, beam, beam), ry=-rang)  # left rafter
        _beam(timber, ( w / 4, y, zc), (rlen, beam, beam), ry=+rang)  # right rafter

    # ridge beam (timber) along Y
    _beam(timber, (0, 0, apex), (beam, d, beam))

    # roof boards (stone) — two slopes, slightly above the rafters
    off = beam * 0.6
    _beam(stone, (-w / 4, 0, zc + off), (rlen, d, board_t), ry=-rang)
    _beam(stone, ( w / 4, 0, zc + off), (rlen, d, board_t), ry=+rang)

    return stone, timber


def main():
    out, w, d, wall_h, theme, seed, windows = _args()
    bpy.ops.wm.read_factory_settings(use_empty=True)

    stone_bm, timber_bm = build_shell(w, d, wall_h, seed=seed, windows=windows)

    for bm, name, rgb in [(stone_bm, "stone", (0.6, 0.58, 0.54)),
                          (timber_bm, "timber", (0.4, 0.26, 0.13))]:
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new(name, me)
        bpy.context.collection.objects.link(ob)
        me.materials.append(_mat(name, rgb))

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB",
                              use_selection=True, export_yup=True)
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()

