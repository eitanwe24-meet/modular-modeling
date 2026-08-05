"""
Build a low-poly Middle Eastern facade module library.

Five 3x3 m modules matching Buildify's placement convention, so they drop into
the same slots:

    X  -1.5 .. +1.5   (3 m wide, origin centred)
    Z   0.0 ..  3.0   (origin at the BOTTOM, parapet is 0..1)
    Y   0.0 .. +0.2   (facade plane at Y=0, body goes INTO +Y)
    Y   negative      (anything projecting outward: oriels, steps)

Facade modules are single-sided shells -- front frame, recessed reveal, back
pane. That is the standard for modular facade kits and is what keeps the tri
counts this low; only the solid wall and the parapet are closed boxes.

Run:
    blender -b <any.blend> --python make_me_library.py -- <out.blend> [--render]
"""

import math
import sys
import bmesh
import bpy
from mathutils import Vector

COLLECTION = "lib_middle_eastern"
W = 1.5             # half width
H = 3.0             # module height
DEPTH = 0.20        # wall body thickness (into +Y)
ARCH_SEGS = 5       # segments per arch half; raise for smoother arches


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def new_bm():
    return bmesh.new()


def loop(bm, pts, y=0.0):
    """Create a closed edge loop from (x, z) pairs at a given depth."""
    verts = [bm.verts.new((x, y, z)) for (x, z) in pts]
    edges = []
    n = len(verts)
    for i in range(n):
        edges.append(bm.edges.new((verts[i], verts[(i + 1) % n])))
    return verts, edges


def rect_pts(x0, z0, x1, z1, seg=2):
    """Rectangle as an ordered loop, subdivided so bridging stays clean."""
    pts = []
    for i in range(seg):
        pts.append((x0 + (x1 - x0) * i / seg, z0))
    for i in range(seg):
        pts.append((x1, z0 + (z1 - z0) * i / seg))
    for i in range(seg):
        pts.append((x1 - (x1 - x0) * i / seg, z1))
    for i in range(seg):
        pts.append((x0, z1 - (z1 - z0) * i / seg))
    return pts


def arch_half(half_w, z_spring, centre_off, segs, left=True):
    """One half of a two-centre pointed arch, springline to apex."""
    R = half_w + centre_off
    c = centre_off if left else -centre_off
    a0 = math.pi if left else 0.0
    a1 = math.acos(-centre_off / R) if left else math.acos(centre_off / R)
    out = []
    for i in range(segs + 1):
        t = i / segs
        a = a0 + (a1 - a0) * t
        out.append((c + R * math.cos(a), z_spring + R * math.sin(a)))
    return out


def pointed_opening(half_w, sill, z_spring, centre_off, segs=ARCH_SEGS):
    """Ordered loop for a pointed-arch opening."""
    pts = [(-half_w, sill), (half_w, sill), (half_w, z_spring)]
    pts += arch_half(half_w, z_spring, centre_off, segs, left=False)[1:]
    pts += list(reversed(arch_half(half_w, z_spring, centre_off, segs,
                                   left=True)))[1:]
    pts.append((-half_w, z_spring))
    # drop consecutive duplicates
    out = []
    for p in pts:
        if not out or (abs(p[0] - out[-1][0]) > 1e-6 or abs(p[1] - out[-1][1]) > 1e-6):
            out.append(p)
    return out


def framed_panel(bm, opening_pts, reveal=0.15, pane=True, outer=None):
    """Front frame bridging the module edge to an opening, plus a recessed
    reveal and an optional back pane."""
    outer_pts = outer if outer else rect_pts(-W, 0.0, W, H, seg=3)
    _ov, oe = loop(bm, outer_pts, 0.0)
    _iv, ie = loop(bm, opening_pts, 0.0)
    bmesh.ops.bridge_loops(bm, edges=oe + ie)

    ret = bmesh.ops.extrude_edge_only(bm, edges=ie)
    geom = ret["geom"]
    nv = [g for g in geom if isinstance(g, bmesh.types.BMVert)]
    ne = [g for g in geom if isinstance(g, bmesh.types.BMEdge)]
    bmesh.ops.translate(bm, verts=nv, vec=(0.0, reveal, 0.0))
    if pane:
        back = [e for e in ne if all(abs(v.co.y - reveal) < 1e-6 for v in e.verts)]
        if back:
            bmesh.ops.contextual_create(bm, geom=back)
    return bm


def box(bm, x0, y0, z0, x1, y1, z1):
    """Closed box wound so every normal already points outward.

    Deterministic winding matters: recalc_face_normals cannot orient geometry
    that is disconnected from the rest of the mesh, so loose islands must be
    correct as built.
    """
    v = [bm.verts.new(p) for p in (
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))]
    for f in ((0, 3, 2, 1),      # -Z
              (4, 5, 6, 7),      # +Z
              (0, 1, 5, 4),      # -Y  (outward face)
              (3, 7, 6, 2),      # +Y
              (0, 4, 7, 3),      # -X
              (1, 2, 6, 5)):     # +X
        bm.faces.new([v[i] for i in f])
    return v


def quad_facing_out(bm, x0, z0, x1, z1, y):
    """Single quad at a fixed depth, wound so its normal points -Y."""
    v = [bm.verts.new(p) for p in ((x0, y, z0), (x1, y, z0),
                                   (x1, y, z1), (x0, y, z1))]
    return bm.faces.new(v)


def finish(bm, name, recalc=True):
    if recalc:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.update()
    ob = bpy.data.objects.new(name, me)
    return ob


# ---------------------------------------------------------------------------
# the five modules
# ---------------------------------------------------------------------------
def build_solid():
    """Plain plaster wall -- a closed slab."""
    bm = new_bm()
    box(bm, -W, 0.0, 0.0, W, DEPTH, H)
    return finish(bm, "me_1_solid")


def build_window_arch():
    """Pointed-arch window with a recessed reveal."""
    bm = new_bm()
    opening = pointed_opening(half_w=0.60, sill=0.95, z_spring=1.85,
                              centre_off=0.20)
    framed_panel(bm, opening, reveal=0.16)
    # sill projecting slightly outward
    box(bm, -0.75, -0.08, 0.86, 0.75, 0.02, 0.95)
    return finish(bm, "me_2_window_arch")


def build_mashrabiya():
    """Projecting latticed oriel -- the signature element.

    The screen is a 3x4 grid of quads with alternate cells recessed rather than
    real openings; a literal lattice costs hundreds of tris for detail that is
    invisible past a few metres.
    """
    bm = new_bm()
    # match the outer loop's vertex count so bridge_loops produces clean quads
    # instead of a fan of triangles
    opening = rect_pts(-1.00, 0.85, 1.00, 2.45, seg=3)
    framed_panel(bm, opening, reveal=0.18, pane=True)
    # orient the shell now; everything added below is wound correctly by hand
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

    px0, px1 = -1.10, 1.10
    pz0, pz1 = 0.78, 2.55
    out = -0.45
    # oriel shell: sides, top, bottom (front face is built as the screen grid)
    box(bm, px0, out, pz0, px1, 0.0, pz0 + 0.06)          # underside
    box(bm, px0, out, pz1 - 0.06, px1, 0.0, pz1)          # top
    box(bm, px0, out, pz0, px0 + 0.06, 0.0, pz1)          # left cheek
    box(bm, px1 - 0.06, out, pz0, px1, 0.0, pz1)          # right cheek

    cols, rows = 3, 4
    for i in range(cols):
        for j in range(rows):
            x0 = px0 + 0.06 + (px1 - px0 - 0.12) * i / cols
            x1 = px0 + 0.06 + (px1 - px0 - 0.12) * (i + 1) / cols
            z0 = pz0 + 0.06 + (pz1 - pz0 - 0.12) * j / rows
            z1 = pz0 + 0.06 + (pz1 - pz0 - 0.12) * (j + 1) / rows
            y = out + (0.05 if (i + j) % 2 else 0.0)
            quad_facing_out(bm, x0, z0, x1, z1, y)
    return finish(bm, "me_3_mashrabiya", recalc=False)


def build_door_arch():
    """Ground-floor pointed-arch entry with a threshold step."""
    bm = new_bm()
    opening = pointed_opening(half_w=0.70, sill=0.0, z_spring=1.60,
                              centre_off=0.22)
    framed_panel(bm, opening, reveal=0.26)
    box(bm, -0.92, -0.16, 0.0, 0.92, 0.02, 0.11)
    return finish(bm, "me_4_door_arch")


def build_parapet():
    """3 x 1 m trim band with stepped merlons."""
    bm = new_bm()
    box(bm, -W, 0.0, 0.0, W, 0.24, 0.52)
    n = 4
    span = (2 * W) / n
    for i in range(n):
        cx = -W + span * (i + 0.5)
        box(bm, cx - 0.22, 0.0, 0.52, cx + 0.22, 0.24, 0.86)
        box(bm, cx - 0.12, 0.0, 0.86, cx + 0.12, 0.24, 1.00)
    return finish(bm, "me_5_parapet")


BUILDERS = (build_solid, build_window_arch, build_mashrabiya,
            build_door_arch, build_parapet)


# ---------------------------------------------------------------------------
def build_library(scene=None):
    scene = scene or bpy.context.scene
    old = bpy.data.collections.get(COLLECTION)
    if old:
        for o in list(old.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.collections.remove(old)
    col = bpy.data.collections.new(COLLECTION)
    scene.collection.children.link(col)

    made = []
    for fn in BUILDERS:
        ob = fn()
        col.objects.link(ob)
        made.append(ob)

    existing = list(scene.get("bld_library", []))
    if COLLECTION not in existing:
        existing.append(COLLECTION)
    scene["bld_library"] = existing
    return col, made


def report(objs):
    print("\n%-20s %-26s %-22s %s" % ("object", "size XxYxZ", "Y range", "tris"))
    print("-" * 84)
    total = 0
    for ob in objs:
        me = ob.data
        me.calc_loop_triangles()
        t = len(me.loop_triangles)
        total += t
        bb = [Vector(v) for v in ob.bound_box]
        xs = [v.x for v in bb]
        ys = [v.y for v in bb]
        zs = [v.z for v in bb]
        print("%-20s %-26s %-22s %d"
              % (ob.name,
                 "%.2f x %.2f x %.2f" % (max(xs) - min(xs), max(ys) - min(ys),
                                         max(zs) - min(zs)),
                 "[%.2f, %.2f]" % (min(ys), max(ys)), t))
    print("-" * 84)
    print("%-20s %-26s %-22s %d" % ("TOTAL", "", "", total))
    return total


def render_sheet(objs, path):
    """Cycles on CPU -- EEVEE and preview rendering both need a GPU context
    and crash in background mode."""
    scene = bpy.context.scene
    sheet = bpy.data.collections.new("_sheet")
    scene.collection.children.link(sheet)
    # anything already in the scene (the factory-startup Cube, a stray building)
    # would sit at the origin behind the middle tile
    for ob in scene.objects:
        if ob.type == "MESH":
            ob.hide_render = True
    for i, ob in enumerate(objs):
        c = ob.copy()
        c.hide_render = False          # copy() inherits the flag set above
        c.location = (i * 3.4 - (len(objs) - 1) * 1.7, 0, 0)
        sheet.objects.link(c)
        # the library collection is linked to the scene too, so every original
        # sits stacked at the origin; without this they overlap the middle tile
        ob.hide_render = True

    light_data = bpy.data.lights.new("_sun", type="SUN")
    light_data.energy = 4.0
    light = bpy.data.objects.new("_sun", light_data)
    light.rotation_euler = (math.radians(58), 0, math.radians(35))
    sheet.objects.link(light)

    cam_data = bpy.data.cameras.new("_cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 18.0
    cam = bpy.data.objects.new("_cam", cam_data)
    cam.location = (0, -14, 1.5)
    cam.rotation_euler = (math.radians(90), 0, 0)
    sheet.objects.link(cam)
    scene.camera = cam

    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 24
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 560
    scene.render.film_transparent = False
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print("rendered", path)


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = argv[0] if argv else None

    col, objs = build_library()
    total = report(objs)
    print("\ncollection %r with %d modules" % (col.name, len(objs)))
    print("scene['bld_library'] = %s" % list(bpy.context.scene["bld_library"]))

    if "--render" in argv:
        i = argv.index("--render")
        png = (argv[i + 1] if len(argv) > i + 1 and argv[i + 1].endswith(".png")
               else r"C:\Users\User\Desktop\BuildingGen\me_library_sheet.png")
        render_sheet(objs, png)

    if out:
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("saved", out)
