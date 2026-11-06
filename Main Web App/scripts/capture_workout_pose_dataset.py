from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTRACTOR_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "extract_workout_pose_dataset.py"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "generated" / "custom-training"
DEFAULT_WINDOW_DURATIONS = (5.0, 10.0, 15.0)
DEFAULT_FEATURE_TARGET_SIZE = 200
DEFAULT_CAMERA_INDEX = 0
SCHEMA_VERSION = 1

ANGLE_LABELS = {
    "left_low",
    "left_center",
    "left_high",
    "center_low",
    "center_center",
    "center_high",
    "right_low",
    "right_center",
    "right_high",
}


def load_script_module(module_name: str, script_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script module: {script_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


extractor = load_script_module("workout_extract_capture_runtime", EXTRACTOR_SCRIPT_PATH)


@dataclass(frozen=True)
class SegmentSpec:
    exercise_key: str
    angle_label: str
    duration_seconds: float
    reps_count: int | None
    notes: str | None


def portable_path(value: Path) -> str:
    return value.resolve().as_posix()


def normalize_angle_label(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in ANGLE_LABELS:
        raise ValueError(
            "Invalid --angle-label. Choose one of: "
            + ", ".join(sorted(ANGLE_LABELS))
        )
    return normalized


def split_angle_label(angle_label: str) -> tuple[str, str]:
    side, vertical = angle_label.split("_", 1)
    # Folder naming prefers low/mid/high while CLI accepts low/center/high.
    vertical_folder = "mid" if vertical == "center" else vertical
    return side, vertical_folder


def resolve_exercise(value: str):
    normalized = extractor.normalize_name(value)

    for exercise in extractor.WORKOUT_EXERCISE_CATALOG:
        if normalized in {
            extractor.normalize_name(exercise.key),
            extractor.normalize_name(exercise.folder_name),
            extractor.normalize_name(exercise.label),
            *[extractor.normalize_name(alias) for alias in exercise.aliases],
        }:
            return exercise

    raise ValueError(f"Unknown exercise: {value}")


def parse_duration_list(value: str) -> list[float]:
    items = [part.strip() for part in value.split(",") if part.strip()]
    if not items:
        raise ValueError("--window-durations must include at least one value")

    durations: list[float] = []
    for item in items:
        parsed = float(item)
        if parsed <= 0:
            raise ValueError("window durations must be greater than 0")
        durations.append(parsed)
    return durations


def duration_folder_name(duration_seconds: float) -> str:
    rounded = int(round(duration_seconds))
    if abs(duration_seconds - rounded) < 1e-6:
        return f"{rounded}s"
    return f"{duration_seconds:g}s"


def normalize_exercise_folder_name(value: str) -> str:
    return "-".join(extractor.normalize_name(value).split())


def parse_segments_file(segments_file: Path) -> list[dict[str, Any]]:
    payload = json.loads(segments_file.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict) and isinstance(payload.get("segments"), list):
        return payload["segments"]

    raise ValueError("Segments file must be a JSON array or an object with a 'segments' array")


def load_segments(args: argparse.Namespace) -> list[SegmentSpec]:
    if args.segments_file is None:
        exercise = resolve_exercise(args.exercise)
        return [
            SegmentSpec(
                exercise_key=exercise.key,
                angle_label=normalize_angle_label(args.angle_label),
                duration_seconds=float(args.duration_seconds),
                reps_count=args.reps_count,
                notes=args.notes,
            )
        ]

    rows = parse_segments_file(args.segments_file)
    segments: list[SegmentSpec] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each segment entry must be an object")

        exercise = resolve_exercise(str(row.get("exercise", row.get("exerciseKey", ""))))
        angle_label = normalize_angle_label(str(row.get("angleLabel", args.angle_label)))
        duration_seconds = float(row.get("durationSeconds", args.duration_seconds))
        if duration_seconds <= 0:
            raise ValueError("Segment durationSeconds must be greater than 0")

        reps_value = row.get("repsCount", None)
        reps_count = None if reps_value is None else int(reps_value)
        notes_value = row.get("notes", None)
        notes = None if notes_value is None else str(notes_value)

        segments.append(
            SegmentSpec(
                exercise_key=exercise.key,
                angle_label=angle_label,
                duration_seconds=duration_seconds,
                reps_count=reps_count,
                notes=notes,
            )
        )

    return segments


def safe_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if parsed != parsed:
        return 0.0
    return parsed


def angle_stats(window_frames: list[dict[str, Any]], angle_names: list[str], key: str) -> list[float]:
    stats: list[float] = []
    for angle_name in angle_names:
        values = [
            safe_float(frame[key].get(angle_name))
            for frame in window_frames
            if frame.get(key, {}).get(angle_name) is not None
        ]
        if not values:
            stats.extend([0.0, 0.0, 0.0, 0.0, 0.0])
            continue

        mean_value = sum(values) / len(values)
        variance = sum((value - mean_value) ** 2 for value in values) / len(values)
        velocity_values = [abs(values[index] - values[index - 1]) for index in range(1, len(values))]
        velocity_mean = sum(velocity_values) / len(velocity_values) if velocity_values else 0.0
        stats.extend(
            [
                safe_float(mean_value),
                safe_float(variance ** 0.5),
                safe_float(min(values)),
                safe_float(max(values)),
                safe_float(velocity_mean),
            ]
        )
    return stats


def build_fixed_feature_vector(
    window: dict[str, Any],
    window_frames: list[dict[str, Any]],
    feature_target_size: int,
) -> list[float]:
    angle_names = list(extractor.ANGLE_DEFINITIONS.keys())
    pose_scores = [safe_float(frame.get("poseScore")) for frame in window_frames if frame.get("poseScore") is not None]
    pose_mean = sum(pose_scores) / len(pose_scores) if pose_scores else 0.0
    pose_variance = sum((score - pose_mean) ** 2 for score in pose_scores) / len(pose_scores) if pose_scores else 0.0

    base_features: list[float] = []
    base_features.extend(safe_float(value) for value in (window.get("targetAngles2dVector") or []))
    base_features.extend(safe_float(value) for value in (window.get("targetAngles3dVector") or []))
    base_features.extend(
        [
            safe_float(window.get("visibleFrameRatio")),
            safe_float(window.get("averagePoseScore")),
            safe_float(window.get("frameCount")),
            safe_float(window.get("windowSeconds")),
            safe_float(window.get("strideSeconds")),
            safe_float(window.get("contractionScore2d")),
            safe_float(window.get("contractionScore3d")),
            safe_float(window.get("contractionScore")),
            safe_float(window.get("contractionStateValue")),
        ]
    )

    aggregate_features: list[float] = []
    aggregate_features.extend(angle_stats(window_frames, angle_names, "angles2d"))
    aggregate_features.extend(angle_stats(window_frames, angle_names, "angles3d"))
    aggregate_features.extend(
        [
            safe_float(pose_mean),
            safe_float(pose_variance ** 0.5),
            safe_float(min(pose_scores) if pose_scores else 0.0),
            safe_float(max(pose_scores) if pose_scores else 0.0),
        ]
    )

    values = [safe_float(value) for value in [*base_features, *aggregate_features]]
    if len(values) >= feature_target_size:
        return values[:feature_target_size]

    return values + ([0.0] * (feature_target_size - len(values)))


def clip_id_for_segment(segment: SegmentSpec, timestamp_text: str) -> str:
    payload = f"{segment.exercise_key}|{segment.angle_label}|{segment.duration_seconds}|{segment.reps_count}|{timestamp_text}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def collect_segment_frames(
    capture: cv2.VideoCapture,
    pose: Any,
    segment: SegmentSpec,
    frame_index_start: int,
    stream_start_ms: float,
) -> tuple[list[dict[str, Any]], int]:
    frames: list[dict[str, Any]] = []
    frame_index = frame_index_start
    segment_started = time.perf_counter()

    while True:
        success, frame = capture.read()
        if not success:
            break

        now_ms = (time.perf_counter() * 1000.0) - stream_start_ms
        elapsed_seconds = (time.perf_counter() - segment_started)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = extractor.mp.Image(image_format=extractor.mp.ImageFormat.SRGB, data=rgb_frame)

        results = pose.detect_for_video(mp_image, int(now_ms))
        pose_landmarks = results.pose_landmarks[0] if results.pose_landmarks else None
        pose_world_landmarks = results.pose_world_landmarks[0] if results.pose_world_landmarks else None

        frames.append(
            extractor.frame_record_for_landmarks(
                frame_index=frame_index,
                timestamp_ms=now_ms,
                pose_landmarks=pose_landmarks,
                pose_world_landmarks=pose_world_landmarks,
                exercise_key=segment.exercise_key,
            )
        )

        frame_index += 1
        if elapsed_seconds >= segment.duration_seconds:
            break

    return frames, frame_index


def build_segment_route(
    output_root: Path,
    exercise_folder: str,
    duration_seconds: float,
    angle_label: str,
) -> Path:
    side, vertical_folder = split_angle_label(angle_label)
    duration_folder = duration_folder_name(duration_seconds)
    return output_root / exercise_folder / duration_folder / side / vertical_folder


def read_existing_window_ids(index_path: Path) -> set[str]:
    if not index_path.exists():
        return set()

    known_ids: set[str] = set()
    with index_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue

            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            window_id = row.get("windowId")
            if isinstance(window_id, str) and window_id:
                known_ids.add(window_id)

    return known_ids


def append_index_rows(index_path: Path, rows: list[dict[str, Any]]) -> int:
    existing_ids = read_existing_window_ids(index_path)
    appended_count = 0

    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("a", encoding="utf-8") as handle:
        for row in rows:
            window_id = row.get("windowId")
            if not isinstance(window_id, str) or not window_id:
                continue

            if window_id in existing_ids:
                continue

            handle.write(json.dumps(row) + "\n")
            existing_ids.add(window_id)
            appended_count += 1

    return appended_count


def write_window_indexes(output_root: Path, windows_rows: list[dict[str, Any]]) -> tuple[int, int]:
    global_index_path = output_root / "windows.jsonl"
    appended_global = append_index_rows(global_index_path, windows_rows)

    exercise_groups: dict[str, list[dict[str, Any]]] = {}
    for row in windows_rows:
        exercise_key = str(row.get("exerciseKey") or "unknown")
        exercise_groups.setdefault(exercise_key, []).append(row)

    appended_exercise_total = 0
    for exercise_key, rows in exercise_groups.items():
        exercise_index_path = output_root / exercise_key / "windows.jsonl"
        appended_exercise_total += append_index_rows(exercise_index_path, rows)

    return appended_global, appended_exercise_total


def run_capture(args: argparse.Namespace) -> int:
    segments = load_segments(args)
    if args.feature_target_size < 32:
        raise ValueError("--feature-target-size must be at least 32")

    window_durations = parse_duration_list(args.window_durations)
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    pose_model_path = extractor.ensure_model_asset(extractor.DEFAULT_MODEL_PATH)
    options = extractor.pose_landmarker.PoseLandmarkerOptions(
        base_options=extractor.BaseOptions(model_asset_path=str(pose_model_path)),
        running_mode=extractor.VisionTaskRunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
        output_segmentation_masks=False,
    )

    capture = cv2.VideoCapture(int(args.camera_index))
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open webcam index {args.camera_index}")

    stream_start_ms = time.perf_counter() * 1000.0
    frame_index = 0
    session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    all_windows_rows: list[dict[str, Any]] = []

    try:
        with extractor.pose_landmarker.PoseLandmarker.create_from_options(options) as pose:
            for index, segment in enumerate(segments, start=1):
                print(
                    f"[segment {index}/{len(segments)}] exercise={segment.exercise_key} "
                    f"angle={segment.angle_label} duration={segment.duration_seconds}s reps={segment.reps_count}"
                )
                frames, frame_index = collect_segment_frames(
                    capture=capture,
                    pose=pose,
                    segment=segment,
                    frame_index_start=frame_index,
                    stream_start_ms=stream_start_ms,
                )

                fps = (len(frames) / segment.duration_seconds) if segment.duration_seconds > 0 else 30.0
                clip_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                clip_id = clip_id_for_segment(segment, f"{session_id}:{clip_timestamp}:{index}")
                exercise_definition = resolve_exercise(segment.exercise_key)
                exercise_folder = normalize_exercise_folder_name(exercise_definition.folder_name)
                route_dir = build_segment_route(
                    output_root=output_root,
                    exercise_folder=exercise_folder,
                    duration_seconds=segment.duration_seconds,
                    angle_label=segment.angle_label,
                )
                route_dir.mkdir(parents=True, exist_ok=True)

                windows: dict[str, list[dict[str, Any]]] = {}
                frame_map = {frame["frameIndex"]: frame for frame in frames}
                for duration_seconds in window_durations:
                    family_key = f"dur_{int(duration_seconds)}s"
                    stride_seconds = max(1.0, duration_seconds / 5.0)
                    family_windows = extractor.build_window_samples(
                        frames=frames,
                        fps=max(1.0, fps),
                        window_seconds=duration_seconds,
                        stride_seconds=stride_seconds,
                        clip_id=clip_id,
                        exercise_key=segment.exercise_key,
                        exercise_label=segment.exercise_key,
                        window_family=family_key,
                    )

                    for window in family_windows:
                        window_frames = [
                            frame_map[frame_index_value]
                            for frame_index_value in window.get("frameIndices", [])
                            if frame_index_value in frame_map
                        ]
                        window["angleLabel"] = segment.angle_label
                        window["repsCount"] = segment.reps_count
                        window["featureTargetSize"] = args.feature_target_size
                        window["featureVectorFixed"] = build_fixed_feature_vector(
                            window=window,
                            window_frames=window_frames,
                            feature_target_size=args.feature_target_size,
                        )
                    windows[family_key] = family_windows

                visible_frames = sum(1 for frame in frames if frame["posePresent"])
                pose_scores = [frame["poseScore"] for frame in frames if frame["poseScore"] is not None]
                side_folder, vertical_folder = split_angle_label(segment.angle_label)
                duration_folder = duration_folder_name(segment.duration_seconds)
                payload = {
                    "schemaVersion": SCHEMA_VERSION,
                    "sourceType": "camera",
                    "cameraIndex": int(args.camera_index),
                    "sessionId": session_id,
                    "capturedAt": datetime.now(timezone.utc).isoformat(),
                    "exerciseKey": segment.exercise_key,
                    "label": exercise_definition.label,
                    "exerciseFolder": exercise_folder,
                    "clipId": clip_id,
                    "angleLabel": segment.angle_label,
                    "cameraSide": side_folder,
                    "cameraLevel": vertical_folder,
                    "durationFolder": duration_folder,
                    "repsCount": segment.reps_count,
                    "notes": segment.notes,
                    "durationSeconds": float(segment.duration_seconds),
                    "fps": round(max(1.0, fps), 3),
                    "frameCount": len(frames),
                    "nodeCount": len(extractor.NODE_SPECS),
                    "angleCount": len(extractor.ANGLE_DEFINITIONS),
                    "contractionAngleNames": extractor.contraction_angle_names_for_exercise(segment.exercise_key),
                    "visibleFrameRatio": round(visible_frames / len(frames), 6) if frames else 0.0,
                    "averagePoseScore": round(sum(pose_scores) / len(pose_scores), 6) if pose_scores else None,
                    "featureTargetSize": args.feature_target_size,
                    "featureSpecVersion": "fixed_v1",
                    "routePath": portable_path(route_dir),
                    "frames": frames,
                    "windows": windows,
                }

                clip_file = route_dir / f"{clip_timestamp}__{clip_id}.clip.json"
                clip_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

                for family_key, family_windows in windows.items():
                    for window in family_windows:
                        all_windows_rows.append(
                            {
                                "clipId": clip_id,
                                "exerciseKey": segment.exercise_key,
                                "label": exercise_definition.label,
                                "exerciseFolder": exercise_folder,
                                "sourceVideo": f"camera:{args.camera_index}",
                                "sourceRelativePath": f"camera/{segment.exercise_key}/{clip_timestamp}",
                                "outputDir": portable_path(route_dir),
                                "routePath": portable_path(route_dir),
                                "durationFolder": duration_folder,
                                "cameraSide": side_folder,
                                "cameraLevel": vertical_folder,
                                "angleLabel": segment.angle_label,
                                "repsCount": segment.reps_count,
                                "windowFamily": family_key,
                                **window,
                            }
                        )

                print(f"Saved segment to {portable_path(clip_file)}")
    finally:
        capture.release()

    appended_global, appended_exercise_total = write_window_indexes(output_root, all_windows_rows)
    skipped_global = len(all_windows_rows) - appended_global
    print(
        f"Indexed windows: appended_global={appended_global} skipped_existing={skipped_global} "
        f"appended_per_exercise={appended_exercise_total}"
    )
    print(f"Global index: {portable_path(output_root / 'windows.jsonl')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture MediaPipe pose data from webcam into JSON-only workout dataset artifacts."
    )
    parser.add_argument("--camera-index", type=int, default=DEFAULT_CAMERA_INDEX, help="Webcam index for OpenCV capture.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="Where clip JSON artifacts and windows index are stored.")
    parser.add_argument("--exercise", default="biceps curl", help="Exercise key/folder/alias for single-segment mode.")
    parser.add_argument("--angle-label", default="center_center", help="Camera angle label.")
    parser.add_argument("--duration-seconds", type=float, default=10.0, help="Single segment duration in seconds.")
    parser.add_argument("--reps-count", type=int, default=None, help="Optional rep count metadata for the segment.")
    parser.add_argument("--notes", default=None, help="Optional notes stored with the segment metadata.")
    parser.add_argument("--segments-file", type=Path, default=None, help="JSON file describing multiple segments to capture in one run.")
    parser.add_argument(
        "--window-durations",
        default=",".join(str(int(value)) for value in DEFAULT_WINDOW_DURATIONS),
        help="Comma-separated list of window durations (seconds), e.g. '5,10,15'.",
    )
    parser.add_argument(
        "--feature-target-size",
        type=int,
        default=DEFAULT_FEATURE_TARGET_SIZE,
        help="Fixed length for featureVectorFixed (e.g. 200 or 500).",
    )
    args = parser.parse_args()

    return run_capture(args)


if __name__ == "__main__":
    raise SystemExit(main())