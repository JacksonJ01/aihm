from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_PATH = PROJECT_ROOT / "generated" / "workout-models" / "workout-centroid-model.json"
FEATURE_MODE_CHOICES = {"2d", "3d", "both"}
LEGACY_BOTH_FEATURE_COUNT = 21


def portable_path(value: Path) -> str:
    return value.resolve().as_posix()


def normalize_feature_mode(feature_mode: str) -> str:
    normalized_mode = feature_mode.strip().lower()
    if normalized_mode not in FEATURE_MODE_CHOICES:
        raise ValueError(f"feature mode must be one of {sorted(FEATURE_MODE_CHOICES)}")
    return normalized_mode


def resolve_feature_spec(model: dict[str, Any], override_feature_mode: str | None = None) -> tuple[str, bool]:
    if override_feature_mode is not None:
        return normalize_feature_mode(override_feature_mode), True

    stored_feature_mode = model.get("featureMode")
    if stored_feature_mode is not None:
        return normalize_feature_mode(str(stored_feature_mode)), True

    feature_count = len(model.get("featureMeans", []))
    if feature_count == LEGACY_BOTH_FEATURE_COUNT:
        return "both", False

    return "both", True


def safe_float(value: Any) -> float:
    if value is None:
        return float("nan")

    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def load_model(model_path: Path) -> dict[str, Any]:
    if not model_path.exists():
        raise RuntimeError(f"Model not found: {portable_path(model_path)}")

    return json.loads(model_path.read_text(encoding="utf-8"))


def flatten_window(window: dict[str, Any], feature_mode: str = "both", include_contraction: bool = True) -> np.ndarray:
    features: list[float] = []

    if feature_mode in {"2d", "both"}:
        vector = window.get("targetAngles2dVector", []) or []
        features.extend(safe_float(value) for value in vector)

    if feature_mode in {"3d", "both"}:
        vector = window.get("targetAngles3dVector", []) or []
        features.extend(safe_float(value) for value in vector)

    features.extend(
        [
            safe_float(window.get("visibleFrameRatio")),
            safe_float(window.get("averagePoseScore")),
            safe_float(window.get("frameCount")),
            safe_float(window.get("windowSeconds")),
            safe_float(window.get("strideSeconds")),
        ]
    )

    if include_contraction:
        features.extend(
            [
                safe_float(window.get("contractionScore2d")),
                safe_float(window.get("contractionScore3d")),
                safe_float(window.get("contractionScore")),
                safe_float(window.get("contractionStateValue")),
            ]
        )

    return np.asarray(features, dtype=np.float32)


def load_clip_windows(clip_path: Path, window_family: str | None) -> list[dict[str, Any]]:
    if not clip_path.exists():
        raise RuntimeError(f"Clip file not found: {portable_path(clip_path)}")

    clip_data = json.loads(clip_path.read_text(encoding="utf-8"))
    windows: list[dict[str, Any]] = []
    windows_section = clip_data.get("windows", [])

    if isinstance(windows_section, list):
        family_name = str(clip_data.get("windowFamily", "short"))
        if window_family is None or window_family == "all" or window_family == family_name:
            windows.extend(windows_section)
        return windows

    if window_family is None or window_family == "all":
        selected_families = list(windows_section.keys())
    else:
        selected_families = [window_family]

    for family in selected_families:
        windows.extend(windows_section.get(family, []))

    return windows


def standardize_features(features: np.ndarray, feature_means: np.ndarray, feature_stds: np.ndarray) -> np.ndarray:
    if features.size == 0:
        return features

    filled = np.where(np.isnan(features), feature_means, features)
    return (filled - feature_means) / feature_stds


def centroid_distances(features: np.ndarray, model: dict[str, Any]) -> tuple[list[str], np.ndarray]:
    labels = list(model["labels"])
    centroid_matrix = np.asarray([model["centroids"][label] for label in labels], dtype=np.float32)
    distances = np.sum((centroid_matrix[None, :, :] - features[:, None, :]) ** 2, axis=2)
    return labels, distances


def main() -> int:
    parser = argparse.ArgumentParser(description="Predict a workout label from a saved clip JSON and trained centroid model.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH, help="Path to the trained model artifact.")
    parser.add_argument("--clip", type=Path, required=True, help="Path to a clip.json file produced by the extractor.")
    parser.add_argument("--window-family", default="short", help="Which window family to use. Use 'all' to combine every family.")
    parser.add_argument("--feature-mode", default=None, help="Optional feature mode override: 2d, 3d, or both. Defaults to the model artifact.")
    args = parser.parse_args()

    model = load_model(args.model)
    feature_mode, include_contraction = resolve_feature_spec(model, args.feature_mode)
    clip_windows = load_clip_windows(args.clip, args.window_family)
    if not clip_windows:
        raise RuntimeError(f"No windows found in {portable_path(args.clip)} for family {args.window_family!r}")

    feature_means = np.asarray(model["featureMeans"], dtype=np.float32)
    feature_stds = np.asarray(model["featureStds"], dtype=np.float32)

    window_features = np.asarray([flatten_window(window, feature_mode, include_contraction) for window in clip_windows], dtype=np.float32)
    standardized_features = standardize_features(window_features, feature_means, feature_stds)

    labels, distances = centroid_distances(standardized_features, model)
    window_predictions: list[dict[str, Any]] = []
    votes: Counter[str] = Counter()
    weighted_votes: defaultdict[str, float] = defaultdict(float)

    for index, (window, distance_row) in enumerate(zip(clip_windows, distances)):
        best_index = int(np.argmin(distance_row))
        predicted_label = labels[best_index]
        vote_weight = 1.0 / (1.0 + float(distance_row[best_index]))
        fallback_window_id = window.get("windowId") or window.get("windowIndex") or f"window-{index}"
        votes[predicted_label] += 1
        weighted_votes[predicted_label] += vote_weight
        window_predictions.append(
            {
                "windowId": fallback_window_id,
                "windowFamily": window.get("windowFamily"),
                "predictedLabel": predicted_label,
                "distance": round(float(distance_row[best_index]), 6),
                "voteWeight": round(vote_weight, 6),
            }
        )

    if weighted_votes:
        final_label = max(weighted_votes.items(), key=lambda item: (item[1], votes[item[0]]))[0]
    else:
        final_label = votes.most_common(1)[0][0]

    result = {
        "clipPath": portable_path(args.clip),
        "modelPath": portable_path(args.model),
        "windowFamily": args.window_family,
        "featureMode": feature_mode,
        "includeContractionFeatures": include_contraction,
        "predictedLabel": final_label,
        "voteCounts": dict(votes),
        "weightedVotes": {label: round(score, 6) for label, score in weighted_votes.items()},
        "windowPredictions": window_predictions,
    }

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())