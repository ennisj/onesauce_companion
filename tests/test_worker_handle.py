from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from onesauce_companion.ui._worker_handle import WorkerHandle


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _EchoWorker(QObject):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, result: str = "done", fail: bool = False) -> None:
        super().__init__()
        self._result = result
        self._fail = fail

    @Slot()
    def run(self) -> None:
        if self._fail:
            self.error.emit(self._result)
        else:
            self.finished.emit(self._result)


def _wait_until(condition, timeout_ms: int = 5000) -> bool:
    from PySide6.QtCore import QElapsedTimer, QEventLoop, QTimer

    timer = QElapsedTimer()
    timer.start()
    while not condition():
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()
        if timer.hasExpired(timeout_ms):
            return False
    return True


def test_worker_handle_runs_worker_and_clears_refs() -> None:
    app = _app()
    handle = WorkerHandle(app)
    worker = _EchoWorker("payload")
    results: list[str] = []
    cleared: list[bool] = []
    worker.finished.connect(results.append)

    handle.start(
        worker,
        finish_signals=(worker.finished, worker.error),
        on_cleared=lambda: cleared.append(True),
    )

    assert handle.worker is worker
    assert _wait_until(lambda: bool(cleared))
    assert results == ["payload"]
    assert handle.running is False
    assert handle.worker is None


def test_worker_handle_error_signal_also_finishes_thread() -> None:
    app = _app()
    handle = WorkerHandle(app)
    worker = _EchoWorker("boom", fail=True)
    errors: list[str] = []
    cleared: list[bool] = []
    worker.error.connect(errors.append)

    handle.start(
        worker,
        finish_signals=(worker.finished, worker.error),
        on_cleared=lambda: cleared.append(True),
    )

    assert _wait_until(lambda: bool(cleared))
    assert errors == ["boom"]
    assert handle.running is False


def test_worker_handle_is_reusable_for_sequential_runs() -> None:
    app = _app()
    handle = WorkerHandle(app)
    for expected in ("first", "second"):
        worker = _EchoWorker(expected)
        spy = QSignalSpy(worker.finished)
        cleared: list[bool] = []
        handle.start(
            worker,
            finish_signals=(worker.finished,),
            on_cleared=lambda done=cleared: done.append(True),
        )
        assert _wait_until(lambda done=cleared: bool(done))
        assert spy.count() == 1
        assert spy.at(0) == [expected]
        assert handle.running is False
