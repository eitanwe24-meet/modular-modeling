"""Read and write ESRI shapefiles with nothing but the standard library.

Why not a library: GDAL, pyproj, Fiona and pyshp are all absent from Blender's
Python, and installing them into it is a support problem on every machine this
ever runs on. BlenderGIS is present and can read a shapefile, but it cannot
write one, and the wizard has to write a point layer -- so half of this would
have to exist anyway. The format is small enough that the whole of it fits
here: a fixed 100-byte header, then records.

Covers what a building footprint layer actually contains: Polygon, PolygonZ and
PolygonM on the way in, Point on the way out, with their .dbf attributes and
the .prj carried across untouched.
"""

import os
import struct

POINT, POLYLINE, POLYGON, MULTIPOINT = 1, 3, 5, 8
POINT_Z, POLYLINE_Z, POLYGON_Z = 11, 13, 15
POINT_M, POLYLINE_M, POLYGON_M = 21, 23, 25

POLYGON_TYPES = (POLYGON, POLYGON_Z, POLYGON_M)

# a .dbf field name is 10 characters. Not a convention -- there are 11 bytes in
# the descriptor and the last must be the terminator
DBF_NAME_MAX = 10


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def _read_dbf(path):
    """(field descriptors, rows as dicts). Empty if there is no .dbf."""
    if not os.path.isfile(path):
        return [], []

    with open(path, "rb") as fh:
        raw = fh.read()

    n_records, header_len, record_len = struct.unpack_from("<IHH", raw, 4)
    fields, off = [], 32
    while off < header_len - 1 and raw[off] != 0x0D:
        name = raw[off:off + 11].split(b"\x00")[0].decode("latin-1").strip()
        ftype = chr(raw[off + 11])
        flen, dec = raw[off + 16], raw[off + 17]
        fields.append((name, ftype, flen, dec))
        off += 32

    rows, pos = [], header_len
    for _ in range(n_records):
        if pos + record_len > len(raw):
            break
        chunk = raw[pos:pos + record_len]
        pos += record_len
        if chunk[:1] == b"*":                      # marked deleted
            continue
        row, at = {}, 1
        for name, ftype, flen, dec in fields:
            text = chunk[at:at + flen].decode("latin-1").strip()
            at += flen
            row[name] = _convert(text, ftype, dec)
        rows.append(row)
    return fields, rows


def _convert(text, ftype, dec):
    """dBASE stores everything as text; give back something usable."""
    if ftype in "NF":
        if not text or text in ("-", "*"):
            return None
        try:
            return float(text) if (dec or "." in text) else int(text)
        except ValueError:
            return None
    if ftype == "L":
        return text.upper() in ("Y", "T")
    return text


def _read_shp(path):
    """(shape type, [record]) where a record is a list of rings/points."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if len(raw) < 100 or struct.unpack_from(">i", raw, 0)[0] != 9994:
        raise ValueError("%s is not a shapefile" % os.path.basename(path))

    file_type = struct.unpack_from("<i", raw, 32)[0]
    end = struct.unpack_from(">i", raw, 24)[0] * 2      # header stores words
    end = min(end, len(raw))

    shapes, pos = [], 100
    while pos + 8 <= end:
        content_len = struct.unpack_from(">i", raw, pos + 4)[0] * 2
        body = pos + 8
        pos = body + content_len
        if content_len == 0:
            shapes.append(None)                          # null shape
            continue
        stype = struct.unpack_from("<i", raw, body)[0]
        if stype == 0:
            shapes.append(None)
        elif stype in (POINT, POINT_Z, POINT_M):
            shapes.append([[struct.unpack_from("<2d", raw, body + 4)]])
        elif stype in POLYGON_TYPES or stype in (POLYLINE, POLYLINE_Z,
                                                 POLYLINE_M):
            n_parts, n_points = struct.unpack_from("<2i", raw, body + 36)
            starts = struct.unpack_from("<%di" % n_parts, raw, body + 44)
            base = body + 44 + 4 * n_parts
            pts = struct.unpack_from("<%dd" % (2 * n_points), raw, base)
            rings = []
            for i, start in enumerate(starts):
                stop = starts[i + 1] if i + 1 < n_parts else n_points
                rings.append([(pts[2 * j], pts[2 * j + 1])
                              for j in range(start, stop)])
            shapes.append(rings)
        else:
            shapes.append(None)                          # unsupported, skipped
    return file_type, shapes


def read_polygons(path):
    """Every polygon in a shapefile, with its attributes.

    Returns dicts of {"rings", "outer", "holes", "attrs", "centroid"}. Rings are
    classed by winding, which is what the format actually specifies: an outer
    ring runs clockwise, a hole runs anticlockwise.
    """
    stem = os.path.splitext(path)[0]
    file_type, shapes = _read_shp(stem + ".shp")
    if file_type not in POLYGON_TYPES:
        raise ValueError("%s holds shape type %d, not polygons"
                         % (os.path.basename(path), file_type))
    _fields, rows = _read_dbf(stem + ".dbf")

    out = []
    for i, rings in enumerate(shapes):
        if not rings:
            continue
        outer = [r for r in rings if signed_area(r) < 0.0]
        holes = [r for r in rings if signed_area(r) >= 0.0]
        if not outer:                       # every ring wound the other way
            outer, holes = holes, []
        big = max(outer, key=lambda r: abs(signed_area(r)))
        out.append({
            "index": i,
            "rings": rings,
            "outer": big,
            "holes": holes + [r for r in outer if r is not big],
            "attrs": rows[i] if i < len(rows) else {},
            "centroid": interior_point(big),
        })
    return out


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------
def signed_area(ring):
    """Negative when the ring is wound clockwise, the way outer rings are."""
    total = 0.0
    for i in range(len(ring)):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % len(ring)]
        total += x0 * y1 - x1 * y0
    return total * 0.5


def centroid(ring):
    """Area centroid. Falls back to the average vertex on a degenerate ring."""
    a = signed_area(ring)
    if abs(a) < 1e-12:
        n = max(1, len(ring))
        return (sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n)
    cx = cy = 0.0
    for i in range(len(ring)):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % len(ring)]
        cross = x0 * y1 - x1 * y0
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    return (cx / (6.0 * a), cy / (6.0 * a))


def point_in_ring(pt, ring):
    """Ray casting, counting crossings to the right of the point."""
    x, y = pt
    inside = False
    for i in range(len(ring)):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % len(ring)]
        if (y0 > y) != (y1 > y):
            t = (y - y0) / (y1 - y0)
            if x < x0 + t * (x1 - x0):
                inside = not inside
    return inside


def interior_point(ring):
    """A point that is actually inside the polygon.

    The area centroid of a C or U shaped building falls outside it, and a
    point layer whose points sit in the courtyard next door is worse than
    useless. When that happens, the midpoint of the widest span across the
    polygon at the centroid's own height is used instead.
    """
    c = centroid(ring)
    if point_in_ring(c, ring):
        return c

    y = c[1]
    xs = []
    for i in range(len(ring)):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % len(ring)]
        if (y0 > y) != (y1 > y):
            t = (y - y0) / (y1 - y0)
            xs.append(x0 + t * (x1 - x0))
    xs.sort()
    best, best_w = None, -1.0
    for i in range(0, len(xs) - 1, 2):
        w = xs[i + 1] - xs[i]
        if w > best_w:
            best, best_w = (xs[i] + xs[i + 1]) * 0.5, w
    return (best, y) if best is not None else c


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------
def _dbf_bytes(fields, rows):
    """A dBASE III table. Field names are cut to 10 characters by the format."""
    header_len = 32 * (len(fields) + 1) + 1
    record_len = 1 + sum(f[2] for f in fields)

    out = bytearray()
    out += struct.pack("<4BIHH20x", 0x03, 95, 1, 1, len(rows),
                       header_len, record_len)
    for name, ftype, flen, dec in fields:
        short = name[:DBF_NAME_MAX].encode("latin-1")
        out += short + b"\x00" * (11 - len(short))
        out += ftype.encode("ascii") + b"\x00" * 4
        out += bytes((flen, dec)) + b"\x00" * 14
    out += b"\x0D"

    for row in rows:
        out += b" "
        for name, ftype, flen, dec in fields:
            value = row.get(name, "")
            if value is None:
                text = ""
            elif ftype in "NF":
                text = ("%.*f" % (dec, float(value))) if dec else \
                    ("%d" % int(value))
            elif ftype == "L":
                text = "T" if value else "F"
            else:
                text = str(value)
            raw = text.encode("latin-1", "replace")[:flen]
            # numbers are right aligned in dBASE, text left
            out += raw.rjust(flen) if ftype in "NF" else raw.ljust(flen)
    out += b"\x1A"
    return bytes(out)


def write_points(path, points, fields, rows, prj=None):
    """Write a point shapefile: .shp, .shx, .dbf and, if given, .prj.

    `fields` are (name, type, length, decimals) and `rows` are dicts keyed by
    the full field name -- the truncation to 10 characters happens on the way
    into the file only, so callers do not have to think about it.
    """
    stem = os.path.splitext(path)[0]
    if len(points) != len(rows):
        raise ValueError("%d point(s) but %d row(s)" % (len(points),
                                                        len(rows)))

    xs = [p[0] for p in points] or [0.0]
    ys = [p[1] for p in points] or [0.0]
    box = (min(xs), min(ys), max(xs), max(ys))

    records, offsets = bytearray(), []
    for i, (x, y) in enumerate(points):
        body = struct.pack("<i2d", POINT, x, y)
        offsets.append((50 + len(records) // 2, len(body) // 2))
        records += struct.pack(">2i", i + 1, len(body) // 2) + body

    def header(length_words):
        return struct.pack(">i20xi", 9994, length_words) + \
            struct.pack("<2i4d", 1000, POINT, *box) + \
            struct.pack("<4d", 0.0, 0.0, 0.0, 0.0)

    with open(stem + ".shp", "wb") as fh:
        fh.write(header(50 + len(records) // 2))
        fh.write(records)

    index = bytearray()
    for off, ln in offsets:
        index += struct.pack(">2i", off, ln)
    with open(stem + ".shx", "wb") as fh:
        fh.write(header(50 + len(index) // 2))
        fh.write(index)

    with open(stem + ".dbf", "wb") as fh:
        fh.write(_dbf_bytes(fields, rows))

    if prj:
        with open(stem + ".prj", "w", encoding="utf-8") as fh:
            fh.write(prj)


def read_prj(path):
    """The .prj text beside a shapefile, or None. Copied, never interpreted."""
    prj = os.path.splitext(path)[0] + ".prj"
    if os.path.isfile(prj):
        with open(prj, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    return None


def write_polygons(path, polygons, fields, rows, prj=None):
    """Write a polygon shapefile. Used by the tests to make input to read."""
    stem = os.path.splitext(path)[0]
    all_pts = [p for poly in polygons for ring in poly for p in ring]
    xs = [p[0] for p in all_pts] or [0.0]
    ys = [p[1] for p in all_pts] or [0.0]
    box = (min(xs), min(ys), max(xs), max(ys))

    records, offsets = bytearray(), []
    for i, rings in enumerate(polygons):
        pts = [p for ring in rings for p in ring]
        rxs = [p[0] for p in pts]
        rys = [p[1] for p in pts]
        starts, run = [], 0
        for ring in rings:
            starts.append(run)
            run += len(ring)
        body = struct.pack("<i4d2i", POLYGON, min(rxs), min(rys), max(rxs),
                           max(rys), len(rings), len(pts))
        body += struct.pack("<%di" % len(starts), *starts)
        for x, y in pts:
            body += struct.pack("<2d", x, y)
        offsets.append((50 + len(records) // 2, len(body) // 2))
        records += struct.pack(">2i", i + 1, len(body) // 2) + body

    def header(length_words):
        return struct.pack(">i20xi", 9994, length_words) + \
            struct.pack("<2i4d", 1000, POLYGON, *box) + \
            struct.pack("<4d", 0.0, 0.0, 0.0, 0.0)

    with open(stem + ".shp", "wb") as fh:
        fh.write(header(50 + len(records) // 2))
        fh.write(records)
    index = bytearray()
    for off, ln in offsets:
        index += struct.pack(">2i", off, ln)
    with open(stem + ".shx", "wb") as fh:
        fh.write(header(50 + len(index) // 2))
        fh.write(index)
    with open(stem + ".dbf", "wb") as fh:
        fh.write(_dbf_bytes(fields, rows))
    if prj:
        with open(stem + ".prj", "w", encoding="utf-8") as fh:
            fh.write(prj)
