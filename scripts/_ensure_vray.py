"""Headless prelude — 3dsmaxbatch defaults to the install renderer (Arnold in Max 2026
even when V-Ray is active in the UI), but the plugin drives V-Ray knobs. Try the
documented V-Ray MAXScript class names; whichever succeeds wins. No-op when V-Ray is
already the active renderer. The result is logged for the verdict file."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def ensure_vray(log_path: Path) -> str:
    try:
        from pymxs import runtime as rt  # type: ignore
    except Exception as e:
        return f"_ensure_vray: pymxs unavailable ({e})"

    def cur_name() -> str:
        try:
            return str(rt.classOf(rt.renderers.current))
        except Exception:
            return "unknown"

    before = cur_name()
    if "v_ray" in before.lower():
        return f"_ensure_vray: already on {before}"

    # Documented V-Ray class names (covers V-Ray 6 / 7 / GPU / hotfixes / updates)
    candidates = (
        "V_Ray_GPU_7_update_2",
        "V_Ray_GPU_7_update_1",
        "V_Ray_GPU_7",
        "V_Ray_GPU_next",
        "V_Ray_7_update_2",
        "V_Ray_7",
        "V_Ray_GPU",
        "VRayGPU",
        "VRay",
    )
    for name in candidates:
        cls = getattr(rt, name, None)
        if cls is None:
            continue
        try:
            rt.renderers.current = cls()
            after = cur_name()
            return f"_ensure_vray: {before} -> {after} via {name}"
        except Exception:
            continue
    return f"_ensure_vray: could not switch from {before}; tried {candidates}"


if __name__ == "__main__":
    out = ensure_vray(REPO / "scripts" / "_stress_result.txt")
    print(out)
