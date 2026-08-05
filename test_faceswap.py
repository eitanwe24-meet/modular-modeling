"""bake -> pick a face -> swap it for another asset -> verify the mesh changed."""
import bpy, sys, json, importlib.util
from collections import Counter
from mathutils import Vector

ADDON = r"C:\Users\User\Desktop\BuildingGen\buildify_face_swap.py"
spec = importlib.util.spec_from_file_location("bfs_mod", ADDON)
bfs = importlib.util.module_from_spec(spec)
sys.modules["bfs_mod"] = bfs
spec.loader.exec_module(bfs)
bfs.register()

scene = bpy.context.scene
P = scene.bfs_props
fails = []


def rule(t):
    print("\n" + "=" * 72 + "\n" + t + "\n" + "=" * 72)


def check(c, m):
    print(("PASS  " if c else "FAIL  ") + m)
    if not c:
        fails.append(m)


rule("0. ASSET DISCOVERY (no 'prepare' step -- raw Buildify file)")
cols = bfs.module_collections(scene)
print("module collections:", cols)
check(len(cols) >= 2, "found module collections by name sniffing")
for c in cols:
    print("   %-22s %s" % (c, bfs.assets_in(c)))

rule("1. BAKE")
P.building = bpy.data.objects["building_base"]
mod = [m for m in P.building.modifiers if m.type == "NODES"][0]
ng = mod.node_group
ident = {i.name: i.identifier for i in ng.interface.items_tree
         if getattr(i, "item_type", "") == "SOCKET" and i.in_out == "INPUT"}
for k in ("Min number of floors", "Max number of floors"):
    mod[ident[k]] = 4
P.building.update_tag()
bpy.context.view_layer.update()

r = bpy.ops.bfs.bake()
print("bake ->", r)
check("FINISHED" in r, "bake succeeded")
ob = P.baked
check(ob is not None, "baked object created")
table = json.loads(ob[bfs.TABLE_PROP])
print("modules in table : %d" % len(table))
print("faces in mesh    : %d" % len(ob.data.polygons))
print("verts            : %d" % len(ob.data.vertices))
print("material slots   : %d" % len(ob.data.materials))
swappable = [i for i, r_ in enumerate(table) if r_["col"]]
print("swappable modules: %d" % len(swappable))
check(len(ob.data.polygons) > 1000, "baked mesh has real faces")
check(len(swappable) > 50, "wall modules identified as swappable")

rule("2. FACE -> MODULE MAPPING")
attr = ob.data.attributes[bfs.FACE_ATTR]
ids = [d.value for d in attr.data]
check(len(ids) == len(ob.data.polygons), "every face carries a panel_id")
check(max(ids) < len(table) and min(ids) >= 0, "all panel_ids are in range")
c = Counter(ids)
print("faces per module: min=%d max=%d" % (min(c.values()), max(c.values())))
# faces belonging to one module should be spatially clustered
tgt = swappable[len(swappable) // 2]
pts = [ob.data.polygons[i].center for i, v in enumerate(ids) if v == tgt]
ctr = sum(pts, Vector()) / len(pts)
spread = max((pt - ctr).length for pt in pts)
print("module %d: %d faces, spread %.2fm around %s"
      % (tgt, len(pts), spread, tuple(round(x, 1) for x in ctr)))
check(spread < 4.0, "one module's faces are spatially clustered (not scattered)")

rule("3. SWAP THE TARGETED MODULE")
P.panel_index = tgt
rec = table[tgt]
cands = bfs.assets_in(rec["col"])
print("module %d is %s from %s; candidates %s"
      % (tgt, rec["asset"], rec["col"], cands))
other = [c_ for c_ in cands if c_ != rec["asset"]][0]

before_faces = len(ob.data.polygons)
before_ids = Counter(d.value for d in ob.data.attributes[bfs.FACE_ATTR].data)
r = bpy.ops.bfs.swap(asset=other)
print("swap ->", r)
ob = P.baked
table2 = json.loads(ob[bfs.TABLE_PROP])
check(table2[tgt]["asset"] == other, "table records the new asset")
check(table2[tgt]["orig"] == rec["asset"], "original asset remembered")

src_faces = len(bpy.data.objects[other].data.polygons)
after_ids = Counter(d.value for d in ob.data.attributes[bfs.FACE_ATTR].data)
print("faces for module %d: %d -> %d (asset %s has %d)"
      % (tgt, before_ids[tgt], after_ids[tgt], other, src_faces))
check(after_ids[tgt] == src_faces, "module now has exactly the new asset's faces")

rule("4. NO COLLATERAL DAMAGE")
diff = [k for k in set(before_ids) | set(after_ids)
        if k != tgt and before_ids.get(k) != after_ids.get(k)]
print("other modules whose face count changed: %d" % len(diff))
check(not diff, "every other module untouched")

rule("5. GEOMETRY LANDED IN THE RIGHT PLACE")
pts2 = [ob.data.polygons[i].center
        for i, d in enumerate(ob.data.attributes[bfs.FACE_ATTR].data) if d.value == tgt]
ctr2 = sum(pts2, Vector()) / len(pts2)
print("centre before %s -> after %s"
      % (tuple(round(x, 2) for x in ctr), tuple(round(x, 2) for x in ctr2)))
check((ctr2 - ctr).length < 1.0, "replacement sits where the old module was")

rule("6. DELETE / RESTORE / REVERT")
bpy.ops.bfs.hide(hide=True)
ob = P.baked
ids3 = Counter(d.value for d in ob.data.attributes[bfs.FACE_ATTR].data)
check(ids3.get(tgt, 0) == 0, "delete removes the module's faces")
bpy.ops.bfs.hide(hide=False)
ob = P.baked
ids4 = Counter(d.value for d in ob.data.attributes[bfs.FACE_ATTR].data)
check(ids4.get(tgt, 0) == src_faces, "restore brings it back")
bpy.ops.bfs.revert()
ob = P.baked
t5 = json.loads(ob[bfs.TABLE_PROP])
check(t5[tgt]["asset"] == rec["asset"], "revert restores the generated asset")

rule("7. CYCLE (head to head)")
P.panel_index = tgt
seen = []
for _ in range(len(cands) + 1):
    t = json.loads(P.baked[bfs.TABLE_PROP])
    seen.append(t[tgt]["asset"])
    bpy.ops.bfs.cycle(delta=1)
print("cycled through:", seen)
check(len(set(seen)) == len(cands), "cycling visits every candidate")

rule("8. MANY EDITS AT ONCE")
edits = {}
for i in swappable[::13][:8]:
    t = json.loads(P.baked[bfs.TABLE_PROP])
    cs = bfs.assets_in(t[i]["col"])
    if len(cs) < 2:
        continue
    nxt = [c_ for c_ in cs if c_ != t[i]["asset"]][0]
    P.panel_index = i
    bpy.ops.bfs.swap(asset=nxt)
    edits[i] = nxt
final = json.loads(P.baked[bfs.TABLE_PROP])
bad = [i for i, a in edits.items() if final[i]["asset"] != a]
print("applied %d edits, %d wrong" % (len(edits), len(bad)))
check(not bad, "all %d edits held simultaneously" % len(edits))
fc = Counter(d.value for d in P.baked.data.attributes[bfs.FACE_ATTR].data)
ok = all(fc[i] == len(bpy.data.objects[a].data.polygons) for i, a in edits.items())
check(ok, "face counts match each swapped asset")

rule("9. OBJ EXPORT")
out = r"C:\Users\User\Desktop\BuildingGen\baked_building.obj"
try:
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    P.baked.select_set(True)
    bpy.context.view_layer.objects.active = P.baked
    bpy.ops.wm.obj_export(filepath=out, export_selected_objects=True,
                          export_materials=True)
    import os
    check(os.path.exists(out) and os.path.getsize(out) > 1000,
          "OBJ written (%.0f KB)" % (os.path.getsize(out) / 1024))
except Exception as e:
    check(False, "OBJ export: %s" % e)

rule("RESULT: %s" % ("ALL PASSED" if not fails else "%d FAILURE(S)" % len(fails)))
for f in fails:
    print("  -", f)

bpy.ops.wm.save_as_mainfile(
    filepath=r"C:\Users\User\Desktop\BuildingGen\face_swap_demo.blend")
print("saved face_swap_demo.blend")
