from __future__ import annotations

from importlib.resources import files

__all__ = ["__version__"]

__version__ = files("onesauce_companion").joinpath("VERSION").read_text(encoding="utf-8").strip()
