from __future__ import annotations

import re

import requests

RELEASES_PAGE_URL = "https://github.com/ennisj/onesauce_companion/releases"
LATEST_RELEASE_API_URL = "https://api.github.com/repos/ennisj/onesauce_companion/releases/latest"

_VERSION_PATTERN = re.compile(r"(\d+(?:\.\d+)+)")


def fetch_latest_release_tag() -> str | None:
    response = requests.get(
        LATEST_RELEASE_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "OnesaUCE-Companion-Version-Check",
        },
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    tag_name = str(payload.get("tag_name", "")).strip()
    return tag_name or None


def is_newer_release_available(current_version: str, latest_tag: str | None) -> bool:
    if not latest_tag:
        return False

    current_key = _release_sort_key(current_version)
    latest_key = _release_sort_key(latest_tag)
    if current_key is None or latest_key is None:
        return False
    return latest_key > current_key


def _release_sort_key(value: str) -> tuple[int, ...] | None:
    match = _VERSION_PATTERN.search(value)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))
