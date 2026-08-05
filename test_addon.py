import bpy, sys, importlib.util
from mathutils import Vector

ADDON = r"C:\Users\User\Desktop\BuildingGen\buildify_panel_editor.py"
spec = importlib.util.spec_from_file_location("bpe_mod", ADDON)
bpe = importlib.util.module_from_spec(spec)
sys.modules["bpe_mod"] = bpe
spec.loader.exec_module(bpe)
bpe.register()

scene = bpy.context.scene
P = scene.bpe_props
fails = []


def rule(t):
    print("\n" + "=" * 72 + "\n" + t + "\n" + "=" * 72)


def check(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        fails.append(msg)


def panels():
    return bpe.rebuild_cache(bpy.context, P.building)


def asset_at(co, tol=0.05):
    for p in panels():
        if (p["co"] - Vector(co)).length < tol:
            return p["asset"]
    return None


rule("1. PREPARE")
r = bpy.ops.bpe.prepare()
print("prepare ->", r)
check("FINISHED" in r, "prepare succeeded")
print("pass map:", dict(scene["bld_pass_map"]))
P.building = bpy.data.objects["building_base"]

mod = [m for m in P.building.modifiers if m.type == "NODES"][0]
ng = mod.node_group
ident = {i.name: i.identifier for i in ng.interface.items_tree
         if getattr(i, "item_type", "") == "SOCKET" and i.in_out == "INPUT"}
for k in ("Min number of floors", "Max number of floors"):
    mod[ident[k]] = 4
# writing a modifier input does not tag the object; without this the first
# evaluation is stale and every later snapshot disagrees with the baseline
P.building.update_tag()
bpy.context.view_layer.update()

rule("2. DISCOVER PANELS")
base = panels()
print("panels found:", len(base))
check(len(base) > 50, "panel discovery works")
from collections import Counter
print("by pass:", dict(Counter(p["pass"] for p in base)))
print("by asset:", dict(Counter(p["asset"] for p in base)))

baseline = {tuple(round(c, 3) for c in p["co"]): p["asset"] for p in base}

rule("3. PICK A PANEL (nearest to 3D cursor)")
target = sorted(base, key=lambda p: (p["pass"], tuple(p["co"])))[len(base) // 2]
scene.cursor.location = target["co"]
bpy.ops.bpe.pick_cursor()
print("picked: %s  pass=%d  at %s" % (P.pick_asset, P.pick_pass,
                                      tuple(round(c, 2) for c in P.pick_co)))
check(P.picked, "panel picked")
check(P.pick_asset == target["asset"], "picked the expected panel")

cands = bpe.candidates_for(scene, P.pick_pass)
print("candidates for pass %d: %s" % (P.pick_pass, cands))
check(len(cands) > 1, "more than one candidate asset available")

rule("4. HEAD-TO-HEAD SWAP  (cycle >)")
before = asset_at(target["co"])
bpy.ops.bpe.cycle_asset(delta=1)
after = asset_at(target["co"])
print("%s  ->  %s" % (before, after))
check(after is not None and after != before, "cycling swapped the asset")
check(after == P.pick_asset, "UI label matches what actually rendered")

rule("5. DIRECT PICK BY INDEX")
want = 0 if cands.index(P.pick_asset) != 0 else 1
bpy.ops.bpe.set_asset(index=want)
got = asset_at(target["co"])
print("requested index %d (%s) -> rendered %s" % (want, cands[want], got))
check(got == cands[want], "set_asset selects the right asset")

rule("6. NO COLLATERAL DAMAGE")
now = {tuple(round(c, 3) for c in p["co"]): p["asset"] for p in panels()}
tkey = tuple(round(c, 3) for c in target["co"])
diff = [k for k in set(baseline) | set(now)
        if k != tkey and baseline.get(k) != now.get(k)]
print("panels changed besides the target: %d" % len(diff))
for k in diff[:5]:
    print("   ", k, baseline.get(k), "->", now.get(k))
check(not diff, "only the targeted panel changed")

rule("7. HIDE / SHOW")
bpy.ops.bpe.set_hide(hide=True)
check(asset_at(target["co"]) is None, "hide removes the panel")
bpy.ops.bpe.set_hide(hide=False)
check(asset_at(target["co"]) is not None, "show brings it back")

rule("8. REVERT TO PROCEDURAL")
bpy.ops.bpe.clear()
check(asset_at(target["co"]) == baseline[tkey],
      "revert restores the original procedural asset")
ovobj = bpy.data.objects[bpe.OV_NAME]
check(len(ovobj.data.vertices) == 0, "override row deleted")

rule("9. MULTI-PANEL EDIT")
picks = []
# only passes with >1 candidate can actually swap (pass 2 'trim' has one asset)
multi = [p for p in base if len(bpe.candidates_for(scene, p["pass"])) > 1]
for p in sorted(multi, key=lambda p: tuple(p["co"]))[::17][:5]:
    scene.cursor.location = p["co"]
    bpy.ops.bpe.pick_cursor()
    bpy.ops.bpe.cycle_asset(delta=1)
    picks.append((p["co"], p["asset"], P.pick_asset))
print("edited %d panels" % len(picks))
ok = True
for co, was, now_name in picks:
    got = asset_at(co)
    if got != now_name:
        print("   MISMATCH at %s: expected %s got %s" % (tuple(co), now_name, got))
        ok = False
check(ok, "all %d independent edits held simultaneously" % len(picks))
print("override table rows:", len(bpy.data.objects[bpe.OV_NAME].data.vertices))

rule("RESULT: %s" % ("ALL PASSED" if not fails else "%d FAILURE(S)" % len(fails)))
for f in fails:
    print("  -", f)

bpy.ops.wm.save_as_mainfile(
    filepath=r"C:\Users\User\Desktop\BuildingGen\panel_editor_demo.blend")
print("saved panel_editor_demo.blend")
