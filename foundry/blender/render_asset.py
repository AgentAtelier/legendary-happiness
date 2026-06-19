"""Run INSIDE Blender:
    blender --background --python render_asset.py -- <glb> <out_png>

Renders a framed thumbnail of the asset with Cycles on CPU — reliable headless
with no GPU/display. Low samples/resolution: this is for eyeball verification,
not beauty."""

import math
import sys

import bpy
from mathutils import Vector


def _argv():
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else []


def main():
    glb, out_png = _argv()[0], _argv()[1]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)  # glTF import returns to Z-up in Blender

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    scene.render.resolution_x = 640
    scene.render.resolution_y = 480
    scene.render.filepath = out_png

    target = bpy.data.objects.new("target", None)
    scene.collection.objects.link(target)
    target.location = (0.0, 0.0, 0.4)

    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.location = Vector((2.4, -2.4, 1.7))
    con = cam.constraints.new("TRACK_TO")
    con.target = target
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"

    sun_data = bpy.data.lights.new("sun", "SUN")
    sun_data.energy = 3.0
    sun = bpy.data.objects.new("sun", sun_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(50), 0.0, math.radians(40))

    bpy.ops.render.render(write_still=True)


main()
