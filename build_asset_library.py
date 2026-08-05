"""
Export every module from Buildify and the Middle Eastern library into a
sectioned folder tree of .obj files.

    <root>/
        walls/      plain wall panels
        windows/    panels with a window opening
        doors/      ground-floor entries
        trim/       cornice / parapet bands
        pillars/    corner pieces
        roof/       rooftop details
        props/      signs, AC units, satellites

Files are written with Blender's default OBJ axes (-Z forward, Y up), which is
exactly what the add-on imports with by default, so they round-trip unchanged.

Run:
    blender -b buildify_1.0.blend --python build_asset_library.py -- <root>
"""

import importlib.util
import os
import sys

import bpy

HERE = r"C:\Users\User\Desktop\BuildingGen"
SECTIONS = ("walls", "windows", "doors", "trim", "pillars", "roof", "props")

# explicit placement for the modules we authored
ME_SECTION = {
    "me_1_solid": "walls",
    "me_2_window_arch": "windows",
    "me_3_mashrabiya": "windows",
    "me_4_door_arch": "doors",
    "me_5_parapet": "trim",
}


def section_for(obj_name, collection_name):
    """Where a module belongs. Explicit for ours, by collection for Buildify's."""
    if obj_name in ME_SECTION:
        return ME_SECTION[obj_name]
    c = (collection_name or "").lower()
    n = obj_name.lower()
    if "pillar" in c or "pillar" in n:
        return "pillars"
    if "roof" in c or "rooftop" in c:
        return "roof"
    if "detail" in c:
        return "props"
    if "trim" in c or "trim" in n:
        return "trim"
    if "wall" in c or "wall" in n:
        return "walls"
    return "props"


def collect(scene):
    """(object, section) for every module-like asset in the file."""
    import blm_mod as blm
    out, seen = [], set()
    for cn in blm.library_collections(scene):
        col = bpy.data.collections.get(cn)
        if not col:
            continue
        for ob in col.objects:
            if ob.type != "MESH" or ob.name in seen:
                continue
            seen.add(ob.name)
            out.append((ob, section_for(ob.name, cn)))
    # rooftop / facade props live in collections the add-on does not treat as
    # libraries, but they are still useful assets
    for cn in ("rooftop_details _small", "rooftop_details_medium",
               "rooftop_details_large", "details_first_floor",
               "details_other_floor"):
        col = bpy.data.collections.get(cn)
        if not col:
            continue
        for ob in col.objects:
            if ob.type == "MESH" and ob.name not in seen:
                seen.add(ob.name)
                out.append((ob, section_for(ob.name, cn)))
    return out


def export_one(ob, path):
    """Export a single object at its own origin, modifiers applied."""
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    hidden = ob.hide_get()
    ob.hide_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob

    loc = ob.matrix_world.copy()
    ob.matrix_world.identity()             # write it at the origin
    try:
        bpy.ops.wm.obj_export(
            filepath=path, export_selected_objects=True,
            export_materials=True, apply_modifiers=True,
            forward_axis="NEGATIVE_Z", up_axis="Y")
    finally:
        ob.matrix_world = loc
        ob.hide_set(hidden)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    root = argv[0] if argv else os.path.join(
        os.path.expanduser("~"), "Desktop", "BuildingAssets")

    spec = importlib.util.spec_from_file_location(
        "blm_mod", os.path.join(HERE, "buildify_modular.py"))
    blm = importlib.util.module_from_spec(spec)
    sys.modules["blm_mod"] = blm
    spec.loader.exec_module(blm)
    blm.register()

    scene = bpy.context.scene

    # make sure our own library exists in this file before exporting it
    if "lib_middle_eastern" not in bpy.data.collections:
        mkspec = importlib.util.spec_from_file_location(
            "mk", os.path.join(HERE, "make_me_library.py"))
        mk = importlib.util.module_from_spec(mkspec)
        sys.modules["mk"] = mk
        mkspec.loader.exec_module(mk)
        mk.build_library(scene)

    for s in SECTIONS:
        os.makedirs(os.path.join(root, s), exist_ok=True)

    items = collect(scene)
    print("\n%-30s %-10s %s" % ("object", "section", "tris"))
    print("-" * 60)
    counts = {s: 0 for s in SECTIONS}
    skipped = []
    for ob, section in sorted(items, key=lambda t: (t[1], t[0].name)):
        me = ob.data
        if not me.vertices or not me.polygons:
            skipped.append("%s (empty)" % ob.name)
            continue
        me.calc_loop_triangles()
        path = os.path.join(root, section, "%s.obj" % ob.name)
        export_one(ob, path)
        counts[section] += 1
        print("%-30s %-10s %d" % (ob.name, section, len(me.loop_triangles)))

    print("\n" + "=" * 60)
    print("root: %s" % root)
    for s in SECTIONS:
        n = len(       [f for f in os.listdir(os.path.join(root, s))
                        if f.lower().endswith(".obj")])
        print("  %-10s %2d obj" % (s + "/", n))
    print("total exported: %d" % sum(counts.values()))
    if skipped:
        print("skipped: %s" % ", ".join(skipped))


if __name__ == "__main__":
    main()
