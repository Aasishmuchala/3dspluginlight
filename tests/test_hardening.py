"""Pre-test hardening: consensus merge, diagnostics runner, depth sanity-gate."""

from __future__ import annotations

import numpy as np

from lightmatch_max.core.consensus import merge_consensus_recipes
from lightmatch_max.core.depth_evidence import depth_evidence, z_pass_is_usable
from lightmatch_max.core.diagnostics import all_passed, format_report, run_checks


# -- consensus ------------------------------------------------------------------------
def _run(iso, sun, extra=None):
    vals = [
        {"param": "cam.iso", "set": iso, "from": 100, "step": 1, "why": "w"},
        {"param": "sun.intensity_mult", "set": sun, "from": 1.0, "step": 2, "why": "k"},
    ]
    if extra:
        vals.append(extra)
    return {"baseline": "factory_defaults", "values": vals, "rationale": "r"}


def test_consensus_medians_numerics_and_counts():
    merged = merge_consensus_recipes([_run(200, 1.4), _run(260, 1.6), _run(230, 1.5)])
    vals = {v["param"]: v for v in merged["values"]}
    assert vals["cam.iso"]["set"] == 230          # median of 200/260/230
    assert vals["sun.intensity_mult"]["set"] == 1.5
    assert vals["cam.iso"]["consensus_n"] == 3
    assert merged["consensus"]["runs"] == 3
    # metadata (why/from) comes from the first run
    assert vals["cam.iso"]["from"] == 100


def test_consensus_keeps_single_run_params_and_majority_strings():
    r1 = _run(200, 1.4, {"param": "cm.type", "set": "Exponential", "from": "Reinhard", "step": 5})
    r2 = _run(210, 1.4, {"param": "cm.type", "set": "Exponential", "from": "Reinhard", "step": 5})
    r3 = _run(220, 1.4, {"param": "dome.intensity", "set": 0.5, "from": 1.0, "step": 3})  # only run 3
    merged = merge_consensus_recipes([r1, r2, r3])
    vals = {v["param"]: v for v in merged["values"]}
    assert vals["cm.type"]["set"] == "Exponential"        # majority string
    assert vals["dome.intensity"]["consensus_n"] == 1      # single-run param kept
    assert vals["dome.intensity"]["set"] == 0.5


def test_consensus_per_fixture_moves_are_distinct():
    r = {"values": [{"param": "light.multiplier", "set": 40, "node": "A"},
                    {"param": "light.multiplier", "set": 12, "node": "B"}]}
    merged = merge_consensus_recipes([r, r, r])
    keys = {(v["param"], v.get("node")) for v in merged["values"]}
    assert keys == {("light.multiplier", "A"), ("light.multiplier", "B")}


def test_consensus_empty_and_cap():
    assert merge_consensus_recipes([])["values"] == []
    big = {"values": [{"param": f"p{i}", "set": i, "consensus_n": 1} for i in range(40)]}
    assert len(merge_consensus_recipes([big], max_items=32)["values"]) == 32


# -- diagnostics ----------------------------------------------------------------------
def test_diagnostics_runs_and_formats():
    def ok():
        return "fine"

    def boom():
        raise RuntimeError("nope")

    results = run_checks([("A", ok), ("B", boom)])
    assert results[0] == {"name": "A", "ok": True, "detail": "fine"}
    assert results[1]["ok"] is False and "nope" in results[1]["detail"]
    assert not all_passed(results)
    rep = format_report(results)
    assert "1/2 checks passed" in rep and "✓ A" in rep and "✗ B" in rep
    assert all_passed(run_checks([("A", ok)]))


# -- depth sanity gate ----------------------------------------------------------------
def test_depth_gate_rejects_constant_and_beauty():
    H, W = 80, 120
    lum = np.tile(np.linspace(0.2, 0.7, W), (H, 1))
    # constant z → unusable
    assert not z_pass_is_usable(lum, np.full((H, W), 5.0))
    assert depth_evidence(lum, np.full((H, W), 5.0)) is None
    # z IS the beauty (identical) → unusable
    assert not z_pass_is_usable(lum, lum.copy())
    assert depth_evidence(lum, lum.copy()) is None
    # a real depth field (varies in x, uncorrelated-enough with lum's structure) → usable
    z = np.tile(np.linspace(0, 100, W), (H, 1))
    lum2 = np.tile(np.linspace(0.7, 0.2, H)[:, None], (1, W))  # lum varies in Y, z in X
    assert z_pass_is_usable(lum2, z)
    assert depth_evidence(lum2, z) is not None
