"""3ds Max startup hook — copy this file into
  %LOCALAPPDATA%/Autodesk/3dsMax/<version> - 64bit/ENU/scripts/startup/
and set LIGHTMATCH_MAX_REPO below (or the LIGHTMATCH_MAX env var) to the repo path.
It registers a "LightMatch" macroscript under category "LightMatch" — bind it to a
toolbar button / hotkey via Customize → Customize User Interface."""

import os
import sys

LIGHTMATCH_MAX_REPO = os.environ.get("LIGHTMATCH_MAX", r"C:\Users\aasis\lightmatch-max")


def _register():
    if LIGHTMATCH_MAX_REPO not in sys.path:
        sys.path.insert(0, LIGHTMATCH_MAX_REPO)
    from pymxs import runtime as rt  # type: ignore

    rt.macros.new(
        "LightMatch",
        "LightMatch",
        "Open LightMatch — match your render's lighting to a reference",
        "LightMatch",
        'python.Execute "import lightmatch_max.ui.dock as _lmd; _lmd.show_dock()"',
    )


try:
    _register()
except Exception as e:  # never break Max startup
    print(f"[lightmatch-max] startup registration failed: {e}")
