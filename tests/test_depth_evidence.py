"""Depth-evidence tests — synthetic ramps with known depth structure."""

from __future__ import annotations

import numpy as np

from lightmatch_max.core.depth_evidence import (
    depth_block,
    depth_evidence,
    haze_lift,
    subject_separation_stops,
    z_band_stats,
)

H, W = 80, 120


def _lum_z(bright_near=True, fog=False):
    """z increases with x (left near, right far). lum brighter near unless fog.

    For the fog case each column has a vertical tonal RANGE (dark→bright in y) so p5/p95
    are meaningful, then a distance-proportional atmospheric veil lifts the far blacks and
    a distance-proportional scale compresses far contrast — the aerial-perspective
    signature."""
    x1 = np.linspace(0, 1, W)
    z = np.tile(x1 * 100.0, (H, 1))  # 0..100, larger = farther (right)
    if fog:
        y1 = np.linspace(0.05, 0.7, H)[:, None]        # per-column tonal range (H,1)
        base = np.tile(y1, (1, W))                      # dark→bright top→bottom
        xg = np.tile(x1, (H, 1))
        lum = base * (1 - 0.4 * xg) + 0.3 * xg          # veil + compress with distance
    elif bright_near:
        lum = np.tile(0.6 - 0.4 * x1, (H, 1))           # near ~0.6, far ~0.2
    else:
        lum = np.tile(0.2 + 0.4 * x1, (H, 1))
    return lum.astype(np.float64), z.astype(np.float64)


def test_bands_partition_and_fracs_sum_to_one():
    lum, z = _lum_z()
    bands = z_band_stats(lum, z, 4)
    assert len(bands) == 4
    assert abs(sum(b["frac"] for b in bands) - 1.0) < 0.02
    # z ranges are monotonic front-to-back
    assert bands[0]["z_lo"] <= bands[-1]["z_hi"]
    # near band brighter than far band (bright_near)
    assert bands[0]["p50"] > bands[-1]["p50"]


def test_subject_separation_positive_when_subject_brighter():
    lum, z = _lum_z(bright_near=True)
    sep = subject_separation_stops(lum, z)
    assert sep is not None and sep > 0
    # invert: far brighter → negative separation
    lum2, z2 = _lum_z(bright_near=False)
    assert subject_separation_stops(lum2, z2) < 0


def test_haze_lift_signs_under_fog():
    lum, z = _lum_z(bright_near=True, fog=True)
    hz = haze_lift(lum, z)
    assert hz is not None
    assert hz["far_p5_minus_near_p5"] > 0  # far blacks lifted
    assert hz["far_contrast_over_near"] is not None and hz["far_contrast_over_near"] < 1  # far compressed


def test_alpha_mask_excludes_pixels():
    lum, z = _lum_z()
    alpha = np.ones((H, W), dtype=bool)
    alpha[:, : W // 2] = False  # drop the near half
    bands = z_band_stats(lum, z, 4, alpha=alpha)
    # every band's z should be from the far half only
    assert min(b["z_lo"] for b in bands) >= 49.0


def test_degenerate_inputs_return_none_or_empty():
    lum, z = _lum_z()
    # uniform z → collapses to a single band (or fewer), never crashes
    zu = np.full((H, W), 5.0)
    bands = z_band_stats(lum, zu, 4)
    assert len(bands) >= 1
    # all-non-finite z → no evidence
    zn = np.full((H, W), np.nan)
    assert depth_evidence(lum, zn) is None
    # None z
    assert depth_evidence(lum, None) is None
    # shape mismatch
    assert depth_evidence(lum, z[:, :10]) is None
    # tiny image doesn't crash
    z_band_stats(np.array([[0.5]]), np.array([[1.0]]), 4)


def test_depth_block_has_honesty_clause_and_payload():
    lum, z = _lum_z()
    ev = depth_evidence(lum, z)
    blk = depth_block(ev["bands"], ev["separation_stops"], ev["haze"])
    assert "the reference is a photo" in blk.lower()
    assert "MEASURED DEPTH STRUCTURE" in blk
    assert "aerial perspective" in blk.lower()


def test_separation_none_without_enough_pixels():
    # a 2-pixel image can't reach MIN_SIDE_PIXELS
    lum = np.array([[0.5, 0.2]])
    z = np.array([[1.0, 9.0]])
    assert subject_separation_stops(lum, z) is None
