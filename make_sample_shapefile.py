"""Build a small example footprint layer, to try the wizard on.

Nothing here is real data -- it is a stand-in shaped like the real thing: a
projected CRS with coordinates in the hundreds of thousands, an OBJECTID, and
heights in metres in RELATIVE_F. The footprints are deliberately varied,
including the two cases that break naive code: a concave plan whose centroid
falls outside it, and a courtyard block with a hole.

Run with any Python:
    python make_sample_shapefile.py [output folder]
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shapefile_io as sio          # noqa: E402

# Israel TM Grid, the same numbers a local layer carries. The point is the
# magnitude: 180 km east, 663 km north, where float32 starts to lose grip
EAST, NORTH = 180000.0, 663000.0
PRJ = ('PROJCS["Israel_TM_Grid",GEOGCS["GCS_Israel",'
       'DATUM["D_Israel",SPHEROID["GRS_1980",6378137.0,298.257222101]],'
       'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],'
       'PROJECTION["Transverse_Mercator"],PARAMETER["False_Easting",219529.584],'
       'PARAMETER["False_Northing",626907.39],'
       'PARAMETER["Central_Meridian",35.20451694444445],'
       'PARAMETER["Scale_Factor",1.0000067],'
       'PARAMETER["Latitude_Of_Origin",31.73439361111111],UNIT["Meter",1.0]]')


def rect(cx, cy, w, h, turn=0.0):
    """A rectangle, wound clockwise the way a shapefile winds an outer ring."""
    pts = [(-w / 2, -h / 2), (-w / 2, h / 2), (w / 2, h / 2), (w / 2, -h / 2)]
    c, s = math.cos(turn), math.sin(turn)
    out = [(cx + x * c - y * s, cy + x * s + y * c) for x, y in pts]
    return out + [out[0]]


def ell(cx, cy, a, b, arm):
    """An L-shaped block: a concave plan, centroid outside the building."""
    pts = [(0, 0), (0, b), (arm, b), (arm, arm), (a, arm), (a, 0)]
    out = [(cx + x - a / 2, cy + y - b / 2) for x, y in pts]
    return out + [out[0]]


def ring_ccw(cx, cy, w, h):
    """A hole, wound the other way round, as the format requires."""
    pts = rect(cx, cy, w, h)[:-1]
    pts.reverse()
    return pts + [pts[0]]


BUILDINGS = [
    # (rings, OBJECTID, RELATIVE_F metres, description)
    ([rect(EAST + 0, NORTH + 0, 18.0, 11.0)], 101, 9.0, "shop row"),
    ([rect(EAST + 45, NORTH + 8, 12.0, 12.0)], 102, 21.0, "tower"),
    ([rect(EAST + 80, NORTH - 5, 26.0, 9.0, math.radians(18.0))],
     103, 12.0, "slab, off the grid"),
    ([ell(EAST + 20, NORTH + 45, 24.0, 26.0, 10.0)], 104, 15.0, "L block"),
    ([rect(EAST + 90, NORTH + 40, 30.0, 30.0),
      ring_ccw(EAST + 90, NORTH + 40, 12.0, 12.0)], 105, 18.0, "courtyard"),
    ([rect(EAST + 140, NORTH + 10, 9.0, 9.0)], 106, 4.0, "kiosk"),
    ([rect(EAST + 150, NORTH + 50, 14.0, 20.0)], 107, 33.0, "high rise"),
    ([rect(EAST + 175, NORTH - 10, 11.0, 11.0)], 108, 0.0, "no height on file"),
]


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "buildings.shp")

    fields = [("OBJECTID", "N", 10, 0), ("RELATIVE_F", "N", 12, 2),
              ("NOTE", "C", 32, 0)]
    rows = [{"OBJECTID": oid, "RELATIVE_F": h, "NOTE": note}
            for _rings, oid, h, note in BUILDINGS]
    sio.write_polygons(path, [b[0] for b in BUILDINGS], fields, rows, prj=PRJ)

    print("wrote %s" % path)
    for rings, oid, h, note in BUILDINGS:
        area = abs(sio.signed_area(rings[0]))
        print("   %d  %6.1f m2  %5.1f m  %s%s"
              % (oid, area, h, note,
                 "  (+ hole)" if len(rings) > 1 else ""))
    print("\nTry it:")
    print('   wizard.bat --shp "%s" --out "%s" --dry-run'
          % (path, os.path.join(out_dir, "models")))


if __name__ == "__main__":
    main()
