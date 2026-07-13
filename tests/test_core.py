"""Core behavior beyond raw parity: data loaders, prompt selection, scope/Area-mode
withholding, validation, evidence assembly, session bookkeeping, JSON extraction."""

from __future__ import annotations

import json

import pytest

from lightmatch_max.core import data, engine, session as sess
from lightmatch_max.core.omega import parse_json_from_text
from lightmatch_max.core.scope import scope_of, withhold_globals


def test_packs_loaded_with_both_targets():
    assert data.target_label("vray7max").startswith("V-Ray")
    assert data.target_label("vantage33").startswith("Chaos Vantage")
    total = sum(len(g["entries"]) for g in data.sheet("vray7max")) + sum(
        len(g["entries"]) for g in data.sheet("vantage33")
    )
    assert total >= 300


def test_lookup_and_clamp():
    e = data.lookup("vray7max", "sun.intensity_mult")
    assert e and e["ui_path"]
    v, flagged = data.clamp("vray7max", "sun.intensity_mult", 1e12)
    assert flagged and v == e["range"][1]
    v, flagged = data.clamp("vray7max", "sun.intensity_mult", e["default"])
    assert not flagged


def test_system_prompt_variants():
    free = data.system_prompt("vray7max", "recipe", False)
    locked = data.system_prompt("vray7max", "recipe", True)
    corr = data.system_prompt("vray7max", "correction", False)
    assert "AREA MODE" not in free and "AREA MODE — SCENE GLOBALS ARE LOCKED" in locked
    assert "CORRECTION ROUND" in corr
    assert "OUTPUT FORMAT" in free and '"values"' in free  # embedded schema


def test_scope_and_withhold():
    assert scope_of("cam.iso") == "camera"
    assert scope_of("light.multiplier") == "local"
    assert scope_of("sun.intensity_mult") == "global"
    out = withhold_globals(
        {"values": [{"param": "cam.iso", "set": 200}, {"param": "sun.intensity_mult", "set": 1.4, "why": "w"}]},
        "values",
    )
    assert [v["param"] for v in out["values"]] == ["cam.iso"]
    assert out["withheld_globals"] == [{"param": "sun.intensity_mult", "set": 1.4, "why": "w"}]


def test_validate_items_drops_unknown_dedupes_and_clamps():
    cleaned = engine.validate_items(
        "vray7max",
        {
            "values": [
                {"param": "sun.intensity_mult", "set": 1e12, "from": 1},
                {"param": "sun.intensity_mult", "set": 2, "from": 1},   # dupe — first wins
                {"param": "made.up_knob", "set": 5},                      # unknown — dropped
                {"param": "cam.iso", "set": 400, "from": 100},
            ]
        },
        "recipe",
    )
    vals = cleaned["values"]
    assert [v["param"] for v in vals] == ["sun.intensity_mult", "cam.iso"]
    assert vals[0]["clamped"] is True


def test_build_user_content_shape():
    m = {"diff": {f"grid.{i}": 0.01 for i in range(16)}}
    content = engine.build_user_content(
        "recipe",
        [{"label": "REFERENCE:", "b64": "QUJD"}],
        m,
        context={"scene": "interior", "time": "", "rig": "sun"},
        live_params={"sun.turbidity": 2.5},
        renderer="V_Ray_7",
    )
    kinds = [c["type"] for c in content]
    assert kinds[0] == "text" and kinds[1] == "image"
    joined = "\n".join(c.get("text", "") for c in content if c["type"] == "text")
    assert "COMPUTED EVIDENCE" in joined
    assert "SPATIAL ASYMMETRY" in joined
    assert "SCENE CONTEXT — scene: interior, rig: sun" in joined
    assert "CURRENT SCENE SETTINGS" in joined and "sun.turbidity = 2.5" in joined


def test_parse_json_from_text_robustness():
    assert parse_json_from_text('noise {"a": {"b": 1}} trailing')["a"]["b"] == 1
    assert parse_json_from_text('{"s": "brace } in string"}')["s"] == "brace } in string"
    assert parse_json_from_text("no json here") is None


def test_session_history_and_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "SESS_DIR", tmp_path)
    s = sess.new_session()
    s["recipe"] = {"values": [{"param": "cam.iso", "from": 100, "set": 200, "why": "w"}]}
    for i in range(10):
        sess.push_attempt(s, 20 - i, {"moves": [{"param": "cam.iso", "from": 200, "to": 190 - i, "why": "trim"}]})
    assert len(s["attempts"]) == engine.ATTEMPTS_CAP
    assert s["attempt_count"] == 10
    rounds = sess.history_rounds(s)
    assert rounds[0]["round"] == 0
    assert rounds[1]["round"] == 3  # oldest stored is attempt 3 (10 - 8 + 1)
    sess.save(s)
    listed = sess.list_sessions()
    assert listed and listed[0]["attempts"] == engine.ATTEMPTS_CAP
    assert listed[0]["best_score"] == 11


def test_dumps_r4_rounds_and_compacts():
    out = engine.dumps_r4({"a": 0.123456789, "b": [1.00004]})
    assert out == '{"a":0.1235,"b":[1.0]}'
