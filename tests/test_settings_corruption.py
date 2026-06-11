import json

from onesauce_companion.services.settings import AppSettings, SettingsStore
from onesauce_companion.services.state import InstallState


def _store_with_keyring(tmp_path, monkeypatch, keyring_password: str = "") -> SettingsStore:
    store = SettingsStore(tmp_path)
    monkeypatch.setattr(store, "_get_keyring_password", lambda: keyring_password)
    monkeypatch.setattr(store, "_set_keyring_password", lambda password: True)
    return store


def test_corrupt_settings_json_falls_back_to_defaults(tmp_path, monkeypatch):
    store = _store_with_keyring(tmp_path, monkeypatch, keyring_password="kept-secret")
    store.config_file.write_text("{not valid json", encoding="utf-8")

    settings = store.load()

    assert settings.install_target == AppSettings().install_target
    assert settings.archive_password == "kept-secret"
    assert not store.config_file.exists()
    assert (tmp_path / "settings.json.corrupt").exists()


def test_settings_json_with_wrong_root_type_falls_back_to_defaults(tmp_path, monkeypatch):
    store = _store_with_keyring(tmp_path, monkeypatch)
    store.config_file.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    settings = store.load()

    assert settings == AppSettings(archive_password="")
    assert (tmp_path / "settings.json.corrupt").exists()


def test_settings_json_with_bad_field_types_falls_back_to_defaults(tmp_path, monkeypatch):
    store = _store_with_keyring(tmp_path, monkeypatch)
    store.config_file.write_text(json.dumps({"downloads_retention_days": "garbage"}), encoding="utf-8")

    settings = store.load()

    assert settings.downloads_retention_days == AppSettings().downloads_retention_days


def test_valid_settings_json_still_loads(tmp_path, monkeypatch):
    store = _store_with_keyring(tmp_path, monkeypatch)
    store.config_file.write_text(json.dumps({"install_target": "V:\\OnesaUCE"}), encoding="utf-8")

    settings = store.load()

    assert settings.install_target == "V:\\OnesaUCE"
    assert store.config_file.exists()


def test_corrupt_state_json_returns_empty_state(tmp_path):
    state_path = tmp_path / ".onesauce_companion" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{broken", encoding="utf-8")

    state = InstallState.load(tmp_path)

    assert state.versions == {}
    assert state.archive_filenames == {}
    assert state.collection_roots == {}


def test_state_json_with_wrong_root_type_returns_empty_state(tmp_path):
    state_path = tmp_path / ".onesauce_companion" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    state = InstallState.load(tmp_path)

    assert state.versions == {}
