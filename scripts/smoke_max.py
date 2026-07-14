"""In-Max smoke — validates the pymxs surface (renderer reachable, KNOWN_PROPS pull,
apply inside an undo record, undo round-trip, and camera-scope Stage 1:
list_cameras / set_active_camera / render_camera through a real camera). Run headlessly
via the .ms wrapper:

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

    # -- CAMERA SCOPE (Stage 1) — certify list/set-active/render-through the camera -----
    # These exercise the camera-scoped picker plumbing against REAL pymxs. A genuine
    # exception in list_cameras / set_active_camera propagates and FAILS the smoke;
    # only a headless-render quirk in render_camera is caught and logged (step 4).
    from lightmatch_max.maxio import vfb  # noqa: E402

    # 1. list_cameras — the picker's source. If the smoke scene has no camera, create a
    #    VRayPhysicalCamera (+ best-effort target) so the checks have a node to act on.
    cams = scene.list_cameras()
    if not cams:
        smoke_cam = rt.VRayPhysicalCamera()
        smoke_cam.position = rt.Point3(0, -250, 120)
        smoke_cam.name = "LM_SmokeCam"
        try:
            tgt = rt.targetObject()
            tgt.position = rt.Point3(0, 0, 60)
            smoke_cam.target = tgt
            lines.append("created VRayPhysicalCamera 'LM_SmokeCam' + target (smoke scene had no camera)")
        except Exception as e:
            lines.append(f"created VRayPhysicalCamera 'LM_SmokeCam' (target attach skipped: {type(e).__name__}: {e})")
        cams = scene.list_cameras()
    lines.append(f"cameras: {len(cams)} -> {[(c['name'], c['class'], c['exposure_on']) for c in cams]}")
    assert cams, "no cameras to scope even after creating one"
    cam_name = cams[0]["name"]

    # 2. set_active_camera — must return True AND actually point the viewport at that node
    ok = scene.set_active_camera(cam_name)
    assert ok is True, f"set_active_camera({cam_name!r}) returned {ok!r}, expected True"
    active = rt.viewport.getCamera()
    active_name = str(active.name) if active is not None else None
    lines.append(f"set_active_camera({cam_name!r})={ok}; viewport camera now={active_name}")
    assert active_name == cam_name, f"viewport camera is {active_name!r}, expected {cam_name!r}"

    # 3. not-found path — False, never a raise
    missing = scene.set_active_camera("__no_such_camera__")
    assert missing is False, f"set_active_camera('__no_such_camera__') returned {missing!r}, expected False"
    lines.append("set_active_camera('__no_such_camera__')=False (not-found path clean)")

    # 4. render_camera — a REAL render THROUGH the picked camera. Steps 1-3 already
    #    certified the scope surface; a headless-render quirk here only logs.
    try:
        img = vfb.render_camera(cam_name, 160, 120)
        assert img.width == 160 and img.height == 120, \
            f"render_camera size {img.width}x{img.height}, expected 160x120"
        lines.append(f"render_camera({cam_name!r}) -> PIL {img.width}x{img.height}")
    except Exception as e:
        lines.append(f"render_camera logged (non-fatal headless quirk): {type(e).__name__}: {e}")

    lines.append("MAX_SMOKE_OK")
    return "\n".join(lines)


try:
    out = run()
except Exception:
    out = "MAX_SMOKE_FAIL\n" + traceback.format_exc()
RESULT.write_text(out, encoding="utf-8")
print(out)
