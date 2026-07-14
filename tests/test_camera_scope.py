"""B1 — stamp_camera_node: physical-camera recipe rows (known_props node == "cam")
get tagged with the PICKED camera's exact scene-node name so they land on THAT
camera, not the renderer's first-of-kind camera. Pure: no Qt, no pymxs — runs in the
default core suite."""

from __future__ import annotations

from lightmatch_max.core.scope import stamp_camera_node


def test_camera_params_get_node_stamped():
    rows = [
        {"param": "cam.iso", "set": 260},
        {"param": "cam.fnumber", "set": 8.0},
        {"param": "cam.shutter", "set": 125.0},
    ]
    out = stamp_camera_node(rows, "Cam_Kitchen")
    assert [r["node"] for r in out] == ["Cam_Kitchen", "Cam_Kitchen", "Cam_Kitchen"]


def test_non_camera_params_pass_through_unchanged():
    rows = [
        {"param": "sun.intensity_mult", "set": 1.6},
        {"param": "light.multiplier", "set": 50},
    ]
    out = stamp_camera_node(rows, "Cam_Kitchen")
    assert "node" not in out[0]
    assert "node" not in out[1]
    assert out[0]["param"] == "sun.intensity_mult"
    assert out[1]["param"] == "light.multiplier"


def test_explicit_node_is_preserved():
    rows = [{"param": "cam.iso", "set": 260, "node": "Cam_Bathroom"}]
    out = stamp_camera_node(rows, "Cam_Kitchen")
    assert out[0]["node"] == "Cam_Bathroom"  # not overwritten


def test_falsy_camera_name_is_a_noop():
    rows = [{"param": "cam.iso", "set": 260}, {"param": "sun.intensity_mult", "set": 1.6}]
    for empty in ("", None):
        out = stamp_camera_node(rows, empty)
        assert all("node" not in r for r in out)


def test_original_rows_are_not_mutated():
    src = {"param": "cam.iso", "set": 260}
    rows = [src]
    out = stamp_camera_node(rows, "Cam_Kitchen")
    assert "node" not in src            # input dict untouched
    assert out[0] is not src            # a fresh row was returned
    assert out[0]["node"] == "Cam_Kitchen"


def test_non_dict_rows_pass_through():
    rows = [{"param": "cam.iso", "set": 260}, "not-a-dict", None]
    out = stamp_camera_node(rows, "Cam_Kitchen")
    assert out[0]["node"] == "Cam_Kitchen"
    assert out[1] == "not-a-dict"
    assert out[2] is None


def test_hostile_param_never_raises():
    """The camera stress sweep's finding: a row whose 'param' is unhashable (list/dict)
    must pass through untouched, not raise TypeError on the known_props lookup — matching
    validate_items / withhold_globals, which guard isinstance(param, str)."""
    rows = [
        {"param": ["cam.iso"], "set": 100},   # unhashable list param
        {"param": {"x": 1}, "set": 100},      # unhashable dict param
        {"param": 123, "set": 100},           # non-str, hashable
        {"param": None, "set": 100},
        {"set": 100},                          # no param key at all
        {"param": "cam.iso", "set": 100},     # the one real cam row still stamps
    ]
    out = stamp_camera_node(rows, "PhysCam01")
    assert out[:5] == rows[:5]                 # every hostile row passed through untouched
    assert out[5]["node"] == "PhysCam01"       # the genuine cam.iso row still got stamped


def test_non_list_values_returned_unchanged():
    """A non-list `values` (None / scalar / str) is returned as-is rather than iterated —
    no raise, honoring the 'NEVER raises' contract even off the real call path."""
    for bad in (None, 123, 3.14):
        assert stamp_camera_node(bad, "Cam_Kitchen") is bad
