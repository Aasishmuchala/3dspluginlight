"""Probe Max's pymxs-Python sys.path and USER_SITE to figure out where to install deps."""

from __future__ import annotations

import importlib
import os
import sys
import traceback

OUT_PATH = r"C:\Users\Aasish Muchala\Desktop\3dspluginlight\scripts\_paths_probe.txt"

lines = []
lines.append(f"sys.version: {sys.version.split()[0]}")
lines.append(f"sys.executable: {sys.executable}")
lines.append(f"sys.platform: {sys.platform}")
lines.append("")

# Where Python actually THINKS the packages live.
appdata = os.environ.get("APPDATA", "")
locapp = os.environ.get("LOCALAPPDATA", "")
lines.append("env vars:")
lines.append(f"  APPDATA       = {appdata!r}")
lines.append(f"  LOCALAPPDATA  = {locapp!r}")
lines.append("")

candidates = []
if appdata:
    candidates.append(os.path.join(appdata, "Python", "Python311", "site-packages"))
if locapp:
    candidates.append(os.path.join(locapp, "Python", "Python311", "site-packages"))

lines.append("Per-candidate diagnostics:")
for c in candidates:
    lines.append(f"  -- {c} --")
    lines.append(f"     os.path.isdir()  : {os.path.isdir(c)}")
    lines.append(f"     os.path.exists() : {os.path.exists(c)}")
    try:
        rp = os.path.realpath(c)
        lines.append(f"     os.path.realpath : {rp}")
        lines.append(f"     realpath isdir   : {os.path.isdir(rp)}")
    except Exception as e:
        lines.append(f"     realpath ERROR   : {type(e).__name__}: {e}")
    try:
        listing = os.listdir(c) if os.path.exists(c) else "n/a (no exists)"
        if isinstance(listing, list):
            lines.append(f"     listdir count    : {len(listing)}; first: {listing[:8]}")
        else:
            lines.append(f"     listdir          : {listing}")
    except Exception as e:
        lines.append(f"     listdir ERROR    : {type(e).__name__}: {e}")
    try:
        st = os.stat(c) if os.path.exists(c) else None
        lines.append(f"     stat             : {st}")
    except Exception as e:
        lines.append(f"     stat ERROR       : {type(e).__name__}: {e}")
lines.append("")

# Try the imports — the dependency check the bootstrap does.
lines.append("Module import attempts (with each path inserted at sys.path[0]):")
for path in candidates:
    real = os.path.realpath(path)
    for trial in (path, real):
        if trial and trial not in sys.path:
            sys.path.insert(0, trial)
    lines.append(f"  sys.path now contains {os.path.basename(os.path.normpath(path))}: "
                 f"{any(os.path.normpath(p) == os.path.normpath(path) or os.path.normpath(p) == os.path.normpath(real) for p in sys.path)}")
    for name in ("numpy", "PIL", "requests"):
        # Drop cached imports between attempts.
        sys.modules.pop(name, None)
        try:
            m = importlib.import_module(name)
            lines.append(f"    {name}: OK ({getattr(m, '__file__', '?')[:80]}, v={getattr(m, '__version__', '?')})")
        except BaseException as e:
            lines.append(f"    {name}: FAIL ({type(e).__name__}): {str(e)[:200]}")
    lines.append("")

lines.append(f"PYTHONPATH: {os.environ.get('PYTHONPATH', '(unset)')}")

with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"wrote {OUT_PATH}")
print("\n".join(lines))
