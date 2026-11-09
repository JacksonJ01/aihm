from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

UNKNOWN = "unknown"


def _majority(series: pd.Series) -> str:
    values = series.dropna().astype(str)
    values = values[values != UNKNOWN]
    return str(values.mode().iloc[0]) if not values.empty else UNKNOWN


def _infer_fps(df: pd.DataFrame) -> float:
    if "fps" in df.columns:
        fps = pd.to_numeric(df["fps"], errors="coerce").dropna()
        if not fps.empty and np.isfinite(fps.iloc[0]) and float(fps.iloc[0]) > 0:
            return float(fps.iloc[0])
    timestamps = pd.to_numeric(df["timestamp_s"], errors="coerce").to_numpy(dtype=float)
    dt = np.diff(timestamps)
    valid = dt[np.isfinite(dt) & (dt > 0)]
    if valid.size == 0:
        raise ValueError("Cannot infer FPS from timestamps.")
    return float(1.0 / np.median(valid))


def _prepare_window_features(
    source_times: np.ndarray, matrix: np.ndarray, valid_pose: np.ndarray,
    target_times: np.ndarray, max_gap: float,
) -> np.ndarray:
    """Interpolate adjacent native observations together, preserving the zero fill for missing inputs."""
    right = source_times.searchsorted(target_times).clip(0, len(source_times) - 1)
    left = (right - 1).clip(0)
    # Accept an exact sample from either side despite floating-point rounding.
    exact_right = np.abs(target_times - source_times[right]) <= 1e-9
    exact_left = np.abs(target_times - source_times[left]) <= 1e-9
    right = np.where(exact_left & ~exact_right, left, right)
    left = np.where(exact_left | exact_right, right, left)
    elapsed = source_times[right] - source_times[left]
    in_range = (target_times >= source_times[0] - 1e-9) & (target_times <= source_times[-1] + 1e-9)
    valid_time = in_range & (elapsed <= max_gap) & valid_pose[left] & valid_pose[right]
    fraction = np.divide(target_times - source_times[left], elapsed, out=np.zeros_like(target_times), where=elapsed > 0)
    start, finish = matrix[left], matrix[right]
    with np.errstate(invalid="ignore"):
        samples = (1 - fraction[:, None]) * start + fraction[:, None] * finish
    return np.where(valid_time[:, None] & np.isfinite(samples), samples, 0).astype(np.float32)


def _nearest_sequence_labels(source_times: np.ndarray, values: list[str], target_times: np.ndarray) -> list[str]:
    if len(values) == 0:
        return [UNKNOWN] * len(target_times)
    indices = np.searchsorted(source_times, target_times, side="left")
    indices = np.clip(indices, 0, len(source_times) - 1)
    previous = np.maximum(indices - 1, 0)
    choose_previous = np.abs(target_times - source_times[previous]) <= np.abs(target_times - source_times[indices])
    indices = np.where(choose_previous, previous, indices)
    return [str(values[index]) for index in indices]


def _nearest_binary_labels(source_times: np.ndarray, values: np.ndarray, target_times: np.ndarray) -> np.ndarray:
    if len(values) == 0:
        return np.zeros(len(target_times), dtype=np.int64)
    indices = np.searchsorted(source_times, target_times, side="left")
    indices = np.clip(indices, 0, len(source_times) - 1)
    previous = np.maximum(indices - 1, 0)
    nearest = np.where(
        np.abs(target_times - source_times[previous]) <= np.abs(target_times - source_times[indices]),
        previous,
        indices,
    )
    output = values[nearest].astype(np.int64, copy=True)

    # Preserve a narrow positive band around sparse source boundaries. This is
    # helpful when source and model FPS differ slightly.
    max_gap = 0.5 / max(1.0, 1.0 / np.median(np.diff(source_times))) if len(source_times) > 1 else 0.02
    for source_index in np.flatnonzero(values > 0):
        close = np.abs(target_times - source_times[source_index]) <= max_gap
        output[close] = 1
    return output


@dataclass(frozen=True)
class WindowRecord:
    X: np.ndarray
    targets: dict[str, Any]
    metadata: dict[str, Any]


def generate_window_records(
    df: pd.DataFrame,
    feature_cols: list[str],
    *,
    window_seconds: float,
    stride_seconds: float,
    min_valid_pose_fraction: float = 0.8,
    target_specs: dict[str, dict[str, Any]] | None = None,
    model_fps: float | None = None,
) -> list[WindowRecord]:
    """Generate fixed-duration model windows using a canonical sampling rate.

    Feature extraction never assumes a nominal FPS. Dataset generation may choose
    a canonical `model_fps` so recordings from different source FPS values produce
    tensors with identical temporal dimensions. Labels are joined in memory and
    sampled/aggregated only for the current window.
    """
    if df.empty:
        return []
    if not np.isfinite([window_seconds, stride_seconds]).all() or window_seconds <= 0 or stride_seconds <= 0:
        raise ValueError("window_seconds and stride_seconds must be finite and positive.")
    if not feature_cols:
        raise ValueError("feature_cols cannot be empty.")
    if "timestamp_s" not in df.columns:
        raise ValueError("timestamp_s is required for window generation.")

    timestamps = pd.to_numeric(df["timestamp_s"], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(timestamps).all():
        raise ValueError("timestamps must be finite.")
    if np.any(np.diff(timestamps) < 0):
        order = np.argsort(timestamps, kind="stable")
        timestamps = timestamps[order]
        df = df.iloc[order]
    if np.any(np.diff(timestamps) <= 0):
        raise ValueError("timestamps must be strictly increasing after ordering.")
    source_fps = _infer_fps(df)
    canonical_fps = float(model_fps if model_fps is not None else source_fps)
    if not np.isfinite(canonical_fps) or canonical_fps <= 0:
        raise ValueError("model_fps must be finite and positive when supplied.")

    window_frames = max(1, int(round(float(window_seconds) * canonical_fps)))
    stride_seconds = float(stride_seconds)
    duration = float(timestamps[-1] - timestamps[0])
    if duration + 1e-9 < window_seconds:
        return []

    target_specs = target_specs or {}
    features = df[feature_cols]
    if not all(pd.api.types.is_numeric_dtype(dtype) for dtype in features.dtypes):
        features = features.apply(pd.to_numeric, errors="coerce")
    matrix = features.to_numpy(dtype=np.float32, na_value=np.nan)
    valid_pose = (pd.to_numeric(df["pose_present"], errors="coerce").fillna(0).to_numpy() > 0
                  if "pose_present" in df else np.ones(len(df), dtype=bool))
    grid = np.arange(window_frames, dtype=float) / canonical_fps
    max_gap = 3.0 / source_fps
    records: list[WindowRecord] = []
    last_start = float(timestamps[-1] - window_seconds)
    start_time = float(timestamps[0])
    epsilon = max(1e-9, stride_seconds * 1e-6)

    while start_time <= last_start + epsilon:
        end_time = start_time + float(window_seconds)
        left = int(np.searchsorted(timestamps, start_time - 1e-9, side="left"))
        right = int(np.searchsorted(timestamps, end_time + 1e-9, side="right"))
        chunk = df.iloc[left:right]
        if len(chunk) < 2:
            start_time += stride_seconds
            continue

        valid_fraction = float(valid_pose[left:right].mean())
        if valid_fraction < float(min_valid_pose_fraction):
            start_time += stride_seconds
            continue

        # Sample features at a fixed temporal grid. This guarantees every sample
        # has the same [T, F] shape even when source videos use different FPS.
        target_times = np.minimum(start_time + grid, end_time)
        chunk_times = timestamps[left:right]
        X = _prepare_window_features(chunk_times, matrix[left:right], valid_pose[left:right], target_times, max_gap)

        targets: dict[str, Any] = {}
        coverage: dict[str, float] = {}
        for name, spec in target_specs.items():
            if not bool(spec.get("enabled", True)):
                continue
            task = str(spec.get("task", "classification"))
            column = str(spec.get("frame_column", f"{name}_label"))
            if task == "sequence_classification":
                values = chunk[column].fillna(UNKNOWN).astype(str).tolist() if column in chunk else [UNKNOWN] * len(chunk)
                targets[name] = _nearest_sequence_labels(chunk_times, values, target_times)
                coverage[name] = float(sum(value != UNKNOWN for value in values) / max(1, len(values)))
            elif task == "sequence_binary":
                source_values = pd.to_numeric(chunk[column], errors="coerce").fillna(0).astype(np.int64).to_numpy() if column in chunk else np.zeros(len(chunk), dtype=np.int64)
                targets[name] = _nearest_binary_labels(chunk_times, source_values, target_times)
                coverage[name] = 1.0
            elif task == "classification":
                values = chunk[column] if column in chunk else pd.Series([UNKNOWN] * len(chunk), index=chunk.index)
                string_values = values.fillna(UNKNOWN).astype(str)
                targets[name] = _majority(values)
                known = string_values != UNKNOWN
                coverage[name] = float(known.mean())
                majority = targets[name]
                if majority != UNKNOWN:
                    spec_consistency = float((string_values[known] == majority).mean()) if known.any() else 0.0
                else:
                    spec_consistency = 0.0
                targets.setdefault("_consistency", {})[name] = spec_consistency
            elif task == "regression":
                if column in chunk:
                    values = pd.to_numeric(chunk[column], errors="coerce").to_numpy(dtype=float)
                    finite = np.isfinite(values)
                    targets[name] = float(values[finite].mean()) if finite.any() else None
                    coverage[name] = float(finite.mean())
                else:
                    targets[name], coverage[name] = None, 0.0
            elif task in {"identity", "evaluation_only"}:
                continue
            else:
                raise ValueError(f"Unsupported dataset target task: {task}")

        targets["_coverage"] = coverage
        metadata = {
            "session_id": str(chunk["session_id"].iloc[0]),
            "video_id": str(chunk["video_id"].iloc[0]),
            "participant_id": str(chunk["participant_id"].iloc[0]) if "participant_id" in chunk else "",
            "camera_id": str(chunk["camera_id"].iloc[0]),
            "start_frame": int(chunk["frame_id"].iloc[0]),
            "end_frame": int(chunk["frame_id"].iloc[-1]),
            "start_time_s": start_time,
            "end_time_s": end_time,
            "window_seconds": float(window_seconds),
            "stride_seconds": stride_seconds,
            "source_fps": source_fps,
            "model_fps": canonical_fps,
            "valid_pose_fraction": valid_fraction,
            "set_ids": sorted({int(v) for v in pd.to_numeric(chunk.get("set_id_target", pd.Series(dtype=float)), errors="coerce").dropna().unique() if int(v) >= 1}),
            "rep_ids": sorted({int(v) for v in pd.to_numeric(chunk.get("rep_id_target", pd.Series(dtype=float)), errors="coerce").dropna().unique() if int(v) >= 1}),
        }
        records.append(WindowRecord(X=X, targets=targets, metadata=metadata))
        start_time += stride_seconds

    return records


def generate_windows(
    df: pd.DataFrame,
    feature_cols: list[str],
    window_seconds: float,
    stride_seconds: float,
    min_valid_pose_fraction: float = 0.8,
):
    """Backward-compatible generator returning X plus metadata."""
    records = generate_window_records(
        df,
        feature_cols,
        window_seconds=window_seconds,
        stride_seconds=stride_seconds,
        min_valid_pose_fraction=min_valid_pose_fraction,
        target_specs={},
    )
    if not records:
        source_fps = _infer_fps(df) if not df.empty else 1.0
        window_frames = max(1, int(round(window_seconds * source_fps)))
        return np.empty((0, window_frames, len(feature_cols)), dtype=np.float32), []
    X = np.stack([record.X for record in records]).astype(np.float32)
    return X, [record.metadata for record in records]


def save_windows(
    X: np.ndarray,
    metadata: list[dict],
    output_prefix: str | Path,
    targets: dict[str, np.ndarray] | None = None,
) -> None:
    """Save a per-video window artifact for compatibility/debugging."""
    output_prefix = Path(output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    payload = {"X": X}
    if targets:
        payload.update({f"target_{name}": value for name, value in targets.items()})
    np.savez_compressed(output_prefix.with_suffix(".npz"), **payload)
    output_prefix.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
