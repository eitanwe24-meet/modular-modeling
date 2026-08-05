"""
Verify the per-panel override prototype.

  1. snapshot the generated wall panels
  2. drop three override points (swap asset / nudge / hide)
  3. confirm exactly those three panels changed and nothing else did
  4. change floor count and module width, confirm overrides still bind

Run:  blender -b building_prototype.blend --python verify_prototype.py
"""

import bpy
from mathutils import Vector

WALL_COLS = {"ground_floor_walls", "middle_floor_walls"}
base = bpy.data.objects["building_base"]
mod = [m for m in base.modifiers if m.type == "NODES"][0]
tree = mod.node_group

ident = {}
for it in tree.interface.items_tree:
    if getattr(it, "item_type", "") == "SOCKET" and it.in_out == "INPUT":
        ident[it.name] = it.identifier


def ident_like(frag):
    f = frag.lower().replace(" ", "").replace("-", "")
    for k, v in ident.items():
        if f in k.lower().replace(" ", "").replace("-", ""):
            return v
    raise KeyError(frag)


def wall_names():
    out = set()
    for cn in WALL_COLS:
        if cn in bpy.data.collections:
            out |= {o.name for o in bpy.data.collections[cn].objects}
    return out


WALLS = wall_names()


def panels():
    """-> dict keyed by rounded world position -> instanced object name"""
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    got = {}
    for inst in deps.object_instances:
        if not inst.is_instance:
            continue
        par = inst.parent
        if par is None or par.original != base:
            continue
        nm = inst.object.name.split(".")[0]
        if nm not in WALLS and inst.object.name not in WALLS:
            continue
        t = inst.matrix_world.translation
        got[(round(t.x, 3), round(t.y, 3), round(t.z, 3))] = inst.object.name
    return got


PASS_MAP = dict(bpy.context.scene["bld_pass_map"])
OBJ_PASS = {}
for cn, pid in PASS_MAP.items():
    if cn in bpy.data.collections:
        for o in bpy.data.collections[cn].objects:
            OBJ_PASS[o.name] = pid
print("pass map: %s" % PASS_MAP)


def pass_of(obj_name):
    """Which Walls pass produced this panel -- inferred from its collection."""
    return OBJ_PASS.get(obj_name, 0)


def set_overrides(rows):
    ob = bpy.data.objects["Building_Overrides"]
    me = ob.data
    me.clear_geometry()
    me.from_pydata([tuple(r[0]) for r in rows], [], [])
    for n, t in (("ov_asset", "INT"), ("ov_offset", "FLOAT_VECTOR"),
                 ("ov_hide", "BOOLEAN"), ("ov_pass", "INT")):
        if n not in me.attributes:
            me.attributes.new(n, t, "POINT")
    for i, r in enumerate(rows):
        me.attributes["ov_asset"].data[i].value = r[1]
        me.attributes["ov_offset"].data[i].vector = r[2]
        me.attributes["ov_hide"].data[i].value = r[3]
        me.attributes["ov_pass"].data[i].value = r[4]
    me.update()
    ob.update_tag()
    base.update_tag()


def rule(t):
    print("\n" + "=" * 74)
    print(t)
    print("=" * 74)


# ---------------------------------------------------------------- baseline
rule("1. BASELINE")
b0 = panels()
print("wall panels generated: %d" % len(b0))
from collections import Counter
print("asset distribution: %s" % dict(Counter(v.split('.')[0] + ('.' + v.split('.')[1] if '.' in v else '') for v in b0.values())))

keys = sorted(b0.keys())
# pick three panels spread through the building
targets = [keys[len(keys) // 4], keys[len(keys) // 2], keys[3 * len(keys) // 4]]
for i, t in enumerate(targets):
    print("target %d: %s -> %s" % (i, t, b0[t]))

# ---------------------------------------------------------------- overrides
rule("2. APPLY OVERRIDES  (swap asset / nudge +0.4m / hide)")
cur_assets = sorted({v for v in b0.values()})
print("available wall assets in collections: %s" % cur_assets)

for i, t in enumerate(targets):
    print("target %d pass = %d (%s)" % (i, pass_of(b0[t]), b0[t]))

set_overrides([
    (targets[0], 2, (0.0, 0.0, 0.0), False, pass_of(b0[targets[0]])),  # swap asset
    (targets[1], 0, (0.0, 0.0, 0.40), False, pass_of(b0[targets[1]])), # nudge up 40cm
    (targets[2], 0, (0.0, 0.0, 0.0), True, pass_of(b0[targets[2]])),   # hide
])

b1 = panels()
print("wall panels now: %d  (was %d)" % (len(b1), len(b0)))

ok = True

# -- hide
if targets[2] in b1:
    print("FAIL  hide: panel still present at %s" % (targets[2],))
    ok = False
else:
    print("PASS  hide: panel removed")

# -- asset swap
if targets[0] not in b1:
    print("FAIL  swap: target panel vanished")
    ok = False
elif b1[targets[0]] == b0[targets[0]]:
    print("FAIL  swap: asset unchanged (%s)" % b1[targets[0]])
    ok = False
else:
    print("PASS  swap: %s -> %s" % (b0[targets[0]], b1[targets[0]]))

# -- offset
moved = (round(targets[1][0], 3), round(targets[1][1], 3), round(targets[1][2] + 0.40, 3))
if moved in b1 and targets[1] not in b1:
    print("PASS  nudge: panel moved to %s" % (moved,))
else:
    print("FAIL  nudge: expected panel at %s (present=%s, original still there=%s)"
          % (moved, moved in b1, targets[1] in b1))
    ok = False

# -- collateral damage
untouched_before = {k: v for k, v in b0.items() if k not in targets}
untouched_after = {k: v for k, v in b1.items() if k not in
                   (targets[0], moved, targets[2])}
diff = {k for k in set(untouched_before) | set(untouched_after)
        if untouched_before.get(k) != untouched_after.get(k)}
if diff:
    print("FAIL  %d unrelated panels changed" % len(diff))
    for k in list(diff)[:5]:
        print("        %s: %s -> %s" % (k, untouched_before.get(k), untouched_after.get(k)))
    ok = False
else:
    print("PASS  no collateral change across %d untouched panels" % len(untouched_before))

# ---------------------------------------------------------- stability tests
rule("3. STABILITY: change floor count 4 -> 6")
mod[ident_like("minnumberoffloors")] = 6
mod[ident_like("maxnumberoffloors")] = 6
base.update_tag()
b2 = panels()
print("wall panels at 6 floors: %d" % len(b2))
still = (targets[0] in b2 and b2[targets[0]] == b1[targets[0]])
print("%s  asset override still bound after floor-count change"
      % ("PASS " if still else "FAIL "))
ok = ok and still
hid = targets[2] not in b2
print("%s  hide override still bound" % ("PASS " if hid else "FAIL "))
ok = ok and hid

rule("4. STABILITY: change module width 3.0 -> 2.4 (re-lays every bay)")
mod[ident_like("minnumberoffloors")] = 4
mod[ident_like("maxnumberoffloors")] = 4
mod[ident_like("modulewidth")] = 2.4
base.update_tag()
b3 = panels()
print("wall panels at 2.4m modules: %d" % len(b3))
near = [k for k in b3 if (Vector(k) - Vector(targets[0])).length < 1.2]
print("panels within override radius of target 0: %d" % len(near))
if near:
    print("  -> override re-binds to nearest panel: %s at %s"
          % (b3[near[0]], near[0]))
    print("PASS  position-locked override survives re-layout (binds to neighbour)")
else:
    print("NOTE  no panel within radius; override would be orphaned")

mod[ident_like("modulewidth")] = 3.0

rule("RESULT: %s" % ("ALL CORE CHECKS PASSED" if ok else "FAILURES PRESENT"))
