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

from ..core import autopilot, data, engine, session as sess
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
AMBER = "#e2a13a"


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
    apRow = QtCore.Signal(dict)  # autopilot per-round progress (worker → GUI thread)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LightMatch")
        self.setMinimumWidth(380)
        self.session = sess.new_session(TARGET)
        self.base_capture: Optional[dict] = None
        self.cfg = sess.load_config()
        self._threads: list[QtCore.QThread] = []
        self._workers: list[QtCore.QObject] = []
        self._ap_cancel = False
        self._build()
        self.apRow.connect(self._ap_row)

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

        # scene census summary + pre-flight warnings (populated on Analyze)
        self.census_label = QtWidgets.QLabel("")
        self.census_label.setStyleSheet("color:#8a8a8a;")
        lay.addWidget(self.census_label)
        self.warn_label = QtWidgets.QLabel("")
        self.warn_label.setWordWrap(True)
        self.warn_label.setStyleSheet("color:#c47a2a;")
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

        # autopilot — run the whole loop unattended
        ap_row = QtWidgets.QHBoxLayout()
        self.autopilot_btn = QtWidgets.QPushButton("▶ Autopilot")
        self.autopilot_btn.setToolTip("Run the refine loop unattended: render → check → apply → repeat until matched.")
        self.autopilot_btn.clicked.connect(self._autopilot)
        self.rounds_spin = QtWidgets.QSpinBox()
        self.rounds_spin.setRange(1, 12)
        self.rounds_spin.setValue(5)
        self.rounds_spin.setPrefix("max ")
        self.rounds_spin.setSuffix(" rounds")
        self.cancel_btn = QtWidgets.QPushButton("Stop")
        self.cancel_btn.clicked.connect(self._cancel_autopilot)
        ap_row.addWidget(self.autopilot_btn, 1)
        ap_row.addWidget(self.rounds_spin)
        ap_row.addWidget(self.cancel_btn)
        lay.addLayout(ap_row)

        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        if not IN_MAX:
            for b in (self.grab_btn, self.render_btn, self.apply_btn, self.check_btn, self.autopilot_btn):
                b.setEnabled(False)
            self.status.setText("Standalone preview (no pymxs) — Max-only actions disabled.")

    def _cancel_autopilot(self):
        self._ap_cancel = True
        self.status.setText("Autopilot stopping after this round…")

    # -- helpers -------------------------------------------------------------------
    def _save_cfg(self):
        self.cfg["key"] = self.key_edit.text().strip()
        self.cfg["model"] = self.model_box.currentText()
        sess.save_config(self.cfg)

    def _context(self) -> dict[str, str]:
        return {"scene": self.scene_box.currentText(), "time": self.time_box.currentText(), "rig": self.rig_box.currentText()}

    def _busy(self, on: bool, note: str = ""):
        for b in (self.analyze_btn, self.apply_btn, self.check_btn, self.grab_btn,
                  self.render_btn, self.ref_btn, self.autopilot_btn):
            b.setEnabled(not on and (IN_MAX or b in (self.analyze_btn, self.ref_btn)))
        self.status.setText(note)

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
        self._busy(False, msg)
        if wk in self._workers:
            self._workers.remove(wk)

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

    def _collect_scene(self):
        """Pull live params + full census on the MAIN thread (scene access). Returns
        (live_params, renderer, census_text, warnings). Best-effort — never raises."""
        live, renderer, census_text, warnings = None, "", None, []
        if not IN_MAX:
            return live, renderer, census_text, warnings
        try:
            pulled = maxscene.pull_settings()
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
        return live, renderer, census_text, warnings

    def _show_warnings(self, warnings: list[dict]) -> bool:
        """Render pre-flight warnings; return True if a BLOCK should stop the run."""
        if not warnings:
            self.warn_label.setText("")
            return False
        lines = [("⛔ " if w["severity"] == "block" else "⚠ ") + w["message"] for w in warnings]
        self.warn_label.setText("\n".join(lines))
        return any(w["severity"] == "block" for w in warnings)

    def _analyze(self):
        if not self.session.get("ref") or not self.base_capture:
            self.status.setText("Load a reference and grab a render first.")
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
        ref, base, ctx = self.session["ref"], self.base_capture, self._context()
        self._busy(True, "Reading the light…")
        self._spawn(
            lambda: engine.analyze(key, model, TARGET, ref, base, ctx, lock, live, renderer,
                                   census_text=census_text),
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
            row = {"param": v.get("param"), "set": v.get(val_key)}
            if isinstance(v.get("node"), str) and v.get("node"):
                row["node"] = v["node"]  # per-fixture targeting survives to Apply
            self.table.item(r, 1).setData(QtCore.Qt.UserRole, row)

    def _checked_values(self) -> list[dict]:
        out = []
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).checkState() == QtCore.Qt.Checked:
                out.append(self.table.item(r, 1).data(QtCore.Qt.UserRole))
        return out

    def _format_apply(self, res: dict) -> str:
        bits = [f"applied {len(res.get('applied', []))}"]
        unverified = res.get("unverified") or []
        if unverified:
            bits.append(f"⚠ NOT VERIFIED (something is overriding these): {', '.join(unverified)}")
        if res.get("failed"):
            bits.append(f"failed: {', '.join(res['failed'])}")
        if res.get("manual"):
            bits.append(f"set by hand: {', '.join(res['manual'])}")
        return " · ".join(bits) + " — one undo step."

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
        self.status.setText(self._format_apply(res))

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

        census_text = self.session.get("_census_text")

        def job():
            # Ease-of-use: the artist has usually JUST rendered in the VFB — grab that
            # frame rather than forcing a second render; fall back to a fresh render
            # only when the VFB is empty/unavailable.
            try:
                img = maxvfb.grab_vfb()
            except Exception:
                img = maxvfb.render_view()
            attempt = sess.capture(img)
            score, correction = engine.add_attempt(
                key, model, TARGET, ref, attempt, n, history, ctx, lock, live, renderer,
                census_text=census_text,
            )
            return score, correction

        self._busy(True, f"Checking attempt {n} (grabbing the VFB, rendering if empty)…")
        self._spawn(job, self._check_done)

    # -- AUTOPILOT: run the whole refine loop unattended -----------------------------
    def _autopilot(self):
        if not self.session.get("recipe"):
            self.status.setText("Analyze and apply a recipe first, then Autopilot refines it.")
            return
        key = self.key_edit.text().strip()
        model = self.model_box.currentText()
        lock = self.lock_chk.isChecked()
        ctx = self._context()
        ref = self.session["ref"]
        census_text = self.session.get("_census_text")
        renderer = self.session.get("_renderer", "")
        rounds = int(self.rounds_spin.value())
        self._ap_cancel = False

        def render_cb():
            return sess.capture(maxvfb.render_view())

        def correct_cb(cap, n):
            live = None
            try:
                live = maxscene.pull_settings()["params"]
            except Exception:
                pass
            attempt_n = int(self.session.get("attempt_count", 0)) + 1
            score, corr = engine.add_attempt(
                key, model, TARGET, ref, cap, attempt_n, sess.history_rounds(self.session),
                ctx, lock, live, renderer, census_text=census_text,
            )
            sess.push_attempt(self.session, score, corr)  # so history grows each round
            return score, corr

        def apply_cb(moves):
            return maxscene.apply_values(moves)

        self._busy(True, f"Autopilot: up to {rounds} rounds…")
        self._spawn(
            lambda: autopilot.run_autopilot(
                rounds=rounds, render_cb=render_cb, correct_cb=correct_cb, apply_cb=apply_cb,
                on_round=lambda row: self.apRow.emit(row),
                should_stop=lambda: self._ap_cancel,
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
        sess.save(self.session)
        pct = result.get("final_match_percent")
        reason = result.get("stop_reason", "")
        msg = {
            "matched": "MATCHED — stop lighting, move to grading.",
            "budget": "round budget reached.",
            "oscillating": "stopped — the score was not settling.",
            "no_moves": "no further moves proposed.",
            "cancelled": "cancelled.",
        }.get(reason, reason)
        self._busy(False, f"Autopilot done ({len(result.get('rounds', []))} rounds, {pct}% best): {msg}")
        if pct is not None:
            matched = result.get("matched")
            self.score_label.setText(
                (f"{pct}% — LIGHTING MATCHED" if matched else f"{pct}% match") + f" · autopilot: {msg}"
            )
            self.score_label.setStyleSheet("color:#2e8f5b;" if matched else f"color:{AMBER};")

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
