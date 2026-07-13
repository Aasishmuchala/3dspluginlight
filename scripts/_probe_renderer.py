"""Debug — list every V-Ray-related MAXScript class available in this Max session,
dump the active renderer's class, and try the switch. Verdict goes to _probe.txt."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
OUT = REPO / "scripts" / "_probe.txt"

try:
    from pymxs import runtime as rt  # type: ignore
except Exception as e:
    OUT.write_text(f"pymxs unavailable: {e}\n", encoding="utf-8")
    raise SystemExit(1)

lines: list[str] = []

# 1. Dump the active renderer.
try:
    cur_cls = str(rt.classOf(rt.renderers.current))
    lines.append(f"current renderer class: {cur_cls}")
except Exception as e:
    lines.append(f"could not read current renderer: {e}")

# 2. Enumerate every class whose name contains "vray" via the class manager + classOf.
try:
    cms = [n for n in dir(rt) if "vray" in n.lower() or "v_ray" in n.lower()]
    lines.append(f"\nrt symbols containing 'vray' ({len(cms)}):")
    for n in cms:
        lines.append(f"  {n}")
except Exception as e:
    lines.append(f"could not dir(rt): {e}")

# 3. Probe likely V-Ray candidate classes by trying to create one (best-effort).
candidates = [
    "V_Ray_GPU_7_update_2",
    "V_Ray_GPU_7_update_2_hotfix_2",
    "V_Ray_GPU_7_update_1",
    "V_Ray_GPU_7",
    "V_Ray_GPU_next",
    "V_Ray_7_update_2",
    "V_Ray_7",
    "V_Ray_GPU",
    "VRayGPU",
    "VRay",
    "V_Ray_5_update_1",
    "V_Ray_5",
]
lines.append("\nprobing candidates:")
switched_to = None
for name in candidates:
    cls = getattr(rt, name, None)
    if cls is None:
        lines.append(f"  {name}: NOT FOUND on rt")
        continue
    try:
        inst = cls()
        rt.renderers.current = inst
        new_cls = str(rt.classOf(rt.renderers.current))
        if "v_ray" in new_cls.lower() or "vray" in new_cls.lower():
            switched_to = f"{name} -> {new_cls}"
            lines.append(f"  {name}: SWITCHED OK -> {new_cls}")
            break
        lines.append(f"  {name}: instance created but renderers.current class is {new_cls}")
    except Exception as e:
        lines.append(f"  {name}: EXC {type(e).__name__}: {e}")

if not switched_to:
    lines.append("\nNO V-Ray class could be activated; the install is missing V-Ray for Max 2026.")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {OUT}")
print("\n".join(lines))
