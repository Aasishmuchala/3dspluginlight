"""pymxs scene adapters — pull the live V-Ray values / apply a recipe DIRECTLY, with
real undo. This replaces the web app's localhost bridge entirely: no listener, no
MAXScript string interpolation (values are set through pymxs attributes, so there is
no injection surface at all).

The property map comes from data/knownprops.json — the exact set the web app's
export/apply verified against real Max (never touch a property the map doesn't
vouch for). Only importable inside 3ds Max (pymxs); everything degrades to a clean
LightMatchMaxError elsewhere."""

from __future__ import annotations

import fnmatch
import math
from typing import Any, Optional

from ..core.data import knownprops


class LightMatchMaxError(RuntimeError):
    pass


def _rt():
    try:
        from pymxs import runtime as rt  # type: ignore
        return rt
    except Exception as e:  # pragma: no cover - only outside Max
        raise LightMatchMaxError("pymxs is not available — run this inside 3ds Max.") from e


# cm.type int → pack option string. Superset on the PULL side (deprecated gamma
# options are real scene states); apply still emits only the pack's legal five.
CM_TYPE_BY_INDEX = {
    0: "Linear multiply", 1: "Exponential", 2: "HSV exponential",
    3: "Intensity exponential", 4: "Gamma correction", 5: "Intensity gamma", 6: "Reinhard",
}


def _first_instance(rt, class_name: str):
    cls = getattr(rt, class_name, None)
    if cls is None:
        return None
    try:
        arr = rt.getClassInstances(cls)
        return arr[0] if len(arr) > 0 else None
    except Exception:
        return None


def _vray_light_of_type(rt, type_int: int):
    cls = getattr(rt, "VRayLight", None)
    if cls is None:
        return None
    try:
        for o in rt.getClassInstances(cls):
            try:
                if int(o.type) == type_int:
                    return o
            except Exception:
                continue
    except Exception:
        return None
    return None


def _node_for(rt, node: str, create: bool = False):
    if node == "renderer":
        return rt.renderers.current
    if node == "sun":
        found = _first_instance(rt, "VRaySun")
        if found is None and create:
            found = rt.VRaySun()
        return found
    if node == "light":
        found = _first_instance(rt, "VRayLight")
        if found is None and create:
            found = rt.VRayLight()
        return found
    if node == "plane":
        found = _vray_light_of_type(rt, 0)
        if found is None and create:
            found = rt.VRayLight()
            try:
                found.type = 0
            except Exception:
                pass
        return found
    if node == "dome":
        found = _vray_light_of_type(rt, 1)
        if found is None and create:
            found = rt.VRayLight()
            try:
                found.type = 1
            except Exception:
                pass
        return found
    if node == "cam":
        found = _first_instance(rt, "VRayPhysicalCamera")
        if found is None and create:
            found = rt.VRayPhysicalCamera()
        return found
    return None


def renderer_name() -> str:
    rt = _rt()
    try:
        return str(rt.classOf(rt.renderers.current))
    except Exception:
        return "unknown"


def is_vray() -> bool:
    return "v_ray" in renderer_name().lower().replace("-", "_")


def _discover_renderer_prop(rt, prop: str) -> Optional[str]:
    """GPU/CPU-aware property discovery (mirrors the web export/apply): enumerate the
    ACTUAL renderer's properties and match by shape — colorMapping_type on CPU, or
    whatever a given engine exposes; never isProperty (it ACCESSES the property)."""
    pattern = prop.replace("_", "*").lower()
    try:
        for p in rt.getPropNames(rt.renderers.current):
            if fnmatch.fnmatch(str(p).lower(), pattern):
                return str(p)
    except Exception:
        return None
    return None


def pull_settings(camera_name: Optional[str] = None) -> dict[str, Any]:
    """Read every KNOWN_PROPS value the scene can provide → the CURRENT SCENE
    SETTINGS block (ground truth `from` values). Per-property try/except: one odd
    node never sinks the pull.

    `camera_name` (optional): read cam.* (ISO / f-number / shutter) from the PICKED
    physical camera by name instead of the renderer's first-of-kind — so a scene with
    2+ VRayPhysicalCameras captures the exposure of the camera the user actually
    selected, and Save look (pull) / Restore look (apply, which stamps the same
    camera's node via scope.stamp_camera_node) reference the SAME camera. When it is
    falsy, cam.* falls back to first-of-kind — the historical behavior, so every
    existing call is unaffected. When it is given but the named camera can't be
    resolved (renamed/deleted, or not a physical camera), cam.* lands in `missing`
    rather than silently reading the wrong camera — mirroring apply_values' honest
    named-node failure."""
    rt = _rt()
    props: dict[str, dict] = knownprops()["known_props"]
    params: dict[str, Any] = {}
    missing: list[str] = []
    nodes_cache: dict[str, Any] = {}
    for param, m in props.items():
        node_key = m["node"]
        if node_key not in nodes_cache:
            if node_key == "cam" and camera_name:
                nodes_cache[node_key] = _node_by_name(rt, camera_name)
            else:
                nodes_cache[node_key] = _node_for(rt, node_key, create=False)
        node = nodes_cache[node_key]
        if node is None:
            missing.append(param)
            continue
        try:
            if node_key == "renderer":
                found = _discover_renderer_prop(rt, m["prop"])
                if not found:
                    missing.append(param)
                    continue
                raw = rt.getProperty(node, rt.Name(found))
            else:
                raw = getattr(node, m["prop"])
        except Exception:
            missing.append(param)
            continue
        if m["type"] == "enum":
            try:
                label = CM_TYPE_BY_INDEX.get(int(raw))
            except Exception:
                label = None
            if label is None:
                missing.append(param)
                continue
            params[param] = label
        elif m["type"] == "bool":
            params[param] = bool(raw)
        else:
            try:
                params[param] = float(raw)
            except Exception:
                missing.append(param)
    counts = {
        "suns": _count(rt, "VRaySun"),
        "vrayLights": _count(rt, "VRayLight"),
        "physCams": _count(rt, "VRayPhysicalCamera"),
    }
    return {"renderer": renderer_name(), "vray": is_vray(), "params": params, "missing": missing, "counts": counts}


def _count(rt, class_name: str) -> int:
    cls = getattr(rt, class_name, None)
    if cls is None:
        return 0
    try:
        return int(len(rt.getClassInstances(cls)))
    except Exception:
        return 0


def apply_values(values: list[dict]) -> dict[str, list[str]]:
    """Apply recipe/correction rows ({param, set}) directly, inside ONE undo record —
    Ctrl+Z reverts the whole recipe.

    Each value may carry an explicit `node` (an exact scene node name) to target a
    SPECIFIC fixture — "move VRayLight_Kitchen_Fill", not "the first light of its kind"
    — the scene-census/per-area story. Without `node`, the KNOWN_PROPS kind resolves to
    the first-of-kind node (created if absent).

    Every set is READ BACK and confirmed to have actually landed, so a silent no-op (the
    camera-exposure-toggle class of bug) becomes a visible `unverified` entry instead of
    a quiet lie. Returns {applied, failed, manual, verified, unverified}: `manual` = no
    scriptable path; `applied` = the set didn't throw; `verified` ⊆ applied = read back
    to the target value; `unverified` ⊆ applied = set succeeded but the read-back
    disagreed (something is overriding it — surface it to the user)."""
    rt = _rt()
    props: dict[str, dict] = knownprops()["known_props"]
    applied: list[str] = []
    failed: list[str] = []
    manual: list[str] = []
    verified: list[str] = []
    unverified: list[str] = []
    import pymxs  # type: ignore

    with pymxs.undo(True, "LightMatch apply"):
        for v in values:
            param = v.get("param")
            m = props.get(param) if isinstance(param, str) else None
            if m is None:
                manual.append(str(param))
                continue
            raw = v.get("set")
            node_name = v.get("node") if isinstance(v.get("node"), str) and v.get("node") else None
            try:
                if m["type"] == "bool":
                    # validate_items floats a bool control's `set` (1 -> 1.0, "1" -> 1.0),
                    # so accept a numeric raw as a truth value; string forms still parse.
                    # Without this, 1.0 -> str "1.0" -> not in the tuple -> False, silently
                    # INVERTING an intended ON and disabling the light/sun (2026-07-15 audit).
                    if isinstance(raw, bool):
                        val: Any = raw
                    elif isinstance(raw, (int, float)):
                        val = float(raw) != 0.0
                    else:
                        val = str(raw).strip().lower() in ("1", "true", "on", "yes")
                elif m["type"] == "float":
                    val = float(raw)  # non-numeric raises → failed
                    # float() ACCEPTS "inf"/"1e999"/"nan" → non-finite floats. The
                    # reachable string-set path is already gated upstream (engine
                    # validate_items, commit fd3bbed), but this is the write-boundary
                    # backstop: any caller that bypasses validation still can't
                    # setattr a non-finite value onto a live V-Ray node.
                    if not math.isfinite(val):
                        failed.append(param)
                        continue
                else:  # enum — only a known option string maps to its int
                    options = {k.lower(): int(x) for k, x in m.get("options", {}).items()}
                    key = str(raw).strip().lower()
                    if key not in options:
                        failed.append(param)
                        continue
                    val = options[key]

                if m["node"] == "renderer":
                    found = _discover_renderer_prop(rt, m["prop"])
                    if not found:
                        failed.append(param)
                        continue
                    rt.setProperty(rt.renderers.current, rt.Name(found), val)
                    applied.append(param)
                    read = _read_renderer_prop(rt, found)
                else:
                    # named node overrides first-of-kind. NEVER create a missing fixture: a
                    # lighting-MATCH tool tunes fixtures that EXIST. A hallucinated
                    # sun.*/dome.*/plane.* move for an absent node must fail honestly, not
                    # spawn a stray light that pollutes the scene and stalls convergence
                    # (2026-07-15 audit — the dominant real-world non-convergence cause).
                    node = _node_by_name(rt, node_name) if node_name else _node_for(rt, m["node"], create=False)
                    if node is None:
                        failed.append(param)
                        continue
                    setattr(node, m["prop"], val)  # if this throws → failed, no side-writes
                    # ISO/f-number/shutter no-op unless Exposure is ON (B4 blocker) — but
                    # flip it only AFTER the set succeeds, so a FAILED cam row never
                    # silently leaves Exposure toggled (found 2026-07-13).
                    if m["node"] == "cam":
                        try:
                            node.exposure = True
                        except Exception:
                            pass
                    applied.append(param)
                    read = _read_node_prop(node, m["prop"])

                if _values_match(read, val, m["type"]):
                    verified.append(param)
                else:
                    unverified.append(param)
            except Exception:
                failed.append(param)
    return {
        "applied": applied, "failed": failed, "manual": manual,
        "verified": verified, "unverified": unverified,
    }


def _node_by_name(rt, name: str):
    try:
        return rt.getNodeByName(name, exact=True)
    except Exception:
        try:
            return rt.getNodeByName(name)
        except Exception:
            return None


def _read_node_prop(node, prop: str):
    try:
        return getattr(node, prop)
    except Exception:
        return _READ_FAIL


def _read_renderer_prop(rt, found: str):
    try:
        return rt.getProperty(rt.renderers.current, rt.Name(found))
    except Exception:
        return _READ_FAIL


class _ReadFail:
    pass


_READ_FAIL = _ReadFail()


def _values_match(read, expected, kind: str) -> bool:
    """Did the read-back land on the value we set? Tolerant on floats; the sentinel
    _READ_FAIL (couldn't read) counts as unverified, never as a match."""
    if read is _READ_FAIL:
        return False
    try:
        if kind == "float":
            return abs(float(read) - float(expected)) <= max(1e-4, abs(float(expected)) * 1e-4)
        if kind == "bool":
            return bool(read) == bool(expected)
        return int(read) == int(expected)  # enum
    except Exception:
        return False


# ---------------------------------------------------------------------------------
# SCENE CENSUS — the "understand the project" collector. Reads the whole lighting
# inventory BY NAME plus the silent value-wreckers (exposure control, gamma, color
# mapping) into the dict shape core.census_format consumes. Every read is guarded:
# one odd node must never sink the census.
# ---------------------------------------------------------------------------------
_VRAY_LIGHT_TYPE = {0: "plane", 1: "dome", 2: "sphere", 3: "mesh", 4: "disc"}


def _try(getter, default=None):
    try:
        return getter()
    except Exception:
        return default


def _str(v) -> Optional[str]:
    try:
        s = str(v)
        return s if s and s.lower() != "undefined" else None
    except Exception:
        return None


def _texmap_file(rt, node) -> Optional[str]:
    tex = _try(lambda: node.texmap)
    if tex is None:
        return None
    # Bitmaptexture → .filename; VRayHDRI → .HDRIMapName
    return _str(_try(lambda: tex.filename)) or _str(_try(lambda: tex.HDRIMapName))


def collect_census() -> dict:
    """Full live inventory for core.census_format (warnings + ground-truth prompt block)."""
    rt = _rt()
    renderer = renderer_name()
    census: dict[str, Any] = {
        "renderer": renderer,
        "is_vray": is_vray(),
        "cameras": [],
        "lights": [],
        "suns": [],
        "environment_map": None,
        "exposure_control": {"class": None, "active": None},
        "gamma": None,
        "color_mapping": {"type": None},
        "counts": {},
    }

    # cameras (physical cameras carry the exposure toggle that eats ISO/f/shutter moves)
    for cam in _try(lambda: list(rt.cameras), []) or []:
        cls = _str(_try(lambda: rt.classOf(cam)))
        census["cameras"].append({
            "name": _str(_try(lambda: cam.name)) or "?",
            "class": cls,
            "exposure_on": _try(lambda: bool(cam.exposure)) if cls == "VRayPhysicalCamera" else None,
        })

    # lights — split VRaySun out of the light collection
    for lt in _try(lambda: list(rt.lights), []) or []:
        cls = _str(_try(lambda: rt.classOf(lt))) or "?"
        name = _str(_try(lambda: lt.name)) or "?"
        if "vraysun" in cls.lower():
            census["suns"].append({
                "name": name,
                "on": _try(lambda: bool(lt.enabled)),
                "intensity_mult": _try(lambda: float(lt.intensity_multiplier)),
            })
        else:
            vt = _try(lambda: int(lt.type))
            census["lights"].append({
                "name": name,
                "class": cls,
                "vray_type": _VRAY_LIGHT_TYPE.get(vt) if vt is not None and "vraylight" in cls.lower() else None,
                "on": _try(lambda: bool(lt.on)),
                "multiplier": _try(lambda: float(lt.multiplier)),
                "texmap_file": _texmap_file(rt, lt),
            })

    # environment map (HDRI dome via world environment)
    env = _try(lambda: rt.environmentMap)
    if env is not None:
        census["environment_map"] = _str(_try(lambda: env.filename)) or _str(_try(lambda: env.HDRIMapName))

    # exposure control — the classic silent EV-eater
    ec = _try(lambda: rt.SceneExposureControl.exposureControl)
    if ec is not None:
        ec_cls = _str(_try(lambda: rt.classOf(ec)))
        census["exposure_control"] = {
            "class": ec_cls,
            # "active" when there IS a real exposure control that isn't the explicit none
            "active": bool(ec_cls) and ec_cls not in ("undefined", "NoExposureControl"),
        }

    # gamma: displayGamma when correction is enabled, else effectively 1.0 (linear)
    if _try(lambda: bool(rt.gammaCorrectionEnabled)):
        census["gamma"] = _try(lambda: float(rt.displayGamma))
    else:
        census["gamma"] = 1.0

    # color mapping type (engine-discovered property)
    if census["is_vray"]:
        found = _discover_renderer_prop(rt, "colorMapping_type")
        if found:
            idx = _try(lambda: int(rt.getProperty(rt.renderers.current, rt.Name(found))))
            if idx is not None:
                census["color_mapping"]["type"] = CM_TYPE_BY_INDEX.get(idx)

    census["counts"] = {
        "suns": len(census["suns"]),
        "lights": len(census["lights"]),
        "cameras": len(census["cameras"]),
    }
    return census


# ---------------------------------------------------------------------------------
# CAMERA SCOPE (Stage 1) — the picker's source + the "render THIS camera" plumbing.
# list_cameras mirrors collect_census's camera block; set_active_camera points the
# viewport so a render captures the picked camera's view (and lets B1 stamp the
# exact node name onto cam.* moves).
# ---------------------------------------------------------------------------------
def list_cameras() -> list[dict]:
    """[{"name", "class", "exposure_on"}] for every camera node in the scene — the
    picker's source. exposure_on is bool ONLY for VRayPhysicalCamera, else None. Fully
    guarded (per-node try/except); returns [] on any failure."""
    try:
        rt = _rt()
    except Exception:
        return []
    out: list[dict] = []
    for cam in _try(lambda: list(rt.cameras), []) or []:
        try:
            cls = _str(_try(lambda: rt.classOf(cam)))
            out.append({
                "name": _str(_try(lambda: cam.name)) or "?",
                "class": cls,
                "exposure_on": _try(lambda: bool(cam.exposure)) if cls == "VRayPhysicalCamera" else None,
            })
        except Exception:
            continue
    return out


def set_active_camera(name: str) -> bool:
    """Point the active viewport at the named camera node so a render captures ITS view.
    Returns True on success, False if the camera is not found or the viewport call fails.
    Raises LightMatchMaxError only when pymxs is unavailable (via _rt())."""
    rt = _rt()
    node = _node_by_name(rt, name)
    if node is None:
        return False
    try:
        rt.viewport.setCamera(node)
        return True
    except Exception:
        return False
