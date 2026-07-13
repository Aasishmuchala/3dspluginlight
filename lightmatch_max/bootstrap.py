"""Launch entry point — checks the hard Python dependencies BEFORE importing the core
(which imports numpy at module load), so a missing package shows a clear, actionable
message box in 3ds Max instead of a raw ImportError buried in the MAXScript listener.

The startup macro calls `lightmatch_max.bootstrap.launch()`. This module imports nothing
heavy at top level, so importing IT never fails on a missing dependency."""

from __future__ import annotations

import importlib
import os
import sys

REQUIRED = ("numpy", "PIL", "requests")


def _ensure_usersite_on_path() -> None:
    """3ds Max's interactive Python doesn't auto-initialize site.py, so the user-site
    directory (where the bundled pip falls back to via --target) is NOT on sys.path
    like it is for the standalone python.exe. Try several candidates — site.py's value
    first (works when site is initialized), then hardcoded env-var paths (works when
    it isn't). For each candidate, also resolve realpath() before adding — handles
    Windows AppContainer virtualization where APPDATA points to a per-app sandbox
    inside Packages\\<sid>\\LocalCache; realpath returns the on-disk location other
    apps like Max can actually read."""
    import os as _os
    candidates: list[str] = []
    try:
        import site
        candidates.append(site.getusersitepackages())
    except Exception:
        pass
    for env_var in ("APPDATA", "LOCALAPPDATA"):
        base = _os.environ.get(env_var)
        if base:
            candidates.append(_os.path.join(base, "Python", "Python311", "site-packages"))
    for path in candidates:
        if not path or path in sys.path:
            continue
        # Add both the env-var-derived path and its realpath — the realpath handles
        # Windows AppContainer sandbox redirection; the literal path covers the
        # normal case. Whichever exists and is readable will do.
        for candidate in (path, _os.path.realpath(path)):
            if candidate and candidate not in sys.path:
                sys.path.insert(0, candidate)
        return


def _missing() -> list[str]:
    _ensure_usersite_on_path()
    out = []
    for mod in REQUIRED:
        try:
            importlib.import_module(mod)
        except Exception:
            out.append("Pillow" if mod == "PIL" else mod)
    return out


def launch():
    missing = _missing()
    if missing:
        msg = (
            "LightMatch needs these Python packages, which aren't in 3ds Max's Python yet:\n"
            f"    {', '.join(missing)}\n\n"
            "Install them into Max's Python user-site (from a normal command prompt):\n"
            '    python -m pip install --python-version 3.11 --only-binary=:all: '
            '--target \"%APPDATA%\\Python\\Python311\\site-packages\" \"numpy<2\" Pillow requests\n\n'
            "(V-Ray's native module needs numpy 1.x, so pin numpy<2.) Then reopen LightMatch."
        )
        try:
            from pymxs import runtime as rt  # type: ignore
            rt.messageBox(msg, title="LightMatch — missing dependencies")
        except Exception:
            print("[LightMatch] " + msg)
        return None

    from .ui.dock import show_dock
    return show_dock()
