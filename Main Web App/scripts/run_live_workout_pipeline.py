from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter, deque
from pathlib import Path
from typing import Any

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTRACTOR_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "extract_workout_pose_dataset.py"
PREDICTOR_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "predict_workout_exercise.py"
DEFAULT_MODEL_PATH = PROJECT_ROOT / "generated" / "workout-models" / "workout-centroid-model.json"
DEFAULT_SHORT_WINDOW_SECONDS = 5.0
DEFAULT_LONG_WINDOW_SECONDS = 15.0
DEFAULT_MAX_HISTORY_SECONDS = 20.0
DEFAULT_CONFIDENCE_THRESHOLD = 0.45


def load_script_module(module_name: str, script_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script module: {script_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


extractor = load_script_module("workout_extract_runtime", EXTRACTOR_SCRIPT_PATH)
predictor = load_script_module("workout_predict_runtime", PREDICTOR_SCRIPT_PATH)


def portable_path(value: Path) -> str:
    return value.resolve().as_posix()


def load_model(model_path: Path) -> dict[str, Any]:
    return predictor.load_model(model_path)


def select_causal_frames(frames: list[dict[str, Any]], current_timestamp_ms: float, window_seconds: float) -> list[dict[str, Any]]:
    cutoff_ms = current_timestamp_ms - (window_seconds * 1000.0)
    return [frame for frame in frames if frame["timestampMs"] >= cutoff_ms]


def score_window(window_summary: dict[str, Any], model: dict[str, Any]) -> tuple[str, float, float]:
    feature_means = np.asarray(model["featureMeans"], dtype=np.float32)
    feature_stds = np.asarray(model["featureStds"], dtype=np.float32)
    feature_mode, include_contraction = predictor.resolve_feature_spec(model)
    features = predictor.flatten_window(window_summary, feature_mode, include_contraction)
    standardized = predictor.standardize_features(features[None, :], feature_means, feature_stds)
    labels, distances = predictor.centroid_distances(standardized, model)
    distance = float(distances[0, int(np.argmin(distances[0]))])
    label = labels[int(np.argmin(distances[0]))]
    confidence = 1.0 / (1.0 + distance)
    confidence *= float(window_summary.get("visibleFrameRatio") or 0.0)
    return label, confidence, distance


def build_capture(args: argparse.Namespace):
    if args.video is not None:
        input_path = Path(args.video).expanduser().resolve()
        if not input_path.exists():
            raise RuntimeError(f"Video not found: {portable_path(input_path)}")

        capture_path = input_path
        if capture_path.suffix.lower() != ".mp4":
            clip_id = extractor.clip_id_for_path(capture_path, capture_path.parent)
            capture_path = extractor.normalize_input_video(capture_path, capture_path.parent, clip_id)

        capture = cv2.VideoCapture(str(capture_path))
        source_name = portable_path(input_path)
        return capture, source_name, capture_path

    capture = cv2.VideoCapture(int(args.camera_index))
    return capture, f"camera:{args.camera_index}", None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a live workout prediction pipeline over a webcam or video file.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH, help="Path to the trained workout model artifact.")
    parser.add_argument("--video", type=Path, default=None, help="Optional video file to process instead of the webcam.")
    parser.add_argument("--camera-index", type=int, default=0, help="Webcam index to use when --video is not provided.")
    parser.add_argument("--short-window-seconds", type=float, default=DEFAULT_SHORT_WINDOW_SECONDS, help="Short causal window size in seconds.")
    parser.add_argument("--long-window-seconds", type=float, default=DEFAULT_LONG_WINDOW_SECONDS, help="Long causal window size in seconds.")
    parser.add_argument("--max-history-seconds", type=float, default=DEFAULT_MAX_HISTORY_SECONDS, help="How much frame history to keep in memory.")
    parser.add_argument("--confidence-threshold", type=float, default=DEFAULT_CONFIDENCE_THRESHOLD, help="Confidence cutoff for stable predictions.")
    parser.add_argument("--max-frames", type=int, default=0, help="Stop after this many frames for smoke testing.")
    parser.add_argument("--jsonl", type=Path, default=None, help="Optional output JSONL path for streaming predictions.")
    args = parser.parse_args()

    model = load_model(args.model)
    capture, source_name, normalized_source = build_capture(args)
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open source: {source_name}")

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0) or 30.0
    model_path = Path(args.model).resolve()
    model_path.parent.mkdir(parents=True, exist_ok=True)

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

    history: list[dict[str, Any]] = []
    recent_labels: deque[str] = deque(maxlen=5)
    output_handle = args.jsonl.open("w", encoding="utf-8") if args.jsonl else None

    try:
        with extractor.pose_landmarker.PoseLandmarker.create_from_options(options) as pose:
            frame_index = 0
            while True:
                success, frame = capture.read()
                if not success:
                    break

                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = extractor.mp.Image(image_format=extractor.mp.ImageFormat.SRGB, data=rgb_frame)

                timestamp_ms = capture.get(cv2.CAP_PROP_POS_MSEC)
                if not timestamp_ms:
                    timestamp_ms = (frame_index / fps) * 1000.0

                results = pose.detect_for_video(mp_image, int(timestamp_ms))
                pose_landmarks = results.pose_landmarks[0] if results.pose_landmarks else None
                pose_world_landmarks = results.pose_world_landmarks[0] if results.pose_world_landmarks else None
                frame_record = extractor.frame_record_for_landmarks(
                    frame_index=frame_index,
                    timestamp_ms=timestamp_ms,
                    pose_landmarks=pose_landmarks,
                    pose_world_landmarks=pose_world_landmarks,
                )
                history.append(frame_record)

                min_history_ms = max(args.short_window_seconds, 1.0) * 1000.0
                history_cutoff = timestamp_ms - (args.max_history_seconds * 1000.0)
                history[:] = [record for record in history if record["timestampMs"] >= history_cutoff]

                if history and (timestamp_ms - history[0]["timestampMs"] >= min_history_ms or len(history) >= 2):
                    window_families = [
                        ("short", args.short_window_seconds, 1.0),
                        ("long", args.long_window_seconds, 5.0),
                    ]
                    window_outputs: list[dict[str, Any]] = []
                    votes: Counter[str] = Counter()
                    weighted_votes: dict[str, float] = {}

                    for window_family, window_seconds, stride_seconds in window_families:
                        window_frames = select_causal_frames(history, timestamp_ms, window_seconds)
                        if not window_frames:
                            continue

                        window_summary = extractor.summarize_window(window_frames, fps)
                        window_summary["windowSeconds"] = window_seconds
                        window_summary["strideSeconds"] = stride_seconds
                        predicted_label, confidence, distance = score_window(window_summary, model)
                        votes[predicted_label] += 1
                        weighted_votes[predicted_label] = weighted_votes.get(predicted_label, 0.0) + confidence
                        window_outputs.append(
                            {
                                "windowFamily": window_family,
                                "predictedLabel": predicted_label,
                                "confidence": round(confidence, 6),
                                "distance": round(distance, 6),
                                "frameCount": len(window_frames),
                                "visibleFrameRatio": window_summary.get("visibleFrameRatio"),
                            }
                        )

                    if weighted_votes:
                        final_label = max(weighted_votes.items(), key=lambda item: (item[1], votes[item[0]]))[0]
                        final_confidence = weighted_votes[final_label] / max(1, votes[final_label])
                    else:
                        final_label = "unknown"
                        final_confidence = 0.0

                    stable_label = final_label if len(recent_labels) < recent_labels.maxlen else Counter(recent_labels).most_common(1)[0][0]
                    recent_labels.append(final_label)
                    state = "stable" if final_confidence >= args.confidence_threshold else "low-confidence"

                    output_row = {
                        "source": source_name,
                        "normalizedSource": portable_path(normalized_source) if normalized_source else None,
                        "frameIndex": frame_index,
                        "timestampMs": round(timestamp_ms, 3),
                        "predictedLabel": final_label,
                        "stableLabel": stable_label,
                        "confidence": round(float(final_confidence), 6),
                        "state": state,
                        "windowPredictions": window_outputs,
                    }
                    print(json.dumps(output_row))
                    if output_handle is not None:
                        output_handle.write(json.dumps(output_row) + "\n")

                frame_index += 1
                if args.max_frames and frame_index >= args.max_frames:
                    break
    finally:
        capture.release()
        if output_handle is not None:
            output_handle.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())