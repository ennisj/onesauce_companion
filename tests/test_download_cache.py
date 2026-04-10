from pathlib import Path

from onesauce_companion.services import download_cache


def test_resolve_downloads_dir_uses_requested_path_when_available(tmp_path: Path) -> None:
    requested = tmp_path / "downloads"

    resolved = download_cache.resolve_downloads_dir(requested)

    assert resolved.path == requested
    assert resolved.warning is None
    assert requested.exists()


def test_resolve_downloads_dir_falls_back_when_requested_path_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    requested = Path("U:/onesauce_downloads")
    fallback = tmp_path / "fallback_downloads"

    real_mkdir = Path.mkdir

    def fake_mkdir(self: Path, parents: bool = False, exist_ok: bool = False):
        if self == requested or self == requested.parent:
            raise OSError(67, "The network name cannot be found")
        return real_mkdir(self, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(download_cache, "default_downloads_dir", lambda: fallback)
    monkeypatch.setattr(Path, "mkdir", fake_mkdir)

    resolved = download_cache.resolve_downloads_dir(requested)

    assert resolved.path == fallback
    assert resolved.warning is not None
    assert "U:\\onesauce_downloads" in resolved.warning or "U:/onesauce_downloads" in resolved.warning
    assert fallback.exists()
