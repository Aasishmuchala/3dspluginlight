"""Cinematic DEPTH structure — the measurement cinema needs, from the render's Z pass.

The reference is a PHOTOGRAPH: it has no Z channel, so its depth can only be judged
visually by the model. What we CAN measure deterministically is the current render's
depth structure — how luminance, contrast, and color separate front-to-back — from the
V-Ray Z-depth element the capture layer renders alongside the beauty. That turns "match
the depth" from a vibe into numbers: subject-vs-background separation in stops, whether
the distance is lifting (real aerial perspective) or just underexposed, and the tonal
profile of each depth band.

PURE: operates on injected numpy arrays (H×W linear luminance 0..1 + H×W Z, any units,
larger = farther). No pymxs, no Qt. Reuses the photometry histogram helpers so a band's
percentiles are computed exactly like every other percentile in the app.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from .metrics import HIST_BINS, js_round, percentiles_from_histogram

SIGNAL_MIN = 1.0 / HIST_BINS
MIN_SIDE_PIXELS = 100  # a near/far side below this has too little signal to trust


def _counted_mask(z: np.ndarray, alpha: Optional[np.ndarray]) -> np.ndarray:
    """Pixels that count: finite Z, and opaque when an alpha mask is supplied. Always
    returned flat so callers can index the raveled arrays uniformly."""
    m = np.isfinite(np.asarray(z)).ravel()
    if alpha is not None:
        m = m & np.asarray(alpha).astype(bool).ravel()
    return m


def _median(vals: np.ndarray) -> Optional[float]:
    if vals.size == 0:
        return None
    return float(percentiles_from_histogram(vals, [50])[0])


def z_band_stats(
    lum: np.ndarray,
    z: np.ndarray,
    n_bands: int = 4,
    alpha: Optional[np.ndarray] = None,
) -> list[dict]:
    """Split counted pixels into n_bands by Z QUANTILES (equal-population depth slices)
    and report each band's tonal profile. Bands with no pixels are skipped, so the
    returned list may be shorter than n_bands (e.g. uniform Z collapses to one band)."""
    lum = np.asarray(lum, dtype=np.float64).ravel()
    z = np.asarray(z, dtype=np.float64).ravel()
    counted = _counted_mask(z, alpha).ravel()
    zc = z[counted]
    lc = lum[counted]
    total = zc.size
    if total == 0:
        return []
    edges = np.quantile(zc, np.linspace(0.0, 1.0, n_bands + 1))
    out: list[dict] = []
    for i in range(n_bands):
        lo, hi = edges[i], edges[i + 1]
        if i < n_bands - 1:
            band = (zc >= lo) & (zc < hi)
        else:
            band = (zc >= lo) & (zc <= hi)  # last band is closed on the right
        cnt = int(band.sum())
        if cnt == 0:
            continue
        bl = lc[band]
        p5, p50, p95 = percentiles_from_histogram(bl, [5, 50, 95])
        out.append(
            {
                "band": i,
                "z_lo": js_round(float(lo), 4),
                "z_hi": js_round(float(hi), 4),
                "frac": js_round(cnt / total, 4),
                "mean": js_round(float(bl.mean()), 4),
                "p5": js_round(float(p5), 4),
                "p50": js_round(float(p50), 4),
                "p95": js_round(float(p95), 4),
            }
        )
    return out


def _near_far(
    lum: np.ndarray, z: np.ndarray, alpha: Optional[np.ndarray], near_frac: float, far_frac: float
):
    """Return (near_lum_vals, far_lum_vals) — the nearest near_frac and farthest far_frac
    of counted pixels by Z."""
    lum = np.asarray(lum, dtype=np.float64).ravel()
    z = np.asarray(z, dtype=np.float64).ravel()
    counted = _counted_mask(z, alpha).ravel()
    zc = z[counted]
    lc = lum[counted]
    if zc.size == 0:
        return np.array([]), np.array([])
    near_thr = np.quantile(zc, near_frac)
    far_thr = np.quantile(zc, 1.0 - far_frac)
    near = lc[zc <= near_thr]
    far = lc[zc >= far_thr]
    return near, far


def subject_separation_stops(
    lum: np.ndarray,
    z: np.ndarray,
    alpha: Optional[np.ndarray] = None,
    near_frac: float = 0.25,
    far_frac: float = 0.25,
) -> Optional[float]:
    """log2(near-quartile median / far-quartile median) — the classical foreground-to-
    background separation in stops (positive = the subject reads brighter than its
    background). None when either side lacks signal or pixels."""
    near, far = _near_far(lum, z, alpha, near_frac, far_frac)
    if near.size < MIN_SIDE_PIXELS or far.size < MIN_SIDE_PIXELS:
        return None
    nm, fm = _median(near), _median(far)
    if nm is None or fm is None or nm <= SIGNAL_MIN or fm <= SIGNAL_MIN:
        return None
    return js_round(float(np.log2(nm / fm)), 2)


def haze_lift(
    lum: np.ndarray, z: np.ndarray, alpha: Optional[np.ndarray] = None
) -> Optional[dict]:
    """Aerial-perspective signature: does the distance have LIFTED blacks and COMPRESSED
    contrast (real atmospheric haze), or is it just dark? far_p5_minus_near_p5 > 0 means
    the far blacks are lifted; far_contrast_over_near < 1 means the far contrast is
    compressed. None when a side lacks pixels or near contrast is degenerate."""
    near, far = _near_far(lum, z, alpha, 0.25, 0.25)
    if near.size < MIN_SIDE_PIXELS or far.size < MIN_SIDE_PIXELS:
        return None
    n_p5, n_p95 = percentiles_from_histogram(near, [5, 95])
    f_p5, f_p95 = percentiles_from_histogram(far, [5, 95])
    near_contrast = n_p95 - n_p5
    ratio: Optional[float] = None
    if near_contrast >= SIGNAL_MIN:
        ratio = js_round(float((f_p95 - f_p5) / near_contrast), 4)
    return {
        "far_p5_minus_near_p5": js_round(float(f_p5 - n_p5), 4),
        "far_contrast_over_near": ratio,
    }


def depth_block(
    bands: list[dict], separation: Optional[float], haze: Optional[dict]
) -> str:
    """The prompt text block. Names its honesty upfront: the reference is a photo (no Z),
    so the model judges ITS depth visually; only the render's structure is measured."""
    import json

    payload = {
        "bands": bands,
        "subject_separation_stops": separation,
        "haze": haze,
    }
    guidance = (
        "Subject separation in stops maps to key vs fill and to background exposure; a "
        "reference with more separation than the render wants a brighter key / darker "
        "background, not a global exposure change. A positive far-black lift "
        "(far_p5_minus_near_p5 > 0) with compressed far contrast is AERIAL PERSPECTIVE — "
        "add or keep atmospheric fog/haze (step 6) rather than lifting global exposure."
    )
    return (
        "MEASURED DEPTH STRUCTURE (current render, from its Z pass — the reference is a "
        "photo, judge ITS depth visually): "
        + json.dumps(payload, separators=(",", ":"))
        + " "
        + guidance
    )


def depth_evidence(
    cur_lum: np.ndarray,
    cur_z: Optional[np.ndarray],
    alpha: Optional[np.ndarray] = None,
) -> Optional[dict]:
    """Convenience bundle: {bands, separation_stops, haze} for the current render, or
    None when there is no usable Z pass (missing, shape-mismatched, or all non-finite)."""
    if cur_z is None:
        return None
    cur_lum = np.asarray(cur_lum, dtype=np.float64)
    cur_z = np.asarray(cur_z, dtype=np.float64)
    if cur_lum.shape != cur_z.shape:
        return None
    if not np.isfinite(cur_z).any():
        return None
    bands = z_band_stats(cur_lum, cur_z, 4, alpha)
    if not bands:
        return None
    return {
        "bands": bands,
        "separation_stops": subject_separation_stops(cur_lum, cur_z, alpha),
        "haze": haze_lift(cur_lum, cur_z, alpha),
    }
