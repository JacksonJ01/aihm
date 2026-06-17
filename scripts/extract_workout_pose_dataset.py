from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

import cv2
import mediapipe as mp
from mediapipe.tasks.python.core.base_options import BaseOptions
from mediapipe.tasks.python.vision import pose_landmarker
from mediapipe.tasks.python.vision.core.vision_task_running_mode import VisionTaskRunningMode

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_ROOT = PROJECT_ROOT / "preprocessedWorkoutVideos"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "processed workout videos"
DEFAULT_MODEL_PATH = PROJECT_ROOT / "generated" / "models" / "pose_landmarker_heavy.task"
POSE_LANDMARKER_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task"
)
DEFAULT_SHORT_WINDOW_SECONDS = 5.0
DEFAULT_SHORT_STRIDE_SECONDS = 1.0
DEFAULT_LONG_WINDOW_SECONDS = 15.0
DEFAULT_LONG_STRIDE_SECONDS = 5.0
DEFAULT_FRAME_STEP = 1
DEFAULT_NORMALIZED_VIDEO_ROOT = PROJECT_ROOT / "generated" / "normalized-workout-videos"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
SCHEMA_VERSION = 4

NODE_SPECS = [
    {"name": "leftShoulder", "index": 11},
    {"name": "rightShoulder", "index": 12},
    {"name": "leftElbow", "index": 13},
    {"name": "rightElbow", "index": 14},
    {"name": "leftWrist", "index": 15},
    {"name": "rightWrist", "index": 16},
    {"name": "leftHip", "index": 23},
    {"name": "rightHip", "index": 24},
    {"name": "leftKnee", "index": 25},
    {"name": "rightKnee", "index": 26},
    {"name": "leftAnkle", "index": 27},
    {"name": "rightAnkle", "index": 28},
]

ANGLE_DEFINITIONS = {
    "leftElbow": ("leftShoulder", "leftElbow", "leftWrist"),
    "rightElbow": ("rightShoulder", "rightElbow", "rightWrist"),
    "leftShoulder": ("leftElbow", "leftShoulder", "leftHip"),
    "rightShoulder": ("rightElbow", "rightShoulder", "rightHip"),
    "leftHip": ("leftShoulder", "leftHip", "leftKnee"),
    "rightHip": ("rightShoulder", "rightHip", "rightKnee"),
    "leftKnee": ("leftHip", "leftKnee", "leftAnkle"),
    "rightKnee": ("rightHip", "rightKnee", "rightAnkle"),
}

CONTRACTION_RELAXED_THRESHOLD = 0.33
CONTRACTION_CONTRACTED_THRESHOLD = 0.66

CONTRACTION_ANGLE_GROUPS: dict[str, tuple[str, ...]] = {
    "barbellBicepsCurl": ("leftElbow", "rightElbow"),
    "hammerCurl": ("leftElbow", "rightElbow"),
    "benchPress": ("leftElbow", "rightElbow", "leftShoulder", "rightShoulder"),
    "declineBenchPress": ("leftElbow", "rightElbow", "leftShoulder", "rightShoulder"),
    "inclineBenchPress": ("leftElbow", "rightElbow", "leftShoulder", "rightShoulder"),
    "chestFlyMachine": ("leftElbow", "rightElbow", "leftShoulder", "rightShoulder"),
    "shoulderPress": ("leftElbow", "rightElbow", "leftShoulder", "rightShoulder"),
    "tricepDips": ("leftElbow", "rightElbow", "leftShoulder", "rightShoulder"),
    "tricepPushdown": ("leftElbow", "rightElbow"),
    "latPulldown": ("leftElbow", "rightElbow", "leftShoulder", "rightShoulder"),
    "pullUp": ("leftElbow", "rightElbow", "leftShoulder", "rightShoulder"),
    "pushUp": ("leftElbow", "rightElbow", "leftShoulder", "rightShoulder"),
    "tBarRow": ("leftElbow", "rightElbow", "leftShoulder", "rightShoulder"),
    "squat": ("leftHip", "rightHip", "leftKnee", "rightKnee"),
    "deadlift": ("leftHip", "rightHip", "leftKnee", "rightKnee"),
    "romanianDeadlift": ("leftHip", "rightHip", "leftKnee", "rightKnee"),
    "hipThrust": ("leftHip", "rightHip"),
    "legExtension": ("leftKnee", "rightKnee"),
    "legRaises": ("leftHip", "rightHip", "leftKnee", "rightKnee"),
    "plank": ("leftShoulder", "rightShoulder", "leftHip", "rightHip", "leftKnee", "rightKnee"),
    "russianTwist": ("leftHip", "rightHip", "leftShoulder", "rightShoulder"),
}


def contraction_state_from_score(score: float | None) -> tuple[str | None, int | None]:
    if score is None:
        return None, None

    if score >= CONTRACTION_CONTRACTED_THRESHOLD:
        return "contracted", 1

    if score <= CONTRACTION_RELAXED_THRESHOLD:
        return "relaxed", -1

    return "transition", 0


def contraction_angle_names_for_exercise(exercise_key: str | None) -> list[str]:
    if exercise_key is None:
        return list(ANGLE_DEFINITIONS.keys())

    return list(CONTRACTION_ANGLE_GROUPS.get(exercise_key, ANGLE_DEFINITIONS.keys()))


def contraction_score_from_angles(angle_values: dict[str, float | None], angle_names: list[str]) -> float | None:
    values = [angle_values[name] for name in angle_names if angle_values.get(name) is not None]
    if not values:
        return None

    average_angle = mean(values)
    normalized_score = 1.0 - max(0.0, min(1.0, average_angle / 180.0))
    return round(normalized_score, 6)


@dataclass(frozen=True)
class ExerciseDefinition:
    key: str
    folder_name: str
    label: str
    aliases: list[str]


WORKOUT_EXERCISE_CATALOG: list[ExerciseDefinition] = [
    ExerciseDefinition("barbellBicepsCurl", "barbell biceps curl", "Barbell biceps curl", ["biceps curl", "barbell curl"]),
    ExerciseDefinition("benchPress", "bench press", "Bench press", ["flat bench press"]),
    ExerciseDefinition("chestFlyMachine", "chest fly machine", "Chest fly machine", ["machine fly"]),
    ExerciseDefinition("deadlift", "deadlift", "Deadlift", []),
    ExerciseDefinition("declineBenchPress", "decline bench press", "Decline bench press", ["dbp"]),
    ExerciseDefinition("hammerCurl", "hammer curl", "Hammer curl", []),
    ExerciseDefinition("hipThrust", "hip thrust", "Hip thrust", []),
    ExerciseDefinition("inclineBenchPress", "incline bench press", "Incline bench press", []),
    ExerciseDefinition("latPulldown", "lat pulldown", "Lat pulldown", []),
    ExerciseDefinition("lateralRaise", "lateral raise", "Lateral raise", []),
    ExerciseDefinition("legExtension", "leg extension", "Leg extension", []),
    ExerciseDefinition("legRaises", "leg raises", "Leg raises", []),
    ExerciseDefinition("plank", "plank", "Plank", []),
    ExerciseDefinition("pullUp", "pull Up", "Pull-up", ["pull up", "pullup"]),
    ExerciseDefinition("pushUp", "push-up", "Push-up", ["push up"]),
    ExerciseDefinition("romanianDeadlift", "romanian deadlift", "Romanian deadlift", ["rdl"]),
    ExerciseDefinition("russianTwist", "russian twist", "Russian twist", []),
    ExerciseDefinition("shoulderPress", "shoulder press", "Shoulder press", []),
    ExerciseDefinition("squat", "squat", "Squat", []),
    ExerciseDefinition("tBarRow", "t bar row", "T-bar row", ["t-bar row"]),
    ExerciseDefinition("tricepDips", "tricep dips", "Tricep dips", ["dips"]),
    ExerciseDefinition("tricepPushdown", "tricep Pushdown", "Tricep pushdown", ["tricep pushdown"]),
]

EXERCISE_LOOKUP: dict[str, ExerciseDefinition] = {}
for exercise in WORKOUT_EXERCISE_CATALOG:
    EXERCISE_LOOKUP[" ".join(exercise.folder_name.strip().lower().replace("_", "-").replace("-", " ").split())] = exercise
    EXERCISE_LOOKUP[" ".join(exercise.label.strip().lower().replace("_", "-").replace("-", " ").split())] = exercise
    for alias in exercise.aliases:
        EXERCISE_LOOKUP[" ".join(alias.strip().lower().replace("_", "-").replace("-", " ").split())] = exercise


@dataclass(frozen=True)
class ClipTarget:
    exercise: ExerciseDefinition
    source_path: Path
    relative_source_path: Path
    relative_parent_path: Path
    output_dir: Path
    clip_id: str


def normalize_manifest_path(value: str) -> str:
    return value.strip().replace("\\", "/").lstrip("./")


def portable_path(value: Path) -> str:
    return value.resolve().as_posix()


def relative_path_text(value: Path) -> str:
    return value.as_posix()


def normalize_name(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", " ").replace("-", " ").split())


def load_manifest_csv(manifest_csv: Path) -> tuple[set[str], set[str]]:
    if not manifest_csv.exists():
        raise RuntimeError(f"CSV manifest not found: {portable_path(manifest_csv)}")

    allowed_paths: set[str] = set()
    allowed_exercises: set[str] = set()

    with manifest_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            include_value = normalize_name(str(row.get("include", "1")))
            if include_value in {"0", "false", "no", "off", "skip"}:
                continue

            relative_path = row.get("relative_path") or row.get("source_path") or row.get("path")
            if relative_path:
                allowed_paths.add(normalize_manifest_path(relative_path))

            exercise_key = row.get("exercise_key") or row.get("exerciseKey")
            if exercise_key:
                allowed_exercises.add(normalize_name(exercise_key))

    return allowed_paths, allowed_exercises


def load_manifest_csv(manifest_csv: Path) -> tuple[set[str], set[str]]:
    if not manifest_csv.exists():
        raise RuntimeError(f"CSV manifest not found: {portable_path(manifest_csv)}")

    allowed_paths: set[str] = set()
    allowed_exercises: set[str] = set()

    with manifest_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            include_value = normalize_name(str(row.get("include", "1")))
            if include_value in {"0", "false", "no", "off", "skip"}:
                continue

            relative_path = row.get("relative_path") or row.get("source_path") or row.get("path")
            if relative_path:
                allowed_paths.add(normalize_manifest_path(relative_path))

            exercise_key = row.get("exercise_key") or row.get("exerciseKey")
            if exercise_key:
                allowed_exercises.add(normalize_name(exercise_key))

    return allowed_paths, allowed_exercises


def ensure_model_asset(model_path: Path) -> Path:
    if model_path.exists():
        return model_path

    model_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading heavy pose model to {portable_path(model_path)}")
    urllib.request.urlretrieve(POSE_LANDMARKER_MODEL_URL, model_path)
    return model_path


def resolve_ffmpeg_executable() -> str | None:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path

    try:
        from imageio_ffmpeg import get_ffmpeg_exe
    except ImportError:
        return None

    ffmpeg_path = get_ffmpeg_exe()
    return ffmpeg_path if ffmpeg_path else None


def normalize_input_video(video_path: Path, dataset_root: Path, clip_id: str, normalized_root: Path = DEFAULT_NORMALIZED_VIDEO_ROOT) -> Path:
    if video_path.suffix.lower() == ".mp4":
        return video_path

    ffmpeg_path = resolve_ffmpeg_executable()
    if ffmpeg_path is None:
        raise RuntimeError(
            f"ffmpeg is required to decode {video_path.suffix} files like {video_path.name}. "
            "Install ffmpeg, or install the imageio-ffmpeg Python package so the extractor can use a bundled binary."
        )

    relative_source_path = video_path.relative_to(dataset_root)
    normalized_path = normalized_root / relative_source_path.parent / f"{video_path.stem}__{clip_id}.mp4"
    normalized_path.parent.mkdir(parents=True, exist_ok=True)

    if normalized_path.exists() and normalized_path.stat().st_mtime >= video_path.stat().st_mtime:
        return normalized_path

    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-c:a",
        "aac",
        str(normalized_path),
    ]

    subprocess.run(command, check=True)
    return normalized_path


def angle_from_points_2d(first: dict[str, float], joint: dict[str, float], third: dict[str, float]) -> float | None:
    ax = first["x"] - joint["x"]
    ay = first["y"] - joint["y"]
    bx = third["x"] - joint["x"]
    by = third["y"] - joint["y"]

    magnitude_a = math.sqrt(ax * ax + ay * ay)
    magnitude_b = math.sqrt(bx * bx + by * by)
    if magnitude_a == 0 or magnitude_b == 0:
        return None

    dot = ax * bx + ay * by
    cross = abs(ax * by - ay * bx)
    return round(math.degrees(math.atan2(cross, dot)), 3)


def angle_from_points_3d(first: dict[str, float], joint: dict[str, float], third: dict[str, float]) -> float | None:
    ax = first["x"] - joint["x"]
    ay = first["y"] - joint["y"]
    az = first["z"] - joint["z"]
    bx = third["x"] - joint["x"]
    by = third["y"] - joint["y"]
    bz = third["z"] - joint["z"]

    magnitude_a = math.sqrt(ax * ax + ay * ay + az * az)
    magnitude_b = math.sqrt(bx * bx + by * by + bz * bz)
    if magnitude_a == 0 or magnitude_b == 0:
        return None

    dot = ax * bx + ay * by + az * bz
    normalized = max(-1.0, min(1.0, dot / (magnitude_a * magnitude_b)))
    return round(math.degrees(math.acos(normalized)), 3)


def landmark_visibility(landmark: Any) -> float | None:
    visibility = getattr(landmark, "visibility", None)
    if visibility is None:
        return None
    return round(float(visibility), 6)


def frame_record_for_landmarks(
    frame_index: int,
    timestamp_ms: float,
    pose_landmarks: Any,
    pose_world_landmarks: Any,
    exercise_key: str | None = None,
) -> dict[str, Any]:
    nodes2d: list[dict[str, Any]] = []
    nodes3d: list[dict[str, Any]] = []

    for node in NODE_SPECS:
        landmark_2d = pose_landmarks[node["index"]] if pose_landmarks else None
        landmark_3d = pose_world_landmarks[node["index"]] if pose_world_landmarks else None

        node2d = {
            "name": node["name"],
            "index": node["index"],
            "x": round(float(landmark_2d.x), 6) if landmark_2d else None,
            "y": round(float(landmark_2d.y), 6) if landmark_2d else None,
            "visibility": landmark_visibility(landmark_2d) if landmark_2d else None,
        }

        node3d = {
            "name": node["name"],
            "index": node["index"],
            "x": round(float(landmark_3d.x), 6) if landmark_3d else None,
            "y": round(float(landmark_3d.y), 6) if landmark_3d else None,
            "z": round(float(landmark_3d.z), 6) if landmark_3d else None,
        }

        nodes2d.append(node2d)
        nodes3d.append(node3d)

    named_nodes_2d = {node["name"]: node for node in nodes2d}
    named_nodes_3d = {node["name"]: node for node in nodes3d}

    angles2d: dict[str, float | None] = {}
    angles3d: dict[str, float | None] = {}
    for angle_name, (first_name, joint_name, third_name) in ANGLE_DEFINITIONS.items():
        first_2d = named_nodes_2d[first_name]
        joint_2d = named_nodes_2d[joint_name]
        third_2d = named_nodes_2d[third_name]
        first_3d = named_nodes_3d[first_name]
        joint_3d = named_nodes_3d[joint_name]
        third_3d = named_nodes_3d[third_name]

        if None in (first_2d["x"], first_2d["y"], joint_2d["x"], joint_2d["y"], third_2d["x"], third_2d["y"]):
            angles2d[angle_name] = None
        else:
            angles2d[angle_name] = angle_from_points_2d(first_2d, joint_2d, third_2d)

        if None in (
            first_3d["x"],
            first_3d["y"],
            first_3d["z"],
            joint_3d["x"],
            joint_3d["y"],
            joint_3d["z"],
            third_3d["x"],
            third_3d["y"],
            third_3d["z"],
        ):
            angles3d[angle_name] = None
        else:
            angles3d[angle_name] = angle_from_points_3d(first_3d, joint_3d, third_3d)

    visibilities = [node["visibility"] for node in nodes2d if node["visibility"] is not None]
    pose_score = round(mean(visibilities), 6) if visibilities else None
    contraction_angle_names = contraction_angle_names_for_exercise(exercise_key)
    contraction_score_2d = contraction_score_from_angles(angles2d, contraction_angle_names)
    contraction_score_3d = contraction_score_from_angles(angles3d, contraction_angle_names)
    contraction_components = [score for score in (contraction_score_2d, contraction_score_3d) if score is not None]
    contraction_score = round(mean(contraction_components), 6) if contraction_components else None
    contraction_state, contraction_state_value = contraction_state_from_score(contraction_score)

    return {
        "frameIndex": frame_index,
        "timestampMs": round(timestamp_ms, 3),
        "posePresent": bool(visibilities),
        "poseScore": pose_score,
        "contractionAngleNames": contraction_angle_names,
        "contractionScore2d": contraction_score_2d,
        "contractionScore3d": contraction_score_3d,
        "contractionScore": contraction_score,
        "contractionState": contraction_state,
        "contractionStateValue": contraction_state_value,
        "nodes2d": nodes2d,
        "nodes3d": nodes3d,
        "featureVector2d": [[node["x"], node["y"], node["visibility"]] for node in nodes2d],
        "featureVector3d": [[node["x"], node["y"], node["z"]] for node in nodes3d],
        "angles2d": angles2d,
        "angles3d": angles3d,
        "angleVector2d": [angles2d[angle_name] for angle_name in ANGLE_DEFINITIONS.keys()],
        "angleVector3d": [angles3d[angle_name] for angle_name in ANGLE_DEFINITIONS.keys()],
    }


def summarize_window(window_frames: list[dict[str, Any]], fps: float) -> dict[str, Any]:
    angle_names = list(ANGLE_DEFINITIONS.keys())
    averaged_angles_2d: dict[str, float | None] = {}
    averaged_angles_3d: dict[str, float | None] = {}

    for angle_name in angle_names:
        values_2d = [frame["angles2d"][angle_name] for frame in window_frames if frame["angles2d"][angle_name] is not None]
        values_3d = [frame["angles3d"][angle_name] for frame in window_frames if frame["angles3d"][angle_name] is not None]
        averaged_angles_2d[angle_name] = round(mean(values_2d), 3) if values_2d else None
        averaged_angles_3d[angle_name] = round(mean(values_3d), 3) if values_3d else None

    pose_scores = [frame["poseScore"] for frame in window_frames if frame["poseScore"] is not None]
    contraction_scores_2d = [frame["contractionScore2d"] for frame in window_frames if frame["contractionScore2d"] is not None]
    contraction_scores_3d = [frame["contractionScore3d"] for frame in window_frames if frame["contractionScore3d"] is not None]
    contraction_components = [frame["contractionScore"] for frame in window_frames if frame["contractionScore"] is not None]
    contraction_score_2d = round(mean(contraction_scores_2d), 6) if contraction_scores_2d else None
    contraction_score_3d = round(mean(contraction_scores_3d), 6) if contraction_scores_3d else None
    contraction_score = round(mean(contraction_components), 6) if contraction_components else None
    contraction_state, contraction_state_value = contraction_state_from_score(contraction_score)
    visible_ratio = sum(1 for frame in window_frames if frame["posePresent"]) / len(window_frames)
    start_frame = window_frames[0]
    end_frame = window_frames[-1]

    return {
        "startFrameIndex": start_frame["frameIndex"],
        "endFrameIndex": end_frame["frameIndex"],
        "startTimeMs": round(start_frame["timestampMs"], 3),
        "endTimeMs": round(end_frame["timestampMs"], 3),
        "frameCount": len(window_frames),
        "visibleFrameRatio": round(visible_ratio, 6),
        "averagePoseScore": round(mean(pose_scores), 6) if pose_scores else None,
        "contractionAngleNames": window_frames[0].get("contractionAngleNames", []),
        "contractionScore2d": contraction_score_2d,
        "contractionScore3d": contraction_score_3d,
        "contractionScore": contraction_score,
        "contractionState": contraction_state,
        "contractionStateValue": contraction_state_value,
        "targetAngles2d": averaged_angles_2d,
        "targetAngles3d": averaged_angles_3d,
        "targetAngles2dVector": [averaged_angles_2d[angle_name] for angle_name in angle_names],
        "targetAngles3dVector": [averaged_angles_3d[angle_name] for angle_name in angle_names],
        "frameIndices": [frame["frameIndex"] for frame in window_frames],
    }


def build_window_samples(
    frames: list[dict[str, Any]],
    fps: float,
    window_seconds: float,
    stride_seconds: float,
    clip_id: str,
    exercise_key: str,
    exercise_label: str,
    window_family: str,
) -> list[dict[str, Any]]:
    if not frames:
        return []

    expected_frame_count = max(1, int(round(window_seconds * fps)))
    window_duration_ms = window_seconds * 1000.0
    stride_ms = max(1.0, stride_seconds * 1000.0)
    samples: list[dict[str, Any]] = []
    start_anchor_ms = frames[0]["timestampMs"]
    end_anchor_ms = frames[-1]["timestampMs"]

    if end_anchor_ms - start_anchor_ms <= window_duration_ms:
        window_frames = frames[:]
        summary = summarize_window(window_frames, fps)
        samples.append(
            {
                "windowId": f"{clip_id}:{window_family}:0",
                "clipId": clip_id,
                "exerciseKey": exercise_key,
                "label": exercise_label,
                "windowFamily": window_family,
                "windowSeconds": window_seconds,
                "strideSeconds": stride_seconds,
                "windowIndex": 0,
                "frameCoverageRatio": round(len(window_frames) / expected_frame_count, 6),
                **summary,
            }
        )
        return samples

    sample_index = 0
    anchor_ms = start_anchor_ms
    start_index = 0
    end_index = 0

    while anchor_ms + window_duration_ms <= end_anchor_ms + 1e-6:
        while start_index < len(frames) and frames[start_index]["timestampMs"] < anchor_ms:
            start_index += 1

        end_index = max(end_index, start_index)
        window_end_ms = anchor_ms + window_duration_ms
        while end_index < len(frames) and frames[end_index]["timestampMs"] < window_end_ms:
            end_index += 1

        window_frames = frames[start_index:end_index]
        if not window_frames:
            anchor_ms += stride_ms
            continue

        summary = summarize_window(window_frames, fps)
        samples.append(
            {
                "windowId": f"{clip_id}:{window_family}:{sample_index}",
                "clipId": clip_id,
                "exerciseKey": exercise_key,
                "label": exercise_label,
                "windowFamily": window_family,
                "windowSeconds": window_seconds,
                "strideSeconds": stride_seconds,
                "windowIndex": sample_index,
                "frameCoverageRatio": round(len(window_frames) / expected_frame_count, 6),
                **summary,
            }
        )
        sample_index += 1
        anchor_ms += stride_ms

    return samples


def resolve_exercise_for_video(video_path: Path, dataset_root: Path) -> ExerciseDefinition:
    for ancestor in [video_path.parent, *video_path.parents]:
        try:
            relative_ancestor = ancestor.relative_to(dataset_root)
        except ValueError:
            continue

        if not relative_ancestor.parts:
            continue

        matched_name = normalize_name(relative_ancestor.parts[0])
        exercise = EXERCISE_LOOKUP.get(matched_name)
        if exercise is not None:
            return exercise

        direct_name = normalize_name(relative_ancestor.parts[-1])
        exercise = EXERCISE_LOOKUP.get(direct_name)
        if exercise is not None:
            return exercise

    raise RuntimeError(f"Unable to infer workout label from path: {video_path}")


def clip_id_for_path(video_path: Path, dataset_root: Path) -> str:
    relative_path = portable_path(video_path.relative_to(dataset_root))
    return hashlib.sha1(relative_path.encode("utf-8")).hexdigest()[:12]


def discover_clip_targets(
    dataset_root: Path,
    output_root: Path,
    allowed_paths: set[str] | None = None,
    allowed_exercises: set[str] | None = None,
) -> list[ClipTarget]:
    targets: list[ClipTarget] = []
    for video_path in sorted(dataset_root.rglob("*")):
        if not video_path.is_file() or video_path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue

        exercise = resolve_exercise_for_video(video_path, dataset_root)
        relative_source_path = video_path.relative_to(dataset_root)
        relative_source_text = relative_source_path.as_posix()

        if allowed_paths and normalize_manifest_path(relative_source_text) not in allowed_paths:
            continue
        if allowed_exercises and normalize_name(exercise.key) not in allowed_exercises:
            continue

        relative_parent_path = relative_source_path.parent
        clip_id = clip_id_for_path(video_path, dataset_root)
        output_dir = output_root / relative_parent_path / f"{video_path.stem}__{clip_id}"
        targets.append(
            ClipTarget(
                exercise=exercise,
                source_path=video_path,
                relative_source_path=relative_source_path,
                relative_parent_path=relative_parent_path,
                output_dir=output_dir,
                clip_id=clip_id,
            )
        )

    return targets


def load_existing_clip(output_dir: Path) -> dict[str, Any] | None:
    clip_file = output_dir / "clip.json"
    if not clip_file.exists():
        return None

    return json.loads(clip_file.read_text(encoding="utf-8"))


def write_clip_output(output_dir: Path, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    clip_file = output_dir / "clip.json"
    clip_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def process_video(
    video_path: Path,
    exercise: ExerciseDefinition,
    dataset_root: Path,
    output_root: Path,
    short_window_seconds: float,
    short_stride_seconds: float,
    long_window_seconds: float,
    long_stride_seconds: float,
    frame_step: int,
    overwrite: bool,
) -> dict[str, Any]:
    relative_source_path = video_path.relative_to(dataset_root)
    clip_id = clip_id_for_path(video_path, dataset_root)
    output_dir = output_root / relative_source_path.parent / f"{video_path.stem}__{clip_id}"

    if output_dir.exists() and not overwrite:
        existing_payload = load_existing_clip(output_dir)
        if existing_payload is not None:
            return {
                "clipId": clip_id,
                "exerciseKey": exercise.key,
                "label": exercise.label,
                "sourceVideo": portable_path(video_path),
                "sourceRelativePath": relative_path_text(relative_source_path),
                "outputDir": portable_path(output_dir),
                "outputFile": portable_path(output_dir / "clip.json"),
                "frameCount": existing_payload.get("frameCount"),
                "durationSeconds": existing_payload.get("durationSeconds"),
                "fps": existing_payload.get("fps"),
                "decodedVideo": existing_payload.get("decodedVideo", existing_payload.get("sourceVideo")),
                "shortWindowCount": len(existing_payload.get("windows", {}).get("short", [])),
                "longWindowCount": len(existing_payload.get("windows", {}).get("long", [])),
                "skipped": True,
            }

    decoded_video_path = normalize_input_video(video_path, dataset_root, clip_id)

    capture = cv2.VideoCapture(str(decoded_video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open video: {decoded_video_path}")

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0) or 30.0
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration_seconds = frame_count / fps if frame_count else None

    model_path = ensure_model_asset(DEFAULT_MODEL_PATH)
    options = pose_landmarker.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=VisionTaskRunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
        output_segmentation_masks=False,
    )

    frames: list[dict[str, Any]] = []
    frame_index = 0
    processed_frames = 0

    with pose_landmarker.PoseLandmarker.create_from_options(options) as pose:
        while True:
            success, frame = capture.read()
            if not success:
                break

            if frame_step > 1 and frame_index % frame_step != 0:
                frame_index += 1
                continue

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

            timestamp_ms = capture.get(cv2.CAP_PROP_POS_MSEC)
            if not timestamp_ms:
                timestamp_ms = (frame_index / fps) * 1000.0

            results = pose.detect_for_video(mp_image, int(timestamp_ms))
            pose_landmarks = results.pose_landmarks[0] if results.pose_landmarks else None
            pose_world_landmarks = results.pose_world_landmarks[0] if results.pose_world_landmarks else None
            frames.append(
                frame_record_for_landmarks(
                    frame_index=frame_index,
                    timestamp_ms=timestamp_ms,
                    pose_landmarks=pose_landmarks,
                    pose_world_landmarks=pose_world_landmarks,
                    exercise_key=exercise.key,
                )
            )
            processed_frames += 1
            frame_index += 1

    capture.release()

    short_windows = build_window_samples(
        frames=frames,
        fps=fps,
        window_seconds=short_window_seconds,
        stride_seconds=short_stride_seconds,
        clip_id=clip_id,
        exercise_key=exercise.key,
        exercise_label=exercise.label,
        window_family="short",
    )
    long_windows = build_window_samples(
        frames=frames,
        fps=fps,
        window_seconds=long_window_seconds,
        stride_seconds=long_stride_seconds,
        clip_id=clip_id,
        exercise_key=exercise.key,
        exercise_label=exercise.label,
        window_family="long",
    )

    visible_frames = sum(1 for frame in frames if frame["posePresent"])
    pose_scores = [frame["poseScore"] for frame in frames if frame["poseScore"] is not None]

    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "exerciseKey": exercise.key,
        "label": exercise.label,
        "folderName": exercise.folder_name,
        "aliases": exercise.aliases,
        "clipId": clip_id,
        "sourceVideo": portable_path(video_path),
        "decodedVideo": portable_path(decoded_video_path),
        "sourceRelativePath": relative_path_text(relative_source_path),
        "sourceParentPath": relative_path_text(relative_source_path.parent) if relative_source_path.parent != Path(".") else ".",
        "outputDir": portable_path(output_dir),
        "fps": round(fps, 3),
        "frameCount": len(frames),
        "sourceFrameCount": frame_count,
        "durationSeconds": round(duration_seconds, 3) if duration_seconds is not None else None,
        "shortWindowSeconds": short_window_seconds,
        "shortStrideSeconds": short_stride_seconds,
        "longWindowSeconds": long_window_seconds,
        "longStrideSeconds": long_stride_seconds,
        "frameStep": frame_step,
        "nodeCount": len(NODE_SPECS),
        "angleCount": len(ANGLE_DEFINITIONS),
        "contractionAngleNames": contraction_angle_names_for_exercise(exercise.key),
        "visibleFrameRatio": round(visible_frames / len(frames), 6) if frames else 0.0,
        "averagePoseScore": round(mean(pose_scores), 6) if pose_scores else None,
        "frames": frames,
        "windows": {
            "short": short_windows,
            "long": long_windows,
        },
    }

    write_clip_output(output_dir, payload)

    return {
        "clipId": clip_id,
        "exerciseKey": exercise.key,
        "label": exercise.label,
        "sourceVideo": portable_path(video_path),
        "decodedVideo": portable_path(decoded_video_path),
        "sourceRelativePath": relative_path_text(relative_source_path),
        "outputDir": portable_path(output_dir),
        "outputFile": portable_path(output_dir / "clip.json"),
        "frameCount": len(frames),
        "durationSeconds": payload["durationSeconds"],
        "fps": round(fps, 3),
        "shortWindowCount": len(short_windows),
        "longWindowCount": len(long_windows),
        "processedFrames": processed_frames,
        "skipped": False,
    }


def write_window_index(output_root: Path, clip_payloads: list[dict[str, Any]]) -> None:
    windows_index_path = output_root / "windows.jsonl"
    with windows_index_path.open("w", encoding="utf-8") as handle:
        for clip_payload in clip_payloads:
            clip_file = Path(clip_payload["outputFile"])
            if not clip_file.exists():
                continue

            clip_data = json.loads(clip_file.read_text(encoding="utf-8"))
            for window_family, windows in clip_data.get("windows", {}).items():
                for window in windows:
                    row = {
                        "clipId": clip_data["clipId"],
                        "exerciseKey": clip_data["exerciseKey"],
                        "label": clip_data["label"],
                        "sourceVideo": clip_data["sourceVideo"],
                        "sourceRelativePath": clip_data["sourceRelativePath"],
                        "outputDir": clip_data["outputDir"],
                        "windowFamily": window_family,
                        **window,
                    }
                    handle.write(json.dumps(row) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recursively extract 2D and 3D MediaPipe pose features from workout videos."
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT, help="Root folder to scan for workout videos.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="Root folder for processed workout videos.")
    parser.add_argument("--short-window-seconds", type=float, default=DEFAULT_SHORT_WINDOW_SECONDS, help="Short sliding-window size in seconds.")
    parser.add_argument("--short-stride-seconds", type=float, default=DEFAULT_SHORT_STRIDE_SECONDS, help="Short-window stride in seconds.")
    parser.add_argument("--long-window-seconds", type=float, default=DEFAULT_LONG_WINDOW_SECONDS, help="Long sliding-window size in seconds.")
    parser.add_argument("--long-stride-seconds", type=float, default=DEFAULT_LONG_STRIDE_SECONDS, help="Long-window stride in seconds.")
    parser.add_argument("--frame-step", type=int, default=DEFAULT_FRAME_STEP, help="Process every Nth frame to reduce runtime on long clips.")
    parser.add_argument("--exercise", action="append", default=[], help="Optional exercise key, folder name, or alias filter. Can be provided multiple times.")
    parser.add_argument("--manifest-csv", type=Path, default=None, help="Optional CSV manifest with relative_path and exercise_key columns to filter which videos are processed.")
    parser.add_argument("--limit", type=int, default=0, help="Limit the number of clips processed.")
    parser.add_argument("--overwrite", action="store_true", help="Reprocess clips even if output already exists.")
    args = parser.parse_args()

    if args.frame_step < 1:
        raise ValueError("--frame-step must be at least 1")

    input_root = args.input_root.resolve()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    if not input_root.exists():
        raise RuntimeError(f"Input root does not exist: {portable_path(input_root)}")

    exercise_filter = {normalize_name(value) for value in args.exercise} if args.exercise else None
    manifest_allowed_paths: set[str] | None = None
    manifest_allowed_exercises: set[str] | None = None
    if args.manifest_csv is not None:
        manifest_allowed_paths, manifest_allowed_exercises = load_manifest_csv(args.manifest_csv)

    clip_targets = discover_clip_targets(input_root, output_root, manifest_allowed_paths, manifest_allowed_exercises)
    if exercise_filter:
        clip_targets = [
            target
            for target in clip_targets
            if normalize_name(target.exercise.key) in exercise_filter
            or normalize_name(target.exercise.folder_name) in exercise_filter
            or any(normalize_name(alias) in exercise_filter for alias in target.exercise.aliases)
        ]

    if not clip_targets:
        raise RuntimeError(f"No workout videos found under {portable_path(input_root)}")

    processed_clips: list[dict[str, Any]] = []
    skipped_clips: list[dict[str, Any]] = []
    failed_clips: list[dict[str, Any]] = []
    exercise_counts: Counter[str] = Counter()
    total_windows = 0

    for clip_index, target in enumerate(clip_targets, start=1):
        if args.limit and len(processed_clips) >= args.limit:
            break

        try:
            summary = process_video(
                video_path=target.source_path,
                exercise=target.exercise,
                dataset_root=input_root,
                output_root=output_root,
                short_window_seconds=args.short_window_seconds,
                short_stride_seconds=args.short_stride_seconds,
                long_window_seconds=args.long_window_seconds,
                long_stride_seconds=args.long_stride_seconds,
                frame_step=args.frame_step,
                overwrite=args.overwrite,
            )
        except Exception as error:
            failed_clips.append(
                {
                    "sourceVideo": portable_path(target.source_path),
                    "exerciseKey": target.exercise.key,
                    "message": str(error),
                }
            )
            print(f"[{clip_index}/{len(clip_targets)}] FAILED {portable_path(target.source_path)}: {error}")
            continue

        if summary.get("skipped"):
            skipped_clips.append(summary)
        else:
            processed_clips.append(summary)
        exercise_counts[target.exercise.key] += 1
        total_windows += int(summary.get("shortWindowCount", 0)) + int(summary.get("longWindowCount", 0))
        print(f"[{clip_index}/{len(clip_targets)}] {target.exercise.key}: {portable_path(target.source_path)}")

    write_window_index(output_root, processed_clips + skipped_clips)

    index_payload = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "inputRoot": portable_path(input_root),
        "outputRoot": portable_path(output_root),
        "shortWindowSeconds": args.short_window_seconds,
        "shortStrideSeconds": args.short_stride_seconds,
        "longWindowSeconds": args.long_window_seconds,
        "longStrideSeconds": args.long_stride_seconds,
        "frameStep": args.frame_step,
        "manifestCsv": portable_path(args.manifest_csv) if args.manifest_csv else None,
        "totalDiscoveredClips": len(clip_targets),
        "processedClips": processed_clips,
        "skippedClips": skipped_clips,
        "failedClips": failed_clips,
        "exerciseCounts": dict(sorted(exercise_counts.items())),
        "totalWindowRows": total_windows,
    }

    (output_root / "index.json").write_text(json.dumps(index_payload, indent=2) + "\n", encoding="utf-8")

    print(f"Processed {len(processed_clips)} clips into {portable_path(output_root)}")
    if skipped_clips:
        print(f"Skipped {len(skipped_clips)} existing clips")
    if failed_clips:
        print(f"Failed {len(failed_clips)} clips")

    return 0 if not failed_clips else 1


if __name__ == "__main__":
    raise SystemExit(main())
