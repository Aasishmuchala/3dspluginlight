"""LightMatch dock — the in-Max UI (PySide6, Max 2025+). v0.1 covers the whole loop:

  reference (pick/drop) → [Grab VFB / Render] base → context + Lock globals →
  Analyze → recipe table (check rows) → APPLY (undoable) → re-render → CHECK →
  score + correction rows → repeat until matched.

Deliberately spare: one dockable panel, dense rows, no ceremony. The web app remains
the tool for Chaos Vantage; this dock is V-Ray-in-Max native."""

from __future__ import annotations

import threading
import traceback
from typing import Any, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import autopilot, data, depth_evidence as depthmod, engine, scope, session as sess
from ..core.census_format import census_block, census_warnings, summarize_for_ui
from ..core.metrics import match_percent
from ..core.omega import DEFAULT_MODEL, OmegaError

import importlib.util

from ..maxio import scene as maxscene
from ..maxio import vfb as maxvfb

# The maxio modules import cleanly ANYWHERE (pymxs loads lazily inside them), so
# "did the import succeed" is the wrong Max detector — probe for pymxs itself.
IN_MAX = importlib.util.find_spec("pymxs") is not None

TARGET = "vray7max"
AMBER = "#C98A55"   # warning — muted terracotta, in the warm-neutral family
GREEN = "#D6BB80"   # matched / success — champagne (the accent, celebratory)
ACCENT = "#C8A96A"  # the single champagne-gold accent

# "Quiet luxury" — restraint over decoration (PySide6 QSS): a matte warm near-black surface,
# generous space, ultra-fine hairline detailing, and ONE champagne-gold accent used only
# where it earns attention (the primary action, the matched state). No gloss, no glow, no
# neon. Everything else is calm neutral. (Neomorphism needs soft inset+outset shadows, which
# Qt QSS cannot render, so the luxury reads through material + spacing + a single accent.)
GLASS_QSS = """
* {
    font-family: "SF Pro Text", "SF Pro Display", "Segoe UI Variable Text", "Segoe UI", -apple-system, sans-serif;
    font-size: 12px;
    color: #ECEAE3;
    outline: 0;
}
QWidget#LMDock {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #16151B, stop:1 #100F14);
}
QLabel { background: transparent; color: #ECEAE3; }
QToolTip {
    background: #1C1B22; color: #ECEAE3;
    border: 1px solid rgba(255,255,255,0.10); border-radius: 8px; padding: 6px 10px;
}

/* calm ghost buttons — hairline firms up on hover, no fills shouting */
QPushButton {
    background: rgba(255,255,255,0.035); color: #E4E1D8;
    border: 1px solid rgba(255,255,255,0.08); border-radius: 9px; padding: 8px 13px;
}
QPushButton:hover { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.17); }
QPushButton:pressed { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.10); }
QPushButton:disabled { background: transparent; color: rgba(236,234,227,0.24); border: 1px solid rgba(255,255,255,0.045); }

/* primary — champagne gold, dark text (the one emphasized surface) */
QPushButton#primaryBtn {
    background: #C8A96A; color: #1A1712; font-weight: 600;
    border: 0; border-radius: 9px; padding: 11px 13px;
}
QPushButton#primaryBtn:hover { background: #D6BB80; }
QPushButton#primaryBtn:pressed { background: #B99A5B; }
QPushButton#primaryBtn:disabled { background: rgba(200,169,106,0.22); color: rgba(26,23,18,0.5); }

/* autopilot — understated gold outline */
QPushButton#autopilotBtn {
    background: transparent; color: #D6BB80; font-weight: 600;
    border: 1px solid rgba(200,169,106,0.45);
}
QPushButton#autopilotBtn:hover { background: rgba(200,169,106,0.10); border: 1px solid rgba(200,169,106,0.7); }
QPushButton#autopilotBtn:disabled { color: rgba(214,187,128,0.3); border: 1px solid rgba(200,169,106,0.15); }

/* stop — quiet neutral; warms to red only on hover */
QPushButton#stopBtn {
    background: transparent; color: #C9A9A9; border: 1px solid rgba(255,255,255,0.08);
}
QPushButton#stopBtn:hover { background: rgba(200,90,90,0.14); color: #E7B3B3; border: 1px solid rgba(200,90,90,0.42); }
QPushButton#stopBtn:disabled { color: rgba(201,169,169,0.3); border: 1px solid rgba(255,255,255,0.045); }

/* recessed fields */
QLineEdit, QComboBox, QSpinBox {
    background: rgba(255,255,255,0.03); color: #ECEAE3;
    border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 8px 11px;
    selection-background-color: rgba(200,169,106,0.4);
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid rgba(200,169,106,0.6); }
QComboBox::drop-down { border: 0; width: 22px; }
QComboBox::down-arrow {
    image: none; width: 0; height: 0;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid rgba(180,175,162,0.8); margin-right: 9px;
}
QComboBox QAbstractItemView {
    background: #1C1B22; color: #ECEAE3;
    border: 1px solid rgba(255,255,255,0.10); border-radius: 8px;
    selection-background-color: rgba(200,169,106,0.35); outline: 0; padding: 4px;
}
QSpinBox::up-button, QSpinBox::down-button { width: 0; border: 0; }

/* checkbox — gold when set */
QCheckBox { background: transparent; color: #B7B3A8; spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid rgba(255,255,255,0.22); background: transparent;
}
QCheckBox::indicator:hover { border: 1px solid rgba(200,169,106,0.7); }
QCheckBox::indicator:checked { background: #C8A96A; border: 1px solid #C8A96A; }

/* table — minimal, hairline rows, no vertical rules */
QTableWidget {
    background: transparent; alternate-background-color: rgba(255,255,255,0.018);
    color: #ECEAE3; border: 1px solid rgba(255,255,255,0.07); border-radius: 10px;
    gridline-color: transparent;
    selection-background-color: rgba(200,169,106,0.22); selection-color: #FFFFFF;
}
QTableWidget::item { padding: 5px 7px; border: 0; border-bottom: 1px solid rgba(255,255,255,0.04); }
QHeaderView::section {
    background: transparent; color: #8A857A; border: 0;
    border-bottom: 1px solid rgba(255,255,255,0.10); padding: 8px 7px; font-weight: 600;
}
QTableCornerButton::section { background: transparent; border: 0; }

/* thin neutral scrollbars, gold on hover */
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: rgba(255,255,255,0.13); border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: rgba(200,169,106,0.5); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle:horizontal { background: rgba(255,255,255,0.13); border-radius: 4px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
"""


class Worker(QtCore.QObject):
    done = QtCore.Signal(object)
    fail = QtCore.Signal(str)

    def __init__(self, fn, on_done, thread):
        super().__init__()
        self._fn = fn
        self.on_done = on_done      # called on the GUI thread (see _worker_done)
        self.thread_ref = thread

    def run(self):
        try:
            self.done.emit(self._fn())
        except OmegaError as e:
            self.fail.emit(str(e))
        except Exception as e:  # surface anything — never a silent dead button
            self.fail.emit(f"{e}\n{traceback.format_exc(limit=3)}")


class LightMatchDock(QtWidgets.QWidget):
    apRow = QtCore.Signal(dict)       # autopilot per-round progress (worker → GUI thread)
    _mainCall = QtCore.Signal(object)  # marshal a pymxs call onto the GUI/main thread

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Light")
        self.setMinimumWidth(420)
        self.session = sess.new_session(TARGET)
        # base_capture is a PROPERTY over the active camera's slot (Stage 2) — the render
        # you provide is remembered per camera, not on the widget.
        self.cfg = sess.load_config()
        self._threads: list[QtCore.QThread] = []
        self._workers: list[QtCore.QObject] = []
        self._ap_cancel = False
        self._ap_running = False
        self._has_recipe = False
        self._build()
        self.apRow.connect(self._ap_row)
        self._mainCall.connect(self._exec_main_call)
        self._update_buttons(busy=False)
        self._refresh_cameras()  # populate the picker from the live scene (best-effort)

    # -- main-thread marshalling: 3ds Max / pymxs is MAIN-THREAD-ONLY, so every scene
    # read or mutation must run on the GUI thread. Worker threads (which carry the slow
    # network round) call _run_on_main(fn) to hop a single pymxs op onto the main thread
    # and block until it returns. Running pymxs on a worker QThread can hard-crash Max —
    # this is the guard that keeps scene access on the main thread while the gateway call
    # stays off it (found in the 2026-07-13 review; batch tests never hit it because
    # 3dsmaxbatch is single-threaded).
    @QtCore.Slot(object)
    def _exec_main_call(self, call):
        # If the caller already gave up (timeout), do NOT run the scene op — a timed-out
        # apply must not mutate the scene later behind the user's back (found 2026-07-13).
        if call.get("abandoned"):
            return
        try:
            call["result"] = call["fn"]()
        except Exception as e:  # noqa: BLE001 — ferried back to the worker
            call["error"] = e
        finally:
            call["event"].set()

    # Bound wait: if the main-thread Qt loop ever stalls (a modal, a blocking render
    # path), an unbounded wait would freeze Max forever. A generous timeout turns a
    # hang into a clean, debuggable error instead. Renders can be slow, so it is long.
    MAIN_CALL_TIMEOUT_S = 600

    def _run_on_main(self, fn):
        if QtCore.QThread.currentThread() is self.thread():
            return fn()  # already on the main thread
        call = {"fn": fn, "event": threading.Event(), "result": None, "error": None, "abandoned": False}
        self._mainCall.emit(call)  # queued → runs in _exec_main_call on the main thread
        if not call["event"].wait(timeout=self.MAIN_CALL_TIMEOUT_S):
            call["abandoned"] = True  # if it fires later, _exec_main_call skips it
            raise TimeoutError(
                "3ds Max did not respond on the main thread within "
                f"{self.MAIN_CALL_TIMEOUT_S}s — a render or dialog may be blocking it."
            )
        if call["error"] is not None:
            raise call["error"]
        return call["result"]

    # -- UI scaffold -------------------------------------------------------------
    def _build(self):
        # "Quiet luxury" theme: a styled background needs WA_StyledBackground so the QWidget
        # subclass actually paints the QSS surface, and an objectName so #LMDock scopes the
        # matte fill without bleeding onto every child.
        self.setObjectName("LMDock")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setStyleSheet(GLASS_QSS)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 22)
        lay.setSpacing(14)

        # -- wordmark header: a big, quiet "Light" + one-line what-it-does, then a hairline.
        head = QtWidgets.QVBoxLayout()
        head.setSpacing(2)
        self.wordmark = QtWidgets.QLabel("Light")
        wf = self.wordmark.font()
        wf.setPointSize(20)
        wf.setBold(True)
        self.wordmark.setFont(wf)
        self.wordmark.setStyleSheet("color:#ECEAE3; background:transparent;")
        self.tagline = QtWidgets.QLabel("Match your V-Ray render's lighting to a reference image.")
        self.tagline.setWordWrap(True)
        self.tagline.setStyleSheet("color:#8A857A; background:transparent; font-size:12px;")
        head.addWidget(self.wordmark)
        head.addWidget(self.tagline)
        lay.addLayout(head)
        rule = QtWidgets.QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet("background:rgba(255,255,255,0.09); border:0;")
        lay.addWidget(rule)
        lay.addSpacing(2)

        # key + model row
        row = QtWidgets.QHBoxLayout()
        self.key_edit = QtWidgets.QLineEdit(self.cfg.get("key", ""))
        self.key_edit.setPlaceholderText("oc_… omega key")
        self.key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.key_edit.editingFinished.connect(self._save_cfg)
        self.model_box = QtWidgets.QComboBox()
        self.model_box.addItems([DEFAULT_MODEL, "gpt-5.5"])
        self.model_box.setCurrentText(self.cfg.get("model", DEFAULT_MODEL))
        self.model_box.currentTextChanged.connect(lambda *_: self._save_cfg())
        row.addWidget(self.key_edit, 1)
        row.addWidget(self.model_box)
        lay.addLayout(row)

        # reference + base
        io_row = QtWidgets.QHBoxLayout()
        self.ref_btn = QtWidgets.QPushButton("Reference…")
        self.ref_btn.setToolTip("Load the target image you're matching TOWARD (the look you want).")
        self.ref_btn.clicked.connect(self._pick_reference)
        self.base_btn = QtWidgets.QPushButton("Base…")
        self.base_btn.setToolTip("Load YOUR OWN render (a saved image file) as the base to match — you render "
                                 "however you like, then provide the file. No auto-render; works even outside Max.")
        self.base_btn.clicked.connect(self._pick_base)
        self.grab_btn = QtWidgets.QPushButton("Grab VFB")
        self.grab_btn.setToolTip("Use the render already in Max's V-Ray frame buffer as the base.")
        self.grab_btn.clicked.connect(lambda: self._grab(base=True))
        self.render_btn = QtWidgets.QPushButton("Render view")
        self.render_btn.setToolTip("Optional convenience: auto-render the active view as the base.")
        self.render_btn.clicked.connect(lambda: self._render(base=True))
        self.sessions_btn = QtWidgets.QPushButton("Sessions ▾")
        self.sessions_btn.setToolTip("Reopen a past session (its reference + last recipe) or start a new one.")
        self.sessions_btn.clicked.connect(self._open_sessions)
        io_row.addWidget(self.ref_btn)
        io_row.addWidget(self.base_btn)
        io_row.addWidget(self.grab_btn)
        io_row.addWidget(self.render_btn)
        io_row.addWidget(self.sessions_btn)
        lay.addLayout(io_row)

        # camera scope — pick WHICH scene camera your camera-exposure moves target
        # (cam.iso/fnumber/shutter land on that exact node, not first-of-kind). Picking is
        # passive: it does NOT move the viewport or render. You provide the base render
        # yourself (Base… / Grab VFB). Render camera is an optional auto-render convenience.
        cam_row = QtWidgets.QHBoxLayout()
        self.cam_box = QtWidgets.QComboBox()
        self.cam_box.setToolTip("Scene camera your camera-exposure moves target. Picking is passive — "
                                "you provide the render yourself (Base… / Grab VFB). Each camera keeps "
                                "its own reference, render, and recipe.")
        # Switching cameras recalls that camera's stored state (Stage 2). _refresh_cameras
        # repopulates under blockSignals, so a rescan never fires a spurious recall.
        self.cam_box.currentTextChanged.connect(self._on_camera_changed)
        self.cam_refresh_btn = QtWidgets.QPushButton("⟳")
        self.cam_refresh_btn.setToolTip("Rescan scene cameras")
        self.cam_refresh_btn.setFixedWidth(28)
        self.cam_refresh_btn.clicked.connect(self._refresh_cameras)
        self.render_cam_btn = QtWidgets.QPushButton("Render camera")
        self.render_cam_btn.setToolTip("Optional: point the active viewport at the picked camera and auto-render it. "
                                       "Skip this if you'd rather render yourself and load it with Base….")
        self.render_cam_btn.clicked.connect(self._render_camera)
        cam_row.addWidget(self.cam_box, 1)
        cam_row.addWidget(self.cam_refresh_btn)
        cam_row.addWidget(self.render_cam_btn)
        lay.addLayout(cam_row)

        # Stage 3 — per-camera LIGHTING SNAPSHOT. Save the scene's current lighting as this
        # camera's look; Restore re-applies it (undoable). Auto lighting (OFF by default)
        # does save-on-leave / restore-on-enter as you switch cameras — the only control
        # here that mutates the scene, so it is strictly opt-in.
        light_row = QtWidgets.QHBoxLayout()
        self.save_look_btn = QtWidgets.QPushButton("Save look")
        self.save_look_btn.setToolTip("Snapshot the scene's current lighting (sun, lights, color mapping, "
                                      "exposure) as THIS camera's look.")
        self.save_look_btn.clicked.connect(self._save_look)
        self.restore_look_btn = QtWidgets.QPushButton("Restore look")
        self.restore_look_btn.setToolTip("Re-apply this camera's saved lighting to the scene — one undo step.")
        self.restore_look_btn.clicked.connect(self._restore_look)
        self.vantage_btn = QtWidgets.QPushButton("⚡ Vantage link")
        self.vantage_btn.setToolTip("Start the Chaos Vantage live-link (or refresh it if already running) so your "
                                    "sun/light changes stream into Vantage live. Needs V-Ray GPU as the renderer.")
        self.vantage_btn.clicked.connect(self._vantage_clicked)
        self.autolight_chk = QtWidgets.QCheckBox("Auto lighting on switch")
        self.autolight_chk.setToolTip("OFF by default. When ON, switching cameras SAVES the outgoing camera's "
                                      "lighting and RESTORES the incoming camera's saved look (undoable). This "
                                      "changes your scene on every switch — leave off if you don't want that.")
        light_row.addWidget(self.save_look_btn)
        light_row.addWidget(self.restore_look_btn)
        light_row.addWidget(self.vantage_btn)
        light_row.addWidget(self.autolight_chk, 1)
        lay.addLayout(light_row)

        self.io_label = QtWidgets.QLabel("Load a reference, pick a camera, then provide your render (Base… or Grab VFB).")
        self.io_label.setWordWrap(True)
        lay.addWidget(self.io_label)

        # scene census summary + pre-flight warnings (populated on Analyze)
        self.census_label = QtWidgets.QLabel("")
        self.census_label.setStyleSheet("color:#8A857A;")
        lay.addWidget(self.census_label)
        self.warn_label = QtWidgets.QLabel("")
        self.warn_label.setWordWrap(True)
        self.warn_label.setStyleSheet("color:#C98A55;")
        lay.addWidget(self.warn_label)

        # context + lock
        ctx_row = QtWidgets.QHBoxLayout()
        self.scene_box = QtWidgets.QComboBox(); self.scene_box.addItems(["", "interior", "exterior", "product"])
        self.time_box = QtWidgets.QComboBox(); self.time_box.addItems(["", "dawn", "sunrise", "morning", "midday", "afternoon", "golden hour", "sunset", "dusk", "blue hour", "night"])
        self.rig_box = QtWidgets.QComboBox(); self.rig_box.addItems(["", "HDRI dome", "sun", "both"])
        for b in (self.scene_box, self.time_box, self.rig_box):
            ctx_row.addWidget(b)
        self.lock_chk = QtWidgets.QCheckBox("Lock scene globals")
        self.lock_chk.setToolTip("Per-area pass on a big project: sun/sky/fog/color mapping stay frozen; solve with camera + local lights only.")
        ctx_row.addWidget(self.lock_chk)
        lay.addLayout(ctx_row)

        # options row: consensus + diagnostics
        opt_row = QtWidgets.QHBoxLayout()
        self.consensus_chk = QtWidgets.QCheckBox("Consensus ×3")
        self.consensus_chk.setToolTip("Merge three analyses (median) for a steadier first recipe — 3× the cost & time.")
        self.consensus_chk.setChecked(self.cfg.get("consensus", False))
        self.consensus_chk.toggled.connect(lambda *_: self._save_cfg())
        opt_row.addWidget(self.consensus_chk)
        self.depth_chk = QtWidgets.QCheckBox("Cinematic depth")
        self.depth_chk.setToolTip("Measure the render's depth structure from a V-Ray Z pass (subject/background "
                                  "separation, aerial haze) and feed it to the model. Adds one extra render per "
                                  "Analyze/Check; skipped automatically if a clean Z pass can't be produced.")
        self.depth_chk.setChecked(self.cfg.get("depth", False))
        self.depth_chk.toggled.connect(lambda *_: self._save_cfg())
        opt_row.addWidget(self.depth_chk)
        opt_row.addStretch(1)
        self.diag_btn = QtWidgets.QPushButton("Run diagnostics")
        self.diag_btn.setToolTip("10-second self-test of the Max + gateway plumbing — run this first.")
        self.diag_btn.clicked.connect(self._diagnostics)
        opt_row.addWidget(self.diag_btn)
        lay.addLayout(opt_row)

        # analyze
        self.analyze_btn = QtWidgets.QPushButton("Analyze the match")
        self.analyze_btn.setObjectName("primaryBtn")  # champagne-gold primary action
        # Quiet elevation, not a glow: a soft, tight, dark drop-shadow lifts the gold button
        # off the matte surface the way a premium control sits proud. Guarded — never blocks
        # the build (Qt QSS has no box-shadow, so this is the only way to get real depth).
        try:
            lift = QtWidgets.QGraphicsDropShadowEffect(self)
            lift.setBlurRadius(18)
            lift.setColor(QtGui.QColor(0, 0, 0, 130))
            lift.setOffset(0, 3)
            self.analyze_btn.setGraphicsEffect(lift)
        except Exception:
            pass
        self.analyze_btn.clicked.connect(self._analyze)
        lay.addWidget(self.analyze_btn)

        # score line
        self.score_label = QtWidgets.QLabel("")
        f = self.score_label.font(); f.setPointSize(11); f.setBold(True)
        self.score_label.setFont(f)
        lay.addWidget(self.score_label)

        # recipe table
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["apply", "control", "from → to", "why"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 44)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 110)
        lay.addWidget(self.table, 1)

        self.withheld_label = QtWidgets.QLabel("")
        self.withheld_label.setWordWrap(True)
        self.withheld_label.setStyleSheet("color:#B7B3A8;")
        lay.addWidget(self.withheld_label)

        # apply + check
        act_row = QtWidgets.QHBoxLayout()
        self.apply_btn = QtWidgets.QPushButton("Apply checked to scene (undoable)")
        self.apply_btn.clicked.connect(self._apply)
        self.check_btn = QtWidgets.QPushButton("Re-render && Check")
        self.check_btn.clicked.connect(self._check)
        act_row.addWidget(self.apply_btn)
        act_row.addWidget(self.check_btn)
        lay.addLayout(act_row)

        # autopilot — run the whole loop unattended
        ap_row = QtWidgets.QHBoxLayout()
        self.autopilot_btn = QtWidgets.QPushButton("▶ Autopilot")
        self.autopilot_btn.setObjectName("autopilotBtn")  # mint-glass accent
        self.autopilot_btn.setToolTip("Run the refine loop unattended: render → check → apply → repeat until matched.")
        self.autopilot_btn.clicked.connect(self._autopilot)
        self.rounds_spin = QtWidgets.QSpinBox()
        self.rounds_spin.setRange(1, 12)
        self.rounds_spin.setValue(5)
        self.rounds_spin.setPrefix("max ")
        self.rounds_spin.setSuffix(" rounds")
        self.cancel_btn = QtWidgets.QPushButton("Stop")
        self.cancel_btn.setObjectName("stopBtn")  # soft-red glass
        self.cancel_btn.clicked.connect(self._cancel_autopilot)
        ap_row.addWidget(self.autopilot_btn, 1)
        ap_row.addWidget(self.rounds_spin)
        ap_row.addWidget(self.cancel_btn)
        lay.addLayout(ap_row)

        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        if not IN_MAX:
            for b in (self.grab_btn, self.render_btn, self.render_cam_btn, self.cam_refresh_btn,
                      self.save_look_btn, self.restore_look_btn, self.vantage_btn, self.autolight_chk,
                      self.apply_btn, self.check_btn, self.autopilot_btn):
                b.setEnabled(False)
            self.status.setText("Standalone preview (no pymxs) — Max-only actions disabled.")
        else:
            # In-Max first run: Apply / Check / Autopilot start disabled (no recipe yet).
            # Say WHY, so a greyed-out button reads as a next step, not a broken control.
            self.status.setText("Load a reference, grab your render, then Analyze — "
                                "Apply / Check / Autopilot unlock once a recipe is on the table.")

    def _cancel_autopilot(self):
        self._ap_cancel = True
        self.status.setText("Autopilot stopping after this round…")

    # -- helpers -------------------------------------------------------------------
    def _save_cfg(self):
        self.cfg["key"] = self.key_edit.text().strip()
        self.cfg["model"] = self.model_box.currentText()
        self.cfg["consensus"] = self.consensus_chk.isChecked()
        self.cfg["depth"] = self.depth_chk.isChecked()
        sess.save_config(self.cfg)

    def _context(self) -> dict[str, str]:
        return {"scene": self.scene_box.currentText(), "time": self.time_box.currentText(), "rig": self.rig_box.currentText()}

    def _update_buttons(self, busy: bool):
        # Reference + Analyze + Sessions are always usable (Analyze guards on inputs/key
        # itself). Sessions is disabled only while busy — swapping the session mid-run
        # would pull state out from under the worker.
        self.ref_btn.setEnabled(not busy)
        self.base_btn.setEnabled(not busy)  # file load — no Max needed, usable standalone
        self.analyze_btn.setEnabled(not busy)
        self.sessions_btn.setEnabled(not busy)
        # Lock the camera picker while busy: switching cameras mid-run would recall a
        # different slot out from under the worker (Stage 2).
        self.cam_box.setEnabled(not busy)
        # Scene I/O + diagnostics + camera rescan need Max.
        for b in (self.grab_btn, self.render_btn, self.diag_btn, self.cam_refresh_btn):
            b.setEnabled(not busy and IN_MAX)
        # Render-camera additionally needs at least one camera in the picker, so the
        # button never reads as live when there's nothing to render (matches _refresh_cameras).
        self.render_cam_btn.setEnabled(not busy and IN_MAX and self.cam_box.count() > 0)
        # Stage 3 lighting snapshots need Max; Restore additionally needs a saved look.
        self.save_look_btn.setEnabled(not busy and IN_MAX)
        self.autolight_chk.setEnabled(not busy and IN_MAX)
        # Vantage live-link start/refresh needs Max + V-Ray; usable any time the scene is idle
        # (no recipe required — it's a scene-sync action, not a match action).
        self.vantage_btn.setEnabled(not busy and IN_MAX)
        self.restore_look_btn.setEnabled(not busy and IN_MAX and bool(self._cam().get("lighting_snapshot")))
        # Apply / Check / Autopilot need Max AND a recipe on the table — disabled on
        # first open so the artist is guided to Analyze first, not into a dead-end.
        for b in (self.apply_btn, self.check_btn, self.autopilot_btn):
            b.setEnabled(not busy and IN_MAX and self._has_recipe)
        # Stop is only live while autopilot is running.
        self.cancel_btn.setEnabled(self._ap_running)

    def _busy(self, on: bool, note: str = ""):
        self._update_buttons(busy=on)
        if note:
            self.status.setText(note)

    def _need_key(self) -> bool:
        """Guard: no key → clear, actionable message + focus, and DON'T spawn a worker
        that only fails at the gateway. Returns True if blocked."""
        if not self.key_edit.text().strip():
            self.status.setText("Paste your oc_ omega key in the field at the top, then Analyze.")
            self.key_edit.setFocus()
            return True
        return False

    def _spawn(self, fn, on_done):
        # Worker runs fn() on its own QThread; results come back via signals connected
        # to bound methods of THIS widget (GUI-thread affinity) → Qt queues them across
        # the thread boundary, so the widget-touching callback never runs off the GUI
        # thread. (Connecting to a bare lambda instead runs it on the WORKER thread —
        # a latent off-thread-widget crash the offscreen UI test caught.)
        th = QtCore.QThread(self)
        wk = Worker(fn, on_done, th)
        wk.moveToThread(th)
        th.started.connect(wk.run)
        wk.done.connect(self._worker_done)
        wk.fail.connect(self._worker_fail)
        th.finished.connect(wk.deleteLater)
        # Keep BOTH the thread and the worker referenced — a local-only Worker is GC'd
        # the instant _spawn returns (before its thread runs `started → run`), so the job
        # silently never fires. Cleared in _worker_done/_worker_fail.
        wk._th = th
        th.finished.connect(lambda t=th: self._threads.remove(t) if t in self._threads else None)
        self._threads.append(th)
        self._workers.append(wk)
        th.start()

    @QtCore.Slot(object)
    def _worker_done(self, result):
        wk = self.sender()
        wk.thread_ref.quit()
        try:
            wk.on_done(result)
        finally:
            if wk in self._workers:
                self._workers.remove(wk)

    @QtCore.Slot(str)
    def _worker_fail(self, msg):
        wk = self.sender()
        wk.thread_ref.quit()
        self._ap_running = False  # any in-flight autopilot is over
        self._busy(False, msg)
        if wk in self._workers:
            self._workers.remove(wk)

    # -- actions --------------------------------------------------------------------
    def _pick_reference(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Reference image", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        try:
            from PIL import Image
            self._cam()["ref"] = sess.capture(Image.open(path))  # per active camera
            sess.save(self.session)
        except Exception as e:
            self.status.setText(f"Couldn't read that image: {e}")
            return
        self._io_note()

    def _pick_base(self):
        """Load YOUR OWN render (an image file) as the base to match — the manual path:
        you render however you like, then provide the file. No auto-render, and it works
        even outside Max (file I/O only). If a camera is picked, the base is tagged to it
        so cam-exposure moves target that camera's node."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Base render", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        try:
            from PIL import Image
            self.base_capture = sess.capture(Image.open(path))  # -> active camera's slot
            sess.save(self.session)  # your render persists with this camera
        except Exception as e:
            self.status.setText(f"Couldn't read that image: {e}")
            return
        self._io_note()

    # -- sessions: reopen past work (reference + last recipe) or start fresh -----------
    def _open_sessions(self):
        menu = QtWidgets.QMenu(self)
        menu.addAction("＋ New session").triggered.connect(self._new_session)
        items = sess.list_sessions()
        if items:
            menu.addSeparator()
        for s in items[:30]:  # newest first; cap the list so the menu stays usable
            best = s.get("best_score")
            pct = f"{match_percent(best)}% best" if isinstance(best, (int, float)) else "no score yet"
            label = f"{s.get('created', '?')}   ·   {s.get('attempts', 0)} attempt(s)   ·   {pct}"
            if s.get("cameras"):
                label += f"   · 📷 {s['cameras']}"
            if s.get("lock_globals"):
                label += "   · 🔒 area"
            sid = s.get("id", "")
            menu.addAction(label).triggered.connect(lambda _=False, i=sid: self._load_session(i))
        if not items:
            a = menu.addAction("No saved sessions yet")
            a.setEnabled(False)
        menu.popup(QtGui.QCursor.pos())  # non-blocking; actions fire via triggered

    def _new_session(self):
        self.session = sess.new_session(TARGET)
        self.session["active_camera"] = self._active_camera() or ""  # keep the picked camera
        self._has_recipe = False
        self.table.setRowCount(0)
        self.score_label.setText("")
        self.withheld_label.setText("")
        self.warn_label.setText("")
        self.census_label.setText("")
        self._io_note()
        self._update_buttons(busy=False)
        self.status.setText("New session — pick a camera, load a reference, provide your render to begin.")

    def _load_session(self, session_id: str):
        s = sess.load(session_id)  # migrated to the per-camera model on load
        if not s:
            self.status.setText("Couldn't load that session — its file is missing.")
            return
        self.session = s
        ctx = s.get("context") or {}
        self.scene_box.setCurrentText(ctx.get("scene", ""))
        self.time_box.setCurrentText(ctx.get("time", ""))
        self.rig_box.setCurrentText(ctx.get("rig", ""))
        self.lock_chk.setChecked(bool(s.get("lock_globals")))
        # Point the picker at the session's active camera WITHOUT firing a recall (we recall
        # explicitly below). If that camera isn't in the current scene's list, show it anyway
        # so the saved slot is reachable; "" selects nothing → the default slot.
        want = s.get("active_camera") or ""
        self.cam_box.blockSignals(True)
        if want and self.cam_box.findText(want) < 0:
            self.cam_box.addItem(want)
        self.cam_box.setCurrentIndex(self.cam_box.findText(want))  # -1 for "" → empty → default slot
        self.cam_box.blockSignals(False)
        # Recall the active camera's stored reference/render/recipe/score (its base persists,
        # so a saved BYO render comes back — this is the per-camera recall).
        self._recall_camera()
        self.warn_label.setText("")
        self.census_label.setText("")
        n = self._cam().get("attempt_count", 0)
        ncams = len([k for k in s.get("cameras", {}) if k])
        cam_note = f" · {ncams} camera(s)" if ncams else ""
        self.status.setText(f"Loaded session ({n} attempt(s){cam_note}) — continue where you left off.")

    def _grab(self, base: bool):
        try:
            img = maxvfb.grab_vfb()
            self.base_capture = sess.capture(img)  # capture can also fail on a bad frame
        except Exception as e:
            self.status.setText(str(e))
            return
        self._io_note()

    def _render(self, base: bool):
        # Render on the MAIN thread — pymxs is main-thread-only. This blocks the UI for
        # the render (normal for Max); processEvents lets the status paint first.
        self._busy(True, "Rendering…")
        QtWidgets.QApplication.processEvents()
        try:
            img = maxvfb.render_view()
            self.base_capture = sess.capture(img)
        except Exception as e:
            self._busy(False, str(e))
            return
        self._busy(False, "")
        self._io_note()

    # -- camera scope: pick a scene camera, render ITS view, target its exposure ---------
    def _active_camera(self) -> Optional[str]:
        # The picker is the source of truth for which camera is active; guard hasattr so a
        # base_capture access during __init__ (before _build) can't crash.
        box = getattr(self, "cam_box", None)
        name = box.currentText().strip() if box is not None else ""
        return name or None

    def _cam(self) -> dict:
        """The ACTIVE camera's session slot (Stage 2), created lazily. Everything the dock
        reads/writes per camera — ref, base, recipe, attempts — lives here. "" = the
        default slot when no camera is picked."""
        return sess.camera_slot(self.session, self._active_camera() or "")

    @property
    def base_capture(self):
        """The render you're matching, for the ACTIVE camera. Reads/writes the camera slot
        so switching cameras recalls that camera's own render (and it persists on save)."""
        return self._cam().get("base")

    @base_capture.setter
    def base_capture(self, value):
        self._cam()["base"] = value

    def _on_camera_changed(self, name: str):
        """User picked a different camera: remember it and recall THAT camera's stored
        reference/render/recipe/score into the dock. With Auto lighting OFF (default) this is
        a pure panel swap — nothing touches the scene. With it ON (Stage 3, opt-in) it also
        save-on-leaves the outgoing camera's lighting and restore-on-enters the new one."""
        new = (name or "").strip()
        prev = self.session.get("active_camera", "")
        auto = IN_MAX and self.autolight_chk.isChecked() and prev != new
        saved = self._auto_save_look(prev) if auto else False   # snapshot the camera you leave (a read)
        self.session["active_camera"] = new
        self._recall_camera()
        restored = self._auto_restore_look(new) if auto else None  # apply the one you enter (undoable)
        if auto:
            self._note_auto_lighting(prev, new, saved, restored)

    def _note_auto_lighting(self, prev, new, saved, restored):
        """Disclose what auto lighting did on this switch — the save-on-leave overwrites the
        outgoing camera's saved look, and a restore mutates the scene, so neither is silent."""
        bits = []
        if saved:
            bits.append(f"saved {prev or 'default'}'s look")
        if restored == "ok":
            bits.append(f"restored {new or 'default'}'s look (Ctrl+Z reverts)")
        elif restored == "fail":
            bits.append(f"⚠ restore of {new or 'default'} failed — Ctrl+Z to revert any partial change")
        if bits:
            self.status.setText("Auto lighting: " + " · ".join(bits) + ".")

    # -- Stage 3: per-camera lighting snapshots (save-on-leave / restore-on-enter) --------
    def _snapshot_params(self, camera_name=None):
        """Pull the scene's current lighting into a {param: value} dict (the snapshot).
        Main-thread pymxs. Returns None (never raises) outside Max or on failure.

        cam.* (ISO/f-number/shutter) is read from the target camera so the snapshot — and
        thus Save look / Restore look — references the same physical camera the moves land
        on. camera_name defaults to the ACTIVE picker (the Save-look case); pass an explicit
        name for save-on-leave, which must snapshot the OUTGOING camera even though the
        picker has already advanced to the incoming one ('' → default/first-of-kind slot)."""
        if not IN_MAX:
            return None
        cam = self._active_camera() if camera_name is None else (camera_name or None)
        try:
            return maxscene.pull_settings(cam).get("params") or {}
        except Exception:
            return None

    def _save_look(self):
        """Snapshot the scene's current lighting as the ACTIVE camera's look."""
        params = self._snapshot_params()
        if params is None:
            self.status.setText("Saving a look needs 3ds Max + V-Ray.")
            return
        if not params:  # Max reachable but nothing to snapshot — match the auto path, keep
            self.status.setText("No lighting values found to save.")  # status ↔ enablement consistent
            return
        cam = self._active_camera()
        self._cam()["lighting_snapshot"] = params
        sess.save(self.session)
        where = f"camera {cam}" if cam else "the default look"
        self.status.setText(f"Saved {len(params)} lighting value(s) as {where}'s look.")
        self._update_buttons(busy=False)  # Restore now unlocks for this camera

    def _restore_look(self):
        """Re-apply the active camera's saved lighting to the scene (one undo step)."""
        params = self._cam().get("lighting_snapshot")
        if not isinstance(params, dict) or not params:
            self.status.setText("No saved look for this camera yet — Save look first.")
            return
        rows = scope.snapshot_to_rows(params, self._active_camera())
        try:
            res = maxscene.apply_values(rows)
        except Exception as e:
            self.status.setText(str(e))
            return
        self._sync_vantage(res)  # nudge the live-link so the restored look reaches Vantage
        self.status.setText("Restored look — " + self._format_apply(res))

    def _auto_save_look(self, cam_name: str) -> bool:
        """save-on-leave: snapshot the OUTGOING camera's lighting into its slot. Returns
        True if a look was captured (so the switch can disclose the overwrite)."""
        # Scope the pull to the OUTGOING camera explicitly — the picker has already moved
        # to the incoming one, so self._active_camera() would read the wrong exposure.
        params = self._snapshot_params(cam_name)
        if params:
            sess.camera_slot(self.session, cam_name or "")["lighting_snapshot"] = params
            return True
        return False

    def _auto_restore_look(self, cam_name: str):
        """restore-on-enter: apply the INCOMING camera's saved look if it has one. Returns
        "ok"/"fail"/None so the switch can disclose a scene write (and a silent partial fail)."""
        params = sess.camera_slot(self.session, cam_name or "").get("lighting_snapshot")
        if not (isinstance(params, dict) and params):
            return None
        try:
            maxscene.apply_values(scope.snapshot_to_rows(params, cam_name or None))
            return "ok"
        except Exception:
            return "fail"

    def _recall_camera(self):
        """Load the active camera slot's recipe + score + I/O state into the dock — the
        recall-on-switch. Shared by the picker and the session loader. Non-destructive."""
        slot = self._cam()
        atts = slot.get("attempts") or []
        last_moves = atts[-1].get("correction", {}).get("moves") if atts else None
        recipe_vals = (slot.get("recipe") or {}).get("values")
        if isinstance(last_moves, list) and last_moves:
            self._fill_table(last_moves, val_key="to")
            self._has_recipe = True
        elif isinstance(recipe_vals, list) and recipe_vals:
            self._fill_table(recipe_vals, val_key="set")
            self._has_recipe = True
        else:
            self.table.setRowCount(0)
            self._has_recipe = False
        best = min((a["score"] for a in atts if isinstance(a.get("score"), (int, float))), default=None)
        if best is not None:
            self.score_label.setText(f"{match_percent(best)}% best")
            self.score_label.setStyleSheet(f"color:{AMBER};")
        else:
            self.score_label.setText("")
        self.withheld_label.setText("")
        self._io_note()
        self._update_buttons(busy=False)

    def _refresh_cameras(self):
        """Rescan the scene's cameras into the picker (MAIN thread — this runs in a GUI
        slot). Preserves the current selection if it still exists. Best-effort: outside
        Max, or on any scene-read failure, leave the picker as-is. Never raises."""
        if not IN_MAX:
            return
        try:
            cams = maxscene.list_cameras()
        except Exception:
            return
        keep = self._active_camera()
        self.cam_box.blockSignals(True)
        self.cam_box.clear()
        self.cam_box.addItems([c.get("name", "") for c in cams if c.get("name")])
        if keep is not None:
            i = self.cam_box.findText(keep)
            if i < 0:
                # The camera you're solving isn't in the rescanned scene (renamed / deleted /
                # transient). Keep it selected rather than silently jumping to another camera
                # (which would strand your per-camera work and mis-target the recipe).
                self.cam_box.addItem(keep)
                i = self.cam_box.findText(keep)
            self.cam_box.setCurrentIndex(i)
        self.cam_box.blockSignals(False)
        # Signals were blocked through the repopulate (no spurious recall), so sync the
        # session's active-camera key to whatever the widget settled on.
        self.session["active_camera"] = self._active_camera() or ""
        self.render_cam_btn.setEnabled(self.cam_box.count() > 0)

    def _render_camera(self):
        """Render the picked camera's view (main-thread, blocking) — mirrors _render(base=True)
        but points the viewport at THAT camera first, and remembers it as the session's
        active camera so cam-exposure moves get stamped onto its node."""
        name = self._active_camera()
        if not name:
            self.status.setText("Pick a camera to render.")
            return
        self._busy(True, f"Rendering {name}…")
        QtWidgets.QApplication.processEvents()
        try:
            img = maxvfb.render_camera(name)
            self.base_capture = sess.capture(img)
            self.session["active_camera"] = name
        except Exception as e:
            self._busy(False, str(e))
            return
        self._busy(False, "")
        self._io_note()

    def _io_note(self):
        slot = self._cam()
        cam = self._active_camera()
        r = "✓ reference" if slot.get("ref") else "reference missing"
        b = "✓ render" if slot.get("base") else "render missing"
        tag = f" · 📷 {cam}" if cam else ""
        self.io_label.setText(f"{r} · {b}{tag}")

    def _collect_scene(self):
        """Pull live params + full census on the MAIN thread (scene access). Returns
        (live_params, renderer, census_text, warnings). Best-effort — never raises."""
        live, renderer, census_text, warnings = None, "", None, []
        if not IN_MAX:
            return live, renderer, census_text, warnings
        try:
            # cam.* from the picked camera → Analyze's `from` exposure matches the camera
            # whose recipe we apply (stamp_camera_node targets the same node).
            pulled = maxscene.pull_settings(self._active_camera())
            live, renderer = pulled["params"], pulled["renderer"]
        except Exception:
            pass
        try:
            census = maxscene.collect_census()
            warnings = census_warnings(census)
            census_text = census_block(census)
            self.census_label.setText(summarize_for_ui(census, warnings))
        except Exception:
            pass
        self._refresh_cameras()  # keep the picker in sync with the freshly-read scene
        return live, renderer, census_text, warnings

    def _depth_text(self) -> Optional[str]:
        """Cinematic-depth prompt block (opt-in). Renders a V-Ray Z pass on the MAIN
        thread, measures the render's depth structure, and returns the prompt text — or
        None when depth is off, not in Max, or the Z pass isn't usable. NEVER raises and
        never returns partial/garbage: a bad Z read degrades to absent, not to wrong
        numbers the model would trust."""
        if not IN_MAX or not self.depth_chk.isChecked():
            return None
        try:
            pair = maxvfb.grab_depth_evidence()
            if not pair:
                return None
            lum, z = pair
            ev = depthmod.depth_evidence(lum, z)
            if not ev:
                return None
            return depthmod.depth_block(ev["bands"], ev["separation_stops"], ev["haze"])
        except Exception:
            return None

    def _show_warnings(self, warnings: list[dict]) -> bool:
        """Render pre-flight warnings; return True if a BLOCK should stop the run."""
        if not warnings:
            self.warn_label.setText("")
            return False
        lines = [("⛔ " if w["severity"] == "block" else "⚠ ") + w["message"] for w in warnings]
        self.warn_label.setText("\n".join(lines))
        return any(w["severity"] == "block" for w in warnings)

    def _analyze(self):
        slot = self._cam()
        if not slot.get("ref") or not slot.get("base"):
            cam = self._active_camera()
            where = f" for camera {cam}" if cam else ""
            self.status.setText(f"Load a reference and provide your render{where} first.")
            return
        if self._need_key():
            return
        key = self.key_edit.text().strip()
        model = self.model_box.currentText()
        lock = self.lock_chk.isChecked()
        self.session["lock_globals"] = lock
        live, renderer, census_text, warnings = self._collect_scene()
        if self._show_warnings(warnings):
            self.status.setText("Fix the blocking issue above, then Analyze.")
            return
        self.session["_census_text"] = census_text  # reused each Check/Autopilot round
        self.session["_renderer"] = renderer
        ref, base, ctx = slot.get("ref"), slot.get("base"), self._context()
        consensus = self.consensus_chk.isChecked()
        # Depth grab is a MAIN-THREAD render — do it here, before the worker spawns, and
        # pass the finished text in (like census_text). None when off / not usable.
        if self.depth_chk.isChecked() and IN_MAX:
            self._busy(True, "Rendering depth pass…")
            QtWidgets.QApplication.processEvents()
        depth_text = self._depth_text()
        self.session["_depth_on"] = bool(depth_text)
        # engine.analyze does NO pymxs (evidence + gateway + validate) — safe on a worker.
        self._busy(True, "Reading the light" + (" (consensus ×3)…" if consensus else "…"))
        # Bind THIS camera's slot into the completion handler — _collect_scene above can
        # rescan cameras, so re-resolving _cam() in _analyze_done could store the recipe on
        # a different camera than the one we analyzed (found in the Stage 2 review).
        self._spawn(
            lambda: engine.analyze(key, model, TARGET, ref, base, ctx, lock, live, renderer,
                                   census_text=census_text, consensus=consensus, depth_text=depth_text),
            lambda recipe: self._analyze_done(recipe, slot),
        )

    # -- DIAGNOSTICS: a fast self-test of the whole Max + gateway plumbing, run FIRST -
    def _diagnostics(self):
        from ..core import diagnostics
        from ..core import omega as _omega

        _cw, _sui = census_warnings, summarize_for_ui
        key = self.key_edit.text().strip()
        model = self.model_box.currentText()

        def check_deps():
            import numpy, PIL, requests  # noqa: F401
            return "numpy, Pillow, requests present"

        def check_renderer():
            name = self._run_on_main(maxscene.renderer_name)
            if "v_ray" not in name.lower().replace("-", "_"):
                raise RuntimeError(f"active renderer is {name}, not V-Ray")
            return name

        def check_pull():
            p = self._run_on_main(maxscene.pull_settings)
            return f"{len(p['params'])} params, {len(p['missing'])} missing"

        def check_census():
            c = self._run_on_main(maxscene.collect_census)
            w = _cw(c)
            blocks = [x["code"] for x in w if x["severity"] == "block"]
            if blocks:
                raise RuntimeError("blocking: " + ", ".join(blocks))
            return _sui(c, w)

        def check_apply_verify():
            # non-destructive: re-apply a param to its CURRENT value and confirm read-back.
            # Use ONLY scene-domain scalars — NOT cam.iso, whose apply force-enables camera
            # Exposure (scene.py apply_values) as a side-effect and would leave a diagnostic
            # run having silently toggled the camera's exposure ON. The plumbing test is
            # param-agnostic, so a side-effect-free scalar proves it identically. (2026-07-16 audit)
            def op():
                p = maxscene.pull_settings()["params"]
                for k in ("sun.turbidity", "sun.intensity_mult", "light.multiplier",
                          "dome.intensity", "fill.plane_intensity"):
                    if k in p and isinstance(p[k], (int, float)):
                        r = maxscene.apply_values([{"param": k, "set": p[k]}])
                        return f"{k} verified" if k in r.get("verified", []) else f"{k} applied (unverified)"
                return "no scalar param to test (scene has no sun/light)"
            return self._run_on_main(op)

        def check_marshaller():
            return "ok" if self._run_on_main(lambda: "ok") == "ok" else "FAILED"

        def check_key():
            if not key:
                return "no key yet — paste your oc_ key before Analyze"
            return _omega.ping(key, model)

        checks = [
            ("Python dependencies", check_deps),
            ("3ds Max / V-Ray reachable", check_renderer),
            ("Scene pull", check_pull),
            ("Scene census + warnings", check_census),
            ("Apply + read-back verify", check_apply_verify),
            ("Main-thread marshaller", check_marshaller),
            ("Gateway key", check_key),
        ]
        self._busy(True, "Running diagnostics…")
        self._spawn(lambda: diagnostics.run_checks(checks), self._diagnostics_done)

    def _diagnostics_done(self, results: list):
        from ..core import diagnostics
        report = diagnostics.format_report(results)
        self._busy(False, "Diagnostics complete.")
        self.warn_label.setText(report)
        self.warn_label.setStyleSheet("color:#D6BB80;" if diagnostics.all_passed(results) else "color:#C98A55;")

    def _analyze_done(self, recipe: dict, slot: Optional[dict] = None):
        (slot if slot is not None else self._cam())["recipe"] = recipe  # the camera we analyzed
        sess.save(self.session)
        values = recipe.get("values", [])
        withheld = recipe.get("withheld_globals") or []
        self._fill_table(values, val_key="set")
        if not values:
            # valid JSON, zero applicable controls — not a silent green dead-end.
            self._has_recipe = False
            note = "The model proposed no applicable moves"
            if withheld:
                note += " (all its moves were scene-globals, withheld by the lock)"
            self._busy(False, note + " — try Analyze again, or set the scene context.")
        else:
            self._has_recipe = True
            self._busy(False, "Recipe ready — untick anything you don't want, then Apply.")
        self.withheld_label.setText(
            f"{len(withheld)} scene-global move(s) withheld — globals locked: "
            + " · ".join(f"{w['param']} → {w['set']}" for w in withheld)
            if withheld else ""
        )

    def _fill_table(self, rows: list[dict], val_key: str):
        self.table.setRowCount(0)
        for v in rows:
            entry = data.lookup(TARGET, v.get("param", "")) or {}
            r = self.table.rowCount()
            self.table.insertRow(r)
            chk = QtWidgets.QTableWidgetItem()
            chk.setCheckState(QtCore.Qt.Checked)
            chk.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
            self.table.setItem(r, 0, chk)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(entry.get("ui_path", v.get("param", ""))))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(f"{v.get('from', '')} → {v.get(val_key, '')}"))
            self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(str(v.get("why", ""))))
            row = {"param": v.get("param"), "set": v.get(val_key)}
            if isinstance(v.get("node"), str) and v.get("node"):
                row["node"] = v["node"]  # per-fixture targeting survives to Apply
            self.table.item(r, 1).setData(QtCore.Qt.UserRole, row)

    def _checked_values(self) -> list[dict]:
        out = []
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).checkState() == QtCore.Qt.Checked:
                out.append(self.table.item(r, 1).data(QtCore.Qt.UserRole))
        # B1: stamp cam-exposure moves onto the picked camera's exact node before Apply.
        return scope.stamp_camera_node(out, self._active_camera())

    def _format_apply(self, res: dict) -> str:
        bits = [f"applied {len(res.get('applied', []))}"]
        unverified = res.get("unverified") or []
        if unverified:
            bits.append(f"⚠ NOT VERIFIED (something is overriding these): {', '.join(unverified)}")
        if res.get("failed"):
            bits.append(f"failed: {', '.join(res['failed'])}")
        if res.get("manual"):
            bits.append(f"set by hand: {', '.join(res['manual'])}")
        if res.get("vfb_only"):
            bits.append(f"⚠ V-Ray-render only (won't show in Chaos Vantage): {', '.join(res['vfb_only'])}")
        # Tell the user whether their SCENE-domain changes are actually reaching Vantage. The
        # live-link is a running V-Ray GPU IPR — if it isn't running, that is WHY 'nothing
        # changed in Vantage'. Only mention it when there's a Vantage-visible change to sync.
        scene_moves = [p for p in res.get("applied", []) if p not in set(res.get("vfb_only") or [])]
        if scene_moves:
            if maxscene.livelink_active():
                bits.append(f"✓ Chaos Vantage live-link active — {len(scene_moves)} scene change(s) streaming")
            else:
                bits.append("○ Chaos Vantage live-link not running — start it (V-Ray ▸ Chaos Vantage) to see these live")
        return " · ".join(bits) + " — one undo step."

    def _sync_vantage(self, res: dict) -> None:
        """On a deliberate Apply/Restore, if a Vantage live-link is running and this changed
        scene-domain nodes, restart the link so the change reliably propagates — Chaos' own
        recommended fix for DCC changes (lighting especially) that don't auto-stream. Best-
        effort and main-thread (pymxs); never disturbs the apply result. NOT used in the
        autopilot loop (a per-round link restart would be disruptive)."""
        if not [p for p in res.get("applied", []) if p not in set(res.get("vfb_only") or [])]:
            return
        try:
            self._run_on_main(maxscene.refresh_livelink)
        except Exception:
            pass

    def _vantage_clicked(self):
        """One click: START the Chaos Vantage live-link if it isn't running, or REFRESH it if
        it is (so a lighting change that didn't auto-stream gets pushed). All pymxs → main
        thread; best-effort, never throws out to the UI."""
        try:
            if self._run_on_main(maxscene.livelink_active):
                res = self._run_on_main(maxscene.refresh_livelink)
                self.status.setText({
                    "refreshed": "↻ Refreshed the Chaos Vantage live-link — your latest changes are pushed to Vantage.",
                    "not_active": "Chaos Vantage live-link isn't running — click again to start it.",
                    "unavailable": "Couldn't refresh the live-link — restart it via the V-Ray toolbar ▸ Chaos Vantage.",
                }.get(res, f"Vantage live-link: {res}"))
                return
            res = self._run_on_main(maxscene.start_livelink)
        except Exception as e:
            self.status.setText(f"Vantage live-link: {e}")
            return
        self.status.setText({
            "already_active": "✓ Chaos Vantage live-link is already running — your changes are streaming.",
            "started": "✓ Started the Chaos Vantage live-link — Vantage is launching; changes will stream live.",
            "needs_gpu": "Switch the renderer to V-Ray GPU — the Chaos Vantage live-link is GPU-only.",
            "no_vray": "Set the renderer to V-Ray GPU first — the Chaos Vantage live-link is a V-Ray feature.",
            "unavailable": "Start the live-link from the V-Ray toolbar ▸ Chaos Vantage (not scriptable in this session).",
        }.get(res, f"Vantage live-link: {res}"))

    def _apply(self):
        values = self._checked_values()
        if not values:
            self.status.setText("Nothing checked.")
            return
        try:
            res = maxscene.apply_values(values)
        except Exception as e:
            self.status.setText(str(e))
            return
        self._sync_vantage(res)  # nudge the live-link so the change reaches Vantage
        self.status.setText(self._format_apply(res))

    def _check(self):
        slot = self._cam()
        if not slot.get("ref"):
            self.status.setText("Load a reference first.")
            return
        if self._need_key():
            return
        key = self.key_edit.text().strip()
        model = self.model_box.currentText()
        lock = self.lock_chk.isChecked()
        ctx = self._context()
        ref = slot.get("ref")
        n = int(slot.get("attempt_count", 0)) + 1
        history = sess.history_rounds(slot)
        # Pull + render on the MAIN thread (pymxs). Render FRESH — you just applied the
        # recipe, so the scene changed; grabbing the old VFB would score the pre-apply
        # frame and make Apply look like it did nothing (found 2026-07-13).
        live, renderer = None, ""
        try:
            # Same camera as the moves we stamp/apply below (_checked_values →
            # stamp_camera_node(self._active_camera())) so the refine `from` is honest.
            pulled = maxscene.pull_settings(self._active_camera())
            live, renderer = pulled["params"], pulled["renderer"]
        except Exception:
            pass
        self._busy(True, f"Rendering attempt {n}…")
        QtWidgets.QApplication.processEvents()
        try:
            # Render the PICKED camera (matches the pull/stamp on _active_camera), not the
            # active viewport — else the scored frame is the wrong view and never reflects
            # the applied cam.* moves, so the loop can't converge (2026-07-15 audit).
            _pick = self._active_camera()
            img = maxvfb.render_camera(_pick) if _pick else maxvfb.render_view()  # fresh — Apply changed the scene
            attempt = sess.capture(img)
        except Exception as e:
            self._busy(False, f"Render failed: {e}")
            return

        census_text = self.session.get("_census_text")
        # Depth pass (main-thread render), when opted in — same as Analyze.
        depth_text = self._depth_text()
        # Only the gateway round runs on the worker (no pymxs here).
        self._busy(True, f"Checking attempt {n}…")
        self._spawn(
            lambda: engine.add_attempt(key, model, TARGET, ref, attempt, n, history, ctx,
                                       lock, live, renderer, census_text=census_text,
                                       depth_text=depth_text),
            self._check_done,
        )

    # -- AUTOPILOT: run the whole refine loop unattended -----------------------------
    def _autopilot(self):
        # Bind the ACTIVE camera's slot for the whole run — autopilot refines ONE camera,
        # even if the picker is changed mid-loop.
        slot = self._cam()
        # Guard the reference BEFORE spawning the worker — every refine round scores against
        # `ref`, so a recipe-carrying-but-reference-less slot (e.g. a hand-ported/legacy
        # session) would otherwise burn a render and fail deep in the worker. Mirror the
        # _check()/_analyze() guard (2026-07-16 stress audit).
        if not slot.get("ref"):
            self.status.setText("Load a reference first — Autopilot scores each round against it.")
            return
        if not slot.get("recipe") or not self._has_recipe:
            self.status.setText("Analyze first — Autopilot then refines the recipe for you.")
            return
        if self._need_key():
            return
        key = self.key_edit.text().strip()
        model = self.model_box.currentText()
        lock = self.lock_chk.isChecked()
        ctx = self._context()
        ref = slot.get("ref")
        census_text = self.session.get("_census_text")
        renderer = self.session.get("_renderer", "")
        rounds = int(self.rounds_spin.value())
        self._ap_cancel = False
        self._ap_running = True

        # run_autopilot runs on a worker (the gateway rounds must stay off the GUI
        # thread), but EVERY pymxs op is marshalled onto the main thread via _run_on_main
        # — pymxs is main-thread-only.
        def render_cb():
            # Render the PICKED camera (matches correct_cb's pull and apply_cb's stamp on
            # _active_camera), not the active viewport — else the scored frame never
            # reflects the cam.* moves and the loop can't converge (2026-07-15 audit).
            _pick = self._active_camera()
            return self._run_on_main(
                lambda: sess.capture(maxvfb.render_camera(_pick) if _pick else maxvfb.render_view())
            )

        def correct_cb(cap, n):
            live = None
            try:
                # Pull the picked camera's exposure so it matches apply_cb, which stamps
                # cam.* onto self._active_camera() — keeps pull and apply on one camera.
                live = self._run_on_main(lambda: maxscene.pull_settings(self._active_camera())["params"])
            except Exception:
                pass
            attempt_n = int(slot.get("attempt_count", 0)) + 1
            score, corr = engine.add_attempt(  # network — stays on the worker
                key, model, TARGET, ref, cap, attempt_n, sess.history_rounds(slot),
                ctx, lock, live, renderer, census_text=census_text,
            )
            sess.push_attempt(slot, score, corr)  # so this camera's history grows each round
            return score, corr

        def apply_cb(moves):
            # B1: stamp cam-exposure moves onto the picked camera's node in the loop too.
            return self._run_on_main(
                lambda: maxscene.apply_values(scope.stamp_camera_node(moves, self._active_camera()))
            )

        # KEEP-BEST seams: snapshot the current lighting, and restore a snapshot. Reuse the
        # exact Save-look / Restore-look machinery so the loop can roll the scene back to the
        # best-scoring round instead of leaving it wherever it stopped.
        def snapshot_cb():
            return self._run_on_main(self._snapshot_params)

        def restore_cb(snap):
            if not isinstance(snap, dict) or not snap:
                return None
            return self._run_on_main(
                lambda: maxscene.apply_values(scope.snapshot_to_rows(snap, self._active_camera()))
            )

        self._busy(True, f"Autopilot: up to {rounds} rounds…")
        self._update_buttons(busy=True)  # enables Stop (via _ap_running)
        self._spawn(
            lambda: autopilot.run_autopilot(
                rounds=rounds, render_cb=render_cb, correct_cb=correct_cb, apply_cb=apply_cb,
                on_round=lambda row: self.apRow.emit(row),
                should_stop=lambda: self._ap_cancel,
                snapshot_cb=snapshot_cb, restore_cb=restore_cb,
            ),
            self._autopilot_done,
        )

    @QtCore.Slot(dict)
    def _ap_row(self, row: dict):
        self.status.setText(
            f"Autopilot round {row['n']}: {row['match_percent']}% · "
            + (row.get("status_reason") or "")
        )

    def _autopilot_done(self, result: dict):
        self._ap_running = False
        sess.save(self.session)
        best = result.get("best_match_percent")
        reason = result.get("stop_reason", "")
        if reason.startswith("error:"):
            msg = "error — " + (result.get("error_message") or reason.split(":", 1)[-1])
        else:
            msg = {
                "matched": "MATCHED — stop lighting, move to grading.",
                "budget": "round budget reached.",
                "oscillating": "stopped — the score was not settling.",
                "no_moves": "no further moves proposed.",
                "cancelled": "cancelled.",
            }.get(reason, reason)
        nr = len(result.get("rounds", []))
        best_txt = f"{best}% best" if best is not None else "no score"
        self._busy(False, f"Autopilot done ({nr} round{'s' if nr != 1 else ''}, {best_txt}): {msg}")
        if best is not None:
            matched = result.get("matched")
            self.score_label.setText(
                (f"{best}% — LIGHTING MATCHED" if matched else f"{best}% best match") + f" · {msg}"
            )
            self.score_label.setStyleSheet("color:#D6BB80;" if matched else f"color:{AMBER};")
        # Push the FINAL (best-scoring) scene to Vantage: the keep-best restore + each round's
        # apply wrote nodes directly, bypassing the per-apply nudge, so refresh the live-link
        # once here (best-effort) if it's running — so Vantage ends on the matched look.
        if len(result.get("rounds", [])):
            try:
                self._run_on_main(maxscene.refresh_livelink)
            except Exception:
                pass

    def _check_done(self, result):
        score, correction = result
        sess.push_attempt(self._cam(), score, correction)  # attempt belongs to the active camera
        sess.save(self.session)
        pct = match_percent(score)
        moves = correction.get("moves", [])
        self._fill_table(moves, val_key="to")
        if engine.matched(score):
            self.score_label.setText(f"{pct}% — LIGHTING MATCHED · stop lighting, move to grading")
            self.score_label.setStyleSheet("color:#D6BB80;")
            self._has_recipe = bool(moves)
            self._busy(False, "Matched. If you want to keep going, apply any remaining moves and Check again.")
        elif not moves:
            self._has_recipe = False
            self._busy(False, f"{pct}% match, but the model proposed no further moves — try Check again.")
        else:
            self.score_label.setText(f"{pct}% match · look distance {score:.1f}")
            self.score_label.setStyleSheet(f"color:{AMBER};")
            self._has_recipe = True
            self._busy(False, correction.get("status_reason", "Apply the moves, then Check again."))
        withheld = correction.get("withheld_globals") or []
        self.withheld_label.setText(
            f"{len(withheld)} scene-global move(s) withheld — globals locked."
            if withheld else ""
        )

    # -- clean shutdown: cancel any run and JOIN every worker thread before the widget
    # (and, in tests, the QApplication) is torn down. A QThread still running — or a
    # QThread object destroyed while its OS thread lives — is an access-violation crash
    # at interpreter teardown (found 2026-07-13; pytest passed but the process aborted).
    def _shutdown(self):
        self._ap_cancel = True
        for th in list(self._threads):
            try:
                th.quit()
                th.wait(3000)
            except Exception:
                pass
        self._threads.clear()
        self._workers.clear()
        try:
            QtWidgets.QApplication.processEvents()  # flush pending deleteLater
        except Exception:
            pass

    def closeEvent(self, event):
        self._shutdown()
        super().closeEvent(event)


_dock_instance: Optional[LightMatchDock] = None


def show_dock():
    """Entry point — inside Max, parent to the Max main window; standalone, run a
    plain Qt app for UI development."""
    global _dock_instance
    parent = None
    try:
        from qtmax import GetQMaxMainWindow  # type: ignore
        parent = GetQMaxMainWindow()
    except Exception:
        parent = None
    _dock_instance = LightMatchDock(parent)
    if parent is not None:
        _dock_instance.setWindowFlag(QtCore.Qt.Tool, True)
    _dock_instance.show()
    return _dock_instance
