"""Scene census — the "understand the project" brain. Turns a live scene inventory
(collected by the pymxs layer) into two things:

  1. PRE-FLIGHT WARNINGS for the silent value-wreckers — the scene states that make a
     perfectly correct recipe value do nothing (or the wrong thing): auto/environment
     exposure control overriding the camera, the camera exposure toggle off, a gamma
     setup that isn't 2.2, multiple suns, no lights. Most "the tool gave wrong values"
     experiences in this class are actually right values applied into a scene that eats
     them; these warnings catch that before the render.
  2. The GROUND-TRUTH prompt block — every light/sun/camera BY NAME, the HDRI path, the
     color-mapping mode — so the model reasons about the real project, and can address a
     specific fixture by node name instead of "the first light of its kind".

PURE: census dict in, warnings + text out. No pymxs. Every field is optional because
the collector is best-effort (one odd node must never sink the census).
"""

from __future__ import annotations

import os
from typing import Any, Optional

LIGHT_ROW_CAP = 24


def _basename(path: Optional[str]) -> Optional[str]:
    if not isinstance(path, str) or not path:
        return None
    # handle both windows and posix separators regardless of host
    return os.path.basename(path.replace("\\", "/"))


def census_warnings(census: dict) -> list[dict]:
    """Pre-flight checks. Each: {code, severity ('block'|'warn'), message}. Blocks first."""
    c = census or {}
    warns: list[dict] = []

    if not c.get("is_vray"):
        warns.append({
            "code": "NOT_VRAY", "severity": "block",
            "message": f"Active renderer is {c.get('renderer', 'unknown')}; LightMatch drives V-Ray. Switch the renderer to V-Ray.",
        })

    suns = c.get("suns") or []
    lights = c.get("lights") or []
    lights_on = [l for l in lights if l.get("on") is not False]
    suns_on = [s for s in suns if s.get("on") is not False]
    if not suns and not lights_on:
        warns.append({
            "code": "NO_SUN_NO_LIGHTS", "severity": "warn",
            "message": "No sun and no lights are on — there is nothing for the recipe to move. Add a light or a VRaySun.",
        })
    if len(suns) > 1:
        names = ", ".join(str(s.get("name", "?")) for s in suns[:4])
        warns.append({
            "code": "MULTIPLE_SUNS", "severity": "warn",
            "message": f"{len(suns)} suns in the scene ({names}). Recipes address ONE sun; a sun move targets the first — name the one you mean.",
        })

    for cam in c.get("cameras") or []:
        if cam.get("class") == "VRayPhysicalCamera" and cam.get("exposure_on") is False:
            warns.append({
                "code": "CAMERA_EXPOSURE_OFF", "severity": "warn",
                "message": f'Camera "{cam.get("name", "?")}" has Exposure OFF — ISO / f-number / shutter moves will silently no-op until you enable Exposure on the physical camera.',
            })

    ec = c.get("exposure_control") or {}
    if ec.get("active") and ec.get("class") and "vray" not in str(ec.get("class")).lower():
        warns.append({
            "code": "ENV_EXPOSURE_CONTROL", "severity": "warn",
            "message": f"Environment Exposure Control ({ec.get('class')}) is active and overriding camera exposure — every EV move will be re-tonemapped by it. Disable it (Rendering ▸ Environment ▸ Exposure Control ▸ no exposure control) or set it to the V-Ray control.",
        })

    gamma = c.get("gamma")
    if isinstance(gamma, (int, float)) and not isinstance(gamma, bool) and abs(gamma - 2.2) > 0.05:
        warns.append({
            "code": "GAMMA_OFF", "severity": "warn",
            "message": f"Gamma/LUT is set to {gamma}, not 2.2 — WB and exposure math assume a 2.2 display. Set Customize ▸ Preferences ▸ Gamma to 2.2.",
        })

    if not (c.get("cameras") or []):
        warns.append({
            "code": "NO_CAMERA", "severity": "warn",
            "message": "No camera in the scene — you are rendering the free viewport, so per-shot exposure moves have nowhere to land. Create a physical camera for repeatable exposure.",
        })

    warns.sort(key=lambda w: 0 if w["severity"] == "block" else 1)
    return warns


NODE_INSTRUCTION = (
    'To move a SPECIFIC light, put its exact node name in the move as "node" '
    '(e.g. {"param":"light.multiplier","node":"VRayLight_Kitchen_Fill",...}) — moves '
    'without "node" target the first light of that kind.'
)


def census_block(census: dict) -> str:
    """Ground-truth inventory prompt block: renderer + color mapping, lights BY NAME,
    suns, cameras (+exposure), environment map, gamma, then the node-targeting rule."""
    c = census or {}
    lines: list[str] = ["SCENE CENSUS — ground-truth inventory read live from 3ds Max:"]
    cm = (c.get("color_mapping") or {}).get("type")
    lines.append(f"- renderer: {c.get('renderer', 'unknown')}; color mapping: {cm or 'unknown'}")
    if isinstance(c.get("gamma"), (int, float)):
        lines.append(f"- gamma: {c['gamma']}")
    env = _basename(c.get("environment_map"))
    if env:
        lines.append(f"- environment map: {env}")

    suns = c.get("suns") or []
    if suns:
        lines.append("- suns:")
        for s in suns:
            on = "on" if s.get("on") is not False else "OFF"
            mult = s.get("intensity_mult")
            lines.append(f"    {s.get('name', '?')} · {on}" + (f" · intensity {mult}" if mult is not None else ""))

    lights = c.get("lights") or []
    if lights:
        lines.append(f"- lights ({len(lights)}):")
        for l in lights[:LIGHT_ROW_CAP]:
            parts = [str(l.get("name", "?"))]
            kind = l.get("vray_type") or l.get("class")
            if kind:
                parts.append(str(kind))
            parts.append("on" if l.get("on") is not False else "OFF")
            if l.get("multiplier") is not None:
                parts.append(f"mult {l['multiplier']}")
            tex = _basename(l.get("texmap_file"))
            if tex:
                parts.append(f"tex {tex}")
            lines.append("    " + " · ".join(parts))
        if len(lights) > LIGHT_ROW_CAP:
            lines.append(f"    … and {len(lights) - LIGHT_ROW_CAP} more")

    cams = c.get("cameras") or []
    if cams:
        lines.append("- cameras:")
        for cam in cams:
            exp = cam.get("exposure_on")
            exp_s = "" if exp is None else (" · exposure on" if exp else " · EXPOSURE OFF")
            lines.append(f"    {cam.get('name', '?')} · {cam.get('class', '?')}{exp_s}")

    lines.append(NODE_INSTRUCTION)
    return "\n".join(lines)


def summarize_for_ui(census: dict, warnings: list[dict]) -> str:
    """One short status line for the dock."""
    c = census or {}
    nl = len(c.get("lights") or [])
    ns = len(c.get("suns") or [])
    nc = len(c.get("cameras") or [])
    nw = len(warnings or [])
    bits = [f"{nl} light{'s' if nl != 1 else ''}"]
    if ns:
        bits.append(f"{ns} sun{'s' if ns != 1 else ''}")
    bits.append(f"{nc} cam{'s' if nc != 1 else ''}")
    if nw:
        blocks = sum(1 for w in warnings if w.get("severity") == "block")
        bits.append(f"{nw} warning{'s' if nw != 1 else ''}" + (" (BLOCK)" if blocks else ""))
    return " · ".join(bits)
