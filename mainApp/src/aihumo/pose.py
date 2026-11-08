from __future__ import annotations

import logging
import numbers
from pathlib import Path
from typing import Callable, Iterator

import cv2
import mediapipe as mp
import numpy as np
import pandas as pd

from .tracking import TargetStatus, TargetTracker

LOGGER = logging.getLogger(__name__)
LANDMARK_COUNT = 33
ProgressCallback = Callable[[float, str], None]


class _GrowableFrameBuffer:
    """Typed NumPy-backed row buffer used during sequential video capture.

    String/status fields remain Python lists, while all frame measurements and
    landmark values use expandable NumPy arrays. This avoids retaining one
    dictionary per frame and still produces the same DataFrame contract.
    """

    def __init__(self, first_row: dict, initial_capacity: int = 4096):
        self.capacity = max(1, int(initial_capacity))
        self.size = 0
        self.numeric: dict[str, np.ndarray] = {}
        self.other: dict[str, list] = {}
        for key, value in first_row.items():
            if isinstance(value, (numbers.Real, np.number, bool)):
                dtype = np.bool_ if isinstance(value, (bool, np.bool_)) else np.float64
                self.numeric[key] = np.empty(self.capacity, dtype=dtype)
            else:
                self.other[key] = []

    def _grow(self) -> None:
        new_capacity = self.capacity * 2
        for key, values in self.numeric.items():
            expanded = np.empty(new_capacity, dtype=values.dtype)
            expanded[: self.size] = values[: self.size]
            self.numeric[key] = expanded
        self.capacity = new_capacity

    def append(self, row: dict) -> None:
        if self.size >= self.capacity:
            self._grow()
        for key, values in self.numeric.items():
            values[self.size] = row.get(key, np.nan)
        for key, values in self.other.items():
            values.append(row.get(key))
        self.size += 1

    def to_dataframe(self) -> pd.DataFrame:
        data = {key: values[: self.size] for key, values in self.numeric.items()}
        data.update(self.other)
        return pd.DataFrame(data)


def _emit(callback: ProgressCallback | None, fraction: float, message: str) -> None:
    if callback:
        callback(float(max(0.0, min(1.0, fraction))), message)


def _make_landmarker(model_path: str | Path, cfg: dict):
    options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=max(1, int(cfg.get("num_poses", 1))),
        min_pose_detection_confidence=float(cfg.get("min_pose_detection_confidence", 0.5)),
        min_pose_presence_confidence=float(cfg.get("min_pose_presence_confidence", 0.5)),
        min_tracking_confidence=float(cfg.get("min_tracking_confidence", 0.5)),
    )
    return mp.tasks.vision.PoseLandmarker.create_from_options(options)


def inspect_video(video_path: str | Path) -> dict:
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Source video does not exist: {video_path}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open source video: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    codec_int = int(cap.get(cv2.CAP_PROP_FOURCC) or 0)
    codec = "".join(chr((codec_int >> (8 * i)) & 0xFF) for i in range(4)).strip("\x00") or None
    duration = frame_count / fps if fps > 0 else 0.0
    cap.release()

    if frame_count <= 0:
        raise ValueError(f"Source video contains no frames: {video_path}")
    if fps <= 0:
        raise ValueError(f"Could not determine a valid source FPS: {video_path}")
    if width <= 0 or height <= 0:
        raise ValueError(f"Could not determine source resolution: {video_path}")

    return {
        "width": width,
        "height": height,
        "source_fps": fps,
        "frame_count": frame_count,
        "duration_s": duration,
        "codec": codec,
        "frame_interval_s": 1.0 / fps,
    }


def _pose_to_array(pose_landmarks) -> np.ndarray:
    points = np.full((LANDMARK_COUNT, 3), np.nan, dtype=float)
    for index in range(min(LANDMARK_COUNT, len(pose_landmarks))):
        point = pose_landmarks[index]
        points[index] = [float(point.x), float(point.y), float(point.z)]
    return points


def _pose_quality(pose_landmarks) -> float:
    values = []
    for point in pose_landmarks:
        visibility = float(getattr(point, "visibility", np.nan))
        presence = float(getattr(point, "presence", np.nan))
        if np.isfinite(visibility):
            values.append(visibility)
        elif np.isfinite(presence):
            values.append(presence)
    if not values:
        return float(np.isfinite([point.x for point in pose_landmarks]).mean())
    return float(np.clip(np.nanmean(values), 0.0, 1.0))


def _write_pose_row(row: dict, pose_landmarks, world_landmarks) -> None:
    if pose_landmarks is None:
        for i in range(LANDMARK_COUNT):
            row[f"lm{i}_x"] = np.nan
            row[f"lm{i}_y"] = np.nan
            row[f"lm{i}_z"] = np.nan
            row[f"lm{i}_visibility"] = np.nan
            row[f"lm{i}_presence"] = np.nan
    else:
        for i in range(LANDMARK_COUNT):
            point = pose_landmarks[i]
            row[f"lm{i}_x"] = float(point.x)
            row[f"lm{i}_y"] = float(point.y)
            row[f"lm{i}_z"] = float(point.z)
            row[f"lm{i}_visibility"] = float(getattr(point, "visibility", np.nan))
            row[f"lm{i}_presence"] = float(getattr(point, "presence", np.nan))

    for i in range(LANDMARK_COUNT):
        if world_landmarks is not None:
            point = world_landmarks[i]
            row[f"world{i}_x"] = float(point.x)
            row[f"world{i}_y"] = float(point.y)
            row[f"world{i}_z"] = float(point.z)
        else:
            row[f"world{i}_x"] = np.nan
            row[f"world{i}_y"] = np.nan
            row[f"world{i}_z"] = np.nan


def iter_landmark_rows(
    video_path: str | Path,
    model_path: str | Path,
    pose_cfg: dict,
    identifiers: dict,
    video_info: dict | None = None,
    *,
    tracking_cfg: dict | None = None,
    tracker: TargetTracker | None = None,
    start_frame: int = 0,
    end_frame: int | None = None,
    previous_timestamp_s: float | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Iterator[dict]:
    """Yield regular MediaPipe pose rows without performing final Parquet I/O.

    The default ``single_pose`` mode uses MediaPipe's pose result independently
    on every frame. It does not establish a persistent bounding-box search
    region. The old target-association tracker remains available only when
    ``tracking.mode`` is explicitly ``target_association``.
    """
    video_path = Path(video_path)
    video_info = video_info or inspect_video(video_path)
    source_fps = float(video_info["source_fps"])
    declared_frame_count = int(video_info["frame_count"])
    start_frame = max(0, int(start_frame))
    stop_frame = declared_frame_count if end_frame is None else min(int(end_frame), declared_frame_count)
    if start_frame >= stop_frame:
        return

    tracking_cfg = tracking_cfg or {}
    tracking_enabled = bool(
        tracking_cfg.get("enabled", False)
        and tracking_cfg.get("mode", "single_pose") == "target_association"
    )
    if tracking_enabled:
        tracker = tracker or TargetTracker(tracking_cfg)
        # Multi-pose inference is required for identity matching. Keep the user's
        # configured value when it is already >= 2; otherwise use the tracker cap.
        pose_cfg = dict(pose_cfg)
        pose_cfg["num_poses"] = max(2, int(pose_cfg.get("num_poses", 1)), int(tracking_cfg.get("max_poses", 2)))
    else:
        tracker = None

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open source video: {video_path}")
    try:
        if start_frame and not cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame):
            raise RuntimeError(f"Could not seek to checkpoint frame {start_frame}: {video_path}")
        with _make_landmarker(model_path, pose_cfg) as landmarker:
            frame_idx = start_frame
            last_timestamp_s = previous_timestamp_s
            last_inference_ms = -1
            while frame_idx < stop_frame:
                if cancel_check and cancel_check():
                    raise InterruptedError("Video processing was cancelled.")

                ok, frame_bgr = cap.read()
                if not ok:
                    raise RuntimeError(
                        f"Could not read source frame {frame_idx}; expected frames through {stop_frame - 1}."
                    )

                decoder_timestamp_s = float(cap.get(cv2.CAP_PROP_POS_MSEC)) / 1000.0
                if (np.isfinite(decoder_timestamp_s) and decoder_timestamp_s >= 0
                        and (last_timestamp_s is None or decoder_timestamp_s > last_timestamp_s)):
                    timestamp_s = decoder_timestamp_s
                    timestamp_source = "decoder"
                else:
                    # Anchor fallback to the last accepted source timestamp. An
                    # irregular stream can be ahead of frame_idx / source_fps.
                    timestamp_s = (frame_idx / source_fps if last_timestamp_s is None
                                   else last_timestamp_s + 1.0 / source_fps)
                    timestamp_source = "fps_estimate"
                delta_time_s = np.nan if last_timestamp_s is None else timestamp_s - last_timestamp_s
                last_timestamp_s = timestamp_s
                # MediaPipe requires increasing integer milliseconds. Preserve
                # the higher precision source timestamps in the frame table.
                timestamp_ms = max(last_inference_ms + 1, int(round(timestamp_s * 1000.0)))
                last_inference_ms = timestamp_ms
                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                result = landmarker.detect_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb),
                    timestamp_ms,
                )

                poses = result.pose_landmarks or []
                worlds = result.pose_world_landmarks or []
                row = {
                    **identifiers,
                    "frame_id": frame_idx,
                    "source_frame_index": frame_idx,
                    "timestamp_s": timestamp_s,
                    "delta_time_s": delta_time_s,
                    "timestamp_source": timestamp_source,
                    "timestamp_quality": "source_pts" if timestamp_source == "decoder" else "fps_fallback",
                    "fps": source_fps,
                    "pose_present": 0,
                    "detected_pose_count": int(len(poses)),
                    "target_track_id": np.nan,
                    "target_confidence": 0.0,
                    "target_status": TargetStatus.SEARCHING.value if tracking_enabled else TargetStatus.TRACKED.value,
                    "pose_confidence": 0.0,
                    "occlusion_ratio": 0.0,
                    "reacquisition_flag": False,
                    "target_selection_method": "auto_primary_participant" if tracking_enabled else "single_pose",
                }
                if tracking_enabled:
                    row.update({
                        "target_bbox_x1": np.nan,
                        "target_bbox_y1": np.nan,
                        "target_bbox_x2": np.nan,
                        "target_bbox_y2": np.nan,
                    })

                target_pose = None
                target_world = None
                if tracking_enabled:
                    candidates = []
                    for index, pose in enumerate(poses):
                        candidate = tracker.candidate_from_landmarks(_pose_to_array(pose))
                        if candidate is not None:
                            # Appearance is deliberately computed only for candidates.
                            if bool(tracking_cfg.get("use_appearance", True)):
                                candidate = type(candidate)(
                                    candidate.landmarks,
                                    candidate.bbox,
                                    candidate.pose_quality,
                                    tracker._appearance_signature(frame_bgr, candidate.bbox),
                                )
                            candidates.append((index, candidate))
                    decision = tracker.update([candidate for _, candidate in candidates], frame_idx)
                    row["target_track_id"] = float(decision.target_track_id) if decision.target_track_id is not None else np.nan
                    row["target_confidence"] = decision.target_confidence
                    row["target_status"] = decision.status.value
                    row["pose_confidence"] = decision.pose_confidence
                    row["occlusion_ratio"] = decision.occlusion_ratio
                    row["reacquisition_flag"] = decision.reacquisition_flag
                    row["target_selection_method"] = decision.target_selection_method
                    if decision.bbox is not None:
                        row["target_bbox_x1"], row["target_bbox_y1"], row["target_bbox_x2"], row["target_bbox_y2"] = decision.bbox

                    # The tracker currently associates the target internally. Find the
                    # matching candidate by comparing the chosen track's current pose.
                    if decision.target_track_id is not None and decision.status in {TargetStatus.TRACKED, TargetStatus.REACQUIRED}:
                        target_track = tracker.tracks.get(decision.target_track_id)
                        if target_track is not None:
                            best_index = None
                            best_error = float("inf")
                            for candidate_index, candidate in candidates:
                                error = np.nanmean(np.linalg.norm(
                                    candidate.landmarks[:, :2] - target_track.landmarks[:, :2], axis=1
                                ))
                                if np.isfinite(error) and error < best_error:
                                    best_error = error
                                    best_index = candidate_index
                            if best_index is not None:
                                target_pose = poses[candidates[best_index][0]]
                                target_world = worlds[candidates[best_index][0]] if candidates[best_index][0] < len(worlds) else None
                else:
                    if poses:
                        target_pose = poses[0]
                        target_world = worlds[0] if worlds else None
                        row["pose_present"] = 1
                        row["target_status"] = TargetStatus.TRACKED.value
                        row["pose_confidence"] = _pose_quality(target_pose)
                        row["target_confidence"] = row["pose_confidence"]
                        row["target_track_id"] = 1.0
                        # Single-pose mode intentionally does not create or
                        # persist a subject-search bounding box.
                    else:
                        # A single-pose frame with no MediaPipe result is not a
                        # tracked frame. Keeping it as tracked makes validation
                        # reject the recording because its landmark columns are
                        # necessarily NaN.
                        row["target_status"] = TargetStatus.SEARCHING.value

                if target_pose is not None and row["target_status"] in {
                    TargetStatus.TRACKED.value,
                    TargetStatus.REACQUIRED.value,
                }:
                    row["pose_present"] = 1
                    _write_pose_row(row, target_pose, target_world)
                else:
                    _write_pose_row(row, None, None)

                yield row
                frame_idx += 1
                if frame_idx == start_frame + 1 or frame_idx % 30 == 0 or frame_idx == stop_frame:
                    _emit(
                        progress_callback,
                        frame_idx / max(1, declared_frame_count),
                        f"Pose/tracking: frame {frame_idx}/{declared_frame_count}",
                    )
    finally:
        cap.release()


def extract_landmarks_dataframe(
    video_path: str | Path,
    model_path: str | Path,
    pose_cfg: dict,
    identifiers: dict,
    video_info: dict | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_check: Callable[[], bool] | None = None,
    tracking_cfg: dict | None = None,
    tracker: TargetTracker | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Extract one complete frame table in memory; no final Parquet I/O occurs here."""
    video_info = video_info or inspect_video(video_path)
    rows = iter_landmark_rows(
        video_path,
        model_path,
        pose_cfg,
        identifiers,
        video_info,
        tracking_cfg=tracking_cfg,
        tracker=tracker,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )
    first_row = next(rows, None)
    if first_row is None:
        raise ValueError(f"MediaPipe produced no frames for: {video_path}")
    buffer = _GrowableFrameBuffer(first_row)
    buffer.append(first_row)
    for row in rows:
        buffer.append(row)
    df = buffer.to_dataframe()
    if df.empty:
        raise ValueError(f"MediaPipe produced no frames for: {video_path}")
    LOGGER.info("MediaPipe extraction complete: %d frames", len(df))
    return df, {
        **video_info,
        "frames_processed": len(df),
        "pose_frames": int(df["pose_present"].sum()),
        "tracked_frames": int(df["target_status"].isin([TargetStatus.TRACKED.value, TargetStatus.REACQUIRED.value]).sum())
        if "target_status" in df.columns else int(df["pose_present"].sum()),
    }


def extract_landmarks(
    video_path: str | Path,
    output_path: str | Path,
    session_id: str,
    video_id: str,
    camera_id: str,
    model_path: str,
    pose_cfg: dict,
    target_fps: float | None = None,
) -> dict:
    """Backward-compatible raw-landmark extraction entry point."""
    from .storage import save_parquet

    info = inspect_video(video_path)
    if target_fps is not None and info["source_fps"] <= 0:
        info["source_fps"] = float(target_fps)
    tracking_cfg = pose_cfg.get("tracking", {}) if isinstance(pose_cfg, dict) else {}
    df, result = extract_landmarks_dataframe(
        video_path,
        model_path,
        pose_cfg,
        {"session_id": session_id, "video_id": video_id, "camera_id": camera_id},
        info,
        tracking_cfg=tracking_cfg,
    )
    save_parquet(df, output_path)
    return {
        "video_id": video_id,
        "frames": len(df),
        "source_fps": result["source_fps"],
        "output": str(output_path),
    }
