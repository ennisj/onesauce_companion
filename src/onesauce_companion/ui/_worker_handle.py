"""Lifecycle wrapper for one background QThread/worker pair."""
from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import QObject, QThread, SignalInstance, Slot


class WorkerHandle(QObject):
    """Owns a background QThread/worker pair and its lifecycle wiring.

    ``start()`` moves the worker onto a fresh thread, connects each finish
    signal to the thread's quit slot, and clears the references once the
    thread has finished, invoking ``on_cleared`` on the GUI thread. This
    replaces the hand-written ``_x_thread``/``_x_worker`` attribute pairs
    and ``_clear_x_refs`` slots that were duplicated per task in MainWindow.

    The handle must be created on the GUI thread so that the thread-finished
    notification (and ``on_cleared``) are delivered there.
    """

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self._on_cleared: Callable[[], None] | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    @property
    def worker(self) -> QObject | None:
        return self._worker

    def start(
        self,
        worker: QObject,
        *,
        finish_signals: Iterable[SignalInstance],
        on_cleared: Callable[[], None] | None = None,
    ) -> None:
        """Run ``worker.run`` on a new thread; quit when a finish signal fires.

        Callers are expected to connect the worker's result signals before
        calling, and to check :attr:`running` if concurrent starts are not
        desired.
        """
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(getattr(worker, "run"))
        for signal in finish_signals:
            signal.connect(thread.quit)
        # _handle_thread_finished must be connected before deleteLater: slots
        # run in connection order, and sender() must still be alive when the
        # stale-thread guard inspects it.
        thread.finished.connect(self._handle_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        self._on_cleared = on_cleared
        thread.start()

    @Slot()
    def _handle_thread_finished(self) -> None:
        # A finished notification from a superseded thread must not clear
        # the references of a newer run.
        if self._thread is not None and self.sender() is not self._thread:
            return
        self._thread = None
        self._worker = None
        on_cleared, self._on_cleared = self._on_cleared, None
        if on_cleared is not None:
            on_cleared()
