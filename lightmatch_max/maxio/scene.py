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


def pull_settings() -> dict[str, Any]:
    """Read every KNOWN_PROPS value the scene can provide → the CURRENT SCENE
    SETTINGS block (ground truth `from` values). Per-property try/except: one odd
    node never sinks the pull."""
    rt = _rt()
    props: dict[str, dict] = knownprops()["known_props"]
    params: dict[str, Any] = {}
    missing: list[str] = []
    nodes_cache: dict[str, Any] = {}
    for param, m in props.items():
        node_key = m["node"]
        if node_key not in nodes_cache:
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
    Ctrl+Z reverts the whole recipe. Returns {applied, failed, manual}: `manual` are
    controls the verified map has no scriptable path for (VFB layers, placements…)."""
    rt = _rt()
    props: dict[str, dict] = knownprops()["known_props"]
    applied: list[str] = []
    failed: list[str] = []
    manual: list[str] = []
    import pymxs  # type: ignore

    with pymxs.undo(True, "LightMatch apply"):
        for v in values:
            param = v.get("param")
            m = props.get(param) if isinstance(param, str) else None
            if m is None:
                manual.append(str(param))
                continue
            raw = v.get("set")
            try:
                if m["type"] == "bool":
                    val: Any = bool(raw) if isinstance(raw, bool) else str(raw).strip().lower() in ("1", "true", "on", "yes")
                elif m["type"] == "float":
                    val = float(raw)  # non-numeric raises → failed
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
                else:
                    node = _node_for(rt, m["node"], create=True)
                    if node is None:
                        failed.append(param)
                        continue
                    # ISO/f-number/shutter silently no-op unless the camera's exposure
                    # toggle is ON (the B4 audit blocker) — enable it, guarded.
                    if m["node"] == "cam":
                        try:
                            node.exposure = True
                        except Exception:
                            pass
                    setattr(node, m["prop"], val)
                applied.append(param)
            except Exception:
                failed.append(param)
    return {"applied": applied, "failed": failed, "manual": manual}
