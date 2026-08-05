"""
The sectioned asset tree: one library per subfolder, round-tripping through
.obj without losing scale or orientation.

Run: blender -b --factory-startup --python test_sections.py -- <root>
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


rule("1. THE TREE ON DISK")
print("  root: %s" % ROOT)
check(os.path.isdir(ROOT), "asset root exists")
secs = blm.sections_in(ROOT)
print("  sections: %s" % secs)
for s in secs:
    print("    %-10s %d obj" % (s, len(blm.scan_folder(ROOT, s))))
check(set(secs) >= {"walls", "windows", "doors", "trim", "pillars", "roof"},
      "expected sections present")

rule("2. SYNC LOADS EVERY SECTION AS ITS OWN LIBRARY")
P.asset_folder = ROOT
P.obj_forward, P.obj_up = "NEGATIVE_Z", "Y"   # matches the exporter
P.folder_fit = "NONE"                          # test the raw round-trip
r = bpy.ops.blm.sync_folder()
print("  sync ->", r)
check("FINISHED" in r, "sync succeeded")

libs = blm.library_collections(scene)
print("  libraries: %s" % libs)
for s in secs:
    cname = blm.folder_collection_name(ROOT, s)
    col = bpy.data.collections.get(cname)
    n_disk = len(blm.scan_folder(ROOT, s))
    n_load = len(col.objects) if col else 0
    print("    %-16s %d/%d loaded" % (cname, n_load, n_disk))
    check(cname in libs, "%s is a library" % cname)
    check(n_load == n_disk, "%s loaded all %d assets" % (cname, n_disk))

rule("3. ROUND-TRIP FIDELITY (export -> .obj -> import)")
# these were written straight from the source modules, so with fit=NONE the
# dimensions must come back unchanged
EXPECT = {"me_1_solid": (3.0, 0.20, 3.0),
          "me_2_window_arch": (3.0, 0.24, 3.0),
          "me_3_mashrabiya": (3.0, 0.63, 3.0),
          "me_4_door_arch": (3.0, 0.42, 3.0),
          "me_5_parapet": (3.0, 0.24, 1.0)}
for name, (ew, ed, eh) in EXPECT.items():
    ob = bpy.data.objects.get(name)
    if ob is None:
        check(False, "%s present after round-trip" % name)
        continue
    x0, x1, y0, y1, z0, z1 = blm.mesh_bounds(ob.data)
    w, d, h = x1 - x0, y1 - y0, z1 - z0
    print("  %-18s %.2f x %.2f x %.2f  (expected %.2f x %.2f x %.2f)"
          % (name, w, d, h, ew, ed, eh))
    check(abs(w - ew) < 0.02 and abs(h - eh) < 0.02,
          "%s keeps its size through the .obj round-trip" % name)
    check(h > 0.3 * w or name == "me_5_parapet",
          "%s stands upright (orientation survived)" % name)
    check(abs(x0 + w / 2) < 0.02 and abs(z0) < 0.02,
          "%s keeps origin at base-centre" % name)

rule("4. SECTIONS ARE SEPARATE, NOT ONE BIG POOL")
walls = blm.assets_in(blm.folder_collection_name(ROOT, "walls"))
roof = blm.assets_in(blm.folder_collection_name(ROOT, "roof"))
print("  walls:  %s" % walls)
print("  roof :  %s" % roof)
check(walls and roof and not set(walls) & set(roof),
      "walls and roof hold different assets")
check("me_1_solid" in walls, "our solid wall filed under walls")
check(any("chimney" in n or "antenna" in n for n in roof),
      "Buildify rooftop props filed under roof")

rule("5. ADDING A FILE TO A SECTION REFRESHES IT")
src = os.path.join(ROOT, "walls", os.path.basename(
    blm.scan_folder(ROOT, "walls")[0]))
tmp = os.path.join(os.path.expanduser("~"), "Desktop", "_tmp_asset.obj")
shutil.copy2(src, tmp)
before = len(blm.assets_in(blm.folder_collection_name(ROOT, "windows")))
r = bpy.ops.blm.import_asset_file(filepath=tmp, directory=os.path.dirname(tmp),
                                  section="windows")
print("  import into 'windows' ->", r)
after = len(blm.assets_in(blm.folder_collection_name(ROOT, "windows")))
print("  windows: %d -> %d assets" % (before, after))
check(after == before + 1, "file landed in the chosen section and auto-refreshed")
check(P.library == blm.folder_collection_name(ROOT, "windows"),
      "dropdown switched to that section")

rule("6. A BRAND NEW SECTION CAN BE CREATED")
r = bpy.ops.blm.import_asset_file(filepath=tmp, directory=os.path.dirname(tmp),
                                  new_section="balconies")
newdir = os.path.join(ROOT, "balconies")
check(os.path.isdir(newdir), "new section folder created on disk")
cname = blm.folder_collection_name(ROOT, "balconies")
check(cname in blm.library_collections(scene), "and registered as a library")
print("  sections now: %s" % blm.sections_in(ROOT))

rule("7. CLEANUP LEAVES THE TREE CONSISTENT")
for f in blm.scan_folder(ROOT, "balconies"):
    os.remove(f)
os.rmdir(newdir)
# the copied file is named after the temp file, not after its source
extra = [f for f in blm.scan_folder(ROOT, "windows")
         if os.path.basename(f).startswith("_tmp_asset")]
print("  removing from windows/: %s" % [os.path.basename(f) for f in extra])
for f in extra:
    os.remove(f)
os.remove(tmp)
bpy.ops.blm.sync_folder()
check(cname not in blm.library_collections(scene),
      "removed section's library dropped")
check(len(blm.assets_in(blm.folder_collection_name(ROOT, "windows"))) == before,
      "windows back to its original %d assets" % before)

rule("RESULT: %s" % ("ALL PASSED" if not fails else "%d FAILURE(S)" % len(fails)))
for f in fails:
    print("  -", f)
