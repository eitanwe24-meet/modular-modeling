"""Building wizard: a shapefile of footprints in, a folder of FBX models out.

Reads a polygon shapefile of buildings, builds each one through Buildify at
the height its attribute gives, and exports it as its own .fbx. Writes a table
linking every footprint to the model made from it, so the models can be placed
back on a point layer.

Run:
    wizard.bat --shp C:\\data\\buildings.shp --out C:\\data\\models

or directly:
    blender -b buildify_1.0.blend --python building_wizard.py -- --shp ... --out ...

Options:
    --height-field NAME   attribute holding the height in metres (RELATIVE_F)
    --id-field NAME       attribute to name models after; auto-detected if not
                          given, sequential if nothing unique is found
    --full                run the hidden-face cull and seam dissolve as well.
                          Much slower: this is most of the runtime on a batch
    --points              also write a point shapefile of the centroids
    --limit N             only the first N buildings, for a trial run
    --dry-run             read and report, build nothing
    --heading gis|math    how @mref_rotate_heading is measured. gis, the
                          default, is degrees clockwise from north; math is
                          degrees anticlockwise from east
    --no-canonical        keep each model at the angle its footprint sits at,
                          and report a heading of 0

Each model is built with its main facade along +X whatever angle the building
sits at on the ground, and @mref_rotate_heading says how far to turn it to put
it back. Two identical blocks at different angles then produce identical
models, and the placement carries the difference.

Every model is built at its own origin, not at its map coordinates: a city in
a projected CRS sits hundreds of kilometres from zero, where single-precision
floats have decimetre gaps and the geometry visibly wobbles. The real position
travels in the table instead.
"""

import csv
import math
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import shapefile_io as sio          # noqa: E402  (needs the path set first)

MODULE_HEIGHT = 3.0                 # Buildify's module, and so its floor
ID_CANDIDATES = ("OBJECTID", "OBJECTID_1", "FID", "OID", "ID", "GID",
                 "BLDG_ID", "BUILDING_ID", "BUILDINGID", "OSM_ID", "UUID",
                 "CODE", "MS_KAYAN", "BLD_ID")
MODEL_FIELD = "@mref_model"
HEADING_FIELD = "@mref_rotate_heading"


# ---------------------------------------------------------------------------
# arguments
# ---------------------------------------------------------------------------
def ensure_addon():
    """Make the Buildify operators available, however this was started.

    Prefers the installed add-on, and falls back to loading the source file
    sitting next to this one -- so the wizard runs on a machine where the
    add-on was never installed through Blender's preferences, which is the
    normal state of a build server.
    """
    if hasattr(bpy.ops.object, "buildify_generate"):
        try:
            bpy.ops.preferences.addon_enable(module="buildify_modular")
            return "installed add-on"
        except Exception:
            pass

    import importlib.util
    src = os.path.join(HERE, "buildify_modular.py")
    if not os.path.isfile(src):
        raise SystemExit("buildify_modular.py is not next to building_wizard.py"
                         " and the add-on is not installed")
    spec = importlib.util.spec_from_file_location("buildify_modular_src", src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["buildify_modular_src"] = mod
    spec.loader.exec_module(mod)
    mod.register()
    return "source file"


def parse_args(argv):
    args = {"shp": None, "out": None, "height-field": "RELATIVE_F",
            "id-field": None, "limit": 0, "full": False, "points": False,
            "dry-run": False, "heading": "gis", "no-canonical": False}
    i = 0
    while i < len(argv):
        key = argv[i].lstrip("-")
        if key in ("full", "points", "dry-run", "no-canonical"):
            args[key] = True
            i += 1
        elif key in args and i + 1 < len(argv):
            args[key] = argv[i + 1]
            i += 2
        else:
            raise SystemExit("unknown or incomplete option: %s" % argv[i])
    if not args["shp"] or not args["out"]:
        raise SystemExit("--shp and --out are both required")
    args["limit"] = int(args["limit"] or 0)
    return args


# ---------------------------------------------------------------------------
# reading the layer
# ---------------------------------------------------------------------------
def looks_like_degrees(polys):
    """A layer still in lat/long, which would build millimetre-wide houses."""
    for poly in polys:
        for x, y in poly["outer"]:
            if abs(x) > 180.0 or abs(y) > 90.0:
                return False
    return True


def to_metres(polys):
    """Degrees to metres on a tangent plane at the middle of the data.

    A degree of longitude is shorter than a degree of latitude by cos(lat), so
    a single scale factor leaves every footprint stretched east to west.
    """
    xs = [x for p in polys for x, _ in p["outer"]]
    ys = [y for p in polys for _, y in p["outer"]]
    lat0 = (min(ys) + max(ys)) * 0.5
    rad = math.radians(lat0)
    kx = 111412.84 * math.cos(rad) - 93.5 * math.cos(3 * rad)
    ky = (111132.92 - 559.82 * math.cos(2 * rad) + 1.175 * math.cos(4 * rad))
    for p in polys:
        p["outer"] = [(x * kx, y * ky) for x, y in p["outer"]]
        p["holes"] = [[(x * kx, y * ky) for x, y in r] for r in p["holes"]]
        p["centroid"] = (p["centroid"][0] * kx, p["centroid"][1] * ky)
    return kx, ky


def pick_id_field(polys, forced=None):
    """Which attribute names the models.

    Requires the values to be unique, because they become file names: two
    buildings claiming the same name would silently overwrite each other and
    the table would point half the points at the wrong model.
    """
    if forced:
        vals = [p["attrs"].get(forced) for p in polys]
        if any(v is None for v in vals):
            return None, "%r is missing on some rows" % forced
        if len(set(map(str, vals))) != len(vals):
            return None, "%r is not unique" % forced
        return forced, "forced"

    names = list(polys[0]["attrs"].keys()) if polys else []
    ordered = [n for n in ID_CANDIDATES if n in names]
    ordered += [n for n in names if n not in ordered]
    for name in ordered:
        vals = [p["attrs"].get(name) for p in polys]
        if any(v is None or v == "" for v in vals):
            continue
        if len(set(map(str, vals))) == len(vals):
            return name, "auto"
    return None, "no unique field found"


def model_name(poly, id_field, n):
    if id_field is not None:
        raw = poly["attrs"].get(id_field)
        text = ("%d" % raw) if isinstance(raw, float) and raw.is_integer() \
            else str(raw)
        safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in text)
        return "bld_%s" % safe
    return "bld_%04d" % (n + 1)


# ---------------------------------------------------------------------------
# building one
# ---------------------------------------------------------------------------
def principal_direction(ring):
    """Which way the building faces, as an angle anticlockwise from east.

    The compass direction carrying the most wall, not the single longest edge.
    A footprint digitised from aerial imagery has its long facade broken into
    several segments, and the longest single one of those is often shorter than
    an undivided end wall -- which would turn the building sideways.

    Directions are taken modulo 180 degrees, since a wall has an orientation
    but not a sense: a facade running east-west is the same wall either way.
    """
    buckets = {}
    for i in range(len(ring)):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % len(ring)]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length < 1e-9:
            continue
        key = round(math.degrees(math.atan2(dy, dx)) % 180.0, 1)
        buckets[key] = buckets.get(key, 0.0) + length
    if not buckets:
        return 0.0
    return math.radians(max(buckets, key=buckets.get))


def heading_from(theta, convention):
    """The angle to rotate a canonical model by, to put it back on the map.

    `theta` is anticlockwise from east, which is how the maths works out and
    is not how a heading is usually written. A GIS heading is clockwise from
    north, so the two differ by a reflection as well as a quarter turn -- get
    that wrong and every building is mirrored about the north-south axis,
    which looks plausible on a square plan and wrong on everything else.
    """
    deg = math.degrees(theta)
    if convention == "math":
        return round(deg % 360.0, 3)
    return round((90.0 - deg) % 360.0, 3)


def footprint_object(ring, name, canonical=True):
    """A flat face at the origin from one ring, wound so it faces up.

    Shapefile outer rings are closed and clockwise; Blender wants neither, and
    Buildify reads the border edges, so a doubled last vertex would put a
    zero-length edge in the wall run.

    With `canonical` the footprint is also turned so its main facade runs along
    +X. The model is then built in a fixed orientation whatever the building's
    angle on the ground, and the heading needed to put it back travels in the
    table. Two identical blocks at different angles come out as identical
    models, which is the point.

    Returns (object, map centre, theta) where theta is anticlockwise from east.
    """
    pts = list(ring)
    if len(pts) > 1 and abs(pts[0][0] - pts[-1][0]) < 1e-9 \
            and abs(pts[0][1] - pts[-1][1]) < 1e-9:
        pts.pop()
    clean = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - clean[-1][0]) > 1e-6 or abs(p[1] - clean[-1][1]) > 1e-6:
            clean.append(p)
    if len(clean) < 3:
        return None, None, 0.0
    if sio.signed_area(clean) < 0.0:          # clockwise: flip to face up
        clean.reverse()

    cx = sum(p[0] for p in clean) / len(clean)
    cy = sum(p[1] for p in clean) / len(clean)

    theta = principal_direction(clean) if canonical else 0.0
    c, s = math.cos(-theta), math.sin(-theta)
    local = []
    for x, y in clean:
        dx, dy = x - cx, y - cy
        local.append((dx * c - dy * s, dx * s + dy * c, 0.0))

    me = bpy.data.meshes.new(name)
    me.from_pydata(local, [], [list(range(len(local)))])
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob, (cx, cy), theta


def set_seed(group, seed, seen=None):
    """Vary the clutter between buildings.

    Buildify exposes no seed on the modifier -- the randomness lives on Random
    Value nodes inside the tree, so the seed is set on them directly. Walks
    nested groups, since the wall passes are group nodes of their own.
    """
    seen = seen if seen is not None else set()
    if group is None or group.name in seen:
        return 0
    seen.add(group.name)
    n = 0
    for node in group.nodes:
        socket = node.inputs.get("Seed")
        if socket is not None and hasattr(socket, "default_value"):
            socket.default_value = seed
            n += 1
        # a group node holds its tree in .node_tree; .node_group does not exist
        inner = getattr(node, "node_tree", None)
        if inner is not None:
            n += set_seed(inner, seed, seen)
    return n


def select_only(ob):
    """Make `ob` the one selected, active object.

    Goes through the view layer after an explicit update: removing objects
    leaves stale entries behind, and iterating them hands back None, which
    turned the second building of every run into a crash while the first one
    worked perfectly.
    """
    bpy.context.view_layer.update()
    for other in bpy.context.scene.objects:
        if other is not None:
            other.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob


def set_floors(ob, n):
    """Write the floor count straight onto the modifier.

    The add-on turns a height into floors with floor(h / 3), which builds
    about two metres short at every height -- fine when you are eyeballing a
    single building, wrong when the number came off a survey. The wizard sets
    the count itself, from a height mapping it measures.

    Only MIN and MAX are matched, never bare "FLOOR": the tree also has a
    boolean called "- Randomize floor numbers -", and writing an integer into
    it would silently turn floor randomisation on.
    """
    mod = next((m for m in ob.modifiers if m.type == "NODES"), None)
    if mod is None or mod.node_group is None:
        return False
    wrote = 0
    for item in mod.node_group.interface.items_tree:
        if item.item_type != "SOCKET":
            continue
        name = item.name.upper()
        if "FLOOR" not in name:
            continue
        if "MIN" in name or "MAX" in name:
            mod[item.identifier] = int(n)
            wrote += 1
    # writing mod[identifier] does not tag the object; without this the first
    # evaluation still uses the previous floor count
    ob.update_tag()
    bpy.context.view_layer.update()
    return wrote > 0


def measure_top(ob):
    """How tall the generated building actually is, instances included."""
    deps = bpy.context.evaluated_depsgraph_get()
    top = 0.0
    for inst in deps.object_instances:
        if not (inst.is_instance and inst.parent
                and inst.parent.original == ob):
            continue
        src = inst.object
        if src is None or src.type != "MESH":
            continue
        for v in src.data.vertices:
            z = (inst.matrix_world @ v.co).z
            if z > top:
                top = z
    return top


def calibrate(kit):
    """Measure what a floor is worth in this kit: top = a * floors + b.

    Measured rather than assumed, so a swapped module kit with a different
    module or trim height still lands on the right heights. Two builds are
    enough because the relationship is a straight line.
    """
    samples = []
    for n in (2, 5):
        ob, _origin, _theta = footprint_object(
            [(0, 0), (0, 9), (15, 9), (15, 0)], "_calib")
        select_only(ob)
        bpy.ops.object.buildify_generate()
        set_floors(ob, n)
        samples.append((n, measure_top(ob)))
        wipe(kit)
    (n0, t0), (n1, t1) = samples
    if abs(t1 - t0) < 1e-6:
        return MODULE_HEIGHT, 0.0
    a = (t1 - t0) / float(n1 - n0)
    return a, t0 - a * n0


def floors_for(height, a, b):
    """The floor count whose building comes closest to this height."""
    if a <= 1e-6:
        return max(1, int(round(height / MODULE_HEIGHT)))
    return max(1, int(round((height - b) / a)))


def build_one(ob, height, full, floors):
    """Generate, then bake to a single real mesh. True if anything came out."""
    p = bpy.context.scene.blm_props
    p.use_attr = False
    p.build_height = float(height)

    select_only(ob)
    bpy.ops.object.buildify_generate()
    set_floors(ob, floors)
    bpy.context.view_layer.update()

    bpy.ops.object.buildify_optimize(cull=full, dissolve=full)
    baked = bpy.context.active_object
    return baked if baked and baked.data and len(baked.data.polygons) else None


def export_fbx(ob, path):
    select_only(ob)
    bpy.ops.export_scene.fbx(filepath=path, use_selection=True,
                             apply_unit_scale=True, mesh_smooth_type="FACE",
                             path_mode="COPY", embed_textures=False)


def wipe(keep):
    """Clear away one building, so memory does not climb across the run.

    `keep` is everything that existed before the first building -- which is
    Buildify's own module library. Deleting by type instead took the kit with
    it: the first building came out perfect and every one after it was a bare
    two-triangle footprint, because there were no modules left to instance.
    """
    for ob in list(bpy.data.objects):
        if ob not in keep and ob.type in ("MESH", "EMPTY"):
            bpy.data.objects.remove(ob, do_unlink=True)
    for block in (bpy.data.meshes,):
        for item in list(block):
            if item.users == 0:
                block.remove(item)
    bpy.context.view_layer.update()


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------
def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = parse_args(argv)
    print("buildify operators: %s" % ensure_addon())

    polys = sio.read_polygons(args["shp"])
    if not polys:
        raise SystemExit("no polygons in %s" % args["shp"])
    print("\nread %d footprint(s) from %s"
          % (len(polys), os.path.basename(args["shp"])))
    print("attributes: %s" % ", ".join(sorted(polys[0]["attrs"].keys())))

    if looks_like_degrees(polys):
        kx, ky = to_metres(polys)
        print("coordinates are degrees -- converted at %.0f m/deg east, "
              "%.0f m/deg north" % (kx, ky))

    hf = args["height-field"]
    heights = [p["attrs"].get(hf) for p in polys]
    usable = [h for h in heights if isinstance(h, (int, float)) and h > 0]
    if not usable:
        raise SystemExit("no usable %r values. Attributes present: %s"
                         % (hf, ", ".join(sorted(polys[0]["attrs"].keys()))))
    usable.sort()
    print("%s: %.2f min / %.2f median / %.2f max m  ->  %d to %d floors"
          % (hf, usable[0], usable[len(usable) // 2], usable[-1],
             max(1, int(usable[0] // MODULE_HEIGHT)),
             max(1, int(usable[-1] // MODULE_HEIGHT))))
    if len(usable) != len(heights):
        print("%d footprint(s) have no usable %s and will be skipped"
              % (len(heights) - len(usable), hf))

    id_field, how = pick_id_field(polys, args["id-field"])
    if id_field:
        print("naming models from %r (%s)" % (id_field, how))
    else:
        print("numbering models sequentially (%s)" % how)

    if args["limit"]:
        polys = polys[:args["limit"]]
        print("limited to the first %d" % len(polys))

    out_dir = args["out"]
    os.makedirs(out_dir, exist_ok=True)

    # everything already in the .blend is Buildify's kit and must survive the
    # clean-up between buildings
    kit = set(bpy.data.objects)

    slope, base = MODULE_HEIGHT, 0.0
    if not args["dry-run"]:
        slope, base = calibrate(kit)
        print("this kit builds %.2f m per floor plus %.2f m of trim  ->  "
              "%.1f m asks for %d floor(s), built %.2f m"
              % (slope, base, usable[len(usable) // 2],
                 floors_for(usable[len(usable) // 2], slope, base),
                 slope * floors_for(usable[len(usable) // 2], slope, base)
                 + base))

    rows, skipped = [], []
    started = time.time()
    for n, poly in enumerate(polys):
        height = poly["attrs"].get(hf)
        name = model_name(poly, id_field, n)
        if not isinstance(height, (int, float)) or height <= 0:
            skipped.append((name, "no %s" % hf))
            continue

        ob, origin, theta = footprint_object(poly["outer"], name,
                                             canonical=not args["no-canonical"])
        if ob is None:
            skipped.append((name, "footprint has fewer than 3 corners"))
            continue

        row = {"index": poly["index"], "x": poly["centroid"][0],
               "y": poly["centroid"][1], "height_m": height,
               MODEL_FIELD: name,
               HEADING_FIELD: heading_from(theta, args["heading"])}
        if id_field:
            row[id_field] = poly["attrs"].get(id_field)

        if args["dry-run"]:
            rows.append(row)
            wipe(kit)
            continue

        try:
            set_seed(bpy.data.node_groups.get("building"), n + 1)
            floors = floors_for(height, slope, base)
            row["floors"] = floors
            row["built_m"] = round(slope * floors + base, 2)
            baked = build_one(ob, height, args["full"], floors)
            if baked is None:
                skipped.append((name, "nothing generated"))
                wipe(kit)
                continue
            path = os.path.join(out_dir, name + ".fbx")
            export_fbx(baked, path)
            baked.data.calc_loop_triangles()
            row["tris"] = len(baked.data.loop_triangles)
            rows.append(row)
            print("  [%d/%d] %-24s %5.1f m  %6d tris"
                  % (n + 1, len(polys), name, height, row["tris"]))
        except Exception as exc:                       # one bad footprint
            skipped.append((name, "%s" % exc))         # must not stop the run
            print("  [%d/%d] %-24s FAILED: %s" % (n + 1, len(polys), name, exc))
        wipe(kit)

    # ---- the table ---------------------------------------------------------
    csv_path = os.path.join(out_dir, "models.csv")
    keys = ["index", MODEL_FIELD, HEADING_FIELD, "height_m", "floors",
            "built_m", "x", "y", "tris"]
    if id_field:
        keys.insert(1, id_field)
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    if args["points"]:
        pts = [(r["x"], r["y"]) for r in rows]
        fields = [(MODEL_FIELD, "C", 64, 0), (HEADING_FIELD, "N", 10, 3),
                  ("height_m", "N", 12, 2)]
        if id_field:
            fields.append((id_field[:10], "C", 32, 0))
        prows = []
        for r in rows:
            pr = {MODEL_FIELD: r[MODEL_FIELD],
                  HEADING_FIELD: r[HEADING_FIELD],
                  "height_m": r["height_m"]}
            if id_field:
                pr[id_field[:10]] = str(r.get(id_field, ""))
            prows.append(pr)
        shp_path = os.path.join(out_dir, "model_points.shp")
        sio.write_points(shp_path, pts, fields, prows,
                         prj=sio.read_prj(args["shp"]))
        print("wrote %s  (names cut to %r and %r -- a .dbf allows 10 "
              "characters; the csv carries them in full)"
              % (os.path.basename(shp_path), MODEL_FIELD[:10],
                 HEADING_FIELD[:10]))

    took = time.time() - started
    print("\n%d model(s) in %s, %.1f s (%.1f s each)"
          % (len(rows), out_dir, took, took / max(1, len(rows))))
    print("table: %s" % csv_path)
    if skipped:
        print("skipped %d:" % len(skipped))
        for name, why in skipped[:20]:
            print("   %-24s %s" % (name, why))


if __name__ == "__main__":
    main()
