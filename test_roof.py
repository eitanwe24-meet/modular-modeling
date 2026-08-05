"""Build Modular Objects must keep the roof, and must not lose any geometry.

Buildify's flat roof is real mesh geometry on the building object, not an
instance, so a modularize that walks only `depsgraph.object_instances` copies
every wall and pillar and silently drops the roof -- and then hides the
building, taking the roof with it. The building comes out open-topped.

This asserts the whole evaluated building is accounted for afterwards:
instanced polygons plus the building's own polygons, nothing missing.

Run: blender -b buildify_1.0.blend --python test_roof.py
"""
import importlib.util
import sys

import bpy

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


rule("0. GENERATE")
# the 3D cursor in buildify_1.0.blend sits 25 m from the origin, so passing
# location explicitly is not optional -- without it the building is built off
# in space and every positional assertion below reads as a failure
bpy.ops.mesh.primitive_plane_add(size=12.0, location=(0.0, 0.0, 0.0))
plane = bpy.context.active_object
P.build_height = 12.0
bpy.ops.object.buildify_generate()
bpy.context.view_layer.update()

deps = bpy.context.evaluated_depsgraph_get()

inst_polys = 0
for inst in deps.object_instances:
    if (inst.is_instance and inst.parent is not None
            and inst.parent.original == plane
            and inst.object is not None and inst.object.type == "MESH"):
        inst_polys += len(inst.object.data.polygons)

ev = plane.evaluated_get(deps)
own = ev.to_mesh()
own_polys = len(own.polygons)
own_top = max((v.co.z for v in own.vertices), default=0.0)
ev.to_mesh_clear()

print("instanced polys %d / own polys %d (top at z=%.2f)"
      % (inst_polys, own_polys, own_top))
check(inst_polys > 0, "building generated instanced modules")
check(own_polys > 0, "building has non-instanced geometry (the roof)")

rule("1. MODULARIZE")
P.building = plane
bpy.ops.blm.modularize()
col = P.modules_collection
objs = list(col.objects)
made_polys = sum(len(o.data.polygons) for o in objs)

print("%d objects, %d polys (expected %d)"
      % (len(objs), made_polys, inst_polys + own_polys))
check(made_polys == inst_polys + own_polys,
      "no geometry lost: modules account for every evaluated polygon")

rule("2. THE ROOF SURVIVES")
roofs = [o for o in objs if o.name.endswith("_Roof")]
check(len(roofs) == 1, "exactly one roof object was created")
if roofs:
    roof = roofs[0]
    top = max((roof.matrix_world @ v.co).z for v in roof.data.vertices)
    print("roof %r: %d polys, top at z=%.2f"
          % (roof.name, len(roof.data.polygons), top))
    check(len(roof.data.polygons) == own_polys,
          "roof carries all of the non-instanced geometry")
    check(abs(top - own_top) < 1e-4,
          "roof sits at the same height it did before")
    check(blm.is_module(roof), "roof is selectable through the add-on")
    check(roof.get(blm.P_SLOT) == "",
          "roof has no slot: there is no library of roofs to swap it against")
    check(roof.visible_get(), "roof is visible after the building is hidden")

check(plane.hide_get(), "the source building is hidden")

rule("3. THE WALLS STILL WORK")
walls = [o for o in objs if o.get(blm.P_SLOT)]
check(len(walls) > 0, "swappable wall modules exist")
if walls:
    target = walls[0]
    slot = target[blm.P_SLOT]
    cands = blm.assets_in(slot)
    other = next((c for c in cands if c != blm.current_asset(target)), None)
    print("swapping %s (%s): %s -> %s"
          % (target.name, slot, blm.current_asset(target), other))
    if other:
        before = [(o.name, o.data.name) for o in objs if o is not target]
        check(blm.apply_asset(target, other), "swap applied")
        check(blm.current_asset(target) == other, "module now shows the swap")
        after = [(o.name, o.data.name) for o in objs if o is not target]
        check(before == after, "no other module changed")

rule("4. CONVERT TO OBJ IS GONE")
check(not hasattr(bpy.types, "BUILDIFY_OT_convert_obj"),
      "the Convert to OBJ operator is no longer registered")
check(not hasattr(bpy.ops.object, "buildify_convert_obj")
      or "buildify_convert_obj" not in dir(bpy.ops.object),
      "object.buildify_convert_obj cannot be called")

print("\n" + "=" * 72)
print("FAILED %d" % len(fails) if fails else "ALL PASSED")
for f in fails:
    print("  - " + f)
print("=" * 72)
sys.exit(1 if fails else 0)
