bl_info = {
    "name": "Buildify Panel Editor",
    "author": "prototype",
    "version": (0, 2, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > Building",
    "description": "Per-panel asset swapping for Buildify-generated buildings",
    "category": "Object",
}

import bpy
from bpy.props import (BoolProperty, FloatProperty, FloatVectorProperty,
                       IntProperty, PointerProperty, StringProperty)
from bpy_extras import view3d_utils
from mathutils import Vector

ATTR_HOME = "bld_home"
ATTR_CELL = "bld_cell_id"
OV_NAME = "Building_Overrides"
OV_ATTRS = (("ov_asset", "INT"), ("ov_offset", "FLOAT_VECTOR"),
            ("ov_hide", "BOOLEAN"), ("ov_pass", "INT"))

# panel cache: building object name -> list of dicts
_CACHE = {}


# =============================================================================
# node graph injection  (same surgery as build_prototype.py, self-contained)
# =============================================================================
def _sock(node, name, which):
    coll = node.inputs if which == "in" else node.outputs
    hits = [s for s in coll if s.name == name]
    if not hits:
        raise KeyError("%s has no %s socket %r" % (node.bl_idname, which, name))
    for s in hits:
        if s.enabled:
            return s
    return hits[0]


def _new(tree, idname, x, y, label="", **props):
    n = tree.nodes.new(idname)
    n.location = (x, y)
    if label:
        n.label = label
    for k, v in props.items():
        setattr(n, k, v)
    return n


def _link(tree, a, an, b, bn):
    return tree.links.new(_sock(a, an, "out"), _sock(b, bn, "in"))


def _build_lookup(tree, ox, oy):
    obj_info = _new(tree, "GeometryNodeObjectInfo", ox, oy, "override object",
                    transform_space="RELATIVE")
    obj_in = _new(tree, "NodeGroupInput", ox - 260, oy + 180, "object in")
    _link(tree, obj_in, "Override object", obj_info, "Object")

    # passes have non-aligned bays, so restrict to this pass's overrides first
    pass_attr = _new(tree, "GeometryNodeInputNamedAttribute", ox - 260, oy - 340,
                     "ov_pass", data_type="INT")
    pass_attr.inputs["Name"].default_value = "ov_pass"
    pass_in = _new(tree, "NodeGroupInput", ox - 260, oy - 480, "pass in")
    pass_eq = _new(tree, "FunctionNodeCompare", ox - 60, oy - 400, "same pass",
                   data_type="INT", operation="EQUAL")
    _link(tree, pass_attr, "Attribute", pass_eq, "A")
    _link(tree, pass_in, "Pass id", pass_eq, "B")

    sep = _new(tree, "GeometryNodeSeparateGeometry", ox + 60, oy - 160,
               "this pass only", domain="POINT")
    _link(tree, obj_info, "Geometry", sep, "Geometry")
    _link(tree, pass_eq, "Result", sep, "Selection")

    home = _new(tree, "GeometryNodeInputNamedAttribute", ox, oy - 200,
                "panel home", data_type="FLOAT_VECTOR")
    home.inputs["Name"].default_value = ATTR_HOME

    nearest = _new(tree, "GeometryNodeSampleNearest", ox + 220, oy - 60,
                   "nearest override", domain="POINT")
    _link(tree, sep, "Selection", nearest, "Geometry")
    _link(tree, home, "Attribute", nearest, "Sample Position")

    def sample(name, dtype, from_socket=None, attr=None, dy=0):
        si = _new(tree, "GeometryNodeSampleIndex", ox + 440, oy + dy,
                  "sample " + name, data_type=dtype, domain="POINT")
        _link(tree, sep, "Selection", si, "Geometry")
        _link(tree, nearest, "Index", si, "Index")
        if attr:
            na = _new(tree, "GeometryNodeInputNamedAttribute", ox + 220,
                      oy + dy - 120, attr, data_type=dtype)
            na.inputs["Name"].default_value = attr
            _link(tree, na, "Attribute", si, "Value")
        elif from_socket:
            tree.links.new(from_socket, _sock(si, "Value", "in"))
        return si

    pos = _new(tree, "GeometryNodeInputPosition", ox + 220, oy + 120)
    s_pos = sample("pos", "FLOAT_VECTOR", from_socket=pos.outputs["Position"], dy=140)

    dist = _new(tree, "ShaderNodeVectorMath", ox + 660, oy + 140, "distance",
                operation="DISTANCE")
    tree.links.new(_sock(s_pos, "Value", "out"), dist.inputs[0])
    tree.links.new(_sock(home, "Attribute", "out"), dist.inputs[1])

    radius = _new(tree, "NodeGroupInput", ox + 440, oy + 320, "radius in")
    cmp = _new(tree, "FunctionNodeCompare", ox + 860, oy + 140, "within radius",
               data_type="FLOAT", operation="LESS_THAN")
    _link(tree, dist, "Value", cmp, "A")
    _link(tree, radius, "Override radius", cmp, "B")

    enable = _new(tree, "NodeGroupInput", ox + 860, oy + 320, "enable in")
    gate = _new(tree, "FunctionNodeBooleanMath", ox + 1060, oy + 200,
                "has override", operation="AND")
    _link(tree, cmp, "Result", gate, "Boolean")
    tree.links.new(_sock(enable, "Enable overrides", "out"), gate.inputs[1])

    return {
        "has": gate.outputs["Boolean"],
        "asset": sample("asset", "INT", attr="ov_asset", dy=-40).outputs["Value"],
        "offset": sample("offset", "FLOAT_VECTOR", attr="ov_offset", dy=-260).outputs["Value"],
        "hide": sample("hide", "BOOLEAN", attr="ov_hide", dy=-480).outputs["Value"],
        "home": home.outputs["Attribute"],
    }


def _inject(tree):
    names = {i.name for i in tree.interface.items_tree}
    if "Override object" not in names:
        tree.interface.new_socket("Override object", in_out="INPUT",
                                  socket_type="NodeSocketObject")
        s = tree.interface.new_socket("Override radius", in_out="INPUT",
                                      socket_type="NodeSocketFloat")
        s.default_value, s.min_value, s.max_value = 1.2, 0.0, 100.0
        s = tree.interface.new_socket("Enable overrides", in_out="INPUT",
                                      socket_type="NodeSocketBool")
        s.default_value = True
        s = tree.interface.new_socket("Pass id", in_out="INPUT",
                                      socket_type="NodeSocketInt")
        s.default_value, s.min_value, s.max_value = 0, 0, 64

    iop = tree.nodes["Instance on Points"]
    pts_in = _sock(iop, "Points", "in")
    idx_in = _sock(iop, "Instance Index", "in")
    src_points = pts_in.links[0].from_socket
    src_index = idx_in.links[0].from_socket if idx_in.links else None

    bx, by = iop.location.x - 2100, iop.location.y - 900

    pos = _new(tree, "GeometryNodeInputPosition", bx - 200, by - 160)
    store_home = _new(tree, "GeometryNodeStoreNamedAttribute", bx, by,
                      "store home pos", data_type="FLOAT_VECTOR", domain="POINT")
    store_home.inputs["Name"].default_value = ATTR_HOME
    tree.links.new(src_points, _sock(store_home, "Geometry", "in"))
    _link(tree, pos, "Position", store_home, "Value")

    ov = _build_lookup(tree, bx + 300, by - 700)

    hide_and = _new(tree, "FunctionNodeBooleanMath", bx + 1600, by - 220,
                    "hide?", operation="AND")
    tree.links.new(ov["has"], hide_and.inputs[0])
    tree.links.new(ov["hide"], hide_and.inputs[1])

    dele = _new(tree, "GeometryNodeDeleteGeometry", bx + 1780, by, "apply hide",
                domain="POINT", mode="ALL")
    _link(tree, store_home, "Geometry", dele, "Geometry")
    _link(tree, hide_and, "Boolean", dele, "Selection")

    zero = _new(tree, "FunctionNodeInputVector", bx + 1780, by - 400, "zero")
    off_sw = _new(tree, "GeometryNodeSwitch", bx + 1960, by - 320, "offset?",
                  input_type="VECTOR")
    tree.links.new(ov["has"], _sock(off_sw, "Switch", "in"))
    _link(tree, zero, "Vector", off_sw, "False")
    tree.links.new(ov["offset"], _sock(off_sw, "True", "in"))

    setpos = _new(tree, "GeometryNodeSetPosition", bx + 2160, by, "apply offset")
    _link(tree, dele, "Geometry", setpos, "Geometry")
    _link(tree, off_sw, "Output", setpos, "Offset")
    tree.links.new(_sock(setpos, "Geometry", "out"), pts_in)

    if src_index is not None:
        sw = _new(tree, "GeometryNodeSwitch", bx + 2160, by - 560, "asset?",
                  input_type="INT")
        tree.links.new(ov["has"], _sock(sw, "Switch", "in"))
        tree.links.new(src_index, _sock(sw, "False", "in"))
        tree.links.new(ov["asset"], _sock(sw, "True", "in"))
        tree.links.new(_sock(sw, "Output", "out"), idx_in)


# =============================================================================
# override table
# =============================================================================
def get_override_object(scene, create=True):
    ob = bpy.data.objects.get(OV_NAME)
    if ob is None and create:
        me = bpy.data.meshes.new(OV_NAME)
        me.from_pydata([], [], [])
        ob = bpy.data.objects.new(OV_NAME, me)
        scene.collection.objects.link(ob)
        ob.show_in_front = True
        ob.display_type = "WIRE"
    if ob:
        for n, t in OV_ATTRS:
            if n not in ob.data.attributes:
                ob.data.attributes.new(n, t, "POINT")
    return ob


def read_table(ob):
    me = ob.data
    rows = []
    for i, v in enumerate(me.vertices):
        rows.append({
            "co": Vector(v.co),
            "ov_asset": me.attributes["ov_asset"].data[i].value,
            "ov_offset": Vector(me.attributes["ov_offset"].data[i].vector),
            "ov_hide": me.attributes["ov_hide"].data[i].value,
            "ov_pass": me.attributes["ov_pass"].data[i].value,
        })
    return rows


def write_table(ob, rows):
    me = ob.data
    me.clear_geometry()
    me.from_pydata([tuple(r["co"]) for r in rows], [], [])
    for n, t in OV_ATTRS:
        if n not in me.attributes:
            me.attributes.new(n, t, "POINT")
    for i, r in enumerate(rows):
        me.attributes["ov_asset"].data[i].value = int(r["ov_asset"])
        me.attributes["ov_offset"].data[i].vector = tuple(r["ov_offset"])
        me.attributes["ov_hide"].data[i].value = bool(r["ov_hide"])
        me.attributes["ov_pass"].data[i].value = int(r["ov_pass"])
    me.update()
    ob.update_tag()


def find_row(rows, co, pass_id, tol=0.05):
    for i, r in enumerate(rows):
        if r["ov_pass"] == pass_id and (r["co"] - co).length < tol:
            return i
    return -1


# =============================================================================
# panel discovery
# =============================================================================
def pass_map(scene):
    raw = scene.get("bld_pass_map")
    return dict(raw) if raw else {}


def obj_to_pass(scene):
    out = {}
    for cn, pid in pass_map(scene).items():
        col = bpy.data.collections.get(cn)
        if col:
            for o in col.objects:
                out[o.name] = (pid, cn)
    return out


def candidates_for(scene, pass_id):
    """Assets selectable for this pass. Collection Info instances children in
    alphabetical order, so index N here == Instance Index N in the node tree."""
    for cn, pid in pass_map(scene).items():
        if pid == pass_id:
            col = bpy.data.collections.get(cn)
            if col:
                return sorted([o.name for o in col.objects])
    return []


def rebuild_cache(context, building):
    scene = context.scene
    o2p = obj_to_pass(scene)
    context.view_layer.update()
    deps = context.evaluated_depsgraph_get()
    panels = []
    for inst in deps.object_instances:
        if not inst.is_instance or inst.parent is None:
            continue
        if inst.parent.original != building:
            continue
        nm = inst.object.name
        if nm not in o2p:
            continue
        pid, cn = o2p[nm]
        panels.append({
            "co": Vector(inst.matrix_world.translation),
            "asset": nm,
            "pass": pid,
            "collection": cn,
        })
    _CACHE[building.name] = panels
    return panels


def get_cache(context, building):
    return _CACHE.get(building.name) or rebuild_cache(context, building)


def nearest_panel(panels, point, max_dist=1e9):
    best, bd = None, max_dist
    for p in panels:
        d = (p["co"] - point).length
        if d < bd:
            best, bd = p, d
    return best, bd


# =============================================================================
# properties
# =============================================================================
class BPE_Props(bpy.types.PropertyGroup):
    building: PointerProperty(
        type=bpy.types.Object, name="Building",
        description="Object carrying the Buildify 'building' modifier",
        poll=lambda self, o: o.type == "MESH")
    picked: BoolProperty(default=False)
    pick_co: FloatVectorProperty(subtype="XYZ")
    pick_pass: IntProperty(default=0)
    pick_asset: StringProperty(default="")
    radius: FloatProperty(
        name="Bind Radius", default=1.2, min=0.01, max=20.0,
        description="How close an override point must be to claim a panel")
    nudge: FloatVectorProperty(
        name="Offset", subtype="TRANSLATION", size=3, default=(0, 0, 0))


def props(context):
    return context.scene.bpe_props


# =============================================================================
# operators
# =============================================================================
class BPE_OT_append_buildify(bpy.types.Operator):
    """Append a complete Buildify setup (node groups + module assets) from a
    .blend file into this file"""
    bl_idname = "bpe.append_buildify"
    bl_label = "Append Buildify From .blend"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.blend", options={"HIDDEN"})

    def invoke(self, context, event):
        import os
        guess = os.path.join(os.path.expanduser("~"), "Downloads",
                             "buildify_1.0.blend")
        if os.path.exists(guess):
            self.filepath = guess
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        import os
        path = self.filepath
        if not path or not os.path.exists(path):
            self.report({"ERROR"}, "Pick a Buildify .blend file")
            return {"CANCELLED"}

        with bpy.data.libraries.load(path) as (src, _dst):
            objects = list(src.objects)
            groups = list(src.node_groups)

        if "Walls" not in groups and not any(g.startswith("Walls") for g in groups):
            self.report({"ERROR"},
                        "%s has no 'Walls' node group - is this a Buildify file?"
                        % os.path.basename(path))
            return {"CANCELLED"}

        # Appending the demo building object drags in every dependency it needs:
        # all node groups, the module collections and their meshes.
        host = "building_base" if "building_base" in objects else None
        if host:
            bpy.ops.wm.append(filepath=os.path.join(path, "Object", host),
                              directory=os.path.join(path, "Object") + os.sep,
                              filename=host)
            ob = bpy.data.objects.get(host)
            if ob:
                props(context).building = ob
                for o in bpy.context.view_layer.objects:
                    o.select_set(False)
                ob.select_set(True)
                context.view_layer.objects.active = ob
            self.report({"INFO"}, "Appended %s (%d node groups, %d collections)"
                        % (host, len(bpy.data.node_groups),
                           len(bpy.data.collections)))
        else:
            # no demo object - bring the graph and assets across on their own
            with bpy.data.libraries.load(path) as (src, dst):
                dst.node_groups = list(src.node_groups)
                dst.collections = list(src.collections)
            self.report({"WARNING"},
                        "No 'building_base' in that file. Appended node groups "
                        "and collections - add a 'building' Geometry Nodes "
                        "modifier to your own mesh manually.")
        return {"FINISHED"}


class BPE_OT_prepare(bpy.types.Operator):
    """Inject the per-panel override layer into this file's Buildify node groups"""
    bl_idname = "bpe.prepare"
    bl_label = "Prepare Building"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        if any(ng.name.startswith("WallsOV") for ng in bpy.data.node_groups):
            self.report({"INFO"}, "Already prepared")
            return {"CANCELLED"}

        walls = [ng for ng in bpy.data.node_groups if ng.name.startswith("Walls")]
        if not walls:
            self.report({"ERROR"}, "No Buildify 'Walls' node group in this file")
            return {"CANCELLED"}

        copies = {}
        for g in walls:
            c = g.copy()
            c.name = g.name.replace("Walls", "WallsOV")
            c.use_fake_user = True
            copies[g.name] = c
            try:
                _inject(c)
            except Exception as e:
                self.report({"ERROR"}, "Injection failed on %s: %s" % (g.name, e))
                return {"CANCELLED"}

        bld = bpy.data.node_groups.get("building")
        if bld is None:
            self.report({"ERROR"}, "No 'building' node group")
            return {"CANCELLED"}

        for n in bld.nodes:
            if n.bl_idname == "GeometryNodeGroup" and n.node_tree \
                    and n.node_tree.name in copies:
                n.node_tree = copies[n.node_tree.name]

        names = {i.name for i in bld.interface.items_tree}
        if "Override object" not in names:
            bld.interface.new_socket("Override object", in_out="INPUT",
                                     socket_type="NodeSocketObject")
            s = bld.interface.new_socket("Override radius", in_out="INPUT",
                                         socket_type="NodeSocketFloat")
            s.default_value, s.min_value, s.max_value = 1.2, 0.0, 100.0
            s = bld.interface.new_socket("Enable overrides", in_out="INPUT",
                                         socket_type="NodeSocketBool")
            s.default_value = True

        gi = bld.nodes.new("NodeGroupInput")
        gi.location = (-800, -900)
        gi.label = "override controls"

        pmap, pid = {}, 0
        for n in bld.nodes:
            if n.bl_idname == "GeometryNodeGroup" and n.node_tree in copies.values():
                for nm in ("Override object", "Override radius", "Enable overrides"):
                    bld.links.new(_sock(gi, nm, "out"), _sock(n, nm, "in"))
                _sock(n, "Pass id", "in").default_value = pid
                wm = _sock(n, "Wall modules", "in")
                cn = wm.default_value.name if (not wm.links and wm.default_value) else ""
                if cn:
                    pmap[cn] = pid
                pid += 1
        scene["bld_pass_map"] = pmap

        ov = get_override_object(scene)
        p = props(context)
        target = p.building or bpy.data.objects.get("building_base")
        for ob in bpy.data.objects:
            for m in ob.modifiers:
                if m.type == "NODES" and m.node_group is bld:
                    ident = {i.name: i.identifier for i in bld.interface.items_tree
                             if getattr(i, "item_type", "") == "SOCKET"
                             and i.in_out == "INPUT"}
                    m[ident["Override object"]] = ov
                    m[ident["Override radius"]] = p.radius
                    m[ident["Enable overrides"]] = True
                    if target is None:
                        target = ob
        p.building = target
        _CACHE.clear()
        self.report({"INFO"}, "Prepared %d wall pass(es): %s" % (pid, pmap))
        return {"FINISHED"}


class BPE_OT_refresh(bpy.types.Operator):
    """Re-scan the generated building for panels"""
    bl_idname = "bpe.refresh"
    bl_label = "Refresh Panels"

    def execute(self, context):
        p = props(context)
        if not p.building:
            self.report({"ERROR"}, "Set the Building object first")
            return {"CANCELLED"}
        n = len(rebuild_cache(context, p.building))
        self.report({"INFO"}, "%d panels found" % n)
        return {"FINISHED"}


class BPE_OT_pick_cursor(bpy.types.Operator):
    """Select the panel nearest to the 3D cursor"""
    bl_idname = "bpe.pick_cursor"
    bl_label = "Pick Nearest to 3D Cursor"

    def execute(self, context):
        p = props(context)
        if not p.building:
            self.report({"ERROR"}, "Set the Building object first")
            return {"CANCELLED"}
        panels = get_cache(context, p.building)
        if not panels:
            self.report({"ERROR"}, "No panels found - press Refresh")
            return {"CANCELLED"}
        hit, d = nearest_panel(panels, context.scene.cursor.location)
        set_picked(context, hit)
        self.report({"INFO"}, "%s (%.2fm away)" % (hit["asset"], d))
        return {"FINISHED"}


class BPE_OT_pick_click(bpy.types.Operator):
    """Click a panel in the viewport to select it"""
    bl_idname = "bpe.pick_click"
    bl_label = "Pick Panel by Click"

    def invoke(self, context, event):
        p = props(context)
        if not p.building:
            self.report({"ERROR"}, "Set the Building object first")
            return {"CANCELLED"}
        get_cache(context, p.building)
        context.window_manager.modal_handler_add(self)
        context.window.cursor_modal_set("EYEDROPPER")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
            context.window.cursor_modal_restore()
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            context.window.cursor_modal_restore()
            return self.do_pick(context, event)
        return {"RUNNING_MODAL"}

    def do_pick(self, context, event):
        p = props(context)
        region, rv3d = context.region, context.region_data
        coord = (event.mouse_region_x, event.mouse_region_y)
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        deps = context.evaluated_depsgraph_get()
        ok, loc, _n, _i, _o, _m = context.scene.ray_cast(deps, origin, direction)
        if not ok:
            self.report({"WARNING"}, "Nothing under the cursor")
            return {"CANCELLED"}
        panels = get_cache(context, p.building)
        hit, d = nearest_panel(panels, loc)
        if hit is None:
            self.report({"WARNING"}, "No panel near that point")
            return {"CANCELLED"}
        set_picked(context, hit)
        self.report({"INFO"}, "%s (%.2fm from hit)" % (hit["asset"], d))
        return {"FINISHED"}


def set_picked(context, panel):
    p = props(context)
    p.picked = True
    p.pick_co = tuple(panel["co"])
    p.pick_pass = panel["pass"]
    p.pick_asset = panel["asset"]


def apply_override(context, **changes):
    """Create or update the override row for the picked panel."""
    p = props(context)
    scene = context.scene
    ov = get_override_object(scene)
    rows = read_table(ov)
    co = Vector(p.pick_co)
    i = find_row(rows, co, p.pick_pass)
    if i < 0:
        cur = candidates_for(scene, p.pick_pass)
        try:
            cur_idx = cur.index(p.pick_asset)
        except ValueError:
            cur_idx = 0
        rows.append({"co": co, "ov_asset": cur_idx, "ov_offset": Vector((0, 0, 0)),
                     "ov_hide": False, "ov_pass": p.pick_pass})
        i = len(rows) - 1
    rows[i].update(changes)
    write_table(ov, rows)
    if p.building:
        p.building.update_tag()
    context.view_layer.update()
    rebuild_cache(context, p.building)
    return rows[i]


class BPE_OT_set_asset(bpy.types.Operator):
    """Swap this panel to the chosen asset"""
    bl_idname = "bpe.set_asset"
    bl_label = "Swap Asset"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty()

    def execute(self, context):
        p = props(context)
        if not p.picked:
            self.report({"ERROR"}, "Pick a panel first")
            return {"CANCELLED"}
        apply_override(context, ov_asset=self.index, ov_hide=False)
        cands = candidates_for(context.scene, p.pick_pass)
        if 0 <= self.index < len(cands):
            p.pick_asset = cands[self.index]
        return {"FINISHED"}


class BPE_OT_cycle_asset(bpy.types.Operator):
    """Step to the next/previous asset for a head-to-head comparison"""
    bl_idname = "bpe.cycle_asset"
    bl_label = "Cycle Asset"
    bl_options = {"REGISTER", "UNDO"}

    delta: IntProperty(default=1)

    def execute(self, context):
        p = props(context)
        if not p.picked:
            self.report({"ERROR"}, "Pick a panel first")
            return {"CANCELLED"}
        cands = candidates_for(context.scene, p.pick_pass)
        if not cands:
            self.report({"ERROR"}, "No candidate assets for this pass")
            return {"CANCELLED"}
        try:
            cur = cands.index(p.pick_asset)
        except ValueError:
            cur = 0
        nxt = (cur + self.delta) % len(cands)
        apply_override(context, ov_asset=nxt, ov_hide=False)
        p.pick_asset = cands[nxt]
        self.report({"INFO"}, "%s  ->  %s" % (cands[cur], cands[nxt]))
        return {"FINISHED"}


class BPE_OT_set_hide(bpy.types.Operator):
    """Remove this panel from the building"""
    bl_idname = "bpe.set_hide"
    bl_label = "Hide Panel"
    bl_options = {"REGISTER", "UNDO"}

    hide: BoolProperty(default=True)

    def execute(self, context):
        if not props(context).picked:
            return {"CANCELLED"}
        apply_override(context, ov_hide=self.hide)
        return {"FINISHED"}


class BPE_OT_apply_nudge(bpy.types.Operator):
    """Move this panel by the offset above"""
    bl_idname = "bpe.apply_nudge"
    bl_label = "Apply Offset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = props(context)
        if not p.picked:
            return {"CANCELLED"}
        apply_override(context, ov_offset=Vector(p.nudge))
        return {"FINISHED"}


class BPE_OT_clear(bpy.types.Operator):
    """Revert this panel to the procedural result"""
    bl_idname = "bpe.clear"
    bl_label = "Revert to Procedural"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = props(context)
        ov = get_override_object(context.scene, create=False)
        if ov is None or not p.picked:
            return {"CANCELLED"}
        rows = read_table(ov)
        i = find_row(rows, Vector(p.pick_co), p.pick_pass)
        if i < 0:
            self.report({"INFO"}, "No override on this panel")
            return {"CANCELLED"}
        rows.pop(i)
        write_table(ov, rows)
        if p.building:
            p.building.update_tag()
        context.view_layer.update()
        rebuild_cache(context, p.building)
        return {"FINISHED"}


class BPE_OT_clear_all(bpy.types.Operator):
    """Delete every override in this building"""
    bl_idname = "bpe.clear_all"
    bl_label = "Clear All Overrides"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ov = get_override_object(context.scene, create=False)
        if ov:
            write_table(ov, [])
            p = props(context)
            if p.building:
                p.building.update_tag()
            context.view_layer.update()
            rebuild_cache(context, p.building)
        return {"FINISHED"}


# =============================================================================
# UI
# =============================================================================
class BPE_PT_main(bpy.types.Panel):
    bl_label = "Buildify Panel Editor"
    bl_idname = "BPE_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Building"

    def draw(self, context):
        lay = self.layout
        scene = context.scene
        p = props(context)

        has_buildify = any(ng.name.startswith("Walls") for ng in bpy.data.node_groups)
        prepared = any(ng.name.startswith("WallsOV") for ng in bpy.data.node_groups)

        if not has_buildify:
            box = lay.box()
            box.label(text="No Buildify in this file", icon="ERROR")
            col = box.column(align=True)
            col.label(text="This add-on customises Buildify;")
            col.label(text="it doesn't include it. Load it first:")
            box.operator("bpe.append_buildify", icon="APPEND_BLEND")
            box.label(text="(or just open buildify_1.0.blend)", icon="INFO")
            return

        if not prepared:
            box = lay.box()
            box.label(text="Buildify found - not prepared yet", icon="INFO")
            box.operator("bpe.prepare", icon="MODIFIER")
            return

        lay.prop(p, "building")
        row = lay.row(align=True)
        row.operator("bpe.refresh", icon="FILE_REFRESH")
        row.operator("bpe.clear_all", text="", icon="TRASH")

        lay.separator()
        row = lay.row(align=True)
        row.scale_y = 1.3
        row.operator("bpe.pick_click", icon="EYEDROPPER")
        lay.operator("bpe.pick_cursor", icon="CURSOR")

        if not p.picked:
            lay.label(text="No panel selected", icon="INFO")
            return

        lay.separator()
        box = lay.box()
        box.label(text="Selected Panel", icon="MESH_PLANE")
        col = box.column(align=True)
        col.label(text="Asset:  %s" % p.pick_asset)
        col.label(text="Pass:   %d" % p.pick_pass)
        col.label(text="At:     %.1f, %.1f, %.1f" % tuple(p.pick_co))

        # ---- head to head ------------------------------------------------
        cands = candidates_for(scene, p.pick_pass)
        box = lay.box()
        box.label(text="Swap Asset (head to head)", icon="ARROW_LEFTRIGHT")

        row = box.row(align=True)
        row.scale_y = 1.4
        op = row.operator("bpe.cycle_asset", text="", icon="TRIA_LEFT")
        op.delta = -1
        row.label(text=p.pick_asset or "-")
        op = row.operator("bpe.cycle_asset", text="", icon="TRIA_RIGHT")
        op.delta = 1

        col = box.column(align=True)
        for i, name in enumerate(cands):
            r = col.row(align=True)
            r.depress = (name == p.pick_asset)
            o = r.operator("bpe.set_asset", text=name,
                           icon="RADIOBUT_ON" if name == p.pick_asset
                           else "RADIOBUT_OFF")
            o.index = i
        if not cands:
            box.label(text="No assets mapped for this pass", icon="ERROR")

        # ---- other edits --------------------------------------------------
        box = lay.box()
        box.label(text="Adjust", icon="MODIFIER")
        box.prop(p, "nudge")
        box.operator("bpe.apply_nudge", icon="TRANSFORM_ORIGINS")
        row = box.row(align=True)
        o = row.operator("bpe.set_hide", text="Hide", icon="HIDE_ON")
        o.hide = True
        o = row.operator("bpe.set_hide", text="Show", icon="HIDE_OFF")
        o.hide = False
        box.operator("bpe.clear", icon="LOOP_BACK")


CLASSES = (BPE_Props, BPE_OT_append_buildify, BPE_OT_prepare,
           BPE_OT_refresh, BPE_OT_pick_cursor,
           BPE_OT_pick_click, BPE_OT_set_asset, BPE_OT_cycle_asset,
           BPE_OT_set_hide, BPE_OT_apply_nudge, BPE_OT_clear, BPE_OT_clear_all,
           BPE_PT_main)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.bpe_props = PointerProperty(type=BPE_Props)


def unregister():
    del bpy.types.Scene.bpe_props
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
