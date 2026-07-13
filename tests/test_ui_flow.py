"""Offscreen UI-flow drive of the real LightMatchDock widget — proves the whole
click-path (reference → grab → analyze → recipe table + checkboxes → apply → check →
score + correction table) wires up, with the gateway and Max I/O stubbed. Runs under
Qt's offscreen platform, so it needs no display and no Max. Skips cleanly if PySide6
is absent (it ships inside Max)."""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytestmark = pytest.mark.ui  # excluded from the default run (PySide6 teardown quirk)

pytest.importorskip("PySide6")
from PySide6 import QtCore, QtWidgets  # noqa: E402

from lightmatch_max.core import engine  # noqa: E402
from lightmatch_max.core import session as sess  # noqa: E402
from lightmatch_max.ui import dock as dockmod  # noqa: E402


@pytest.fixture(scope="session")
def app():
    # SESSION scope + never destroy the QApplication: a module-scoped app that is torn
    # down mid-suite while any dock's QThread lingers crashes the process on PySide6 6.11
    # (access violation). The dock's closeEvent joins its threads; this app outlives them.
    a = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield a


@pytest.fixture
def make_dock(app):
    """Factory that tracks every dock it creates and GUARANTEES teardown (join threads,
    delete the C++ object, flush events) after the test — even on failure — so no Qt
    object survives into the next test / interpreter teardown."""
    created = []

    def _make():
        d = dockmod.LightMatchDock()
        created.append(d)
        return d

    yield _make
    import gc
    for d in created:
        try:
            d._shutdown()
            d.deleteLater()
        except Exception:
            pass
    for _ in range(3):
        QtWidgets.QApplication.processEvents(QtCore.QEventLoop.AllEvents, 20)
    gc.collect()
    QtWidgets.QApplication.processEvents(QtCore.QEventLoop.AllEvents, 20)


def _pil(w=48, h=32, fill=(180, 120, 60)):
    from PIL import Image
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[..., 0], arr[..., 1], arr[..., 2] = fill
    return Image.fromarray(arr, "RGB")


STUB_RECIPE = {
    "baseline": "settings_screenshot", "hdri_mood": "warm",
    "values": [
        {"param": "cam.iso", "set": 260, "from": 320, "step": 1, "confidence": "high", "why": "brighter"},
        {"param": "light.multiplier", "set": 50, "from": 42, "step": 4, "confidence": "med", "why": "fill"},
        {"param": "sun.intensity_mult", "set": 1.6, "from": 1.35, "step": 2, "confidence": "high", "why": "key"},
    ],
    "rationale": "stub", "gi_notes": "", "status": "continue",
}
STUB_CORR = {
    "moves": [{"param": "cam.iso", "to": 240, "from": 260, "step": 1, "confidence": "high", "why": "trim"}],
    "rationale": "stub", "status": "continue", "status_reason": "closer", "applied_assumed": True,
}


def _drain(widget, timeout_ms=4000):
    """Pump the event loop until no worker threads remain (analyze/check run on a
    QThread and post back)."""
    deadline = QtCore.QElapsedTimer()
    deadline.start()
    app = QtWidgets.QApplication.instance()
    while deadline.elapsed() < timeout_ms:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        if all(not t.isRunning() for t in widget._threads):
            app.processEvents()
            return
    raise TimeoutError("worker did not finish")


def test_full_dock_flow(make_dock, tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "SESS_DIR", tmp_path)
    monkeypatch.setattr(sess, "CONFIG_PATH", tmp_path / "config.json")

    # stub the gateway: recipe then correction
    calls = {"n": 0}

    def fake_analyze(*a, **k):
        calls["n"] += 1
        # exercise the real validate + Area-withhold path via the engine
        target, ref, base = a[2], a[3], a[4]
        lock = k.get("lock_globals", a[7] if len(a) > 7 else False)
        cleaned = engine.validate_items(target, dict(STUB_RECIPE), "recipe")
        from lightmatch_max.core.scope import withhold_globals
        return withhold_globals(cleaned, "values") if lock else cleaned

    def fake_add_attempt(*a, **k):
        cleaned = engine.validate_items("vray7max", dict(STUB_CORR), "correction")
        return 8.0, cleaned  # look 8 → 92%

    monkeypatch.setattr(dockmod.engine, "analyze", fake_analyze)
    monkeypatch.setattr(dockmod.engine, "add_attempt", fake_add_attempt)

    # stub Max I/O the dock touches
    monkeypatch.setattr(dockmod, "IN_MAX", True)
    monkeypatch.setattr(dockmod.maxvfb, "grab_vfb", lambda: _pil(fill=(90, 110, 150)))
    monkeypatch.setattr(dockmod.maxvfb, "render_view", lambda *a, **k: _pil(fill=(120, 110, 90)))
    applied_log = {}
    monkeypatch.setattr(
        dockmod.maxscene, "pull_settings",
        lambda: {"params": {"sun.turbidity": 3.0, "cam.iso": 320.0}, "renderer": "V_Ray_7", "missing": [], "counts": {}},
    )

    def fake_apply(values):
        applied_log["values"] = values
        return {"applied": [v["param"] for v in values], "failed": [], "manual": []}

    monkeypatch.setattr(dockmod.maxscene, "apply_values", fake_apply)

    d = make_dock()
    d.key_edit.setText("oc_stub")
    d.lock_chk.setChecked(True)

    # 1) reference via the capture path (bypass the file dialog)
    d.session["ref"] = sess.capture(_pil(fill=(200, 130, 70)))
    # 2) grab a base render
    d._grab(base=True)
    assert d.base_capture is not None

    # 3) analyze
    d._analyze()
    _drain(d)
    assert calls["n"] == 1
    # recipe table shows ONLY the kept camera+local rows; the global was withheld
    controls = [d.table.item(r, 1).data(QtCore.Qt.UserRole)["param"] for r in range(d.table.rowCount())]
    assert controls == ["cam.iso", "light.multiplier"]
    assert "withheld" in d.withheld_label.text().lower()
    assert "sun.intensity_mult" in d.withheld_label.text()

    # 4) uncheck one row, apply — only the checked control reaches the scene
    d.table.item(1, 0).setCheckState(QtCore.Qt.Unchecked)
    d._apply()
    assert [v["param"] for v in applied_log["values"]] == ["cam.iso"]
    assert "applied 1" in d.status.text()

    # 5) re-render & check → score + correction table
    d._check()
    _drain(d)
    assert "92%" in d.score_label.text()
    corr_controls = [d.table.item(r, 1).data(QtCore.Qt.UserRole)["param"] for r in range(d.table.rowCount())]
    assert corr_controls == ["cam.iso"]
    # session persisted with the attempt
    assert len(sess.list_sessions()) >= 1


def test_dock_diagnostics_runs_via_marshaller(make_dock, tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "SESS_DIR", tmp_path)
    monkeypatch.setattr(sess, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(dockmod, "IN_MAX", True)
    monkeypatch.setattr(dockmod.maxscene, "renderer_name", lambda: "V_Ray_7")
    monkeypatch.setattr(dockmod.maxscene, "pull_settings",
                        lambda: {"params": {"sun.turbidity": 3.0}, "renderer": "V_Ray_7", "missing": []})
    monkeypatch.setattr(dockmod.maxscene, "collect_census",
                        lambda: {"is_vray": True, "renderer": "V_Ray_7", "lights": [{"name": "L", "on": True}],
                                 "suns": [{"name": "S", "on": True}], "cameras": [{"name": "c", "class": "VRayPhysicalCamera", "exposure_on": True}],
                                 "exposure_control": {"class": None, "active": False}, "gamma": 2.2, "color_mapping": {"type": "Reinhard"}})
    monkeypatch.setattr(dockmod.maxscene, "apply_values",
                        lambda moves: {"applied": [m["param"] for m in moves], "failed": [], "verified": [m["param"] for m in moves], "unverified": [], "manual": []})

    d = make_dock()
    d.key_edit.setText("")  # no key → the gateway check reports a note, not a failure
    d._diagnostics()
    _drain(d, timeout_ms=6000)
    report = d.warn_label.text()
    assert "checks passed" in report
    assert "✓ Main-thread marshaller" in report        # the marshaller ran (worker→main)
    assert "✓ Scene census" in report or "Scene census" in report
    assert "no key yet" in report                        # gateway check without a key


def test_dock_guards_without_inputs(make_dock, tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "SESS_DIR", tmp_path)
    monkeypatch.setattr(sess, "CONFIG_PATH", tmp_path / "config.json")
    d = make_dock()
    d._analyze()  # no reference/base → guarded, no crash
    assert "reference" in d.status.text().lower() or "grab" in d.status.text().lower()


def test_run_on_main_marshals_pymxs_to_the_gui_thread(make_dock, tmp_path, monkeypatch):
    """The critical safety guarantee: a pymxs call issued from a WORKER thread runs on
    the MAIN (GUI) thread via _run_on_main — pymxs is main-thread-only."""
    import threading

    monkeypatch.setattr(sess, "SESS_DIR", tmp_path)
    monkeypatch.setattr(sess, "CONFIG_PATH", tmp_path / "config.json")
    d = make_dock()
    main_tid = threading.get_ident()
    captured = {}

    def worker_job():
        # this runs on a worker QThread; the marshalled fn must run on the main thread
        def pymxs_op():
            captured["ran_on"] = threading.get_ident()
            return "ok"
        captured["worker_on"] = threading.get_ident()
        return d._run_on_main(pymxs_op)

    d._spawn(worker_job, lambda r: captured.update(result=r))
    _drain(d, timeout_ms=5000)
    assert captured["result"] == "ok"
    assert captured["worker_on"] != main_tid          # the job really ran off-thread
    assert captured["ran_on"] == main_tid             # but the pymxs op ran on main


def test_session_picker_reloads_reference_and_recipe(make_dock, tmp_path, monkeypatch):
    """Reopening a saved session restores its reference, context, lock, and last move
    card onto a fresh dock — and clears base_capture so the artist must re-grab (the live
    scene may have moved on). The MAJOR usability gap: sessions were write-only before."""
    monkeypatch.setattr(sess, "SESS_DIR", tmp_path)
    monkeypatch.setattr(sess, "CONFIG_PATH", tmp_path / "config.json")

    s = sess.new_session("vray7max")
    s["ref"] = sess.capture(_pil(fill=(200, 130, 70)))
    s["recipe"] = {"values": [{"param": "cam.iso", "set": 260, "from": 320, "why": "x"}]}
    s["context"] = {"scene": "interior", "time": "dusk", "rig": "both"}
    s["lock_globals"] = True
    sess.push_attempt(s, 8.0, {"moves": [{"param": "cam.iso", "to": 240, "from": 260, "why": "trim"}],
                               "status": "continue"})
    sess.save(s)

    d = make_dock()
    d.base_capture = _pil()  # pretend a stale render is loaded
    assert d.session["id"] != s["id"]

    d._load_session(s["id"])

    assert d.session["id"] == s["id"]
    assert d.session.get("ref") is not None          # reference restored
    assert d.lock_chk.isChecked() is True            # lock restored
    assert d.scene_box.currentText() == "interior"   # context restored
    assert d.time_box.currentText() == "dusk"
    assert d._has_recipe is True
    assert d.base_capture is None                     # stale render cleared → must re-grab
    # the table shows the LATEST correction move, not the original recipe
    params = [d.table.item(r, 1).data(QtCore.Qt.UserRole)["param"] for r in range(d.table.rowCount())]
    assert params == ["cam.iso"]
    assert d.table.item(0, 2).text() == "260 → 240"  # from → to of the correction


def test_dock_autopilot_runs_and_reports(make_dock, tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "SESS_DIR", tmp_path)
    monkeypatch.setattr(sess, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(dockmod, "IN_MAX", True)
    monkeypatch.setattr(dockmod.maxvfb, "render_view", lambda *a, **k: _pil())
    monkeypatch.setattr(dockmod.maxscene, "pull_settings", lambda: {"params": {}, "renderer": "V"})
    monkeypatch.setattr(dockmod.maxscene, "apply_values",
                        lambda moves: {"applied": [m["param"] for m in moves], "failed": [], "verified": [m["param"] for m in moves], "unverified": [], "manual": []})

    scores = iter([15.0, 6.0, 2.0])  # matched on round 3

    def fake_add_attempt(*a, **k):
        return next(scores), {"moves": [{"param": "cam.iso", "to": 250, "from": 300}], "status_reason": "r", "status": "continue"}

    monkeypatch.setattr(dockmod.engine, "add_attempt", fake_add_attempt)

    d = make_dock()
    d.key_edit.setText("oc_stub")
    d.session["ref"] = sess.capture(_pil(fill=(200, 130, 70)))
    d.session["recipe"] = {"values": [{"param": "cam.iso", "set": 300, "from": 320}]}
    d._has_recipe = True  # precondition a real Analyze establishes
    d.rounds_spin.setValue(6)
    d._autopilot()
    _drain(d, timeout_ms=6000)
    assert "MATCHED" in d.score_label.text() or "matched" in d.status.text().lower()
