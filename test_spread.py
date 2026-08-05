"""Spread Texture Across Faces: one texture over touching same-material faces.

An asset whose faces each carry the whole image looks like the texture was
scaled per face. Spreading derives every UV from the vertex position, so faces
sharing an edge necessarily share the UV on that edge and the image crosses the
join -- at the density the asset already used.

Run: blender -b --factory-startup --python test_spread.py
"""
import importlib.util
import math
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


def wall(name, n=3, w=1.0, h=2.0, second_material_on_last=False):
    """A run of n quads side by side in the XZ plane, sharing edges.

    Each face is given the whole image, 0-1 -- the "one by one" mapping this
    operator exists to replace.
    """
    me = bpy.data.meshes.new(name)
    verts, faces = [], []
    for i in range(n + 1):
        verts.append((i * w, 0.0, 0.0))
        verts.append((i * w, 0.0, h))
    for i in range(n):
        a = i * 2
        faces.append((a, a + 2, a + 3, a + 1))
    me.from_pydata(verts, [], faces)
    me.update()

    uv = me.uv_layers.new(name="UVMap")
    per_face = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    for poly in me.polygons:
        for k, li in enumerate(poly.loop_indices):
            uv.data[li].uv = per_face[k]

    m1 = bpy.data.materials.new(name + "_brick")
    me.materials.append(m1)
    if second_material_on_last:
        m2 = bpy.data.materials.new(name + "_metal")
        me.materials.append(m2)
        me.polygons[-1].material_index = 1

    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def face_uvs(me):
    return [[tuple(round(c, 5) for c in me.uv_layers.active.data[li].uv)
             for li in p.loop_indices] for p in me.polygons]


def density_of(me, poly):
    """Tiles per metre actually achieved on one face."""
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    f = bm.faces[poly.index]
    ga = f.calc_area()
    ua = blm._uv_area(f, bm.loops.layers.uv.active)
    bm.free()
    return math.sqrt(ua / ga) if ga > 1e-12 else 0.0


rule("1. THE PROBLEM: EACH FACE CARRIES THE WHOLE IMAGE")
ob = wall("wall_a", n=3, w=1.0, h=2.0)
before = face_uvs(ob.data)
d_before = density_of(ob.data, ob.data.polygons[0])
print("face 0 uvs %s" % (before[0],))
print("density before %.4f tiles/m" % d_before)
check(before[0] == before[1] == before[2],
      "every face starts with an identical 0-1 mapping")

rule("2. AFTER SPREADING, THE TEXTURE CROSSES THE JOINS")
bpy.ops.object.select_all(action="DESELECT")
ob.select_set(True)
bpy.context.view_layer.objects.active = ob
bpy.ops.blm.spread_uv()

after = face_uvs(ob.data)
for i, f in enumerate(after):
    print("face %d uvs %s" % (i, f))
check(after[0] != after[1], "faces no longer share one identical mapping")

# faces 0 and 1 share the edge at x = 1.0; the two loops on that edge must
# agree, or the texture restarts at the seam
shared = set(after[0]) & set(after[1])
check(len(shared) == 2,
      "adjacent faces agree on the UVs of the edge they share (%d of 2)"
      % len(shared))
shared12 = set(after[1]) & set(after[2])
check(len(shared12) == 2, "and so do the next pair")

us = [u for f in after for u, _ in f]
print("u spans %.3f .. %.3f across the whole wall" % (min(us), max(us)))
check(max(us) - min(us) > 1.5,
      "the image runs across the wall instead of restarting on each face")

rule("3. THE DENSITY THE FILE ALREADY USED IS KEPT")
d_after = density_of(ob.data, ob.data.polygons[0])
print("density before %.4f, after %.4f tiles/m" % (d_before, d_after))
check(abs(d_after - d_before) < 1e-3,
      "texture is the same size on the geometry as it was in the file")

rule("4. A DIFFERENT MATERIAL IS A DIFFERENT ISLAND")
# Islands cannot be told apart by comparing UV values: every UV comes from the
# vertex position, so a neighbouring island lands on the coordinates it would
# have had anyway. What separates them is that each measures its OWN density --
# so the metal face is given twice the tiling of the brick, and neither may
# drag the other.
ob2 = wall("wall_b", n=3, second_material_on_last=True)
uv2 = ob2.data.uv_layers.active
for li in ob2.data.polygons[-1].loop_indices:
    uv2.data[li].uv = (uv2.data[li].uv[0] * 2.0, uv2.data[li].uv[1] * 2.0)
d_brick_before = density_of(ob2.data, ob2.data.polygons[0])
d_metal_before = density_of(ob2.data, ob2.data.polygons[-1])
print("before: brick %.4f, metal %.4f tiles/m"
      % (d_brick_before, d_metal_before))

bpy.ops.object.select_all(action="DESELECT")
ob2.select_set(True)
bpy.context.view_layer.objects.active = ob2
bpy.ops.blm.spread_uv()

got = face_uvs(ob2.data)
d_brick_after = density_of(ob2.data, ob2.data.polygons[0])
d_metal_after = density_of(ob2.data, ob2.data.polygons[-1])
print("after:  brick %.4f, metal %.4f tiles/m"
      % (d_brick_after, d_metal_after))
check(len(set(got[0]) & set(got[1])) == 2,
      "the two brick faces still share their edge UVs")
check(abs(d_brick_after - d_brick_before) < 1e-3,
      "the brick run kept its own density, undisturbed by the metal face")
check(abs(d_metal_after - d_metal_before) < 1e-3,
      "the metal face kept its own, denser mapping")
check(abs(d_metal_after - d_brick_after) > 1e-3,
      "the two islands were measured separately, not averaged together")

rule("5. AN ASSET WITH NO UVS AT ALL")
ob3 = wall("wall_c", n=2)
while ob3.data.uv_layers:
    ob3.data.uv_layers.remove(ob3.data.uv_layers[0])
bpy.ops.object.select_all(action="DESELECT")
ob3.select_set(True)
bpy.context.view_layer.objects.active = ob3
bpy.ops.blm.spread_uv()
check(len(ob3.data.uv_layers) == 1, "a UV layer was created")
if ob3.data.uv_layers:
    d = density_of(ob3.data, ob3.data.polygons[0])
    print("fallback density %.4f tiles/m" % d)
    check(abs(d - 1.0) < 1e-3, "fell back to one tile per metre")

rule("6. FORCING A DENSITY")
ob4 = wall("wall_d", n=2)
bpy.ops.object.select_all(action="DESELECT")
ob4.select_set(True)
bpy.context.view_layer.objects.active = ob4
bpy.ops.blm.spread_uv(tiles_per_m=2.0)
d = density_of(ob4.data, ob4.data.polygons[0])
print("forced density %.4f tiles/m" % d)
check(abs(d - 2.0) < 1e-3, "tiles_per_m overrides the measured density")

print("\n" + "=" * 72)
print("FAILED %d" % len(fails) if fails else "ALL PASSED")
for f in fails:
    print("  - " + f)
print("=" * 72)
sys.exit(1 if fails else 0)
