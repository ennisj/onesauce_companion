from __future__ import annotations

import re
from pathlib import Path


BUILD_PATTERN = re.compile(r"Build\s+(v[0-9][^\s]*)", re.IGNORECASE)
FILENAME_VERSION_PATTERN = re.compile(r"(v\d+\.\d+b\d+)", re.IGNORECASE)


def parse_build_version(text: str) -> str | None:
    match = BUILD_PATTERN.search(text)
    if not match:
        return None
    return match.group(1)


def parse_version_from_filename(name: str) -> str | None:
    match = FILENAME_VERSION_PATTERN.search(name)
    if not match:
        return None
    return match.group(1)


def decode_version_text(raw: bytes) -> str:
    for encoding in ("utf-16", "utf-8-sig", "utf-8", "latin1"):
        try:
            return raw.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").strip()


def read_version_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return parse_build_version(decode_version_text(path.read_bytes()))
