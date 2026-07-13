"""Regression pins for the 2026-07-13 adversarial-review fixes (core side)."""

from __future__ import annotations

from lightmatch_max.core import engine
from lightmatch_max.core.autopilot import run_autopilot
from lightmatch_max.core.census_format import census_warnings


def test_per_fixture_moves_survive_validation():
    """Two light.multiplier moves with DIFFERENT nodes must both be kept (per-fixture
    targeting); a true same-node duplicate still collapses."""
    cleaned = engine.validate_items(
        "vray7max",
        {"values": [
            {"param": "light.multiplier", "set": 55, "from": 30, "node": "Kitchen_Fill"},
            {"param": "light.multiplier", "set": 12, "from": 30, "node": "Living_Key"},
            {"param": "light.multiplier", "set": 99, "from": 30, "node": "Kitchen_Fill"},  # dup node → dropped
            {"param": "light.multiplier", "set": 40, "from": 30},  # no node → its own bucket
        ]},
        "recipe",
    )
    vals = cleaned["values"]
    keys = [(v["param"], v.get("node")) for v in vals]
    assert ("light.multiplier", "Kitchen_Fill") in keys
    assert ("light.multiplier", "Living_Key") in keys
    assert ("light.multiplier", None) in keys
    assert len(vals) == 3  # the duplicate Kitchen_Fill row was dropped
    assert next(v for v in vals if v.get("node") == "Kitchen_Fill")["set"] == 55  # first wins


def test_disabled_only_sun_is_flagged():
    census = {"is_vray": True, "renderer": "V_Ray_7", "cameras": [{"name": "c", "class": "VRayPhysicalCamera", "exposure_on": True}],
              "lights": [], "suns": [{"name": "TheSun", "on": False, "intensity_mult": 1.0}],
              "exposure_control": {"class": None, "active": False}, "gamma": 2.2, "color_mapping": {"type": "Reinhard"}}
    codes = {w["code"] for w in census_warnings(census)}
    assert "NO_SUN_NO_LIGHTS" in codes
    # an ENABLED sun clears it
    census["suns"][0]["on"] = True
    assert "NO_SUN_NO_LIGHTS" not in {w["code"] for w in census_warnings(census)}


def _cap():
    return {"metrics": {}, "b64": "QUJD", "media_type": "image/jpeg"}


def test_autopilot_reports_best_not_last():
    # 75 → 82 → 78 then budget: best is 82, last is 78
    scores = iter([25.0, 18.0, 22.0])  # match% = 75, 82, 78 (single worsening, not oscillation)

    def correct_cb(c, n):
        return next(scores), {"moves": [{"param": "cam.iso", "to": 200, "from": 300}], "status_reason": "r", "status": "continue"}

    res = run_autopilot(rounds=3, render_cb=_cap, correct_cb=correct_cb, apply_cb=lambda m: {"applied": ["cam.iso"]})
    assert res["stop_reason"] == "budget"
    assert res["best_match_percent"] == 82
    assert res["final_match_percent"] == 78  # last round, distinct from best


def test_autopilot_error_carries_message():
    def apply_cb(m):
        raise RuntimeError("gateway said no")

    res = run_autopilot(
        rounds=3, render_cb=_cap,
        correct_cb=lambda c, n: (15.0, {"moves": [{"param": "cam.iso", "to": 200, "from": 300}], "status_reason": "r", "status": "continue"}),
        apply_cb=apply_cb,
    )
    assert res["stop_reason"] == "error:RuntimeError"
    assert res["error_message"] == "gateway said no"  # the real reason reaches the UI
