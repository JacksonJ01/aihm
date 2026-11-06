from __future__ import annotations

from pathlib import Path

import pandas as pd

LANDMARK_COUNT = 33


def validate_frame_dataframe(df: pd.DataFrame) -> None:
    required = ["session_id", "video_id", "camera_id", "frame_id", "timestamp_s"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Missing required identifiers: {missing}")
    if df.empty:
        raise ValueError("Frame DataFrame is empty.")
    if df.columns.duplicated().any():
        duplicates = df.columns[df.columns.duplicated()].tolist()
        raise ValueError(f"Duplicate feature columns detected: {duplicates}")
    frame_ids = pd.to_numeric(df["frame_id"], errors="coerce")
    if frame_ids.isna().any():
        raise ValueError("frame_id contains invalid values.")
    if not frame_ids.is_unique:
        raise ValueError("frame_id values are not unique.")
    if not frame_ids.is_monotonic_increasing:
        raise ValueError("frame_id is not ordered increasingly.")
    expected = pd.RangeIndex(start=0, stop=len(df), step=1)
    if not frame_ids.astype(int).reset_index(drop=True).equals(pd.Series(expected, name="frame_id")):
        raise ValueError("frame_id must be contiguous from 0 to frame_count-1.")

    timestamps = pd.to_numeric(df["timestamp_s"], errors="coerce")
    if timestamps.isna().any():
        raise ValueError("timestamp_s contains invalid values.")
    if not timestamps.is_monotonic_increasing:
        raise ValueError("timestamp_s is not monotonic.")
    if "delta_time_s" in df.columns:
        delta = pd.to_numeric(df["delta_time_s"], errors="coerce")
        if len(delta) and not pd.isna(delta.iloc[0]):
            raise ValueError("delta_time_s must be null/NaN for the first frame.")
        if (delta.iloc[1:].dropna() <= 0).any():
            raise ValueError("delta_time_s must be positive for subsequent valid frames.")
    if "timestamp_source" in df.columns:
        allowed_sources = {"decoder", "fps_estimate"}
        observed_sources = set(df["timestamp_source"].dropna().astype(str).unique())
        invalid_sources = observed_sources - allowed_sources
        if invalid_sources:
            raise ValueError(f"Invalid timestamp_source values: {sorted(invalid_sources)}")

    for i in range(LANDMARK_COUNT):
        for axis in ("x", "y", "z"):
            column = f"lm{i}_{axis}"
            if column not in df.columns:
                raise ValueError(f"Missing expected landmark column: {column}")

    if "target_status" in df.columns:
        allowed_statuses = {"searching", "tracked", "partially_occluded", "occluded", "lost", "reacquired", "ambiguous"}
        observed = set(df["target_status"].dropna().astype(str).unique())
        invalid_statuses = observed - allowed_statuses
        if invalid_statuses:
            raise ValueError(f"Invalid target_status values: {sorted(invalid_statuses)}")
        tracked = df["target_status"].isin({"tracked", "reacquired"})
        if (tracked & (pd.to_numeric(df["pose_present"], errors="coerce").fillna(0) != 1)).any():
            raise ValueError("Tracked/reacquired frames must contain a valid target pose.")
        if "target_confidence" in df.columns:
            confidence = pd.to_numeric(df["target_confidence"], errors="coerce")
            if ((confidence.dropna() < 0) | (confidence.dropna() > 1)).any():
                raise ValueError("target_confidence must be within [0, 1].")


def validate_artifacts(
    *,
    source_video: Path,
    processed_video: Path,
    landmarks_path: Path,
    features_path: Path,
    metadata_path: Path,
    manifest_path: Path,
    quality_path: Path | None = None,
) -> None:
    paths = [
        (source_video, "source video"),
        (processed_video, "processed video"),
        (landmarks_path, "landmarks Parquet"),
        (features_path, "features Parquet"),
        (metadata_path, "metadata JSON"),
        (manifest_path, "feature manifest JSON"),
    ]
    if quality_path is not None:
        paths.append((quality_path, "quality report JSON"))
    for path, label in paths:
        if not path.exists() or path.stat().st_size == 0:
            raise ValueError(f"Expected {label} was not created: {path}")

    landmarks = pd.read_parquet(landmarks_path)
    features = pd.read_parquet(features_path)
    validate_frame_dataframe(landmarks)
    validate_frame_dataframe(features)
    if len(landmarks) != len(features):
        raise ValueError(
            f"Row-count mismatch: landmarks={len(landmarks)}, features={len(features)}"
        )
