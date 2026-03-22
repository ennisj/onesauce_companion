from onesauce_companion.services.settings import AppSettings, SettingsStore


def test_blank_archive_password_save_does_not_delete_keyring_entry(tmp_path, monkeypatch):
    store = SettingsStore(tmp_path)
    deleted = False
    stored_passwords: list[str] = []

    def fake_set_keyring_password(password: str) -> bool:
        stored_passwords.append(password)
        return True

    def fake_delete_keyring_password() -> None:
        nonlocal deleted
        deleted = True

    monkeypatch.setattr(store, "_set_keyring_password", fake_set_keyring_password)
    monkeypatch.setattr(store, "_delete_keyring_password", fake_delete_keyring_password)

    store.save(AppSettings(archive_email="user@example.com", archive_password=""))

    assert stored_passwords == []
    assert deleted is False


def test_nonblank_archive_password_save_stores_keyring_entry(tmp_path, monkeypatch):
    store = SettingsStore(tmp_path)
    stored_passwords: list[str] = []

    def fake_set_keyring_password(password: str) -> bool:
        stored_passwords.append(password)
        return True

    monkeypatch.setattr(store, "_set_keyring_password", fake_set_keyring_password)

    store.save(AppSettings(archive_email="user@example.com", archive_password="secret"))

    assert stored_passwords == ["secret"]
