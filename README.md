# Buildify Modular

A Blender 4.5 add-on that turns a footprint and a height into a building, then
lets you edit **individual panels** of it — move one window, swap one balcony,
delete one shopfront — and bake the result into a single game-ready mesh.

**The add-on is [`buildify_modular.py`](buildify_modular.py).** Everything else
in this repo supports it: asset generators, the prototypes it grew out of, and
headless tests.

Generators like Buildify compute each panel as a pure function of
`Random Value(ID, Seed)`, so no panel has a persistent identity and there is
nowhere to store a manual edit — change the seed and every panel moves. This
add-on gives each panel a real, selectable object, so an edit survives.

---

## Requirements

- **Blender 4.5** (LTS).
- **Buildify 1.0** by Pavel Oliva (sold on Blender Market), open in the
  scene. The add-on drives Buildify's `building` node group;
  it does not reimplement it. Buildify's own `.blend` and assets are **not**
  redistributed here — you need your own copy.
- A folder of `.obj` modules, if you want your own kit. The generators below
  produce one.

---

## Install

**From source, for development:**

```
install.bat              copy source into Blender's add-ons folder
install.bat --check      is what Blender runs the same as what I edited?
install.bat --zip        also rebuild buildify_modular_addon.zip
```

Then restart Blender, or disable and re-enable the add-on.

This step is not optional busywork. Blender runs a *copy* under different
names — `buildify_modular.py` → `__init__.py`, `make_me_library.py` →
`me_library.py`, `make_levant_library.py` → `levant_library.py` — so editing a
file here has no effect until it is copied over. `install.py` does the copy per
a manifest, deletes `__pycache__`, and verifies the result by hash.

`install.bat` uses Blender's own bundled Python, so nothing needs to be
installed. (The `python` on PATH under Windows is usually the Microsoft Store
stub, which runs nothing at all.)

**As a normal user:** run `install.bat --zip`, then in Blender use
*Edit > Preferences > Add-ons > Install* and pick
`buildify_modular_addon.zip`.

---

## Use it

Everything lives in the 3D viewport sidebar (`N`) under the **Building** tab,
in three panels meant to be worked top to bottom.

### 1 – Build
Pick a module kit, set a height in metres, press **Generate Building**. Floor
count comes from the height. The footprint is whatever mesh you have selected.

### 2 – Customize
**Build Modular Objects** explodes the generated building into one real object
per module, sharing mesh data. From there ordinary Blender works: click a panel
to select it, `G`/`R`/`S` to move it. The panel adds a visual asset library —
swap the selected modules to any asset, cycle through a slot's assets head to
head, select every module using the same asset or sitting in the same slot,
revert one to what Buildify originally generated, or delete it.

The library is a **folder**: drop `.obj` files in, press **Refresh From
Folder**, and each subfolder becomes its own section in the dropdown. Imported
meshes are auto-fitted to the 3 m module slot and aligned to the facade plane.

### 3 – Finish
**Optimize For Game** is one button with no options: realise instances → join →
make single-user → merge duplicate materials → weld → delete faces no ray from
outside can reach → dissolve the seams between modules. Then **Export FBX**.

**Order matters.** Baking strips the Buildify modifier and joins everything, so
Customize cannot run afterwards. Build → Customize → Finish, once.

---

## What's in this repo

| | |
|---|---|
| [`buildify_modular.py`](buildify_modular.py) | **The add-on.** v0.4 — everything above, in one file |
| [`install.py`](install.py) / [`install.bat`](install.bat) | Source → Blender's add-ons folder, verified by hash |

**Module libraries** — run inside Blender to generate assets, no modelling
required:

| | |
|---|---|
| [`make_me_library.py`](make_me_library.py) | 5 low-poly Middle Eastern modules (solid, arched window, mashrabiya, arched door, merlon parapet), 398 tris |
| [`make_levant_library.py`](make_levant_library.py) | 14 more, Levantine / Palestinian (Beirut + Gaza), 1 860 tris |
| [`build_asset_library.py`](build_asset_library.py) | Export Buildify's own modules to a sectioned `.obj` folder tree |

**Prototypes** — earlier approaches, kept because they document what was tried:

| | |
|---|---|
| [`build_prototype.py`](build_prototype.py) | Injects a per-panel override layer into a copy of Buildify's `Walls` node group |
| [`verify_prototype.py`](verify_prototype.py) | Its regression test: asset swap, positional nudge and hide, each with zero collateral change |
| [`buildify_panel_editor.py`](buildify_panel_editor.py) | v0.2, click-to-pick a panel, superseded by the explode approach |
| [`buildify_face_swap.py`](buildify_face_swap.py) | Face-level swapping on a baked mesh, superseded |
| [`dump_buildify.py`](dump_buildify.py), [`trace_walls.py`](trace_walls.py) | Reverse-engineering: dump the node graph, trace the `Walls` pipeline |

**Also here:** [`gis_scale_fix.py`](gis_scale_fix.py) is an unrelated
standalone add-on that converts a degrees-based GIS import to real metres on a
local tangent plane — a uniform scale leaves the map stretched east-west,
because a degree of longitude is shorter than a degree of latitude by
cos(latitude).

**Tests** (`test_*.py`) run headless and assert on the result:

```
blender -b buildify_1.0.blend --python test_modular.py
```

---

## Notes

`.blend`, `.obj` and `.fbx` files are **not** tracked — they are 59 of the
folder's 66 MB, and several are Buildify-derived. Run the generators to rebuild
the libraries.

Module slots are 3 × 3 m, because that is Buildify's `Module width` /
`Module height` default. Modules are authored with the body into `+Y`,
projections into `−Y`, and the origin at the base.
