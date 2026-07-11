"""Downloads table layout persistence: column order rules and settings loading."""
from __future__ import annotations

import json

from onesauce_companion.services.settings import AppSettings, SettingsStore
from onesauce_companion.ui.screens.downloader_screen import (
    DOWNLOADS_TABLE_COLUMNS,
    downloads_column_order_valid,
)


DEFAULT_ORDER = list(DOWNLOADS_TABLE_COLUMNS)


def _store_with_keyring(tmp_path, monkeypatch) -> SettingsStore:
    store = SettingsStore(tmp_path)
    monkeypatch.setattr(store, "_get_keyring_password", lambda: "")
    monkeypatch.setattr(store, "_set_keyring_password", lambda password: True)
    monkeypatch.setattr(store, "_delete_keyring_password", lambda: None)
    return store


# ---------------------------------------------------------------------------
# downloads_column_order_valid
# ---------------------------------------------------------------------------

def test_default_column_order_is_valid():
    assert downloads_column_order_valid(DEFAULT_ORDER)


def test_reorder_within_group_is_valid():
    order = list(DEFAULT_ORDER)
    downloaded = order.index("downloaded")
    installed = order.index("installed")
    order[downloaded], order[installed] = order[installed], order[downloaded]
    assert downloads_column_order_valid(order)


def test_moving_whole_cabinet_group_before_local_group_is_valid():
    order = [key for key in DEFAULT_ORDER if key not in {"cabinet_version", "cabinet_status"}]
    order[order.index("downloaded"):order.index("downloaded")] = ["cabinet_version", "cabinet_status"]
    assert downloads_column_order_valid(order)


def test_splitting_a_group_is_invalid():
    order = list(DEFAULT_ORDER)
    order.remove("installed")
    order.append("installed")  # "Local" band now split by the Cabinet columns
    assert not downloads_column_order_valid(order)


def test_ungrouped_column_inside_a_group_is_invalid():
    order = list(DEFAULT_ORDER)
    order.remove("size")
    order.insert(order.index("installed"), "size")
    assert not downloads_column_order_valid(order)


def test_missing_or_duplicate_columns_are_invalid():
    assert not downloads_column_order_valid(DEFAULT_ORDER[:-1])
    assert not downloads_column_order_valid([*DEFAULT_ORDER[:-1], DEFAULT_ORDER[0]])
    assert not downloads_column_order_valid([])


# ---------------------------------------------------------------------------
# Settings load/save
# ---------------------------------------------------------------------------

def test_downloads_table_settings_roundtrip(tmp_path, monkeypatch):
    store = _store_with_keyring(tmp_path, monkeypatch)
    settings = AppSettings(
        downloads_column_order=list(DEFAULT_ORDER),
        downloads_column_widths={"component": 320, "status": 250},
        downloads_sort=[
            {"column": "type", "direction": "asc"},
            {"column": "component", "direction": "desc"},
        ],
    )

    store.save(settings)
    loaded = store.load()

    assert loaded.downloads_column_order == settings.downloads_column_order
    assert loaded.downloads_column_widths == settings.downloads_column_widths
    assert loaded.downloads_sort == settings.downloads_sort


def test_downloads_table_settings_reject_malformed_values(tmp_path, monkeypatch):
    store = _store_with_keyring(tmp_path, monkeypatch)
    store.config_file.write_text(
        json.dumps(
            {
                "downloads_column_order": ["component", 3, "component"],
                "downloads_column_widths": {"component": "wide", "status": -5, "size": 90.0, "type": True},
                "downloads_sort": [
                    {"column": "type", "direction": "sideways"},
                    {"column": "", "direction": "asc"},
                    {"column": "size", "direction": "DESC"},
                    {"column": "size", "direction": "asc"},
                    "not-a-dict",
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = store.load()

    assert loaded.downloads_column_order == []
    assert loaded.downloads_column_widths == {"size": 90}
    assert loaded.downloads_sort == [{"column": "size", "direction": "desc"}]


def test_downloads_table_settings_default_when_absent(tmp_path, monkeypatch):
    store = _store_with_keyring(tmp_path, monkeypatch)
    store.config_file.write_text(json.dumps({"install_target": "X:\\OnesaUCE"}), encoding="utf-8")

    loaded = store.load()

    assert loaded.downloads_column_order == []
    assert loaded.downloads_column_widths == {}
    assert loaded.downloads_sort == []
