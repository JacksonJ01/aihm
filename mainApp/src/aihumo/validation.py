from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

LANDMARK_COUNT = 33
RECORDING_IDS = ("session_id", "video_id", "camera_id")


def _read_validation_frame_table(path: Path) -> pd.DataFrame:
    """Read only columns used by frame validation, not the full feature table."""
    with pq.ParquetFile(path) as parquet:
        available = set(parquet.schema_arrow.names)
        required = [*RECORDING_IDS, "frame_id", "timestamp_s"]
        landmarks = [f"lm{i}_{axis}" for i in range(LANDMARK_COUNT) for axis in ("x", "y", "z")]
        optional = ["participant_id", "source_frame_index", "delta_time_s", "timestamp_source",
                    "target_status", "pose_present", "target_confidence"]
        return parquet.read(columns=[
            column for column in (*required, *landmarks, *optional) if column in available
        ]).to_pandas()


def validate_frame_dataframe(df: pd.DataFrame) -> None:
    required = [*RECORDING_IDS, "frame_id", "timestamp_s"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Missing required identifiers: {missing}")
    if df.empty:
        raise ValueError("Frame DataFrame is empty.")
    if df.columns.duplicated().any():
        duplicates = df.columns[df.columns.duplicated()].tolist()
        raise ValueError(f"Duplicate feature columns detected: {duplicates}")
    for column in RECORDING_IDS:
        values = df[column].astype("string").str.strip().fillna("")
        if values.eq("").any() or values.nunique() != 1:
            raise ValueError(f"{column} must identify one recording consistently.")
    frame_ids = pd.to_numeric(df["frame_id"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    if not np.array_equal(frame_ids, np.arange(len(df))):
        raise ValueError("frame_id must contain contiguous integers from 0 to frame_count-1.")
    if "source_frame_index" in df:
        source_frames = pd.to_numeric(df["source_frame_index"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
        if (not np.isfinite(source_frames).all() or (source_frames < 0).any()
                or (source_frames != np.floor(source_frames)).any() or (np.diff(source_frames) <= 0).any()):
            raise ValueError("source_frame_index must contain increasing nonnegative integers.")

    timestamps = pd.to_numeric(df["timestamp_s"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    if not np.isfinite(timestamps).all() or (timestamps < 0).any():
        raise ValueError("timestamp_s must be finite and nonnegative.")
    intervals = np.diff(timestamps)
    if (intervals <= 0).any():
        raise ValueError("timestamp_s must be strictly increasing.")
    if "delta_time_s" in df.columns:
        if not pd.isna(df["delta_time_s"].iloc[0]):
            raise ValueError("delta_time_s must be null/NaN for the first frame.")
        delta = pd.to_numeric(df["delta_time_s"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)[1:]
        if (delta <= 0).any() or not np.allclose(delta, intervals, rtol=1e-6, atol=1e-9):
            raise ValueError("delta_time_s must match elapsed time between source frames.")
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
        if tracked.any() and ("pose_present" not in df
                              or (pd.to_numeric(df.loc[tracked, "pose_present"], errors="coerce").fillna(0) != 1).any()):
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

    landmarks = _read_validation_frame_table(landmarks_path)
    features = _read_validation_frame_table(features_path)
    validate_frame_dataframe(landmarks)
    validate_frame_dataframe(features)
    if len(landmarks) != len(features):
        raise ValueError(
            f"Row-count mismatch: landmarks={len(landmarks)}, features={len(features)}"
        )
    for column in (*RECORDING_IDS, "participant_id"):
        if column in landmarks and column in features:
            if not landmarks[column].astype("string").fillna("").equals(features[column].astype("string").fillna("")):
                raise ValueError(f"Landmarks and features disagree on {column}.")
    for column in ("timestamp_s", "source_frame_index"):
        if column in landmarks and column in features:
            if not np.array_equal(pd.to_numeric(landmarks[column]), pd.to_numeric(features[column])):
                raise ValueError(f"Landmarks and features disagree on {column}.")
    cap = cv2.VideoCapture(str(processed_video))
    try:
        if not cap.isOpened():
            raise ValueError(f"Cannot open skeleton video: {processed_video}")
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count != len(features):
            raise ValueError(
                f"Skeleton video has {frame_count} frames but features have {len(features)}: "
                f"{processed_video}"
            )
        first_ok, _ = cap.read()
        if not first_ok:
            raise ValueError(f"Cannot decode the first skeleton video frame: {processed_video}")
        if frame_count > 1:
            last_ok = cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count - 1) and cap.read()[0]
            if not last_ok:
                raise ValueError(f"Cannot decode the last skeleton video frame: {processed_video}")
    finally:
        cap.release()
