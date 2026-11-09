import pandas as pd
import pytest

from aihumo.splits import grouped_split


def test_split_is_reproducible_and_keeps_whole_participants_together(detail):
    manifest = pd.DataFrame({
        "session_id": ["S1", "S2", "S2", "S1", "S1", "S2"],
        "participant_id": ["P1", "P1", "P1", "P2", "P3", "P4"],
        "camera_id": ["front", "front", "side", "side", "front", "front"],
    })
    split = grouped_split(manifest, {})
    assert split == grouped_split(manifest.iloc[::-1], {})
    groups = [set(split[name]) for name in ("train", "val", "test")]
    assert set.union(*groups) == set(manifest["participant_id"])
    assert sum(len(group) for group in groups) == 4
    assert split["group_key"] == "participant_id"
    detail(input="Four participants with overlapping session IDs and two cameras.",
           observed="Reversing manifest order keeps the same participant-disjoint split.")


def test_partial_participant_ids_cannot_trigger_session_fallback(detail):
    manifest = pd.DataFrame({"session_id": ["S1", "S2", "S3"], "participant_id": ["P1", "P1", None]})
    with pytest.raises(ValueError, match="partially filled") as failure:
        grouped_split(manifest, {})
    assert grouped_split(manifest.drop(columns="participant_id"), {})["group_key"] == "session_id"
    detail(input="One participant across two sessions, plus one session without an ID.", observed=str(failure.value))
