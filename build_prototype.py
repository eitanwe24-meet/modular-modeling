"""
Buildify per-panel override prototype.

Retrofits Buildify 1.0's `Walls` node group with a per-panel override layer:
  * every wall panel records its home position in a named attribute `bld_home`
  * an external "override" mesh is sampled per panel (nearest point within a radius)
  * a matched panel can swap asset, be nudged, or be hidden -- unmatched panels
    fall through to Buildify's original random behaviour untouched

Run:  blender -b buildify_1.0.blend --python build_prototype.py -- <out.blend>
"""

import bpy, sys, os

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[-1:]
OUT = argv[0]
STAGE = int(argv[1]) if len(argv) > 1 else 5
RADIUS_DEFAULT = 1.2          # metres; module width is 3.0
ATTR_HOME = "bld_home"        # panel home position (pre-offset)
ATTR_CELL = "bld_cell_id"     # debug/index-locked id

log = []
def p(s):
    log.append(str(s))
    print(s)


# ----------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------
def sock(node, name, which):
    """Resolve a socket by name, preferring the *enabled* one.

    Typed nodes (Switch, Sample Index, Compare, Store Named Attribute) carry one
    hidden socket per data type, all sharing a name; only the active variant is
    enabled. Vector Math instead has several same-named sockets all enabled, so
    callers must index those positionally.
    """
    coll = node.inputs if which == "in" else node.outputs
    hits = [s for s in coll if s.name == name]
    if not hits:
        raise KeyError("%s has no %s socket %r (has: %s)"
                       % (node.bl_idname, which, name, [s.name for s in coll]))
    for s in hits:
        if s.enabled:
            return s
    return hits[0]


def new(tree, idname, x, y, label="", **props):
    n = tree.nodes.new(idname)
    n.location = (x, y)
    if label:
        n.label = label
    for k, v in props.items():
        setattr(n, k, v)
    return n


def link(tree, a, aname, b, bname):
    return tree.links.new(sock(a, aname, "out"), sock(b, bname, "in"))


def require(tree, name):
    if name not in tree.nodes:
        raise KeyError("node %r missing from %r" % (name, tree.name))
    return tree.nodes[name]


# ----------------------------------------------------------------------------
# the override lookup sub-graph
# ----------------------------------------------------------------------------
def build_lookup(tree, ox, oy):
    """Emit the override sampling nodes. Returns dict of output sockets."""

    obj_info = new(tree, "GeometryNodeObjectInfo", ox, oy, "override object",
                   transform_space="RELATIVE")
    obj_in = new(tree, "NodeGroupInput", ox - 260, oy + 180, "object in")
    link(tree, obj_in, "Override object", obj_info, "Object")

    # Ground-floor and middle-floor are separate Walls passes whose bays do not
    # line up, so panels from different passes can sit <0.4m apart. A purely
    # positional lookup captures the wrong one. Restrict each pass to the
    # override points tagged for it before doing any nearest-point search.
    pass_attr = new(tree, "GeometryNodeInputNamedAttribute", ox - 260, oy - 340,
                    "ov_pass", data_type="INT")
    pass_attr.inputs["Name"].default_value = "ov_pass"
    pass_in = new(tree, "NodeGroupInput", ox - 260, oy - 480, "pass in")
    pass_eq = new(tree, "FunctionNodeCompare", ox - 60, oy - 400, "same pass",
                  data_type="INT", operation="EQUAL")
    link(tree, pass_attr, "Attribute", pass_eq, "A")
    link(tree, pass_in, "Pass id", pass_eq, "B")

    sep = new(tree, "GeometryNodeSeparateGeometry", ox + 60, oy - 160,
              "this pass only", domain="POINT")
    link(tree, obj_info, "Geometry", sep, "Geometry")
    link(tree, pass_eq, "Result", sep, "Selection")

    # 'home' = the panel's original position, stored before any offset is applied
    home = new(tree, "GeometryNodeInputNamedAttribute", ox, oy - 200,
               "panel home", data_type="FLOAT_VECTOR")
    home.inputs["Name"].default_value = ATTR_HOME

    # nearest override point to this panel
    nearest = new(tree, "GeometryNodeSampleNearest", ox + 220, oy - 60,
                  "nearest override", domain="POINT")
    link(tree, sep, "Selection", nearest, "Geometry")
    link(tree, home, "Attribute", nearest, "Sample Position")

    def sample(name, data_type, value_socket_from=None, const_name=None, dy=0):
        si = new(tree, "GeometryNodeSampleIndex", ox + 440, oy + dy,
                 "sample " + name, data_type=data_type, domain="POINT")
        link(tree, sep, "Selection", si, "Geometry")
        link(tree, nearest, "Index", si, "Index")
        if const_name:
            na = new(tree, "GeometryNodeInputNamedAttribute", ox + 220, oy + dy - 120,
                     const_name, data_type=data_type)
            na.inputs["Name"].default_value = const_name
            link(tree, na, "Attribute", si, "Value")
        elif value_socket_from:
            tree.links.new(value_socket_from, sock(si, "Value", "in"))
        return si

    # position of that override point -> distance gate
    pos = new(tree, "GeometryNodeInputPosition", ox + 220, oy + 120)
    s_pos = sample("pos", "FLOAT_VECTOR", value_socket_from=pos.outputs["Position"], dy=140)

    dist = new(tree, "ShaderNodeVectorMath", ox + 660, oy + 140, "distance",
               operation="DISTANCE")
    tree.links.new(sock(s_pos, "Value", "out"), dist.inputs[0])
    tree.links.new(sock(home, "Attribute", "out"), dist.inputs[1])

    radius = new(tree, "NodeGroupInput", ox + 440, oy + 320, "radius in")

    cmp = new(tree, "FunctionNodeCompare", ox + 860, oy + 140, "within radius",
              data_type="FLOAT", operation="LESS_THAN")
    link(tree, dist, "Value", cmp, "A")
    link(tree, radius, "Override radius", cmp, "B")

    enable = new(tree, "NodeGroupInput", ox + 860, oy + 320, "enable in")
    gate = new(tree, "FunctionNodeBooleanMath", ox + 1060, oy + 200, "has override",
               operation="AND")
    link(tree, cmp, "Result", gate, "Boolean")
    tree.links.new(sock(enable, "Enable overrides", "out"), gate.inputs[1])

    s_asset = sample("asset", "INT", const_name="ov_asset", dy=-40)
    s_off = sample("offset", "FLOAT_VECTOR", const_name="ov_offset", dy=-260)
    s_hide = sample("hide", "BOOLEAN", const_name="ov_hide", dy=-480)

    return {
        "has": gate.outputs["Boolean"],
        "asset": s_asset.outputs["Value"],
        "offset": s_off.outputs["Value"],
        "hide": s_hide.outputs["Value"],
        "home": home.outputs["Attribute"],
    }


# ----------------------------------------------------------------------------
# inject into one copy of `Walls`
# ----------------------------------------------------------------------------
def inject(tree, stage=5):
    """stage 1=home attr, 2=+cell id, 3=+hide, 4=+offset, 5=+asset swap"""
    p("  injecting into %r (%d nodes) stage=%d" % (tree.name, len(tree.nodes), stage))

    # --- new group inputs -------------------------------------------------
    existing = {i.name for i in tree.interface.items_tree}
    if "Override object" not in existing:
        tree.interface.new_socket("Override object", in_out="INPUT",
                                  socket_type="NodeSocketObject")
        s = tree.interface.new_socket("Override radius", in_out="INPUT",
                                      socket_type="NodeSocketFloat")
        s.default_value, s.min_value, s.max_value = RADIUS_DEFAULT, 0.0, 100.0
        s = tree.interface.new_socket("Enable overrides", in_out="INPUT",
                                      socket_type="NodeSocketBool")
        s.default_value = True
        s = tree.interface.new_socket("Pass id", in_out="INPUT",
                                      socket_type="NodeSocketInt")
        s.default_value, s.min_value, s.max_value = 0, 0, 64

    iop = require(tree, "Instance on Points")           # main wall instancer
    pts_in = sock(iop, "Points", "in")
    idx_in = sock(iop, "Instance Index", "in")

    if not pts_in.links:
        raise RuntimeError("Instance on Points.Points is unconnected")
    src_points = pts_in.links[0].from_socket
    src_index = idx_in.links[0].from_socket if idx_in.links else None
    p("    points  <- %s" % src_points.node.name)
    p("    index   <- %s" % (src_index.node.name if src_index else "(unconnected)"))

    bx, by = iop.location.x - 2100, iop.location.y - 900

    # --- 1. record home position -----------------------------------------
    pos = new(tree, "GeometryNodeInputPosition", bx - 200, by - 160)
    store_home = new(tree, "GeometryNodeStoreNamedAttribute", bx, by,
                     "store home pos", data_type="FLOAT_VECTOR", domain="POINT")
    store_home.inputs["Name"].default_value = ATTR_HOME
    tree.links.new(src_points, sock(store_home, "Geometry", "in"))
    link(tree, pos, "Position", store_home, "Value")

    tail = store_home          # geometry chain tail so far

    if stage <= 1:
        tree.links.new(sock(tail, "Geometry", "out"), pts_in)
        p("    -> stage 1 only (%d nodes)" % len(tree.nodes))
        return

    # --- 2. lookup --------------------------------------------------------
    ov = build_lookup(tree, bx + 300, by - 700)

    # --- 3. debug cell id (index-locked): floor(ID) + quantised home ------
    # Buildify's Set ID leaves ID == floor index at this point in the graph.
    fid = new(tree, "GeometryNodeInputID", bx + 200, by + 320)
    qx = new(tree, "ShaderNodeVectorMath", bx + 380, by + 220, "quantise",
             operation="SCALE")
    tree.links.new(ov["home"], qx.inputs[0])
    qx.inputs["Scale"].default_value = 4.0
    snapv = new(tree, "ShaderNodeVectorMath", bx + 560, by + 220, "snap",
                operation="SNAP")
    tree.links.new(sock(qx, "Vector", "out"), snapv.inputs[0])
    snapv.inputs[1].default_value = (1.0, 1.0, 1.0)
    sep = new(tree, "ShaderNodeSeparateXYZ", bx + 740, by + 220)
    link(tree, snapv, "Vector", sep, "Vector")
    m1 = new(tree, "ShaderNodeMath", bx + 900, by + 300, "x*73", operation="MULTIPLY")
    link(tree, sep, "X", m1, "Value")
    m1.inputs[1].default_value = 73.0
    m2 = new(tree, "ShaderNodeMath", bx + 900, by + 140, "y*179", operation="MULTIPLY")
    link(tree, sep, "Y", m2, "Value")
    m2.inputs[1].default_value = 179.0
    a1 = new(tree, "ShaderNodeMath", bx + 1060, by + 220, "", operation="ADD")
    link(tree, m1, "Value", a1, "Value")
    tree.links.new(sock(m2, "Value", "out"), a1.inputs[1])
    m3 = new(tree, "ShaderNodeMath", bx + 1060, by + 60, "floor*1013",
             operation="MULTIPLY")
    link(tree, fid, "ID", m3, "Value")
    m3.inputs[1].default_value = 1013.0
    a2 = new(tree, "ShaderNodeMath", bx + 1220, by + 160, "cell id", operation="ADD")
    link(tree, a1, "Value", a2, "Value")
    tree.links.new(sock(m3, "Value", "out"), a2.inputs[1])

    store_cell = new(tree, "GeometryNodeStoreNamedAttribute", bx + 1400, by,
                     "store cell id", data_type="INT", domain="POINT")
    store_cell.inputs["Name"].default_value = ATTR_CELL
    link(tree, store_home, "Geometry", store_cell, "Geometry")
    link(tree, a2, "Value", store_cell, "Value")
    tail = store_cell

    if stage <= 2:
        tree.links.new(sock(tail, "Geometry", "out"), pts_in)
        p("    -> stage 2 (%d nodes)" % len(tree.nodes))
        return

    # --- 4. hide matched panels ------------------------------------------
    hide_and = new(tree, "FunctionNodeBooleanMath", bx + 1600, by - 220,
                   "hide?", operation="AND")
    tree.links.new(ov["has"], hide_and.inputs[0])
    tree.links.new(ov["hide"], hide_and.inputs[1])

    dele = new(tree, "GeometryNodeDeleteGeometry", bx + 1780, by,
               "apply hide", domain="POINT", mode="ALL")
    link(tree, store_cell, "Geometry", dele, "Geometry")
    link(tree, hide_and, "Boolean", dele, "Selection")
    tail = dele

    if stage <= 3:
        tree.links.new(sock(tail, "Geometry", "out"), pts_in)
        p("    -> stage 3 (%d nodes)" % len(tree.nodes))
        return

    # --- 5. apply positional offset --------------------------------------
    zero = new(tree, "FunctionNodeInputVector", bx + 1780, by - 400, "zero")
    off_sw = new(tree, "GeometryNodeSwitch", bx + 1960, by - 320, "offset?",
                 input_type="VECTOR")
    tree.links.new(ov["has"], sock(off_sw, "Switch", "in"))
    link(tree, zero, "Vector", off_sw, "False")
    tree.links.new(ov["offset"], sock(off_sw, "True", "in"))

    setpos = new(tree, "GeometryNodeSetPosition", bx + 2160, by, "apply offset")
    link(tree, dele, "Geometry", setpos, "Geometry")
    link(tree, off_sw, "Output", setpos, "Offset")

    tree.links.new(sock(setpos, "Geometry", "out"), pts_in)

    if stage <= 4:
        p("    -> stage 4 (%d nodes)" % len(tree.nodes))
        return

    # --- 6. swap the asset index -----------------------------------------
    if src_index is not None:
        idx_sw = new(tree, "GeometryNodeSwitch", bx + 2160, by - 560, "asset?",
                     input_type="INT")
        tree.links.new(ov["has"], sock(idx_sw, "Switch", "in"))
        tree.links.new(src_index, sock(idx_sw, "False", "in"))
        tree.links.new(ov["asset"], sock(idx_sw, "True", "in"))
        tree.links.new(sock(idx_sw, "Output", "out"), idx_in)

    p("    -> %d nodes after injection" % len(tree.nodes))


def store_home_out(n):
    return n


# ----------------------------------------------------------------------------
# override object
# ----------------------------------------------------------------------------
def make_override_object(name="Building_Overrides"):
    me = bpy.data.meshes.new(name)
    me.from_pydata([], [], [])
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    me.attributes.new("ov_asset", "INT", "POINT")
    me.attributes.new("ov_offset", "FLOAT_VECTOR", "POINT")
    me.attributes.new("ov_hide", "BOOLEAN", "POINT")
    me.attributes.new("ov_pass", "INT", "POINT")
    ob.show_in_front = True
    ob.display_type = "WIRE"
    return ob


def set_overrides(ob, rows):
    """rows: list of (position, asset_index, offset, hide)"""
    me = ob.data
    me.clear_geometry()
    me.from_pydata([r[0] for r in rows], [], [])
    for n, t, d in (("ov_asset", "INT", "POINT"),
                    ("ov_offset", "FLOAT_VECTOR", "POINT"),
                    ("ov_hide", "BOOLEAN", "POINT")):
        if n not in me.attributes:
            me.attributes.new(n, t, d)
    a = me.attributes["ov_asset"].data
    o = me.attributes["ov_offset"].data
    h = me.attributes["ov_hide"].data
    for i, r in enumerate(rows):
        a[i].value = r[1]
        o[i].vector = r[2]
        h[i].value = r[3]
    me.update()


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
p("=== Buildify override prototype ===")
p("blender %s" % bpy.app.version_string)

wall_groups = [ng for ng in bpy.data.node_groups if ng.name.startswith("Walls")]
p("found wall groups: %s" % [g.name for g in wall_groups])

copies = {}
for g in wall_groups:
    c = g.copy()
    c.name = g.name.replace("Walls", "WallsOV")
    c.use_fake_user = True
    copies[g.name] = c
    inject(c, STAGE)

# swap inside `building`
bld = bpy.data.node_groups["building"]
swapped = 0
for n in bld.nodes:
    if n.bl_idname == "GeometryNodeGroup" and n.node_tree and n.node_tree.name in copies:
        n.node_tree = copies[n.node_tree.name]
        swapped += 1
p("swapped %d Walls instances inside `building`" % swapped)

# expose override controls on `building` and wire them through
names = {i.name for i in bld.interface.items_tree}
if "Override object" not in names:
    bld.interface.new_socket("Override object", in_out="INPUT",
                             socket_type="NodeSocketObject")
    s = bld.interface.new_socket("Override radius", in_out="INPUT",
                                 socket_type="NodeSocketFloat")
    s.default_value, s.min_value, s.max_value = RADIUS_DEFAULT, 0.0, 100.0
    s = bld.interface.new_socket("Enable overrides", in_out="INPUT",
                                 socket_type="NodeSocketBool")
    s.default_value = True

gi = bld.nodes.new("NodeGroupInput")
gi.location = (-800, -900)
gi.label = "override controls"

# Each Walls pass gets its own id so overrides can't leak between passes whose
# bays don't align. Record which module collection each pass draws from -- the
# addon uses this to infer a clicked panel's pass from its source collection.
pass_map = {}
pid = 0
for n in bld.nodes:
    if n.bl_idname == "GeometryNodeGroup" and n.node_tree in copies.values():
        for nm in ("Override object", "Override radius", "Enable overrides"):
            bld.links.new(sock(gi, nm, "out"), sock(n, nm, "in"))
        sock(n, "Pass id", "in").default_value = pid
        wm = sock(n, "Wall modules", "in")
        col = wm.default_value.name if (not wm.links and wm.default_value) else \
            ("<linked:%s>" % wm.links[0].from_node.name if wm.links else "<unset>")
        pass_map[col] = pid
        p("  pass %d  <- wall modules: %s  (node %r)" % (pid, col, n.name))
        pid += 1
bpy.context.scene["bld_pass_map"] = pass_map

ov_obj = make_override_object()
p("created %r" % ov_obj.name)

# point the modifier at it
base = bpy.data.objects["building_base"]
mod = [m for m in base.modifiers if m.type == "NODES"][0]
ident = {}
for it in bld.interface.items_tree:
    if getattr(it, "item_type", "") == "SOCKET" and it.in_out == "INPUT":
        ident[it.name] = it.identifier
mod[ident["Override object"]] = ov_obj
mod[ident["Override radius"]] = RADIUS_DEFAULT
mod[ident["Enable overrides"]] = True
p("modifier wired: Override object=%s" % ov_obj.name)

# deterministic base so the prototype is reproducible
# (Buildify's socket names carry stray whitespace, so match loosely)
def ident_like(frag):
    frag = frag.lower().replace(" ", "").replace("-", "")
    for k, v in ident.items():
        if frag in k.lower().replace(" ", "").replace("-", ""):
            return v
    raise KeyError("no input socket matching %r in %s" % (frag, list(ident)))

# NB: leave "Randomize floor numbers" ON. With it off Buildify expects a floor
# count attribute from BLOSM/ADE on the base mesh; without one it yields zero
# floors and no walls at all. Min==Max gives determinism instead.
mod[ident_like("randomizefloornum")] = True
mod[ident_like("minnumberoffloors")] = 4
mod[ident_like("maxnumberoffloors")] = 4

bpy.ops.wm.save_as_mainfile(filepath=OUT)
p("saved %s" % OUT)
