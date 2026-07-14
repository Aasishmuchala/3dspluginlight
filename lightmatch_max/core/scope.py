"""Control scope (global | camera | local) — reads the exported prefix map so the
plugin's Area-mode behavior can never drift from the web app's (web src/lib/scope.ts)."""

from __future__ import annotations

from .data import knownprops


def scope_of(param_id: str) -> str:
    prefix = param_id.split(".", 1)[0] if "." in param_id else param_id
    return knownprops()["prefix_scope"].get(prefix, "global")


def stamp_camera_node(values, camera_name):
    """Stamp physical-camera moves with the PICKED camera's exact scene-node name so
    cam.iso / cam.fnumber / cam.shutter land on THAT physical camera, not the renderer's
    first-of-kind. Returns a NEW list; a camera-param row (known_props[param].node == "cam")
    with no explicit non-empty 'node' gets a shallow copy carrying node=camera_name. Every
    other row — non-camera params, rows already node-targeted, non-dicts — passes through
    untouched. No-op when camera_name is falsy or values isn't a list. NEVER mutates the
    input rows and NEVER raises, even on hostile rows (a non-str/unhashable `param` just
    passes through) — matching validate_items / withhold_globals, which guard the same way."""
    if not camera_name or not isinstance(values, list):
        return values
    kp = knownprops()["known_props"]
    out = []
    for it in values:
        # isinstance(param, str) BEFORE the dict lookup: a list/dict `param` is unhashable
        # and would raise on kp.get(param) otherwise (found by the camera stress sweep).
        param = it.get("param") if isinstance(it, dict) else None
        if isinstance(param, str) and kp.get(param, {}).get("node") == "cam" and not it.get("node"):
            row = dict(it)  # shallow copy — leave the caller's row untouched
            row["node"] = camera_name
            out.append(row)
        else:
            out.append(it)
    return out


def snapshot_to_rows(params, camera_name=None):
    """Turn a lighting SNAPSHOT — a {param: value} dict as produced by scene.pull_settings —
    into apply_values rows [{param, set, node?}], stamping physical-camera params with the
    given camera's node so a restored exposure lands on THAT camera. Skips non-str keys and
    degrades to [] on a non-dict snapshot; NEVER raises. Pure (no pymxs) so it's unit-testable."""
    if not isinstance(params, dict):
        return []
    rows = [{"param": k, "set": v} for k, v in params.items() if isinstance(k, str)]
    return stamp_camera_node(rows, camera_name)


def withhold_globals(cleaned: dict, items_key: str) -> dict:
    """Area-mode enforcement belt (port of the engine's withholdGlobals): strip
    scene-global moves from recipe `values` / correction `moves`, parking them on
    `withheld_globals` for disclosure. Correction moves carry `to`; recipe values
    carry `set` — both normalize to `set` in the withheld row."""
    items = cleaned.get(items_key) or []
    kept, withheld = [], []
    for it in items:
        if not isinstance(it, dict):
            kept.append(it)  # malformed rows pass through — validation is the filter
            continue
        param = it.get("param")
        if isinstance(param, str) and scope_of(param) == "global":
            raw = it.get("set") if items_key == "values" else it.get("to")
            row = {"param": param, "set": raw if isinstance(raw, (int, float, str)) else str(raw)}
            if isinstance(it.get("why"), str) and it["why"]:
                row["why"] = it["why"]
            withheld.append(row)
        else:
            kept.append(it)
    if not withheld:
        return cleaned
    out = dict(cleaned)
    out[items_key] = kept
    out["withheld_globals"] = withheld
    return out
