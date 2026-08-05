"""
Second wave of low-poly facade modules for `lib_middle_eastern` -- Levantine /
Palestinian vernacular (Beirut + Gaza).

Same slot convention as make_me_library.py, so these drop into the same grid:

    X  -1.5 .. +1.5   (3 m wide, origin centred)
    Z   0.0 ..  3.0   (origin at the BOTTOM)
    Y   0.0 .. +0.2   (facade plane at Y=0, body goes INTO +Y)
    Y   negative      (anything projecting outward: balconies, shutters, signs)

Fourteen modules:

    walls/      me_6_block_wall        unrendered concrete block, running bond
                me_7_breeze_block      pierced screen wall (stairs / lightwell)
                me_8_rc_frame          expressed RC frame with block infill
    windows/    me_9_triple_arch       Lebanese central-hall triple arcade
                me_10_shutter_window   louvered timber shutters, folded open
                me_11_grille_window    small window, steel grille, concrete lintel
                me_12_window_ac        window with split A/C unit and drain pipe
    balconies/  me_13_balcony_iron     cantilever slab, wrought-iron railing
                me_14_balcony_block    solid parapet topped with breeze block
                me_15_balcony_glazed   later aluminium-glazed infill balcony
    doors/      me_16_shop_shutter     roller-shutter shopfront with sign fascia
                me_17_double_door      double entry door, transom, stone surround
    trim/       me_18_roof_tanks       parapet with water tanks + solar collector
                me_19_rebar_top        unfinished floor, stub columns, rebar

Run:
    blender -b <any.blend> --python make_levant_library.py -- [out.blend]
                                        [--export <assets root>] [--render [png]]
"""

import importlib.util
import math
import os
import sys

import bmesh
import bpy

HERE = os.path.dirname(os.path.abspath(__file__))

# reuse the first library's helpers verbatim -- the whole point is that the two
# waves share one set of conventions. Packaged into the add-on the file is
# renamed me_library.py, so accept either name.
_base = None
for _cand in ("make_me_library.py", "me_library.py"):
    if os.path.exists(os.path.join(HERE, _cand)):
        _base = os.path.join(HERE, _cand)
        break
if _base is None:
    raise ImportError("make_me_library.py not found next to %s" % __file__)
_spec = importlib.util.spec_from_file_location("make_me_library", _base)
mk = importlib.util.module_from_spec(_spec)
sys.modules["make_me_library"] = mk
_spec.loader.exec_module(mk)

W, H, DEPTH = mk.W, mk.H, mk.DEPTH
new_bm, box, quad_facing_out = mk.new_bm, mk.box, mk.quad_facing_out
rect_pts, framed_panel, finish = mk.rect_pts, mk.framed_panel, mk.finish

COLLECTION = mk.COLLECTION          # extend the existing library, don't fork it

SECTION = {
    "me_6_block_wall": "walls",
    "me_7_breeze_block": "walls",
    "me_8_rc_frame": "walls",
    "me_9_triple_arch": "windows",
    "me_10_shutter_window": "windows",
    "me_11_grille_window": "windows",
    "me_12_window_ac": "windows",
    "me_13_balcony_iron": "balconies",
    "me_14_balcony_block": "balconies",
    "me_15_balcony_glazed": "balconies",
    "me_16_shop_shutter": "doors",
    "me_17_double_door": "doors",
    "me_18_roof_tanks": "trim",
    "me_19_rebar_top": "trim",
}


# ---------------------------------------------------------------------------
# extra helpers
# ---------------------------------------------------------------------------
def bar(bm, x0, y0, z0, x1, y1, z1):
    """Open-ended prism: four sides, no end caps.

    Balusters and rebar are always capped by a rail or buried in a slab, so the
    two end faces are never seen -- dropping them saves a third of the tris on
    the parts a facade needs most of.
    """
    v = [bm.verts.new(p) for p in (
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))]
    for f in ((0, 1, 5, 4),      # -Y (outward)
              (3, 7, 6, 2),      # +Y
              (0, 4, 7, 3),      # -X
              (1, 2, 6, 5)):     # +X
        bm.faces.new([v[i] for i in f])
    return v


def sloped_plate(bm, x0, x1, y_back, z_back, y_front, z_front, t):
    """Closed slab whose two long edges sit at different heights.

    A vertical shear of `box`, so the hand-wound winding stays outward.
    """
    v = [bm.verts.new(p) for p in (
        (x0, y_front, z_front), (x1, y_front, z_front),
        (x1, y_back, z_back), (x0, y_back, z_back),
        (x0, y_front, z_front + t), (x1, y_front, z_front + t),
        (x1, y_back, z_back + t), (x0, y_back, z_back + t))]
    for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
              (3, 7, 6, 2), (0, 4, 7, 3), (1, 2, 6, 5)):
        bm.faces.new([v[i] for i in f])
    return v


def prism_x(bm, x0, x1, cy, cz, r, segs=6):
    """Closed prism about the X axis -- water tanks, pipes, drums.

    Wound by hand for the same reason `box` is: a loose island cannot be
    reoriented by recalc_face_normals once it is disconnected from the shell.
    """
    ring = [(cy + r * math.cos(2 * math.pi * i / segs),
             cz + r * math.sin(2 * math.pi * i / segs)) for i in range(segs)]
    a = [bm.verts.new((x0, y, z)) for (y, z) in ring]
    b = [bm.verts.new((x1, y, z)) for (y, z) in ring]
    for i in range(segs):
        j = (i + 1) % segs
        bm.faces.new((a[i], a[j], b[j], b[i]))
    bm.faces.new(list(reversed(a)))       # -X cap
    bm.faces.new(b)                       # +X cap
    return a + b


def shift(pts, dx=0.0, dz=0.0):
    return [(x + dx, z + dz) for (x, z) in pts]


def _dedupe(pts):
    out = []
    for p in pts:
        if not out or abs(p[0] - out[-1][0]) > 1e-6 or abs(p[1] - out[-1][1]) > 1e-6:
            out.append(p)
    return out


def round_opening(half_w, sill, z_spring, segs=6):
    """Ordered loop for a semicircular-headed opening (Levantine arcade)."""
    pts = [(-half_w, sill), (half_w, sill)]
    for i in range(segs + 1):
        a = math.pi * i / segs
        pts.append((half_w * math.cos(a), z_spring + half_w * math.sin(a)))
    return _dedupe(pts)


def shell(bm):
    """Orient a framed_panel shell before hand-wound parts are added to it."""
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])


def weld(bm, dist=1e-5):
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=dist)


def screen_bars(bm, x0, z0, x1, z1, cols, rows, y, t):
    """Grid of mullions across an opening, drawn as the solid webs only.

    The holes are left genuinely empty so the recessed back pane shows through
    -- cheaper than modelling each perforation and it silhouettes correctly.
    The two directions sit at slightly different depths: coplanar quads that
    cross would z-fight at every intersection.
    """
    for k in range(1, cols):
        cx = x0 + (x1 - x0) * k / cols
        quad_facing_out(bm, cx - t, z0, cx + t, z1, y)
    for k in range(1, rows):
        cz = z0 + (z1 - z0) * k / rows
        quad_facing_out(bm, x0, cz - t, x1, cz + t, y - 0.005)


# ---------------------------------------------------------------------------
# walls
# ---------------------------------------------------------------------------
def build_block_wall():
    """Bare concrete block, laid in running bond and never rendered.

    Blocks are proud quads rather than boxes: at 3 m the mortar joint is a
    shading break, not a silhouette, so two tris per block is enough.
    """
    bm = new_bm()
    box(bm, -W, 0.0, 0.0, W, DEPTH, H)
    shell(bm)

    rows, bw, g = 7, 1.0, 0.025          # block 1 m long, 25 mm joint
    for r in range(rows):
        z0 = r * (H / rows) + g
        z1 = (r + 1) * (H / rows) - g
        off = 0.0 if r % 2 == 0 else -bw / 2.0
        x = -W + off
        while x < W - 1e-6:
            quad_facing_out(bm, max(x + g, -W + g), z0,
                            min(x + bw - g, W - g), z1, -0.02)
            x += bw
    return finish(bm, "me_6_block_wall", recalc=False)


def build_breeze_block():
    """Pierced screen wall -- stair cores and lightwells all over Gaza."""
    bm = new_bm()
    framed_panel(bm, rect_pts(-1.15, 0.30, 1.15, 2.70, seg=3), reveal=0.14)
    shell(bm)
    screen_bars(bm, -1.15, 0.30, 1.15, 2.70, cols=4, rows=5, y=0.02, t=0.055)
    return finish(bm, "me_7_breeze_block", recalc=False)


def build_rc_frame():
    """Expressed reinforced-concrete frame with recessed block infill."""
    # frame members butt end-to-end rather than overlapping: two boxes sharing a
    # corner would put two identical front faces in the same plane and z-fight
    bm = new_bm()
    box(bm, -1.22, 0.08, 0.26, 1.22, DEPTH, 2.62)        # infill, set well back
    box(bm, -W, -0.09, 0.0, -1.22, DEPTH, H)             # left column
    box(bm, 1.22, -0.09, 0.0, W, DEPTH, H)               # right column
    box(bm, -1.22, -0.09, 2.62, 1.22, DEPTH, H)          # ring beam
    box(bm, -1.22, -0.09, 0.0, 1.22, DEPTH, 0.26)        # floor band
    # blockwork inside the frame, same running bond as me_6 -- courses read as
    # masonry infill, where evenly spaced full-width bands read as a shutter
    rows, bw, g = 6, 0.82, 0.025
    for r in range(rows):
        z0 = 0.26 + (2.62 - 0.26) * r / rows + g
        z1 = 0.26 + (2.62 - 0.26) * (r + 1) / rows - g
        x = -1.22 + (0.0 if r % 2 == 0 else -bw / 2.0)
        while x < 1.22 - 1e-6:
            quad_facing_out(bm, max(x + g, -1.22 + g), z0,
                            min(x + bw - g, 1.22 - g), z1, 0.06)
            x += bw
    return finish(bm, "me_8_rc_frame", recalc=False)


# ---------------------------------------------------------------------------
# windows
# ---------------------------------------------------------------------------
def build_triple_arch():
    """The Lebanese central-hall triple arcade.

    Built as three independent bays that are welded afterwards: bridge_loops
    only takes one inner loop, and rect_pts(seg=3) puts matching vertices on
    each shared bay edge, so the seams merge exactly.
    """
    bm = new_bm()
    opening = round_opening(half_w=0.32, sill=0.80, z_spring=1.90, segs=6)
    for cx in (-1.0, 0.0, 1.0):
        framed_panel(bm, shift(opening, dx=cx), reveal=0.18,
                     outer=rect_pts(cx - 0.5, 0.0, cx + 0.5, H, seg=3))
    weld(bm)
    shell(bm)

    box(bm, -1.36, -0.07, 0.70, 1.36, 0.02, 0.80)        # continuous sill
    for cx in (-0.5, 0.5):                               # colonnettes
        bar(bm, cx - 0.07, -0.09, 0.80, cx + 0.07, 0.01, 1.90)
        box(bm, cx - 0.11, -0.12, 1.90, cx + 0.11, 0.02, 2.00)
    box(bm, -1.40, -0.07, 2.44, 1.40, 0.02, 2.56)        # cornice over arcade
    return finish(bm, "me_9_triple_arch", recalc=False)


def build_shutter_window():
    """Timber louvered shutters, folded flat against the wall.

    Open leaves, because closed ones hide the module they belong to and the
    half-open facade is the look anyway.
    """
    bm = new_bm()
    framed_panel(bm, rect_pts(-0.62, 0.85, 0.62, 2.35, seg=3), reveal=0.16)
    shell(bm)

    for x0 in (-1.24, 0.66):
        box(bm, x0, -0.07, 0.85, x0 + 0.58, -0.02, 2.35)
        for i in range(8):
            z0 = 0.90 + (2.30 - 0.90) * i / 8.0
            z1 = 0.90 + (2.30 - 0.90) * (i + 1) / 8.0
            quad_facing_out(bm, x0 + 0.03, z0 + 0.01, x0 + 0.55, z1 - 0.01,
                            -0.075 if i % 2 else -0.085)
    box(bm, -0.80, -0.10, 0.76, 0.80, 0.02, 0.85)        # sill
    box(bm, -0.80, -0.06, 2.35, 0.80, 0.01, 2.45)        # lintel
    return finish(bm, "me_10_shutter_window", recalc=False)


def build_grille_window():
    """Small deep-set window behind a welded steel grille."""
    bm = new_bm()
    framed_panel(bm, rect_pts(-0.45, 1.15, 0.45, 2.00, seg=2), reveal=0.20)
    shell(bm)

    for cx in (-0.23, 0.0, 0.23):
        bar(bm, cx - 0.022, -0.03, 1.15, cx + 0.022, 0.03, 2.00)
    box(bm, -0.45, -0.038, 1.55, 0.45, 0.038, 1.60)      # mid rail, clear of them
    box(bm, -0.64, -0.07, 2.00, 0.64, 0.02, 2.15)        # cast lintel
    box(bm, -0.58, -0.08, 1.06, 0.58, 0.02, 1.15)        # sill
    return finish(bm, "me_11_grille_window", recalc=False)


def build_window_ac():
    """Window with a split A/C condenser bracketed beside it, and its drain."""
    bm = new_bm()
    framed_panel(bm, rect_pts(-0.60, 0.95, 0.60, 2.30, seg=3), reveal=0.15)
    shell(bm)
    box(bm, -0.74, -0.09, 0.86, 0.74, 0.02, 0.95)        # sill

    box(bm, 0.72, -0.30, 2.30, 1.32, -0.02, 2.72)        # condenser
    quad_facing_out(bm, 0.80, 2.38, 1.24, 2.64, -0.305)  # fan grille
    for cx in (0.80, 1.20):                              # wall brackets
        bar(bm, cx, -0.26, 2.18, cx + 0.06, -0.04, 2.30)
    bar(bm, 0.98, -0.18, 0.95, 1.04, -0.12, 2.30)        # condensate pipe
    return finish(bm, "me_12_window_ac", recalc=False)


# ---------------------------------------------------------------------------
# balconies
# ---------------------------------------------------------------------------
def _balcony_door(bm, half_w=0.55, top=2.30, reveal=0.16):
    """French door behind a balcony, threshold clear of the slab."""
    framed_panel(bm, rect_pts(-half_w, 0.16, half_w, top, seg=3), reveal=reveal)
    shell(bm)


def build_balcony_iron():
    """Cantilever slab with a wrought-iron railing -- standard Beirut."""
    bm = new_bm()
    _balcony_door(bm)
    box(bm, -1.30, -0.62, 0.0, 1.30, 0.0, 0.14)          # slab

    # the front run stops where the returns begin -- overlapping them would put
    # two coincident front faces in the same plane at each corner
    rails = ((-1.22, -0.62, 1.22, -0.54),                # front
             (-1.30, -0.62, -1.22, 0.0),                 # left return
             (1.22, -0.62, 1.30, 0.0))                   # right return
    for (x0, y0, x1, y1) in rails:
        box(bm, x0, y0, 0.18, x1, y1, 0.24)              # bottom rail
        box(bm, x0, y0, 1.00, x1, y1, 1.08)              # top rail
    for i in range(9):                                   # front balusters
        cx = -1.22 + 2.44 * i / 8.0
        bar(bm, cx - 0.018, -0.605, 0.24, cx + 0.018, -0.565, 1.00)
    for cx in (-1.26, 1.26):                             # return balusters
        bar(bm, cx - 0.018, -0.32, 0.24, cx + 0.018, -0.28, 1.00)
    return finish(bm, "me_13_balcony_iron", recalc=False)


def build_balcony_block():
    """Solid parapet capped by a course of breeze block -- Gaza / Khan Younis."""
    bm = new_bm()
    _balcony_door(bm, half_w=0.70, top=2.30)
    box(bm, -1.34, -0.66, 0.0, 1.34, 0.0, 0.14)          # slab

    # front run and returns tile the perimeter without overlapping (see
    # build_balcony_iron); the coping is offset outward by the same rule
    walls = ((-1.22, -0.66, 1.22, -0.54, -1.22, -0.68, 1.22, -0.52),
             (-1.34, -0.66, -1.22, 0.0, -1.36, -0.68, -1.22, 0.02),
             (1.22, -0.66, 1.34, 0.0, 1.22, -0.68, 1.36, 0.02))
    for (x0, y0, x1, y1, cx0, cy0, cx1, cy1) in walls:
        box(bm, x0, y0, 0.14, x1, y1, 0.84)              # solid parapet
        box(bm, cx0, cy0, 0.84, cx1, cy1, 0.92)          # coping
        box(bm, x0, y0, 1.26, x1, y1, 1.36)              # block course cap
    for i in range(6):                                   # pierced top course
        cx = -1.16 + 2.32 * i / 5.0
        bar(bm, cx - 0.06, -0.64, 0.92, cx + 0.06, -0.56, 1.26)
    return finish(bm, "me_14_balcony_block", recalc=False)


def build_balcony_glazed():
    """Balcony closed in later with aluminium sliders -- ubiquitous retrofit.

    The wall behind stays a plain slab: once the box is glazed the original
    facade is not readable from outside, so modelling it would be tris nobody
    sees.
    """
    bm = new_bm()
    box(bm, -W, 0.0, 0.0, W, DEPTH, H)
    shell(bm)

    box(bm, -1.30, -0.60, 0.0, 1.30, 0.0, 0.12)          # floor
    box(bm, -1.30, -0.60, 2.86, 1.30, 0.0, H)            # soffit
    box(bm, -1.30, -0.60, 0.12, 1.30, -0.52, 0.92)       # spandrel
    box(bm, -1.30, -0.60, 0.12, -1.22, 0.0, 2.86)        # left cheek
    box(bm, 1.22, -0.60, 0.12, 1.30, 0.0, 2.86)          # right cheek

    quad_facing_out(bm, -1.22, 0.92, 1.22, 2.86, -0.565)  # glazing
    for cx in (-0.41, 0.41):
        bar(bm, cx - 0.03, -0.60, 0.92, cx + 0.03, -0.54, 2.86)
    box(bm, -1.22, -0.59, 2.30, 1.22, -0.55, 2.36)       # transom, clear of them
    return finish(bm, "me_15_balcony_glazed", recalc=False)


# ---------------------------------------------------------------------------
# doors
# ---------------------------------------------------------------------------
def build_shop_shutter():
    """Roller-shutter shopfront, three quarters down, sign board over."""
    bm = new_bm()
    framed_panel(bm, rect_pts(-1.20, 0.0, 1.20, 2.40, seg=3), reveal=0.22)
    shell(bm)

    for i in range(11):                                  # corrugated curtain
        z0 = 0.62 + (2.36 - 0.62) * i / 11.0
        z1 = 0.62 + (2.36 - 0.62) * (i + 1) / 11.0
        quad_facing_out(bm, -1.18, z0, 1.18, z1, 0.04 if i % 2 else 0.07)
    box(bm, -1.26, -0.11, 2.40, 1.26, 0.02, 2.62)        # roller housing
    box(bm, -1.44, -0.15, 2.62, 1.44, 0.02, 2.96)        # sign fascia
    box(bm, -1.26, -0.15, 0.0, 1.26, 0.02, 0.10)         # threshold
    return finish(bm, "me_16_shop_shutter", recalc=False)


def build_double_door():
    """Double entry with a transom light and a dressed-stone surround."""
    bm = new_bm()
    framed_panel(bm, rect_pts(-0.72, 0.0, 0.72, 2.45, seg=3), reveal=0.24)
    shell(bm)

    for x0 in (-0.70, 0.02):                             # leaves
        box(bm, x0, 0.10, 0.10, x0 + 0.68, 0.18, 2.05)
        for j in range(2):
            z0 = 0.30 + j * 0.86
            quad_facing_out(bm, x0 + 0.09, z0, x0 + 0.59, z0 + 0.66, 0.085)
    box(bm, -0.72, 0.10, 2.05, 0.72, 0.20, 2.13)         # transom bar
    for x0 in (-0.94, 0.72):                             # jambs
        box(bm, x0, -0.09, 0.0, x0 + 0.22, 0.02, 2.45)
    box(bm, -0.94, -0.09, 2.45, 0.94, 0.02, 2.64)        # head
    box(bm, -0.98, -0.22, 0.0, 0.98, 0.02, 0.12)         # step
    return finish(bm, "me_17_double_door", recalc=False)


# ---------------------------------------------------------------------------
# trim / roofline
# ---------------------------------------------------------------------------
def build_roof_tanks():
    """Roof edge with water tanks and a solar collector behind the parapet.

    Tanks sit in +Y (roof side) so the module still caps a facade cleanly.
    """
    bm = new_bm()
    box(bm, -W, 0.0, 0.0, W, 0.22, 0.62)                 # parapet
    box(bm, -W, -0.04, 0.62, W, 0.26, 0.70)              # coping

    # tanks and collector share the roof in X so nothing interpenetrates; the
    # stands run down to the deck rather than stopping behind the parapet
    for cx in (-0.10, 0.70):                             # tanks on sleepers
        prism_x(bm, cx, cx + 0.70, 0.60, 1.02, 0.30, segs=6)
        for cy in (0.42, 0.74):
            bar(bm, cx + 0.06, cy, 0.10, cx + 0.64, cy + 0.06, 0.76)
    sloped_plate(bm, -1.40, -0.30, 1.05, 1.22, 0.55, 0.86, 0.06)  # collector
    for cx in (-1.36, -0.42):
        bar(bm, cx, 1.00, 0.10, cx + 0.06, 1.06, 1.22)   # back legs
        bar(bm, cx, 0.55, 0.10, cx + 0.06, 0.61, 0.86)   # front legs
    return finish(bm, "me_18_roof_tanks", recalc=False)


def build_rebar_top():
    """Floor left unfinished for a storey that has not been built yet."""
    bm = new_bm()
    box(bm, -W, 0.0, 0.0, W, 0.55, 0.26)                 # slab edge
    box(bm, -0.78, 0.10, 0.26, 0.78, 0.34, 0.74)         # low block screen
    for cx in (-1.10, 0.80):                             # stub columns
        box(bm, cx, 0.06, 0.26, cx + 0.30, 0.36, 0.98)
        for (dx, dy) in ((0.05, 0.05), (0.23, 0.05),
                         (0.05, 0.25), (0.23, 0.25)):
            bar(bm, cx + dx, 0.06 + dy, 0.98,
                cx + dx + 0.022, 0.06 + dy + 0.022, 1.46)
    return finish(bm, "me_19_rebar_top", recalc=False)


BUILDERS = (build_block_wall, build_breeze_block, build_rc_frame,
            build_triple_arch, build_shutter_window, build_grille_window,
            build_window_ac, build_balcony_iron, build_balcony_block,
            build_balcony_glazed, build_shop_shutter, build_double_door,
            build_roof_tanks, build_rebar_top)


# ---------------------------------------------------------------------------
def build_library(scene=None, with_base=True):
    """Add these modules to lib_middle_eastern, rebuilding the first wave too."""
    scene = scene or bpy.context.scene
    if with_base:
        col, base = mk.build_library(scene)          # clears + rebuilds wave one
    else:
        col = bpy.data.collections.get(COLLECTION)
        if col is None:
            col = bpy.data.collections.new(COLLECTION)
            scene.collection.children.link(col)
        base = [o for o in col.objects if o.type == "MESH"]

    made = []
    for fn in BUILDERS:
        ob = fn()
        if ob.name in col.objects:
            col.objects.unlink(col.objects[ob.name])
        col.objects.link(ob)
        made.append(ob)
    return col, base, made


def build_full_library(scene=None):
    """Both waves as one (collection, objects) pair.

    Matches make_me_library.build_library's shape so the add-on's "Create
    Middle Eastern Library" button can call either builder and get all 19
    modules instead of only the original five.
    """
    col, base, made = build_library(scene)
    return col, base + made


def export_objects(objs, root):
    """Write each module to <root>/<section>/<name>.obj, Blender OBJ axes."""
    written = []
    for ob in objs:
        section = SECTION.get(ob.name)
        if not section:
            continue
        d = os.path.join(root, section)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "%s.obj" % ob.name)

        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        ob.hide_set(False)
        ob.select_set(True)
        bpy.context.view_layer.objects.active = ob
        loc = ob.matrix_world.copy()
        ob.matrix_world.identity()
        try:
            bpy.ops.wm.obj_export(
                filepath=path, export_selected_objects=True,
                export_materials=True, apply_modifiers=True,
                forward_axis="NEGATIVE_Z", up_axis="Y")
        finally:
            ob.matrix_world = loc
        written.append((section, path))
    return written


def render_sheet(objs, path, cols=5, gap_x=3.4, gap_z=4.2):
    """Contact sheet, Cycles on CPU (EEVEE needs a GPU context in background)."""
    scene = bpy.context.scene
    sheet = bpy.data.collections.new("_sheet")
    scene.collection.children.link(sheet)
    for ob in scene.objects:
        if ob.type == "MESH":
            ob.hide_render = True

    rows = (len(objs) + cols - 1) // cols
    for i, ob in enumerate(objs):
        r, c = divmod(i, cols)
        n = min(cols, len(objs) - r * cols)
        cp = ob.copy()
        cp.hide_render = False
        cp.location = (c * gap_x - (n - 1) * gap_x / 2.0, 0, -r * gap_z)
        sheet.objects.link(cp)

    light_data = bpy.data.lights.new("_sun", type="SUN")
    light_data.energy = 4.0
    light = bpy.data.objects.new("_sun", light_data)
    light.rotation_euler = (math.radians(58), 0, math.radians(35))
    sheet.objects.link(light)

    span_x = cols * gap_x
    span_z = rows * gap_z
    cam_data = bpy.data.cameras.new("_cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = span_x + 1.0
    cam = bpy.data.objects.new("_cam", cam_data)
    cam.location = (0, -22, 1.5 - (rows - 1) * gap_z / 2.0)
    cam.rotation_euler = (math.radians(90), 0, 0)
    sheet.objects.link(cam)
    scene.camera = cam

    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 24
    scene.render.resolution_x = 2400
    scene.render.resolution_y = int(2400 * (span_z + 1.0) / (span_x + 1.0))
    scene.render.film_transparent = False
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print("rendered", path)


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = argv[0] if argv and argv[0].endswith(".blend") else None

    col, base, made = build_library()
    print("\nwave one (unchanged): %d modules" % len(base))
    total = mk.report(made)
    print("\ncollection %r now holds %d modules" % (col.name,
                                                    len(base) + len(made)))
    print("new geometry: %d tris" % total)

    if "--export" in argv:
        i = argv.index("--export")
        root = (argv[i + 1] if len(argv) > i + 1 and not argv[i + 1].startswith("--")
                else os.path.join(os.path.expanduser("~"), "Desktop",
                                  "BuildingAssets"))
        print("\nexporting to %s" % root)
        for section, path in export_objects(made, root):
            print("  %-11s %s" % (section + "/", os.path.basename(path)))

    if "--render" in argv:
        i = argv.index("--render")
        png = (argv[i + 1] if len(argv) > i + 1 and argv[i + 1].endswith(".png")
               else os.path.join(HERE, "levant_library_sheet.png"))
        render_sheet(made, png)

    if out:
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("saved", out)
