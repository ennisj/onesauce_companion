"""Shared UI constants — screen indices and table column maps."""
from __future__ import annotations

SETTINGS_SCREEN = 0
BASE_COMPONENTS_SCREEN = 1
GAME_PACKS_SCREEN = 2
BITLCD_MARQUEES_SCREEN = 3
OPTIONAL_COMPONENTS_SCREEN = 4
QUEUE_SCREEN = 5
GAMES_SCREEN = 6
COLLECTIONS_SCREEN = 7
TWEAKS_SCREEN = 8
LOGS_SCREEN = 9

BASE_TABLE_COLUMNS = {
    "select": 0,
    "component": 1,
    "installed": 2,
    "available": 3,
    "downloaded": 4,
    "size": 5,
    "status": 6,
}

OPTIONAL_TABLE_COLUMNS = {
    "select": 0,
    "component": 1,
    "type": 2,
    "installed": 3,
    "available": 4,
    "downloaded": 5,
    "size": 6,
    "status": 7,
}

QUEUE_TABLE_COLUMNS = {
    "actions": 0,
    "component": 1,
    "source": 2,
    "available": 3,
    "size": 4,
    "status": 5,
}

GAMES_TABLE_COLUMNS = {
    "index": 0,
    "game_name": 1,
    "collection": 2,
    "status": 3,
}

COLLECTIONS_TABLE_COLUMNS = {
    "index": 0,
    "collection_name": 1,
    "parent_collections": 2,
    "game_count": 3,
}
