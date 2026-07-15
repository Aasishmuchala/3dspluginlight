"""Autopilot — the unattended refine loop: render → measure → correct → apply → repeat,
until measured-matched or a round budget. It runs the entire lighting for you.

PURE orchestrator over injected callables, so it is fully testable without Max and the
dock/Max layer only has to supply the four seams (render, correct, apply, and optional
progress/cancel). Every model-and-render round is one logged row; the caller drives one
undo step per apply and a final confirming render.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .engine import matched as _default_matched
from .metrics import match_percent


def _moves_from_correction(correction: dict) -> list[dict]:
    """Translate a correction's moves (which use `to`) into apply rows (which use `set`),
    carrying an explicit `node` when the model named a specific fixture. Globals were
    already stripped by the engine into withheld_globals, so they simply are not in
    `moves` — nothing to re-add here."""
    out: list[dict] = []
    for m in correction.get("moves") or []:
        if not isinstance(m, dict) or not isinstance(m.get("param"), str):
            continue
        if "to" not in m:
            continue
        row: dict[str, Any] = {"param": m["param"], "set": m["to"]}
        if isinstance(m.get("node"), str) and m["node"]:
            row["node"] = m["node"]
        out.append(row)
    return out


def run_autopilot(
    *,
    rounds: int,
    render_cb: Callable[[], dict],
    correct_cb: Callable[[dict, int], tuple],
    apply_cb: Callable[[list], dict],
    on_round: Optional[Callable[[dict], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    matched_fn: Optional[Callable[[float], bool]] = None,
    snapshot_cb: Optional[Callable[[], Any]] = None,
    restore_cb: Optional[Callable[[Any], Any]] = None,
) -> dict:
    """Loop up to `rounds` refine rounds.

    render_cb()            -> capture dict (session.capture shape)
    correct_cb(cap, n)     -> (score: float, correction: dict)   (engine.add_attempt seam)
    apply_cb(moves)        -> apply result dict {applied, failed, ...}
    on_round(row)          -> progress (exceptions swallowed)
    should_stop()          -> cooperative cancel, checked before each round
    matched_fn(score)      -> bool (default engine.matched)
    snapshot_cb()          -> opaque token capturing the CURRENT lighting (optional)
    restore_cb(token)      -> re-apply a snapshot token (optional)

    KEEP-BEST: the model is a noisy actuator — a correction can make the score WORSE than
    an earlier round (measured live: a run hit 97% then a later apply dropped it to 66%).
    When snapshot/restore seams are supplied, the loop snapshots the best-scoring state as
    it goes and, on ANY exit, leaves the scene at that best state instead of the last
    (possibly worse) one — so the user's final render is the best result the loop found,
    not wherever it happened to stop.

    stop_reason: matched | budget | no_moves | oscillating | cancelled | error:<Exc>.
    Never raises — a callable exception aborts with reason 'error:<ExcName>' and the
    partial rounds preserved.
    """
    matched_fn = matched_fn or _default_matched
    rows: list[dict] = []
    prev_score: Optional[float] = None
    worsen_streak = 0
    stop_reason = "budget"
    final_score: Optional[float] = None
    error_message: Optional[str] = None
    best_score: Optional[float] = None
    best_snap: Any = None

    def consider_best(score: float) -> None:
        """Snapshot the CURRENT scene when it is the best-scoring one so far. The score
        measures the live scene entering this round, so the snapshot IS the state that
        earned it. best_score and best_snap are updated ATOMICALLY: a better round whose
        snapshot fails (seam returns None or raises) is NOT recorded, so it can never
        clobber a good earlier best with a None we then can't restore."""
        nonlocal best_score, best_snap
        if best_score is not None and score >= best_score:
            return
        if snapshot_cb is None:
            best_score = score  # no seam: still track the best score for reporting
            return
        try:
            snap = snapshot_cb()
        except Exception:
            snap = None
        if snap is None:
            return  # couldn't capture this better state — keep the last restorable best
        best_score = score
        best_snap = snap

    def emit(row: dict) -> None:
        rows.append(row)
        if on_round:
            try:
                on_round(row)
            except Exception:
                pass  # progress reporting must never break the loop

    try:
        for n in range(1, rounds + 1):
            if should_stop and should_stop():
                stop_reason = "cancelled"
                break

            cap = render_cb()
            score, correction = correct_cb(cap, n)
            final_score = score
            consider_best(score)  # remember the best state before this round mutates it

            if matched_fn(score):
                emit({
                    "n": n, "score": score, "match_percent": match_percent(score),
                    "moves": [], "apply_result": None,
                    "status_reason": (correction or {}).get("status_reason", "matched"),
                })
                stop_reason = "matched"
                break

            # oscillation guard: two consecutive worsening rounds → stop burning renders
            if prev_score is not None and score > prev_score:
                worsen_streak += 1
            else:
                worsen_streak = 0
            prev_score = score

            moves = _moves_from_correction(correction or {})
            if not moves:
                emit({
                    "n": n, "score": score, "match_percent": match_percent(score),
                    "moves": [], "apply_result": None,
                    "status_reason": (correction or {}).get("status_reason", "no applicable moves"),
                })
                stop_reason = "no_moves"
                break

            if worsen_streak >= 2:
                emit({
                    "n": n, "score": score, "match_percent": match_percent(score),
                    "moves": moves, "apply_result": None,
                    "status_reason": "score worsened two rounds running — stopping to avoid oscillation",
                })
                stop_reason = "oscillating"
                break

            apply_result = apply_cb(moves)
            emit({
                "n": n, "score": score, "match_percent": match_percent(score),
                "moves": moves, "apply_result": apply_result,
                "status_reason": (correction or {}).get("status_reason", ""),
            })
    except Exception as e:  # any seam blew up — abort cleanly, keep the partial log
        stop_reason = f"error:{type(e).__name__}"
        error_message = str(e) or type(e).__name__

    # KEEP-BEST: leave the scene at the best-scoring state, not the last one. On EVERY exit
    # except 'matched' the scene is at the last, UNMEASURED apply output (a correction was
    # applied after the last measured score, or the loop was cancelled/errored), which is
    # unknown quality — so roll back to the best snapshot we actually captured. 'matched'
    # breaks BEFORE applying, so the scene there already IS the best (no restore needed).
    restored_best = False
    if restore_cb is not None and best_snap is not None and stop_reason != "matched":
        try:
            restore_cb(best_snap)
            restored_best = True
        except Exception:
            pass  # couldn't restore — leave the scene as-is rather than crash the loop

    # best (max) match across rounds — NOT the last round's, which can be lower after an
    # oscillation/budget stop (the last score may be the worst one measured).
    round_pcts = [r["match_percent"] for r in rows if isinstance(r.get("match_percent"), int)]
    best_match_percent = max(round_pcts) if round_pcts else None

    return {
        "rounds": rows,
        "final_score": final_score,
        "final_match_percent": match_percent(final_score) if final_score is not None else None,
        "best_match_percent": best_match_percent,
        "restored_to_best": restored_best,
        "matched": stop_reason == "matched",
        "stop_reason": stop_reason,
        "error_message": error_message,
    }
