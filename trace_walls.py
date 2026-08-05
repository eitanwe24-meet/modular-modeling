import bpy, sys, json
from collections import Counter, defaultdict

target = "Walls"
ng = bpy.data.node_groups[target]

lines = []
def p(s=""):
    lines.append(str(s))

p(f"=== {target}: {len(ng.nodes)} nodes ===")
p()
p("--- NODE TYPE HISTOGRAM ---")
for t, c in Counter(n.bl_idname for n in ng.nodes).most_common():
    p(f"  {c:3}  {t}")

# structural nodes of interest
KEY = ("InstanceOnPoints", "MeshToPoints", "CurveToPoints", "DuplicateElements",
       "RealizeInstances", "RandomValue", "StoreNamedAttribute", "CaptureAttribute",
       "CollectionInfo", "ObjectInfo", "MeshLine", "Grid", "SampleIndex",
       "SetPosition", "TranslateInstances", "RotateInstances", "ScaleInstances",
       "SeparateGeometry", "DeleteGeometry", "Switch", "Index", "ID",
       "AccumulateField", "AttributeStatistic", "SortElements", "Repeat", "ForEach",
       "EdgeVertices", "InputMeshEdgeVertices", "SplineParameter", "ResampleCurve",
       "ExtrudeMesh", "MeshBoolean", "JoinGeometry", "SubdivideMesh", "SetID")

p()
p("--- STRUCTURAL NODES (in dependency order from output) ---")

# build link map
inputs_of = defaultdict(list)   # node -> [(from_node, from_socket, to_socket)]
for l in ng.links:
    inputs_of[l.to_node.name].append((l.from_node, l.from_socket.name, l.to_socket.name))

out_nodes = [n for n in ng.nodes if n.bl_idname == "NodeGroupOutput"]

visited = []
order = []
def walk(n, depth):
    if n.name in visited or depth > 60:
        return
    visited.append(n.name)
    order.append((depth, n))
    for (src, ssock, dsock) in inputs_of[n.name]:
        walk(src, depth + 1)

for o in out_nodes:
    walk(o, 0)

for depth, n in order:
    label = n.label or ""
    extra = ""
    if n.bl_idname == "GeometryNodeCollectionInfo":
        extra = " [collection info]"
    if hasattr(n, "operation"):
        extra += f" op={n.operation}"
    if hasattr(n, "data_type"):
        extra += f" dtype={n.data_type}"
    if hasattr(n, "domain"):
        extra += f" dom={n.domain}"
    if hasattr(n, "mode"):
        extra += f" mode={n.mode}"
    ins = inputs_of[n.name]
    src_desc = ", ".join(f"{s.name}.{ss}->{ds}" for (s, ss, ds) in ins)
    p(f"{'  '*min(depth,20)}{n.bl_idname:38} '{n.name}' {label}{extra}")
    if src_desc:
        p(f"{'  '*min(depth,20)}      <- {src_desc}")

p()
p("--- ALL NODES WITH NON-EMPTY LABELS (author's own annotations) ---")
for n in ng.nodes:
    if n.label:
        p(f"  {n.bl_idname:38} '{n.name}'  LABEL='{n.label}'")

p()
p("--- FRAMES / NOTES ---")
for n in ng.nodes:
    if n.bl_idname == "NodeFrame":
        p(f"  FRAME '{n.name}' label='{n.label}'")
for t in bpy.data.texts:
    p(f"  TEXT DATABLOCK: {t.name} ({len(t.as_string())} chars)")

path = sys.argv[-1]
open(path, "w", encoding="utf-8").write("\n".join(lines))
print("WROTE", path)
