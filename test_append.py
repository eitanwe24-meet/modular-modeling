"""Empty file -> bpe.append_buildify -> bpe.prepare -> swap an asset."""
import bpy, sys, importlib.util
from collections import Counter

bpy.ops.wm.read_factory_settings(use_empty=True)

ADDON = r"C:\Users\User\Desktop\BuildingGen\buildify_panel_editor.py"
spec = importlib.util.spec_from_file_location("bpe_mod", ADDON)
bpe = importlib.util.module_from_spec(spec)
sys.modules["bpe_mod"] = bpe
spec.loader.exec_module(bpe)
bpe.register()

fails = []


def check(c, m):
    print(("PASS  " if c else "FAIL  ") + m)
    if not c:
        fails.append(m)


print("empty scene: node_groups=%d" % len(bpy.data.node_groups))
check(not any(g.name.startswith("Walls") for g in bpy.data.node_groups),
      "starts with no Buildify (reproduces the reported error)")

try:
    r = bpy.ops.bpe.prepare()
    refused = "CANCELLED" in r
    msg = str(r)
except RuntimeError as e:
    # reporting {'ERROR'} makes bpy.ops raise when driven from a script;
    # in the UI this is just a red toast + CANCELLED
    refused, msg = True, str(e)
print("prepare on empty file -> %s" % msg)
check(refused, "prepare refuses cleanly when Buildify is absent")

print("\n-- append --")
r = bpy.ops.bpe.append_buildify(filepath=r"C:\Users\User\Downloads\buildify_1.0.blend")
print("append ->", r)
check("FINISHED" in r, "append_buildify succeeded")
check(any(g.name.startswith("Walls") for g in bpy.data.node_groups),
      "Walls node group now present")
check(bpy.data.objects.get("building_base") is not None, "building_base appended")
print("collections: %d   objects: %d   node_groups: %d"
      % (len(bpy.data.collections), len(bpy.data.objects),
         len(bpy.data.node_groups)))

P = bpy.context.scene.bpe_props
check(P.building is not None and P.building.name == "building_base",
      "Building field auto-filled")

print("\n-- prepare --")
r = bpy.ops.bpe.prepare()
print("prepare ->", r)
check("FINISHED" in r, "prepare succeeded after append")
print("pass map:", dict(bpy.context.scene.get("bld_pass_map", {})))

print("\n-- use it --")
panels = bpe.rebuild_cache(bpy.context, P.building)
check(len(panels) > 50, "%d panels discovered" % len(panels))

multi = [p for p in panels if len(bpe.candidates_for(bpy.context.scene, p["pass"])) > 1]
t = sorted(multi, key=lambda p: tuple(p["co"]))[len(multi) // 2]
bpy.context.scene.cursor.location = t["co"]
bpy.ops.bpe.pick_cursor()
before = P.pick_asset
bpy.ops.bpe.cycle_asset(delta=1)
after = P.pick_asset
now = {tuple(round(c, 3) for c in p["co"]): p["asset"]
       for p in bpe.rebuild_cache(bpy.context, P.building)}
rendered = now.get(tuple(round(c, 3) for c in t["co"]))
print("%s -> %s (rendered: %s)" % (before, after, rendered))
check(rendered == after and after != before, "asset swap works end to end")

print("\nRESULT: %s" % ("ALL PASSED" if not fails else "%d FAILURE(S)" % len(fails)))
for f in fails:
    print("  -", f)
