bl_info = {
    "name": "Buildify Modular",
    "author": "prototype",
    "version": (0, 4, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > Building",
    "description": "Explode a Buildify building into individually selectable "
                   "module objects, then swap any of them from a visual library",
    "category": "Object",
}

import math

import bmesh
import bpy
from bpy.props import (BoolProperty, FloatProperty, IntProperty,
                       PointerProperty, StringProperty)
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

P_SLOT = "bld_slot"      # which module collection this object may draw from
P_ORIG = "bld_orig"      # what Buildify originally generated here
P_ASSET = "bld_asset"    # which asset it currently uses
P_MOD = "bld_module"     # marker: this object is a swappable module
MODULES_SUFFIX = "_Modules"
COLLECTION_ME = "lib_middle_eastern"
W_HALF = 1.5             # module slots are 3 m wide
GRID_COLUMNS = 2         # asset thumbnail grid, fixed
THUMB_SCALE = 4.0        # asset thumbnail size, fixed


# =============================================================================
# library discovery
# =============================================================================
def folder_library_names(scene):
    """Collection names for the sections of the configured asset folder."""
    p = getattr(scene, "blm_props", None)
    if p is None or not p.asset_folder:
        return []
    root = p.asset_folder
    return [folder_collection_name(root, s) for s in sections_in(root)]


def library_collections(scene):
    """Collections offered in the Library dropdown.

    When an asset folder is configured, its sections ARE the libraries -- the
    in-file collections (Buildify's, or one built by Create Library) are not
    mixed in, otherwise the dropdown lists the same assets twice under
    different names. Untick "Folder Only" to fall back to in-file collections.
    """
    p = getattr(scene, "blm_props", None)
    if p is None or getattr(p, "folder_only", True):
        names = [c for c in folder_library_names(scene)
                 if c in bpy.data.collections]
        if names:
            return names
    return all_asset_collections(scene)


def all_asset_collections(scene):
    """Every collection that could hold modules, folder-backed or in-file.

    Used to identify where a placed module came from, which must keep working
    even when the dropdown is restricted to folder sections.

    Uses the pass map written by an earlier 'prepare' step when present,
    otherwise sniffs collection names so a plain Buildify file works too.
    Override by setting scene['bld_library'] to a list of collection names --
    that is the hook for a custom library later.
    """
    found = []

    def add(name):
        if name in bpy.data.collections and name not in found:
            found.append(name)

    # explicitly registered libraries first -- these are additive, not a
    # replacement, so a custom library sits alongside Buildify's rather than
    # hiding it (which would leave every generated module unswappable)
    for name in list(scene.get("bld_library", [])):
        add(name)

    pm = scene.get("bld_pass_map")
    if pm:
        for name in dict(pm):
            add(name)

    sniffed = []
    for c in bpy.data.collections:
        n = c.name.lower()
        if c.name.endswith(MODULES_SUFFIX):
            continue
        if ("wall" in n or "trim" in n or "pillar" in n) and \
                any(o.type == "MESH" for o in c.objects):
            sniffed.append(c.name)
    for name in sorted(sniffed):
        add(name)

    return found


def assets_in(cn):
    col = bpy.data.collections.get(cn)
    if not col:
        return []
    return sorted([o.name for o in col.objects if o.type == "MESH"])


def asset_label(obj_name):
    """Display name for an asset.

    Blender appends .001 when an imported asset's name is already taken (very
    likely when the source .blend also holds an object of that name), so show
    the file it came from rather than the mangled datablock name.
    """
    import os
    ob = bpy.data.objects.get(obj_name)
    src = ob.get(P_SRC) if ob else None
    if src:
        return os.path.splitext(os.path.basename(src))[0]
    return obj_name


def slot_of(obj_name, scene):
    """Which collection an asset belongs to.

    Checks the dropdown's libraries first, then every other module collection,
    so a module generated from a Buildify collection still reports its origin
    when the dropdown is restricted to folder sections.
    """
    for names in (library_collections(scene), all_asset_collections(scene)):
        for cn in names:
            col = bpy.data.collections.get(cn)
            if col and obj_name in col.objects:
                return cn
    return ""


def all_library_objects(scene):
    out = []
    for cn in library_collections(scene):
        out.extend(assets_in(cn))
    return out


def is_module(ob):
    return bool(ob) and ob.type == "MESH" and ob.get(P_MOD)


def current_asset(ob):
    """Which library asset this module is showing.

    Buildify's meshes are named 'Cube.006' etc, so object.data.name tells you
    nothing -- the asset name is tracked on the object instead, with a data
    comparison as fallback for objects made before this was recorded.
    """
    name = ob.get(P_ASSET)
    if name and name in bpy.data.objects:
        return name
    for cand in assets_in(ob.get(P_SLOT, "")):
        a = bpy.data.objects.get(cand)
        if a and a.data is ob.data:
            return cand
    return ob.data.name


def selected_modules(context):
    mods = [o for o in context.selected_objects if is_module(o)]
    act = context.active_object
    if is_module(act) and act not in mods:
        mods.append(act)
    return mods


# =============================================================================
# previews
# =============================================================================
def preview_icon(name):
    ob = bpy.data.objects.get(name)
    if ob is None:
        return 0
    try:
        if ob.preview is None:
            ob.preview_ensure()
        return ob.preview.icon_id or 0
    except Exception:
        return 0


class BLM_OT_gen_previews(bpy.types.Operator):
    """Render thumbnails for every library asset (needs the Blender UI)"""
    bl_idname = "blm.gen_previews"
    bl_label = "Generate Asset Previews"

    def execute(self, context):
        if bpy.app.background:
            self.report({"WARNING"}, "Preview rendering needs the Blender UI")
            return {"CANCELLED"}
        n = 0
        for name in all_library_objects(context.scene):
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
# build:  procedural building  ->  one real object per module
# =============================================================================
def apply_asset(ob, asset_name):
    """Repoint a module object at a different asset, keeping its transform."""
    src = bpy.data.objects.get(asset_name)
    if src is None or src.type != "MESH":
        return False
    ob.data = src.data
    ob[P_ASSET] = asset_name
    # materials linked to the object rather than the mesh must be copied over
    for i, slot in enumerate(ob.material_slots):
        if i < len(src.material_slots):
            ssl = src.material_slots[i]
            slot.link = ssl.link
            if ssl.link == "OBJECT":
                slot.material = ssl.material
    return True


class BLM_OT_modularize(bpy.types.Operator):
    """Turn the generated building into one selectable object per module"""
    bl_idname = "blm.modularize"
    bl_label = "Build Modular Objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        p = scene.blm_props
        building = p.building
        if building is None:
            self.report({"ERROR"}, "Pick the Building object first")
            return {"CANCELLED"}

        context.view_layer.update()
        deps = context.evaluated_depsgraph_get()

        col_name = building.name + MODULES_SUFFIX
        old = bpy.data.collections.get(col_name)
        if old:
            for o in list(old.objects):
                bpy.data.objects.remove(o, do_unlink=True)
            bpy.data.collections.remove(old)
        col = bpy.data.collections.new(col_name)
        scene.collection.children.link(col)

        made, swappable = 0, 0
        for idx, inst in enumerate(deps.object_instances):
            if not inst.is_instance or inst.parent is None:
                continue
            if inst.parent.original != building:
                continue
            ev = inst.object
            if ev is None or ev.type != "MESH":
                continue
            src = ev.original

            # object.copy() shares the mesh datablock and carries the modifier
            # stack across, so this stays cheap no matter how many modules
            ob = src.copy()
            ob.matrix_world = inst.matrix_world.copy()
            slot = slot_of(src.name, scene)
            ob[P_SLOT] = slot
            ob[P_ORIG] = src.name
            ob[P_ASSET] = src.name
            ob[P_MOD] = True
            ob.name = "M%03d_%s" % (idx, src.name)
            col.objects.link(ob)
            made += 1
            if slot:
                swappable += 1

        if not made:
            bpy.data.collections.remove(col)
            self.report({"ERROR"}, "No generated geometry on %s. Does it have "
                                   "the Buildify modifier?" % building.name)
            return {"CANCELLED"}

        # ---- the roof ------------------------------------------------------
        # Not everything the node group emits is an instance. Buildify's flat
        # roof is real mesh geometry on the building object itself -- for a
        # square footprint, literally one quad at the top -- so the loop above
        # never sees it. Hiding the building then took the roof with it and the
        # building came out open-topped. Copy that geometry into a real object
        # too, before anything gets hidden.
        roof = None
        roof_me = bpy.data.meshes.new_from_object(
            building.evaluated_get(deps), preserve_all_data_layers=True,
            depsgraph=deps)
        if roof_me is not None:
            if roof_me.polygons:
                roof_me.name = building.name + "_Roof"
                roof = bpy.data.objects.new(building.name + "_Roof", roof_me)
                roof.matrix_world = building.matrix_world.copy()
                # selectable and deletable like any module, but there is no
                # library of roofs to swap it against, so it carries no slot
                roof[P_SLOT] = ""
                roof[P_MOD] = True
                col.objects.link(roof)
            else:
                bpy.data.meshes.remove(roof_me)

        p.modules_collection = col
        building.hide_set(True)
        for o in context.view_layer.objects:
            o.select_set(False)

        self.report({"INFO"}, "Created %d module objects (%d swappable)%s"
                    % (made, swappable, " + roof" if roof else ""))
        return {"FINISHED"}


def mesh_bounds(me):
    xs = [v.co.x for v in me.vertices]
    ys = [v.co.y for v in me.vertices]
    zs = [v.co.z for v in me.vertices]
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def facade_plane_y(me, gap=0.03):
    """Y of the wall face -- the surface that tiles with the next module.

    Anything in front of it is meant to project out of the building, anything
    behind it is the thickness of the wall.

    Three things this is deliberately *not*:

    - Not the bounding box. A balcony reaches 0.6 m out, so re-origining on the
      front of the box buries the wall 0.6 m behind its neighbours.
    - Not simply the biggest face. On a shopfront or a breeze-block screen the
      biggest outward-facing face is the pane at the *back* of the recess.
      What identifies the wall is that it reaches the panel's left and right
      edges, because that is the part that meets the module next door.
    - Not a single exact plane. Buildify's ground floor wall is faceted, its
      face spread over six bands a centimetre apart, and bucketing on exact Y
      splits that into crumbs small enough for a stray flat detail to outweigh
      them. Faces within `gap` of each other are treated as one surface.

    The front of the winning surface is returned, since that is the side which
    has to line up.
    """
    if not me.polygons or not me.vertices:
        return None
    xs = [v.co.x for v in me.vertices]
    x0, x1 = min(xs), max(xs)
    edge = max((x1 - x0) * 1e-3, 1e-4)

    hits = []
    for poly in me.polygons:
        if poly.normal.y > -0.9:                  # not facing out
            continue
        if not any(abs(me.vertices[i].co.x - x0) < edge or
                   abs(me.vertices[i].co.x - x1) < edge
                   for i in poly.vertices):
            continue
        hits.append((poly.center.y, poly.area))
    if not hits:
        return None

    hits.sort()
    best_front, best_area = None, -1.0
    front, area, prev = hits[0][0], 0.0, hits[0][0]
    for y, a in hits:
        if y - prev > gap:                        # start of a new surface
            if area > best_area:
                best_front, best_area = front, area
            front, area = y, 0.0
        area += a
        prev = y
    if area > best_area:
        best_front = front
    return best_front


def normalize_mesh(me, fit="WIDTH", slot_h=3.0):
    """Scale and re-origin a mesh so it fills a module slot.

    Result is centred on X, sits on Z=0, and has its front face on the Y=0
    facade plane with the body running into +Y -- the convention Buildify's own
    modules use, so the asset drops straight into a slot.
    """
    if not me.vertices:
        return "empty mesh"
    x0, x1, y0, y1, z0, z1 = mesh_bounds(me)
    w, h = (x1 - x0), (z1 - z0)
    note = ""
    if fit != "NONE" and w > 1e-6 and h > 1e-6:
        if fit == "STRETCH":
            sx, sz = (2 * W_HALF) / w, slot_h / h
            sy = sx
            note = "stretched x%.3f z%.3f" % (sx, sz)
        else:                               # WIDTH: uniform, width becomes 3 m
            sx = sy = sz = (2 * W_HALF) / w
            note = "scaled x%.3f" % sx
        me.transform(Matrix.Diagonal((sx, sy, sz, 1.0)))
    x0, x1, y0, y1, z0, z1 = mesh_bounds(me)
    # sit on Z=0 and centre on X, but line the *wall* up with Y=0 rather than
    # the front of the bounding box, so projections stay in front of the facade
    wall_y = facade_plane_y(me)
    me.transform(Matrix.Translation((-(x0 + x1) / 2.0,
                                     -(y0 if wall_y is None else wall_y),
                                     -z0)))
    return note


def mesh_from_objects(objs, deps, name="asset"):
    """Combine several objects' visible geometry into one world-space mesh.

    Anything living on the *loops* has to be carried across by hand.
    `from_pydata` builds vertices and faces and nothing else, so UVs do not
    survive it -- and a textured asset that arrives without UVs does not look
    untextured, it looks like the texture was rescaled, because every face ends
    up sampling the same corner of the image. Material indices have the same
    problem and were already handled; UVs and smooth shading are here for the
    same reason.
    """
    verts, faces, mats, mat_index = [], [], [], {}
    smooth = []
    uv_names = []            # ordered: the first one stays the active layer
    uv_values = {}           # layer name -> flat [u, v, u, v, ...] per loop
    n_loops = 0

    for ob in objs:
        if ob.type != "MESH":
            continue
        ev = ob.evaluated_get(deps)
        src = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True,
                                              depsgraph=deps)
        src.transform(ob.matrix_world)

        # a layer that only some of the objects have still has to line up with
        # every loop recorded so far, so it starts padded
        for layer in src.uv_layers:
            if layer.name not in uv_values:
                uv_names.append(layer.name)
                uv_values[layer.name] = [0.0] * (2 * n_loops)

        off = len(verts)
        verts.extend([v.co.copy() for v in src.vertices])
        for poly in src.polygons:
            faces.append([off + i for i in poly.vertices])
            smooth.append(poly.use_smooth)
            for lname in uv_names:
                layer = src.uv_layers.get(lname)
                out = uv_values[lname]
                for li in poly.loop_indices:
                    if layer is None:
                        out.extend((0.0, 0.0))
                    else:
                        out.extend(layer.data[li].uv)
            n_loops += len(poly.vertices)

            m = None
            if poly.material_index < len(src.materials):
                m = src.materials[poly.material_index]
            key = m.name if m else ""
            if key not in mat_index:
                mat_index[key] = len(mat_index)
            mats.append(mat_index[key])
        bpy.data.meshes.remove(src)

    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.update()
    for key, _ in sorted(mat_index.items(), key=lambda kv: kv[1]):
        me.materials.append(bpy.data.materials.get(key) if key else None)
    if len(me.polygons) == len(mats):
        for p, mi in zip(me.polygons, mats):
            p.material_index = mi
    if len(me.polygons) == len(smooth):
        me.polygons.foreach_set("use_smooth", smooth)
    for lname in uv_names:
        vals = uv_values[lname]
        if len(vals) != 2 * len(me.loops):
            continue                       # face order disagreed: leave it out
        layer = me.uv_layers.new(name=lname, do_init=False)
        layer.data.foreach_set("uv", vals)
    me.update()
    return me


def fit_mesh_to_slot(ob, deps, fit="WIDTH", slot_h=3.0):
    """Bake one object's visible geometry into a slot-sized mesh."""
    me = mesh_from_objects([ob], deps, ob.name)
    return me, normalize_mesh(me, fit, slot_h)


class BLM_OT_add_asset(bpy.types.Operator):
    """Add the selected mesh to a module library, auto-fitted to the slot.

    It appears in the swap grid straight away -- no rebuild, no restart"""
    bl_idname = "blm.add_asset"
    bl_label = "Add Selected Mesh As Asset"
    bl_options = {"REGISTER", "UNDO"}

    asset_name: StringProperty(
        name="Name", default="",
        description="Leave blank to keep each object's own name")
    target: StringProperty(
        name="Library", default="",
        description="Collection to add to; blank uses the selected library")
    fit: bpy.props.EnumProperty(
        name="Auto-fit",
        items=(("WIDTH", "Fit width (keep shape)",
                "Scale uniformly so the asset is exactly 3 m wide"),
               ("STRETCH", "Stretch to slot",
                "Scale X and Z independently to fill 3 m x 3 m exactly"),
               ("NONE", "Leave as-is",
                "Only move it to the right origin, do not rescale")),
        default="WIDTH")
    slot_height: FloatProperty(name="Slot Height", default=3.0, min=0.1, max=20.0)

    def invoke(self, context, event):
        p = context.scene.blm_props
        if not self.target:
            self.target = (p.library if p.library != "AUTO"
                           else (COLLECTION_ME if COLLECTION_ME in
                                 bpy.data.collections else "lib_custom"))
        return context.window_manager.invoke_props_dialog(self, width=340)

    def draw(self, context):
        lay = self.layout
        srcs = self.sources(context)
        lay.label(text="Adding %d object(s)" % len(srcs), icon="MESH_DATA")
        lay.prop(self, "target")
        lay.prop(self, "fit")
        if self.fit == "STRETCH":
            lay.prop(self, "slot_height")
        if len(srcs) == 1:
            lay.prop(self, "asset_name")

    def sources(self, context):
        lib_objs = set()
        for cn in library_collections(context.scene):
            col = bpy.data.collections.get(cn)
            if col:
                lib_objs.update(o.name for o in col.objects)
        return [o for o in context.selected_objects
                if o.type == "MESH" and not is_module(o)
                and o.name not in lib_objs]

    def execute(self, context):
        srcs = self.sources(context)
        if not srcs:
            self.report({"ERROR"}, "Select a mesh that is not already a module "
                                   "or a library asset")
            return {"CANCELLED"}

        target = self.target.strip() or "lib_custom"
        col = bpy.data.collections.get(target)
        if col is None:
            col = bpy.data.collections.new(target)
            context.scene.collection.children.link(col)

        deps = context.evaluated_depsgraph_get()
        added, notes = [], []
        for src in srcs:
            me, note = fit_mesh_to_slot(src, deps, self.fit, self.slot_height)
            name = (self.asset_name.strip() if (self.asset_name.strip() and
                                                len(srcs) == 1) else src.name)
            if name in bpy.data.objects:
                i = 1
                while "%s_%02d" % (name, i) in bpy.data.objects:
                    i += 1
                name = "%s_%02d" % (name, i)
            me.name = name
            ob = bpy.data.objects.new(name, me)
            col.objects.link(ob)
            added.append(ob)
            if note:
                notes.append("%s: %s" % (name, note))

        # register the collection so it shows up in the library dropdown
        libs = list(context.scene.get("bld_library", []))
        if target not in libs:
            libs.append(target)
            context.scene["bld_library"] = libs
        context.scene.blm_props.library = target

        # previews need a GPU context: attempting this headless crashes the
        # graphics driver on exit, so only do it in a real Blender session
        if not bpy.app.background:
            for ob in added:
                try:
                    if ob.preview is None:
                        ob.preview_ensure()
                    with context.temp_override(id=ob):
                        bpy.ops.ed.lib_id_generate_preview()
                except Exception:
                    pass

        for area in context.screen.areas if context.screen else []:
            area.tag_redraw()

        msg = "Added %d asset(s) to %s" % (len(added), target)
        if notes:
            msg += "  (%s)" % "; ".join(notes[:2])
        self.report({"INFO"}, msg)
        return {"FINISHED"}


# =============================================================================
# folder-backed library:  a directory of .obj files IS the library
# =============================================================================
P_SRC = "bld_src"        # absolute path of the .obj this asset came from
P_MTIME = "bld_mtime"    # its modification time when last imported
ASSET_EXTS = (".obj",)


ROOT_SECTION = ""        # loose .obj files sitting directly in the root


def folder_collection_name(folder, section=ROOT_SECTION):
    """Collection name for a section. Each subfolder is its own library."""
    import os
    if section:
        return "lib_%s" % section
    base = os.path.basename(os.path.normpath(bpy.path.abspath(folder)))
    return "lib_%s" % (base or "assets")


def scan_folder(folder, section=ROOT_SECTION):
    """Absolute paths of every asset file in one section, sorted by name."""
    import os
    d = bpy.path.abspath(folder)
    if not d or not os.path.isdir(d):
        return []
    if section:
        d = os.path.join(d, section)
        if not os.path.isdir(d):
            return []
    out = []
    for fn in sorted(os.listdir(d)):
        if fn.lower().endswith(ASSET_EXTS) and os.path.isfile(os.path.join(d, fn)):
            out.append(os.path.join(d, fn))
    return out


def sections_in(folder):
    """Section names: every immediate subfolder holding .obj files, plus the
    root itself if loose files are sitting there."""
    import os
    d = bpy.path.abspath(folder) if folder else ""
    if not d or not os.path.isdir(d):
        return []
    out = []
    if scan_folder(d, ROOT_SECTION):
        out.append(ROOT_SECTION)
    for name in sorted(os.listdir(d)):
        sub = os.path.join(d, name)
        if os.path.isdir(sub) and not name.startswith((".", "_")):
            if scan_folder(d, name):
                out.append(name)
    return out


def scan_all_sections(folder):
    return {s: scan_folder(folder, s) for s in sections_in(folder)}


_SECTION_KEEP = []


def section_enum_items(self, context):
    p = context.scene.blm_props
    items = []
    for s in sections_in(p.asset_folder):
        label = s if s else "(root)"
        items.append((s if s else "__root__", label,
                      "%d assets" % len(scan_folder(p.asset_folder, s))))
    if not items:
        items = [("__root__", "(root)", "The asset folder itself")]
    _SECTION_KEEP.clear()
    _SECTION_KEEP.extend(items)
    return _SECTION_KEEP


def import_asset_file(path, fit="WIDTH", slot_h=3.0,
                      forward="NEGATIVE_Z", up="Y"):
    """Import one .obj and return a single slot-fitted asset object.

    Multi-object .obj files are merged into one asset -- a module has to be a
    single object for swapping to work.
    """
    import os
    before = set(bpy.data.objects)
    try:
        bpy.ops.wm.obj_import(filepath=path, forward_axis=forward, up_axis=up)
    except Exception as e:
        return None, "import failed: %s" % e
    fresh = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in fresh if o.type == "MESH"]
    if not meshes:
        for o in fresh:
            bpy.data.objects.remove(o, do_unlink=True)
        return None, "no mesh in file"

    deps = bpy.context.evaluated_depsgraph_get()
    stem = os.path.splitext(os.path.basename(path))[0]
    me = mesh_from_objects(meshes, deps, stem)
    note = normalize_mesh(me, fit, slot_h)

    for o in fresh:                        # drop the raw imported objects
        bpy.data.objects.remove(o, do_unlink=True)

    ob = bpy.data.objects.new(stem, me)
    ob[P_SRC] = path
    ob[P_MTIME] = os.path.getmtime(path)

    # A facade module should be roughly as tall as it is wide. If it comes in
    # flat, the file's axis convention almost certainly disagrees with the
    # Forward/Up settings, and auto-fit (which normalises on width alone)
    # cannot detect that on its own.
    x0, x1, y0, y1, z0, z1 = mesh_bounds(me)
    w, h, d = (x1 - x0), (z1 - z0), (y1 - y0)
    if w > 1e-6 and h < 0.3 * w:
        note = ("looks flat (%.2f x %.2f x %.2f w/d/h) - check Forward/Up axis"
                % (w, d, h))
    return ob, note


class BLM_OT_sync_folder(bpy.types.Operator):
    """Re-read the asset folder: import new .obj files, refresh changed ones,
    drop assets whose file was deleted"""
    bl_idname = "blm.sync_folder"
    bl_label = "Refresh From Folder"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        import os
        scene = context.scene
        p = scene.blm_props
        folder = bpy.path.abspath(p.asset_folder) if p.asset_folder else ""
        if not folder or not os.path.isdir(folder):
            self.report({"ERROR"}, "Set a valid asset folder first")
            return {"CANCELLED"}

        counts, warnings = sync_asset_folder(scene)
        for w in warnings:
            self.report({"WARNING"}, w)
        self.report({"INFO"}, "%d section(s): %d new, %d updated, %d removed"
                    % counts)
        for area in (context.screen.areas if context.screen else []):
            area.tag_redraw()
        return {"FINISHED"}


def sync_asset_folder(scene):
    """Re-read the asset folder into collections. Returns (counts, warnings).

    Split out of the operator so a file-load handler can run it too: new
    sections and new .obj files do not exist in a saved .blend until something
    imports them, so without this the Library dropdown still shows whatever was
    there when the file was saved.
    """
    import os
    warnings = []
    p = scene.blm_props
    folder = bpy.path.abspath(p.asset_folder) if p.asset_folder else ""
    if not folder or not os.path.isdir(folder):
        return (0, 0, 0, 0), warnings

    by_section = scan_all_sections(folder)
    libs = list(scene.get("bld_library", []))
    total_add = total_chg = total_del = 0
    names = []

    # drop collections for sections that no longer exist on disk
    live = {folder_collection_name(folder, s) for s in by_section}
    for cn in list(libs):
        if cn.startswith("lib_") and cn not in live:
            col = bpy.data.collections.get(cn)
            if col and any(o.get(P_SRC) for o in col.objects):
                for o in list(col.objects):
                    bpy.data.objects.remove(o, do_unlink=True)
                bpy.data.collections.remove(col)
                libs.remove(cn)

    for section, files in by_section.items():
        cname = folder_collection_name(folder, section)
        names.append(cname)
        col = bpy.data.collections.get(cname)
        if col is None:
            col = bpy.data.collections.new(cname)
            scene.collection.children.link(col)
            col.hide_viewport = True       # source assets, not scene content
            col.hide_render = True

        on_disk = {f: os.path.getmtime(f) for f in files}
        have = {}
        for ob in list(col.objects):
            src = ob.get(P_SRC)
            if src is None:
                continue
            if src not in on_disk:
                bpy.data.objects.remove(ob, do_unlink=True)       # file deleted
                total_del += 1
            else:
                have[src] = ob

        for f, mtime in on_disk.items():
            ob = have.get(f)
            if ob is not None:
                if abs(float(ob.get(P_MTIME, 0.0)) - mtime) < 1e-6:
                    continue                                      # unchanged
                bpy.data.objects.remove(ob, do_unlink=True)        # re-import
                total_chg += 1
            else:
                total_add += 1
            new, note = import_asset_file(f, p.folder_fit, p.slot_height,
                                          p.obj_forward, p.obj_up)
            if new is None:
                warnings.append("%s: %s" % (os.path.basename(f), note))
                continue
            if note and "look" in note:
                warnings.append("%s: %s" % (os.path.basename(f), note))
            col.objects.link(new)

        if cname not in libs:
            libs.append(cname)

    scene["bld_library"] = libs
    # Keep the current selection. Resetting to names[0] on every refresh threw
    # the user off whichever library they were working in -- and off AUTO,
    # which is never in `names` at all.
    try:
        if p.library != "AUTO" and p.library not in names and names:
            p.library = names[0]
    except Exception:
        pass

    return (len(by_section), total_add, total_chg, total_del), warnings


class BLM_OT_import_asset_file(bpy.types.Operator):
    """Pick a file anywhere on this computer, copy it into the asset folder,
    and load it"""
    bl_idname = "blm.import_asset_file"
    bl_label = "Add Asset File"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)
    directory: StringProperty(subtype="DIR_PATH")
    filter_glob: StringProperty(default="*.obj", options={"HIDDEN"})
    section: bpy.props.EnumProperty(
        name="Section", items=section_enum_items,
        description="Which section folder to copy the file into")
    new_section: StringProperty(
        name="Or New Section", default="",
        description="Type a name to create a new section folder")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context):
        lay = self.layout
        box = lay.box()
        box.label(text="Copy into section:", icon="FILE_FOLDER")
        box.prop(self, "section", text="")
        box.prop(self, "new_section")

    def execute(self, context):
        import os
        import shutil
        p = context.scene.blm_props
        root = bpy.path.abspath(p.asset_folder) if p.asset_folder else ""
        if not root or not os.path.isdir(root):
            self.report({"ERROR"}, "Set a valid asset folder first")
            return {"CANCELLED"}

        sec = self.new_section.strip() or (
            "" if self.section == "__root__" else self.section)
        dest = os.path.join(root, sec) if sec else root
        if not os.path.isdir(dest):
            os.makedirs(dest)

        picked = []
        if self.files:
            picked = [os.path.join(self.directory, f.name)
                      for f in self.files if f.name]
        elif self.filepath:
            picked = [self.filepath]
        picked = [f for f in picked if f.lower().endswith(ASSET_EXTS)]
        if not picked:
            self.report({"ERROR"}, "Pick one or more .obj files")
            return {"CANCELLED"}

        copied = []
        for src in picked:
            if os.path.normcase(os.path.dirname(src)) == os.path.normcase(dest):
                copied.append(src)                    # already in the folder
                continue
            stem, ext = os.path.splitext(os.path.basename(src))
            target = os.path.join(dest, stem + ext)
            i = 1
            while os.path.exists(target):
                target = os.path.join(dest, "%s_%02d%s" % (stem, i, ext))
                i += 1
            shutil.copy2(src, target)
            # .obj files reference a sibling .mtl; bring it along
            mtl = os.path.splitext(src)[0] + ".mtl"
            if os.path.exists(mtl):
                try:
                    shutil.copy2(mtl, os.path.splitext(target)[0] + ".mtl")
                except Exception:
                    pass
            copied.append(target)

        bpy.ops.blm.sync_folder()
        if sec:
            cname = folder_collection_name(root, sec)
            try:
                p.library = cname
            except Exception:
                pass
        self.report({"INFO"}, "Added %d file(s) to %s"
                    % (len(copied), sec or "(root)"))
        return {"FINISHED"}


class BLM_OT_open_asset_folder(bpy.types.Operator):
    """Open the asset folder in the file explorer"""
    bl_idname = "blm.open_asset_folder"
    bl_label = "Open Folder"

    def execute(self, context):
        import os
        d = bpy.path.abspath(context.scene.blm_props.asset_folder or "")
        if not d or not os.path.isdir(d):
            self.report({"ERROR"}, "Set a valid asset folder first")
            return {"CANCELLED"}
        bpy.ops.wm.path_open(filepath=d)
        return {"FINISHED"}


class BLM_OT_export_selected_to_folder(bpy.types.Operator):
    """Export the selected mesh into the asset folder as .obj, so it becomes a
    permanent part of the library"""
    bl_idname = "blm.export_to_folder"
    bl_label = "Save Selected To Folder"
    bl_options = {"REGISTER", "UNDO"}

    asset_name: StringProperty(name="File Name", default="")
    section: bpy.props.EnumProperty(name="Section", items=section_enum_items)
    new_section: StringProperty(name="Or New Section", default="")

    def invoke(self, context, event):
        act = context.active_object
        self.asset_name = act.name if act else "asset"
        return context.window_manager.invoke_props_dialog(self, width=320)

    def execute(self, context):
        import os
        p = context.scene.blm_props
        root = bpy.path.abspath(p.asset_folder) if p.asset_folder else ""
        if not root or not os.path.isdir(root):
            self.report({"ERROR"}, "Set a valid asset folder first")
            return {"CANCELLED"}
        sec = self.new_section.strip() or (
            "" if self.section == "__root__" else self.section)
        dest = os.path.join(root, sec) if sec else root
        if not os.path.isdir(dest):
            os.makedirs(dest)
        sel = [o for o in context.selected_objects if o.type == "MESH"]
        if not sel:
            self.report({"ERROR"}, "Select a mesh")
            return {"CANCELLED"}

        stem = (self.asset_name.strip() or sel[0].name)
        target = os.path.join(dest, stem + ".obj")
        i = 1
        while os.path.exists(target):
            target = os.path.join(dest, "%s_%02d.obj" % (stem, i))
            i += 1
        bpy.ops.wm.obj_export(filepath=target, export_selected_objects=True,
                              export_materials=True,
                              forward_axis=p.obj_forward, up_axis=p.obj_up)
        bpy.ops.blm.sync_folder()
        self.report({"INFO"}, "Saved %s" % os.path.basename(target))
        return {"FINISHED"}


class BLM_OT_swap(bpy.types.Operator):
    """Swap every selected module to this asset"""
    bl_idname = "blm.swap"
    bl_label = "Swap To This Asset"
    bl_options = {"REGISTER", "UNDO"}

    asset: StringProperty()

    def execute(self, context):
        mods = selected_modules(context)
        if not mods:
            self.report({"ERROR"}, "Select a module object first")
            return {"CANCELLED"}
        src = bpy.data.objects.get(self.asset)
        if src is None:
            self.report({"ERROR"}, "No such asset: %s" % self.asset)
            return {"CANCELLED"}

        asset_slot = slot_of(self.asset, context.scene)
        lib = context.scene.blm_props.library
        done, skipped = 0, 0
        for ob in mods:
            if lib == "AUTO":
                # Guard against dropping roof trim into a wall slot. The test
                # is membership of this module's own slot, not
                # slot_of(asset) == slot: an object can sit in several
                # collections and slot_of returns whichever it meets first,
                # which rejected perfectly good swaps.
                if self.asset not in assets_in(ob.get(P_SLOT, "")):
                    skipped += 1
                    continue
            elif asset_slot != lib:
                # an explicit library is chosen: anything from it is fair game,
                # anything from outside it is not
                skipped += 1
                continue
            if apply_asset(ob, self.asset):
                done += 1

        msg = "Swapped %d module(s) to %s" % (done, self.asset)
        if skipped:
            msg += "  (%d skipped: different slot)" % skipped
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class BLM_OT_cycle(bpy.types.Operator):
    """Step the selected modules through their slot's assets, head to head"""
    bl_idname = "blm.cycle"
    bl_label = "Cycle Asset"
    bl_options = {"REGISTER", "UNDO"}

    delta: IntProperty(default=1)

    def execute(self, context):
        mods = selected_modules(context)
        if not mods:
            return {"CANCELLED"}
        lib = context.scene.blm_props.library
        n = 0
        for ob in mods:
            cands = assets_in(ob.get(P_SLOT, "") if lib == "AUTO" else lib)
            if len(cands) < 2:
                continue
            try:
                i = cands.index(current_asset(ob))
            except ValueError:
                i = 0
            apply_asset(ob, cands[(i + self.delta) % len(cands)])
            n += 1
        if not n:
            self.report({"WARNING"}, "Nothing to cycle (slot has one asset)")
            return {"CANCELLED"}
        return {"FINISHED"}


class BLM_OT_revert(bpy.types.Operator):
    """Put back the module Buildify originally generated here"""
    bl_idname = "blm.revert"
    bl_label = "Revert To Generated"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        n = 0
        for ob in selected_modules(context):
            orig = ob.get(P_ORIG)
            if orig and apply_asset(ob, orig):
                n += 1
        self.report({"INFO"}, "Reverted %d module(s)" % n)
        return {"FINISHED"}


class BLM_OT_select_same(bpy.types.Operator):
    """Select every module that currently uses the same asset"""
    bl_idname = "blm.select_same"
    bl_label = "Select All Like This"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        act = context.active_object
        if not is_module(act):
            return {"CANCELLED"}
        target = act.data
        n = 0
        for ob in context.view_layer.objects:
            if is_module(ob) and ob.data == target:
                ob.select_set(True)
                n += 1
        self.report({"INFO"}, "Selected %d modules" % n)
        return {"FINISHED"}


class BLM_OT_select_slot(bpy.types.Operator):
    """Select every module in the same slot (whole floor band, etc.)"""
    bl_idname = "blm.select_slot"
    bl_label = "Select All In Slot"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        act = context.active_object
        if not is_module(act):
            return {"CANCELLED"}
        slot = act.get(P_SLOT)
        n = 0
        for ob in context.view_layer.objects:
            if is_module(ob) and ob.get(P_SLOT) == slot:
                ob.select_set(True)
                n += 1
        self.report({"INFO"}, "Selected %d modules in %s" % (n, slot))
        return {"FINISHED"}


class BLM_OT_delete(bpy.types.Operator):
    """Delete the selected modules"""
    bl_idname = "blm.delete"
    bl_label = "Delete Modules"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mods = selected_modules(context)
        for ob in mods:
            bpy.data.objects.remove(ob, do_unlink=True)
        self.report({"INFO"}, "Deleted %d module(s)" % len(mods))
        return {"FINISHED"}


class BLM_OT_export_fbx(bpy.types.Operator):
    """Export the finished building as .fbx"""
    bl_idname = "blm.export_fbx"
    bl_label = "Export FBX"

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.fbx", options={"HIDDEN"})
    join_meshes: BoolProperty(
        name="Join Into One Mesh", default=False,
        description="Merge every module into a single object on export. Off "
                    "keeps them separate so they stay editable in the engine")

    def invoke(self, context, event):
        p = context.scene.blm_props
        self.filepath = ((p.modules_collection.name if p.modules_collection
                          else "building") + ".fbx")
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context):
        self.layout.prop(self, "join_meshes")

    def execute(self, context):
        p = context.scene.blm_props
        col = p.modules_collection
        if col is None or not col.objects:
            self.report({"ERROR"}, "Build the modules first")
            return {"CANCELLED"}

        for o in context.view_layer.objects:
            o.select_set(False)

        temp = None
        if self.join_meshes:
            # join a throwaway copy so the editable modules survive
            copies = []
            for o in col.objects:
                c = o.copy()
                c.data = o.data.copy()      # join() needs unshared meshes
                context.scene.collection.objects.link(c)
                c.select_set(True)
                copies.append(c)
            if copies:
                context.view_layer.objects.active = copies[0]
                bpy.ops.object.join()
                temp = context.view_layer.objects.active
                temp.name = col.name
        else:
            for o in col.objects:
                o.hide_set(False)
                o.select_set(True)
                context.view_layer.objects.active = o

        n = len([o for o in context.view_layer.objects if o.select_get()])
        try:
            bpy.ops.export_scene.fbx(
                filepath=self.filepath,
                use_selection=True,
                object_types={"MESH"},
                use_mesh_modifiers=True,
                mesh_smooth_type="FACE",
                apply_scale_options="FBX_SCALE_NONE",
                add_leaf_bones=False,
                bake_anim=False,
                path_mode="AUTO")
        except Exception as e:
            self.report({"ERROR"}, "FBX export failed: %s" % e)
            return {"CANCELLED"}
        finally:
            if temp is not None:
                mesh = temp.data
                bpy.data.objects.remove(temp, do_unlink=True)
                bpy.data.meshes.remove(mesh)

        self.report({"INFO"}, "Exported %s (%d object%s) to %s"
                    % ("joined mesh" if self.join_meshes else "modules",
                       n, "" if n == 1 else "s", self.filepath))
        return {"FINISHED"}


# =============================================================================
# stage 1: build the building
#
# Merged in from the standalone "Buildify Manager" script. That was the front
# of the pipeline -- drive Buildify's node group from a height, then bake the
# result down to one game-ready mesh -- and everything above is what happens
# afterwards, once there is a model to take apart and customise.
#
# Its "Convert to OBJ" button is gone: blm.export_fbx already covers getting
# the finished mesh out.
# =============================================================================
STOCK_SLOTS = {
    "ground": "ground_floor_walls",
    "middle": "middle_floor_walls",
    "trim": "trim",
}

# which sections of the asset folder feed which slot
ROLE_SECTIONS = {
    "ground": ("doors", "walls"),
    "middle": ("windows", "walls", "balconies"),
    "trim": ("trim",),
}

ROLE_COLLECTION = {
    "ground": "me_ground_modules",
    "middle": "me_middle_modules",
    "trim": "me_trim_modules",
}


def find_building_group():
    for name in ("F  BUILDING", "F BUILDING", "building"):
        ng = bpy.data.node_groups.get(name)
        if ng:
            return ng
    for ng in bpy.data.node_groups:
        if "BUILDING" in ng.name.upper():
            return ng
    return None


def wall_slots(node_group):
    """{role: (group node, 'Wall modules' socket)} for the three wall slots.

    Buildify does not expose its module collections on the modifier -- they are
    defaults on group nodes *inside* the tree -- so swapping kits means writing
    those sockets. Each slot is identified by the stock collection it shipped
    with, remembered on the node before it is overwritten so the switch back
    stays possible.
    """
    found = {}
    for node in node_group.nodes:
        if node.type != "GROUP" or not node.node_tree:
            continue
        sock = node.inputs.get("Wall modules")
        if sock is None:
            continue
        stock = node.get("blm_stock")
        if stock is None:
            stock = sock.default_value.name if sock.default_value else ""
            node["blm_stock"] = stock
        for role, name in STOCK_SLOTS.items():
            if stock == name:
                found[role] = (node, sock)
    return found


def role_collection(role, create=False):
    name = ROLE_COLLECTION[role]
    col = bpy.data.collections.get(name)
    if col is None and create:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
        # keep the raw modules out of the viewport; Collection Info still reads
        # them, they just stop piling up on top of each other at the origin
        layer = bpy.context.view_layer.layer_collection.children.get(name)
        if layer:
            layer.exclude = True
    return col


def stock_facade_y(collection_name):
    """Where the kit that shipped in this slot puts its wall.

    Slots do not share a facade line: Buildify's ground floor is built 0.43 m
    proud of the floors above it, so a module dropped into the ground slot at
    Y=0 sits a comfortable step *behind* the stock corner pillars either side
    of it. Median rather than mean, so one odd module cannot drag the line.
    """
    col = bpy.data.collections.get(collection_name)
    if col is None:
        return None
    vals = []
    for ob in col.objects:
        if ob.type != "MESH":
            continue
        y = facade_plane_y(ob.data)
        if y is not None:
            vals.append(y)
    if not vals:
        return None
    vals.sort()
    return vals[len(vals) // 2]


def import_modules(folder, prefix=""):
    """Import matching .obj files from the sections into the role collections.

    These are imported separately from the swap library's `lib_*` collections
    on purpose: those are re-origined to fit a slot, which would shove a
    projecting module such as a balcony back off the facade plane. The node
    group needs them at their authored coordinates.
    """
    import os
    added = {}
    for role, sections in ROLE_SECTIONS.items():
        col = role_collection(role, create=True)
        for old in list(col.objects):          # rebuild from scratch each time
            bpy.data.objects.remove(old, do_unlink=True)
        # snap this slot's modules onto the facade line the stock kit uses for
        # the same slot, so our panels meet the stock corner pillars flush
        ref = stock_facade_y(STOCK_SLOTS[role])
        n = 0
        for section in sections:
            d = os.path.join(folder, section)
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if not fn.lower().endswith(".obj"):
                    continue
                # the asset folder holds Buildify's own exported modules next
                # to ours, so without a filter the custom kit ends up half stock
                if prefix and not fn.startswith(prefix):
                    continue
                stem = os.path.splitext(fn)[0]
                before = set(bpy.data.objects)
                bpy.ops.wm.obj_import(filepath=os.path.join(d, fn),
                                      forward_axis="NEGATIVE_Z", up_axis="Y")
                fresh = [o for o in bpy.data.objects if o not in before]
                for i, ob in enumerate(fresh):
                    # The OBJ importer applies the axis conversion as an object
                    # ROTATION and leaves the mesh data Y-up. Collection Info
                    # instances the mesh data and resets child transforms, so
                    # that rotation is discarded and every panel is placed lying
                    # flat. Bake the transform into the data instead.
                    ob.data.transform(ob.matrix_world)
                    ob.matrix_world = Matrix.Identity(4)
                    # Line the wall up with this slot's facade line, so a
                    # module with a balcony or a deep sill sits flush with the
                    # plain walls either side of it instead of stepping back,
                    # and the whole row meets the stock corner pillars.
                    wall_y = facade_plane_y(ob.data)
                    if wall_y is not None:
                        shift = (0.0 if ref is None else ref) - wall_y
                        if abs(shift) > 1e-6:
                            ob.data.transform(
                                Matrix.Translation((0.0, shift, 0.0)))
                    for c in list(ob.users_collection):
                        c.objects.unlink(ob)
                    col.objects.link(ob)
                    ob.name = stem if i == 0 else "%s_%d" % (stem, i)
                    n += 1
        added[role] = n
    return added


def apply_style(style):
    """Point the three wall slots at either the stock kit or our modules."""
    ng = find_building_group()
    if ng is None:
        return None, "No 'building' node group in this file."
    slots = wall_slots(ng)
    if not slots:
        return None, "Could not find Buildify's wall slots in the node tree."

    done = []
    for role, (node, sock) in slots.items():
        if style == "BUILDIFY":
            target = bpy.data.collections.get(node.get("blm_stock", ""))
        else:
            target = role_collection(role)
            if target is None or not target.objects:
                return None, ("No modules loaded for the %s slot -- press "
                              "Load Modules first." % role)
        if target is None:
            continue
        sock.default_value = target
        done.append("%s->%s" % (role, target.name))
    return done, ""


# ---------------------------------------------------------------------------
# hidden-face culling
# ---------------------------------------------------------------------------
def _sphere_dirs(n):
    """n roughly-even directions on the unit sphere (Fibonacci lattice)."""
    out = []
    ga = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(n):
        z = 1.0 - 2.0 * (i + 0.5) / n
        r = math.sqrt(max(0.0, 1.0 - z * z))
        a = ga * i
        out.append(Vector((math.cos(a) * r, math.sin(a) * r, z)))
    return out


def _seen_from_viewpoints(bvh, centre, radius, views, grid, wanted):
    """Face indices a viewer standing outside actually lands a ray on.

    Orthographic sweeps from viewpoints over the upper hemisphere. This is what
    catches geometry visible *through* an opening: from a face deep inside, a
    distant window covers a few degrees of sky and a per-face direction sweep
    steps straight over it, but from the viewpoint that window is wide and the
    ray goes through it without trying.

    Only `wanted` faces are recorded -- everything else is already being kept.
    """
    seen = set()
    span = radius * 2.1
    far = radius * 6.0
    for d in _sphere_dirs(views * 2):
        if d.z < -0.05:                 # nobody views a building from below
            continue
        eye = centre + d * (radius * 2.5)
        up = Vector((0.0, 0.0, 1.0))
        if abs(d.z) > 0.98:
            up = Vector((0.0, 1.0, 0.0))
        u = d.cross(up).normalized()
        v = u.cross(d).normalized()
        ray = -d
        for i in range(grid):
            base = eye + u * ((i / (grid - 1.0) - 0.5) * span)
            for j in range(grid):
                o = base + v * ((j / (grid - 1.0) - 0.5) * span)
                idx = bvh.ray_cast(o, ray, far)[2]
                if idx is not None and idx in wanted:
                    seen.add(idx)
    return seen


CULL_SAMPLES = 256      # directions tested per face
CULL_VIEWS = 24         # viewpoints swept around the building
CULL_GRID = 192         # rays per side from each viewpoint
DISSOLVE_ANGLE = math.radians(1.0)
WELD_DISTANCE = 1e-4


def cull_hidden_faces(bm, samples=CULL_SAMPLES, views=CULL_VIEWS,
                      grid=CULL_GRID, cull_bottom=True, min_keep=0.10,
                      dry_run=False):
    """Delete every face in `bm` that no ray from outside the building reaches.

    A face is kept if a ray leaving it escapes the mesh in any direction. That
    is a real visibility test, unlike mesh.select_interior_faces, which infers
    "inside" from surrounding geometry and cheerfully deletes the visible face
    of an open single-sided facade module.

    Both sides of a face are tested, so one whose winding got flipped somewhere
    in the kit is kept rather than silently deleted.

    Returns (removed, note), or the condemned face indices if dry_run.
    """
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    bm.faces.index_update()
    if not bm.faces:
        return 0, "no faces"

    bvh = BVHTree.FromBMesh(bm)
    dirs = _sphere_dirs(samples)

    xs = [v.co.x for v in bm.verts]
    ys = [v.co.y for v in bm.verts]
    zs = [v.co.z for v in bm.verts]
    size = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) or 1.0
    far = size * 4.0
    # Lift the ray origin clear of the face plane rather than hugging it. At a
    # fraction of a millimetre a grazing ray skims along its own face and
    # registers a self-hit, which reads as "hidden"; a few millimetres is still
    # far thinner than any wall, so it cannot tunnel through one.
    eps = max(1e-4, size * 5e-4)
    zmin = min(zs)

    def reach(p, d):
        """True if a viewer outside could stand somewhere along this ray.

        With the building on the ground a downward ray is only useful while it
        is still above ground level, so it gets clipped there. That removes the
        underside the building stands on -- every direction off it runs into
        either the building or the ground -- while keeping balcony soffits,
        which are seen from below by someone standing out in front of them.
        """
        limit = far
        if cull_bottom and d.z < -1e-6:
            limit = min(far, (zmin - p.z) / d.z)
            if limit <= eps:
                return False
        return bvh.ray_cast(p, d, limit)[0] is None

    def escapes(origins, n):
        """Can a ray leave the mesh from any of these points, any direction?"""
        for d in dirs:
            nd = n.dot(d)
            if abs(nd) < 0.02:                  # exactly edge-on, no escape
                continue
            off = n * (eps if nd > 0.0 else -eps)
            for p in origins:
                if reach(p + off, d):
                    return True
        return False

    hidden = []
    for f in bm.faces:
        c = f.calc_center_median()
        n = f.normal
        if n.length_squared < 1e-12:
            continue                            # degenerate, leave alone

        # straight out of the face is by far the likeliest escape route, so
        # trying it first settles most exterior faces in one or two raycasts
        if any(reach(c + d * eps, d) for d in (n, -n)):
            continue
        if escapes((c,), n):
            continue
        # Only the centre has been tested so far. A face can be half covered by
        # something in front of it -- a balcony slab across a wall panel, a
        # pillar across a window reveal -- and the centre and corners can all
        # sit in the covered half. Edge midpoints go in too, so a face showing
        # only a strip of itself still finds its way out.
        probes = [c + (v.co - c) * 0.85 for v in f.verts]
        vs = f.verts[:]
        for i, v in enumerate(vs):
            mid = (v.co + vs[(i + 1) % len(vs)].co) * 0.5
            probes.append(c + (mid - c) * 0.85)
        if escapes(probes, n):
            continue
        hidden.append(f)

    # second opinion on everything the escape test condemned, from outside in
    if hidden:
        idx = {f.index for f in hidden}
        lo = Vector((min(xs), min(ys), zmin))
        hi = Vector((max(xs), max(ys), max(zs)))
        rescued = _seen_from_viewpoints(bvh, (lo + hi) * 0.5,
                                        max((hi - lo).length * 0.5, 1e-3),
                                        views, grid, idx)
        if rescued:
            hidden = [f for f in hidden if f.index not in rescued]

    if dry_run:                        # for diagnostics: report, change nothing
        return {f.index for f in hidden}

    total = len(bm.faces)
    if total - len(hidden) < total * min_keep:
        return 0, ("kept everything: the test wanted %d of %d faces, which "
                   "means the mesh is not closed the way it should be"
                   % (len(hidden), total))

    bmesh.ops.delete(bm, geom=hidden, context="FACES")
    return len(hidden), ""


def unify_materials(obj):
    """Fold mat.001 / mat.002 back onto the material they were copied from.

    Joining many modules leaves a slot per source datablock, so the same
    concrete ends up as four or five materials and the engine sees four or five
    draw calls. Returns how many slots disappeared.
    """
    me = obj.data
    if not me.materials:
        return 0

    before = len(me.materials)
    canonical = []                  # de-duplicated, in first-seen order
    remap = []                      # old slot index -> canonical index
    for mat in me.materials:
        if mat is None:
            target = None
        else:
            stem, _, tail = mat.name.rpartition(".")
            # only treat a trailing .001 as a copy, never a real name
            base = stem if stem and tail.isdigit() and len(tail) == 3 else mat.name
            target = bpy.data.materials.get(base) or mat
        if target in canonical:
            remap.append(canonical.index(target))
        else:
            remap.append(len(canonical))
            canonical.append(target)

    # a slot nothing is assigned to is just an extra entry for the exporter to
    # carry around, so drop those at the same time
    hits = [remap[p.material_index] if p.material_index < len(remap) else 0
            for p in me.polygons]
    used = sorted(set(hits))
    if len(used) == before:
        return 0

    final = [canonical[i] for i in used]
    squeeze = {old: new for new, old in enumerate(used)}

    me.materials.clear()
    for mat in final:
        me.materials.append(mat)
    for poly, idx in zip(me.polygons, hits):
        poly.material_index = squeeze[idx]
    return before - len(final)


class BUILDIFY_OT_load_modules(bpy.types.Operator):
    """Import the .obj modules from the asset folder and sort them into the
    ground / middle / trim slots the node group builds from"""
    bl_idname = "object.buildify_load_modules"
    bl_label = "Load Modules From Folder"

    def execute(self, context):
        import os
        p = context.scene.blm_props
        folder = bpy.path.abspath(p.asset_folder) if p.asset_folder else ""
        if not folder or not os.path.isdir(folder):
            self.report({"ERROR"}, "Set a valid asset folder first")
            return {"CANCELLED"}

        added = import_modules(folder, p.module_prefix)
        if not sum(added.values()):
            self.report({"ERROR"}, "No .obj files starting with %r under %s"
                        % (p.module_prefix, folder))
            return {"CANCELLED"}

        counts = ", ".join(
            "%s: %d" % (r, len(role_collection(r).objects)
                        if role_collection(r) else 0)
            for r in ("ground", "middle", "trim"))
        self.report({"INFO"}, "Imported %d modules (%s)"
                    % (sum(added.values()), counts))
        return {"FINISHED"}


class BUILDIFY_OT_apply_style(bpy.types.Operator):
    """Rewire the building node group to the chosen module kit"""
    bl_idname = "object.buildify_apply_style"
    bl_label = "Apply Module Style"

    def execute(self, context):
        done, err = apply_style(context.scene.blm_props.module_style)
        if err:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}
        for ob in context.scene.objects:
            ob.update_tag()
        context.view_layer.update()
        self.report({"INFO"}, "Style applied: " + ", ".join(done))
        return {"FINISHED"}


class BUILDIFY_OT_generate(bpy.types.Operator):
    """Apply the Buildify node group, setting floor counts from the height"""
    bl_idname = "object.buildify_generate"
    bl_label = "Generate Building"

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == "MESH"

    def execute(self, context):
        obj = context.active_object
        p = context.scene.blm_props
        height = p.build_height

        if p.use_attr:
            found = None
            if p.attr_name in obj:
                try:
                    found = float(obj[p.attr_name])
                except (ValueError, TypeError):
                    pass
            if found is None and obj.data and hasattr(obj.data, "attributes"):
                attr = obj.data.attributes.get(p.attr_name)
                if attr and len(attr.data):
                    if hasattr(attr.data[0], "value"):
                        found = float(attr.data[0].value)
                    elif hasattr(attr.data[0], "vector"):
                        found = float(attr.data[0].vector[0])
            if found is not None:
                height = found
                self.report({"INFO"}, "Read height %g from %r"
                            % (height, p.attr_name))
            else:
                self.report({"WARNING"}, "Attribute %r not found, using %g"
                            % (p.attr_name, height))

        # a footprint shorter than one module still has to get one floor,
        # otherwise floor(h/3) == 0 and the node group emits nothing at all
        lo = max(1, math.floor(height / 3.0))
        hi = max(lo, math.ceil(height / 3.0))

        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        mod = next((m for m in obj.modifiers if m.type == "NODES"), None)
        if not mod:
            mod = obj.modifiers.new(name="Buildify Nodes", type="NODES")

        group = find_building_group()
        if not group:
            obj.modifiers.remove(mod)
            self.report({"ERROR"}, "No Geometry Node group containing 'BUILDING'")
            return {"CANCELLED"}

        mod.node_group = group
        mod.name = group.name

        # build with whichever kit is selected, not whatever the node tree
        # happens to be pointing at from a previous run
        _done, err = apply_style(p.module_style)
        if err:
            self.report({"WARNING"}, err)

        if hasattr(group, "interface"):
            for item in group.interface.items_tree:
                if item.item_type != "SOCKET":
                    continue
                name = item.name.upper()
                if "FLOOR" not in name:
                    continue
                if "MIN" in name:
                    mod[item.identifier] = lo
                elif "MAX" in name:
                    mod[item.identifier] = hi

        # writing mod[identifier] does NOT tag the object, so the first
        # evaluation would otherwise still use the previous floor counts
        obj.update_tag()
        context.view_layer.update()
        self.report({"INFO"}, "Building generated: %d-%d floors" % (lo, hi))
        return {"FINISHED"}


class BUILDIFY_OT_optimize(bpy.types.Operator):
    """Turn the finished building into one game-ready mesh.

    Realises the modules, joins them, welds the seams, deletes every face that
    cannot be seen from outside, dissolves the edges left between neighbouring
    faces that share a material, and folds duplicate materials into one.
    """
    bl_idname = "object.buildify_optimize"
    bl_label = "Optimize For Game"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        p = context.scene.blm_props
        sources = [o for o in context.selected_objects if o.type == "MESH"]
        if not sources:
            self.report({"ERROR"}, "Select at least one mesh object")
            return {"CANCELLED"}

        # 1. Realise the geometry-nodes instances into real objects.
        #
        # A Buildify building is instances, not objects: the modules only exist
        # inside the depsgraph, so object.join() finds nothing to join ("No mesh
        # data to join") and object.convert(target='MESH') applies the stack
        # without realising instances -- both hand back a bare footprint.
        #
        # duplicates_make_real is used rather than rebuilding the mesh from
        # depsgraph.object_instances by hand: it carries material slots, UV
        # layers and custom attributes across. A hand-built bmesh keeps the
        # per-face material *indices* but none of the slots they point at, which
        # is how a baked building loses every material it had.
        bpy.ops.object.select_all(action="DESELECT")
        for o in sources:
            o.select_set(True)
        context.view_layer.objects.active = sources[0]

        # diff bpy.data rather than trusting the selection the operator leaves
        # behind: that is not reliable from a script or in background mode
        before_objs = set(bpy.data.objects)
        bpy.ops.object.duplicates_make_real(use_base_parent=False,
                                            use_hierarchy=False)
        parts = [o for o in bpy.data.objects
                 if o not in before_objs and o.type == "MESH"]
        parts.extend(o for o in sources if o.type == "MESH")
        # the sources keep their node modifier, which would rebuild the whole
        # building again on top of the joined mesh
        for o in sources:
            for mod in list(o.modifiers):
                if mod.type == "NODES":
                    o.modifiers.remove(mod)

        # After Customize the building is already real objects rather than
        # instances, so one part with geometry is a perfectly good input --
        # only a footprint with nothing generated on it is an error.
        parts = [o for o in parts if o.data and len(o.data.polygons)]
        if not parts:
            self.report({"ERROR"}, "Nothing to bake -- generate a building first")
            return {"CANCELLED"}

        # 2. Join natively, so materials are remapped for us
        bpy.ops.object.select_all(action="DESELECT")
        for o in parts:
            o.select_set(True)
        active = sources[0] if sources[0] in parts else parts[0]
        context.view_layer.objects.active = active
        if len(parts) > 1:
            bpy.ops.object.join()
        obj = context.active_object

        # join keeps the ACTIVE object's mesh datablock, and after Customize
        # every module shares its mesh with the library asset it was drawn
        # from. Welding or culling that in place would edit the library itself,
        # and the decimate refuses outright ("cannot be applied to multi-user
        # data"), so take a private copy before touching anything.
        if obj.data.users > 1:
            obj.data = obj.data.copy()

        # the result absorbed the modules but is not one any more; leaving the
        # markers on would have Customize offer to swap the whole building
        for key in (P_MOD, P_SLOT, P_ASSET, P_ORIG, P_SRC, P_MTIME):
            if key in obj:
                del obj[key]

        obj.data.calc_loop_triangles()
        before = len(obj.data.loop_triangles)

        # 3. Fold mat.001-style copies together before anything looks at which
        #    faces "share a material" -- otherwise identical concrete on two
        #    modules counts as two materials and its shared edge survives.
        dropped = unify_materials(obj)

        # 4-6 in one bmesh pass: weld, cull, dissolve.
        # NOTE: mesh.merge_by_distance and mesh.delete_interior do not exist --
        # the real operators are remove_doubles and select_interior_faces.
        me = obj.data
        bm = bmesh.new()
        bm.from_mesh(me)

        # 4. weld the module seams so neighbours actually share vertices;
        #    nothing below can dissolve an edge that is really two edges
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=WELD_DISTANCE)

        # 5. drop everything the outside of the building cannot see
        culled, note = cull_hidden_faces(bm)
        if note:
            self.report({"WARNING"}, note)

        # 6. Remove the edges left between the assets. Faces that are flat with
        #    each other and carry the same material become one face, which is
        #    what stitches the panels into a continuous wall instead of a grid
        #    of tiles. Delimiting on material keeps a texture boundary from
        #    being merged away.
        faces_before = len(bm.faces)
        bmesh.ops.dissolve_limit(bm, angle_limit=DISSOLVE_ANGLE,
                                 verts=bm.verts[:], edges=bm.edges[:],
                                 delimit={"MATERIAL"})
        merged = faces_before - len(bm.faces)

        bm.to_mesh(me)
        bm.free()
        me.update()

        obj.data.calc_loop_triangles()
        after = len(obj.data.loop_triangles)
        self.report({"INFO"},
                    "%d modules -> 1 mesh: %d -> %d tris, %d hidden faces "
                    "deleted, %d seams dissolved, %d material slots merged "
                    "(%d left)"
                    % (len(parts), before, after, culled, merged, dropped,
                       len(obj.data.materials)))
        return {"FINISHED"}


# =============================================================================
# properties / UI
# =============================================================================
def _load_library_builder():
    """Find the module-library builder.

    Installing a single .py copies it into Blender's addons folder and leaves
    any sibling files behind, so try the packaged form first and fall back to a
    loose file next to this one (or in the project folder) for development.

    The Levant builder is preferred where present: it produces both waves, so
    the button yields the whole 19-module library rather than the first five.
    """
    try:
        from . import levant_library       # installed as a package/.zip
        return levant_library
    except Exception:
        pass
    try:
        from . import me_library
        return me_library
    except Exception:
        pass
    import os
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    proj = os.path.join(os.path.expanduser("~"), "Desktop", "BuildingGen")
    for cand in (os.path.join(here, "make_levant_library.py"),
                 os.path.join(here, "levant_library.py"),
                 os.path.join(proj, "make_levant_library.py"),
                 os.path.join(here, "make_me_library.py"),
                 os.path.join(here, "me_library.py"),
                 os.path.join(proj, "make_me_library.py")):
        if os.path.exists(cand):
            spec = importlib.util.spec_from_file_location("_me_lib", cand)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m
    return None


_ENUM_KEEP = []      # Blender needs the item strings kept alive by Python


def _stable_id(name, taken):
    """A number for an enum item that depends only on its name.

    Blender stores a dynamic EnumProperty as the item's NUMBER, not its
    identifier. With auto-numbering the number is just the position, so adding
    one section renumbers every later entry -- 'lib_balconies' sorts first, so
    after it appeared every saved selection silently pointed one library to the
    left. Deriving the number from the name pins a selection to the library it
    was actually made on.
    """
    import zlib
    n = zlib.crc32(name.encode("utf8")) & 0x3FFFFFF
    while n in taken:          # collisions are vanishingly rare, but cheap to fix
        n += 1
    taken.add(n)
    return n


def library_enum_items(self, context):
    scene = context.scene
    items = [("AUTO", "Auto (module's own slot)",
              "Only offer assets from the collection this module came from")]
    loaded = library_collections(scene)
    for cn in loaded:
        n = len(assets_in(cn))
        items.append((cn, cn, "Use %s (%d assets)" % (cn, n)))

    # Sections sitting on disk that nothing has imported yet. They used to be
    # invisible until a manual Refresh, which is what made new libraries look
    # like they had not been added at all.
    p = getattr(scene, "blm_props", None)
    if p is not None and p.asset_folder:
        for s in sections_in(p.asset_folder):
            cn = folder_collection_name(p.asset_folder, s)
            if cn not in loaded:
                items.append((cn, cn + "   (not loaded)",
                              "On disk but not imported yet -- press Refresh "
                              "From Folder"))

    # "Auto" must be number 0: an EnumProperty that has never been set stores 0,
    # and with every number derived from a name there was nothing at 0 for it to
    # resolve to -- so the dropdown silently read as some other library, and the
    # swap operator refused every asset as "different slot".
    taken = {0}
    numbered = [(i[0], i[1], i[2],
                 0 if i[0] == "AUTO" else _stable_id(i[0], taken))
                for i in items]
    _ENUM_KEEP.clear()
    _ENUM_KEEP.extend(numbered)
    return _ENUM_KEEP


class BLM_OT_make_library(bpy.types.Operator):
    """Build the built-in low-poly Middle Eastern module library"""
    bl_idname = "blm.make_library"
    bl_label = "Create Middle Eastern Library"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mod = _load_library_builder()
        if mod is None:
            self.report({"ERROR"}, "Could not find the library builder. Install "
                                   "the .zip, or keep make_me_library.py next to "
                                   "this file.")
            return {"CANCELLED"}
        builder = getattr(mod, "build_full_library", mod.build_library)
        col, objs = builder(context.scene)
        context.scene.blm_props.library = col.name
        self.report({"INFO"}, "Built %s with %d modules"
                    % (col.name, len(objs)))
        return {"FINISHED"}


AXIS_ITEMS = (("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", ""),
              ("NEGATIVE_X", "-X", ""), ("NEGATIVE_Y", "-Y", ""),
              ("NEGATIVE_Z", "-Z", ""))


class BLM_Props(bpy.types.PropertyGroup):
    asset_folder: StringProperty(
        name="Asset Folder", subtype="DIR_PATH", default="",
        description="Folder of .obj files. Drop files in here and press "
                    "Refresh -- the folder is the library")
    folder_fit: bpy.props.EnumProperty(
        name="Auto-fit",
        items=(("WIDTH", "Fit width (keep shape)",
                "Scale uniformly so each asset is exactly 3 m wide"),
               ("STRETCH", "Stretch to slot",
                "Scale X and Z independently to fill the slot exactly"),
               ("NONE", "Leave as-is", "Only re-origin, do not rescale")),
        default="WIDTH")
    slot_height: FloatProperty(name="Slot Height", default=3.0, min=0.1, max=20.0)
    auto_sync: BoolProperty(
        name="Auto Refresh On Open", default=True,
        description="Re-read the asset folder when this .blend is opened, so "
                    "modules and sections added since it was saved show up "
                    "without pressing Refresh")
    folder_only: BoolProperty(
        name="Folder Only", default=True,
        description="List only the asset folder's sections as libraries. Turn "
                    "off to also show collections that live inside this .blend "
                    "(Buildify's own, or one made by Create Library)")
    obj_forward: bpy.props.EnumProperty(
        name="Forward", items=AXIS_ITEMS, default="NEGATIVE_Z",
        description="OBJ forward axis; the default round-trips Blender's own "
                    "OBJ exporter")
    obj_up: bpy.props.EnumProperty(
        name="Up", items=AXIS_ITEMS, default="Y",
        description="OBJ up axis")
    library: bpy.props.EnumProperty(
        name="Library", items=library_enum_items,
        description="Which module collection the swap grid draws from")
    building: PointerProperty(
        type=bpy.types.Object, name="Building",
        description="Object carrying the Buildify modifier",
        poll=lambda self, o: o.type == "MESH")
    modules_collection: PointerProperty(type=bpy.types.Collection, name="Modules")

    # ---- stage 1: build ---------------------------------------------------
    module_style: bpy.props.EnumProperty(
        name="Module Kit",
        description="Which kit of facade modules the building is built from",
        items=(("BUILDIFY", "Buildify (stock)",
                "The modules that ship with Buildify"),
               ("LEVANT", "Middle Eastern (custom)",
                "The me_* modules in the asset folder")),
        default="BUILDIFY")
    module_prefix: StringProperty(
        name="Name Filter", default="me_",
        description="Only load .obj files whose name starts with this. The "
                    "asset folder also holds Buildify's own exported modules, "
                    "which would otherwise be mixed into the custom kit")
    build_height: FloatProperty(
        name="Height", default=10.0, min=0.1,
        description="Target height; the floor count follows from it")
    use_attr: BoolProperty(
        name="Use Attribute", default=False,
        description="Read the height from a custom attribute instead, so a "
                    "whole imported shapefile can build at once")
    attr_name: StringProperty(
        name="Attribute Name", default="RELATIVE_F",
        description="Attribute to read the height from")



class BLM_PT_build(bpy.types.Panel):
    """Stage one: turn a footprint into a building, then bake it to a mesh."""
    bl_label = "1 - Build"
    bl_idname = "BLM_PT_build"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Building"
    bl_order = 0

    def draw(self, context):
        lay = self.layout
        p = context.scene.blm_props

        box = lay.box()
        box.label(text="Module Kit", icon="ASSET_MANAGER")
        box.prop(p, "module_style", text="")
        if p.module_style == "LEVANT":
            box.prop(p, "asset_folder", text="")
            box.prop(p, "module_prefix")
            box.operator("object.buildify_load_modules", icon="IMPORT")
            counts = []
            for role in ("ground", "middle", "trim"):
                col = bpy.data.collections.get(ROLE_COLLECTION[role])
                counts.append("%s %d" % (role, len(col.objects) if col else 0))
            box.label(text=" / ".join(counts), icon="INFO")
        box.operator("object.buildify_apply_style", icon="FILE_REFRESH")

        box = lay.box()
        box.label(text="Footprint", icon="MESH_PLANE")
        box.prop(p, "use_attr")
        if p.use_attr:
            box.prop(p, "attr_name")
        else:
            box.prop(p, "build_height", text="Height (m)")
        row = box.row()
        row.scale_y = 1.3
        row.operator("object.buildify_generate", icon="MOD_BUILD")


class BLM_PT_main(bpy.types.Panel):
    bl_label = "2 - Customize"
    bl_idname = "BLM_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Building"
    bl_order = 1

    def draw(self, context):
        lay = self.layout
        scene = context.scene
        p = scene.blm_props

        # ---- asset folder --------------------------------------------------
        import os
        box = lay.box()
        box.label(text="Asset Folder", icon="FILE_FOLDER")
        box.prop(p, "asset_folder", text="")
        folder = bpy.path.abspath(p.asset_folder) if p.asset_folder else ""
        valid = bool(folder) and os.path.isdir(folder)

        row = box.row(align=True)
        row.scale_y = 1.2
        sub = row.row(align=True)
        sub.enabled = valid
        sub.operator("blm.import_asset_file", text="", icon="ADD")
        sub.operator("blm.sync_folder", text="Refresh", icon="FILE_REFRESH")
        sub.operator("blm.open_asset_folder", text="", icon="FILEBROWSER")
        box.prop(p, "auto_sync")

        if not p.asset_folder:
            box.label(text="Pick a folder of .obj files", icon="INFO")
        elif not valid:
            box.label(text="Folder not found", icon="ERROR")
        else:
            by_section = scan_all_sections(folder)
            if not by_section:
                box.label(text="No .obj files found here yet", icon="INFO")
            stale = 0
            for section, files in by_section.items():
                cname = folder_collection_name(folder, section)
                col = bpy.data.collections.get(cname)
                loaded = len(col.objects) if col else 0
                synced = (loaded == len(files))
                stale += 0 if synced else 1
                r = box.row(align=True)
                r.label(text="%-12s %d obj" % (section or "(root)", len(files)),
                        icon="CHECKMARK" if synced else "FILE_REFRESH")
                if not synced:
                    r.label(text="%d loaded" % loaded)
            if stale:
                box.label(text="Folder changed - press Refresh", icon="ERROR")
            box.prop(p, "folder_only")
            r = box.row(align=True)
            r.prop(p, "folder_fit", text="")
            if p.folder_fit == "STRETCH":
                r.prop(p, "slot_height", text="H")
            r = box.row(align=True)
            r.prop(p, "obj_forward")
            r.prop(p, "obj_up")

        libs = library_collections(scene)
        if not libs:
            box = lay.box()
            box.label(text="No module library yet", icon="ERROR")
            box.operator("blm.make_library", icon="ASSET_MANAGER")
            return

        # ---- build ---------------------------------------------------------
        box = lay.box()
        box.label(text="Build", icon="MOD_BUILD")
        box.prop(p, "building")
        row = box.row()
        row.scale_y = 1.3
        row.operator("blm.modularize", icon="OUTLINER_OB_GROUP_INSTANCE")
        if COLLECTION_ME not in bpy.data.collections:
            box.operator("blm.make_library", icon="ASSET_MANAGER")
        if p.modules_collection:
            box.label(text="%d modules in %s"
                      % (len(p.modules_collection.objects),
                         p.modules_collection.name), icon="CHECKMARK")

        # ---- selection -----------------------------------------------------
        mods = selected_modules(context)
        act = context.active_object

        if not mods:
            b = lay.box()
            b.label(text="Click a module in the viewport",
                    icon="RESTRICT_SELECT_OFF")
            if act is not None and not is_module(act):
                b.label(text="'%s' is not a module" % act.name, icon="INFO")
            meshes = [o for o in context.selected_objects if o.type == "MESH"]
            if meshes:
                b.operator("blm.export_to_folder", icon="EXPORT")
            return

        slots = {o.get(P_SLOT, "") for o in mods}
        box = lay.box()
        col = box.column(align=True)
        if len(mods) == 1:
            ob = mods[0]
            cur_name = current_asset(ob)
            col.label(text=ob.name, icon="MESH_PLANE")
            col.label(text="Asset:  %s" % asset_label(cur_name))
            col.label(text="Slot:   %s" % (ob.get(P_SLOT) or "not swappable"))
            if cur_name != ob.get(P_ORIG, cur_name):
                col.label(text="Was:    %s" % ob.get(P_ORIG), icon="LOOP_BACK")
        else:
            col.label(text="%d modules selected" % len(mods), icon="MESH_PLANE")
            col.label(text="Slots:  %s" % ", ".join(sorted(s for s in slots if s)))

        # ---- the library ---------------------------------------------------
        active_slots = [s for s in slots if s]
        if not active_slots:
            lay.box().label(text="These are props, not swappable modules.",
                            icon="INFO")
            return
        if len(active_slots) > 1:
            lay.box().label(text="Select modules from one slot at a time.",
                            icon="ERROR")
            return

        slot = active_slots[0]
        source = slot if p.library == "AUTO" else p.library
        cands = assets_in(source)
        current = current_asset(mods[0]) if len(mods) == 1 else None

        box = lay.box()
        box.label(text="Library  (%d sections)" % len(libs),
                  icon="ASSET_MANAGER")
        box.prop(p, "library", text="")
        r = box.row(align=True)
        r.operator("blm.import_asset_file", text="Add File", icon="ADD")
        r.operator("blm.export_to_folder", text="Save Selection", icon="EXPORT")
        if p.library != "AUTO" and p.library != slot:
            box.label(text="Cross-library: module came from %s" % slot,
                      icon="INFO")

        if not any(preview_icon(c) for c in cands):
            box.operator("blm.gen_previews", icon="RENDER_RESULT")

        row = box.row(align=True)
        row.scale_y = 1.3
        row.operator("blm.cycle", text="", icon="TRIA_LEFT").delta = -1
        row.label(text=asset_label(current) if current
                  else "%d selected" % len(mods))
        row.operator("blm.cycle", text="", icon="TRIA_RIGHT").delta = 1

        grid = box.grid_flow(row_major=True, columns=GRID_COLUMNS,
                             even_columns=True, even_rows=False)
        for name in cands:
            cell = grid.column(align=True)
            icon_id = preview_icon(name)
            if icon_id:
                cell.template_icon(icon_value=icon_id, scale=THUMB_SCALE)
            else:
                sub = cell.box()
                sub.scale_y = THUMB_SCALE * 0.6
                sub.label(text="", icon="MESH_PLANE")
            short = asset_label(name).replace(source.rstrip("s") + "_", "")
            short = short.replace("lib_", "").replace("_", " ")
            op = cell.operator("blm.swap", text=short,
                               depress=(name == current))
            op.asset = name

        # ---- edits ---------------------------------------------------------
        box = lay.box()
        box.label(text="Edit", icon="MODIFIER")
        r = box.row(align=True)
        r.operator("blm.revert", icon="LOOP_BACK")
        r.operator("blm.delete", text="", icon="TRASH")


class BLM_PT_finish(bpy.types.Panel):
    """Stage three: flatten the finished building into a game-ready mesh.

    This runs last on purpose. Baking removes the Buildify modifier and joins
    everything into one mesh, so nothing above it -- swapping a panel, nudging
    a module -- can work afterwards.
    """
    bl_label = "3 - Finish"
    bl_idname = "BLM_PT_finish"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Building"
    bl_order = 2

    def draw(self, context):
        lay = self.layout
        p = context.scene.blm_props

        box = lay.box()
        box.label(text="Select the building, then:", icon="INFO")
        row = box.row()
        row.scale_y = 1.6
        row.operator("object.buildify_optimize", icon="MESH_DATA")
        lay.operator("blm.export_fbx", icon="EXPORT")


CLASSES = (BLM_Props, BLM_OT_make_library, BLM_OT_gen_previews,
           BLM_OT_add_asset, BLM_OT_sync_folder, BLM_OT_import_asset_file,
           BLM_OT_open_asset_folder, BLM_OT_export_selected_to_folder,
           BUILDIFY_OT_load_modules, BUILDIFY_OT_apply_style,
           BUILDIFY_OT_generate, BUILDIFY_OT_optimize,
           BLM_OT_modularize, BLM_OT_swap,
           BLM_OT_cycle, BLM_OT_revert, BLM_OT_select_same, BLM_OT_select_slot,
           BLM_OT_delete, BLM_OT_export_fbx,
           BLM_PT_build, BLM_PT_main, BLM_PT_finish)


def _autosync():
    """Re-read the asset folder for every scene that has one configured.

    Runs from a timer rather than straight out of the load handler: creating
    datablocks while Blender is still opening the file is not safe.
    """
    for scene in bpy.data.scenes:
        p = getattr(scene, "blm_props", None)
        if p is None or not p.asset_folder or not p.auto_sync:
            continue
        try:
            counts, _ = sync_asset_folder(scene)
        except Exception as e:            # never let a handler break file load
            print("[buildify_modular] auto-sync skipped: %s" % e)
            continue
        if counts[1] or counts[2] or counts[3]:
            print("[buildify_modular] auto-sync %r: %d new, %d updated, "
                  "%d removed" % (scene.name, counts[1], counts[2], counts[3]))
    for w in bpy.data.window_managers:
        for win in w.windows:
            for area in win.screen.areas:
                area.tag_redraw()
    return None                            # one shot


@bpy.app.handlers.persistent
def _on_load(_dummy):
    # a saved .blend only holds the modules that existed when it was saved, so
    # new .obj files and whole new sections are invisible until something
    # imports them -- which is why new libraries looked like they never arrived
    bpy.app.timers.register(_autosync, first_interval=0.2)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.blm_props = PointerProperty(type=BLM_Props)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    # tolerate a partially-registered state (e.g. the module was also loaded
    # manually by a script while the add-on was enabled)
    try:
        del bpy.types.Scene.blm_props
    except Exception:
        pass
    for c in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(c)
        except Exception:
            pass


if __name__ == "__main__":
    register()
