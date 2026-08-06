"""The shapefile reader and writer, checked against files we build ourselves.

There is no sample of the real data to test against, so the tests cover the
shapes a footprint layer actually contains -- rings wound both ways, holes,
multipart polygons, the .dbf types, and the coordinate magnitudes a projected
CRS produces -- rather than one happy case.

Run with any Python:  python test_shapefile.py
"""

import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shapefile_io as sio          # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="shp_test_")


def rule(t):
    print("\n" + "=" * 72 + "\n" + t + "\n" + "=" * 72)


def check(c, m):
    print(("PASS  " if c else "FAIL  ") + m)
    if not c:
        fails.append(m)


def ring(cx, cy, w, h, clockwise=True):
    """A closed rectangle, wound the way a shapefile winds an outer ring."""
    # up the left side, across the top, down the right: clockwise as written
    pts = [(cx - w / 2, cy - h / 2), (cx - w / 2, cy + h / 2),
           (cx + w / 2, cy + h / 2), (cx + w / 2, cy - h / 2)]
    if not clockwise:
        pts.reverse()
    return pts + [pts[0]]


rule("1. WINDING TELLS AN OUTER RING FROM A HOLE")
outer = ring(0, 0, 10, 10, clockwise=True)
hole = ring(0, 0, 4, 4, clockwise=False)
print("outer signed area %.1f, hole %.1f"
      % (sio.signed_area(outer), sio.signed_area(hole)))
check(sio.signed_area(outer) < 0, "a clockwise outer ring has negative area")
check(sio.signed_area(hole) > 0, "an anticlockwise hole has positive area")

rule("2. ROUND TRIP THROUGH A POLYGON SHAPEFILE")
# coordinates the size a projected CRS actually produces
path = os.path.join(TMP, "buildings.shp")
polys = [[ring(180000.0, 663000.0, 12.0, 8.0)],
         [ring(180040.0, 663025.0, 20.0, 20.0), ring(180040.0, 663025.0,
                                                     6.0, 6.0, False)],
         [ring(180090.0, 663060.0, 7.5, 30.0)]]
fields = [("OBJECTID", "N", 10, 0), ("RELATIVE_F", "N", 12, 2),
          ("NAME", "C", 32, 0)]
rows = [{"OBJECTID": 101, "RELATIVE_F": 12.5, "NAME": "one"},
        {"OBJECTID": 102, "RELATIVE_F": 24.0, "NAME": "courtyard"},
        {"OBJECTID": 103, "RELATIVE_F": 9.0, "NAME": "slab"}]
sio.write_polygons(path, polys, fields, rows,
                   prj='PROJCS["Israel_TM"]')

got = sio.read_polygons(path)
print("wrote %d, read %d" % (len(polys), len(got)))
check(len(got) == 3, "every polygon came back")
check([r["attrs"]["OBJECTID"] for r in got] == [101, 102, 103],
      "integer attributes survive")
check(abs(got[0]["attrs"]["RELATIVE_F"] - 12.5) < 1e-9,
      "decimals survive: RELATIVE_F is 12.5, not 12")
check(got[1]["attrs"]["NAME"] == "courtyard", "text attributes survive")
check(len(got[1]["holes"]) == 1, "the courtyard's hole was recognised")
check(len(got[0]["holes"]) == 0, "a plain building has none")
# which ring is which, not just how many: swapping them would keep the count
# right and put the building where the courtyard should be
outer_area = abs(sio.signed_area(got[1]["outer"]))
hole_area = abs(sio.signed_area(got[1]["holes"][0]))
print("outer %.0f m2, hole %.0f m2 (expected 400 and 36)"
      % (outer_area, hole_area))
check(abs(outer_area - 400.0) < 1e-6,
      "the 20 m ring is the building, not the hole")
check(abs(hole_area - 36.0) < 1e-6, "and the 6 m ring is the hole")

x, y = got[0]["centroid"]
print("centroid %.3f, %.3f (expected 180000, 663000)" % (x, y))
check(abs(x - 180000.0) < 1e-6 and abs(y - 663000.0) < 1e-6,
      "the centroid lands where it should, at full coordinate magnitude")

w = max(p[0] for p in got[0]["outer"]) - min(p[0] for p in got[0]["outer"])
check(abs(w - 12.0) < 1e-9, "no precision lost at 180 km from the origin")
check(sio.read_prj(path) == 'PROJCS["Israel_TM"]', ".prj is carried across")

rule("3. A CENTROID THAT FALLS OUTSIDE ITS OWN BUILDING")
# a U: the area centroid sits in the courtyard, between the arms
U = [(0, 0), (14, 0), (14, 10), (10, 10), (10, 4), (4, 4), (4, 10), (0, 10)]
c = sio.centroid(U)
inside = sio.interior_point(U)
print("area centroid %s inside=%s -> interior point %s inside=%s"
      % (tuple(round(v, 2) for v in c), sio.point_in_ring(c, U),
         tuple(round(v, 2) for v in inside), sio.point_in_ring(inside, U)))
check(not sio.point_in_ring(c, U),
      "the plain area centroid really does fall outside a U")
check(sio.point_in_ring(inside, U),
      "interior_point puts the point inside the building instead")

rule("4. THE 10-CHARACTER FIELD NAME LIMIT")
ppath = os.path.join(TMP, "pts.shp")
sio.write_points(ppath, [(180000.0, 663000.0), (180040.0, 663025.0)],
                 [("@mref_model", "C", 64, 0), ("height_m", "N", 12, 2)],
                 [{"@mref_model": "bld_101", "height_m": 12.5},
                  {"@mref_model": "bld_102", "height_m": 24.0}],
                 prj='PROJCS["Israel_TM"]')
names, prows = sio._read_dbf(os.path.join(TMP, "pts.dbf"))
print("field names in the file: %s" % [n[0] for n in names])
check([n[0] for n in names] == ["@mref_mode", "height_m"],
      "an 11-character name is stored as 10, as the format requires")
check(prows[0]["@mref_mode"] == "bld_101", "the VALUE is untouched")
check(abs(prows[1]["height_m"] - 24.0) < 1e-9, "numeric values round trip")

stype, shapes = sio._read_shp(os.path.join(TMP, "pts.shp"))
check(stype == sio.POINT, "the file declares itself a point shapefile")
check(len(shapes) == 2, "both points are there")
check(abs(shapes[0][0][0][0] - 180000.0) < 1e-9, "at the right coordinates")

rule("5. THE .SHX INDEX MATCHES THE .SHP")
# ArcGIS reads the index, not the file, so a wrong offset here is invisible
# until the layer opens empty in ArcMap and fine everywhere else
with open(os.path.join(TMP, "pts.shx"), "rb") as fh:
    shx = fh.read()
with open(os.path.join(TMP, "pts.shp"), "rb") as fh:
    shp = fh.read()
check((len(shx) - 100) // 8 == 2, "one index entry per record")
ok = True
for i in range(2):
    off, ln = struct.unpack_from(">2i", shx, 100 + i * 8)
    rec_len = struct.unpack_from(">i", shp, off * 2 + 4)[0]
    if rec_len != ln:
        ok = False
check(ok, "every index entry points at a record of the length it claims")
check(struct.unpack_from(">i", shp, 24)[0] * 2 == len(shp),
      "the header's file length matches the bytes actually written")

rule("6. AWKWARD INPUT DOES NOT CRASH THE READER")
empty = os.path.join(TMP, "empty.shp")
sio.write_polygons(empty, [], [("ID", "N", 8, 0)], [])
check(sio.read_polygons(empty) == [], "an empty layer reads as no polygons")

nodbf = os.path.join(TMP, "nodbf.shp")
sio.write_polygons(nodbf, [[ring(0, 0, 4, 4)]], [("ID", "N", 8, 0)],
                   [{"ID": 1}])
os.remove(os.path.join(TMP, "nodbf.dbf"))
got = sio.read_polygons(nodbf)
check(len(got) == 1 and got[0]["attrs"] == {},
      "a missing .dbf gives geometry with no attributes, not an exception")

try:
    sio.read_polygons(os.path.join(TMP, "pts.shp"))
    check(False, "reading points as polygons is refused")
except ValueError as exc:
    print("refused with: %s" % exc)
    check(True, "reading points as polygons is refused")

print("\n" + "=" * 72)
print("FAILED %d" % len(fails) if fails else "ALL PASSED")
for f in fails:
    print("  - " + f)
print("=" * 72)
sys.exit(1 if fails else 0)
