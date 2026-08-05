"""
Final export is FBX, in both separate-modules and joined form.

Run: blender -b buildify_1.0.blend --python test_export_fbx.py
"""

import importlib.util
import os
import sys

import bpy

HERE = r"C:\Users\User\Desktop\BuildingGen"
OUT = os.path.join(HERE, "_fbx_out")
os.makedirs(OUT, exist_ok=True)

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


rule("1. BUILD A BUILDING")
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
print("  modules: %d" % len(mods))
check(len(mods) > 100, "modules built")

rule("2. THE OPERATOR IS FBX, NOT OBJ")
check(hasattr(bpy.types, "BLM_OT_export_fbx"), "blm.export_fbx exists")
check(not hasattr(bpy.types, "BLM_OT_export_obj"), "the old OBJ operator is gone")

rule("3. EXPORT AS SEPARATE MODULES")
sep = os.path.join(OUT, "building_separate.fbx")
if os.path.exists(sep):
    os.remove(sep)
r = bpy.ops.blm.export_fbx(filepath=sep, join_meshes=False)
print("  export ->", r)
check("FINISHED" in r, "separate export ran")
check(os.path.exists(sep), "file written")
size = os.path.getsize(sep) if os.path.exists(sep) else 0
print("  %s  %.0f KB" % (os.path.basename(sep), size / 1024))
check(size > 10000, "file has real content (%.0f KB)" % (size / 1024))
with open(sep, "rb") as fh:
    head = fh.read(64)
check(b"Kaydara FBX Binary" in head, "it is a real FBX (magic header present)")

rule("4. EXPORT JOINED INTO ONE MESH")
joined = os.path.join(OUT, "building_joined.fbx")
if os.path.exists(joined):
    os.remove(joined)
n_before = len(P.modules_collection.objects)
r = bpy.ops.blm.export_fbx(filepath=joined, join_meshes=True)
print("  export ->", r)
check("FINISHED" in r, "joined export ran")
check(os.path.exists(joined), "file written")
print("  %s  %.0f KB" % (os.path.basename(joined),
                         os.path.getsize(joined) / 1024))
check(os.path.getsize(joined) > 10000, "joined file has content")
check(len(P.modules_collection.objects) == n_before,
      "joining did not destroy the editable modules (%d still there)"
      % len(P.modules_collection.objects))
leftovers = [o.name for o in scene.collection.objects
             if o.name.startswith(P.modules_collection.name)]
check(not leftovers, "no temporary joined object left behind: %s" % leftovers)

rule("5. RE-IMPORT THE FBX TO PROVE IT IS READABLE")
before = set(bpy.data.objects)
bpy.ops.import_scene.fbx(filepath=sep)
fresh = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
print("  re-imported %d objects" % len(fresh))
check(len(fresh) > 100, "separate export round-trips as many objects")
tot = sum(len(o.data.polygons) for o in fresh)
print("  total faces: %d" % tot)
check(tot > 1000, "geometry survived the round trip")
for o in fresh:
    bpy.data.objects.remove(o, do_unlink=True)

before = set(bpy.data.objects)
bpy.ops.import_scene.fbx(filepath=joined)
fresh = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
print("  joined re-imported as %d object(s), %d faces"
      % (len(fresh), sum(len(o.data.polygons) for o in fresh)))
check(len(fresh) == 1, "joined export really is a single mesh")

rule("RESULT: %s" % ("ALL PASSED" if not fails else "%d FAILURE(S)" % len(fails)))
for f in fails:
    print("  -", f)
