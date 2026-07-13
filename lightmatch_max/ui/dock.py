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

from ..core import data, engine, session as sess
from ..core.metrics import match_percent
from ..core.omega import DEFAULT_MODEL, OmegaError

try:  # inside Max
    from ..maxio import scene as maxscene
    from ..maxio import vfb as maxvfb
    IN_MAX = True
except Exception:  # standalone dev preview
    maxscene = None  # type: ignore
    maxvfb = None  # type: ignore
    IN_MAX = False

TARGET = "vray7max"
AMBER = "#e2a13a"


class Worker(QtCore.QObject):
    done = QtCore.Signal(object)
    fail = QtCore.Signal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except OmegaError as e:
            self.fail.emit(str(e))
        except Exception as e:  # surface anything — never a silent dead button
            self.fail.emit(f"{e}\n{traceback.format_exc(limit=3)}")


class LightMatchDock(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LightMatch")
        self.setMinimumWidth(380)
        self.session = sess.new_session(TARGET)
        self.base_capture: Optional[dict] = None
        self.cfg = sess.load_config()
        self._threads: list[QtCore.QThread] = []
        self._build()

    # -- UI scaffold -------------------------------------------------------------
    def _build(self):
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

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
        self.ref_btn.clicked.connect(self._pick_reference)
        self.grab_btn = QtWidgets.QPushButton("Grab VFB")
        self.grab_btn.clicked.connect(lambda: self._grab(base=True))
        self.render_btn = QtWidgets.QPushButton("Render view")
        self.render_btn.clicked.connect(lambda: self._render(base=True))
        io_row.addWidget(self.ref_btn)
        io_row.addWidget(self.grab_btn)
        io_row.addWidget(self.render_btn)
        lay.addLayout(io_row)

        self.io_label = QtWidgets.QLabel("Load a reference, then grab your current render.")
        self.io_label.setWordWrap(True)
        lay.addWidget(self.io_label)

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

        # analyze
        self.analyze_btn = QtWidgets.QPushButton("Analyze the match")
        self.analyze_btn.setStyleSheet(f"font-weight:600;background:{AMBER};color:#232323;padding:6px;")
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
        self.withheld_label.setStyleSheet("color:#5f7f9f;")
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

        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        if not IN_MAX:
            self.grab_btn.setEnabled(False)
            self.render_btn.setEnabled(False)
            self.apply_btn.setEnabled(False)
            self.check_btn.setEnabled(False)
            self.status.setText("Standalone preview (no pymxs) — Max-only actions disabled.")

    # -- helpers -------------------------------------------------------------------
    def _save_cfg(self):
        self.cfg["key"] = self.key_edit.text().strip()
        self.cfg["model"] = self.model_box.currentText()
        sess.save_config(self.cfg)

    def _context(self) -> dict[str, str]:
        return {"scene": self.scene_box.currentText(), "time": self.time_box.currentText(), "rig": self.rig_box.currentText()}

    def _busy(self, on: bool, note: str = ""):
        for b in (self.analyze_btn, self.apply_btn, self.check_btn, self.grab_btn, self.render_btn, self.ref_btn):
            b.setEnabled(not on and (IN_MAX or b in (self.analyze_btn, self.ref_btn)))
        self.status.setText(note)

    def _spawn(self, fn, on_done):
        th = QtCore.QThread(self)
        wk = Worker(fn)
        wk.moveToThread(th)
        th.started.connect(wk.run)
        wk.done.connect(lambda r: (on_done(r), th.quit()))
        wk.fail.connect(lambda m: (self._busy(False, m), th.quit()))
        self._threads.append(th)
        th.start()

    # -- actions --------------------------------------------------------------------
    def _pick_reference(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Reference image", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        from PIL import Image
        self.session["ref"] = sess.capture(Image.open(path))
        sess.save(self.session)
        self._io_note()

    def _grab(self, base: bool):
        try:
            img = maxvfb.grab_vfb()
        except Exception as e:
            self.status.setText(str(e))
            return
        self.base_capture = sess.capture(img)
        self._io_note()

    def _render(self, base: bool):
        self._busy(True, "Rendering…")
        self._spawn(lambda: maxvfb.render_view(), self._render_done)

    def _render_done(self, img):
        self.base_capture = sess.capture(img)
        self._busy(False, "")
        self._io_note()

    def _io_note(self):
        r = "✓ reference" if self.session.get("ref") else "reference missing"
        b = "✓ render" if self.base_capture else "render missing"
        self.io_label.setText(f"{r} · {b}")

    def _analyze(self):
        if not self.session.get("ref") or not self.base_capture:
            self.status.setText("Load a reference and grab a render first.")
            return
        key = self.key_edit.text().strip()
        model = self.model_box.currentText()
        lock = self.lock_chk.isChecked()
        self.session["lock_globals"] = lock
        live = None
        renderer = ""
        if IN_MAX:
            try:
                pulled = maxscene.pull_settings()
                live, renderer = pulled["params"], pulled["renderer"]
            except Exception:
                pass
        ref, base, ctx = self.session["ref"], self.base_capture, self._context()
        self._busy(True, "Reading the light…")
        self._spawn(
            lambda: engine.analyze(key, model, TARGET, ref, base, ctx, lock, live, renderer),
            self._analyze_done,
        )

    def _analyze_done(self, recipe: dict):
        self.session["recipe"] = recipe
        sess.save(self.session)
        self._busy(False, "Recipe ready — check the rows you'll take, then Apply.")
        self._fill_table(recipe.get("values", []), val_key="set")
        withheld = recipe.get("withheld_globals") or []
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
            self.table.item(r, 1).setData(QtCore.Qt.UserRole, {"param": v.get("param"), "set": v.get(val_key)})

    def _checked_values(self) -> list[dict]:
        out = []
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).checkState() == QtCore.Qt.Checked:
                out.append(self.table.item(r, 1).data(QtCore.Qt.UserRole))
        return out

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
        bits = [f"applied {len(res['applied'])}"]
        if res["failed"]:
            bits.append(f"failed: {', '.join(res['failed'])}")
        if res["manual"]:
            bits.append(f"set by hand: {', '.join(res['manual'])}")
        self.status.setText(" · ".join(bits) + " — one undo step.")

    def _check(self):
        if not self.session.get("ref"):
            self.status.setText("Load a reference first.")
            return
        key = self.key_edit.text().strip()
        model = self.model_box.currentText()
        lock = self.lock_chk.isChecked()
        ctx = self._context()
        ref = self.session["ref"]
        n = int(self.session.get("attempt_count", 0)) + 1
        history = sess.history_rounds(self.session)
        live = None
        renderer = ""
        try:
            pulled = maxscene.pull_settings()
            live, renderer = pulled["params"], pulled["renderer"]
        except Exception:
            pass

        def job():
            img = maxvfb.render_view()
            attempt = sess.capture(img)
            score, correction = engine.add_attempt(
                key, model, TARGET, ref, attempt, n, history, ctx, lock, live, renderer
            )
            return score, correction

        self._busy(True, f"Rendering attempt {n} and checking…")
        self._spawn(job, self._check_done)

    def _check_done(self, result):
        score, correction = result
        sess.push_attempt(self.session, score, correction)
        sess.save(self.session)
        pct = match_percent(score)
        if engine.matched(score):
            self.score_label.setText(f"{pct}% — LIGHTING MATCHED · stop lighting, move to grading")
            self.score_label.setStyleSheet("color:#2e8f5b;")
        else:
            self.score_label.setText(f"{pct}% match · look distance {score:.1f}")
            self.score_label.setStyleSheet(f"color:{AMBER};")
        self._busy(False, correction.get("status_reason", ""))
        self._fill_table(correction.get("moves", []), val_key="to")
        withheld = correction.get("withheld_globals") or []
        self.withheld_label.setText(
            f"{len(withheld)} scene-global move(s) withheld — globals locked."
            if withheld else ""
        )


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
