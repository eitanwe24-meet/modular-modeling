"""A textured .obj must keep its UVs when it comes in as a library asset.

mesh_from_objects rebuilds the merged mesh with from_pydata, which carries
vertices and faces and nothing else. Loop data has to be copied by hand or it
is silently gone -- and an asset that loses its UVs does not read as
"untextured", it reads as "the texture changed scale", because every face then
samples the same corner of the image. That is a slow bug to recognise, so it
is pinned here.

Run: blender -b --factory-startup --python test_uv.py
"""
import importlib.util
import os
import sys
import tempfile

import bpy

ADDON = r"C:\Users\User\Desktop\BuildingGen\buildify_modular.py"
spec = importlib.util.spec_from_file_location("blm_mod", ADDON)
blm = importlib.util.module_from_spec(spec)
sys.modules["blm_mod"] = blm
spec.loader.exec_module(blm)
blm.register()

fails = []
TMP = tempfile.gettempdir()


def rule(t):
    print("\n" + "=" * 72 + "\n" + t + "\n" + "=" * 72)


def check(c, m):
    print(("PASS  " if c else "FAIL  ") + m)
    if not c:
        fails.append(m)


def uv_multiset(me):
    """Every UV coordinate, order-independent -- face order may legitimately
    differ between a plain import and a merged one."""
    if not me.uv_layers:
        return []
    return sorted((round(d.uv[0], 5), round(d.uv[1], 5))
                  for d in me.uv_layers.active.data)


def author_asset(name, uv_scale=1.0, second_layer=False):
    """A UV-mapped cube exported to .obj, the way a user's asset arrives."""
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0.0, 0.0, 0.0))
    ob = bpy.context.active_object
    ob.name = name
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")
    if uv_scale != 1.0:
        for d in ob.data.uv_layers.active.data:
            d.uv = (d.uv[0] * uv_scale, d.uv[1] * uv_scale)
    if second_layer:
        ob.data.uv_layers.new(name="second")
    mat = bpy.data.materials.new(name + "_mat")
    mat.use_nodes = True
    ob.data.materials.append(mat)

    path = os.path.join(TMP, name + ".obj")
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True,
                          export_uv=True, export_materials=True)
    return ob, path


rule("1. A TEXTURED ASSET KEEPS ITS UVS")
src, path = author_asset("uv_asset", uv_scale=1.0)
want = uv_multiset(src.data)
n_loops = len(src.data.uv_layers.active.data)
print("authored: %d uv layers, %d loops" % (len(src.data.uv_layers), n_loops))
bpy.data.objects.remove(src, do_unlink=True)

ob, note = blm.import_asset_file(path, fit="WIDTH", slot_h=3.0)
check(ob is not None, "asset imported (%s)" % note)
if ob:
    check(len(ob.data.uv_layers) >= 1, "asset has a UV layer")
    got = uv_multiset(ob.data)
    check(len(got) == len(want), "every loop kept a UV (%d of %d)"
          % (len(got), len(want)))
    check(got == want, "UV coordinates are unchanged, value for value")
    check(len(ob.data.materials) >= 1, "material survived")

rule("2. SLOT-FITTING MUST NOT TOUCH THE UVS")
# fitting scales geometry into the 3 m slot. That is a transform on the
# vertices; if it ever reached the UVs the texture really would rescale.
src2, path2 = author_asset("uv_big", uv_scale=1.0)
src2.data.transform(blm.Matrix.Diagonal((4.0, 4.0, 4.0, 1.0)))
bpy.ops.wm.obj_export(filepath=path2, export_selected_objects=True,
                      export_uv=True, export_materials=True)
want2 = uv_multiset(src2.data)
bpy.data.objects.remove(src2, do_unlink=True)

ob2, note2 = blm.import_asset_file(path2, fit="WIDTH", slot_h=3.0)
check(ob2 is not None, "oversized asset imported (%s)" % note2)
if ob2:
    w = max(v.co.x for v in ob2.data.vertices) - min(v.co.x
                                                     for v in ob2.data.vertices)
    print("fitted width %.3f m, note: %s" % (w, note2))
    check(abs(w - 3.0) < 1e-3, "geometry was scaled to the 3 m slot")
    check(uv_multiset(ob2.data) == want2,
          "UVs did NOT scale with the geometry")

rule("3. SEVERAL UV LAYERS, AND OBJECTS THAT HAVE NONE")
src3, path3 = author_asset("uv_two", second_layer=True)
names = [l.name for l in src3.data.uv_layers]
print("authored layers: %s" % names)
bpy.data.objects.remove(src3, do_unlink=True)
ob3, _ = blm.import_asset_file(path3, fit="WIDTH", slot_h=3.0)
if ob3:
    got_names = [l.name for l in ob3.data.uv_layers]
    print("imported layers: %s" % got_names)
    check(len(got_names) >= 1, "at least the active UV layer came through")

# a merge where one object carries UVs and the other does not: the loops still
# have to line up, or the UVs land on the wrong faces
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
plain = bpy.context.active_object
while plain.data.uv_layers:
    plain.data.uv_layers.remove(plain.data.uv_layers[0])
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(3.0, 0.0, 0.0))
mapped = bpy.context.active_object

# removing a UV layer does not tag the object, so without this the depsgraph
# hands back the mesh as it was BEFORE the removal -- the "unmapped" cube
# arrives still carrying UVMap and the padding path is never exercised
plain.update_tag()
mapped.update_tag()
bpy.context.view_layer.update()
deps = bpy.context.evaluated_depsgraph_get()
merged = blm.mesh_from_objects([plain, mapped], deps, "merged")
check(len(merged.uv_layers) >= 1, "merged mesh has a UV layer")
if merged.uv_layers:
    check(len(merged.uv_layers.active.data) == len(merged.loops),
          "UV data covers every loop of the merged mesh (%d)" % len(merged.loops))
    nonzero = sum(1 for d in merged.uv_layers.active.data
                  if d.uv[0] or d.uv[1])
    print("loops with a real UV: %d of %d" % (nonzero, len(merged.loops)))
    check(0 < nonzero < len(merged.loops),
          "the mapped object kept its UVs and the unmapped one is padded")

print("\n" + "=" * 72)
print("FAILED %d" % len(fails) if fails else "ALL PASSED")
for f in fails:
    print("  - " + f)
print("=" * 72)
sys.exit(1 if fails else 0)
