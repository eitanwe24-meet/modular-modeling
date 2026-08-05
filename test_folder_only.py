"""
With an asset folder configured, the folder's sections are the ONLY libraries
in the dropdown -- Buildify's in-file collections must not be mixed in -- and
pressing Refresh must rebuild that list.

Run: blender -b buildify_1.0.blend --python test_folder_only.py -- <root>
"""

import importlib.util
import os
import shutil
import sys

import bpy

HERE = r"C:\Users\User\Desktop\BuildingGen"
ROOT = (sys.argv[sys.argv.index("--") + 1:] or
        [os.path.join(os.path.expanduser("~"), "Desktop", "BuildingAssets")])[0]

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


BUILDIFY = {"ground_floor_walls", "middle_floor_walls", "trim",
            "ground_floor_pillars", "middle_floor_pillars", "top_trim_pillars"}

rule("1. BEFORE A FOLDER IS SET: in-file collections are the libraries")
libs0 = blm.library_collections(scene)
print("  libraries: %s" % libs0)
check(BUILDIFY & set(libs0), "Buildify's collections show when there is no folder")

rule("2. AFTER SYNC: only the folder's sections are listed")
P.asset_folder = ROOT
P.obj_forward, P.obj_up = "NEGATIVE_Z", "Y"
r = bpy.ops.blm.sync_folder()
check("FINISHED" in r, "sync succeeded")

libs = blm.library_collections(scene)
print("  libraries: %s" % libs)
sections = ["lib_" + s for s in blm.sections_in(ROOT)]
check(sorted(libs) == sorted(sections),
      "dropdown lists exactly the folder's sections")
check(not (BUILDIFY & set(libs)),
      "Buildify's in-file collections are NOT in the dropdown")
check(all(c.startswith("lib_") for c in libs), "every library is folder-backed")

items = [i[0] for i in blm.library_enum_items(None, bpy.context)]
print("  enum items: %s" % items)
check(not (BUILDIFY & set(items)), "the enum itself is clean too")
check(P.library in libs, "current selection is a real section (%s)" % P.library)

rule("3. MODULE ORIGINS STILL RESOLVE (slot_of sees everything)")
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
slotted = [o for o in mods if o.get(blm.P_SLOT)]
print("  %d modules, %d with a resolved origin" % (len(mods), len(slotted)))
check(len(slotted) > 100, "modules still know which collection they came from")

rule("4. SWAPPING FROM A FOLDER SECTION")
wall = next(o for o in mods if "wall" in o.get(blm.P_SLOT, ""))
for o in bpy.context.view_layer.objects:
    o.select_set(False)
wall.select_set(True)
bpy.context.view_layer.objects.active = wall
before = blm.current_asset(wall)
before_loc = wall.matrix_world.translation.copy()
P.library = "lib_walls"
target = blm.assets_in("lib_walls")[0]
bpy.ops.blm.swap(asset=target)
print("  %s -> %s" % (before, blm.current_asset(wall)))
check(blm.current_asset(wall) == target, "swapped from lib_walls")
check((wall.matrix_world.translation - before_loc).length < 1e-5,
      "transform preserved")

rule("5. REFRESH PICKS UP A NEW SECTION")
newdir = os.path.join(ROOT, "balconies")
os.makedirs(newdir, exist_ok=True)
shutil.copy2(blm.scan_folder(ROOT, "walls")[0],
             os.path.join(newdir, "balcony_test.obj"))
before_libs = set(blm.library_collections(scene))
bpy.ops.blm.sync_folder()
after_libs = set(blm.library_collections(scene))
print("  added: %s" % sorted(after_libs - before_libs))
check("lib_balconies" in after_libs, "Refresh added the new section as a library")
check(blm.assets_in("lib_balconies") , "and loaded its asset")

rule("6. REFRESH DROPS A DELETED SECTION")
shutil.rmtree(newdir)
bpy.ops.blm.sync_folder()
libs2 = blm.library_collections(scene)
print("  libraries: %s" % libs2)
check("lib_balconies" not in libs2, "Refresh removed the deleted section")
check("lib_balconies" not in bpy.data.collections,
      "its collection was cleaned up, not just hidden")
check(sorted(libs2) == sorted(["lib_" + s for s in blm.sections_in(ROOT)]),
      "dropdown matches the folder again")

rule("7. 'FOLDER ONLY' OFF BRINGS THE IN-FILE COLLECTIONS BACK")
P.folder_only = False
libs3 = blm.library_collections(scene)
print("  libraries: %d entries" % len(libs3))
check(BUILDIFY & set(libs3), "Buildify's collections reappear when unticked")
check(set(["lib_" + s for s in blm.sections_in(ROOT)]) <= set(libs3),
      "folder sections are still there too")
P.folder_only = True

rule("RESULT: %s" % ("ALL PASSED" if not fails else "%d FAILURE(S)" % len(fails)))
for f in fails:
    print("  -", f)
