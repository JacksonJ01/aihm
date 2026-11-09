import json

import pandas as pd
import pytest

from aihumo.annotations import AnnotationState
from aihumo.dataset_builder import build_dataset_experiment
from aihumo.storage import save_json_atomic
from tests.test_features import make_frame_data


@pytest.mark.parametrize("issue", [None, "wrong_camera", "duplicate_features"])
def test_dataset_build_pairs_files_by_recording_identity(tmp_path, issue, detail):
    identifiers = {"session_id": "001", "video_id": "007", "participant_id": "011", "camera_id": "003"}
    frames = make_frame_data(13).assign(**identifiers)
    features_path = tmp_path / "features.parquet"
    frames.to_parquet(features_path)
    features_before = features_path.read_bytes()
    annotation_path = tmp_path / "annotation.json"
    annotation_ids = {**identifiers, "camera_id": "004"} if issue == "wrong_camera" else identifiers
    state = AnnotationState.new(annotation_ids)
    state.add({"annotation_id": "A1", "segment_id": "SEG1", "annotation_type": "activity_state",
               "activity_state": "active", "start_frame": 0, "end_frame": 12})
    state.status = "completed"
    save_json_atomic(state.to_document(), annotation_path)
    row = {**identifiers, "features_path": features_path.name, "annotation_json": annotation_path.name}
    manifest_path = tmp_path / "videos.csv"
    pd.DataFrame([row] * (2 if issue == "duplicate_features" else 1)).to_csv(manifest_path, index=False)
    cfg = {
        "windows": {"seconds": .2, "stride_seconds": .1, "model_fps": 30},
        "dataset": {"targets": {"activity_state": {"task": "sequence_classification"}}},
    }
    options = dict(root=tmp_path, manifest_path=manifest_path, cfg=cfg)
    if issue is None:
        output = build_dataset_experiment(**options)
        manifest = json.loads((output / "dataset_manifest.json").read_text(encoding="utf-8"))
        assert manifest["split_strategy"]["train"] == ["011"]
        assert manifest["split_summaries"]["train"]["samples"] == 3
        detail(observed="Three windows exported and leading zeros in the participant ID were preserved.")
    else:
        message = "disagree on camera_id" if issue == "wrong_camera" else "repeats the same feature Parquet"
        with pytest.raises(ValueError, match=message) as failure:
            build_dataset_experiment(**options)
        assert not (tmp_path / "data" / "datasets").exists()
        detail(observed=str(failure.value))
    assert features_path.read_bytes() == features_before
