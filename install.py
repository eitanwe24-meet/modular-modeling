"""Install this add-on into Blender, so what Blender runs is what you edited.

Editing `buildify_modular.py` here does NOT change what Blender runs. Blender
loads a *copy*, in a different folder, under different names:

    BuildingGen\\buildify_modular.py    ->  addons\\buildify_modular\\__init__.py
    BuildingGen\\make_me_library.py     ->  addons\\buildify_modular\\me_library.py
    BuildingGen\\make_levant_library.py ->  addons\\buildify_modular\\levant_library.py

Three files, three different names, and a stale copy looks exactly like a
change that had no effect -- which is the expensive failure here, because it
reads as a bug in the code you just wrote rather than as a file that never
moved.

The compiled bytecode is deleted rather than reasoned about. Python reuses a
`.pyc` when the source mtime and size recorded inside it still match the
`.py`, and a file copy can reproduce both -- so the safe move is to remove
`__pycache__` outright on every install.

Usage:
    install.py            install into the newest Blender found, then verify
    install.py --check    report drift, write nothing
    install.py --all      install into every Blender version found
    install.py --zip      also rebuild buildify_modular_addon.zip
    install.py --target D:\\path\\to\\addons   install somewhere explicit

Needs no packages, but does need a real Python. The `python` on PATH here is
the Microsoft Store stub, which exits without running anything -- use
`install.bat`, which finds Blender's own interpreter.
"""

import argparse
import hashlib
import os
import shutil
import sys
import zipfile
from pathlib import Path

ADDON = "buildify_modular"

# source file here -> name it must have inside the installed add-on package
MODULES = {
    "buildify_modular.py": "__init__.py",
    "make_me_library.py": "me_library.py",
    "make_levant_library.py": "levant_library.py",
}

HERE = Path(__file__).resolve().parent
ZIP_NAME = "buildify_modular_addon.zip"


def digest(path):
    """SHA-256 of a file, or None if it isn't there."""
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def blender_addon_dirs():
    """Every `scripts/addons` Blender might load from, newest version first.

    Blender keeps add-ons per version under the user's roaming profile, not
    next to the executable -- a portable unzipped Blender still installs here.
    Sorted by version number so a 4.5 and a 4.2 profile don't fight over which
    is "the" install.
    """
    roots = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "Blender Foundation" / "Blender")
    # macOS / Linux, so the script isn't silently Windows-only
    roots.append(Path.home() / "Library" / "Application Support" / "Blender")
    roots.append(Path.home() / ".config" / "blender")

    found = []
    for root in roots:
        if not root.is_dir():
            continue
        for version in root.iterdir():
            addons = version / "scripts" / "addons"
            if addons.is_dir():
                found.append(addons)

    def key(p):
        try:
            return tuple(int(n) for n in p.parents[1].name.split("."))
        except ValueError:
            return (0,)

    return sorted(found, key=key, reverse=True)


def targets(args):
    """The add-on folders to write to."""
    if args.target:
        return [Path(args.target).expanduser().resolve() / ADDON]
    dirs = blender_addon_dirs()
    if not dirs:
        sys.exit("No Blender add-ons folder found. Pass --target explicitly.")
    return [d / ADDON for d in (dirs if args.all else dirs[:1])]


def sources():
    """Check every source file exists before touching the install."""
    missing = [name for name in MODULES if not (HERE / name).is_file()]
    if missing:
        sys.exit("Missing source file(s): %s" % ", ".join(missing))
    return {name: HERE / name for name in MODULES}


def check(target, src):
    """Per-file state, without writing: same / differs / missing."""
    rows = []
    for name, installed_name in MODULES.items():
        want = digest(src[name])
        have = digest(target / installed_name)
        state = "same" if want == have else ("missing" if have is None
                                             else "differs")
        rows.append((name, installed_name, state))
    return rows


def install(target, src):
    """Copy the three files in, drop the bytecode, then prove it landed."""
    target.mkdir(parents=True, exist_ok=True)

    pycache = target / "__pycache__"
    if pycache.is_dir():
        shutil.rmtree(pycache)
        print("  removed __pycache__")

    for name, installed_name in MODULES.items():
        dst = target / installed_name
        # copyfile, not copy2: a fresh mtime is what stops a leftover .pyc
        # elsewhere from looking current
        shutil.copyfile(src[name], dst)
        os.utime(dst, None)
        print("  %-24s -> %s" % (name, installed_name))

    bad = [n for n, i in MODULES.items() if digest(src[n]) != digest(target / i)]
    if bad:
        sys.exit("Copy did not verify: %s" % ", ".join(bad))
    print("  verified: %d file(s) byte-identical" % len(MODULES))


def make_zip(src):
    """Rebuild the installable zip, with the package folder inside it.

    Blender's "Install from file" wants one top-level folder whose name is the
    module name, so the entries are written as buildify_modular/<file>.
    """
    out = HERE / ZIP_NAME
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, installed_name in MODULES.items():
            z.write(src[name], "%s/%s" % (ADDON, installed_name))
    print("built %s (%.1f KB)" % (out.name, out.stat().st_size / 1024))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="report drift and write nothing")
    ap.add_argument("--all", action="store_true",
                    help="install into every Blender version found")
    ap.add_argument("--zip", action="store_true",
                    help="also rebuild " + ZIP_NAME)
    ap.add_argument("--target", metavar="ADDONS_DIR",
                    help="install into this addons folder instead")
    args = ap.parse_args()

    src = sources()

    for target in targets(args):
        print(target)
        if args.check:
            for name, installed_name, state in check(target, src):
                print("  %-24s -> %-20s %s" % (name, installed_name, state))
        else:
            install(target, src)

    if args.zip:
        make_zip(src)

    if not args.check:
        print("\nRestart Blender, or disable and re-enable the add-on, to load it.")


if __name__ == "__main__":
    main()
