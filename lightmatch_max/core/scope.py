"""Control scope (global | camera | local) — reads the exported prefix map so the
plugin's Area-mode behavior can never drift from the web app's (web src/lib/scope.ts)."""

from __future__ import annotations

from .data import knownprops


def scope_of(param_id: str) -> str:
    prefix = param_id.split(".", 1)[0] if "." in param_id else param_id
    return knownprops()["prefix_scope"].get(prefix, "global")


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
