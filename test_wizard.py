"""The wizard end to end: a shapefile goes in, FBX models come out.

Builds its own input layer -- footprints at real projected-CRS magnitudes,
with an OBJECTID and a RELATIVE_F height -- then runs the whole pipeline and
checks the models, the table and the point layer against it.

Run: blender -b buildify_1.0.blend --python test_wizard.py
"""

import csv
import math
import os
import sys
import tempfile

sys.path.insert(0, r"C:\Users\User\Desktop\BuildingGen")

import bpy                                          # noqa: E402
import shapefile_io as sio                          # noqa: E402
import building_wizard as wiz                       # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="wizard_test_")


def rule(t):
    print("\n" + "=" * 72 + "\n" + t + "\n" + "=" * 72)


def check(c, m):
    print(("PASS  " if c else "FAIL  ") + m)
    if not c:
        fails.append(m)


def ring(cx, cy, w, h):
    pts = [(cx - w / 2, cy - h / 2), (cx - w / 2, cy + h / 2),
           (cx + w / 2, cy + h / 2), (cx + w / 2, cy - h / 2)]
    return pts + [pts[0]]                            # clockwise, as ESRI winds


rule("0. AN INPUT LAYER, AT THE COORDINATES REAL DATA USES")
shp = os.path.join(TMP, "buildings.shp")
out = os.path.join(TMP, "models")
polys = [[ring(180000.0, 663000.0, 15.0, 9.0)],
         [ring(180050.0, 663030.0, 12.0, 12.0)],
         [ring(180100.0, 663060.0, 21.0, 9.0)],
         [ring(180150.0, 663090.0, 10.0, 10.0)]]     # this one has no height
fields = [("OBJECTID", "N", 10, 0), ("RELATIVE_F", "N", 12, 2)]
rows = [{"OBJECTID": 101, "RELATIVE_F": 9.0},
        {"OBJECTID": 102, "RELATIVE_F": 15.0},
        {"OBJECTID": 103, "RELATIVE_F": 6.0},
        {"OBJECTID": 104, "RELATIVE_F": 0.0}]
sio.write_polygons(shp, polys, fields, rows, prj='PROJCS["Israel_TM_Grid"]')
print("wrote %d footprints to %s" % (len(polys), shp))

rule("1. RUN THE WIZARD")
sys.argv = ["blender", "--", "--shp", shp, "--out", out, "--points"]
wiz.main()

made = sorted(f for f in os.listdir(out) if f.endswith(".fbx"))
print("models: %s" % made)
check(len(made) == 3, "one model per footprint that had a height")
check(made == ["bld_101.fbx", "bld_102.fbx", "bld_103.fbx"],
      "named bld_<OBJECTID>, from the field the wizard picked itself")
check("bld_104.fbx" not in made,
      "the footprint with RELATIVE_F = 0 was skipped, not built empty")
for name in made:
    size = os.path.getsize(os.path.join(out, name))
    print("   %-16s %8.1f KB" % (name, size / 1024.0))
    check(size > 20000, "%s is a real model, not an empty file" % name)

rule("2. THE TABLE LINKS POINTS TO MODELS")
with open(os.path.join(out, "models.csv"), encoding="utf-8") as fh:
    table = list(csv.DictReader(fh))
print("columns: %s" % list(table[0].keys()))
check(len(table) == 3, "a row per model")
check(wiz.MODEL_FIELD in table[0],
      "the full 11-character name survives in the csv")
check([r[wiz.MODEL_FIELD] for r in table] == ["bld_101", "bld_102",
                                              "bld_103"],
      "every row names its model")
check(all(r["OBJECTID"] for r in table), "and carries the source OBJECTID")

# the point must land on the building it came from, in map coordinates
first = table[0]
print("row 1: x=%s y=%s height=%s tris=%s"
      % (first["x"], first["y"], first["height_m"], first["tris"]))
check(abs(float(first["x"]) - 180000.0) < 1e-6
      and abs(float(first["y"]) - 663000.0) < 1e-6,
      "the coordinates are the footprint's own, in the source CRS")
check(int(first["tris"]) > 100, "the model has real geometry")

rule("3. HEIGHT DRIVES THE MODEL")
tris = {r[wiz.MODEL_FIELD]: int(r["tris"]) for r in table}
heights = {r[wiz.MODEL_FIELD]: float(r["height_m"]) for r in table}
print("heights %s" % heights)
print("tris    %s" % tris)
check(heights["bld_102"] == 15.0, "RELATIVE_F was read as metres")
check(tris["bld_102"] > tris["bld_103"],
      "the 15 m building has more geometry than the 6 m one")

rule("4. THE MODEL IS AT THE ORIGIN, NOT AT ITS MAP POSITION")
# 180 km from zero a float has decimetre gaps and the geometry wobbles
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob, do_unlink=True)
bpy.ops.import_scene.fbx(filepath=os.path.join(out, "bld_101.fbx"))
imported = [o for o in bpy.data.objects if o.type == "MESH"]
check(len(imported) == 1, "the fbx holds a single joined mesh")
if imported:
    pts = [o.matrix_world @ v.co for o in imported for v in o.data.vertices]
    cx = (min(p.x for p in pts) + max(p.x for p in pts)) * 0.5
    cy = (min(p.y for p in pts) + max(p.y for p in pts)) * 0.5
    zmax = max(p.z for p in pts)
    print("imported: centre (%.2f, %.2f), top %.2f m, %d verts"
          % (cx, cy, zmax, len(pts)))
    # not the bbox midpoint: Buildify scatters rooftop clutter at random, and
    # one aerial near an edge moves the midpoint without moving the building.
    # What matters is that the model is in local coordinates at all -- the
    # footprint sits at 180 km east in the source layer
    far = max(max(abs(p.x) for p in pts), max(abs(p.y) for p in pts))
    print("furthest vertex from the origin: %.2f m" % far)
    check(far < 50.0,
          "it sits at the origin, not at its map coordinates 180 km away")
    # the add-on's floor(h/3) built this 2 m short. The wizard measures what a
    # floor is worth in the kit and picks the nearest count, so the error can
    # never exceed half a storey
    print("asked 9.00 m, built %.2f m, out by %.2f" % (zmax, zmax - 9.0))
    check(abs(zmax - 9.0) <= 1.51,
          "and stands 9 m tall, within half a storey of the height it was "
          "given")

rule("5. THE EXPORTED MODEL HAS A ROOF")
# Buildify's flat roof is real geometry on the building object, not an
# instance, so duplicates_make_real does not see it -- and the bake removes
# the modifier, which reverts the object to its bare footprint. The building
# then came out open at the top with a floor plate at ground level instead,
# which is only obvious if you look down at it.
if imported:
    ob = imported[0]
    flats = {}
    for p in ob.data.polygons:
        if abs(p.normal.z) < 0.9:
            continue
        z = round(sum((ob.matrix_world @ ob.data.vertices[i].co).z
                      for i in p.vertices) / len(p.vertices), 2)
        flats[z] = flats.get(z, 0.0) + p.area

    footprint = 15.0 * 9.0
    big = {z: a for z, a in flats.items() if a > footprint * 0.6}
    print("horizontal area by height: %s"
          % {z: round(a, 1) for z, a in sorted(big.items())})
    check(bool(big), "the model has a footprint-sized horizontal surface")
    if big:
        highest = max(big)
        lowest = min(big)
        print("roof-sized surface at z=%.2f, model top %.2f" % (highest, zmax))
        check(highest > zmax - 1.5,
              "and it is at the TOP of the building: the roof is there")
        check(lowest > 1.0,
              "with no stray floor plate left at ground level")

rule("6. THE POINT LAYER")
pts_shp = os.path.join(out, "model_points.shp")
check(os.path.isfile(pts_shp), "a point shapefile was written")
if os.path.isfile(pts_shp):
    stype, shapes = sio._read_shp(pts_shp)
    names, prows = sio._read_dbf(os.path.join(out, "model_points.dbf"))
    print("point fields: %s" % [n[0] for n in names])
    check(stype == sio.POINT, "it really is a point layer")
    check(len(shapes) == 3, "one point per model")
    check(prows[0]["@mref_mode"] == "bld_101",
          "each point names its model (field cut to 10 chars by the format)")
    check(abs(shapes[0][0][0][0] - 180000.0) < 1e-6,
          "the point is at the footprint's map coordinates")
    check(sio.read_prj(pts_shp) == 'PROJCS["Israel_TM_Grid"]',
          "the source projection was carried across")

rule("7. THE HEADING PUTS THE MODEL BACK ON ITS FOOTPRINT")
# A 24 x 8 block turned 30 degrees anticlockwise from east. The model must come
# out axis-aligned, and the heading must be exactly what turns it back.
TURN = math.radians(30.0)


def turned(cx, cy, w, h, a):
    pts = [(-w / 2, -h / 2), (-w / 2, h / 2), (w / 2, h / 2), (w / 2, -h / 2)]
    c, s = math.cos(a), math.sin(a)
    out = [(cx + x * c - y * s, cy + x * s + y * c) for x, y in pts]
    return out + [out[0]]


rot_shp = os.path.join(TMP, "rotated.shp")
rot_out = os.path.join(TMP, "rotated_models")
sio.write_polygons(rot_shp, [[turned(180000.0, 663000.0, 24.0, 8.0, TURN)]],
                   fields, [{"OBJECTID": 201, "RELATIVE_F": 9.0}],
                   prj='PROJCS["Israel_TM_Grid"]')

sys.argv = ["blender", "--", "--shp", rot_shp, "--out", rot_out, "--points"]
wiz.main()

with open(os.path.join(rot_out, "models.csv"), encoding="utf-8") as fh:
    rot_table = list(csv.DictReader(fh))
heading = float(rot_table[0][wiz.HEADING_FIELD])
# gis convention: clockwise from north. 30 deg anticlockwise from east is
# 60 deg clockwise from north
print("footprint turned 30 deg from east -> heading %.3f (expect 60)"
      % heading)
check(wiz.HEADING_FIELD in rot_table[0],
      "the csv carries the full 20-character heading name")
check(abs(heading - 60.0) < 0.2, "the heading is measured clockwise from north")

for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob, do_unlink=True)
bpy.ops.import_scene.fbx(filepath=os.path.join(rot_out, "bld_201.fbx"))
mdl = [o for o in bpy.data.objects if o.type == "MESH"][0]
mpts = [mdl.matrix_world @ v.co for v in mdl.data.vertices]
mw = max(p.x for p in mpts) - min(p.x for p in mpts)
mh = max(p.y for p in mpts) - min(p.y for p in mpts)
print("model footprint %.2f x %.2f m (the block is 24 x 8)" % (mw, mh))
check(mw > mh, "the model was built with its long side along X")
check(abs(mw - 24.0) < 3.0 and abs(mh - 8.0) < 3.0,
      "and at its true size: a model still turned 30 deg would measure about "
      "25 x 19 from its bounding box")

# Turn the model by the heading and it must line up with the footprint again.
# Measured as extents along the footprint's own axes rather than by finding
# "the far corner": a rectangle has two of those, exactly as far apart, and
# picking either one reads as a 2 x 18.43 degree error that is not there.
back = math.radians(90.0 - heading)          # gis heading -> maths angle
c, s = math.cos(back), math.sin(back)
placed = [(p.x * c - p.y * s, p.x * s + p.y * c) for p in mpts]

ux, uy = math.cos(TURN), math.sin(TURN)      # the footprint's long axis
along = [x * ux + y * uy for x, y in placed]
across = [-x * uy + y * ux for x, y in placed]
span_along = max(along) - min(along)
span_across = max(across) - min(across)
print("placed model spans %.2f m along the footprint's long axis and %.2f m "
      "across it (block is 24 x 8)" % (span_along, span_across))
check(abs(span_along - 24.0) < 3.0 and abs(span_across - 8.0) < 3.0,
      "rotating the model by the heading lands it back on its footprint")

# and the same measurement without the rotation must NOT fit, or the check
# above would pass for a model that was never turned at all
raw_along = [p.x * ux + p.y * uy for p in mpts]
raw_across = [-p.x * uy + p.y * ux for p in mpts]
print("unrotated, the same model spans %.2f x %.2f m on those axes"
      % (max(raw_along) - min(raw_along), max(raw_across) - min(raw_across)))
check(abs((max(raw_across) - min(raw_across)) - 8.0) > 3.0,
      "and the test would have failed had the heading been ignored")

rule("8. A LAYER IN DEGREES IS CONVERTED, NOT BUILT MILLIMETRES WIDE")
deg = os.path.join(TMP, "degrees.shp")
sio.write_polygons(deg, [[ring(34.78, 32.07, 0.00012, 0.00009)]],
                   fields, [{"OBJECTID": 1, "RELATIVE_F": 9.0}])
got = sio.read_polygons(deg)
check(wiz.looks_like_degrees(got), "a lat/long layer is recognised")
kx, ky = wiz.to_metres(got)
w = max(p[0] for p in got[0]["outer"]) - min(p[0] for p in got[0]["outer"])
h = max(p[1] for p in got[0]["outer"]) - min(p[1] for p in got[0]["outer"])
print("0.00012 x 0.00009 deg -> %.2f x %.2f m (%.0f, %.0f m/deg)"
      % (w, h, kx, ky))
check(8.0 < w < 15.0 and 8.0 < h < 12.0,
      "which becomes a building of a believable size in metres")
check(kx < ky, "and longitude is scaled less than latitude, as it must be")

print("\n" + "=" * 72)
print("FAILED %d" % len(fails) if fails else "ALL PASSED")
for f in fails:
    print("  - " + f)
print("=" * 72)
sys.exit(1 if fails else 0)
