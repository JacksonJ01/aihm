from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .annotations import annotation_to_frame_targets, load_annotation_file
from .config import resolve_path
from .features import select_model_features
from .splits import grouped_split, save_splits
from .validation import validate_frame_dataframe
from .windowing import UNKNOWN, WindowRecord, generate_window_records

CATEGORICAL_TASKS = {"classification", "sequence_classification"}
IGNORED_TASKS = {"identity", "evaluation_only"}


def _target_specs(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    targets = cfg.get("dataset", {}).get("targets", {})
    if not targets:
        raise ValueError("No dataset targets are configured.")
    result: dict[str, dict[str, Any]] = {}
    valid_tasks = CATEGORICAL_TASKS | {"sequence_binary", "regression"} | IGNORED_TASKS
    for name, raw in targets.items():
        spec = dict(raw)
        spec.setdefault("enabled", True)
        spec.setdefault("trainable", False)
        spec.setdefault("evaluation_role", "available")
        spec.setdefault("task", "classification")
        spec.setdefault("weight", 1.0)
        spec.setdefault("min_known_fraction", 0.8)
        spec.setdefault("min_consistency", 0.0)
        spec.setdefault("frame_column", f"{name}_label")
        if spec["task"] not in valid_tasks:
            raise ValueError(f"Unsupported dataset target task for {name}: {spec['task']}")
        if bool(spec.get("trainable", False)) and str(spec["task"]) == "identity":
            raise ValueError(f"Identity target {name} cannot be trainable. Use it only for grouping/evaluation metadata.")
        result[name] = spec
    return result


def _resolve_artifact(root: Path, row: pd.Series, key: str, default: str) -> Path:
    value = row.get(key)
    value = "" if pd.isna(value) else str(value)
    return resolve_path(root, value or default)


def _passes_target_coverage(record: WindowRecord, specs: dict[str, dict[str, Any]]) -> bool:
    coverage = record.targets.get("_coverage", {})
    consistency = record.targets.get("_consistency", {})
    for name, spec in specs.items():
        if not bool(spec.get("enabled", True)):
            continue
        min_known = float(spec.get("min_known_fraction", 0.0))
        task = str(spec.get("task", "classification"))
        if task in IGNORED_TASKS:
            continue
        if coverage.get(name, 0.0) < min_known:
            return False
        if task == "classification" and consistency.get(name, 0.0) < float(spec.get("min_consistency", 0.0)):
            return False
        if bool(spec.get("require_known", False)):
            value = record.targets.get(name)
            if task in CATEGORICAL_TASKS and value == UNKNOWN:
                return False
            if task == "regression" and value is None:
                return False
    return True


def _collect_label_mappings(records: list[WindowRecord], specs: dict[str, dict[str, Any]]) -> dict[str, dict[str, int]]:
    mappings: dict[str, dict[str, int]] = {}
    for name, spec in specs.items():
        if not bool(spec.get("enabled", True)) or str(spec.get("task")) not in CATEGORICAL_TASKS:
            continue
        labels: set[str] = set()
        for record in records:
            value = record.targets.get(name)
            if isinstance(value, list):
                labels.update(str(item) for item in value if str(item) != UNKNOWN)
            elif value is not None and str(value) != UNKNOWN:
                labels.add(str(value))
        mappings[name] = {label: index for index, label in enumerate(sorted(labels))}
    return mappings


def _encode_records(
    records: list[WindowRecord],
    specs: dict[str, dict[str, Any]],
    mappings: dict[str, dict[str, int]],
) -> dict[str, np.ndarray]:
    arrays: dict[str, list[Any]] = {}
    for name, spec in specs.items():
        if not bool(spec.get("enabled", True)) or str(spec.get("task")) in IGNORED_TASKS:
            continue
        arrays[name] = []

    for record in records:
        for name in arrays:
            spec = specs[name]
            task = str(spec.get("task"))
            value = record.targets.get(name)
            if task == "sequence_classification":
                mapping = mappings.get(name, {})
                arrays[name].append(np.asarray([mapping.get(str(item), -1) for item in value], dtype=np.int64))
            elif task == "classification":
                arrays[name].append(int(mappings.get(name, {}).get(str(value), -1)))
            elif task == "sequence_binary":
                arrays[name].append(np.asarray(value, dtype=np.int64))
            elif task == "regression":
                arrays[name].append(np.nan if value is None else float(value))
            else:
                raise ValueError(f"Unsupported dataset target task: {task}")

    encoded: dict[str, np.ndarray] = {}
    for name, values in arrays.items():
        if not values:
            encoded[name] = np.asarray([], dtype=np.float32)
        elif isinstance(values[0], np.ndarray):
            encoded[name] = np.stack(values)
        else:
            encoded[name] = np.asarray(values)
    return encoded


def _write_split(
    output_dir: Path,
    split: str,
    records: list[WindowRecord],
    specs: dict[str, dict[str, Any]],
    mappings: dict[str, dict[str, int]],
    feature_count: int,
    window_frames: int,
) -> dict[str, Any]:
    X = (
        np.stack([record.X for record in records]).astype(np.float32)
        if records
        else np.empty((0, window_frames, feature_count), dtype=np.float32)
    )
    targets = _encode_records(records, specs, mappings)
    payload = {"X": X}
    payload.update({f"target_{name}": value for name, value in targets.items()})
    np.savez_compressed(output_dir / f"{split}.npz", **payload)
    (output_dir / f"{split}_metadata.json").write_text(
        json.dumps([record.metadata for record in records], indent=2),
        encoding="utf-8",
    )
    return {
        "samples": int(len(records)),
        "shape": list(X.shape),
        "arrays": {name: list(value.shape) for name, value in targets.items()},
        "videos": sorted({record.metadata["video_id"] for record in records}),
        "participants": sorted({record.metadata["participant_id"] for record in records if record.metadata.get("participant_id")}),
    }


def build_dataset_experiment(
    *,
    root: str | Path,
    manifest_path: str | Path,
    cfg: dict[str, Any],
    experiment_name: str | None = None,
) -> Path:
    """Build the reproducible ML dataset used by training and evaluation.

    Processing artifacts remain immutable. Annotation labels are joined into a
    temporary frame table, windows are resampled to the configured model FPS,
    and only the experiment-specific NPZ/JSON artifacts receive labels.
    """
    root = Path(root)
    manifest_path = Path(manifest_path)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    manifest = pd.read_csv(manifest_path)
    if manifest.empty:
        raise ValueError("Video manifest contains no rows.")

    splits = grouped_split(manifest, cfg)
    target_specs = _target_specs(cfg)
    split_groups = {
        group: split
        for split in ("train", "val", "test")
        for group in splits.get(split, [])
    }
    group_column = splits["group_key"]
    model_fps = float(cfg.get("windows", {}).get("model_fps", 30.0))
    window_seconds = float(cfg["windows"]["seconds"])
    stride_seconds = float(cfg["windows"]["stride_seconds"])
    window_frames = max(1, int(round(window_seconds * model_fps)))

    records_by_split: dict[str, list[WindowRecord]] = {"train": [], "val": [], "test": []}
    feature_columns: list[str] | None = None
    source_videos = 0
    source_details: list[dict[str, Any]] = []
    require_completed = bool(cfg.get("dataset", {}).get("require_completed_annotations", True))
    boundary_radius = int(cfg.get("dataset", {}).get("rep_boundary_radius_frames", 0))

    for _, row in manifest.iterrows():
        group_value = "" if pd.isna(row[group_column]) else str(row[group_column]).strip()
        split = split_groups.get(group_value)
        if split not in records_by_split:
            continue

        session_id = str(row["session_id"])
        video_id = str(row["video_id"])
        default_feature = f"data/processed/{session_id}/{video_id}/parquet/{video_id}_features.parquet"
        default_annotation = f"data/processed/{session_id}/{video_id}/annotations/{video_id}_annotations.json"
        feature_path = _resolve_artifact(root, row, "features_path", default_feature)
        annotation_path = _resolve_artifact(root, row, "annotation_json", default_annotation)
        if not feature_path.exists() or not annotation_path.exists():
            raise FileNotFoundError(
                f"Missing dataset artifacts for {session_id}/{video_id}: "
                f"{feature_path}, {annotation_path}"
            )

        df = pd.read_parquet(feature_path)
        validate_frame_dataframe(df)
        annotation_document = load_annotation_file(annotation_path)
        annotation_session = annotation_document.get("annotation_session", {})
        if require_completed and annotation_session.get("status") != "completed":
            raise ValueError(
                f"Annotation session for {session_id}/{video_id} is not marked completed. "
                "Complete annotation before building a training dataset."
            )

        labeled_df = annotation_to_frame_targets(
            df,
            annotation_document,
            boundary_radius_frames=boundary_radius,
        )
        selected_features = select_model_features(df, cfg)
        if feature_columns is None:
            feature_columns = selected_features
        elif selected_features != feature_columns:
            raise ValueError(
                "Feature schema differs across videos; process all recordings with one feature configuration."
            )

        video_records = generate_window_records(
            labeled_df,
            feature_columns,
            window_seconds=window_seconds,
            stride_seconds=stride_seconds,
            min_valid_pose_fraction=float(cfg["windows"].get("min_valid_pose_fraction", 0.8)),
            target_specs=target_specs,
            model_fps=model_fps,
        )
        filtered_records = [record for record in video_records if _passes_target_coverage(record, target_specs)]
        records_by_split[split].extend(filtered_records)
        source_videos += 1
        source_details.append({
            "session_id": session_id,
            "video_id": video_id,
            "participant_id": str(row.get("participant_id", "") or ""),
            "split": split,
            "source_fps": float(video_records[0].metadata["source_fps"]) if video_records else None,
            "windows_before_filter": len(video_records),
            "windows_after_filter": len(filtered_records),
            "annotation_status": annotation_session.get("status"),
        })

    if feature_columns is None:
        raise RuntimeError("No feature artifacts were successfully loaded.")
    if not records_by_split["train"]:
        raise RuntimeError("No usable training windows were produced. Check annotation coverage, split sizes, and target thresholds.")

    label_mappings = _collect_label_mappings(records_by_split["train"], target_specs)
    experiment_name = experiment_name or cfg.get("dataset", {}).get("experiment_name", "experiment_001")
    output_dir = root / "data" / "datasets" / str(experiment_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    save_splits(splits, output_dir / "splits.json")

    split_summaries = {
        split: _write_split(
            output_dir,
            split,
            records,
            target_specs,
            label_mappings,
            len(feature_columns),
            window_frames,
        )
        for split, records in records_by_split.items()
    }

    dataset_manifest = {
        "schema_version": "1.1",
        "project": cfg.get("project", {}),
        "experiment_name": str(experiment_name),
        "source_manifest": str(manifest_path),
        "split_strategy": splits,
        "feature_columns": feature_columns,
        "feature_count": len(feature_columns),
        "windows": {
            **cfg.get("windows", {}),
            "model_fps": model_fps,
            "window_frames": window_frames,
            "fixed_temporal_shape": True,
        },
        "targets": target_specs,
        "label_mappings": label_mappings,
        "label_encoding": "categorical mappings are fitted from training windows only; unknown sequence labels use -1",
        "split_summaries": split_summaries,
        "source_video_count": source_videos,
        "source_details": source_details,
        "training_target_policy": {
            name: {
                "enabled": bool(spec.get("enabled", True)),
                "trainable": bool(spec.get("trainable", False)),
                "evaluation_role": spec.get("evaluation_role"),
                "task": spec.get("task"),
                "weight": float(spec.get("weight", 1.0)),
            }
            for name, spec in target_specs.items()
        },
        "reproducibility": {
            "config": cfg,
            "feature_parquet_is_input_only": True,
            "annotation_source_of_truth": "annotations.json",
            "require_completed_annotations": require_completed,
            "rep_boundary_radius_frames": boundary_radius,
            "note": "Source FPS is preserved in feature artifacts; model windows are resampled to one configured model FPS.",
        },
    }
    (output_dir / "dataset_manifest.json").write_text(
        json.dumps(dataset_manifest, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    return output_dir
