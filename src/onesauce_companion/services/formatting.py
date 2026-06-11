from __future__ import annotations


def format_size_label(size_bytes: int) -> str:
    """Compact decimal size label used in component tables, e.g. ``4.9G``."""
    value = float(size_bytes)
    for unit in ("B", "K", "M", "G", "T"):
        if value < 1000.0 or unit == "T":
            if unit == "B":
                return f"{int(value)}B"
            return f"{value:.1f}{unit}"
        value /= 1000.0
    return f"{value:.1f}T"


def format_bytes(size_bytes: int | None) -> str:
    """Human-readable binary size for log/error messages, e.g. ``1.5 GB``."""
    if size_bytes is None:
        return "unknown size"
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"
