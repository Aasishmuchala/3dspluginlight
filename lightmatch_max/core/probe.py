"""Calibration probe — the "measure your scene's real sensitivity" mechanism, ported
faithfully from the web app (src/store/useEngine.ts suggestProbe / addProbeRenderImpl
and src/lib/client-adapter.ts's MEASURED SCENE RESPONSE block).

The idea: after the initial recipe, re-render with exactly ONE knob changed and measure
what actually moved. Then every subsequent magnitude the model proposes is scaled by the
scene's MEASURED response to that knob instead of the model's guess — the single biggest
lever against "the values were off". PURE: recipe dict in, MetricVector dicts in, text
out. No pymxs, no network.
"""

from __future__ import annotations

import math
from typing import Optional

from . import data
from .metrics import js_round, scene_evidence, wb_exposure_evidence


def suggest_probe(recipe: dict, target: str) -> Optional[dict]:
    """Pick the ONE recipe move worth probing: a step-2..4 NUMERIC knob (not a
    placement / dropdown / color token), the one with the largest RELATIVE change. The
    range-span floor (denom = max(|from|, span*0.1)) stops a from≈0 knob from reading as
    an infinite relative change. Returns {param, from, to} or None."""
    if not isinstance(recipe, dict) or not isinstance(recipe.get("values"), list):
        return None
    best: Optional[dict] = None
    best_rel = 0.0
    for v in recipe["values"]:
        if not isinstance(v, dict) or not isinstance(v.get("param"), str):
            continue
        step = v.get("step")
        if not (isinstance(step, (int, float)) and not isinstance(step, bool) and 2 <= step <= 4):
            continue
        s = v.get("set")
        frm = v.get("from")
        if not _finite_num(s) or not _finite_num(frm):
            continue
        entry = data.lookup(target, v["param"])
        if entry and entry.get("kind") == "placement":
            continue  # an instruction, not a scalar knob
        span = 0.0
        rng = entry.get("range") if entry else None
        if isinstance(rng, list) and len(rng) == 2 and rng[0] < rng[1]:
            span = rng[1] - rng[0]
        denom = max(abs(frm), span * 0.1)
        if not (denom > 0):
            continue
        rel = abs(s - frm) / denom
        if rel > best_rel:
            best_rel = rel
            best = {"param": v["param"], "from": float(frm), "to": float(s)}
    return best


def _finite_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def probe_response(base_metrics: dict, probe_metrics: dict) -> dict:
    """The MEASURED response of the scene to the single probed knob: probe render vs the
    BASE render, per channel. Each channel is None when the pixels carry no signal for it
    (same guards the evidence helpers use — a None here can never be a fabricated
    number)."""
    # d_ev: log2(probe.p50 / base.p50) — positive = the probe render came out brighter.
    d_ev = wb_exposure_evidence(probe_metrics, base_metrics)["exposure_gap_ev"]

    warmth_delta = probe_metrics["wb"]["warmthHighlight"] - base_metrics["wb"]["warmthHighlight"]
    d_warmth = js_round(warmth_delta, 4) if math.isfinite(warmth_delta) else None

    # centroid / key:fill via scene_evidence with base as "reference" and probe as
    # "current" — the same projection the model reads, so the signs agree.
    sc = scene_evidence(base_metrics, probe_metrics)
    ref_c = sc["light_centroid"]["reference"]
    cur_c = sc["light_centroid"]["current"]
    d_centroid_x = js_round(cur_c["x"] - ref_c["x"], 4) if (ref_c and cur_c) else None

    ref_kf = sc["key_fill_ratio"]["reference"]
    cur_kf = sc["key_fill_ratio"]["current"]
    d_kf = js_round(cur_kf - ref_kf, 4) if (ref_kf is not None and cur_kf is not None) else None

    return {
        "d_ev": d_ev,
        "d_warmth_highlight": d_warmth,
        "d_centroid_x": d_centroid_x,
        "d_key_fill_ratio": d_kf,
    }


def probe_block(param: str, frm, to, response: dict) -> str:
    """The verbatim-ported prompt block (n/a for null channels)."""

    def fmt(v) -> str:
        return str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else "n/a"

    r = response or {}
    return (
        f"MEASURED SCENE RESPONSE (calibration probe): changing {param} {frm}->{to} moved: "
        f"median {fmt(r.get('d_ev'))} EV, highlight warmth {fmt(r.get('d_warmth_highlight'))}, "
        f"light centroid x {fmt(r.get('d_centroid_x'))}, key:fill {fmt(r.get('d_key_fill_ratio'))}. "
        f"Scale every magnitude in your moves by this measured sensitivity."
    )
