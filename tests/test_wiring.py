"""Engine prompt-assembly wiring for the new evidence blocks (census / probe / depth)."""

from __future__ import annotations

from lightmatch_max.core import engine
from lightmatch_max.core.census_format import census_block
from lightmatch_max.core.depth_evidence import depth_block
from lightmatch_max.core.probe import probe_block


def test_blocks_are_threaded_into_user_content():
    census = census_block({"is_vray": True, "renderer": "V_Ray_7",
                           "lights": [{"name": "Key", "class": "VRayLight", "on": True}],
                           "color_mapping": {"type": "Reinhard"}})
    probe = probe_block("sun.intensity_mult", 1.0, 1.8,
                        {"d_ev": 0.4, "d_warmth_highlight": None, "d_centroid_x": 0.1, "d_key_fill_ratio": 0.5})
    depth = depth_block([{"band": 0, "z_lo": 0, "z_hi": 1, "frac": 1.0, "mean": 0.5, "p5": 0.4, "p50": 0.5, "p95": 0.6}],
                        0.8, {"far_p5_minus_near_p5": 0.1, "far_contrast_over_near": 0.7})

    content = engine.build_user_content(
        "correction",
        [{"label": "REFERENCE:", "b64": "QUJD"}],
        {"diff": {}},
        context={"scene": "interior"},
        census_text=census, probe_text=probe, depth_text=depth,
    )
    joined = "\n".join(c.get("text", "") for c in content if c["type"] == "text")
    assert "SCENE CENSUS" in joined
    assert 'put its exact node name in the move as "node"' in joined
    assert "MEASURED SCENE RESPONSE (calibration probe)" in joined
    assert "MEASURED DEPTH STRUCTURE" in joined
    # absent blocks simply don't appear
    content2 = engine.build_user_content("recipe", [], {"diff": {}})
    j2 = "\n".join(c.get("text", "") for c in content2 if c["type"] == "text")
    assert "SCENE CENSUS" not in j2 and "calibration probe" not in j2
