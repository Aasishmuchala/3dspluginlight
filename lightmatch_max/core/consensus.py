"""Consensus ×3 — fold N recipe results from IDENTICAL requests into ONE, to kill
run-to-run LLM variance on the initial recipe. Faithful port of the web app's
mergeConsensusRecipes (src/store/useEngine.ts):

  - per param across runs: numeric `set` → MEDIAN (robust middle; one outlier run can't
    drag the value), string `set` → MAJORITY vote (ties → the FIRST run's value,
    deterministic — no coin flips);
  - from/step/confidence/why (and any other metadata) come from the FIRST run that
    emitted the param (mixing metadata across runs would stitch a `why` onto a number it
    never justified);
  - consensus_n = how many runs emitted the param; params emitted by only ONE run are
    KEPT (not dropped) — the UI can flag low agreement, which is more honest than silently
    discarding a move;
  - dedupe key is (param, node) so per-fixture moves survive (matches validate_items);
  - the envelope (baseline/hdri_mood/rationale/…) comes from the first run, with a
    `consensus: {runs}` marker so the UI knows the denominator.

PURE — recipe dicts in, one recipe dict out. Correction rounds deliberately stay
single-call (a trim is history-coupled; merging three parallel trims corresponds to no
one model's coherent plan)."""

from __future__ import annotations

import math
from statistics import median
from typing import Any


def _finite_number(v) -> bool:
    """True only for a real, finite numeric `set`. math.isfinite() converts to float and
    raises OverflowError on a huge int literal (10**400) from a hostile model reply — treat
    that as non-numeric (falls to the majority-vote path) instead of crashing the merge."""
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return False
    try:
        return math.isfinite(v)
    except (OverflowError, ValueError):
        return False


def _nkey(item: dict) -> tuple:
    param = item.get("param")
    node = item.get("node") if isinstance(item.get("node"), str) and item.get("node") else None
    return (param, node)


def merge_consensus_recipes(runs: list[dict], max_items: int = 32) -> dict:
    """Merge N fulfilled recipe dicts (each with a `values` list) into one."""
    runs = [r for r in runs if isinstance(r, dict) and isinstance(r.get("values"), list)]
    if not runs:
        return {"values": [], "consensus": {"runs": 0}}
    first = runs[0]

    # first-appearance order of (param, node) across runs; per-key items in run order
    order: list[tuple] = []
    by_key: dict[tuple, list[dict]] = {}
    for run in runs:
        seen_in_run: set = set()
        for item in run.get("values", []):
            if not isinstance(item, dict) or not isinstance(item.get("param"), str):
                continue
            k = _nkey(item)
            if k in seen_in_run:
                continue  # validate_items already drops in-run dupes; belt
            seen_in_run.add(k)
            if k not in by_key:
                by_key[k] = []
                order.append(k)
            by_key[k].append(item)

    merged: list[dict] = []
    for k in order:
        items = by_key[k]
        out = dict(items[0])  # metadata from the first emitting run
        out["consensus_n"] = len(items)
        sets = [it.get("set") for it in items]
        all_numeric = all(_finite_number(v) for v in sets)
        if all_numeric:
            out["set"] = median(sets)
        else:
            # majority vote; ties → first run's value (insertion order preserved)
            counts: dict[str, dict] = {}
            for v in sets:
                key = f"{type(v).__name__}:{v}"
                c = counts.get(key) or {"v": v, "n": 0}
                c["n"] += 1
                counts[key] = c
            best_v: Any = sets[0]
            best_n = 0
            for c in counts.values():
                if c["n"] > best_n:
                    best_n = c["n"]
                    best_v = c["v"]
            out["set"] = best_v
        merged.append(out)

    # re-enforce the schema cap AFTER the merge: drop the lowest-consensus_n item (ties:
    # the LAST-appearing one) until it fits, so agreement survives truncation.
    while len(merged) > max_items:
        min_n = math.inf
        min_idx = -1
        for i, it in enumerate(merged):
            n = it.get("consensus_n", 1)
            if n <= min_n:  # <= keeps scanning → ties land on the last occurrence
                min_n = n
                min_idx = i
        merged.pop(min_idx)

    result = dict(first)
    result["values"] = merged
    result["consensus"] = {"runs": len(runs)}
    return result
