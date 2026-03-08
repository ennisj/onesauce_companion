from __future__ import annotations

import gzip
import json
import os
import struct
from time import sleep
from pathlib import Path

from internetarchive import get_item

from onesauce_companion.manifest import GAME_PACKS
from onesauce_companion.services.archive_org import ArchiveOrgCredentials, create_authenticated_session
from onesauce_companion.services.settings import SettingsStore


EOCD_SIG = b"PK\x05\x06"
ZIP64_LOCATOR_SIG = b"PK\x06\x07"
ZIP64_EOCD_SIG = b"PK\x06\x06"
CEN_SIG = b"PK\x01\x02"
COLLECTION_PREFIX = "content/retrofe/collections/"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "src" / "onesauce_companion" / "data" / "games_manifest.json.gz"


def main() -> int:
    credentials = _load_credentials()
    session, user, _ = create_authenticated_session(credentials)
    print(f"Authenticated with Archive.org as {user}.")

    manifest_entries: dict[tuple[str, str], dict[str, str]] = {}
    for index, spec in enumerate(GAME_PACKS, start=1):
        print(f"[{index}/{len(GAME_PACKS)}] Inspecting {spec.filename}...")
        item = get_item(spec.archive_item, archive_session=session)
        metadata = next((entry for entry in item.files if entry.get("name") == spec.filename), None)
        if metadata is None:
            raise FileNotFoundError(f"Archive.org file metadata not found for {spec.filename}")
        archive_file = item.get_file(spec.filename, file_metadata=metadata)
        size_bytes = int(metadata["size"])
        tail = _fetch_tail_for_central_directory(
            session,
            [
                (archive_file.url, archive_file.auth),
                (spec.download_url, archive_file.auth),
                (spec.download_url, None),
                (archive_file.url, None),
            ],
            size_bytes,
        )
        for name in _rom_entries_from_tail(tail, size_bytes):
            game_pack, rom_path = _parse_collection_and_rom_path(name)
            if game_pack is None or rom_path is None:
                continue
            manifest_entries[(game_pack.casefold(), rom_path.casefold())] = {
                "game_name": Path(rom_path).name,
                "game_pack": game_pack,
                "rom_path": rom_path,
            }

    ordered_entries = sorted(
        manifest_entries.values(),
        key=lambda entry: (entry["game_pack"].casefold(), entry["game_name"].casefold(), entry["rom_path"].casefold()),
    )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUTPUT_PATH, "wt", encoding="utf-8") as handle:
        json.dump(ordered_entries, handle, indent=2)
    print(f"Wrote {len(ordered_entries)} game entries to {OUTPUT_PATH}.")
    return 0


def _load_credentials() -> ArchiveOrgCredentials:
    email = os.environ.get("ONESAUCE_ARCHIVE_EMAIL", "").strip()
    password = os.environ.get("ONESAUCE_ARCHIVE_PASSWORD", "")
    if email and password:
        return ArchiveOrgCredentials(email=email, password=password)

    settings = SettingsStore().load()
    if settings.archive_email.strip() and settings.archive_password:
        return ArchiveOrgCredentials(settings.archive_email.strip(), settings.archive_password)
    raise RuntimeError("Archive.org credentials not found. Set ONESAUCE_ARCHIVE_EMAIL/PASSWORD or save credentials in the app settings.")


def _fetch_tail_for_central_directory(session, candidates: list[tuple[str, object]], size_bytes: int) -> bytes:
    tail_size = min(size_bytes, 8 * 1024 * 1024)
    max_tail_size = min(size_bytes, 128 * 1024 * 1024)
    while True:
        last_error: Exception | None = None
        for url, auth in candidates:
            try:
                tail = _request_tail(session, url, auth, tail_size)
            except Exception as exc:
                last_error = exc
                continue
            if _tail_contains_central_directory(tail, size_bytes):
                return tail
        if tail_size >= max_tail_size:
            if last_error is not None:
                raise last_error
            raise RuntimeError(f"Could not capture full central directory within {max_tail_size} bytes.")
        tail_size = min(max_tail_size, tail_size * 2)


def _request_tail(session, url: str, auth, tail_size: int) -> bytes:
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            with session.get(
                url,
                headers={"Range": f"bytes=-{tail_size}"},
                auth=auth,
                stream=True,
                timeout=(15, 180),
            ) as response:
                response.raise_for_status()
                return response.content
        except Exception as exc:
            last_error = exc
            if attempt == 4:
                break
            sleep(2 + attempt)
    if last_error is None:
        raise RuntimeError("Archive tail request failed.")
    raise last_error


def _tail_contains_central_directory(tail: bytes, size_bytes: int) -> bool:
    try:
        _central_directory_bounds(tail, size_bytes)
    except Exception:
        return False
    return True


def _rom_entries_from_tail(tail: bytes, size_bytes: int) -> list[str]:
    start, end = _central_directory_bounds(tail, size_bytes)
    entries: list[str] = []
    pos = start
    while pos < end:
        if tail[pos : pos + 4] != CEN_SIG:
            raise RuntimeError(f"Invalid central directory signature at offset {pos}.")
        header = tail[pos : pos + 46]
        values = struct.unpack("<4s6H3L5H2L", header)
        flags = values[3]
        name_len = values[10]
        extra_len = values[11]
        comment_len = values[12]
        name_bytes = tail[pos + 46 : pos + 46 + name_len]
        encoding = "utf-8" if flags & 0x800 else "cp437"
        name = name_bytes.decode(encoding, errors="replace")
        if "/roms/" in name and not name.endswith("/"):
            entries.append(name)
        pos += 46 + name_len + extra_len + comment_len
    return entries


def _central_directory_bounds(tail: bytes, size_bytes: int) -> tuple[int, int]:
    eocd_index = tail.rfind(EOCD_SIG)
    if eocd_index < 0:
        raise RuntimeError("EOCD record not found in archive tail.")

    values = struct.unpack("<4s4H2LH", tail[eocd_index : eocd_index + 22])
    cd_size = values[5]
    cd_offset = values[6]
    if cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF:
        loc_index = tail.rfind(ZIP64_LOCATOR_SIG, 0, eocd_index)
        if loc_index < 0:
            raise RuntimeError("ZIP64 locator not found in archive tail.")
        _, _, zip64_eocd_offset, _ = struct.unpack("<4sLQL", tail[loc_index : loc_index + 20])
        relative_offset = zip64_eocd_offset - (size_bytes - len(tail))
        zip64_record = tail[relative_offset : relative_offset + 56]
        if zip64_record[:4] != ZIP64_EOCD_SIG:
            raise RuntimeError("ZIP64 EOCD record not present in fetched tail.")
        zip64_values = struct.unpack("<4sQ2H2L4Q", zip64_record)
        cd_size = zip64_values[8]
        cd_offset = zip64_values[9]

    start = cd_offset - (size_bytes - len(tail))
    end = start + cd_size
    if start < 0 or end > len(tail):
        raise RuntimeError("Central directory extends outside the fetched archive tail.")
    return start, end


def _parse_collection_and_rom_path(path: str) -> tuple[str | None, str | None]:
    if not path.startswith(COLLECTION_PREFIX):
        return None, None
    suffix = path.removeprefix(COLLECTION_PREFIX)
    if "/roms/" not in suffix:
        return None, None
    collection_name, rom_path = suffix.split("/roms/", 1)
    if not collection_name or not rom_path:
        return None, None
    return collection_name, rom_path


if __name__ == "__main__":
    raise SystemExit(main())

