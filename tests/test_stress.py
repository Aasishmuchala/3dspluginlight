"""Adversarial stress — degenerate images, hostile model replies, corrupt sessions,
and parse edge cases. The invariant under attack everywhere: no crash, no NaN, no
fabricated signal, and hostile input can never reach the scene-apply surface."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from lightmatch_max.core import data, engine, session as sess
from lightmatch_max.core.metrics import (
    match_percent,
    measure_from_pixels,
    score_vectors,
    wb_exposure_evidence,
    scene_evidence,
)
from lightmatch_max.core.omega import parse_json_from_text
from lightmatch_max.core.scope import withhold_globals


def img(w, h, fill=(128, 128, 128, 255)):
    a = np.zeros((h, w, 4), dtype=np.uint8)
    a[..., 0], a[..., 1], a[..., 2], a[..., 3] = fill
    return a


def finite_deep(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            finite_deep(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            finite_deep(v, f"{path}[{i}]")
    elif isinstance(x, float):
        assert math.isfinite(x), f"non-finite at {path}: {x}"


# -- degenerate images ---------------------------------------------------------------
@pytest.mark.parametrize(
    "name,pixels",
    [
        ("all_black", img(64, 48, (0, 0, 0, 255))),
        ("all_white", img(64, 48, (255, 255, 255, 255))),
        ("fully_transparent", img(64, 48, (90, 120, 60, 0))),
        ("one_pixel", img(1, 1, (200, 100, 50, 255))),
        ("one_row_strip", img(64, 1, (10, 200, 30, 255))),
        ("one_col_strip", img(1, 64, (10, 200, 30, 255))),
        ("two_by_two", img(2, 2, (5, 250, 128, 255))),
    ],
)
def test_degenerate_images_never_crash_or_nan(name, pixels):
    h, w = pixels.shape[:2]
    m = measure_from_pixels(pixels, w, h)
    finite_deep(m, name)
    assert len(m["grid"]) == 16
    # self-score is always a perfect match, even for degenerates
    assert score_vectors(m, m) == 0
    ev = wb_exposure_evidence(m, m)
    se = scene_evidence(m, m)
    # black frame: no CCT fabrication, no exposure signal, no centroid
    if name == "all_black":
        assert ev["exposure_gap_ev"] is None
        assert ev["wb_estimate_k"]["reference_highlights"] is None
        assert se["light_centroid"]["reference"] is None


def test_flat_frame_fabricates_no_sky_and_transparent_hole_stays_neutral():
    flat = measure_from_pixels(img(64, 48), 64, 48)
    assert "sky" not in flat
    holed = img(64, 48, (128, 128, 128, 255))
    holed[10:30, 20:40, 3] = 0  # transparent hole
    m2 = measure_from_pixels(holed, 64, 48)
    full = measure_from_pixels(img(64, 48), 64, 48)
    assert abs(score_vectors(full, m2)) < 0.01  # hole reads neutral, not black


def test_score_extremes_clamped():
    black = measure_from_pixels(img(32, 32, (0, 0, 0, 255)), 32, 32)
    white = measure_from_pixels(img(32, 32, (255, 255, 255, 255)), 32, 32)
    s = score_vectors(black, white)
    assert 0 < s <= 100
    assert 0 <= match_percent(s) <= 100


# -- hostile model replies through validation ------------------------------------------
def test_validate_survives_garbage_items():
    cleaned = engine.validate_items(
        "vray7max",
        {
            "values": [
                None,
                42,
                {"no_param": True},
                {"param": 7, "set": 1},
                {"param": "sun.intensity_mult", "set": float("nan"), "from": 1},
                {"param": "sun.intensity_mult", "set": "not a number", "from": 1},
                {"param": "cam.iso", "set": 1e308, "from": 100},
            ]
        },
        "recipe",
    )
    vals = cleaned["values"]
    # NaN passes isinstance(float) — the clamp must still yield a finite in-range value
    finite_deep([v.get("set") for v in vals if isinstance(v.get("set"), float)])
    iso = next(v for v in vals if v["param"] == "cam.iso")
    assert iso["clamped"] is True and math.isfinite(iso["set"])


def test_validate_rejects_missing_array():
    with pytest.raises(ValueError):
        engine.validate_items("vray7max", {"rationale": "no values"}, "recipe")


def test_withhold_handles_malformed_rows():
    out = withhold_globals({"values": [None, {"set": 1}, {"param": "sun.turbidity", "set": 2.5}]}, "values")
    assert out["withheld_globals"] == [{"param": "sun.turbidity", "set": 2.5}]
    assert None in out["values"] and {"set": 1} in out["values"]  # passthrough, engine validate handles


# -- parse_json_from_text hostility -----------------------------------------------------
@pytest.mark.parametrize(
    "text,expect",
    [
        ("", None),
        ("{", None),
        ('{"a":}', None),
        ('prefix {"broken": } then {"ok": 1}', {"ok": 1}),
        ('{"nested": {"deep": [1, {"x": "}"}]}}', {"nested": {"deep": [1, {"x": "}"}]}}),
        ('```json\n{"fenced": true}\n```', {"fenced": True}),
        ("thinking… " * 1000 + '{"tail": 2}', {"tail": 2}),
    ],
)
def test_parse_json_hostile(text, expect):
    assert parse_json_from_text(text) == expect


# -- session corruption / flooding -----------------------------------------------------
def test_corrupt_session_files_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "SESS_DIR", tmp_path)
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "worse.json").write_text('"just a string"', encoding="utf-8")
    s = sess.new_session()
    sess.save(s)
    listed = sess.list_sessions()
    assert [x["id"] for x in listed if x["id"]] == [s["id"]]


def test_attempt_flood_keeps_cap_and_numbering(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "SESS_DIR", tmp_path)
    s = sess.new_session()
    for i in range(50):
        sess.push_attempt(s, 50 - i, {"moves": []})
    assert len(s["attempts"]) == engine.ATTEMPTS_CAP
    assert s["attempt_count"] == 50
    rounds = sess.history_rounds(s)
    assert rounds[-1]["round"] == 50 and rounds[0]["round"] == 43


# -- evidence assembly under hostile bundles -------------------------------------------
def test_user_content_with_incomplete_grid_skips_asymmetry():
    content = engine.build_user_content("recipe", [], {"diff": {"grid.0": 0.1}})
    joined = "\n".join(c.get("text", "") for c in content)
    assert "SPATIAL ASYMMETRY" not in joined  # incomplete grid → no fabricated scalars


def test_live_params_are_capped_and_clipped():
    live = {f"k{i}": "v" * 500 for i in range(200)}
    content = engine.build_user_content("recipe", [], {"diff": {}}, live_params=live)
    block = next(c["text"] for c in content if "CURRENT SCENE SETTINGS" in c.get("text", ""))
    assert block.count("\n  k") <= 64
    assert "v" * 121 not in block
