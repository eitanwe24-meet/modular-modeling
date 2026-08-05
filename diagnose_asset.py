"""Why does this asset's texture look different from the .obj file?

Open this in Blender's Text Editor, select the asset (or a placed module),
press Run Script, and read the report it leaves in a text block called
"asset_report" -- also printed to the system console.

It reports the things that actually change how big a texture looks, in the
order they are worth suspecting, and says which are fine and which are not.
Nothing is modified.
"""
import os

import bmesh
import bpy

LINES = []


def say(fmt, *a):
    LINES.append(fmt % a if a else fmt)


def head(t):
    say("")
    say("=" * 68)
    say(t)
    say("=" * 68)


def uv_area(face, layer):
    uvs = [l[layer].uv for l in face.loops]
    a = 0.0
    for i in range(len(uvs)):
        u0, v0 = uvs[i]
        u1, v1 = uvs[(i + 1) % len(uvs)]
        a += u0 * v1 - u1 * v0
    return abs(a) * 0.5


def coord_source(mat):
    """What the image node is actually reading its coordinates from.

    This is the one that hides best: a texture driven by Generated or Object
    coordinates rescales when the mesh is scaled into the module slot, and the
    UV data looks perfectly correct the whole time.
    """
    if not mat or not mat.use_nodes:
        return "no nodes"
    out = []
    for node in mat.node_tree.nodes:
        if node.type != "TEX_IMAGE":
            continue
        img = node.image.name if node.image else "NO IMAGE"
        missing = ""
        if node.image:
            path = bpy.path.abspath(node.image.filepath)
            if node.image.packed_file is None and path and not os.path.isfile(path):
                missing = "  <-- FILE MISSING: %s" % path
        vec = node.inputs["Vector"]
        if not vec.is_linked:
            src = "UV (active layer, default)"
        else:
            up = vec.links[0].from_node
            if up.type == "UVMAP":
                src = "UV layer %r" % (up.uv_map or "(active)")
            elif up.type == "TEX_COORD":
                sock = vec.links[0].from_socket.name
                src = "Texture Coordinate > %s" % sock
            elif up.type == "MAPPING":
                src = "Mapping node (scale %s)" % (
                    tuple(round(v, 3) for v in up.inputs["Scale"].default_value))
            else:
                src = up.type
        out.append("%s | %s | %s%s" % (img, src, node.extension, missing))
    return "; ".join(out) if out else "no image texture"


ob = bpy.context.active_object
if ob is None or ob.type != "MESH":
    LINES.append("Select a mesh object first.")
else:
    me = ob.data
    head("OBJECT  %s" % ob.name)
    say("mesh datablock   %s   (used by %d object(s))", me.name, me.users)
    say("dimensions       %.3f x %.3f x %.3f m", *ob.dimensions)
    say("object scale     %.4f, %.4f, %.4f", *ob.scale)
    if any(abs(s - 1.0) > 1e-4 for s in ob.scale):
        say(">>> object scale is not 1. The texture stretches with the object,")
        say("    and non-uniform scale stretches it unevenly. Ctrl+A > Scale.")
    if ob.get("bld_slot") is not None:
        say("add-on slot      %s", ob.get("bld_slot") or "(none)")
        say("showing asset    %s", ob.get("bld_asset"))

    head("UV LAYERS")
    if not me.uv_layers:
        say(">>> NO UV LAYER AT ALL.")
        say("    Every face samples the same corner of the image, which reads")
        say("    as a texture at the wrong scale rather than a missing one.")
        say("    If this asset was imported before the UV fix, the mesh in this")
        say("    .blend is the OLD one -- see STALE LIBRARY below.")
    else:
        for layer in me.uv_layers:
            mark = " (ACTIVE, what a texture reads by default)" \
                if layer is me.uv_layers.active else ""
            say("  %-24s%s", layer.name, mark)
        if len(me.uv_layers) > 1:
            say(">>> more than one UV layer. If the material names a specific")
            say("    one and that name did not survive, it silently falls back.")

        bm = bmesh.new()
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        layer = bm.loops.layers.uv.active
        us = [l[layer].uv[0] for f in bm.faces for l in f.loops]
        vs = [l[layer].uv[1] for f in bm.faces for l in f.loops]
        say("u range          %.3f .. %.3f", min(us), max(us))
        say("v range          %.3f .. %.3f", min(vs), max(vs))

        per_face = []
        for f in bm.faces:
            ga, ua = f.calc_area(), uv_area(f, layer)
            if ga > 1e-12 and ua > 1e-12:
                per_face.append((ua / ga) ** 0.5)
        if per_face:
            per_face.sort()
            lo, mid, hi = (per_face[0], per_face[len(per_face) // 2],
                           per_face[-1])
            say("tiles per metre  %.4f low / %.4f median / %.4f high",
                lo, mid, hi)
            if hi > lo * 1.5:
                say(">>> the texture is a different size on different faces.")
                say("    That is the per-face mapping. Customize > Edit >")
                say("    Spread Texture Across Faces evens it out.")
        n_whole = sum(1 for f in bm.faces
                      if abs(uv_area(f, layer) - 1.0) < 0.05)
        if n_whole:
            say(">>> %d face(s) carry the WHOLE image on their own (uv area 1).",
                n_whole)
            say("    Spread Texture Across Faces is what this is for.")
        bm.free()

    head("MATERIALS  (where the texture really comes from)")
    if not me.materials:
        say(">>> no material on this mesh.")
    for mat in me.materials:
        say("  %s", mat.name if mat else "(empty slot)")
        say("      %s", coord_source(mat))
        if mat and mat.name[-4:-3] == "." and mat.name[-3:].isdigit():
            say("      >>> a .001 copy. Each import makes another one, and")
            say("          edits to one do not reach the others.")
    for mat in me.materials:
        if mat and mat.use_nodes:
            for node in mat.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.extension != "REPEAT":
                    say(">>> image extension is %s, not Repeat. Any UV outside",
                        node.extension)
                    say("    0-1 smears the edge pixel instead of tiling.")
                    break

    head("SLOT FITTING  (the add-on scales assets into a 3 m slot)")
    p = getattr(bpy.context.scene, "blm_props", None)
    if p is None:
        say("add-on not enabled, cannot read the fit setting")
    else:
        fit = getattr(p, "folder_fit", "?")
        say("folder fit       %s", fit)
        if fit == "STRETCH":
            say(">>> STRETCH scales X and Z by different amounts. The geometry")
            say("    is distorted, so the texture on it is too. Use Width.")
        elif fit == "WIDTH":
            say("    Width scales uniformly so the asset is 3 m wide. UVs are")
            say("    untouched, but the texture is now that much bigger or")
            say("    smaller PER METRE than in the file. If your asset was")
            say("    already 3 m wide, the scale factor is 1 and nothing moves.")
        say("")
        say("An asset authored at 3 m wide imports at scale 1. Anything else")
        say("is rescaled, and a tiled texture visibly changes density.")

    head("STALE LIBRARY  (the most common reason a fix 'did not work')")
    say("Refresh From Folder imports files it does not already have. An asset")
    say("already in this .blend keeps the mesh it was imported with -- so a")
    say("mesh built by the old UV-dropping code stays broken until it is")
    say("actually re-imported.")
    say("")
    say("To force it: delete the library collection for that section in the")
    say("Outliner (or delete the asset object), then press Refresh From")
    say("Folder. Check above that a UV layer now exists.")

text = bpy.data.texts.get("asset_report") or bpy.data.texts.new("asset_report")
text.clear()
text.write("\n".join(LINES))
print("\n".join(LINES))
print("\n[written to text block 'asset_report' -- open it in the Text Editor]")
