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


def test_lookup_unhashable_param_returns_none():
    # A hand-corrupted session JSON can carry a list/dict `param` (unhashable). It must
    # miss gracefully (None), not raise TypeError on the internal dict .get() — the
    # dock's _fill_table -> data.lookup path feeds rows straight from disk.
    assert data.lookup("vray7max", ["sun", "intensity_mult"]) is None
    assert data.lookup("vray7max", {"param": "sun.intensity_mult"}) is None
    assert data.lookup("vray7max", 42) is None
    assert data.lookup("vray7max", None) is None
    # clamp() rides on lookup(), so it must stay silent on the same hostile input.
    v, flagged = data.clamp("vray7max", ["sun", "intensity_mult"], 5.0)
    assert (v, flagged) == (5.0, False)


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
    # Stage 2: attempts/recipe/history live on a per-camera SLOT, not the session top level.
    monkeypatch.setattr(sess, "SESS_DIR", tmp_path)
    s = sess.new_session()
    slot = sess.camera_slot(s, "Cam_Kitchen")
    slot["recipe"] = {"values": [{"param": "cam.iso", "from": 100, "set": 200, "why": "w"}]}
    for i in range(10):
        sess.push_attempt(slot, 20 - i, {"moves": [{"param": "cam.iso", "from": 200, "to": 190 - i, "why": "trim"}]})
    assert len(slot["attempts"]) == engine.ATTEMPTS_CAP
    assert slot["attempt_count"] == 10
    rounds = sess.history_rounds(slot)
    assert rounds[0]["round"] == 0
    assert rounds[1]["round"] == 3  # oldest stored is attempt 3 (10 - 8 + 1)
    sess.save(s)
    listed = sess.list_sessions()
    # list_sessions aggregates attempts + best score across ALL of a session's cameras
    assert listed and listed[0]["attempts"] == engine.ATTEMPTS_CAP
    assert listed[0]["best_score"] == 11
    assert listed[0]["cameras"] == 1  # one named camera (the "" default slot doesn't count)


def test_migrate_legacy_session_wraps_into_default_slot(tmp_path, monkeypatch):
    # A pre-Stage-2 session (top-level ref/recipe/attempts) migrates into cameras[""].
    monkeypatch.setattr(sess, "SESS_DIR", tmp_path)
    legacy = {
        "id": "lmx-legacy01", "created": "2026-07-13T00:00:00", "name": "", "target": "vray7max",
        "context": {"scene": "interior", "time": "dusk", "rig": "both"}, "lock_globals": True,
        "ref": {"metrics": {}, "b64": "QUJD", "media_type": "image/jpeg"},
        "recipe": {"values": [{"param": "cam.iso", "from": 320, "set": 260, "why": "x"}]},
        "attempts": [{"score": 8.0, "correction": {"moves": []}, "at": "t"}],
        "attempt_count": 1,
    }
    import json
    (tmp_path / "lmx-legacy01.json").write_text(json.dumps(legacy), encoding="utf-8")
    loaded = sess.load("lmx-legacy01")
    assert "ref" not in loaded and "recipe" not in loaded      # hoisted off the top level
    assert loaded["active_camera"] == ""
    slot = loaded["cameras"][""]
    assert slot["ref"]["b64"] == "QUJD"                         # reference preserved
    assert slot["recipe"]["values"][0]["param"] == "cam.iso"    # recipe preserved
    assert slot["attempt_count"] == 1 and len(slot["attempts"]) == 1
    assert loaded["lock_globals"] is True                       # session-level fields kept
    # idempotent: migrating an already-migrated session is a no-op
    assert sess.migrate_session(loaded) is loaded and loaded["cameras"][""]["attempt_count"] == 1


def test_migrate_drops_stale_toplevel_and_heals_corrupt_slots():
    # A session with cameras AND leftover legacy top-level keys: the stale keys are dropped
    # so they can't diverge from / outlive the slots (Stage 2 review finding).
    m = sess.migrate_session({"id": "z", "cameras": {"": {"ref": {"keep": 1}}}, "ref": {"stale": 9},
                              "recipe": {"stale": 1}, "attempts": [{"score": 1}]})
    assert "ref" not in m and "recipe" not in m and "attempts" not in m
    assert m["cameras"][""]["ref"] == {"keep": 1}
    # A non-dict slot at any key (hand-corrupted) is healed into a fresh slot, not left to
    # crash a reader.
    m2 = sess.migrate_session({"id": "z2", "cameras": {"": {"ref": None}, "front": "oops"}})
    assert isinstance(m2["cameras"]["front"], dict) and m2["cameras"]["front"]["ref"] is None


def test_list_sessions_survives_a_corrupt_slot(tmp_path, monkeypatch):
    # A non-dict slot at a non-active key must NOT erase the whole session from the picker.
    import json
    monkeypatch.setattr(sess, "SESS_DIR", tmp_path)
    good = sess.new_session()
    sess.push_attempt(sess.camera_slot(good, "hero"), 7.0, {"moves": []})
    good["cameras"]["ghost"] = "corrupt-not-a-dict"  # inject a bad slot
    (tmp_path / f"{good['id']}.json").write_text(json.dumps(good), encoding="utf-8")
    listed = sess.list_sessions()
    assert listed and listed[0]["id"] == good["id"]     # still shown, not dropped
    assert listed[0]["best_score"] == 7.0                # aggregation skipped the bad slot


def test_dumps_r4_rounds_and_compacts():
    out = engine.dumps_r4({"a": 0.123456789, "b": [1.00004]})
    assert out == '{"a":0.1235,"b":[1.0]}'
