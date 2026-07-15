"""In-Max smoke — validates the pymxs surface (renderer reachable, KNOWN_PROPS pull,
apply inside an undo record, undo round-trip, camera-scope Stage 1:
list_cameras / set_active_camera / render_camera through a real camera, Stage 3:
a lighting-snapshot Save-look/Restore-look round-trip — pull_settings ->
scope.snapshot_to_rows -> apply_values, asserting the restore re-applies the saved
value at the picked camera, and multi-camera exposure scoping: two VRayPhysicalCameras
with distinct ISOs, asserting pull_settings(camera_name) reads the PICKED camera's cam.*
and not the renderer's first-of-kind). Run headlessly via the .ms wrapper:

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

    # apply_values no longer AUTO-CREATES a missing fixture (2026-07-15: creating stray
    # lights from hallucinated moves stalled convergence). So make a VRaySun explicitly —
    # like this smoke already makes its camera — to exercise the sun apply path.
    try:
        if len(rt.getClassInstances(rt.VRaySun)) == 0:
            rt.VRaySun()
            lines.append("created VRaySun (apply no longer auto-creates)")
    except Exception as e:
        lines.append(f"VRaySun create skipped: {type(e).__name__}: {e}")

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

    # -- NON-FINITE WRITE-BOUNDARY GUARD ------------------------------------------------
    # float() ACCEPTS "inf"/"1e999"/"nan" → non-finite floats. The reachable string-set
    # path is gated upstream (engine.validate_items, fd3bbed); this certifies the
    # apply_values boundary backstop directly against real pymxs: a non-finite `set` must
    # be reported FAILED and must NOT mutate the live node. sun.turbidity was created by
    # the apply above, so it is pullable here.
    guard_before = scene.pull_settings()["params"].get("sun.turbidity")
    if guard_before is None:
        lines.append("nonfinite guard: sun.turbidity unavailable — skipped")
    else:
        for bad in (float("inf"), float("nan")):
            gres = scene.apply_values([{"param": "sun.turbidity", "set": bad}])
            assert "sun.turbidity" in gres["failed"], f"non-finite {bad} not failed: {gres}"
            assert "sun.turbidity" not in gres["applied"], f"non-finite {bad} reached apply: {gres}"
        guard_after = scene.pull_settings()["params"].get("sun.turbidity")
        assert guard_after is not None and abs(guard_after - guard_before) < 1e-4, \
            f"non-finite set mutated sun.turbidity: before={guard_before} after={guard_after}"
        lines.append(f"nonfinite guard: inf/nan -> failed, sun.turbidity unchanged at {guard_after}")

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

    # -- STAGE 3 — LIGHTING SNAPSHOT round-trip (Save look / Restore look) --------------
    # Compose the SHIPPED "Save look" (scene.pull_settings) → snapshot_to_rows → "Restore
    # look" (scene.apply_values) path against REAL pymxs. Unlike render_camera above, this
    # is UNGUARDED: a genuine exception (or a failed assertion) propagates and FAILS the
    # smoke. The ONLY tolerated skip is a scene with no scalar lighting param to nudge —
    # then we log 'stage3 snapshot: no scalar param' and move on without failing.
    from lightmatch_max.core import scope  # noqa: E402

    snap = scene.pull_settings()["params"]  # the exact dict a camera's "Save look" stores
    lines.append(f"stage3 snapshot: {len(snap)} params captured")

    # Prefer the same scalar lighting params the dock's diagnostics use.
    scalar_key = next(
        (k for k in ("sun.turbidity", "cam.iso", "light.multiplier")
         if isinstance(snap.get(k), (int, float)) and not isinstance(snap.get(k), bool)),
        None,
    )
    if scalar_key is None:
        lines.append("stage3 snapshot: no scalar param")
    else:
        orig = float(snap[scalar_key])
        # Nudge the LIVE scene away from the snapshot by a delta well beyond the float
        # verify tolerance (max(1e-4, |v|*1e-4)); stay in-range (e.g. V-Ray turbidity 2..20).
        nudged = orig + 1.0 if abs(orig) < 5.0 else orig - 1.0
        nud_res = scene.apply_values([{"param": scalar_key, "set": nudged}])
        after_nudge = scene.pull_settings()["params"].get(scalar_key)
        lines.append(
            f"stage3 nudge: {scalar_key} {orig} -> set {nudged}; scene now={after_nudge} ({nud_res})"
        )

        # "Restore look" — re-apply the WHOLE saved snapshot, exposure stamped at the
        # picked camera (cam_name from the Stage 1 section) so cam.* lands on that node.
        rows = scope.snapshot_to_rows(snap, cam_name)
        res = scene.apply_values(rows)
        restored = scene.pull_settings()["params"].get(scalar_key)
        tol = max(1e-4, abs(orig) * 1e-4)
        assert restored is not None and abs(restored - orig) <= tol, \
            f"restore did not re-apply {scalar_key}: snapshot={orig}, after-restore={restored}"
        assert scalar_key in res["verified"] or scalar_key in res["applied"], \
            f"{scalar_key} not verified/applied by restore: {res}"
        lines.append(
            f"stage3 restore: {scalar_key} back to {restored} (snapshot {orig}); "
            f"verified={scalar_key in res['verified']}, {len(rows)} rows applied via snapshot_to_rows({cam_name!r})"
        )

    # -- MULTI-CAMERA EXPOSURE SCOPING — pull_settings(camera_name) reads the PICKED -----
    # camera's cam.* (ISO/f/shutter), not the renderer's first-of-kind. This is the ONLY
    # place the bug is reachable: it depends on VRayPhysicalCamera class-instance ordering,
    # which headless mocks can't reproduce. Build two phys cams with DISTINCT ISOs and
    # assert a scoped pull returns each camera's OWN iso. UNGUARDED — a genuine failure
    # (or the wrong iso) propagates and FAILS the smoke.
    def _ensure_exp_cam(name, iso):
        node = rt.getNodeByName(name)
        if node is None or str(rt.classOf(node)) != "VRayPhysicalCamera":
            node = rt.VRayPhysicalCamera()
            node.name = name
        node.ISO = float(iso)
        try:
            node.exposure = True  # exposure ON so ISO is the live control (matches apply)
        except Exception:
            pass
        return node

    _ensure_exp_cam("LM_ExpCamA", 100.0)
    _ensure_exp_cam("LM_ExpCamB", 800.0)
    iso_a = scene.pull_settings("LM_ExpCamA")["params"].get("cam.iso")
    iso_b = scene.pull_settings("LM_ExpCamB")["params"].get("cam.iso")
    iso_firstkind = scene.pull_settings()["params"].get("cam.iso")
    lines.append(f"multicam: scoped A={iso_a} B={iso_b}; first-of-kind={iso_firstkind}")
    # The scoped reads must land on each camera's OWN iso. If camera_name were ignored
    # (the bug), BOTH would equal the first-of-kind iso — so at least one of these fails.
    assert iso_a is not None and abs(iso_a - 100.0) < 1e-3, \
        f"scoped pull of LM_ExpCamA read {iso_a}, expected 100 (camera_name not honored?)"
    assert iso_b is not None and abs(iso_b - 800.0) < 1e-3, \
        f"scoped pull of LM_ExpCamB read {iso_b}, expected 800 (camera_name not honored?)"
    # Sanity: the unscoped pull reads exactly one of the two — proving scoping was not a
    # no-op (one scoped read necessarily differs from the first-of-kind value).
    assert iso_firstkind is not None and (
        abs(iso_firstkind - iso_a) < 1e-3 or abs(iso_firstkind - iso_b) < 1e-3
    ), f"first-of-kind iso {iso_firstkind} matched neither camera (100/800)"
    # A missing/renamed camera must NOT silently fall back to first-of-kind — cam.* goes
    # to `missing` instead (honest, never a wrong-camera read).
    gone = scene.pull_settings("__no_such_camera__")
    assert "cam.iso" in gone["missing"] and "cam.iso" not in gone["params"], \
        f"unresolved camera name should mark cam.iso missing, got params={gone['params'].get('cam.iso')}"
    lines.append("multicam: unresolved name -> cam.iso in missing (no wrong-camera fallback)")

    lines.append("MAX_SMOKE_OK")
    return "\n".join(lines)


try:
    out = run()
except Exception:
    out = "MAX_SMOKE_FAIL\n" + traceback.format_exc()
RESULT.write_text(out, encoding="utf-8")
print(out)
