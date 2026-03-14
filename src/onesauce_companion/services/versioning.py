from __future__ import annotations

import re
from pathlib import Path


BUILD_PATTERN = re.compile(r"Build\s+(v[0-9][^\s]*)", re.IGNORECASE)
FILENAME_VERSION_PATTERN = re.compile(r"(v\d+\.\d+b\d+)", re.IGNORECASE)
ANY_VERSION_PATTERN = re.compile(r"(v\d+\.\d+b\d+)", re.IGNORECASE)


def parse_build_version(text: str) -> str | None:
    match = BUILD_PATTERN.search(text)
    if not match:
        return None
    return match.group(1)


def parse_version_text(text: str) -> str | None:
    detected = parse_build_version(text)
    if detected:
        return detected
    match = ANY_VERSION_PATTERN.search(text)
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
    return parse_version_text(decode_version_text(path.read_bytes()))


def read_version_from_install_root(root: Path) -> str | None:
    if not root.exists() or not root.is_dir():
        return None
    for path in sorted(root.iterdir()):
        if path.is_file() and path.name.lower().endswith("version.txt"):
            detected = read_version_file(path)
            if detected:
                return detected
    return None


def read_version_from_named_subfolders(root: Path, expected_name: str) -> str | None:
    if not root.exists() or not root.is_dir():
        return None
    expected_keys = _name_match_variants(expected_name)
    matches: list[str] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_dir() or _is_empty_directory(path):
            continue
        detected = parse_version_from_filename(path.name)
        folder_name = _bitlcd_folder_pack_name(path.name, detected)
        folder_key = normalize_name_key(folder_name)
        if not _matches_expected_name(folder_key, expected_keys):
            continue
        if detected:
            matches.append(detected)
        else:
            matches.append("installed")
    if not matches:
        return None
    if any(value == "installed" for value in matches):
        versioned = [value for value in matches if value != "installed"]
        if versioned:
            return max(versioned, key=_version_sort_key)
        return "installed"
    return max(matches, key=_version_sort_key)


def normalize_name_key(value: str) -> str:
    cleaned = value.replace("_", " ")
    cleaned = re.sub(r"[^a-z0-9]+", "", cleaned.casefold())
    cleaned = cleaned.replace("comodore", "commodore")
    cleaned = cleaned.replace("thompson", "thomson")
    cleaned = cleaned.replace("famicon", "famicom")
    cleaned = cleaned.replace("casette", "cassette")
    cleaned = cleaned.replace("magnovox", "magnavox")
    return cleaned


def _name_match_variants(value: str) -> set[str]:
    normalized = normalize_name_key(value)
    variants = {normalized}
    if normalized == "daphne99":
        variants.add("daphne")
    return variants


def _matches_expected_name(folder_key: str, expected_keys: set[str]) -> bool:
    for expected in expected_keys:
        if folder_key == expected or folder_key.startswith(expected):
            return True
    return False


def _bitlcd_folder_pack_name(folder_name: str, version: str | None) -> str:
    name = folder_name.replace(version, " ") if version else folder_name
    name = re.sub(r"sys[\s_]+spec", " ", name, flags=re.IGNORECASE)
    name = _strip_trailing_date(name)
    return re.sub(r"\s+", " ", name.replace("_", " ")).strip(" -_")


def _strip_trailing_date(value: str) -> str:
    return re.sub(r"(?:[\s_-]+\d{4,5}(?:[\s_-]+\d{1,2}){1,2})[\s_-]*$", "", value).strip(" -_")


def _is_empty_directory(path: Path) -> bool:
    try:
        next(path.iterdir())
    except StopIteration:
        return True
    except OSError:
        return True
    return False


def _version_sort_key(value: str) -> tuple[int, int, int, str]:
    match = re.match(r"v(\d+)\.(\d+)b(\d+)", value, re.IGNORECASE)
    if not match:
        return (0, 0, 0, value.casefold())
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)), value.casefold())


def has_nonempty_content(root: Path) -> bool:
    return root.exists() and root.is_dir() and not _is_empty_directory(root)
