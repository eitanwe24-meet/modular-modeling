"""Fix GIS imports that land at a fraction of their real size.

A shapefile in a geographic CRS (EPSG:4326 and friends) stores coordinates in
DEGREES. Blender treats one unit as one metre, so a city that spans 0.05 deg
imports 0.05 units wide and looks microscopic. Scaling it up by eye is not
enough, because a degree of longitude is shorter than a degree of latitude by
cos(latitude) -- at 32 deg north that is 15% -- so a uniform scale leaves the
map stretched east to west.

This converts degrees to metres on a local tangent plane centred on the data:

    east  = (lon - lon0) * 111320 * cos(lat0)
    north = (lat - lat0) * 110540

which is accurate to a few parts in a thousand across a city, and puts the
model on the origin where Blender wants it. Z is left alone -- elevation in a
shapefile is already in metres.

Install: Edit > Preferences > Add-ons > Install, pick this file.
Use:     N-panel > GIS tab, select the imported objects, press the button.
"""

import math

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty
from mathutils import Matrix, Vector

bl_info = {
    "name": "GIS Scale Fix",
    "author": "Custom Addon",
    "version": (1, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > GIS",
    "description": "Convert a degrees-based GIS import to metres at real size",
    "category": "Object",
}

def m_per_deg_lat(lat):
    """Metres in one degree of latitude, on the WGS84 ellipsoid.

    Not a constant: the meridian is 110574 m per degree at the equator and
    111694 at the pole. A single average is up to half a percent out, which is
    enough to stretch a city by several metres and to skew the east-west to
    north-south ratio visibly.
    """
    p = math.radians(lat)
    return (111132.92 - 559.82 * math.cos(2 * p) + 1.175 * math.cos(4 * p)
            - 0.0023 * math.cos(6 * p))


def m_per_deg_lon(lat):
    """Metres in one degree of longitude at this latitude, on WGS84."""
    p = math.radians(lat)
    return (111412.84 * math.cos(p) - 93.5 * math.cos(3 * p)
            + 0.118 * math.cos(5 * p))


def mesh_objects(context):
    return [o for o in context.selected_objects if o.type == "MESH"]


def world_bounds(objs):
    """(min, max) corner of everything selected, in world space."""
    lo = Vector((float("inf"),) * 3)
    hi = Vector((float("-inf"),) * 3)
    for ob in objs:
        for v in ob.data.vertices:
            w = ob.matrix_world @ v.co
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    return lo, hi


def looks_like_degrees(lo, hi):
    """Coordinates that fit inside the whole planet's lat/long range.

    A projected CRS puts you in the hundreds of thousands (UTM easting) or
    millions (Web Mercator), so anything this small is degrees -- or already
    metres and merely tiny, which the operator reports rather than guesses at.
    """
    return (abs(lo.x) <= 180.0 and abs(hi.x) <= 180.0
            and abs(lo.y) <= 90.0 and abs(hi.y) <= 90.0)


class GIS_OT_fix_scale(bpy.types.Operator):
    """Convert the selected objects from degrees to metres, at real size"""
    bl_idname = "object.gis_fix_scale"
    bl_label = "Convert Degrees To Metres"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(o.type == "MESH" for o in context.selected_objects)

    def execute(self, context):
        p = context.scene.gis_fix
        objs = mesh_objects(context)
        if not objs:
            self.report({"ERROR"}, "Select the imported objects first")
            return {"CANCELLED"}

        lo, hi = world_bounds(objs)
        if p.mode == "DEGREES" and not looks_like_degrees(lo, hi):
            self.report({"ERROR"},
                        "These are not degrees -- the data spans %.0f x %.0f, "
                        "so it is already projected. Use Multiply instead."
                        % (hi.x - lo.x, hi.y - lo.y))
            return {"CANCELLED"}

        before_x, before_y = hi.x - lo.x, hi.y - lo.y

        if p.mode == "DEGREES":
            lat0 = (lo.y + hi.y) * 0.5 if p.auto_latitude else p.latitude
            lon0 = (lo.x + hi.x) * 0.5
            sx = m_per_deg_lon(lat0)
            sy = m_per_deg_lat(lat0)
            # longitude and latitude scale differently, so this cannot be a
            # uniform scale without stretching the map east to west
            mat = (Matrix.Diagonal((sx, sy, 1.0, 1.0))
                   @ Matrix.Translation((-lon0, -lat0, 0.0)))
            note = "lat %.5f, lon %.5f  (%.0f m/deg E, %.0f m/deg N)" % (
                lat0, lon0, sx, sy)
        else:
            f = p.factor
            mat = Matrix.Diagonal((f, f, f if p.scale_z else 1.0, 1.0))
            note = "x%g" % f

        if not p.recentre and p.mode == "DEGREES":
            # put it back where it was, in metres
            mat = Matrix.Translation((lon0 * sx, lat0 * sy, 0.0)) @ mat

        for ob in objs:
            # bake through the object transform so the result is real data and
            # the object keeps a clean identity matrix
            ob.data.transform(ob.matrix_world)
            ob.data.transform(mat)
            ob.matrix_world = Matrix.Identity(4)
            ob.data.update()

        lo2, hi2 = world_bounds(objs)
        self.report({"INFO"},
                    "%d object(s): %.4f x %.4f -> %.0f x %.0f m   [%s]"
                    % (len(objs), before_x, before_y,
                       hi2.x - lo2.x, hi2.y - lo2.y, note))
        return {"FINISHED"}


class GIS_PG_props(bpy.types.PropertyGroup):
    mode: EnumProperty(
        name="Mode",
        items=(("DEGREES", "Degrees To Metres",
                "Coordinates are lat/long; convert them to real metres"),
               ("FACTOR", "Multiply",
                "Just multiply by a number, for anything else")),
        default="DEGREES")
    auto_latitude: BoolProperty(
        name="Latitude From Data", default=True,
        description="Take the latitude from the middle of the selection. Turn "
                    "off only if the import has already been moved")
    latitude: FloatProperty(
        name="Latitude", default=32.0, min=-90.0, max=90.0,
        description="Latitude the data sits at; sets how much a degree of "
                    "longitude is worth")
    recentre: BoolProperty(
        name="Move To Origin", default=True,
        description="Put the middle of the data on the world origin. Leaving "
                    "it off keeps the real coordinates, which are millions of "
                    "metres from the origin and lose precision")
    factor: FloatProperty(name="Factor", default=100000.0, min=1e-6)
    scale_z: BoolProperty(
        name="Scale Z Too", default=False,
        description="Off by default: elevation in a shapefile is already in "
                    "metres, so scaling it makes buildings kilometres tall")


class GIS_PT_panel(bpy.types.Panel):
    bl_label = "GIS Scale Fix"
    bl_idname = "GIS_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GIS"

    def draw(self, context):
        lay = self.layout
        p = context.scene.gis_fix
        lay.prop(p, "mode", text="")

        if p.mode == "DEGREES":
            lay.prop(p, "auto_latitude")
            row = lay.row()
            row.enabled = not p.auto_latitude
            row.prop(p, "latitude")
            lay.prop(p, "recentre")
        else:
            lay.prop(p, "factor")
            lay.prop(p, "scale_z")

        objs = mesh_objects(context)
        if objs:
            lo, hi = world_bounds(objs)
            box = lay.box()
            box.label(text="%d selected" % len(objs), icon="OBJECT_DATA")
            box.label(text="Spans %.5f x %.5f" % (hi.x - lo.x, hi.y - lo.y))
            if looks_like_degrees(lo, hi):
                box.label(text="Looks like degrees", icon="WORLD_DATA")
                box.label(text="Centre  lat %.4f  lon %.4f"
                          % ((lo.y + hi.y) / 2, (lo.x + hi.x) / 2))
            else:
                box.label(text="Already projected", icon="CHECKMARK")
        else:
            lay.label(text="Select the imported objects", icon="INFO")

        row = lay.row()
        row.scale_y = 1.5
        row.operator("object.gis_fix_scale", icon="FULLSCREEN_ENTER")


CLASSES = (GIS_PG_props, GIS_OT_fix_scale, GIS_PT_panel)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.gis_fix = bpy.props.PointerProperty(type=GIS_PG_props)


def unregister():
    try:
        del bpy.types.Scene.gis_fix
    except Exception:
        pass
    for c in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(c)
        except Exception:
            pass


if __name__ == "__main__":
    register()
