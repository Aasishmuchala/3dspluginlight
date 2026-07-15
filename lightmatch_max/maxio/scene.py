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
    if node == "amb":
        return _first_instance(rt, "VRayAmbientLight")
    return None


_COLOR_NAMES = {
    "white": (255, 255, 255), "neutral": (255, 255, 255), "warm white": (255, 236, 210),
    "cool white": (230, 240, 255), "grey": (128, 128, 128), "gray": (128, 128, 128),
    "warm grey": (120, 110, 95), "warm gray": (120, 110, 95), "amber": (255, 176, 90),
    "warm amber": (255, 194, 122), "pale warm amber": (255, 224, 184), "golden": (255, 200, 110),
    "gold": (255, 200, 110), "orange": (255, 160, 60), "warm tan": (214, 184, 140),
    "tan": (210, 190, 150), "cool blue": (150, 180, 235), "sky blue": (150, 190, 240),
    "blue": (120, 150, 235), "warm": (255, 214, 170), "cool": (190, 210, 245),
}


def _parse_color(raw):
    """Best-effort colour description -> (r,g,b) 0..255. Handles 'RGB(r,g,b)' / '(r,g,b)' /
    'r,g,b', '#rrggbb', and the warm/cool NAMES the model emits ('warm amber', 'warm grey
    ~RGB(80,70,55)'). Longest name wins so 'warm amber' beats 'amber'/'warm'. None if
    nothing parseable is found (row then fails honestly, writes nothing)."""
    import re
    # a live Max color object (from pull_settings snapshots) — round-trips keep-best restore
    if hasattr(raw, "r") and hasattr(raw, "g") and hasattr(raw, "b"):
        try:
            return tuple(max(0, min(255, int(round(float(getattr(raw, c)))))) for c in ("r", "g", "b"))
        except Exception:
            return None
    if isinstance(raw, (list, tuple)) and len(raw) >= 3:
        try:
            return tuple(max(0, min(255, int(raw[i]))) for i in range(3))
        except Exception:
            return None
    s = str(raw)
    m = re.search(r"(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})", s)
    if m:
        return tuple(max(0, min(255, int(x))) for x in m.groups())
    m = re.search(r"#([0-9a-fA-F]{6})", s)
    if m:
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    low = s.lower()
    for name in sorted(_COLOR_NAMES, key=len, reverse=True):
        if name in low:
            return _COLOR_NAMES[name]
    return None


# -- sun ANGLE (elevation/azimuth) — a coupled TRANSFORM, not a property --------------
# A VRaySun's illumination direction is its geometry (position relative to its target),
# so elevation+azimuth can't be a per-row setattr like the other known_props. We treat
# them as one coupled move: place the sun on the sky sphere around its target. Convention:
# elevation = degrees above the horizon (0=horizon, 90=zenith); azimuth = compass degrees,
# 0 = +Y (North), increasing clockwise toward +X (East). All vector math is done in
# explicit components so it never depends on pymxs Point3 operator overloading.
def _proper_node(rt, class_name, name=None):
    """A node of a class as a PROPER node wrapper (with a working .position / .target /
    .name), optionally matched by exact name. getClassInstances() hands back opaque base
    wrappers whose node TRANSFORM is inaccessible (fine for object props like .multiplier,
    useless for the sun's angle), so iterate rt.objects for the sun-angle path instead."""
    for o in rt.objects:
        try:
            if str(rt.classOf(o)) == class_name and (name is None or str(o.name) == name):
                return o
        except Exception:
            continue
    return None


def _get_pos(rt, node):
    """Node world position as (x,y,z) — attribute access, which works on the rt.objects /
    getNodeByName node wrappers used for the sun-angle path."""
    p = node.position
    return float(p.x), float(p.y), float(p.z)


def _set_pos(rt, node, x, y, z):
    node.position = rt.Point3(x, y, z)


def _sun_target_point(rt, sun):
    """(Tx,Ty,Tz) the sun aims at — its Target if it has one, else world origin."""
    try:
        tgt = sun.target
        if tgt is not None:
            return _get_pos(rt, tgt)
    except Exception:
        pass
    return 0.0, 0.0, 0.0


def _sun_dir_and_dist(rt, sun):
    """Unit direction from the target TO the sun (where it sits in the sky) + the distance.
    Falls back to a default distance if the sun sits on its target."""
    tx, ty, tz = _sun_target_point(rt, sun)
    px, py, pz = _get_pos(rt, sun)
    vx, vy, vz = px - tx, py - ty, pz - tz
    d = math.sqrt(vx * vx + vy * vy + vz * vz)
    if d < 1e-6:
        return (0.0, 0.0, 1.0), 100000.0
    return (vx / d, vy / d, vz / d), d


def _sun_current_angles(rt, sun):
    """(elevation_deg, azimuth_deg) of the sun's CURRENT geometry."""
    (nx, ny, nz), _ = _sun_dir_and_dist(rt, sun)
    el = math.degrees(math.asin(max(-1.0, min(1.0, nz))))
    az = math.degrees(math.atan2(nx, ny)) % 360.0
    return el, az


def _set_sun_angles(rt, sun, elevation_deg, azimuth_deg):
    """Position the sun on the sky sphere for the given elevation/azimuth, preserving its
    distance to the target. For a targeted VRaySun (the standard archviz rig) the target
    constraint re-aims it automatically, which is exactly the illumination direction."""
    tx, ty, tz = _sun_target_point(rt, sun)
    _, d = _sun_dir_and_dist(rt, sun)
    er = math.radians(elevation_deg)
    ar = math.radians(azimuth_deg)
    dx = math.cos(er) * math.sin(ar)
    dy = math.cos(er) * math.cos(ar)
    dz = math.sin(er)
    _set_pos(rt, sun, tx + dx * d, ty + dy * d, tz + dz * d)


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
        # sun ANGLE has no simple property — read the sun's current geometry so the
        # snapshot (Save look / keep-best) can restore elevation/azimuth too.
        if m.get("type") == "sun_angle":
            s = _proper_node(rt, "VRaySun")
            if s is None:
                missing.append(param)
                continue
            try:
                el, az = _sun_current_angles(rt, s)
                params[param] = el if m.get("angle") == "elevation" else az
            except Exception:
                missing.append(param)
            continue
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
        elif m["type"] == "color":
            # store JSON-serialisable [r,g,b] (Save look persists params to the session
            # JSON, so a live Max color object can't go in); _parse_color reads it back.
            try:
                params[param] = [int(round(float(raw.r))), int(round(float(raw.g))), int(round(float(raw.b)))]
            except Exception:
                missing.append(param)
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
        # -- coupled sun-ANGLE pre-pass: placement_elevation + placement_azimuth define ONE
        # transform, so they can't go through the per-row setattr loop. Resolve the sun
        # once, apply the combined angle, and verify by reading the ACHIEVED angle back.
        angle_rows = [v for v in values if isinstance(v.get("param"), str)
                      and props.get(v["param"], {}).get("type") == "sun_angle"]
        if angle_rows:
            # GROUP by explicit node name (None = first-of-kind) so a multi-sun scene sets
            # each sun's angle on ITS OWN node instead of collapsing every row onto the
            # first sun. sun-angle needs a PROPER node wrapper (transform access) -> _proper_node.
            groups: dict = {}
            for v in angle_rows:
                nm = v.get("node") if isinstance(v.get("node"), str) and v.get("node") else None
                groups.setdefault(nm, []).append(v)
            for nm, grp in groups.items():
                sun = _proper_node(rt, "VRaySun", nm)
                if sun is None:
                    for v in grp:
                        failed.append(str(v.get("param")))
                    continue
                # A free (targetless) VRaySun is aimed by its ROTATION, not its position, so
                # translating it can't be trusted to re-aim it — report unverified rather than
                # a false 'verified'. Targeted suns (the standard rig) verify normally.
                try:
                    has_target = getattr(sun, "target", None) is not None
                except Exception:
                    has_target = False
                tgt_el, tgt_az = _sun_current_angles(rt, sun)
                usable = []
                for v in grp:
                    try:
                        val = float(v.get("set"))
                        if not math.isfinite(val):
                            raise ValueError
                    except (TypeError, ValueError):
                        failed.append(str(v.get("param"))); continue
                    if props[v["param"]]["angle"] == "elevation":
                        tgt_el = val
                    else:
                        tgt_az = val
                    usable.append(v)
                if not usable:
                    continue
                try:
                    _set_sun_angles(rt, sun, tgt_el, tgt_az)
                    ach_el, ach_az = _sun_current_angles(rt, sun)
                    for v in usable:
                        which = props[v["param"]]["angle"]
                        want, got = (tgt_el, ach_el) if which == "elevation" else (tgt_az, ach_az)
                        diff = abs(want - got)
                        if which == "azimuth":
                            diff = min(diff, 360.0 - diff)
                        applied.append(v["param"])
                        (verified if (has_target and diff < 0.5) else unverified).append(v["param"])
                except Exception:
                    for v in usable:
                        failed.append(str(v.get("param")))
            values = [v for v in values if v not in angle_rows]

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
                elif m["type"] == "color":
                    # The model emits colours as descriptions ("warm amber", "warm grey
                    # ~RGB(80,70,55)"); parse to RGB. These write VRaySun/VRayLight/ambient
                    # colour — a scene-node change Chaos Vantage reflects. (2026-07-16)
                    rgb = _parse_color(raw)
                    if rgb is None:
                        failed.append(param)
                        continue
                    val = rt.color(float(rgb[0]), float(rgb[1]), float(rgb[2]))
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
                    # A light's colour only takes effect in the matching color_mode: RGB
                    # `color` needs color_mode=0, `color_temperature` needs color_mode=1.
                    # Flip it after a successful set (mirrors the cam.exposure gate) so the
                    # warmth/tint actually lands and reflects in Vantage. (2026-07-15/16)
                    csm = m.get("color_mode_set")
                    if csm is not None:
                        try:
                            node.color_mode = int(csm)
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
    # `vfb_only` = applied moves that write the V-Ray render/exposure pipeline (camera
    # exposure, color mapping) — these change the V-Ray VFB but are NOT read by Chaos
    # Vantage (it has its own camera + color pipeline), so they are invisible in a Vantage
    # live-link review. Surfaced so the UI can tell the truth. (2026-07-15 Vantage work)
    vfb_only = [p for p in applied if props.get(p, {}).get("domain") == "vfb"]
    return {
        "applied": applied, "failed": failed, "manual": manual,
        "verified": verified, "unverified": unverified, "vfb_only": vfb_only,
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
        if kind == "color":
            return all(abs(float(getattr(read, c)) - float(getattr(expected, c))) <= 2.0
                       for c in ("r", "g", "b"))
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
