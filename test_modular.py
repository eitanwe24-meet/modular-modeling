"""Each module must be its own selectable object; swapping one must not touch
any other, and transforms must survive the swap."""
import bpy, sys, importlib.util
from collections import Counter
from mathutils import Vector

ADDON = r"C:\Users\User\Desktop\BuildingGen\buildify_modular.py"
spec = importlib.util.spec_from_file_location("blm_mod", ADDON)
blm = importlib.util.module_from_spec(spec)
sys.modules["blm_mod"] = blm
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


def modules():
    return [o for o in P.modules_collection.objects if blm.is_module(o)]


rule("0. LIBRARY")
libs = blm.library_collections(scene)
print("library collections:", libs)
for c in libs:
    print("   %-24s %s" % (c, blm.assets_in(c)))
check(len(libs) >= 2, "library discovered")

rule("1. BUILD MODULAR OBJECTS")
P.building = bpy.data.objects["building_base"]
mod = [m for m in P.building.modifiers if m.type == "NODES"][0]
ng = mod.node_group
ident = {i.name: i.identifier for i in ng.interface.items_tree
         if getattr(i, "item_type", "") == "SOCKET" and i.in_out == "INPUT"}
for k in ("Min number of floors", "Max number of floors"):
    mod[ident[k]] = 4
P.building.update_tag()
bpy.context.view_layer.update()

r = bpy.ops.blm.modularize()
print("modularize ->", r)
check("FINISHED" in r, "modularize succeeded")
mods = modules()
print("module objects created: %d" % len(mods))
check(len(mods) > 100, "one object per module")

swappable = [o for o in mods if o.get(blm.P_SLOT)]
print("swappable: %d   props: %d" % (len(swappable), len(mods) - len(swappable)))
check(len(swappable) > 50, "wall modules marked swappable")

rule("2. EACH MODULE IS INDEPENDENTLY SELECTABLE")
check(all(o.name in bpy.context.view_layer.objects for o in mods[:20]),
      "modules are real scene objects")
uniq_pos = {tuple(round(c, 2) for c in o.matrix_world.translation) for o in mods}
print("distinct module positions: %d of %d" % (len(uniq_pos), len(mods)))
check(len(uniq_pos) > len(mods) * 0.7, "modules occupy distinct positions")
# selecting one must not select others
for o in bpy.context.view_layer.objects:
    o.select_set(False)
t = swappable[len(swappable) // 2]
t.select_set(True)
bpy.context.view_layer.objects.active = t
sel = [o for o in bpy.context.view_layer.objects if o.select_get()]
print("selected after clicking one module: %d (%s)" % (len(sel), sel[0].name))
check(len(sel) == 1, "selecting one module selects ONLY that module")

rule("3. MESH DATA IS SHARED (cheap)")
data_users = Counter(o.data.name for o in mods)
print("distinct mesh datablocks: %d for %d objects" % (len(data_users), len(mods)))
check(len(data_users) < len(mods) / 3,
      "modules share mesh data instead of duplicating geometry")

rule("4. SWAP ONE MODULE")
slot = t.get(blm.P_SLOT)
cands = blm.assets_in(slot)
before_data = blm.current_asset(t)
before_xform = t.matrix_world.copy()
other = [c for c in cands if c != before_data][0]
print("target %s in slot %s: %s -> %s" % (t.name, slot, before_data, other))

snapshot = {o.name: blm.current_asset(o) for o in mods}
r = bpy.ops.blm.swap(asset=other)
print("swap ->", r)
check(blm.current_asset(t) == other, "target module now uses the new asset")
check((t.matrix_world.translation - before_xform.translation).length < 1e-5,
      "transform preserved through the swap")

rule("5. NO COLLATERAL DAMAGE")
changed = [n for n, d in snapshot.items()
           if blm.current_asset(bpy.data.objects[n]) != d]
print("modules whose asset changed: %s" % changed)
check(changed == [t.name], "only the selected module changed")

rule("6. MULTI-SELECT SWAP")
for o in bpy.context.view_layer.objects:
    o.select_set(False)
group = [o for o in swappable if o.get(blm.P_SLOT) == slot][:6]
for o in group:
    o.select_set(True)
bpy.context.view_layer.objects.active = group[0]
third = [c for c in cands if c not in (before_data, other)]
pick = third[0] if third else other
snapshot2 = {o.name: blm.current_asset(o) for o in mods}
bpy.ops.blm.swap(asset=pick)
got = [blm.current_asset(o) for o in group]
print("swapped %d modules to %s -> %s" % (len(group), pick, set(got)))
check(all(g == pick for g in got), "every selected module swapped")
outside = [n for n, d in snapshot2.items()
           if blm.current_asset(bpy.data.objects[n]) != d and
           n not in {o.name for o in group}]
check(not outside, "no module outside the selection changed")

rule("7. SLOT SAFETY")
for o in bpy.context.view_layer.objects:
    o.select_set(False)
wall = next(o for o in swappable if "wall" in o.get(blm.P_SLOT, ""))
wall.select_set(True)
bpy.context.view_layer.objects.active = wall
was = blm.current_asset(wall)
foreign = next((a for cn in libs if cn != wall.get(blm.P_SLOT)
                for a in blm.assets_in(cn)), None)
if foreign:
    bpy.ops.blm.swap(asset=foreign)
    print("tried to put %s (from another slot) into %s" % (foreign, wall.name))
    check(blm.current_asset(wall) == was, "cross-slot swap refused")
else:
    check(True, "only one slot present, nothing to test")

rule("8. CYCLE + REVERT")
for o in bpy.context.view_layer.objects:
    o.select_set(False)
t.select_set(True)
bpy.context.view_layer.objects.active = t
seen = []
for _ in range(len(cands)):
    seen.append(blm.current_asset(t))
    bpy.ops.blm.cycle(delta=1)
print("cycled:", seen)
check(len(set(seen)) == len(cands), "cycling visits every asset in the slot")
bpy.ops.blm.revert()
print("after revert:", blm.current_asset(t), " orig:", t.get(blm.P_ORIG))
check(blm.current_asset(t) == t.get(blm.P_ORIG), "revert restores the generated asset")

rule("9. HELPERS + EXPORT")
for o in bpy.context.view_layer.objects:
    o.select_set(False)
t.select_set(True)
bpy.context.view_layer.objects.active = t
bpy.ops.blm.select_same()
n_same = len([o for o in bpy.context.view_layer.objects if o.select_get()])
print("'select all like this' ->", n_same)
check(n_same > 1, "select-same-asset works")

for o in bpy.context.view_layer.objects:
    o.select_set(False)
t.select_set(True)
bpy.context.view_layer.objects.active = t
bpy.ops.blm.select_slot()
n_slot = len([o for o in bpy.context.view_layer.objects if o.select_get()])
print("'select all in slot' ->", n_slot)
check(n_slot >= n_same, "select-same-slot works")

import os
out = r"C:\Users\User\Desktop\BuildingGen\modular_building.obj"
for o in bpy.context.view_layer.objects:
    o.select_set(False)
for o in P.modules_collection.objects:
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
bpy.ops.wm.obj_export(filepath=out, export_selected_objects=True,
                      export_materials=True)
check(os.path.exists(out) and os.path.getsize(out) > 1000,
      "OBJ exported (%.0f KB)" % (os.path.getsize(out) / 1024))

rule("RESULT: %s" % ("ALL PASSED" if not fails else "%d FAILURE(S)" % len(fails)))
for f in fails:
    print("  -", f)

bpy.ops.wm.save_as_mainfile(
    filepath=r"C:\Users\User\Desktop\BuildingGen\modular_demo.blend")
print("saved modular_demo.blend")
