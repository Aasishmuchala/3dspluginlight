"""Scene-census tests — every warning rule fires and doesn't misfire, block ordering,
node instruction, basename extraction, cap."""

from __future__ import annotations

from lightmatch_max.core.census_format import (
    NODE_INSTRUCTION,
    census_block,
    census_warnings,
    summarize_for_ui,
)


def base(**kw):
    c = {
        "renderer": "V_Ray_7", "is_vray": True,
        "cameras": [{"name": "cam01", "class": "VRayPhysicalCamera", "exposure_on": True}],
        "lights": [{"name": "L1", "class": "VRayLight", "vray_type": "plane", "on": True, "multiplier": 30.0}],
        "suns": [{"name": "TheSun", "on": True, "intensity_mult": 1.0}],
        "environment_map": None, "exposure_control": {"class": None, "active": False},
        "gamma": 2.2, "color_mapping": {"type": "Reinhard"},
        "counts": {},
    }
    c.update(kw)
    return c


def codes(c):
    return {w["code"] for w in census_warnings(c)}


def test_clean_scene_has_no_warnings():
    assert census_warnings(base()) == []


def test_not_vray_blocks_and_sorts_first():
    ws = census_warnings(base(is_vray=False, renderer="Arnold"))
    assert ws[0]["code"] == "NOT_VRAY" and ws[0]["severity"] == "block"


def test_multiple_suns_and_no_lights_no_sun():
    assert "MULTIPLE_SUNS" in codes(base(suns=[{"name": "s1"}, {"name": "s2"}]))
    assert "NO_SUN_NO_LIGHTS" in codes(base(suns=[], lights=[{"name": "L", "on": False}]))
    assert "NO_SUN_NO_LIGHTS" not in codes(base())


def test_camera_exposure_off():
    c = base(cameras=[{"name": "cam", "class": "VRayPhysicalCamera", "exposure_on": False}])
    assert "CAMERA_EXPOSURE_OFF" in codes(c)
    assert "CAMERA_EXPOSURE_OFF" not in codes(base())  # on → no warn


def test_env_exposure_control():
    c = base(exposure_control={"class": "Automatic Exposure Control", "active": True})
    assert "ENV_EXPOSURE_CONTROL" in codes(c)
    # a V-Ray exposure control is not flagged
    assert "ENV_EXPOSURE_CONTROL" not in codes(base(exposure_control={"class": "VRayExposureControl", "active": True}))
    # inactive is not flagged
    assert "ENV_EXPOSURE_CONTROL" not in codes(base(exposure_control={"class": "Automatic Exposure Control", "active": False}))


def test_gamma_and_no_camera():
    assert "GAMMA_OFF" in codes(base(gamma=1.0))
    assert "GAMMA_OFF" not in codes(base(gamma=2.2))
    assert "GAMMA_OFF" not in codes(base(gamma=2.21))  # within tolerance
    assert "NO_CAMERA" in codes(base(cameras=[]))


def test_empty_census_no_crash():
    ws = census_warnings({})
    assert any(w["code"] == "NOT_VRAY" for w in ws)  # missing is_vray → block
    blk = census_block({})
    assert "SCENE CENSUS" in blk and NODE_INSTRUCTION in blk


def test_block_lists_names_and_basename_and_caps():
    lights = [{"name": f"L{i}", "class": "VRayLight", "on": True, "multiplier": float(i),
               "texmap_file": rf"C:\hdri\studio_{i}.exr"} for i in range(30)]
    c = base(lights=lights, environment_map="/textures/sky_dome.hdr")
    blk = census_block(c)
    assert "TheSun" in blk and "cam01" in blk
    assert "sky_dome.hdr" in blk         # basename of the env map
    assert "studio_0.exr" in blk         # windows-path basename
    assert "and 6 more" in blk           # 30 lights, cap 24
    assert NODE_INSTRUCTION in blk
    # exactly 24 light rows shown
    assert blk.count(" · on · mult ") == 24


def test_summarize_for_ui():
    s = summarize_for_ui(base(), census_warnings(base()))
    assert "1 light" in s and "1 cam" in s
    c = base(is_vray=False)
    assert "BLOCK" in summarize_for_ui(c, census_warnings(c))
