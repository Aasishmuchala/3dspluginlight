"""Launch entry point — checks the hard Python dependencies BEFORE importing the core
(which imports numpy at module load), so a missing package shows a clear, actionable
message box in 3ds Max instead of a raw ImportError buried in the MAXScript listener.

The startup macro calls `lightmatch_max.bootstrap.launch()`. This module imports nothing
heavy at top level, so importing IT never fails on a missing dependency."""

from __future__ import annotations

import importlib

REQUIRED = ("numpy", "PIL", "requests")


def _missing() -> list[str]:
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
