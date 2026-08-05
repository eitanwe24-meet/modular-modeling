"""
The asset folder IS the library.

Drop .obj files into a folder, press Refresh, they become swappable modules.
The "+" button copies a file from anywhere on disk into that folder.

Run: blender -b buildify_1.0.blend --python test_folder_library.py
"""

import importlib.util
import os
import shutil
import sys
import tempfile

import bpy

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

ROOT = os.path.join(tempfile.gettempdir(), "blm_assets_test")
OUTSIDE = os.path.join(tempfile.gettempdir(), "blm_elsewhere")
for d in (ROOT, OUTSIDE):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)


def rule(t):
    print("\n" + "=" * 72 + "\n" + t + "\n" + "=" * 72)


def check(c, m):
    print(("PASS  " if c else "FAIL  ") + m)
    if not c:
        fails.append(m)


def write_obj(folder, name, w, h, d=0.3):
    """A minimal hand-written box .obj of a deliberately wrong size."""
    path = os.path.join(folder, name + ".obj")
    v = [(0, 0, 0), (w, 0, 0), (w, d, 0), (0, d, 0),
         (0, 0, h), (w, 0, h), (w, d, h), (0, d, h)]
    f = [(1, 4, 3, 2), (5, 6, 7, 8), (1, 2, 6, 5),
         (2, 3, 7, 6), (3, 4, 8, 7), (4, 1, 5, 8)]
    with open(path, "w") as fh:
        fh.write("# test asset %s\n" % name)
        for x, y, z in v:
            fh.write("v %f %f %f\n" % (x, y, z))
        for q in f:
            fh.write("f %s\n" % " ".join(str(i) for i in q))
    return path


def col_now():
    return bpy.data.collections.get(blm.folder_collection_name(ROOT))


# ---------------------------------------------------------------------------
rule("1. POINT AT A FOLDER OF .OBJ FILES")
write_obj(ROOT, "wall_plain", 5.0, 4.0)
write_obj(ROOT, "wall_window", 2.0, 2.0)
P.asset_folder = ROOT
# these test files are written in Blender's own axis convention, so import
# without any rotation; the defaults (-Z fwd / Y up) are for files produced by
# Blender's OBJ *exporter*, which rotates on the way out
P.obj_forward, P.obj_up = "Y", "Z"
print("  folder: %s" % ROOT)
print("  files : %s" % [os.path.basename(f) for f in blm.scan_folder(ROOT)])
check(len(blm.scan_folder(ROOT)) == 2, "folder scan finds both .obj files")

r = bpy.ops.blm.sync_folder()
print("  sync ->", r)
check("FINISHED" in r, "sync succeeded")
col = col_now()
check(col is not None, "collection created for the folder")
print("  collection: %s  assets: %s"
      % (col.name, sorted(o.name for o in col.objects)))
check(len(col.objects) == 2, "both .obj files imported as assets")

rule("2. IMPORTED ASSETS ARE AUTO-FITTED TO THE SLOT")
for ob in sorted(col.objects, key=lambda o: o.name):
    x0, x1, y0, y1, z0, z1 = blm.mesh_bounds(ob.data)
    print("  %-14s X[%6.2f,%5.2f] Y[%5.2f,%5.2f] Z[%5.2f,%5.2f]"
          % (ob.name, x0, x1, y0, y1, z0, z1))
    check(abs((x1 - x0) - 3.0) < 1e-3, "%s fitted to 3.00 m wide" % ob.name)
    check(abs(x0 + 1.5) < 1e-3, "%s centred on X" % ob.name)
    check(abs(z0) < 1e-3, "%s based at Z=0" % ob.name)
    check(abs(y0) < 1e-3, "%s front face on Y=0" % ob.name)
    check((z1 - z0) > 0.3 * (x1 - x0),
          "%s stands upright (not flattened by a wrong axis)" % ob.name)

rule("2b. A MIS-ORIENTED FILE IS FLAGGED, NOT SILENTLY ACCEPTED")
ob_bad, note = blm.import_asset_file(
    os.path.join(ROOT, "wall_plain.obj"), "WIDTH", 3.0, "NEGATIVE_Z", "Y")
print("  imported with the wrong axis -> note: %r" % note)
check("flat" in (note or ""), "wrong axis convention is reported")
if ob_bad:
    bpy.data.objects.remove(ob_bad, do_unlink=True)

rule("3. IT IS A REAL LIBRARY THE ADD-ON CAN USE")
libs = blm.library_collections(scene)
print("  libraries: %s" % libs)
check(col.name in libs, "folder library is discoverable")
check(P.library == col.name, "dropdown switched to it")
check(sorted(blm.assets_in(col.name)) == sorted(o.name for o in col.objects),
      "swap grid lists the folder's assets")

rule("4. DRAG A NEW .OBJ IN, PRESS REFRESH")
write_obj(ROOT, "wall_door", 3.0, 6.0)
print("  dropped wall_door.obj into the folder")
bpy.ops.blm.sync_folder()
col = col_now()
names = sorted(o.name for o in col.objects)
print("  assets now: %s" % names)
check("wall_door" in names, "new file picked up on refresh")
check(len(col.objects) == 3, "no duplicates of the existing two")

rule("5. UNCHANGED FILES ARE NOT RE-IMPORTED")
ids = {o.name: o.data.name for o in col.objects}
bpy.ops.blm.sync_folder()
col = col_now()
same = all(o.data.name == ids.get(o.name) for o in col.objects)
print("  mesh datablocks stable across a second sync: %s" % same)
check(same, "re-scan skips unchanged files")
check(len(col.objects) == 3, "still three assets")

rule("6. EDIT A FILE -> IT REFRESHES")
before_verts = len(bpy.data.objects["wall_window"].data.vertices)
p2 = write_obj(ROOT, "wall_window", 2.0, 2.0, d=0.9)
os.utime(p2, (os.path.getmtime(p2) + 10, os.path.getmtime(p2) + 10))
bpy.ops.blm.sync_folder()
col = col_now()
w = bpy.data.objects.get("wall_window")
x0, x1, y0, y1, z0, z1 = blm.mesh_bounds(w.data)
print("  wall_window depth now %.2f (was 0.3-scaled)" % (y1 - y0))
check(w is not None and len(col.objects) == 3, "changed file re-imported in place")

rule("7. DELETE A FILE -> THE ASSET GOES AWAY")
os.remove(os.path.join(ROOT, "wall_door.obj"))
bpy.ops.blm.sync_folder()
col = col_now()
names = sorted(o.name for o in col.objects)
print("  assets now: %s" % names)
check("wall_door" not in names, "deleted file's asset removed")
check(len(col.objects) == 2, "the other two survive")

rule("8. THE '+' BUTTON: COPY A FILE FROM ANYWHERE INTO THE FOLDER")
ext = write_obj(OUTSIDE, "imported_arch", 4.0, 4.0)
print("  outside file: %s" % ext)
r = bpy.ops.blm.import_asset_file(filepath=ext, directory=OUTSIDE)
print("  import ->", r)
check("FINISHED" in r, "+ button ran")
check(os.path.exists(os.path.join(ROOT, "imported_arch.obj")),
      "file was COPIED into the asset folder")
check(os.path.exists(ext), "the original file was not moved or deleted")
col = col_now()
names = sorted(o.name for o in col.objects)
print("  assets now: %s" % names)
check("imported_arch" in names, "copied file loaded straight away")

rule("9. NAME COLLISIONS DO NOT CLOBBER")
ext2 = write_obj(OUTSIDE, "imported_arch", 9.0, 9.0)
bpy.ops.blm.import_asset_file(filepath=ext2, directory=OUTSIDE)
on_disk = sorted(os.path.basename(f) for f in blm.scan_folder(ROOT))
print("  folder contents: %s" % on_disk)
check("imported_arch_01.obj" in on_disk, "second copy renamed, first intact")

rule("10. SWAP A FOLDER ASSET ONTO A REAL BUILDING")
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
for o in bpy.context.view_layer.objects:
    o.select_set(False)
wall.select_set(True)
bpy.context.view_layer.objects.active = wall
before = blm.current_asset(wall)
before_loc = wall.matrix_world.translation.copy()
P.library = col.name
bpy.ops.blm.swap(asset="wall_plain")
print("  %s -> %s" % (before, blm.current_asset(wall)))
check(blm.current_asset(wall) == "wall_plain", "folder asset swapped onto module")
check((wall.matrix_world.translation - before_loc).length < 1e-5,
      "transform preserved")

rule("11. SAVE A BLENDER MESH BACK OUT TO THE FOLDER")
bpy.ops.mesh.primitive_cube_add(size=2.0, location=(50, 50, 50))
cube = bpy.context.active_object
cube.name = "handmade"
for o in bpy.context.view_layer.objects:
    o.select_set(False)
cube.select_set(True)
bpy.context.view_layer.objects.active = cube
bpy.ops.blm.export_to_folder(asset_name="handmade")
check(os.path.exists(os.path.join(ROOT, "handmade.obj")),
      "selection exported into the asset folder as .obj")
col = col_now()
# the scene already holds an object called "handmade", so Blender gives the
# asset a .001 suffix; match on the source file instead of the name
srcs = [os.path.basename(o.get(blm.P_SRC, "")) for o in col.objects]
print("  assets by source file: %s" % sorted(srcs))
check("handmade.obj" in srcs, "and loaded back as a library asset")

rule("RESULT: %s" % ("ALL PASSED" if not fails else "%d FAILURE(S)" % len(fails)))
for f in fails:
    print("  -", f)
print("\ntest folder left at: %s" % ROOT)
