"""A gabled roof must work on any footprint, not just a rectangle.

The sweep cuts the plan into slabs at every vertex's ridge-coordinate, so an
L, a U, a rotated box and a plain rectangle all go through the same code. What
has to hold in every case: every eave sits on the wall, the ridge is where the
plan is widest, wings get their own ridges, and the ends are closed.

Run: blender -b --factory-startup --python test_gable.py
"""
import importlib.util
import math
import sys

import bpy
from mathutils import Vector

ADDON = r"C:\Users\User\Desktop\BuildingGen\buildify_modular.py"
spec = importlib.util.spec_from_file_location("blm_mod", ADDON)
blm = importlib.util.module_from_spec(spec)
sys.modules["blm_mod"] = blm
spec.loader.exec_module(blm)
blm.register()

fails = []
PITCH = 35.0
TAN = math.tan(math.radians(PITCH))


def rule(t):
    print("\n" + "=" * 72 + "\n" + t + "\n" + "=" * 72)


def check(c, m):
    print(("PASS  " if c else "FAIL  ") + m)
    if not c:
        fails.append(m)


def flat(name, pts, z=3.0):
    """A flat n-gon at height z, the way a generated roof arrives."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([(x, y, z) for x, y in pts], [], [list(range(len(pts)))])
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def roof(ob, **kw):
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.blm.gable_roof(pitch=PITCH, **kw)
    return ob.data


def zs(me):
    return [v.co.z for v in me.vertices]


def open_above_eaves(me, z0=3.0):
    """Edges with only one face, above the eave line.

    The roof is deliberately open along the bottom -- it sits on the walls --
    so an open edge there is expected. An open edge ABOVE the eaves is a hole,
    and the one that matters is where a wide wing meets a narrow one and the
    ridge steps down: without a wall there you can see straight into the roof.
    """
    counts = {}
    for poly in me.polygons:
        for key in poly.edge_keys:
            counts[key] = counts.get(key, 0) + 1
    bad = []
    for (a, b), n in counts.items():
        if n != 1:
            continue
        za, zb = me.vertices[a].co.z, me.vertices[b].co.z
        if za > z0 + 1e-3 and zb > z0 + 1e-3:
            bad.append((round(za, 3), round(zb, 3)))
    return bad


rule("1. RECTANGLE: THE SIMPLE CASE MUST BE EXACTLY RIGHT")
# 12 x 6 at z = 3. Ridge should run along the 12 m side, half-width 3 m,
# so the ridge stands 3 * tan(35) above the eaves.
ob = flat("rect", [(0, 0), (12, 0), (12, 6), (0, 6)])
me = roof(ob)
want_h = 3.0 * TAN
print("faces %d, z range %.3f .. %.3f, expected ridge at %.3f"
      % (len(me.polygons), min(zs(me)), max(zs(me)), 3.0 + want_h))
check(abs(min(zs(me)) - 3.0) < 1e-4, "eaves sit on the wall, at z = 3")
check(abs(max(zs(me)) - (3.0 + want_h)) < 1e-3,
      "ridge height is half-width x tan(pitch)")

ridge_vs = [v.co for v in me.vertices if v.co.z > 3.0 + want_h - 1e-3]
check(len(ridge_vs) == 2, "the ridge is a single line, two vertices")
if len(ridge_vs) == 2:
    d = ridge_vs[1] - ridge_vs[0]
    print("ridge runs %s, length %.2f" % (tuple(round(c, 2) for c in d),
                                          d.length))
    check(abs(d.x) > abs(d.y), "ridge runs along the LONG side")
    check(abs(d.length - 12.0) < 1e-3, "ridge spans the whole length")
    check(all(abs(v.y - 3.0) < 1e-4 for v in ridge_vs),
          "ridge sits down the middle")
check(len(me.polygons) == 4, "two roof planes and two gable ends")

rule("2. THE SAME RECTANGLE, ROTATED 40 DEGREES")
a = math.radians(40.0)
pts = [(12 * math.cos(a) * t - 6 * math.sin(a) * s,
        12 * math.sin(a) * t + 6 * math.cos(a) * s)
       for t, s in ((0, 0), (1, 0), (1, 1), (0, 1))]
ob2 = flat("rot", pts)
me2 = roof(ob2)
check(abs(max(zs(me2)) - (3.0 + want_h)) < 1e-3,
      "rotation does not change the ridge height")
rv = [v.co for v in me2.vertices if v.co.z > 3.0 + want_h - 1e-3]
if len(rv) == 2:
    d = (rv[1] - rv[0]).normalized()
    want = Vector((math.cos(a), math.sin(a), 0.0))
    dot = abs(d.dot(want))
    print("ridge direction dot long axis = %.5f" % dot)
    check(dot > 0.999, "ridge follows the rotated long axis, not world X")

rule("3. L-SHAPED PLAN")
L = [(0, 0), (12, 0), (12, 6), (6, 6), (6, 14), (0, 14)]
ob3 = flat("Lshape", L)
me3 = roof(ob3)
print("faces %d, z range %.3f .. %.3f"
      % (len(me3.polygons), min(zs(me3)), max(zs(me3))))
check(len(me3.polygons) > 4, "the L produced more than a single box roof")
check(abs(min(zs(me3)) - 3.0) < 1e-4, "every eave still sits on the wall")
check(max(zs(me3)) > 3.0 + 1e-3, "the roof actually rises")
check(all(v.co.z >= 3.0 - 1e-4 for v in me3.vertices),
      "nothing dips below the wall (no overhang was asked for)")
# the ridge runs along the 14 m axis, so the cross-section that matters is the
# wide foot of the L: 12 m across, half-width 6, ridge 6 * tan(pitch) up
check(abs(max(zs(me3)) - (3.0 + 6.0 * TAN)) < 1e-3,
      "ridge height follows the widest cross-section, not the bounding box")
# where the 12 m foot meets the 6 m leg the ridge steps down. That step is a
# wall on a real building and a hole in the mesh if it is not built.
holes = open_above_eaves(me3)
print("open edges above the eaves: %d %s" % (len(holes), holes[:4]))
check(not holes, "the step where the wings meet is walled off, not left open")

rule("4. U-SHAPED PLAN: ONE SLAB, TWO SEPARATE RIDGES")
U = [(0, 0), (14, 0), (14, 10), (10, 10), (10, 4), (4, 4), (4, 10), (0, 10)]
ob4 = flat("Ushape", U)
me4 = roof(ob4)
print("faces %d, z range %.3f .. %.3f"
      % (len(me4.polygons), min(zs(me4)), max(zs(me4))))
check(len(me4.polygons) > 6, "the U produced a roof over each arm")
check(abs(min(zs(me4)) - 3.0) < 1e-4, "eaves on the wall")
top = max(zs(me4))
peaks = [v.co for v in me4.vertices if v.co.z > top - 1e-3]
xs = sorted(round(p.x, 2) for p in peaks)
print("highest points at x = %s" % xs)
check(len(peaks) >= 2, "more than one high point: the arms have their own")
check(not open_above_eaves(me4), "the U is closed everywhere above the eaves")

rule("5. A TRIANGLE, AND A PLAN WITH A SLANTED WALL")
tri = flat("tri", [(0, 0), (10, 0), (5, 8)])
me5 = roof(tri)
check(len(me5.polygons) > 0, "a triangular plan produces a roof")
check(abs(min(zs(me5)) - 3.0) < 1e-4, "eaves on the wall")
print("triangle: %d faces, apex %.3f" % (len(me5.polygons), max(zs(me5))))

slant = flat("slant", [(0, 0), (12, 2), (12, 8), (0, 6)])
me6 = roof(slant)
check(len(me6.polygons) > 0, "a plan with no parallel walls produces a roof")
check(abs(min(zs(me6)) - 3.0) < 1e-4, "eaves on the wall")
for label, m in (("rectangle", me), ("rotated", me2), ("triangle", me5),
                 ("slanted", me6)):
    check(not open_above_eaves(m), "%s is closed above the eaves" % label)

rule("6. PITCH, FORCED AXIS AND OVERHANG")
ob7 = flat("steep", [(0, 0), (12, 0), (12, 6), (0, 6)])
bpy.ops.object.select_all(action="DESELECT")
ob7.select_set(True)
bpy.context.view_layer.objects.active = ob7
bpy.ops.blm.gable_roof(pitch=60.0)
h60 = max(zs(ob7.data)) - 3.0
print("pitch 60 gives ridge %.3f, expected %.3f"
      % (h60, 3.0 * math.tan(math.radians(60.0))))
check(abs(h60 - 3.0 * math.tan(math.radians(60.0))) < 1e-3,
      "pitch drives the ridge height")

ob8 = flat("forced", [(0, 0), (12, 0), (12, 6), (0, 6)])
bpy.ops.object.select_all(action="DESELECT")
ob8.select_set(True)
bpy.context.view_layer.objects.active = ob8
bpy.ops.blm.gable_roof(pitch=PITCH, axis="Y")
rv8 = [v.co for v in ob8.data.vertices
       if v.co.z > max(zs(ob8.data)) - 1e-3]
if len(rv8) == 2:
    d = rv8[1] - rv8[0]
    check(abs(d.y) > abs(d.x), "axis=Y forces the ridge across the long side")
    check(abs(max(zs(ob8.data)) - (3.0 + 6.0 * TAN)) < 1e-3,
          "and the ridge is taller, because it now spans the 12 m width")

ob9 = flat("over", [(0, 0), (12, 0), (12, 6), (0, 6)])
bpy.ops.object.select_all(action="DESELECT")
ob9.select_set(True)
bpy.context.view_layer.objects.active = ob9
bpy.ops.blm.gable_roof(pitch=PITCH, overhang=0.5)
lo = min(zs(ob9.data))
print("with 0.5 m overhang the eave drops to %.3f" % lo)
check(lo < 3.0 - 1e-3, "an overhang hangs below the wall top")
ys = [v.co.y for v in ob9.data.vertices]
check(min(ys) < -0.4 and max(ys) > 6.4,
      "and reaches past the wall on both sides")

rule("7. THE RIDGE FOLLOWS THE LONGEST WALL")
# A plan that is not square to its own bounding box. Its longest wall is the
# slanted one, 11.66 m, while the smallest enclosing rectangle is the
# axis-aligned 10 x 9 -- so the two rules genuinely disagree here, which is
# the only way to tell which one is being used.
S = [(0, 0), (10, 0), (10, 3), (0, 9)]
slant = Vector((0 - 10, 9 - 3, 0)).normalized()
u_long, _ = blm.longest_wall_axis(S)
u_box, _ = blm.ridge_axis(S)
print("longest wall %s   bounding box %s"
      % (tuple(round(c, 3) for c in u_long), tuple(round(c, 3) for c in u_box)))
check(abs(Vector((u_long[0], u_long[1], 0.0)).dot(slant)) > 0.999,
      "longest_wall_axis returns the direction of the 11.66 m wall")
check(abs(u_box[0]) > 0.999,
      "ridge_axis still returns the bounding box's long side (X)")
check(abs(u_long[0] - u_box[0]) > 0.1,
      "the two rules really do disagree on this plan")

ob_a = flat("axis_auto", S)
me_a = roof(ob_a)
ob_b = flat("axis_box", S)
bpy.ops.object.select_all(action="DESELECT")
ob_b.select_set(True)
bpy.context.view_layer.objects.active = ob_b
bpy.ops.blm.gable_roof(pitch=PITCH, axis="BOX")
print("default ridge height %.3f, BOX ridge height %.3f"
      % (max(zs(me_a)), max(zs(ob_b.data))))
check(abs(max(zs(me_a)) - max(zs(ob_b.data))) > 1e-3,
      "the default and BOX produce different roofs, so the default is the wall")
check(not open_above_eaves(me_a), "the longest-wall roof is closed")
check(not open_above_eaves(ob_b.data), "the BOX roof is closed")

rule("8. TEXTURE RUNS ACROSS THE WHOLE ROOF")
ob10 = flat("uvroof", [(0, 0), (12, 0), (12, 6), (0, 6)])
bpy.ops.object.select_all(action="DESELECT")
ob10.select_set(True)
bpy.context.view_layer.objects.active = ob10
bpy.ops.blm.gable_roof(pitch=PITCH, tiles_per_m=1.0)
me10 = ob10.data
check(len(me10.uv_layers) == 1, "the roof came with UVs")
if me10.uv_layers:
    uvs = [tuple(d.uv) for d in me10.uv_layers.active.data]
    us = [u for u, _ in uvs]
    print("u spans %.2f .. %.2f over a 12 m roof" % (min(us), max(us)))
    check(max(us) - min(us) > 6.0,
          "UVs run the length of the roof rather than per face")

print("\n" + "=" * 72)
print("FAILED %d" % len(fails) if fails else "ALL PASSED")
for f in fails:
    print("  - " + f)
print("=" * 72)
sys.exit(1 if fails else 0)
