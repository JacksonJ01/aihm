from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WINDOWS_PATH = PROJECT_ROOT / "generated" / "workout-pose-dataset"
DEFAULT_MODEL_OUTPUT_PATH = PROJECT_ROOT / "generated" / "workout-models" / "workout-centroid-model.json"
DEFAULT_TEST_RATIO = 0.1
DEFAULT_VALIDATION_RATIO = 0.1
DEFAULT_MAX_WINDOWS_PER_CLIP = 0
SCHEMA_VERSION = 3
FEATURE_MODE_CHOICES = {"2d", "3d", "both"}


@dataclass(frozen=True)
class WindowRow:
    clip_id: str
    exercise_key: str
    label: str
    window_family: str
    source_video: str
    feature_vector: list[float]
    feature_source: str


def portable_path(value: Path) -> str:
    return value.resolve().as_posix()


def normalize_feature_mode(feature_mode: str) -> str:
    normalized_mode = feature_mode.strip().lower()
    if normalized_mode not in FEATURE_MODE_CHOICES:
        raise ValueError(f"--feature-mode must be one of {sorted(FEATURE_MODE_CHOICES)}")
    return normalized_mode


def safe_float(value: Any) -> float:
    if value is None:
        return float("nan")

    if isinstance(value, bool):
        return float(value)

    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def flatten_window_features(window_row: dict[str, Any], feature_mode: str) -> list[float]:
    fixed_vector = window_row.get("featureVectorFixed")
    if isinstance(fixed_vector, list):
        return [safe_float(value) for value in fixed_vector]

    features: list[float] = []

    if feature_mode in {"2d", "both"}:
        vector = window_row.get("targetAngles2dVector", []) or []
        features.extend(safe_float(value) for value in vector)

    if feature_mode in {"3d", "both"}:
        vector = window_row.get("targetAngles3dVector", []) or []
        features.extend(safe_float(value) for value in vector)

    features.extend(
        [
            safe_float(window_row.get("visibleFrameRatio")),
            safe_float(window_row.get("averagePoseScore")),
            safe_float(window_row.get("frameCount")),
            safe_float(window_row.get("windowSeconds")),
            safe_float(window_row.get("strideSeconds")),
            safe_float(window_row.get("contractionScore2d")),
            safe_float(window_row.get("contractionScore3d")),
            safe_float(window_row.get("contractionScore")),
            safe_float(window_row.get("contractionStateValue")),
        ]
    )

    return features


def build_feature_names(feature_mode: str) -> list[str]:
    names: list[str] = []

    if feature_mode in {"2d", "both"}:
        names.extend([f"angle2d:{index}" for index in range(8)])

    if feature_mode in {"3d", "both"}:
        names.extend([f"angle3d:{index}" for index in range(8)])

    names.extend(
        [
            "visibleFrameRatio",
            "averagePoseScore",
            "frameCount",
            "windowSeconds",
            "strideSeconds",
            "contractionScore2d",
            "contractionScore3d",
            "contractionScore",
            "contractionStateValue",
        ]
    )
    return names


def build_fixed_feature_names(feature_count: int) -> list[str]:
    return [f"fixed:{index}" for index in range(feature_count)]


def load_window_rows(windows_path: Path, window_families: set[str] | None, feature_mode: str) -> list[WindowRow]:
    rows: list[WindowRow] = []
    source_paths: list[Path]

    if windows_path.is_file() and windows_path.suffix.lower() == ".jsonl":
        source_paths = [windows_path]
    elif windows_path.is_file() and windows_path.name == "clip.json":
        source_paths = [windows_path]
    elif windows_path.is_dir():
        windows_file = windows_path / "windows.jsonl"
        if windows_file.exists():
            source_paths = [windows_file]
        else:
            source_paths = [
                path
                for path in sorted(windows_path.rglob("*.json"))
                if path.name not in {"index.json", "manifest.json"}
                and not path.name.endswith(".jsonl")
            ]
    else:
        raise RuntimeError(f"Training data root not found: {portable_path(windows_path)}")

    if not source_paths:
        raise RuntimeError(f"No window or clip JSON files found under: {portable_path(windows_path)}")

    for source_path in source_paths:
        if source_path.name == "windows.jsonl":
            with source_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue

                    window_row = json.loads(line)
                    if window_families and window_row.get("windowFamily") not in window_families:
                        continue

                    rows.append(
                        WindowRow(
                            clip_id=str(window_row["clipId"]),
                            exercise_key=str(window_row["exerciseKey"]),
                            label=str(window_row.get("label", window_row["exerciseKey"])),
                            window_family=str(window_row.get("windowFamily", "unknown")),
                            source_video=str(window_row.get("sourceVideo", "")),
                            feature_vector=flatten_window_features(window_row, feature_mode),
                            feature_source="fixed" if isinstance(window_row.get("featureVectorFixed"), list) else "legacy",
                        )
                    )
            continue

        clip_data = json.loads(source_path.read_text(encoding="utf-8"))
        windows_section = clip_data.get("windows", [])
        derived_clip_id = str(clip_data.get("clipId", derive_clip_id(source_path)))

        if isinstance(windows_section, list):
            window_family = str(clip_data.get("windowFamily", "short"))
            if not window_families or window_family in window_families:
                for window_row in windows_section:
                    rows.append(
                        WindowRow(
                            clip_id=derived_clip_id,
                            exercise_key=str(clip_data["exerciseKey"]),
                            label=str(clip_data.get("label", clip_data["exerciseKey"])),
                            window_family=window_family,
                            source_video=str(clip_data.get("sourceVideo", "")),
                            feature_vector=flatten_window_features(window_row, feature_mode),
                            feature_source="fixed" if isinstance(window_row.get("featureVectorFixed"), list) else "legacy",
                        )
                    )
            continue

        for window_family, windows in windows_section.items():
            if window_families and window_family not in window_families:
                continue

            for window_row in windows:
                rows.append(
                    WindowRow(
                        clip_id=derived_clip_id,
                        exercise_key=str(clip_data["exerciseKey"]),
                        label=str(clip_data.get("label", clip_data["exerciseKey"])),
                        window_family=str(window_family),
                        source_video=str(clip_data.get("sourceVideo", "")),
                        feature_vector=flatten_window_features(window_row, feature_mode),
                        feature_source="fixed" if isinstance(window_row.get("featureVectorFixed"), list) else "legacy",
                    )
                )

    return rows


def cap_rows_per_clip(rows: list[WindowRow], max_windows_per_clip: int) -> tuple[list[WindowRow], int]:
    if max_windows_per_clip <= 0:
        return rows, 0

    clip_groups: dict[str, list[WindowRow]] = defaultdict(list)
    for row in rows:
        clip_groups[row.clip_id].append(row)

    capped_rows: list[WindowRow] = []
    removed_count = 0

    for clip_id in sorted(clip_groups):
        clip_rows = clip_groups[clip_id]
        if len(clip_rows) <= max_windows_per_clip:
            capped_rows.extend(clip_rows)
            continue

        sample_indices = np.linspace(0, len(clip_rows) - 1, num=max_windows_per_clip, dtype=int)
        selected_indices = list(dict.fromkeys(int(index) for index in sample_indices))
        capped_rows.extend(clip_rows[index] for index in selected_indices)
        removed_count += len(clip_rows) - len(selected_indices)

    return capped_rows, removed_count


def clip_split_bucket(clip_id: str) -> float:
    digest = hashlib.sha1(clip_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def derive_clip_id(source_path: Path) -> str:
    digest = hashlib.sha1(portable_path(source_path).encode("utf-8")).hexdigest()
    return digest[:12]


def split_rows(rows: list[WindowRow], test_ratio: float, validation_ratio: float) -> dict[str, list[WindowRow]]:
    train_rows: list[WindowRow] = []
    validation_rows: list[WindowRow] = []
    test_rows: list[WindowRow] = []

    exercise_groups: dict[str, dict[str, list[WindowRow]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        exercise_groups[row.exercise_key][row.clip_id].append(row)

    for exercise_key in sorted(exercise_groups):
        clip_groups = exercise_groups[exercise_key]
        for clip_id in sorted(clip_groups):
            bucket = clip_split_bucket(f"{exercise_key}:{clip_id}")
            if bucket < test_ratio:
                test_rows.extend(clip_groups[clip_id])
            elif bucket < test_ratio + validation_ratio:
                validation_rows.extend(clip_groups[clip_id])
            else:
                train_rows.extend(clip_groups[clip_id])

    if not train_rows and rows:
        train_rows = rows[:]
        validation_rows = []
        test_rows = []

    return {"train": train_rows, "validation": validation_rows, "test": test_rows}


def as_matrix(rows: list[WindowRow]) -> np.ndarray:
    if not rows:
        return np.empty((0, 0), dtype=np.float32)

    return np.asarray([row.feature_vector for row in rows], dtype=np.float32)


def impute_and_standardize(train_matrix: np.ndarray, *other_matrices: np.ndarray) -> tuple[np.ndarray, list[np.ndarray], np.ndarray, np.ndarray]:
    if train_matrix.size == 0:
        raise RuntimeError("No training samples were found in the windows file.")

    finite_mask = np.isfinite(train_matrix)
    counts = finite_mask.sum(axis=0)
    safe_train = np.where(finite_mask, train_matrix, 0.0)
    feature_means = np.divide(safe_train.sum(axis=0), counts, out=np.zeros(train_matrix.shape[1], dtype=np.float32), where=counts > 0)
    train_filled = np.where(np.isnan(train_matrix), feature_means, train_matrix)
    centered = np.where(np.isnan(train_filled), feature_means, train_filled) - feature_means
    variance = np.divide((centered ** 2).sum(axis=0), counts, out=np.ones(train_matrix.shape[1], dtype=np.float32), where=counts > 0)
    feature_stds = np.sqrt(variance)
    feature_stds = np.where((feature_stds == 0) | ~np.isfinite(feature_stds), 1.0, feature_stds)

    standardized_train = (train_filled - feature_means) / feature_stds
    standardized_others: list[np.ndarray] = []
    for matrix in other_matrices:
        if matrix.size == 0:
            standardized_others.append(matrix)
            continue

        filled = np.where(np.isnan(matrix), feature_means, matrix)
        standardized_others.append((filled - feature_means) / feature_stds)

    return standardized_train, standardized_others, feature_means, feature_stds


def train_centroid_model(features: np.ndarray, labels: list[str]) -> dict[str, np.ndarray]:
    centroids: dict[str, np.ndarray] = {}
    label_to_rows: dict[str, list[np.ndarray]] = defaultdict(list)

    for vector, label in zip(features, labels):
        label_to_rows[label].append(vector)

    for label, vectors in label_to_rows.items():
        centroids[label] = np.mean(np.asarray(vectors, dtype=np.float32), axis=0)

    return centroids


def predict_with_centroids(features: np.ndarray, centroids: dict[str, np.ndarray]) -> list[str]:
    if features.size == 0:
        return []

    labels = sorted(centroids)
    centroid_matrix = np.asarray([centroids[label] for label in labels], dtype=np.float32)
    predictions: list[str] = []

    for vector in features:
        distances = np.sum((centroid_matrix - vector) ** 2, axis=1)
        predictions.append(labels[int(np.argmin(distances))])

    return predictions


def accuracy_score(y_true: list[str], y_pred: list[str]) -> float:
    if not y_true:
        return 0.0

    correct = sum(1 for true_label, predicted_label in zip(y_true, y_pred) if true_label == predicted_label)
    return correct / len(y_true)


def build_confusion_matrix(y_true: list[str], y_pred: list[str], label_order: list[str]) -> list[list[int]]:
    label_to_index = {label: index for index, label in enumerate(label_order)}
    matrix = np.zeros((len(label_order), len(label_order)), dtype=int)

    for true_label, predicted_label in zip(y_true, y_pred):
        true_index = label_to_index[true_label]
        predicted_index = label_to_index[predicted_label]
        matrix[true_index, predicted_index] += 1

    return matrix.tolist()


def summarize_per_class_metrics(y_true: list[str], y_pred: list[str], label_order: list[str]) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    true_counts = Counter(y_true)
    predicted_counts = Counter(y_pred)

    for label in label_order:
        true_positive = sum(1 for true_label, predicted_label in zip(y_true, y_pred) if true_label == label and predicted_label == label)
        false_positive = predicted_counts[label] - true_positive
        false_negative = true_counts[label] - true_positive

        precision_denominator = true_positive + false_positive
        recall_denominator = true_positive + false_negative
        precision = true_positive / precision_denominator if precision_denominator else None
        recall = true_positive / recall_denominator if recall_denominator else None

        if precision is None or recall is None or (precision + recall) == 0:
            f1_score = None
        else:
            f1_score = 2 * precision * recall / (precision + recall)

        metrics[label] = {
            "support": true_counts[label],
            "predictedCount": predicted_counts[label],
            "truePositive": true_positive,
            "falsePositive": false_positive,
            "falseNegative": false_negative,
            "precision": round(precision, 6) if precision is not None else None,
            "recall": round(recall, 6) if recall is not None else None,
            "f1": round(f1_score, 6) if f1_score is not None else None,
        }

    return metrics


def per_class_counts(labels: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(labels).items()))


def evaluate_split(rows: list[WindowRow], centroids: dict[str, np.ndarray], feature_means: np.ndarray, feature_stds: np.ndarray) -> dict[str, Any]:
    if not rows:
        return {
            "sampleCount": 0,
            "accuracy": None,
            "classCounts": {},
            "predictedCounts": {},
            "perClassMetrics": {},
            "confusionMatrix": [],
            "labelOrder": [],
        }

    matrix = np.asarray([row.feature_vector for row in rows], dtype=np.float32)
    matrix = np.where(np.isnan(matrix), feature_means, matrix)
    matrix = (matrix - feature_means) / feature_stds
    predicted = predict_with_centroids(matrix, centroids)
    labels = [row.exercise_key for row in rows]
    label_order = sorted(set(labels) | set(predicted))

    return {
        "sampleCount": len(rows),
        "accuracy": round(accuracy_score(labels, predicted), 6),
        "classCounts": per_class_counts(labels),
        "predictedCounts": per_class_counts(predicted),
        "perClassMetrics": summarize_per_class_metrics(labels, predicted, label_order),
        "confusionMatrix": build_confusion_matrix(labels, predicted, label_order),
        "labelOrder": label_order,
    }


def build_model_payload(
    windows_path: Path,
    window_families: set[str] | None,
    feature_mode: str,
    test_ratio: float,
    validation_ratio: float,
    max_windows_per_clip: int,
) -> dict[str, Any]:
    rows = load_window_rows(windows_path, window_families, feature_mode)
    if not rows:
        raise RuntimeError(f"No training rows found in {portable_path(windows_path)}")

    feature_lengths = {len(row.feature_vector) for row in rows}
    if len(feature_lengths) != 1:
        raise RuntimeError(
            "Inconsistent feature vector lengths in training rows. "
            f"Found lengths: {sorted(feature_lengths)}"
        )

    feature_sources = {row.feature_source for row in rows}
    if len(feature_sources) != 1:
        raise RuntimeError(
            "Mixed feature sources detected. Keep training rows either fully legacy or fully fixed vector."
        )
    feature_source = next(iter(feature_sources))
    feature_count = next(iter(feature_lengths))

    rows, removed_window_count = cap_rows_per_clip(rows, max_windows_per_clip)

    splits = split_rows(rows, test_ratio, validation_ratio)
    train_rows = splits["train"]
    validation_rows = splits["validation"]
    test_rows = splits["test"]

    train_matrix = as_matrix(train_rows)
    validation_matrix = as_matrix(validation_rows)
    test_matrix = as_matrix(test_rows)

    standardized_train, standardized_others, feature_means, feature_stds = impute_and_standardize(
        train_matrix,
        validation_matrix,
        test_matrix,
    )
    standardized_validation, standardized_test = standardized_others

    train_labels = [row.exercise_key for row in train_rows]
    centroids = train_centroid_model(standardized_train, train_labels)

    train_metrics = evaluate_split(train_rows, centroids, feature_means, feature_stds)
    validation_metrics = evaluate_split(validation_rows, centroids, feature_means, feature_stds)
    test_metrics = evaluate_split(test_rows, centroids, feature_means, feature_stds)

    label_order = sorted(centroids)
    feature_names = build_fixed_feature_names(feature_count) if feature_source == "fixed" else build_feature_names(feature_mode)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "trainedAt": datetime.now(timezone.utc).isoformat(),
        "windowsPath": portable_path(windows_path),
        "featureMode": feature_mode,
        "featureSource": feature_source,
        "maxWindowsPerClip": max_windows_per_clip,
        "windowFamilies": sorted(window_families) if window_families else ["short", "long"],
        "featureNames": feature_names,
        "labels": label_order,
        "featureMeans": feature_means.tolist(),
        "featureStds": feature_stds.tolist(),
        "centroids": {label: centroids[label].tolist() for label in label_order},
        "splits": {
            "train": train_metrics,
            "validation": validation_metrics,
            "test": test_metrics,
            "sampleCounts": {
                "train": len(train_rows),
                "validation": len(validation_rows),
                "test": len(test_rows),
            },
        },
        "classCounts": {
            "train": per_class_counts(train_labels),
            "validation": per_class_counts([row.exercise_key for row in validation_rows]),
            "test": per_class_counts([row.exercise_key for row in test_rows]),
        },
        "sourceSummary": {
            "clipCount": len({row.clip_id for row in rows}),
            "windowCount": len(rows),
            "removedWindowCount": removed_window_count,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Train a baseline workout classifier from extracted pose windows.")
    parser.add_argument("--windows", type=Path, default=DEFAULT_WINDOWS_PATH, help="Path to the windows.jsonl file produced by the extractor.")
    parser.add_argument("--output-model", type=Path, default=DEFAULT_MODEL_OUTPUT_PATH, help="Path where the trained model artifact should be written.")
    parser.add_argument("--feature-mode", default="both", help="Which angle features to train on: 2d, 3d, or both.")
    parser.add_argument("--benchmark-feature-mode", action="append", default=[], help="Optional feature mode to benchmark against the selected training mode. Can be repeated.")
    parser.add_argument("--max-windows-per-clip", type=int, default=DEFAULT_MAX_WINDOWS_PER_CLIP, help="Maximum windows to keep per clip before training. Use 0 to keep all windows.")
    parser.add_argument("--window-family", action="append", default=[], help="Optional window family filter. Can be repeated.")
    parser.add_argument("--test-ratio", type=float, default=DEFAULT_TEST_RATIO, help="Fraction of clips to reserve for test evaluation.")
    parser.add_argument("--validation-ratio", type=float, default=DEFAULT_VALIDATION_RATIO, help="Fraction of clips to reserve for validation.")
    args = parser.parse_args()

    if args.test_ratio < 0 or args.validation_ratio < 0 or args.test_ratio + args.validation_ratio >= 1:
        raise ValueError("--test-ratio and --validation-ratio must be non-negative and sum to less than 1")

    feature_mode = normalize_feature_mode(args.feature_mode)

    window_families = set(args.window_family) if args.window_family else None
    model_payload = build_model_payload(
        windows_path=args.windows,
        window_families=window_families,
        feature_mode=feature_mode,
        test_ratio=args.test_ratio,
        validation_ratio=args.validation_ratio,
        max_windows_per_clip=args.max_windows_per_clip,
    )

    benchmark_modes = [normalize_feature_mode(mode) for mode in args.benchmark_feature_mode]
    benchmark_modes = list(dict.fromkeys([feature_mode, *benchmark_modes]))
    if len(benchmark_modes) > 1:
        model_payload["benchmarkResults"] = {
            mode: {
                "featureMode": mode,
                "featureNames": build_feature_names(mode),
                "splits": build_model_payload(
                    windows_path=args.windows,
                    window_families=window_families,
                    feature_mode=mode,
                    test_ratio=args.test_ratio,
                    validation_ratio=args.validation_ratio,
                    max_windows_per_clip=args.max_windows_per_clip,
                )["splits"],
            }
            for mode in benchmark_modes
        }

    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    args.output_model.write_text(json.dumps(model_payload, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote model to {portable_path(args.output_model)}")
    print(json.dumps(model_payload["splits"], indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())