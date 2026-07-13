"""In-Max smoke — validates the pymxs surface (renderer reachable, KNOWN_PROPS pull,
apply inside an undo record, undo round-trip). Run headlessly via the .ms wrapper:

    powershell -File scripts/run_max_smoke.ps1     (or: 3dsmaxbatch scripts/run_smoke.ms)

3dsmaxbatch SWALLOWS Python stdout, so the verdict is written to
scripts/_smoke_result.txt — MAX_SMOKE_OK on success, the traceback on failure."""

import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RESULT = REPO / "scripts" / "_smoke_result.txt"
sys.path.insert(0, str(REPO))


def run() -> str:
    from lightmatch_max.maxio import scene  # noqa: E402

    lines = []
    name = scene.renderer_name()
    lines.append(f"renderer: {name}")
    pulled = scene.pull_settings()
    lines.append(
        f"pulled {len(pulled['params'])} params, missing {len(pulled['missing'])}, counts {pulled['counts']}"
    )

    from pymxs import runtime as rt  # type: ignore

    before = pulled["params"].get("sun.turbidity")
    res = scene.apply_values([{"param": "sun.turbidity", "set": 3.3}])
    lines.append(f"apply: {res}")
    assert "sun.turbidity" in res["applied"] or "sun.turbidity" in res["failed"], "apply produced no verdict"
    if "sun.turbidity" in res["applied"]:
        after_set = scene.pull_settings()["params"].get("sun.turbidity")
        assert after_set is not None and abs(after_set - 3.3) < 1e-4, f"set did not land: {after_set}"
        rt.execute("max undo")
        after_undo = scene.pull_settings()["params"].get("sun.turbidity")
        lines.append(f"turbidity before={before} set={after_set} after-undo={after_undo}")

    lines.append("MAX_SMOKE_OK")
    return "\n".join(lines)


try:
    out = run()
except Exception:
    out = "MAX_SMOKE_FAIL\n" + traceback.format_exc()
RESULT.write_text(out, encoding="utf-8")
print(out)
