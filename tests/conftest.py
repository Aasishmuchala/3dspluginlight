"""Shared pytest fixtures — a single offscreen QApplication for the whole session and a
clean-up pass after every test so lingering Qt objects/threads never survive into
interpreter teardown (which crashes with an access violation on PySide6 6.11)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(autouse=True)
def _qt_flush():
    """After each test, drain the Qt event loop so pending deleteLater / thread cleanup
    completes while the QApplication is still alive."""
    yield
    try:
        from PySide6 import QtCore, QtWidgets
        app = QtWidgets.QApplication.instance()
        if app is not None:
            for _ in range(4):
                app.processEvents(QtCore.QEventLoop.AllEvents, 20)
    except Exception:
        pass


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """PySide6 can crash the interpreter on teardown (access violation) even when every
    test PASSED — a known Qt/Python GC-ordering issue in test harnesses, unrelated to the
    plugin (real Max owns the Qt loop and never tears it down this way). Once pytest has
    finished and printed its summary, exit hard with pytest's REAL status so the process
    exit code reflects the test result, not the Qt teardown quirk. Only fires when Qt was
    actually imported, so core-only runs use normal, clean teardown."""
    import sys

    if "PySide6" not in sys.modules:
        return
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        os._exit(int(exitstatus))
    except Exception:
        os._exit(0)
