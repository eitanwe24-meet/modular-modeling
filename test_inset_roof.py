"""Raise Roof By Inset: detect the roof, inset it as one, lift the inset.

Each step is checked on its own, because each can fail quietly: the detection
can pick up a floor as well as a roof, the inset can fold the outline through
itself while every individual face still looks valid, and the lift can move
the wrong vertices.

Run: blender -b --factory-startup --python test_inset_roof.py
"""
import importlib.util
import sys

import bmesh
import bpy

ADDON = r"C:\Users\User\Desktop\BuildingGen\buildify_modular.py"
spec = importlib.util.spec_from_file_location("blm_mod", ADDON)
blm = importlib.util.module_from_spec(spec)
sys.modules["blm_mod"] = blm
spec.loader.exec_module(blm)
blm.register()

fails = []


def rule(t):
    print("\n" + "=" * 72 + "\n" + t + "\n" + "=" * 72)


def check(c, m):
    print(("PASS  " if c else "FAIL  ") + m)
    if not c:
        fails.append(m)


def flat(name, pts, z=6.0, faces=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata([(x, y, z) for x, y in pts], [],
                   faces if faces else [list(range(len(pts)))])
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def run(ob, **kw):
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.blm.inset_roof(**kw)
    return ob.data


def zs(me):
    return [v.co.z for v in me.vertices]


def open_edges(me):
    counts = {}
    for poly in me.polygons:
        for key in poly.edge_keys:
            counts[key] = counts.get(key, 0) + 1
    return [k for k, n in counts.items() if n > 2]


rule("1. DETECT THE ROOF, EVEN WHEN IT IS SEVERAL FACES")
# a roof split into two coplanar quads, plus a floor facing up further down
me = bpy.data.meshes.new("split")
me.from_pydata([(0, 0, 6), (6, 0, 6), (6, 6, 6), (0, 6, 6),
                (12, 0, 6), (12, 6, 6),
                (0, 0, 0), (12, 0, 0), (12, 6, 0), (0, 6, 0)], [],
               [(0, 1, 2, 3), (1, 4, 5, 2), (6, 7, 8, 9)])
me.update()
ob = bpy.data.objects.new("split", me)
bpy.context.scene.collection.objects.link(ob)

bm = bmesh.new()
bm.from_mesh(me)
bm.normal_update()
patch = blm.roof_patch(bm)
print("upward faces %d, patch %d"
      % (sum(1 for f in bm.faces if f.normal.z > 0.5), len(patch)))
check(len(patch) == 2, "both roof faces found, and only those two")
check(all(max(v.co.z for v in f.verts) > 5.9 for f in patch),
      "the floor at z=0 was not swept in with them")
bm.free()

rule("2. INSET AS ONE REGION, NOT FACE BY FACE")
# gabling is off here on purpose: it slides the ridge along afterwards, and
# this section is about where the inset itself put things
data = run(ob, height=3.0, gabled=False)
top = [v for v in data.vertices if v.co.z > 6.5]
print("%d faces, %d raised vertices, z %.2f .. %.2f"
      % (len(data.polygons), len(top), min(zs(data)), max(zs(data))))
check(len(top) > 0, "something was raised")

# Inset face-by-face would build a wall down the shared edge at x = 6: the
# edge would be duplicated, four raised vertices would sit on that line
# instead of two, and the two lifted faces would no longer touch. Inset as one
# region keeps the edge interior -- so the edge surviving is right, and the
# edge being doubled is what would be wrong.
on_seam = [v for v in top if abs(v.co.x - 6.0) < 1e-4]
print("raised vertices on the shared line: %d" % len(on_seam))
check(len(on_seam) == 2,
      "the shared edge was not duplicated into a wall (2 verts, not 4)")

lifted = [p for p in data.polygons
          if all(data.vertices[i].co.z > 6.5 for i in p.vertices)]
shared = set()
if len(lifted) == 2:
    shared = set(lifted[0].edge_keys) & set(lifted[1].edge_keys)
print("lifted faces %d, edges they share %d" % (len(lifted), len(shared)))
check(len(lifted) == 2, "both roof faces were lifted")
check(len(shared) == 1, "and they still touch: the region moved as one")
check(len(data.polygons) == 9,
      "2 lifted + 6 around the rim + the floor, not 10 from a per-face inset")
check(not open_edges(data), "no edge shared by more than two faces")

rule("3. THE INSET GOES AS FAR AS THE OUTLINE ALLOWS")
ob2 = flat("rect", [(0, 0), (12, 0), (12, 6), (0, 6)])
bm = bmesh.new()
bm.from_mesh(ob2.data)
bm.normal_update()
patch = blm.roof_patch(bm)
limit = blm.largest_inset(bm, patch)
bm.free()
# a 12 x 6 rectangle collapses to a ridge line when inset by half its width
print("largest inset %.4f m, half-width is 3.0" % limit)
check(abs(limit - 3.0) < 0.05, "found the collapse distance, near enough")

run(ob2, height=3.0)
raised = [v.co for v in ob2.data.vertices if v.co.z > 6.5]
xs = sorted(round(p.x, 2) for p in raised)
ys = sorted(round(p.y, 2) for p in raised)
print("ridge x %s  y %s" % (xs, ys))
check(len(raised) >= 2, "the inset became a ridge line, not a point")
check(max(ys) - min(ys) < 0.2,
      "the ridge is a line along the length, not a wide flat top")
check(abs(max(zs(ob2.data)) - 9.0) < 1e-4, "raised by exactly 3 m")

rule("4. A CONCAVE PLAN MUST NOT FOLD THROUGH ITSELF")
L = [(0, 0), (12, 0), (12, 6), (6, 6), (6, 14), (0, 14)]
ob3 = flat("Lshape", L)
bm = bmesh.new()
bm.from_mesh(ob3.data)
bm.normal_update()
patch = blm.roof_patch(bm)
limit3 = blm.largest_inset(bm, patch)
bm.free()
print("L-shape largest inset %.4f m" % limit3)
check(0.1 < limit3 < 3.05, "an L insets less far than its bounding box would")

data3 = run(ob3, height=3.0)
check(not open_edges(data3), "the L stayed a valid surface")
areas = [p.area for p in data3.polygons]
check(min(areas) > 1e-6, "no face collapsed to nothing")
check(all(p.normal.z > -0.01 or abs(p.normal.z) < 0.9 for p in data3.polygons),
      "no face turned inside out")
print("L: %d faces, smallest %.5f m2, z %.2f .. %.2f"
      % (len(data3.polygons), min(areas), min(zs(data3)), max(zs(data3))))

rule("5. GABLED ENDS STAND VERTICAL, HIPPED ENDS SLOPE")
hip = flat("hipped", [(0, 0), (12, 0), (12, 6), (0, 6)])
run(hip, height=3.0, gabled=False)
hz = zs(hip.data)
hip_ridge = [v.co for v in hip.data.vertices if v.co.z > 6.5]
hip_len = max(p.x for p in hip_ridge) - min(p.x for p in hip_ridge)

gab = flat("gabled", [(0, 0), (12, 0), (12, 6), (0, 6)])
run(gab, height=3.0, gabled=True)
gab_ridge = [v.co for v in gab.data.vertices if v.co.z > 6.5]
gab_len = max(p.x for p in gab_ridge) - min(p.x for p in gab_ridge)
print("ridge length: hipped %.3f m, gabled %.3f m (building is 12 m)"
      % (hip_len, gab_len))
check(gab_len > hip_len + 1.0, "the gabled ridge is the longer of the two")
check(abs(gab_len - 12.0) < 1e-3, "and runs the full length of the building")
check(abs(min(zs(gab.data)) - 6.0) < 1e-4, "the eaves did not move")
check(abs(max(zs(gab.data)) - 9.0) < 1e-4, "nor did the ridge height")

# the end faces are the ones spanning both heights. Gabled, they must be
# vertical: a vertical face has no z in its normal.
def end_faces(me):
    out = []
    for p in me.polygons:
        pz = [me.vertices[i].co.z for i in p.vertices]
        if max(pz) > 6.5 and min(pz) < 6.5:
            out.append(p)
    return out


gab_ends = [p for p in end_faces(gab.data)
            if abs(p.normal.x) > abs(p.normal.y)]
hip_ends = [p for p in end_faces(hip.data)
            if abs(p.normal.x) > abs(p.normal.y)]
print("end faces: gabled n.z %s, hipped n.z %s"
      % ([round(p.normal.z, 3) for p in gab_ends],
         [round(p.normal.z, 3) for p in hip_ends]))
check(gab_ends and all(abs(p.normal.z) < 1e-3 for p in gab_ends),
      "gabled ends are vertical walls")
check(hip_ends and all(abs(p.normal.z) > 0.2 for p in hip_ends),
      "hipped ends slope, as they did before the toggle existed")
check(not open_edges(gab.data), "the gabled roof is still a valid surface")
check(min(p.area for p in gab.data.polygons) > 1e-6,
      "no face collapsed when the ridge ran out")

gl = flat("gabled_L", L)
run(gl, height=3.0, gabled=True)
check(not open_edges(gl.data), "an L survives gabling too")
check(min(p.area for p in gl.data.polygons) > 1e-6, "with no collapsed face")
print("gabled L: %d faces, z %.2f .. %.2f"
      % (len(gl.data.polygons), min(zs(gl.data)), max(zs(gl.data))))

rule("6. THE CONTROLS DO WHAT THEY SAY")
ob4 = flat("h5", [(0, 0), (12, 0), (12, 6), (0, 6)])
run(ob4, height=5.0)
check(abs(max(zs(ob4.data)) - 11.0) < 1e-4, "height=5 raises by 5 m")

ob5 = flat("fixed", [(0, 0), (12, 0), (12, 6), (0, 6)])
run(ob5, height=3.0, inset=1.0)
flat_top = [v.co for v in ob5.data.vertices if v.co.z > 6.5]
w = max(p.y for p in flat_top) - min(p.y for p in flat_top)
print("inset=1.0 leaves a flat top %.3f m across (expected 4.0)" % w)
check(abs(w - 4.0) < 1e-3, "a forced inset gives a flat top, not a ridge")

print("\n" + "=" * 72)
print("FAILED %d" % len(fails) if fails else "ALL PASSED")
for f in fails:
    print("  - " + f)
print("=" * 72)
sys.exit(1 if fails else 0)
