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
