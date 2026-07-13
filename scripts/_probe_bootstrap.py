"""Replicate the bootstrap's dep check and report the actual exceptions per module."""

from __future__ import annotations

import importlib
import sys
import traceback

OUT_PATH = r"C:\Users\Aasish Muchala\Desktop\3dspluginlight\scripts\_bootstrap_probe.txt"

REQUIRED = ("numpy", "PIL", "requests")

lines: list[str] = []
lines.append(f"sys.path[:3]: {sys.path[:3]}")
lines.append(f"sys.path has user site-packages: "
             f"{any('Python311' in p and 'site-packages' in p for p in sys.path)}")
lines.append("")
for name in REQUIRED:
    try:
        m = importlib.import_module(name)
        lines.append(f"importlib.import_module({name!r}): OK -> {getattr(m, '__file__', '?')}")
    except Exception as e:
        lines.append(f"importlib.import_module({name!r}): FAIL")
        lines.append("".join(traceback.format_exception(type(e), e, e.__traceback__)))
lines.append("")
# Now load the bootstrap and call _missing() — the EXACT path the toolbar button runs.
try:
    sys.path.insert(0, r"C:\Users\Aasish Muchala\Desktop\3dspluginlight")
    from lightmatch_max import bootstrap as _lmb
    missing = _lmb._missing()
    lines.append(f"bootstrap._missing() -> {missing}")
except Exception as e:
    lines.append("bootstrap import / _missing() FAIL:")
    lines.append("".join(traceback.format_exception(type(e), e, e.__traceback__)))

with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"wrote {OUT_PATH}")
print("\n".join(lines))