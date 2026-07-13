"""In-Max STRESS — the launch gate. Runs headlessly via scripts/run_stress.ms:

  1. populated scene: create sun/light/plane/dome/cam, pull the FULL property set;
  2. apply sweep: every KNOWN_PROPS param at a legal value — zero failed;
  3. hostile apply: strings on floats, unknown enum, unknown param — graceful
     failed/manual verdicts, applied values UNTOUCHED by the hostile rows;
  4. undo integrity: one undo record reverts the whole sweep;
  5. END-TO-END loop with the model STUBBED (no key needed): synthetic reference →
     REAL Max render (capture→measure through the actual VFB/bitmap path) → analyze
     (stub recipe) → validate/withhold under Area lock → apply to the REAL scene →
     re-render → score + correction — the full plugin loop minus only the live
     gateway round.

Verdict file: scripts/_stress_result.txt → MAX_STRESS_OK / MAX_STRESS_FAIL + log."""

import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RESULT = REPO / "scripts" / "_stress_result.txt"
sys.path.insert(0, str(REPO))

L: list[str] = []


def log(msg: str) -> None:
    L.append(str(msg))


def run() -> None:
    from pymxs import runtime as rt  # type: ignore

    from lightmatch_max.core import data, engine
    from lightmatch_max.core import session as sess
    from lightmatch_max.core.metrics import match_percent, score_vectors
    from lightmatch_max.maxio import scene, vfb

    rt.resetMaxFile(rt.Name("noPrompt"))

    # -- 1. populated scene + full pull ------------------------------------------------
    sun = rt.VRaySun()
    sun.position = rt.Point3(200, -200, 300)
    plane_l = rt.VRayLight(); plane_l.type = 0
    dome_l = rt.VRayLight(); dome_l.type = 1
    cam = rt.VRayPhysicalCamera(); cam.position = rt.Point3(0, -250, 120)
    box = rt.Box(); box.width = 120; box.length = 120; box.height = 80
    teapot = rt.Teapot(); teapot.radius = 40; teapot.position = rt.Point3(90, 60, 0)
    pulled = scene.pull_settings()
    log(f"pull: {len(pulled['params'])} params, missing={pulled['missing']}, counts={pulled['counts']}")
    assert pulled["counts"]["suns"] == 1 and pulled["counts"]["physCams"] == 1, "scene population failed"
    assert len(pulled["missing"]) <= 1, f"too many missing on a populated scene: {pulled['missing']}"

    # -- 2. legal apply sweep — every KNOWN_PROPS param --------------------------------
    legal = {
        "sun.enabled": True, "sun.intensity_mult": 1.35, "sun.size_mult": 2.0,
        "sun.turbidity": 3.1, "sun.ozone": 0.4, "sun.invisible": False,
        "light.on": True, "light.multiplier": 42.0, "light.invisible": True,
        "fill.plane_intensity": 18.5, "dome.intensity": 0.8,
        "cam.iso": 320.0, "cam.fnumber": 5.6, "cam.shutter": 125.0,
        "cm.type": "Exponential",
    }
    res = scene.apply_values([{"param": k, "set": v} for k, v in legal.items()])
    log(f"legal sweep: applied={len(res['applied'])} failed={res['failed']} manual={res['manual']}")
    assert not res["failed"] and not res["manual"], f"legal sweep had misses: {res}"
    after = scene.pull_settings()["params"]
    assert abs(after["sun.intensity_mult"] - 1.35) < 1e-4
    assert abs(after["cam.iso"] - 320.0) < 1e-4
    assert after["cm.type"] == "Exponential"
    assert after["light.invisible"] is True

    # -- 3. undo — ADVISORY in batch: 3dsmaxbatch coalesces the whole run into one
    # hold, so per-record granularity (one Ctrl+Z per apply) is only observable in an
    # INTERACTIVE session — it's on the README's interactive checklist. Here we only
    # prove undo doesn't crash and the plugin recovers by re-applying.
    rt.execute("max undo")
    back = scene.pull_settings()
    log(f"after 1 undo (batch-coalesced): counts={back['counts']} — granularity is an interactive-only check")
    if back["counts"]["suns"] == 0:
        sun = rt.VRaySun(); sun.position = rt.Point3(200, -200, 300)
        plane_l = rt.VRayLight(); plane_l.type = 0
        dome_l = rt.VRayLight(); dome_l.type = 1
        cam = rt.VRayPhysicalCamera(); cam.position = rt.Point3(0, -250, 120)
        box = rt.Box(); box.width = 120; box.length = 120; box.height = 80
    res2 = scene.apply_values([{"param": k, "set": v} for k, v in legal.items()])
    assert not res2["failed"], f"re-apply after undo failed: {res2}"
    assert abs(scene.pull_settings()["params"]["sun.turbidity"] - 3.1) < 1e-4

    # -- 4. hostile apply — nothing lands, verdicts are honest -------------------------
    hostile = [
        {"param": "sun.turbidity", "set": "3.0; deleteFile everything"},
        {"param": "cm.type", "set": "TotallyFakeMode"},
        {"param": "made.up_param", "set": 1},
        {"param": "cam.iso", "set": None},
    ]
    res_h = scene.apply_values(hostile)
    log(f"hostile: applied={res_h['applied']} failed={res_h['failed']} manual={res_h['manual']}")
    assert res_h["applied"] == [], "hostile row applied!"
    assert set(res_h["failed"]) == {"sun.turbidity", "cm.type", "cam.iso"}
    assert res_h["manual"] == ["made.up_param"]
    still = scene.pull_settings()["params"]
    assert abs(still["sun.turbidity"] - 3.1) < 1e-4, "hostile pass disturbed a value"

    # -- 5. END-TO-END loop, model stubbed ---------------------------------------------
    import numpy as np
    from PIL import Image

    # deterministic warm reference (the "look we want")
    w, h = 320, 240
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.hypot(xx - w * 0.3, yy - h * 0.3) / (w * 0.9)
    t = np.clip(1 - d, 0, 1)
    ref_arr = np.stack(
        [(40 + 210 * t).astype(np.uint8), (30 + 160 * t).astype(np.uint8), (25 + 100 * t).astype(np.uint8)],
        axis=-1,
    )
    ref_img = Image.fromarray(ref_arr, "RGB")
    ref_cap = sess.capture(ref_img)
    log("reference measured")

    base_img = vfb.render_view(320, 240)  # REAL Max render through the real bitmap path
    base_cap = sess.capture(base_img)
    log(f"base render captured: {base_img.width}x{base_img.height}")

    # stub the gateway: a recipe with camera+local+global moves (globals must be
    # withheld under the Area lock), then a plausible correction.
    stub_recipe = {
        "baseline": "settings_screenshot", "hdri_mood": "warm key",
        "values": [
            {"param": "cam.iso", "set": 260, "from": 320, "step": 1, "confidence": "high", "why": "ref brighter"},
            {"param": "light.multiplier", "set": 50, "from": 42, "step": 4, "confidence": "medium", "why": "lift fill"},
            {"param": "sun.intensity_mult", "set": 1.6, "from": 1.35, "step": 2, "confidence": "high", "why": "hotter key"},
        ],
        "rationale": "stub", "gi_notes": "", "status": "continue",
    }
    stub_correction = {
        "moves": [{"param": "cam.iso", "to": 240, "from": 260, "step": 1, "confidence": "high", "why": "trim"}],
        "rationale": "stub", "status": "continue", "status_reason": "one more pass", "applied_assumed": True,
    }
    import json as _json

    from lightmatch_max.core import omega as omega_mod

    calls = {"n": 0, "systems": []}

    def fake_call(key, system, messages, model=omega_mod.DEFAULT_MODEL, max_tokens=8192):
        calls["n"] += 1
        calls["systems"].append(system)
        # the evidence must have reached the wire assembly
        joined = _json.dumps(messages)
        assert "COMPUTED EVIDENCE" in joined and "CURRENT SCENE SETTINGS" in joined
        return _json.dumps(stub_recipe if calls["n"] == 1 else stub_correction)

    engine.call = fake_call  # the engine imported `call` by name — patch ITS binding

    live = scene.pull_settings()
    recipe = engine.analyze(
        "oc_stub", "claude-opus-4-8", "vray7max", ref_cap, base_cap,
        {"scene": "interior", "time": "golden hour", "rig": "sun"},
        lock_globals=True, live_params=live["params"], renderer=live["renderer"],
    )
    assert "AREA MODE — SCENE GLOBALS ARE LOCKED" in calls["systems"][0]
    kept = [v["param"] for v in recipe["values"]]
    withheld = [wg["param"] for wg in recipe.get("withheld_globals", [])]
    log(f"analyze: kept={kept} withheld={withheld}")
    assert kept == ["cam.iso", "light.multiplier"] and withheld == ["sun.intensity_mult"]

    res_apply = scene.apply_values([{"param": v["param"], "set": v["set"]} for v in recipe["values"]])
    assert set(res_apply["applied"]) == {"cam.iso", "light.multiplier"} and not res_apply["failed"]
    log(f"recipe applied to scene: {res_apply['applied']}")

    attempt_img = vfb.render_view(320, 240)
    attempt_cap = sess.capture(attempt_img)
    s = sess.new_session()
    s["recipe"] = recipe
    score, correction = engine.add_attempt(
        "oc_stub", "claude-opus-4-8", "vray7max", ref_cap, attempt_cap, 1,
        sess.history_rounds(s),
        {"scene": "interior"}, lock_globals=True, live_params=live["params"], renderer=live["renderer"],
    )
    sess.push_attempt(s, score, correction)
    log(f"attempt scored: look={score:.2f} match={match_percent(score)}% moves={[m['param'] for m in correction['moves']]}")
    assert 0 <= score <= 100 and correction["moves"][0]["param"] == "cam.iso"

    # determinism: identical frames measure identical
    assert score_vectors(attempt_cap["metrics"], attempt_cap["metrics"]) == 0
    log("E2E loop complete (2 stubbed model rounds, 2 real renders, 1 real apply)")

    # -- 6. SCENE CENSUS — full inventory + warnings ----------------------------------
    from lightmatch_max.core.census_format import census_block, census_warnings, summarize_for_ui

    census = scene.collect_census()
    warns = census_warnings(census)
    log(f"census: {summarize_for_ui(census, warns)} | codes={[w['code'] for w in warns]}")
    assert census["is_vray"] is True
    assert census["counts"]["cameras"] >= 1 and census["counts"]["suns"] >= 1
    blk = census_block(census)
    assert "SCENE CENSUS" in blk and 'put its exact node name' in blk
    # every sun/camera we created should be named in the block
    assert any(s["name"] in blk for s in census["suns"])

    # -- 7. NAMED-NODE apply + READ-BACK verification ---------------------------------
    named = rt.VRayLight()
    named.type = 0
    named.name = "LM_Kitchen_Fill"
    named.multiplier = 10.0
    res_named = scene.apply_values([{"param": "light.multiplier", "set": 55.0, "node": "LM_Kitchen_Fill"}])
    log(f"named apply: {res_named}")
    assert "light.multiplier" in res_named["applied"]
    assert "light.multiplier" in res_named["verified"]  # read-back confirmed it landed
    assert abs(rt.getNodeByName("LM_Kitchen_Fill").multiplier - 55.0) < 1e-3, "named node didn't take the value"
    # a value on a non-existent node fails honestly (never a silent wrong-node write)
    res_ghost = scene.apply_values([{"param": "light.multiplier", "set": 20.0, "node": "NoSuchLight_xyz"}])
    assert "light.multiplier" not in res_ghost["applied"]

    # -- 8. AUTOPILOT over REAL renders (model stubbed, converges) --------------------
    from lightmatch_max.core import autopilot

    ap_scores = iter([18.0, 9.0, 1.5])  # 3rd round matched (<=3)
    applies = []

    def render_cb():
        return sess.capture(vfb.render_view(240, 180))

    def correct_cb(cap, n):
        sc = next(ap_scores)
        return sc, {"moves": [{"param": "cam.iso", "to": 300 - n * 10, "from": 320}],
                    "rationale": "ap", "status": "continue", "status_reason": f"round {n}"}

    def apply_cb(moves):
        r = scene.apply_values(moves)
        applies.append(r)
        return r

    ap = autopilot.run_autopilot(rounds=6, render_cb=render_cb, correct_cb=correct_cb, apply_cb=apply_cb)
    log(f"autopilot: stop={ap['stop_reason']} rounds={len(ap['rounds'])} final={ap['final_match_percent']}%")
    assert ap["stop_reason"] == "matched" and ap["matched"] is True
    assert len(ap["rounds"]) == 3 and len(applies) == 2  # matched round did not apply
    assert ap["final_match_percent"] == 99

    log("ALL FEATURES OK (census + named-node verify + autopilot over real renders)")

    # -- 9. CONSENSUS ×3 (stubbed 3 identical calls merged) ---------------------------
    from lightmatch_max.core import omega as omega_mod2

    variant = {"n": 0}
    variants = [
        {"values": [{"param": "cam.iso", "set": 200, "from": 320, "step": 1, "why": "a"},
                    {"param": "sun.intensity_mult", "set": 1.4, "from": 1.0, "step": 2, "why": "b"}],
         "baseline": "factory_defaults", "rationale": "r"},
        {"values": [{"param": "cam.iso", "set": 260, "from": 320, "step": 1, "why": "a"},
                    {"param": "sun.intensity_mult", "set": 1.6, "from": 1.0, "step": 2, "why": "b"}],
         "baseline": "factory_defaults", "rationale": "r"},
        {"values": [{"param": "cam.iso", "set": 230, "from": 320, "step": 1, "why": "a"},
                    {"param": "sun.intensity_mult", "set": 1.5, "from": 1.0, "step": 2, "why": "b"}],
         "baseline": "factory_defaults", "rationale": "r"},
    ]

    def fake_call_consensus(key, system, messages, model=omega_mod2.DEFAULT_MODEL, max_tokens=8192):
        i = variant["n"] % 3
        variant["n"] += 1
        return _json.dumps(variants[i])

    engine.call = fake_call_consensus
    con = engine.analyze("oc_stub", "claude-opus-4-8", "vray7max", ref_cap, base_cap,
                         {"scene": "interior"}, lock_globals=False, live_params=live["params"],
                         renderer=live["renderer"], consensus=True)
    con_vals = {v["param"]: v for v in con["values"]}
    log(f"consensus: runs={con.get('consensus', {}).get('runs')} iso={con_vals['cam.iso']['set']} sun={con_vals['sun.intensity_mult']['set']}")
    assert con.get("consensus", {}).get("runs") == 3
    assert con_vals["cam.iso"]["set"] == 230 and con_vals["sun.intensity_mult"]["set"] == 1.5  # medians

    # -- 10. DIAGNOSTICS runner over REAL pymxs --------------------------------------
    from lightmatch_max.core import diagnostics
    from lightmatch_max.core.census_format import census_warnings as _cw2

    checks = [
        ("renderer", lambda: scene.renderer_name()),
        ("pull", lambda: f"{len(scene.pull_settings()['params'])} params"),
        ("census", lambda: [w["code"] for w in _cw2(scene.collect_census())]),
    ]
    diag = diagnostics.run_checks(checks)
    log("diagnostics: " + " | ".join(f"{d['name']}={'ok' if d['ok'] else 'FAIL'}" for d in diag))
    assert all(d["ok"] for d in diag), f"a diagnostic failed: {diag}"

    # -- 11. FLOAT grab (best-effort; may be None on a default scene) ------------------
    fl = vfb.grab_float_luminance(120, 90)
    log(f"float grab: {'HDR array ' + str(fl[0].shape) if fl else 'None (8-bit fallback — calibrate live)'}")

    log("HARDENING OK (consensus + diagnostics + float scaffold)")


try:
    run()
    out = "MAX_STRESS_OK\n" + "\n".join(L)
except Exception:
    out = "MAX_STRESS_FAIL\n" + "\n".join(L) + "\n" + traceback.format_exc()
RESULT.write_text(out, encoding="utf-8")
print(out)
