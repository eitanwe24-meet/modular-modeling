"""
Library geometry conformance + cross-library swapping.

Run:  blender -b buildify_1.0.blend --python test_me_library.py
"""

import importlib.util
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
fails = []


def rule(t):
    print("\n" + "=" * 72 + "\n" + t + "\n" + "=" * 72)


def check(c, m):
    print(("PASS  " if c else "FAIL  ") + m)
    if not c:
        fails.append(m)


def bounds(ob):
    bb = [Vector(v) for v in ob.bound_box]
    return ([min(v.x for v in bb), max(v.x for v in bb)],
            [min(v.y for v in bb), max(v.y for v in bb)],
            [min(v.z for v in bb), max(v.z for v in bb)])


# ---------------------------------------------------------------------------
rule("1. BUILD LIBRARY")
col, objs = mk.build_library(scene)
print("collection: %s   modules: %d" % (col.name, len(objs)))
check(len(objs) == 5, "five modules built")

rule("2. GEOMETRY CONFORMANCE (3 x 3 m, Buildify placement convention)")
BUDGET = {"me_1_solid": 20, "me_2_window_arch": 90, "me_3_mashrabiya": 140,
          "me_4_door_arch": 90, "me_5_parapet": 120}
total = 0
for ob in objs:
    x, y, z = bounds(ob)
    ob.data.calc_loop_triangles()
    tris = len(ob.data.loop_triangles)
    total += tris
    want_h = 1.0 if "parapet" in ob.name else 3.0
    ok_x = abs((x[1] - x[0]) - 3.0) < 1e-4 and abs(x[0] + 1.5) < 1e-4
    ok_z = abs((z[1] - z[0]) - want_h) < 1e-4 and abs(z[0]) < 1e-4
    ok_t = tris <= BUDGET[ob.name]
    print("  %-18s X[%6.2f,%5.2f] Y[%6.2f,%5.2f] Z[%5.2f,%5.2f] %4d tris"
          % (ob.name, x[0], x[1], y[0], y[1], z[0], z[1], tris))
    check(ok_x, "%s is 3.00 m wide, centred on X" % ob.name)
    check(ok_z, "%s is %.2f m tall with origin at the base" % (ob.name, want_h))
    check(ok_t, "%s within tri budget (%d <= %d)" % (ob.name, tris, BUDGET[ob.name]))
print("  total: %d tris" % total)
check(total < 500, "whole library under 500 tris (%d)" % total)

rule("3. FACADE ORIENTATION")
for ob in objs:
    _x, y, _z = bounds(ob)
    check(y[1] > 0.0, "%s has body behind the facade plane (+Y)" % ob.name)
proj = [ob.name for ob in objs if bounds(ob)[1][0] < -0.2]
print("  modules projecting outward past 0.2 m: %s" % proj)
check(proj == ["me_3_mashrabiya"], "only the mashrabiya projects far outward")

rule("4. NORMALS FACE OUTWARD")
for ob in objs:
    me = ob.data
    out = sum(1 for pgon in me.polygons if pgon.normal.y < -0.5)
    check(out > 0, "%s has outward-facing front geometry (%d faces)"
          % (ob.name, out))

rule("5. LIBRARY IS DISCOVERABLE BY THE ADD-ON")
libs = blm.library_collections(scene)
print("  libraries visible to the add-on: %s" % libs)
check(mk.COLLECTION in libs, "new library appears alongside Buildify's")
check(len(libs) > 1, "Buildify's collections are still there (sit alongside)")
check(sorted(blm.assets_in(mk.COLLECTION)) == sorted(o.name for o in objs),
      "add-on lists exactly the five modules")

rule("6. CROSS-LIBRARY SWAP ON A REAL BUILDING")
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

wall = next(o for o in mods if "wall" in o.get(blm.P_SLOT, ""))
for o in bpy.context.view_layer.objects:
    o.select_set(False)
wall.select_set(True)
bpy.context.view_layer.objects.active = wall

before_asset = blm.current_asset(wall)
before_loc = wall.matrix_world.translation.copy()
before_tris = len(wall.data.polygons)
snapshot = {o.name: blm.current_asset(o) for o in mods}

# AUTO must still refuse a foreign asset
P.library = "AUTO"
bpy.ops.blm.swap(asset="me_2_window_arch")
check(blm.current_asset(wall) == before_asset,
      "AUTO mode still refuses a cross-library asset")

# choosing the library explicitly must allow it
P.library = mk.COLLECTION
bpy.ops.blm.swap(asset="me_2_window_arch")
after_asset = blm.current_asset(wall)
print("  %s  ->  %s" % (before_asset, after_asset))
check(after_asset == "me_2_window_arch", "explicit library allows the swap")
check(len(wall.data.polygons) != before_tris, "mesh actually changed")
check((wall.matrix_world.translation - before_loc).length < 1e-5,
      "transform preserved")
check(wall.get(blm.P_ORIG) == before_asset, "original asset still remembered")

changed = [n for n, a in snapshot.items()
           if blm.current_asset(bpy.data.objects[n]) != a]
check(changed == [wall.name], "no other module changed")

rule("7. CYCLE WITHIN THE NEW LIBRARY")
seen = []
for _ in range(5):
    seen.append(blm.current_asset(wall))
    bpy.ops.blm.cycle(delta=1)
print("  cycled:", seen)
check(len(set(seen)) == 5, "cycling visits all five new modules")

rule("8. REVERT CROSSES BACK")
bpy.ops.blm.revert()
print("  after revert:", blm.current_asset(wall))
check(blm.current_asset(wall) == before_asset,
      "revert restores the Buildify module it started as")

rule("RESULT: %s" % ("ALL PASSED" if not fails else "%d FAILURE(S)" % len(fails)))
for f in fails:
    print("  -", f)

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, "me_mixed_demo.blend"))
print("saved me_mixed_demo.blend")
