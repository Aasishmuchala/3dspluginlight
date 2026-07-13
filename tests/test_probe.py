"""Calibration-probe tests — selection contract + response math + block wording."""

from __future__ import annotations

import math

from lightmatch_max.core.metrics import MATCH_THRESHOLD  # noqa: F401 (ensures import path)
from lightmatch_max.core.probe import probe_block, probe_response, suggest_probe


def mv(bias=0.0, warm_hi=0.0, grid=None):
    g = grid if grid is not None else [0.5] * 16
    return {
        "lum": {"p1": 0.01 + bias, "p5": 0.05 + bias, "p25": 0.25 + bias, "p50": 0.5 + bias,
                "p75": 0.75 + bias, "p95": 0.95, "p99": 0.99, "mean": 0.5 + bias},
        "clip": {"hi": 0.02, "lo": 0.02},
        "contrast": {"spread": 0.9, "midSlope": 1.0},
        "wb": {"shadow": {"r": 0.1, "g": 0.1, "b": 0.1}, "highlight": {"r": 0.8, "g": 0.8, "b": 0.8},
               "warmthShadow": 0.0, "warmthHighlight": warm_hi, "tint": 0.0},
        "sat": {"mean": 0.2, "p95": 0.4},
        "grid": g,
    }


def test_suggest_picks_largest_relative_numeric_step_2_4():
    recipe = {"values": [
        {"param": "cam.iso", "set": 400, "from": 100, "step": 1},          # step 1 → excluded
        {"param": "sun.intensity_mult", "set": 1.8, "from": 1.0, "step": 2},  # rel = 0.8/max(1,0.2)=0.8
        {"param": "cm.type", "set": "Exponential", "from": "Reinhard", "step": 5},  # string + step5
        {"param": "sun.kelvin", "set": 5200, "from": 6500, "step": 2},       # placement → excluded
    ]}
    got = suggest_probe(recipe, "vray7max")
    assert got == {"param": "sun.intensity_mult", "from": 1.0, "to": 1.8}


def test_suggest_skips_strings_placements_and_out_of_step():
    recipe = {"values": [
        {"param": "cm.type", "set": "Exponential", "from": "Reinhard", "step": 5},
        {"param": "sun.kelvin", "set": 5200, "from": 6500, "step": 2},  # placement kind
        {"param": "cam.iso", "set": 400, "from": 100, "step": 1},
    ]}
    assert suggest_probe(recipe, "vray7max") is None


def test_zero_from_uses_span_floor_no_infinite_relative():
    # dome.intensity from 0 → 0.5: without the span floor this reads as infinite relative
    recipe = {"values": [
        {"param": "dome.intensity", "set": 0.5, "from": 0.0, "step": 3},
        {"param": "sun.intensity_mult", "set": 1.9, "from": 1.0, "step": 2},
    ]}
    got = suggest_probe(recipe, "vray7max")
    assert got is not None and got["param"] in ("dome.intensity", "sun.intensity_mult")
    # both finite relatives — no crash, a real winner is chosen
    assert math.isfinite(got["to"])


def test_suggest_none_on_junk():
    assert suggest_probe({}, "vray7max") is None
    assert suggest_probe({"values": "nope"}, "vray7max") is None
    assert suggest_probe({"values": [{"param": "x", "set": "s", "from": "s", "step": 2}]}, "vray7max") is None


def test_probe_response_math():
    base = mv(bias=0.0, warm_hi=0.0)
    brighter_warmer = mv(bias=0.2, warm_hi=0.1)
    r = probe_response(base, brighter_warmer)
    assert r["d_ev"] is not None and r["d_ev"] > 0            # probe brighter
    assert r["d_warmth_highlight"] is not None and r["d_warmth_highlight"] > 0  # warmer
    # centroid shift: bias the grid to the right on the probe
    left = mv(grid=[1, 0, 0, 0] * 4)
    right = mv(grid=[0, 0, 0, 1] * 4)
    r2 = probe_response(left, right)
    assert r2["d_centroid_x"] is not None and r2["d_centroid_x"] > 0


def test_probe_response_none_channels_on_no_signal():
    black = mv(bias=-0.5)  # p50 floors near 0 → no exposure signal, no centroid
    # force a truly black grid so centroid/key_fill are None
    black["grid"] = [0.0] * 16
    black["lum"]["p50"] = 0.0
    r = probe_response(black, black)
    assert r["d_ev"] is None
    assert r["d_centroid_x"] is None


def test_probe_block_wording_and_na():
    r = {"d_ev": 0.42, "d_warmth_highlight": None, "d_centroid_x": -0.1, "d_key_fill_ratio": None}
    blk = probe_block("sun.intensity_mult", 1.0, 1.8, r)
    assert blk.startswith("MEASURED SCENE RESPONSE (calibration probe): changing sun.intensity_mult 1.0->1.8 moved:")
    assert "median 0.42 EV" in blk
    assert "highlight warmth n/a" in blk
    assert "key:fill n/a" in blk
    assert blk.endswith("Scale every magnitude in your moves by this measured sensitivity.")
