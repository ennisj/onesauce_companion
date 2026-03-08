from __future__ import annotations

from threading import Condition


class OperationCancelledError(RuntimeError):
    """Raised when the user cancels an in-flight install operation."""


class OperationComponentSkippedError(RuntimeError):
    """Raised when a queued component is removed before completion."""

    def __init__(self, component_key: str) -> None:
        self.component_key = component_key
        super().__init__(f"Component {component_key} was removed from the queue.")


class OperationController:
    def __init__(self) -> None:
        self._condition = Condition()
        self._paused = False
        self._cancelled = False
        self._skipped_components: set[str] = set()

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

    def skip_component(self, component_key: str) -> None:
        with self._condition:
            self._skipped_components.add(component_key)
            self._condition.notify_all()

    def wait_if_paused(self, component_key: str | None = None) -> None:
        with self._condition:
            while self._paused and not self._cancelled:
                if component_key and component_key in self._skipped_components:
                    raise OperationComponentSkippedError(component_key)
                self._condition.wait(timeout=0.25)
            if self._cancelled:
                raise OperationCancelledError("Install cancelled by user.")
            if component_key and component_key in self._skipped_components:
                raise OperationComponentSkippedError(component_key)

    def raise_if_cancelled(self, component_key: str | None = None) -> None:
        with self._condition:
            if self._cancelled:
                raise OperationCancelledError("Install cancelled by user.")
            if component_key and component_key in self._skipped_components:
                raise OperationComponentSkippedError(component_key)

    @property
    def is_paused(self) -> bool:
        with self._condition:
            return self._paused

    @property
    def is_cancelled(self) -> bool:
        with self._condition:
            return self._cancelled

    def is_component_skipped(self, component_key: str) -> bool:
        with self._condition:
            return component_key in self._skipped_components
