"""
Apply the Middle Eastern library to a whole Buildify building and render it.

Run: blender -b buildify_1.0.blend --python render_me_building.py
"""

import importlib.util
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = r"C:\Users\User\Desktop\BuildingGen"


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, fname))
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


mk = load("mk", "make_me_library.py")
blm = load("blm", "buildify_modular.py")
blm.register()

scene = bpy.context.scene
P = scene.blm_props

mk.build_library(scene)

P.building = bpy.data.objects["building_base"]
mod = [m for m in P.building.modifiers if m.type == "NODES"][0]
ident = {i.name: i.identifier for i in mod.node_group.interface.items_tree
         if getattr(i, "item_type", "") == "SOCKET" and i.in_out == "INPUT"}
for k, v in (("Min number of floors", 4), ("Max number of floors", 4)):
    mod[ident[k]] = v
P.building.update_tag()
bpy.context.view_layer.update()

bpy.ops.blm.modularize()
mods = [o for o in P.modules_collection.objects if blm.is_module(o)]
print("modules: %d" % len(mods))

# re-skin: ground floor gets doors and solid wall, upper floors get windows and
# mashrabiya, the trim band becomes a merlon parapet
swapped = 0
for i, ob in enumerate(mods):
    slot = ob.get(blm.P_SLOT, "")
    z = ob.matrix_world.translation.z
    if "trim" in slot:
        target = "me_5_parapet"
    elif "wall" not in slot:
        continue
    elif z < 1.5:
        target = "me_4_door_arch" if i % 7 == 0 else "me_1_solid"
    else:
        target = ("me_3_mashrabiya" if i % 5 == 0 else
                  "me_2_window_arch" if i % 5 in (1, 2, 3) else "me_1_solid")
    if blm.apply_asset(ob, target):
        swapped += 1
print("re-skinned %d modules" % swapped)

# frame the building
pts = [ob.matrix_world.translation for ob in mods]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
ctr = (lo + hi) / 2
size = max((hi - lo).x, (hi - lo).y, (hi - lo).z) or 20.0
print("building centre %s  size %.1f" % (tuple(round(c, 1) for c in ctr), size))

for ob in scene.objects:
    if ob.type == "MESH" and not blm.is_module(ob):
        ob.hide_render = True

light_data = bpy.data.lights.new("_sun", type="SUN")
light_data.energy = 3.5
light_data.angle = math.radians(3)
light = bpy.data.objects.new("_sun", light_data)
light.rotation_euler = (math.radians(52), 0, math.radians(40))
scene.collection.objects.link(light)

world = scene.world or bpy.data.worlds.new("W")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.62, 0.75, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.1

cam_data = bpy.data.cameras.new("_cam")
cam_data.lens = 45
cam = bpy.data.objects.new("_cam", cam_data)
d = size * 1.15
cam.location = ctr + Vector((-d * 0.75, -d * 0.95, size * 0.55))
scene.collection.objects.link(cam)
scene.camera = cam

track = cam.constraints.new("TRACK_TO")
empty = bpy.data.objects.new("_target", None)
empty.location = ctr + Vector((0, 0, size * 0.12))
scene.collection.objects.link(empty)
track.target = empty
track.track_axis = "TRACK_NEGATIVE_Z"
track.up_axis = "UP_Y"

scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 40
scene.render.resolution_x = 1400
scene.render.resolution_y = 950
out = os.path.join(HERE, "me_building.png")
scene.render.filepath = out
bpy.ops.render.render(write_still=True)
print("rendered", out)
