"""The analyze / refine engine — evidence assembly, gateway round, validation, and
session bookkeeping. Ports the web engine's contracts:
  - LEAN evidence: the diff (reference − current) + measured WB/exposure + scene
    projections, never the full metric objects (omega's ~100s ceiling);
  - the SPATIAL ASYMMETRY scalars pre-chewed from the diff grid (sign convention:
    positive leftMinusRight ⇒ reference brighter on the LEFT ⇒ move the key left);
  - CURRENT SCENE SETTINGS from the live pymxs pull (always ground truth in-Max);
  - validation: pack-unknown params dropped, numerics clamped+flagged, Area-mode
    globals withheld after the fact (prompt directive + enforcement belt);
  - refine history with the oscillation-guard framing, attempts capped at 8."""

from __future__ import annotations

import json
import math
from typing import Any, Optional

from . import data
from .metrics import (
    MATCH_THRESHOLD,
    diff_vectors,
    js_round,
    match_percent,
    scene_evidence,
    score_vectors,
    wb_exposure_evidence,
)
from .omega import call, image_block, parse_json_from_text, text_block
from .scope import withhold_globals

ATTEMPTS_CAP = 8


# -- JS-parity JSON: every finite float rounded to 4dp, compact separators ------------
def _round4(v: Any) -> Any:
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return js_round(v, 4) if math.isfinite(v) else v
    if isinstance(v, dict):
        return {k: _round4(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_round4(x) for x in v]
    return v


def dumps_r4(obj: Any) -> str:
    return json.dumps(_round4(obj), separators=(",", ":"))


# -- SPATIAL ASYMMETRY scalars (port of client-adapter's block; same sign prose) -------
def asymmetry_line(diff: dict[str, float]) -> str:
    cells = []
    for i in range(16):
        v = diff.get(f"grid.{i}")
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            return ""
        cells.append(float(v))
    at = lambda r, c: cells[r * 4 + c]  # noqa: E731
    left = sum(at(r, 0) + at(r, 1) for r in range(4))
    right = sum(at(r, 2) + at(r, 3) for r in range(4))
    top = sum(at(0, c) + at(1, c) for c in range(4))
    bottom = sum(at(2, c) + at(3, c) for c in range(4))
    lmr = js_round(left / 8 - right / 8, 4)
    tmb = js_round(top / 8 - bottom / 8, 4)
    return (
        f"\nSPATIAL ASYMMETRY (reference − current): leftMinusRight={lmr}, "
        f"topMinusBottom={tmb} — a positive leftMinusRight means the REFERENCE is brighter on "
        f"the LEFT than the current render; move the key toward the LEFT (or rotate the HDRI so the key comes "
        f"from the left). Positive topMinusBottom means the reference is brighter up top; RAISE the sun "
        f"elevation. Negative values mean the opposite side/direction."
    )


# -- user-content assembly --------------------------------------------------------------
def build_user_content(
    mode: str,
    images: list[dict],  # {label, b64, media_type}
    bundle: dict,
    context: Optional[dict[str, str]] = None,
    live_params: Optional[dict[str, Any]] = None,
    renderer: str = "",
    history: Optional[list[dict]] = None,
) -> list[dict]:
    content: list[dict] = []
    for img in images:
        content.append(text_block(img["label"]))
        content.append(image_block(img["b64"], img.get("media_type", "image/png")))

    content.append(text_block(f"{data.evidence_legend()}\n{dumps_r4(bundle)}{asymmetry_line(bundle.get('diff', {}))}"))

    if context:
        chips = ", ".join(f"{k}: {v}" for k, v in context.items() if v)
        if chips:
            content.append(text_block(f"SCENE CONTEXT — {chips}"))

    if live_params:
        rows = "\n".join(f"  {k} = {str(v)[:120]}" for k, v in list(live_params.items())[:64])
        content.append(text_block(
            f"CURRENT SCENE SETTINGS — read LIVE from 3ds Max (renderer: {renderer or 'unknown'}, pulled just now). "
            f"These are the scene's ACTUAL current values; use them as the exact `from` value for every listed "
            f'control and declare baseline:"settings_screenshot" (the live read supersedes factory defaults; '
            f"controls NOT listed keep the pack default assumption):\n{rows}"
        ))

    if mode == "correction" and history:
        lines = ["MOVE HISTORY (prior rounds — do not reverse any move here by more than half; applied=false means the user skipped that row when re-rendering):"]
        for rnd in history:
            for mv in rnd.get("moves", []):
                lines.append(
                    f"  round {rnd['round']}: {mv['param']} {mv['from']} -> {mv['to']} (applied: {str(mv.get('applied', True)).lower()}) — {mv.get('why', '')}".rstrip()
                )
        content.append(text_block("\n".join(lines)))
    return content


# -- validation (essential port of validateRecipe) ---------------------------------------
def validate_items(target: str, cleaned: dict, mode: str) -> dict:
    key = "moves" if mode == "correction" else "values"
    val_key = "to" if mode == "correction" else "set"
    items = cleaned.get(key)
    if not isinstance(items, list):
        raise ValueError(f"model reply is missing an array `{key}`")
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        param = it.get("param")
        if not isinstance(param, str) or data.lookup(target, param) is None:
            continue  # unknown control — never let an invented knob through
        if param in seen:
            continue  # one value per control; first occurrence wins
        seen.add(param)
        v = it.get(val_key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if not math.isfinite(float(v)):
                continue  # NaN/Inf move is meaningless — clamp can't fix it; drop the row
            clamped_v, flagged = data.clamp(target, param, float(v))
            it = dict(it)
            it[val_key] = clamped_v
            if flagged:
                it["clamped"] = True
        out.append(it)
    result = dict(cleaned)
    result[key] = out
    return result


# -- the two rounds -----------------------------------------------------------------------
def analyze(
    key: str,
    model: str,
    target: str,
    ref: dict,     # {metrics, b64, media_type}
    base: dict,
    context: Optional[dict[str, str]] = None,
    lock_globals: bool = False,
    live_params: Optional[dict[str, Any]] = None,
    renderer: str = "",
) -> dict:
    bundle: dict[str, Any] = {"diff": diff_vectors(base["metrics"], ref["metrics"])}
    bundle.update(wb_exposure_evidence(ref["metrics"], base["metrics"]))
    bundle.update(scene_evidence(ref["metrics"], base["metrics"]))
    content = build_user_content(
        "recipe",
        [
            {"label": "REFERENCE:", "b64": ref["b64"], "media_type": ref.get("media_type", "image/png")},
            {"label": "BASE RENDER:", "b64": base["b64"], "media_type": base.get("media_type", "image/png")},
        ],
        bundle, context, live_params, renderer,
    )
    system = data.system_prompt(target, "recipe", lock_globals)
    text = call(key, system, [{"role": "user", "content": content}], model=model)
    obj = parse_json_from_text(text)
    if not obj or not isinstance(obj.get("values"), list):
        raise ValueError("the model's reply carried no recipe JSON — try Analyze again")
    recipe = validate_items(target, obj, "recipe")
    if lock_globals:
        recipe = withhold_globals(recipe, "values")
    return recipe


def add_attempt(
    key: str,
    model: str,
    target: str,
    ref: dict,
    attempt: dict,
    attempt_n: int,
    history: list[dict],
    context: Optional[dict[str, str]] = None,
    lock_globals: bool = False,
    live_params: Optional[dict[str, Any]] = None,
    renderer: str = "",
) -> tuple[float, dict]:
    score = score_vectors(ref["metrics"], attempt["metrics"])
    bundle: dict[str, Any] = {"diff": diff_vectors(attempt["metrics"], ref["metrics"])}
    bundle.update(wb_exposure_evidence(ref["metrics"], attempt["metrics"]))
    bundle.update(scene_evidence(ref["metrics"], attempt["metrics"]))
    content = build_user_content(
        "correction",
        [
            {"label": "REFERENCE:", "b64": ref["b64"], "media_type": ref.get("media_type", "image/png")},
            {"label": f"ATTEMPT {attempt_n}:", "b64": attempt["b64"], "media_type": attempt.get("media_type", "image/png")},
        ],
        bundle, context, live_params, renderer, history=history,
    )
    system = data.system_prompt(target, "correction", lock_globals)
    text = call(key, system, [{"role": "user", "content": content}], model=model)
    obj = parse_json_from_text(text)
    if not obj or not isinstance(obj.get("moves"), list):
        raise ValueError("the model's reply carried no correction JSON — drop the attempt again")
    correction = validate_items(target, obj, "correction")
    if lock_globals:
        correction = withhold_globals(correction, "moves")
    return score, correction


def matched(score: float) -> bool:
    return score <= MATCH_THRESHOLD


__all__ = [
    "ATTEMPTS_CAP", "MATCH_THRESHOLD", "analyze", "add_attempt", "matched",
    "match_percent", "build_user_content", "validate_items", "dumps_r4", "asymmetry_line",
]
