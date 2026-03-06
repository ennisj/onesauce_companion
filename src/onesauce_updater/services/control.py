from __future__ import annotations

from threading import Condition


class OperationCancelledError(RuntimeError):
    """Raised when the user cancels an in-flight install operation."""


class OperationController:
    def __init__(self) -> None:
        self._condition = Condition()
        self._paused = False
        self._cancelled = False

    def pause(self) -> None:
        with self._condition:
            self._paused = True

    def resume(self) -> None:
        with self._condition:
            self._paused = False
            self._condition.notify_all()

    def cancel(self) -> None:
        with self._condition:
            self._cancelled = True
            self._paused = False
            self._condition.notify_all()

    def wait_if_paused(self) -> None:
        with self._condition:
            while self._paused and not self._cancelled:
                self._condition.wait(timeout=0.25)
            if self._cancelled:
                raise OperationCancelledError("Install cancelled by user.")

    def raise_if_cancelled(self) -> None:
        with self._condition:
            if self._cancelled:
                raise OperationCancelledError("Install cancelled by user.")

    @property
    def is_paused(self) -> bool:
        with self._condition:
            return self._paused

    @property
    def is_cancelled(self) -> bool:
        with self._condition:
            return self._cancelled
