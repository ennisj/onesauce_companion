from __future__ import annotations

from onesauce_companion.manifest import BITLCD_MARQUEES, GAME_PACKS, REQUIRED_COMPONENTS
from onesauce_companion.models import QueueEntry
from onesauce_companion.ui.main_window import MainWindow


def test_next_queue_batch_entries_includes_all_same_target_not_just_contiguous() -> None:
    pending = [
        QueueEntry(spec=GAME_PACKS[0], source_label="Game Pack", target_path="F:\\"),
        QueueEntry(spec=BITLCD_MARQUEES[0], source_label="BitLCD Marquee", target_path="G:\\"),
        QueueEntry(spec=GAME_PACKS[1], source_label="Game Pack", target_path="F:\\"),
        QueueEntry(spec=REQUIRED_COMPONENTS[0], source_label="Base Component", target_path="F:\\"),
    ]

    batch = MainWindow._next_queue_batch_entries(pending)

    assert [entry.spec.key for entry in batch] == [
        GAME_PACKS[0].key,
        GAME_PACKS[1].key,
        REQUIRED_COMPONENTS[0].key,
    ]

