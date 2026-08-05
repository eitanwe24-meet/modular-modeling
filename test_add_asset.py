"""
Adding your own mesh to a library, live.

Run: blender -b buildify_1.0.blend --python test_add_asset.py
"""

import importlib.util
import os
import sys

import bpy
from mathutils import Vector

HERE = r"C:\Users\User\Desktop\BuildingGen"
spec = importlib.util.spec_from_file_location(
    "blm", os.path.join(HERE, "buildify_modular.py"))
blm = importlib.util.module_from_spec(spec)
sys.modules["blm"] = blm
spec.loader.exec_module(blm)
blm.register()

scene = bpy.context.scene
P = scene.blm_props
fails = []


def rule(t):
    print("\n" + "=" * 72 + "\n" + t + "\n" + "=" * 72)


def check(c, m):
    print(("PASS  " if c else "FAIL  ") + m)
    if not c:
        fails.append(m)


def bounds(ob):
    vs = [ob.matrix_world @ v.co for v in ob.data.vertices]
    return (min(v.x for v in vs), max(v.x for v in vs),
            min(v.y for v in vs), max(v.y for v in vs),
            min(v.z for v in vs), max(v.z for v in vs))


def make_test_mesh(name, size, loc, with_modifier=False):
    """A deliberately wrong-sized, wrong-origin, wrong-place cube."""
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = size
    if with_modifier:
        m = ob.modifiers.new("Sub", "SUBSURF")
        m.levels = 1
    return ob


def select_only(ob):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob


rule("1. ADD A BADLY-SIZED MESH (auto-fit width)")
src = make_test_mesh("MyWall", size=(7.0, 1.5, 4.0), loc=(12, 34, 56))
print("  source bounds: X%.2f Y%.2f Z%.2f  at %s"
      % (bounds(src)[1] - bounds(src)[0], bounds(src)[3] - bounds(src)[2],
         bounds(src)[5] - bounds(src)[4], tuple(src.location)))
select_only(src)

r = bpy.ops.blm.add_asset(target="lib_custom", fit="WIDTH")
print("  add_asset ->", r)
check("FINISHED" in r, "add_asset succeeded")

col = bpy.data.collections.get("lib_custom")
check(col is not None and len(col.objects) == 1, "asset landed in lib_custom")
new = col.objects[0]
x0, x1, y0, y1, z0, z1 = bounds(new)
print("  result: X[%.3f,%.3f] Y[%.3f,%.3f] Z[%.3f,%.3f]" % (x0, x1, y0, y1, z0, z1))
check(abs((x1 - x0) - 3.0) < 1e-3, "auto-fitted to exactly 3.00 m wide")
check(abs(x0 + 1.5) < 1e-3 and abs(x1 - 1.5) < 1e-3, "centred on X")
check(abs(z0) < 1e-3, "origin sits at the base (Z=0)")
check(abs(y0) < 1e-3, "front face on the Y=0 facade plane")
ar_src = 4.0 / 7.0
ar_new = (z1 - z0) / (x1 - x0)
check(abs(ar_src - ar_new) < 1e-3, "aspect ratio preserved in WIDTH mode")

rule("2. IT SHOWS UP IN THE LIBRARY IMMEDIATELY")
libs = blm.library_collections(scene)
print("  libraries:", libs)
check("lib_custom" in libs, "new library is discoverable with no rebuild")
check(blm.assets_in("lib_custom") == [new.name],
      "asset listed by the swap grid")
check(P.library == "lib_custom", "library dropdown switched to it")
items = [i[0] for i in blm.library_enum_items(None, bpy.context)]
check("lib_custom" in items, "dropdown enum rebuilt to include it")

rule("3. STRETCH MODE FILLS THE SLOT EXACTLY")
src2 = make_test_mesh("TallThing", size=(2.0, 0.4, 9.0), loc=(-20, 5, 3))
select_only(src2)
bpy.ops.blm.add_asset(target="lib_custom", fit="STRETCH", slot_height=3.0)
s2 = [o for o in col.objects if o.name != new.name][0]
x0, x1, y0, y1, z0, z1 = bounds(s2)
print("  result: X span %.3f  Z span %.3f" % (x1 - x0, z1 - z0))
check(abs((x1 - x0) - 3.0) < 1e-3 and abs((z1 - z0) - 3.0) < 1e-3,
      "stretched to exactly 3.00 x 3.00")

rule("4. MODIFIERS ARE BAKED IN")
src3 = make_test_mesh("Smoothed", size=(3.0, 1.0, 3.0), loc=(0, 0, 0),
                      with_modifier=True)
base_verts = len(src3.data.vertices)
select_only(src3)
bpy.ops.blm.add_asset(target="lib_custom", fit="WIDTH")
s3 = [o for o in col.objects if o.name.startswith("Smoothed")][0]
print("  source mesh verts %d -> asset verts %d" % (base_verts, len(s3.data.vertices)))
check(len(s3.data.vertices) > base_verts, "subsurf applied (what you see is added)")

rule("5. IT CAN ACTUALLY BE SWAPPED ONTO A BUILDING")
P.building = bpy.data.objects["building_base"]
mod = [m for m in P.building.modifiers if m.type == "NODES"][0]
ident = {i.name: i.identifier for i in mod.node_group.interface.items_tree
         if getattr(i, "item_type", "") == "SOCKET" and i.in_out == "INPUT"}
for k in ("Min number of floors", "Max number of floors"):
    mod[ident[k]] = 4
P.building.update_tag()
bpy.context.view_layer.update()
bpy.ops.blm.modularize()
mods = [o for o in P.modules_collection.objects if blm.is_module(o)]
wall = next(o for o in mods if "wall" in o.get(blm.P_SLOT, ""))
select_only(wall)
before = blm.current_asset(wall)
before_loc = wall.matrix_world.translation.copy()
P.library = "lib_custom"
bpy.ops.blm.swap(asset=new.name)
print("  %s -> %s" % (before, blm.current_asset(wall)))
check(blm.current_asset(wall) == new.name, "custom asset swapped onto a module")
check((wall.matrix_world.translation - before_loc).length < 1e-5,
      "transform preserved")

rule("6. GUARDS")
select_only(wall)                       # a module, not a candidate asset
try:
    r = bpy.ops.blm.add_asset(target="lib_custom", fit="WIDTH")
    refused = "CANCELLED" in r
except RuntimeError as e:
    refused = True
    print("  (reported: %s)" % e)
check(refused, "refuses to add a placed module as an asset")

select_only(new)                        # already a library asset
try:
    r = bpy.ops.blm.add_asset(target="lib_custom", fit="WIDTH")
    refused = "CANCELLED" in r
except RuntimeError as e:
    refused = True
check(refused, "refuses to re-add an existing library asset")

n_before = len(col.objects)
src4 = make_test_mesh("Dupe", size=(3.0, 1.0, 3.0), loc=(0, 0, 0))
select_only(src4)
bpy.ops.blm.add_asset(target="lib_custom", fit="WIDTH", asset_name=new.name)
names = [o.name for o in col.objects]
check(len(col.objects) == n_before + 1 and len(set(names)) == len(names),
      "name collision resolved instead of clobbering")
print("  library now:", sorted(names))

rule("RESULT: %s" % ("ALL PASSED" if not fails else "%d FAILURE(S)" % len(fails)))
for f in fails:
    print("  -", f)
