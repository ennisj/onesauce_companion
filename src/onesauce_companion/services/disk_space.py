from __future__ import annotations

import shutil
from pathlib import Path

from onesauce_companion.services.formatting import format_bytes


class InsufficientDiskSpaceError(RuntimeError):
    """Raised when a download or install would exceed the free space on a volume."""


def free_bytes_for_path(path: Path) -> int | None:
    """Return the free bytes on the volume containing ``path``.

    Walks up to the nearest existing ancestor so the check works before the
    directory itself has been created. Returns ``None`` when the volume cannot
    be inspected; callers should treat that as "unknown" and proceed.
    """
    probe = path
    while True:
        if probe.exists():
            try:
                return shutil.disk_usage(probe).free
            except OSError:
                return None
        parent = probe.parent
        if parent == probe:
            return None
        probe = parent


def ensure_free_space(path: Path, required_bytes: int, activity: str) -> None:
    """Raise :class:`InsufficientDiskSpaceError` if the volume holding ``path``
    has less than ``required_bytes`` free. Unknown free space is not an error.
    """
    if required_bytes <= 0:
        return
    free = free_bytes_for_path(path)
    if free is None or free >= required_bytes:
        return
    raise InsufficientDiskSpaceError(
        f"Not enough free disk space to {activity}: needs about {format_bytes(required_bytes)}, "
        f"but only {format_bytes(free)} is free on the volume containing {path}. "
        "Free up space and try again."
    )
