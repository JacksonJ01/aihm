from __future__ import annotations

import json
import random
from pathlib import Path

import pandas as pd


def _nonempty(values: pd.Series) -> pd.Series:
    return values.fillna("").astype(str).str.strip()


def grouped_split(video_manifest: pd.DataFrame, cfg: dict) -> dict[str, list[str]]:
    """Split whole participants when complete IDs exist; otherwise split sessions.

    The unit of splitting is always the declared group, never a frame or window.
    Partially identified manifests are rejected because a session split could
    put a known participant on both sides. Session grouping is a legacy fallback
    for manifests with no participant IDs.
    """
    if "session_id" not in video_manifest.columns:
        raise ValueError("video_manifest must contain session_id")

    sessions = _nonempty(video_manifest["session_id"])
    if sessions.eq("").any():
        raise ValueError("Every manifest row must have a non-empty session_id.")

    use_participant = False
    if "participant_id" in video_manifest.columns:
        participants = _nonempty(video_manifest["participant_id"])
        if participants.ne("").any() and participants.eq("").any():
            raise ValueError("Participant IDs are only partially filled. Complete them before building participant-disjoint splits.")
        use_participant = bool(participants.ne("").all())
    else:
        participants = pd.Series("", index=video_manifest.index)

    group_column = "participant_id" if use_participant else "session_id"
    group_series = participants if use_participant else sessions
    groups = sorted(group_series.unique().tolist())
    if not groups:
        raise ValueError(f"No usable values found for split grouping column: {group_column}")

    split_cfg = cfg.get("splits", {})
    seed = int(split_cfg.get("seed", 42))
    rng = random.Random(seed)
    rng.shuffle(groups)

    n = len(groups)
    train_ratio = float(split_cfg.get("train", 0.7))
    val_ratio = float(split_cfg.get("val", 0.15))
    test_ratio = float(split_cfg.get("test", 0.15))
    if min(train_ratio, val_ratio, test_ratio) < 0:
        raise ValueError("Split ratios cannot be negative.")
    if train_ratio + val_ratio + test_ratio <= 0:
        raise ValueError("At least one split ratio must be positive.")

    # Very small collections cannot support three non-empty independent groups.
    if n == 1:
        train, val, test = groups, [], []
    elif n == 2:
        train, val, test = groups[:1], [], groups[1:]
    else:
        # Reserve at least one group for validation and testing when possible.
        desired_train = max(1, int(round(n * train_ratio)))
        desired_val = max(1, int(round(n * val_ratio)))
        desired_train = min(desired_train, n - 2)
        desired_val = min(desired_val, n - desired_train - 1)
        if desired_val < 1:
            desired_val = 1
            desired_train = max(1, n - 2)
        train = groups[:desired_train]
        val = groups[desired_train:desired_train + desired_val]
        test = groups[desired_train + desired_val:]

    return {
        "group_key": group_column,
        "train": train,
        "val": val,
        "test": test,
        "seed": seed,
        "ratios": {"train": train_ratio, "val": val_ratio, "test": test_ratio},
    }


def save_splits(splits: dict, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(splits, indent=2), encoding="utf-8")
