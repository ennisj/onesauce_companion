from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version
from importlib.resources import files

__all__ = ["__version__"]


def _load_version() -> str:
    try:
        return files("onesauce_companion").joinpath("VERSION").read_text(encoding="utf-8").strip()
    except (FileNotFoundError, ModuleNotFoundError):
        pass

    try:
        return package_version("onesauce-companion")
    except PackageNotFoundError:
        return "0.0.0"


__version__ = _load_version()
