import bpy, sys, json
from collections import Counter

out = {}

# --- node groups overview ---
groups = [ng for ng in bpy.data.node_groups]
out["blend_version"] = bpy.app.version_string
out["num_node_groups"] = len(groups)

ginfo = []
for ng in groups:
    types = Counter(n.bl_idname for n in ng.nodes)
    # interface (4.x uses interface.items_tree)
    ins, outs = [], []
    try:
        for it in ng.interface.items_tree:
            if getattr(it, "item_type", "") == "SOCKET":
                rec = {
                    "name": it.name,
                    "socket": it.socket_type,
                    "in_out": it.in_out,
                }
                for attr in ("default_value", "min_value", "max_value", "subtype"):
                    if hasattr(it, attr):
                        v = getattr(it, attr)
                        try:
                            json.dumps(v)
                            rec[attr] = v
                        except TypeError:
                            rec[attr] = list(v) if hasattr(v, "__len__") else str(v)
                (ins if it.in_out == "INPUT" else outs).append(rec)
            else:
                (ins).append({"panel": it.name})
    except Exception as e:
        ins.append({"error": str(e)})

    ginfo.append({
        "name": ng.name,
        "type": ng.bl_idname,
        "users": ng.users,
        "fake_user": ng.use_fake_user,
        "num_nodes": len(ng.nodes),
        "node_type_histogram": dict(types.most_common()),
        "inputs": ins,
        "outputs": outs,
        "child_groups": sorted({n.node_tree.name for n in ng.nodes
                                if n.bl_idname == "GeometryNodeGroup" and n.node_tree}),
    })

ginfo.sort(key=lambda g: -g["num_nodes"])
out["node_groups"] = ginfo

# --- objects & their modifiers ---
objs = []
for ob in bpy.data.objects:
    mods = []
    for m in ob.modifiers:
        rec = {"name": m.name, "type": m.type}
        if m.type == "NODES" and m.node_group:
            rec["node_group"] = m.node_group.name
            vals = {}
            try:
                for it in m.node_group.interface.items_tree:
                    if getattr(it, "item_type", "") == "SOCKET" and it.in_out == "INPUT":
                        key = it.identifier
                        if key in m:
                            v = m[key]
                            try:
                                json.dumps(v)
                            except TypeError:
                                v = str(v)
                            vals[it.name] = v
            except Exception as e:
                vals["error"] = str(e)
            rec["modifier_values"] = vals
        mods.append(rec)
    objs.append({
        "name": ob.name,
        "type": ob.type,
        "collections": [c.name for c in ob.users_collection],
        "modifiers": mods,
        "verts": len(ob.data.vertices) if ob.type == "MESH" else None,
        "attributes": [ {"name": a.name, "domain": a.domain, "type": a.data_type}
                        for a in (ob.data.attributes if ob.type == "MESH" else []) ],
    })
out["objects"] = objs

# --- collections (asset libraries) ---
cols = []
for c in bpy.data.collections:
    cols.append({
        "name": c.name,
        "num_objects": len(c.objects),
        "object_names": [o.name for o in c.objects][:25],
        "children": [ch.name for ch in c.children],
    })
out["collections"] = cols

path = sys.argv[-1]
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1)
print("WROTE", path)
