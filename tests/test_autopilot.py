"""Autopilot tests — the unattended loop over fake callables."""

from __future__ import annotations

import pytest

from lightmatch_max.core.autopilot import run_autopilot


def cap():
    return {"metrics": {}, "b64": "QUJD", "media_type": "image/jpeg"}


def corr(moves, status="continue", reason="trim"):
    return {"moves": moves, "rationale": "s", "status": status, "status_reason": reason}


def test_converges_and_stops_on_matched_without_applying():
    scores = iter([20.0, 8.0, 2.0])  # 3rd round matched (<=3)
    applied = []

    def correct_cb(c, n):
        return next(scores), corr([{"param": "cam.iso", "to": 200 - n, "from": 300}])

    def apply_cb(moves):
        applied.append(moves)
        return {"applied": [m["param"] for m in moves], "failed": []}

    res = run_autopilot(rounds=8, render_cb=cap, correct_cb=correct_cb, apply_cb=apply_cb)
    assert res["stop_reason"] == "matched" and res["matched"] is True
    assert res["final_match_percent"] == 98
    assert len(res["rounds"]) == 3
    assert len(applied) == 2  # the matched (3rd) round did NOT apply
    assert res["rounds"][-1]["apply_result"] is None


def test_oscillation_guard_after_two_worsenings():
    scores = iter([10.0, 14.0, 20.0, 25.0])  # monotonically worse

    def correct_cb(c, n):
        return next(scores), corr([{"param": "cam.iso", "to": 100 + n, "from": 100}])

    res = run_autopilot(rounds=8, render_cb=cap, correct_cb=correct_cb, apply_cb=lambda m: {"applied": []})
    assert res["stop_reason"] == "oscillating"
    # round1 10 (apply), round2 14 (worse#1, apply), round3 20 (worse#2 → stop, no apply)
    assert len(res["rounds"]) == 3
    assert res["rounds"][-1]["apply_result"] is None


def test_no_moves_stops():
    def correct_cb(c, n):
        return 15.0, corr([])  # nothing to apply

    res = run_autopilot(rounds=5, render_cb=cap, correct_cb=correct_cb, apply_cb=lambda m: {})
    assert res["stop_reason"] == "no_moves"
    assert len(res["rounds"]) == 1


def test_budget_exhaustion():
    def correct_cb(c, n):
        return 15.0 - n * 0.1, corr([{"param": "cam.iso", "to": 200, "from": 300}])  # improving, never matched

    res = run_autopilot(rounds=3, render_cb=cap, correct_cb=correct_cb, apply_cb=lambda m: {"applied": ["cam.iso"]})
    assert res["stop_reason"] == "budget"
    assert len(res["rounds"]) == 3


def test_cancel_before_first_round():
    res = run_autopilot(
        rounds=5, render_cb=cap, correct_cb=lambda c, n: (10.0, corr([])),
        apply_cb=lambda m: {}, should_stop=lambda: True,
    )
    assert res["stop_reason"] == "cancelled"
    assert res["rounds"] == []


def test_apply_exception_aborts_with_error_and_preserves_rounds():
    def apply_cb(moves):
        raise RuntimeError("scene locked")

    res = run_autopilot(
        rounds=5, render_cb=cap,
        correct_cb=lambda c, n: (15.0, corr([{"param": "cam.iso", "to": 200, "from": 300}])),
        apply_cb=apply_cb,
    )
    assert res["stop_reason"] == "error:RuntimeError"
    assert res["rounds"] == []  # error happened before the row was emitted this round


def test_node_passthrough_and_withheld_never_applied():
    seen = {}

    def apply_cb(moves):
        seen["moves"] = moves
        return {"applied": [m["param"] for m in moves]}

    def correct_cb(c, n):
        return 15.0, {
            "moves": [{"param": "light.multiplier", "to": 45, "from": 30, "node": "VRayLight_Kitchen_Fill"}],
            "withheld_globals": [{"param": "sun.intensity_mult", "set": 1.6}],
            "status_reason": "x", "status": "continue",
        }

    res = run_autopilot(rounds=1, render_cb=cap, correct_cb=correct_cb, apply_cb=apply_cb)
    assert seen["moves"] == [{"param": "light.multiplier", "set": 45, "node": "VRayLight_Kitchen_Fill"}]
    # the withheld global never reached apply
    assert all(m["param"] != "sun.intensity_mult" for m in seen["moves"])


def test_keep_best_restores_best_snapshot_at_end():
    # scores improve then WORSEN without ever matching -> the loop must roll the scene back
    # to the best-scoring round's snapshot, not leave it at the last (worse) state.
    scores = iter([10.0, 4.0, 8.0])
    snaps = iter(["A", "B", "C"])  # snapshot returns a distinct token per call
    restored = []

    res = run_autopilot(
        rounds=3, render_cb=cap,
        correct_cb=lambda c, n: (next(scores), corr([{"param": "cam.iso", "to": 200, "from": 300}])),
        apply_cb=lambda m: {"applied": ["cam.iso"]},
        snapshot_cb=lambda: next(snaps),
        restore_cb=lambda snap: restored.append(snap),
    )
    assert res["stop_reason"] == "budget"
    assert res["restored_to_best"] is True
    assert restored == ["B"]  # snapshot of the best round (score 4.0), not "A"/"C"
    assert res["best_match_percent"] == 96  # match_percent(4.0)


def test_keep_best_no_restore_when_matched():
    # a matched stop IS already the best state — nothing to roll back.
    scores = iter([10.0, 2.0])  # round 2 matched (<=3)
    restored = []

    res = run_autopilot(
        rounds=5, render_cb=cap,
        correct_cb=lambda c, n: (next(scores), corr([{"param": "cam.iso", "to": 200, "from": 300}])),
        apply_cb=lambda m: {"applied": ["cam.iso"]},
        snapshot_cb=lambda: "s", restore_cb=lambda snap: restored.append(snap),
    )
    assert res["stop_reason"] == "matched"
    assert res["restored_to_best"] is False
    assert restored == []


def test_keep_best_restores_after_budget_even_when_last_round_was_best():
    # last round has the best score but then applies a correction (budget exit) -> the scene
    # is now post-apply/unmeasured, so keep-best must still roll back to that best snapshot.
    scores = iter([10.0, 5.0])
    snaps = iter(["A", "B"])
    restored = []
    res = run_autopilot(
        rounds=2, render_cb=cap,
        correct_cb=lambda c, n: (next(scores), corr([{"param": "cam.iso", "to": 200, "from": 300}])),
        apply_cb=lambda m: {"applied": ["cam.iso"]},
        snapshot_cb=lambda: next(snaps), restore_cb=lambda s: restored.append(s),
    )
    assert res["stop_reason"] == "budget"
    assert restored == ["B"] and res["restored_to_best"] is True


def test_keep_best_failed_snapshot_never_clobbers_a_good_one():
    # the BEST-scoring round's snapshot FAILS (seam returns None) -> it must NOT become the
    # recorded best; restore falls back to the best snapshot we could actually capture,
    # never None.
    scores = iter([10.0, 3.5, 12.0])  # 3.5 is best but not matched (>3)
    snaps = iter(["A", None, "C"])    # round 2 (the best) can't be snapshotted
    restored = []
    res = run_autopilot(
        rounds=3, render_cb=cap,
        correct_cb=lambda c, n: (next(scores), corr([{"param": "cam.iso", "to": 200, "from": 300}])),
        apply_cb=lambda m: {"applied": ["cam.iso"]},
        snapshot_cb=lambda: next(snaps), restore_cb=lambda s: restored.append(s),
    )
    assert restored == ["A"]  # best RESTORABLE snapshot, never None


def test_keep_best_noop_without_seams():
    # backward-compat: no snapshot/restore seams -> keep-best is inert, loop behaves as before.
    res = run_autopilot(
        rounds=2, render_cb=cap,
        correct_cb=lambda c, n: (10.0 + n, corr([{"param": "cam.iso", "to": 200, "from": 300}])),
        apply_cb=lambda m: {"applied": ["cam.iso"]},
    )
    assert res["restored_to_best"] is False


def test_on_round_progress_exceptions_swallowed():
    def bad_progress(row):
        raise ValueError("ui gone")

    res = run_autopilot(
        rounds=1, render_cb=cap,
        correct_cb=lambda c, n: (2.0, corr([])),  # matched
        apply_cb=lambda m: {}, on_round=bad_progress,
    )
    assert res["stop_reason"] == "matched"  # progress error didn't break the loop
