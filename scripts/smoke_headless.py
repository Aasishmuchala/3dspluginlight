"""Headless core smoke — runs ANYWHERE (plain python or 3dsmaxbatch): proves the
data artifacts load, the measurement core computes, prompts assemble, and the
Area-mode belt filters. Prints SMOKE_OK on success (the MaxOptimizer pattern).

    python scripts/smoke_headless.py
    3dsmaxbatch scripts/smoke_headless.py   (validates the same core under Max's Python)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from lightmatch_max.core import data, engine  # noqa: E402
from lightmatch_max.core.metrics import (  # noqa: E402
    match_percent,
    measure_from_pixels,
    score_vectors,
)
from lightmatch_max.core.scope import withhold_globals  # noqa: E402

def main() -> int:
    # data artifacts
    assert data.target_label("vray7max").startswith("V-Ray")
    assert "AREA MODE" in data.system_prompt("vray7max", "recipe", True)
    assert "COMPUTED EVIDENCE" in data.evidence_legend()

    # measurement on a synthetic gradient
    w, h = 96, 64
    x = np.linspace(0, 255, w, dtype=np.float64)
    img = np.zeros((h, w, 4), dtype=np.uint8)
    img[..., 0] = np.tile(x, (h, 1)).astype(np.uint8)
    img[..., 1] = 120
    img[..., 2] = 80
    img[..., 3] = 255
    m = measure_from_pixels(img, w, h)
    assert 0 < m["lum"]["p50"] < 1 and len(m["grid"]) == 16
    assert score_vectors(m, m) == 0 and match_percent(0) == 100

    # area-mode belt
    out = withhold_globals({"values": [{"param": "sun.turbidity", "set": 2.5}, {"param": "cam.iso", "set": 200}]}, "values")
    assert [v["param"] for v in out["values"]] == ["cam.iso"]

    # user-content assembly
    content = engine.build_user_content("recipe", [], {"diff": {}}, context={"scene": "interior"})
    assert any("COMPUTED EVIDENCE" in c.get("text", "") for c in content)

    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
