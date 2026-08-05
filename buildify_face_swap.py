bl_info = {
    "name": "Buildify Face Swap",
    "author": "prototype",
    "version": (0, 3, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > Building",
    "description": "Bake a Buildify building to editable faces, then click any "
                   "face and swap it for another module using visual previews",
    "category": "Object",
}

import json
import bpy
import bmesh
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, IntProperty,
                       PointerProperty, StringProperty)
from mathutils import Matrix, Vector

TABLE_PROP = "bld_panel_table"     # JSON list of panel records on the baked obj
FACE_ATTR = "panel_id"             # int face attribute -> index into that table
BAKED_SUFFIX = "_Editable"


# =============================================================================
# asset discovery
# =============================================================================
def pass_map(scene):
    """collection name -> pass id, written by the prepare step (optional)."""
    raw = scene.get("bld_pass_map")
    return dict(raw) if raw else {}


def module_collections(scene):
    """Every Buildify module collection that holds swappable wall modules.

    Falls back to name sniffing when the file was never 'prepared', so this
    works on a plain Buildify file too.
    """
    pm = pass_map(scene)
    if pm:
        return [cn for cn in pm if cn in bpy.data.collections]
    out = []
    for c in bpy.data.collections:
        n = c.name.lower()
        if ("wall" in n or n == "trim") and any(o.type == "MESH" for o in c.objects):
            out.append(c.name)
    return sorted(out)


def collection_of(obj_name, scene):
    for cn in module_collections(scene):
        col = bpy.data.collections.get(cn)
        if col and obj_name in col.objects:
            return cn
    return ""


def assets_in(cn):
    col = bpy.data.collections.get(cn)
    if not col:
        return []
    return sorted([o.name for o in col.objects if o.type == "MESH"])


def all_module_objects(scene):
    out = []
    for cn in module_collections(scene):
        out.extend(assets_in(cn))
    return out


# =============================================================================
# previews
# =============================================================================
def preview_icon(name):
    """icon_id for an object's preview, or 0 if it has not been rendered yet."""
    ob = bpy.data.objects.get(name)
    if ob is None:
        return 0
    try:
        if ob.preview is None:
            ob.preview_ensure()
        return ob.preview.icon_id or 0
    except Exception:
        return 0


class BFS_OT_gen_previews(bpy.types.Operator):
    """Render thumbnail previews for every module asset

    Needs a GPU context, so it only works in the normal Blender UI"""
    bl_idname = "bfs.gen_previews"
    bl_label = "Generate Asset Previews"

    def execute(self, context):
        n = 0
        for name in all_module_objects(context.scene):
            ob = bpy.data.objects.get(name)
            if ob is None:
                continue
            try:
                if ob.preview is None:
                    ob.preview_ensure()
                with context.temp_override(id=ob):
                    bpy.ops.ed.lib_id_generate_preview()
                n += 1
            except Exception as e:
                self.report({"WARNING"}, "%s: %s" % (name, e))
        self.report({"INFO"}, "Generated %d previews" % n)
        return {"FINISHED"}


# =============================================================================
# bake:  procedural building  ->  real editable mesh + panel table
# =============================================================================
def gather_panels(context, building):
    """One record per generated instance, in depsgraph order."""
    scene = context.scene
    context.view_layer.update()
    deps = context.evaluated_depsgraph_get()
    recs = []
    for inst in deps.object_instances:
        if not inst.is_instance or inst.parent is None:
            continue
        if inst.parent.original != building:
            continue
        src = inst.object
        if src is None or src.type != "MESH":
            continue
        cn = collection_of(src.name, scene)
        recs.append({
            "m": [c for row in inst.matrix_world for c in row],
            "asset": src.name,
            "col": cn,               # "" => not swappable (pillar, roof prop...)
            "orig": src.name,
            "hidden": False,
        })
    return recs


def rec_matrix(rec):
    m = rec["m"]
    return Matrix([m[0:4], m[4:8], m[8:12], m[12:16]])


def build_mesh_from_table(table, name):
    """The baked mesh is a pure function of the table -- swapping an asset is
    just editing one record and rebuilding."""
    verts, faces, pids, mats = [], [], [], []
    mat_index = {}

    for i, rec in enumerate(table):
        if rec.get("hidden"):
            continue
        src = bpy.data.objects.get(rec["asset"])
        if src is None or src.type != "MESH":
            continue
        me = src.data
        M = rec_matrix(rec)
        off = len(verts)
        verts.extend([M @ v.co for v in me.vertices])
        for poly in me.polygons:
            faces.append([off + idx for idx in poly.vertices])
            pids.append(i)
            mat = None
            if poly.material_index < len(src.material_slots):
                mat = src.material_slots[poly.material_index].material
            key = mat.name if mat else ""
            if key not in mat_index:
                mat_index[key] = len(mat_index)
            mats.append(mat_index[key])

    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.update()

    ordered = sorted(mat_index.items(), key=lambda kv: kv[1])
    for key, _ in ordered:
        me.materials.append(bpy.data.materials.get(key) if key else None)
    if len(me.polygons) == len(mats):
        for p, mi in zip(me.polygons, mats):
            p.material_index = mi

    attr = me.attributes.new(FACE_ATTR, "INT", "FACE")
    for d, v in zip(attr.data, pids):
        d.value = v
    return me


def rebuild_baked(obj):
    table = json.loads(obj[TABLE_PROP])
    old = obj.data
    obj.data = build_mesh_from_table(table, old.name + "_r")
    if old.users == 0:
        bpy.data.meshes.remove(old)
    obj.data.name = obj.name
    return obj


class BFS_OT_bake(bpy.types.Operator):
    """Realize the procedural building into a real mesh whose faces you can
    click, keeping a record of which module each face came from"""
    bl_idname = "bfs.bake"
    bl_label = "Bake to Editable Faces"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.bfs_props
        building = p.building
        if building is None:
            self.report({"ERROR"}, "Pick the Building object first")
            return {"CANCELLED"}

        table = gather_panels(context, building)
        if not table:
            self.report({"ERROR"}, "No generated geometry found on %s. Does it "
                                   "have the Buildify modifier?" % building.name)
            return {"CANCELLED"}

        name = building.name + BAKED_SUFFIX
        old = bpy.data.objects.get(name)
        if old:
            bpy.data.objects.remove(old, do_unlink=True)

        me = build_mesh_from_table(table, name)
        ob = bpy.data.objects.new(name, me)
        ob.matrix_world = building.matrix_world.copy()
        context.scene.collection.objects.link(ob)
        ob[TABLE_PROP] = json.dumps(table)

        p.baked = ob
        p.panel_index = -1
        building.hide_set(True)
        for o in context.view_layer.objects:
            o.select_set(False)
        ob.select_set(True)
        context.view_layer.objects.active = ob

        swappable = sum(1 for r in table if r["col"])
        self.report({"INFO"}, "Baked %d faces from %d modules (%d swappable)"
                    % (len(me.polygons), len(table), swappable))
        return {"FINISHED"}


# =============================================================================
# face -> panel
# =============================================================================
def panel_of_active_face(context):
    p = context.scene.bfs_props
    ob = p.baked
    if ob is None or context.mode != "EDIT_MESH" or context.edit_object != ob:
        return -1
    bm = bmesh.from_edit_mesh(ob.data)
    layer = bm.faces.layers.int.get(FACE_ATTR)
    if layer is None:
        return -1
    f = bm.faces.active
    if f is None or not f.select:
        sel = [x for x in bm.faces if x.select]
        if not sel:
            return -1
        f = sel[-1]
    return f[layer]


class BFS_OT_pick_face(bpy.types.Operator):
    """Use the face selected in Edit Mode as the target"""
    bl_idname = "bfs.pick_face"
    bl_label = "Use Selected Face"

    def execute(self, context):
        p = context.scene.bfs_props
        i = panel_of_active_face(context)
        if i < 0:
            self.report({"ERROR"}, "Select a face on the baked object in Edit Mode")
            return {"CANCELLED"}
        p.panel_index = i
        table = json.loads(p.baked[TABLE_PROP])
        rec = table[i]
        self.report({"INFO"}, "Module %d: %s%s"
                    % (i, rec["asset"], "" if rec["col"] else "  (not swappable)"))
        return {"FINISHED"}


class BFS_OT_pick_nearest(bpy.types.Operator):
    """Target the module nearest the 3D cursor (works in Object Mode)"""
    bl_idname = "bfs.pick_nearest"
    bl_label = "Pick Nearest to 3D Cursor"

    def execute(self, context):
        p = context.scene.bfs_props
        if p.baked is None:
            self.report({"ERROR"}, "Bake first")
            return {"CANCELLED"}
        table = json.loads(p.baked[TABLE_PROP])
        cur = context.scene.cursor.location
        best, bd = -1, 1e18
        for i, rec in enumerate(table):
            if not rec["col"]:
                continue
            d = (rec_matrix(rec).translation - cur).length
            if d < bd:
                best, bd = i, d
        if best < 0:
            self.report({"ERROR"}, "No swappable modules")
            return {"CANCELLED"}
        p.panel_index = best
        self.report({"INFO"}, "%s (%.2fm)" % (table[best]["asset"], bd))
        return {"FINISHED"}


# =============================================================================
# swapping
# =============================================================================
class BFS_OT_swap(bpy.types.Operator):
    """Replace the targeted module with this asset"""
    bl_idname = "bfs.swap"
    bl_label = "Swap To This Asset"
    bl_options = {"REGISTER", "UNDO"}

    asset: StringProperty()

    def execute(self, context):
        p = context.scene.bfs_props
        if p.baked is None or p.panel_index < 0:
            self.report({"ERROR"}, "Pick a face first")
            return {"CANCELLED"}
        if bpy.data.objects.get(self.asset) is None:
            self.report({"ERROR"}, "No such asset: %s" % self.asset)
            return {"CANCELLED"}

        was_edit = context.mode == "EDIT_MESH"
        if was_edit:
            bpy.ops.object.mode_set(mode="OBJECT")

        table = json.loads(p.baked[TABLE_PROP])
        old = table[p.panel_index]["asset"]
        table[p.panel_index]["asset"] = self.asset
        table[p.panel_index]["hidden"] = False
        p.baked[TABLE_PROP] = json.dumps(table)
        rebuild_baked(p.baked)

        if was_edit:
            bpy.ops.object.mode_set(mode="EDIT")
        self.report({"INFO"}, "%s  ->  %s" % (old, self.asset))
        return {"FINISHED"}


class BFS_OT_cycle(bpy.types.Operator):
    """Step through the assets in this module's collection, head to head"""
    bl_idname = "bfs.cycle"
    bl_label = "Cycle Asset"
    bl_options = {"REGISTER", "UNDO"}

    delta: IntProperty(default=1)

    def execute(self, context):
        p = context.scene.bfs_props
        if p.baked is None or p.panel_index < 0:
            return {"CANCELLED"}
        table = json.loads(p.baked[TABLE_PROP])
        rec = table[p.panel_index]
        cands = assets_in(rec["col"])
        if len(cands) < 2:
            self.report({"WARNING"}, "Only %d asset in %s"
                        % (len(cands), rec["col"] or "this slot"))
            return {"CANCELLED"}
        try:
            cur = cands.index(rec["asset"])
        except ValueError:
            cur = 0
        return bpy.ops.bfs.swap(asset=cands[(cur + self.delta) % len(cands)])


class BFS_OT_hide(bpy.types.Operator):
    """Delete this module from the building"""
    bl_idname = "bfs.hide"
    bl_label = "Delete Module"
    bl_options = {"REGISTER", "UNDO"}

    hide: BoolProperty(default=True)

    def execute(self, context):
        p = context.scene.bfs_props
        if p.baked is None or p.panel_index < 0:
            return {"CANCELLED"}
        was_edit = context.mode == "EDIT_MESH"
        if was_edit:
            bpy.ops.object.mode_set(mode="OBJECT")
        table = json.loads(p.baked[TABLE_PROP])
        table[p.panel_index]["hidden"] = self.hide
        p.baked[TABLE_PROP] = json.dumps(table)
        rebuild_baked(p.baked)
        if was_edit:
            bpy.ops.object.mode_set(mode="EDIT")
        return {"FINISHED"}


class BFS_OT_revert(bpy.types.Operator):
    """Put the originally generated module back"""
    bl_idname = "bfs.revert"
    bl_label = "Revert This Module"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.bfs_props
        if p.baked is None or p.panel_index < 0:
            return {"CANCELLED"}
        table = json.loads(p.baked[TABLE_PROP])
        table[p.panel_index]["asset"] = table[p.panel_index]["orig"]
        table[p.panel_index]["hidden"] = False
        p.baked[TABLE_PROP] = json.dumps(table)
        rebuild_baked(p.baked)
        return {"FINISHED"}


class BFS_OT_export_obj(bpy.types.Operator):
    """Export the baked building as an .obj"""
    bl_idname = "bfs.export_obj"
    bl_label = "Export OBJ"

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.obj", options={"HIDDEN"})

    def invoke(self, context, event):
        p = context.scene.bfs_props
        self.filepath = (p.baked.name if p.baked else "building") + ".obj"
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        p = context.scene.bfs_props
        if p.baked is None:
            self.report({"ERROR"}, "Bake first")
            return {"CANCELLED"}
        for o in context.view_layer.objects:
            o.select_set(False)
        p.baked.select_set(True)
        context.view_layer.objects.active = p.baked
        bpy.ops.wm.obj_export(filepath=self.filepath, export_selected_objects=True,
                              export_materials=True)
        self.report({"INFO"}, "Exported %s" % self.filepath)
        return {"FINISHED"}


# =============================================================================
# properties / UI
# =============================================================================
class BFS_Props(bpy.types.PropertyGroup):
    building: PointerProperty(
        type=bpy.types.Object, name="Building",
        description="Object carrying the Buildify modifier",
        poll=lambda self, o: o.type == "MESH")
    baked: PointerProperty(
        type=bpy.types.Object, name="Baked",
        poll=lambda self, o: o.type == "MESH")
    panel_index: IntProperty(default=-1)
    thumb_scale: FloatProperty(name="Thumbnail Size", default=4.0, min=1.0, max=10.0)
    columns: IntProperty(name="Columns", default=3, min=1, max=6)


class BFS_PT_main(bpy.types.Panel):
    bl_label = "Buildify Face Swap"
    bl_idname = "BFS_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Building"

    def draw(self, context):
        lay = self.layout
        scene = context.scene
        p = scene.bfs_props

        cols = module_collections(scene)
        if not cols:
            box = lay.box()
            box.label(text="No Buildify module collections", icon="ERROR")
            box.label(text="Open or append a Buildify file first.")
            return

        # ---- step 1 -------------------------------------------------------
        box = lay.box()
        box.label(text="1. Bake", icon="MOD_BUILD")
        box.prop(p, "building")
        box.operator("bfs.bake", icon="MESH_DATA")
        if p.baked:
            box.label(text="Baked: %s (%d faces)"
                      % (p.baked.name, len(p.baked.data.polygons)), icon="CHECKMARK")

        if p.baked is None:
            return

        # ---- step 2 -------------------------------------------------------
        box = lay.box()
        box.label(text="2. Pick a Face", icon="FACESEL")
        if context.mode == "EDIT_MESH" and context.edit_object == p.baked:
            box.operator("bfs.pick_face", icon="RESTRICT_SELECT_OFF")
        else:
            box.label(text="Tab into Edit Mode on the baked object,")
            box.label(text="click a face, then press the button.")
            box.operator("bfs.pick_face", icon="RESTRICT_SELECT_OFF")
        box.operator("bfs.pick_nearest", icon="CURSOR")

        if p.panel_index < 0:
            lay.label(text="No module targeted yet", icon="INFO")
            return

        try:
            table = json.loads(p.baked[TABLE_PROP])
            rec = table[p.panel_index]
        except Exception:
            lay.label(text="Panel table missing - re-bake", icon="ERROR")
            return

        box = lay.box()
        col = box.column(align=True)
        col.label(text="Module #%d" % p.panel_index, icon="MESH_PLANE")
        col.label(text="Current:  %s" % rec["asset"])
        col.label(text="Slot:     %s" % (rec["col"] or "not swappable"))
        if rec["asset"] != rec["orig"]:
            col.label(text="Was:      %s" % rec["orig"], icon="LOOP_BACK")

        if not rec["col"]:
            box.label(text="This is a pillar/prop, not a wall module.",
                      icon="INFO")
            return

        # ---- step 3: the asset picker --------------------------------------
        cands = assets_in(rec["col"])
        box = lay.box()
        row = box.row(align=True)
        row.label(text="3. Choose Asset", icon="ASSET_MANAGER")
        row.prop(p, "thumb_scale", text="")
        row.prop(p, "columns", text="")

        have_previews = any(preview_icon(c) for c in cands)
        if not have_previews:
            box.operator("bfs.gen_previews", icon="RENDER_RESULT")

        row = box.row(align=True)
        row.scale_y = 1.3
        row.operator("bfs.cycle", text="", icon="TRIA_LEFT").delta = -1
        row.label(text=rec["asset"])
        row.operator("bfs.cycle", text="", icon="TRIA_RIGHT").delta = 1

        grid = box.grid_flow(row_major=True, columns=p.columns,
                             even_columns=True, even_rows=False, align=False)
        for name in cands:
            cell = grid.column(align=True)
            cell.alert = (name == rec["asset"])
            icon_id = preview_icon(name)
            if icon_id:
                cell.template_icon(icon_value=icon_id, scale=p.thumb_scale)
            else:
                sub = cell.box()
                sub.scale_y = max(1.0, p.thumb_scale * 0.6)
                sub.label(text="", icon="MESH_PLANE")
            short = name.replace(rec["col"].rstrip("s") + "_", "").replace("_", " ")
            op = cell.operator("bfs.swap", text=short,
                               depress=(name == rec["asset"]))
            op.asset = name

        # ---- step 4 -------------------------------------------------------
        box = lay.box()
        box.label(text="4. Other Edits", icon="MODIFIER")
        r = box.row(align=True)
        r.operator("bfs.hide", text="Delete", icon="TRASH").hide = True
        r.operator("bfs.hide", text="Restore", icon="RECOVER_LAST").hide = False
        box.operator("bfs.revert", icon="LOOP_BACK")
        box.operator("bfs.export_obj", icon="EXPORT")


CLASSES = (BFS_Props, BFS_OT_gen_previews, BFS_OT_bake, BFS_OT_pick_face,
           BFS_OT_pick_nearest, BFS_OT_swap, BFS_OT_cycle, BFS_OT_hide,
           BFS_OT_revert, BFS_OT_export_obj, BFS_PT_main)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.bfs_props = PointerProperty(type=BFS_Props)


def unregister():
    del bpy.types.Scene.bfs_props
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
