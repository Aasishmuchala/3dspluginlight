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


def test_numeric_string_set_cannot_reach_apply_as_nonfinite():
    # A hostile model reply that emits `set` as a numeric STRING bypassed the numeric gate
    # and reached apply_values, where float("1e999")/float("nan") make inf/nan WITHOUT
    # raising and setattr'd a live V-Ray node. validate_items must coerce+validate strings.
    out = engine.validate_items("vray7max", {"values": [
        {"param": "sun.intensity_mult", "set": "1e999"},          # -> inf
        {"param": "sun.intensity_mult", "set": "nan", "node": "A"},
        {"param": "sun.intensity_mult", "set": "-inf", "node": "B"},
        {"param": "sun.intensity_mult", "set": "999999", "node": "C"},  # finite but wild
    ]}, "recipe")["values"]
    for it in out:                                   # every survivor is a finite number now
        assert isinstance(it["set"], (int, float)) and not isinstance(it["set"], bool)
        assert math.isfinite(float(it["set"]))
    # the three non-finite strings were dropped entirely; only the clamped 999999 survives
    assert len(out) == 1 and out[0].get("clamped") is True


def test_apply_values_float_boundary_never_setattrs_nonfinite(monkeypatch):
    # Defense-in-depth at the Max WRITE boundary. validate_items (above) closes the
    # REACHABLE hole, but a direct apply_values call / the diagnostics re-apply path / a
    # future feature could bypass it. float("inf")/float("nan")/float("1e999") all parse
    # WITHOUT raising, so apply_values' float branch must gate on math.isfinite and report
    # the param FAILED before it ever reaches setattr on a live V-Ray node. Proven by
    # injecting a fake pymxs whose node records every write.
    import contextlib
    import sys
    import types

    from lightmatch_max.maxio import scene

    class _RecordingNode:
        def __init__(self):
            object.__setattr__(self, "writes", {})

        def __setattr__(self, name, value):
            self.writes[name] = value
            object.__setattr__(self, name, value)

    class _FakeRT:
        def __init__(self):
            self.created: list[_RecordingNode] = []

        def VRaySun(self):  # both the class arg (via getattr) and the constructor
            n = _RecordingNode()
            self.created.append(n)
            return n

        def getClassInstances(self, _cls):
            return []  # none exist -> _node_for takes the create path

    fake_rt = _FakeRT()
    fake_pymxs = types.ModuleType("pymxs")
    fake_pymxs.runtime = fake_rt
    fake_pymxs.undo = lambda *a, **k: contextlib.nullcontext()
    monkeypatch.setitem(sys.modules, "pymxs", fake_pymxs)

    # control: a FINITE value MUST reach setattr — proves the fake harness exercises the
    # write path, so a later "no write" assertion means the guard fired, not a dead mock.
    ok = scene.apply_values([{"param": "sun.intensity_mult", "set": 2.5}])
    assert "sun.intensity_mult" in ok["applied"]
    assert len(fake_rt.created) == 1 and fake_rt.created[0].writes.get("intensity_multiplier") == 2.5

    # each non-finite `set` (direct float or numeric string) -> failed, and NO node is even
    # created, so setattr is never reached with a non-finite value.
    for bad in (float("inf"), float("-inf"), float("nan"), "1e999", "nan"):
        fake_rt.created.clear()
        res = scene.apply_values([{"param": "sun.intensity_mult", "set": bad}])
        assert "sun.intensity_mult" in res["failed"], f"{bad!r} not reported failed: {res}"
        assert "sun.intensity_mult" not in res["applied"], f"{bad!r} reached apply: {res}"
        assert fake_rt.created == [], f"{bad!r} resolved a node before the guard: setattr risk"


def test_history_rounds_survives_a_corrupt_attempts_list():
    # A hand-edited / hand-portable session (the module docstring invites this) can carry a
    # non-dict attempt (or non-dict recipe); history_rounds is on the correction path and
    # must degrade to fewer rounds, not throw AttributeError out of a guard-shaped function.
    slot = {"recipe": {"values": [{"param": "cam.iso", "set": 200, "from": 320}]},
            "attempts": ["GARBAGE", None, 42,
                         {"correction": {"moves": [{"param": "cam.iso", "to": 190, "from": 200}]}}],
            "attempt_count": 4}
    rounds = sess.history_rounds(slot)                       # must not raise
    assert [r["round"] for r in rounds] == [0, 4]            # recipe + the one valid attempt
    # a non-dict recipe is also tolerated (no crash, just no round 0)
    assert sess.history_rounds({"recipe": "corrupt", "attempts": []}) == []


def test_huge_int_and_snapshot_nonfinite_cannot_reach_apply():
    # A JSON integer literal with >308 digits parses to a Python int; float(10**400) and
    # math.isfinite(10**400) raise OverflowError (not inf). validate_items must DROP it, not
    # crash, and never let it (or a non-finite snapshot value) reach the apply payload.
    from lightmatch_max.core import scope, consensus
    out = engine.validate_items("vray7max", {"values": [
        {"param": "sun.intensity_mult", "set": 10 ** 400},          # huge int -> drop
        {"param": "sun.intensity_mult", "set": "1e999", "node": "A"},  # -> inf -> drop
        {"param": "sun.intensity_mult", "set": "5.0", "node": "B"},   # keep, clamped
    ]}, "recipe")["values"]
    assert all(isinstance(it["set"], (int, float)) and math.isfinite(float(it["set"])) for it in out)
    # snapshot restore is the ONE apply path that skips validate_items — it must filter too
    rows = scope.snapshot_to_rows({"sun.turbidity": float("inf"), "cam.iso": 200, "big": 10 ** 400}, "CamX")
    assert [r["param"] for r in rows] == ["cam.iso"] and math.isfinite(rows[0]["set"])
    # consensus merge must not OverflowError on a huge int (falls to majority vote)
    m = consensus.merge_consensus_recipes([{"values": [{"param": "sun.turbidity", "set": 10 ** 400}]}] * 2)
    assert len(m["values"]) == 1


def test_history_rounds_and_push_attempt_survive_hostile_bookkeeping():
    # Corrupt 'correction' (non-dict) and non-numeric 'attempt_count' must degrade, not throw.
    assert sess.history_rounds({"attempts": [{"correction": "oops"},
                                             {"correction": {"moves": [{"param": "cam.iso", "to": 1, "from": 2}]}}],
                                "attempt_count": "bad"}) [-1]["moves"][0]["param"] == "cam.iso"
    slot = {"attempt_count": "bad", "attempts": []}
    sess.push_attempt(slot, 5.0, {"moves": []})
    assert slot["attempt_count"] == 1  # recovered from the junk count


def test_measure_and_parse_degrade_on_pathological_input():
    # 0x0 image -> documented ValueError (not ZeroDivisionError); js_round(nan) -> nan (no
    # ValueError from math.floor); deeply-nested JSON -> None or a value, never RecursionError.
    from lightmatch_max.core.metrics import js_round, measure_from_pixels
    from lightmatch_max.core.omega import parse_json_from_text
    with pytest.raises(ValueError):
        measure_from_pixels(np.zeros((0,), "uint8"), 0, 0)
    assert math.isnan(js_round(float("nan")))
    parse_json_from_text('{"v":' * 2000 + "1" + "}" * 2000)  # must not raise RecursionError
