"""Run a deterministic, MediaPipe-free AIHuMo pipeline smoke test.

This exercises the canonical data contract from synthetic landmarks through
feature Parquet, graph provenance, annotation persistence, frame targets, and
fixed-rate dataset windows. It writes only to a temporary directory.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aihumo.annotations import AnnotationState, annotation_to_frame_targets, validate_annotations
from aihumo.config import load_config
from aihumo.features import ANGLE_PREFIXES, FeatureEngine, angle_family
from aihumo.graphs import generate_angle_graphs
from aihumo.splits import grouped_split
from aihumo.storage import load_parquet, save_parquet_atomic
from aihumo.validation import validate_frame_dataframe
from aihumo.windowing import generate_window_records


def synthetic_frames(count: int = 90) -> pd.DataFrame:
    t = np.arange(count, dtype=float) / 30.0
    data: dict[str, object] = {
        "session_id": ["S0001"] * count,
        "video_id": ["V0001"] * count,
        "participant_id": ["P0001"] * count,
        "camera_id": ["C0001"] * count,
        "frame_id": np.arange(count, dtype=np.int64),
        "timestamp_s": t,
        "fps": np.full(count, 30.0),
        "pose_present": np.ones(count, dtype=np.int8),
    }
    # A stable synthetic standing pose with a smooth knee-like movement.
    base = np.zeros((33, 3), dtype=float)
    base[:, 0] = 0.5
    base[:, 1] = 0.5
    for index in range(33):
        base[index, 0] += (index % 5) * 0.01
        base[index, 1] += (index % 7) * 0.01
    movement = 0.03 * np.sin(2.0 * np.pi * 0.5 * t)
    for index in range(33):
        data[f"lm{index}_x"] = base[index, 0] + movement
        data[f"lm{index}_y"] = base[index, 1] + movement * (1.0 if index in {25, 26, 27, 28} else 0.2)
        data[f"lm{index}_z"] = np.zeros(count)
        data[f"world{index}_x"] = data[f"lm{index}_x"]
        data[f"world{index}_y"] = data[f"lm{index}_y"]
        data[f"world{index}_z"] = data[f"lm{index}_z"]
    return pd.DataFrame(data)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    cfg = load_config(ROOT / "configs" / "config.json")
    frame_df = synthetic_frames()
    feature_result = FeatureEngine(cfg).build(frame_df, frame_size=(1280, 720))
    features = feature_result.dataframe
    validate_frame_dataframe(features)
    assert all(len(angle_family(features.columns, prefix)) == 15 for prefix in ANGLE_PREFIXES.values())

    with tempfile.TemporaryDirectory(prefix="aihumo_simulation_") as temp:
        root = Path(temp)
        feature_path = root / "V0001_features.parquet"
        save_parquet_atomic(features, feature_path)
        before = digest(feature_path)
        assert load_parquet(feature_path).equals(features)

        graph_manifest = generate_angle_graphs(
            features,
            root / "Graphs",
            exercise_id="bodyweight_squat",
            feature_data_version=cfg["project"]["processing_version"],
            export_images=False,
        )
        assert graph_manifest["angleFeatureIds"]
        assert graph_manifest["angleSpace"] == "video_plane_2d"
        assert Path(graph_manifest["manifestPath"]).exists()

        state = AnnotationState.new({
            "session_id": "S0001", "video_id": "V0001", "participant_id": "P0001",
            "camera_id": "C0001", "features_parquet": str(feature_path),
        })
        state.add({
            "annotation_id": "A00001", "segment_id": "V0001_SEG0001",
            "annotation_type": "general", "start_frame": 0, "end_frame": 9,
            "activity_state": "idle", "phase": "none", "form_label": "unlabeled",
            "notes": "Setup interval; no exercise hierarchy is claimed.",
        })
        state.add({
            "annotation_id": "A00002", "segment_id": "V0001_SEG0002",
            "annotation_type": "activity_state", "start_frame": 13, "end_frame": 89,
            "activity_state": "active", "phase": "none", "form_label": "unlabeled",
        })
        state.add({
            "annotation_id": "A00003", "segment_id": "V0001_SEG0003",
            "annotation_type": "set", "start_frame": 13, "end_frame": 89,
            "activity_state": "active", "exercise": "bodyweight_squat",
            "set_id": 1, "phase": "none", "form_label": "unlabeled",
        })
        state.add({
            "annotation_id": "A00004", "segment_id": "V0001_SEG0004",
            "annotation_type": "rep", "start_frame": 15, "end_frame": 45,
            "activity_state": "active", "exercise": "bodyweight_squat",
            "set_id": 1, "rep_id": 1, "phase": "none", "form_label": "unlabeled",
        })
        state.add({
            "annotation_id": "A00005", "segment_id": "V0001_SEG0005",
            "annotation_type": "phase", "start_frame": 22, "end_frame": 30,
            "activity_state": "active", "exercise": "bodyweight_squat",
            "set_id": 1, "rep_id": 1, "phase": "hold", "form_label": "unlabeled",
        })
        state.add({
            "annotation_id": "A00006", "segment_id": "V0001_SEG0006",
            "annotation_type": "form_interval", "start_frame": 30, "end_frame": 35,
            "activity_state": "active", "exercise": "bodyweight_squat",
            "phase": "none", "form_label": "poor",
            "issue_type": ["tracking_quality", "form_deviation"],
            "error_category": ["Motion blur", "Joint alignment"],
            "affected_joints": ["left_knee", "right_knee"],
        })
        annotation_path = root / "V0001_annotations.json"
        annotation_parquet = root / "V0001_annotations.parquet"
        state.save(annotation_path, annotation_parquet)
        reopened = AnnotationState.load(annotation_path)
        validate_annotations(reopened.to_document(), len(features))
        form_annotation = next(
            item for item in reopened.annotations if item.get("annotation_type") == "form_interval"
        )
        assert form_annotation["issue_type"] == ["tracking_quality", "form_deviation"]
        assert form_annotation["error_category"] == ["Motion blur", "Joint alignment"]
        assert [item["annotation_type"] for item in reopened.annotations] == [
            "general", "activity_state", "set", "rep", "phase", "form_interval"
        ]

        labeled = annotation_to_frame_targets(features, reopened.to_document(), boundary_radius_frames=1)
        assert set(labeled.loc[15:45, "exercise_label"]) == {"bodyweight_squat"}
        feature_columns = FeatureEngine(cfg).select_model_features(features)
        records = generate_window_records(
            labeled,
            feature_columns,
            window_seconds=2.0,
            stride_seconds=1.0,
            min_valid_pose_fraction=0.8,
            model_fps=30.0,
            target_specs={"activity_state": {"task": "sequence_classification", "frame_column": "activity_state_label"}},
        )
        assert records and records[0].X.shape[0] == 60
        assert digest(feature_path) == before

        split = grouped_split(pd.DataFrame({
            "session_id": ["S1", "S2", "S3"],
            "participant_id": ["P1", "P2", "P3"],
        }), cfg)
        assert split["group_key"] == "participant_id"
        print(json.dumps({
            "status": "passed",
            "frames": len(features),
            "featureCount": len(feature_columns),
            "angleCountsBySpace": {space: len(angle_family(features.columns, prefix))
                                   for space, prefix in ANGLE_PREFIXES.items()},
            "windowCount": len(records),
            "annotationCount": len(reopened.annotations),
            "activityGapAllowed": True,
            "formOverlayCount": sum(item.get("annotation_type") == "form_interval" for item in reopened.annotations),
            "featureParquetUnchangedAfterAnnotation": True,
            "temporaryRoot": str(root),
        }, indent=2))


if __name__ == "__main__":
    main()
