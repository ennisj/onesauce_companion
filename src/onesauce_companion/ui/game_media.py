"""Game and collection media lookup helpers used by the details screens."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PySide6.QtGui import QPixmap

from onesauce_companion.services.collection_catalog import collection_directory_candidates
from onesauce_companion.services.games import GameManifestEntry


GAME_PRIMARY_ART_FOLDERS = ("artwork_3d", "artwork_front", "artwork_front_s")
GAME_DETAIL_MEDIA_FOLDERS = ("screenshot", "screentitle", "video")
IMAGE_MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
VIDEO_MEDIA_SUFFIXES = {".mp4", ".avi", ".mkv", ".mov", ".webm"}
STORY_MEDIA_SUFFIXES = {".txt"}

_BITLCD_MEDIA_INDEX: dict[str, dict[str, Path]] = {}
_VIDEO_THUMBNAIL_CACHE: dict[tuple[str, int], QPixmap] = {}

def _game_name_candidates(rom_name: str) -> tuple[str, ...]:
    path = Path(rom_name)
    candidates: list[str] = []
    current = path.name
    while current:
        if current not in candidates:
            candidates.append(current)
        stem = Path(current).stem
        if stem == current:
            break
        current = stem
    return tuple(candidates)


def _find_matching_media_file(directory: Path, base_names: tuple[str, ...], allowed_suffixes: set[str] | None = None) -> Path | None:
    if not directory.exists() or not directory.is_dir():
        return None
    candidate_keys = {name.casefold() for name in base_names}
    search_dirs: list[Path] = [directory]
    for name in base_names:
        nested_dir = directory / Path(name).stem
        if nested_dir.exists() and nested_dir.is_dir() and nested_dir not in search_dirs:
            search_dirs.append(nested_dir)
    for search_dir in search_dirs:
        for path in sorted(search_dir.iterdir(), key=lambda item: item.name.casefold()):
            if not path.is_file():
                continue
            if allowed_suffixes is not None and path.suffix.casefold() not in allowed_suffixes:
                continue
            if _media_path_matches(path, candidate_keys):
                return path
    return None


def _resolve_collection_media_root(target_dir: Path | None, collection_name: str) -> Path | None:
    for collection_dir in collection_directory_candidates(target_dir, collection_name):
        media_root = collection_dir / "system_artwork"
        if media_root.exists() and media_root.is_dir():
            return media_root
    return None


def _find_named_collection_media_file(
    media_root: Path | None,
    stem_name: str,
    allowed_suffixes: set[str],
) -> Path | None:
    if media_root is None or not media_root.exists() or not media_root.is_dir():
        return None
    stem_key = stem_name.casefold()
    for path in sorted(media_root.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file():
            continue
        if path.suffix.casefold() not in allowed_suffixes:
            continue
        if path.stem.casefold() == stem_key:
            return path
    return None


def _find_first_collection_video(media_root: Path | None) -> Path | None:
    if media_root is None or not media_root.exists() or not media_root.is_dir():
        return None
    video_dir = media_root / "video"
    if not video_dir.exists() or not video_dir.is_dir():
        return None
    for path in sorted(video_dir.iterdir(), key=lambda item: item.name.casefold()):
        if path.is_file() and path.suffix.casefold() in VIDEO_MEDIA_SUFFIXES:
            return path
    return None


def _find_collection_videos(media_root: Path | None) -> tuple[Path, ...]:
    if media_root is None or not media_root.exists() or not media_root.is_dir():
        return tuple()
    video_dir = media_root / "video"
    if not video_dir.exists() or not video_dir.is_dir():
        return tuple()
    return tuple(
        path
        for path in sorted(video_dir.iterdir(), key=lambda item: item.name.casefold())
        if path.is_file() and path.suffix.casefold() in VIDEO_MEDIA_SUFFIXES
    )


def _media_path_matches(path: Path, candidate_keys: set[str]) -> bool:
    current = path.name.casefold()
    current_stem = path.stem.casefold()
    if current in candidate_keys or current_stem in candidate_keys:
        return True
    for candidate in candidate_keys:
        if current_stem.startswith(candidate + " (") or current_stem.startswith(candidate + "["):
            return True
    nested_stem = current_stem
    while True:
        reduced = Path(nested_stem).stem.casefold()
        if reduced == nested_stem:
            break
        if reduced in candidate_keys:
            return True
        for candidate in candidate_keys:
            if reduced.startswith(candidate + " (") or reduced.startswith(candidate + "["):
                return True
        nested_stem = reduced
    return False


def _find_matching_lcd_marquee_file(
    media_root: Path,
    bitlcd_target_dir: Path | None,
    entry: GameManifestEntry,
    base_names: tuple[str, ...],
) -> Path | None:
    match = _find_matching_media_file(media_root / "lcd_marquee", base_names, IMAGE_MEDIA_SUFFIXES)
    if match is not None:
        return match
    return _find_matching_bitlcd_media_file(bitlcd_target_dir, entry, base_names)


def _find_matching_bitlcd_media_file(
    bitlcd_target_dir: Path | None,
    entry: GameManifestEntry,
    base_names: tuple[str, ...],
) -> Path | None:
    if bitlcd_target_dir is None or not bitlcd_target_dir.exists() or not bitlcd_target_dir.is_dir():
        return None
    candidate_dirs = _candidate_bitlcd_roots(bitlcd_target_dir, entry)
    candidate_keys = {name.casefold() for name in base_names}
    for root_dir in candidate_dirs:
        index = _bitlcd_media_index_for_root(root_dir)
        for candidate in candidate_keys:
            match = index.get(candidate)
            if match is not None:
                return match
    return None


def _bitlcd_media_index_for_root(root_dir: Path) -> dict[str, Path]:
    cache_key = str(root_dir)
    cached = _BITLCD_MEDIA_INDEX.get(cache_key)
    if cached is not None:
        return cached
    index: dict[str, Path] = {}
    for path in sorted(root_dir.rglob("*"), key=lambda item: str(item).casefold()):
        if not path.is_file() or path.suffix.casefold() not in IMAGE_MEDIA_SUFFIXES:
            continue
        for token in _media_match_tokens(path):
            index.setdefault(token, path)
    _BITLCD_MEDIA_INDEX[cache_key] = index
    return index


def _invalidate_bitlcd_media_index() -> None:
    _BITLCD_MEDIA_INDEX.clear()


def _media_match_tokens(path: Path) -> set[str]:
    tokens: set[str] = set()
    current = path.name.casefold()
    current_stem = path.stem.casefold()
    tokens.add(current)
    nested_stem = current_stem
    while True:
        tokens.add(nested_stem)
        for delimiter in (" (", "["):
            if delimiter in nested_stem:
                tokens.add(nested_stem.split(delimiter, 1)[0])
        reduced = Path(nested_stem).stem.casefold()
        if reduced == nested_stem:
            break
        nested_stem = reduced
    return tokens


def _candidate_bitlcd_roots(bitlcd_target_dir: Path, entry: GameManifestEntry) -> list[Path]:
    name_candidates = [entry.collection_name, entry.install_collection_name or "", entry.source_pack or ""]
    normalized_tokens = {_normalize_lookup_name(name) for name in name_candidates if name}
    direct_matches: list[Path] = []
    for child in sorted(bitlcd_target_dir.iterdir(), key=lambda item: item.name.casefold()):
        if not child.is_dir():
            continue
        normalized_child = _normalize_lookup_name(child.name)
        if any(token and token in normalized_child for token in normalized_tokens):
            direct_matches.append(child)
    return direct_matches


def _normalize_lookup_name(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _media_key_for_title(title: str) -> str:
    return {
        "Front Artwork": "front_art",
        "Bezel": "bezel",
        "Logo": "logo",
        "LED Marquee": "led_marquee",
        "LCD Marquee": "lcd_marquee",
        "Screenshot": "screenshot",
        "Screen Title": "screentitle",
    }[title]


def _resolve_lcd_marquee_target_dir(
    media_root: Path | None,
    bitlcd_target_dir: Path | None,
    entry: GameManifestEntry,
    current_path: Path | None,
) -> Path | None:
    if current_path is not None:
        return current_path.parent
    if media_root is not None:
        return media_root / "lcd_marquee"
    candidate_dirs = _candidate_bitlcd_roots(bitlcd_target_dir, entry)
    return candidate_dirs[0] if candidate_dirs else bitlcd_target_dir


def _read_story_text(story_path: Path | None) -> str:
    if story_path is None or not story_path.exists():
        return "No story file found."
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return story_path.read_text(encoding=encoding).strip() or "Story file is empty."
        except UnicodeDecodeError:
            continue
        except OSError:
            return "Unable to read the story file."
    return "Unable to decode the story file."


def _resolve_game_media_root(
    target_dir: Path | None,
    entry: GameManifestEntry,
    base_names: tuple[str, ...],
) -> Path | None:
    if target_dir is None:
        return None
    candidate_roots: list[Path] = _candidate_game_media_roots(target_dir, entry)

    best_root = None
    best_score = -1

    for media_root in candidate_roots:
        score = _score_game_media_root(media_root, base_names)
        if score > best_score:
            best_score = score
            best_root = media_root

    return best_root


def _candidate_game_media_roots(target_dir: Path, entry: GameManifestEntry) -> list[Path]:
    candidate_roots: list[Path] = []
    collections_root = _game_media_search_root(target_dir)
    for collection_name in (entry.collection_name, entry.install_collection_name or entry.collection_name):
        direct_root = collections_root / collection_name / "medium_artwork"
        if direct_root.exists() and direct_root not in candidate_roots:
            candidate_roots.append(direct_root)

    installed_collection = _find_installed_collection_root(target_dir, entry)
    if installed_collection is not None and installed_collection not in candidate_roots:
        candidate_roots.insert(0, installed_collection)

    return candidate_roots


def _game_media_search_root(target_dir: Path) -> Path:
    return target_dir / "content" / "retrofe" / "collections"


def _find_installed_collection_root(target_dir: Path, entry: GameManifestEntry) -> Path | None:
    collections_root = _game_media_search_root(target_dir)
    if not collections_root.exists():
        return None
    for collection_dir in collections_root.iterdir():
        if not collection_dir.is_dir():
            continue
        if (collection_dir / "roms" / entry.rom_path).exists():
            media_root = collection_dir / "medium_artwork"
            if media_root.exists():
                return media_root
    return None


def _score_game_media_root(media_root: Path, base_names: tuple[str, ...]) -> int:
    if not media_root.exists() or not media_root.is_dir():
        return -1
    score = 0
    folder_suffixes = {
        "artwork_front": IMAGE_MEDIA_SUFFIXES,
        "bezel": IMAGE_MEDIA_SUFFIXES,
        "logo": IMAGE_MEDIA_SUFFIXES,
        "story": STORY_MEDIA_SUFFIXES,
        "led_marquee": IMAGE_MEDIA_SUFFIXES,
        "lcd_marquee": IMAGE_MEDIA_SUFFIXES,
        "screenshot": IMAGE_MEDIA_SUFFIXES,
        "screentitle": IMAGE_MEDIA_SUFFIXES,
        "video": VIDEO_MEDIA_SUFFIXES,
    }
    for folder_name, suffixes in folder_suffixes.items():
        if _find_matching_media_file(media_root / folder_name, base_names, suffixes) is not None:
            score += 1
    return score


def _extract_video_thumbnail(video_path: Path) -> QPixmap | None:
    try:
        stat = video_path.stat()
    except OSError:
        return None
    cache_key = (str(video_path.resolve()), stat.st_mtime_ns)
    cached = _VIDEO_THUMBNAIL_CACHE.get(cache_key)
    if cached is not None:
        return QPixmap(cached)

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        return None

    for offset in _video_thumbnail_offsets(video_path):
        pixmap = _run_ffmpeg_thumbnail_extract(ffmpeg_path, video_path, offset)
        if pixmap is None or pixmap.isNull():
            continue
        _VIDEO_THUMBNAIL_CACHE[cache_key] = QPixmap(pixmap)
        return pixmap
    return None


def _video_thumbnail_offsets(video_path: Path) -> tuple[float, ...]:
    ffprobe_path = shutil.which("ffprobe")
    offsets: list[float] = []
    if ffprobe_path is not None:
        try:
            result = subprocess.run(
                [
                    ffprobe_path,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(video_path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                duration = float((result.stdout or "").strip())
                if duration > 0:
                    offsets.append(min(max(duration * 0.15, 1.0), max(duration - 0.25, 0.0)))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    offsets.extend((5.0, 1.0, 0.0))
    unique_offsets: list[float] = []
    for offset in offsets:
        rounded = round(max(0.0, offset), 3)
        if rounded not in unique_offsets:
            unique_offsets.append(rounded)
    return tuple(unique_offsets)


def _run_ffmpeg_thumbnail_extract(ffmpeg_path: str, video_path: Path, offset: float) -> QPixmap | None:
    try:
        result = subprocess.run(
            [
                ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{offset:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "pipe:1",
            ],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    pixmap = QPixmap()
    if not pixmap.loadFromData(result.stdout, "PNG"):
        return None
    return pixmap


