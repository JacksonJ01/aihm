import json

import numpy as np
import pandas as pd

from aihumo.annotations import (
    AnnotationState,
    _canonical_annotation,
    annotation_to_dataframe,
    annotation_to_frame_targets,
    build_rep_summary,
    validate_annotations,
)


def test_issue_fields_normalize_legacy_scalars_and_preserve_multi_select():
    legacy = _canonical_annotation({
        "annotation_type": "form_interval",
        "issue_type": "tracking_quality",
        "error_category": "Motion blur",
        "affected_joints": "left_knee,right_knee",
    })
    assert legacy["issue_type"] == ["tracking_quality"]
    assert legacy["error_category"] == ["Motion blur"]
    assert legacy["affected_joints"] == ["left_knee", "right_knee"]

    multiple = _canonical_annotation({
        "annotation_type": "form_interval",
        "issue_type": ["tracking_quality", "form_deviation"],
        "error_category": ["Motion blur", "Joint alignment"],
        "affected_joints": ["left_knee", "right_knee"],
    })
    assert multiple["issue_type"] == ["tracking_quality", "form_deviation"]
    assert multiple["error_category"] == ["Motion blur", "Joint alignment"]
    parquet_row = annotation_to_dataframe({"annotations": [multiple]}).iloc[0]
    assert parquet_row["issue_type"] == "tracking_quality,form_deviation"
    assert parquet_row["error_category"] == "Motion blur,Joint alignment"


def test_annotation_state_round_trip_json(tmp_path):
    path = tmp_path / "annotations.json"
    state = AnnotationState.new({"session_id": "S001", "video_id": "V001"})
    annotation = {
        "annotation_id": state.next_annotation_id(),
        "segment_id": state.next_segment_id(),
        "start_frame": 10,
        "end_frame": 20,
        "start_time_s": 1.0,
        "end_time_s": 2.0,
        "duration_s": 1.0,
        "annotation_type": "rep",
        "activity_state": "active",
        "exercise": "squat",
        "phase": "none",
        "rep_id": 1,
        "set_id": 1,
    }
    state.add(annotation)
    from aihumo.storage import save_json_atomic
    save_json_atomic(state.to_document(), path)

    restored = AnnotationState.load(path)
    assert len(restored.annotations) == 1
    assert restored.last_completed_frame == 20
    assert restored.next_annotation_id() == "A00002"
    assert restored.next_segment_id() == "V001_SEG0002"
    assert json.loads(path.read_text())["annotation_session"]["progress"]["last_annotation_id"] == "A00001"


def test_activity_state_segments_are_non_overlapping_but_reps_can_overlap():
    document = {
        "schema_version": "1.2",
        "annotations": [
            {"annotation_id": "A00001", "segment_id": "V001_SEG0001", "annotation_type": "activity_state", "start_frame": 0, "end_frame": 99, "activity_state": "active", "phase": "none", "form_label": "unlabeled"},
            {"annotation_id": "A00002", "segment_id": "V001_SEG0002", "annotation_type": "rep", "start_frame": 20, "end_frame": 50, "activity_state": "active", "exercise": "squat", "phase": "none", "set_id": 1, "rep_id": 1, "form_label": "unlabeled"},
            {"annotation_id": "A00003", "segment_id": "V001_SEG0003", "annotation_type": "phase", "start_frame": 25, "end_frame": 35, "activity_state": "active", "exercise": "squat", "phase": "concentric", "set_id": 1, "rep_id": 1, "form_label": "unlabeled"},
        ],
    }
    validate_annotations(document, 100)


def test_setup_gaps_and_form_intervals_are_valid_sibling_layers():
    document = {
        "annotations": [
            {"annotation_id": "A00001", "segment_id": "V001_SEG0001", "annotation_type": "general", "start_frame": 0, "end_frame": 9, "activity_state": "idle", "phase": "none"},
            # Frames 10–12 are intentionally unclassified setup/gap frames.
            {"annotation_id": "A00002", "segment_id": "V001_SEG0002", "annotation_type": "activity_state", "start_frame": 13, "end_frame": 99, "activity_state": "active", "phase": "none"},
            {"annotation_id": "A00003", "segment_id": "V001_SEG0003", "annotation_type": "rep", "start_frame": 20, "end_frame": 60, "activity_state": "active", "exercise": "bodyweight_squat", "phase": "none", "set_id": 1, "rep_id": 1},
            {"annotation_id": "A00004", "segment_id": "V001_SEG0004", "annotation_type": "form_interval", "start_frame": 35, "end_frame": 40, "activity_state": "active", "exercise": "bodyweight_squat", "phase": "none", "issue_type": "tracking_quality", "error_category": "Motion blur", "affected_joints": ["left_knee", "right_knee"]},
        ],
    }
    validate_annotations(document, 100)


def test_annotation_rows_follow_activity_set_rep_phase_hierarchy():
    state = AnnotationState.new({"video_id": "V001"})
    # Add them out of order to verify the persisted timeline is reorganized.
    state.add({"annotation_id": "A00004", "segment_id": "V001_SEG0004", "annotation_type": "rep", "start_frame": 20, "end_frame": 50, "activity_state": "active", "exercise": "bodyweight_squat", "set_id": 1, "rep_id": 1, "phase": "none"})
    state.add({"annotation_id": "A00002", "segment_id": "V001_SEG0002", "annotation_type": "activity_state", "start_frame": 10, "end_frame": 90, "activity_state": "active", "phase": "none"})
    state.add({"annotation_id": "A00005", "segment_id": "V001_SEG0005", "annotation_type": "phase", "start_frame": 25, "end_frame": 30, "activity_state": "active", "set_id": 1, "rep_id": 1, "phase": "hold"})
    state.add({"annotation_id": "A00003", "segment_id": "V001_SEG0003", "annotation_type": "set", "start_frame": 10, "end_frame": 90, "activity_state": "active", "exercise": "bodyweight_squat", "set_id": 1, "phase": "none"})
    assert [item["annotation_type"] for item in state.annotations] == ["activity_state", "set", "rep", "phase"]


def test_legacy_top_bottom_phase_values_migrate_to_hold():
    state = AnnotationState.new({"video_id": "V001"})
    state.add({"annotation_id": "A00001", "segment_id": "V001_SEG0001", "annotation_type": "activity_state", "start_frame": 0, "end_frame": 9, "activity_state": "active", "phase": "none"})
    state.add({"annotation_id": "A00002", "segment_id": "V001_SEG0002", "annotation_type": "rep", "start_frame": 0, "end_frame": 9, "activity_state": "active", "set_id": 1, "rep_id": 1, "phase": "none"})
    state.add({"annotation_id": "A00003", "segment_id": "V001_SEG0003", "annotation_type": "phase", "start_frame": 0, "end_frame": 0, "activity_state": "active", "set_id": 1, "rep_id": 1, "phase": "bottom"})
    assert state.annotations[-1]["phase"] == "hold"


def test_rep_boundary_and_summary_are_derived_from_annotations():
    document = {
        "annotations": [
            {"annotation_id": "A00001", "segment_id": "V001_SEG0001", "annotation_type": "rep", "start_frame": 10, "end_frame": 20, "activity_state": "active", "exercise": "squat", "phase": "none", "set_id": 1, "rep_id": 1, "form_label": "good", "form_score": 0.9},
            {"annotation_id": "A00002", "segment_id": "V001_SEG0002", "annotation_type": "phase", "start_frame": 12, "end_frame": 15, "activity_state": "active", "exercise": "squat", "phase": "hold", "set_id": 1, "rep_id": 1, "form_label": "unlabeled"},
        ]
    }
    df = pd.DataFrame({
        "session_id": ["S1"] * 30,
        "video_id": ["V1"] * 30,
        "camera_id": ["C1"] * 30,
        "frame_id": range(30),
        "timestamp_s": np.arange(30) / 30.0,
        "lm0_x": [0.0] * 30,
    })
    labeled = annotation_to_frame_targets(df, document, boundary_radius_frames=2)
    assert labeled.loc[8:12, "rep_boundary_label"].sum() == 5
    assert labeled.loc[18:22, "rep_boundary_label"].sum() == 5
    summary = build_rep_summary(document)
    assert summary[0]["rep_id"] == 1
    assert summary[0]["phases"] == ["hold"]
    assert summary[0]["form_score"] == 0.9


def test_rep_and_phase_must_be_inside_active_hierarchy():
    base = {
        "annotation_id": "A00001",
        "segment_id": "V001_SEG0001",
        "annotation_type": "activity_state",
        "start_frame": 0,
        "end_frame": 49,
        "activity_state": "active",
        "phase": "none",
        "form_label": "unlabeled",
    }
    rep = {
        "annotation_id": "A00002",
        "segment_id": "V001_SEG0002",
        "annotation_type": "rep",
        "start_frame": 10,
        "end_frame": 20,
        "activity_state": "active",
        "exercise": "squat",
        "phase": "none",
        "set_id": 1,
        "rep_id": 1,
        "form_label": "unlabeled",
    }
    phase = {
        "annotation_id": "A00003",
        "segment_id": "V001_SEG0003",
        "annotation_type": "phase",
        "start_frame": 12,
        "end_frame": 15,
        "activity_state": "active",
        "exercise": "squat",
        "phase": "hold",
        "set_id": 1,
        "rep_id": 1,
        "form_label": "unlabeled",
    }
    validate_annotations({"annotations": [base, rep, phase]}, 50)


def test_rep_outside_active_segment_is_rejected():
    document = {
        "annotations": [
            {
                "annotation_id": "A00001", "segment_id": "V001_SEG0001",
                "annotation_type": "activity_state", "start_frame": 0, "end_frame": 9,
                "activity_state": "active", "phase": "none", "form_label": "unlabeled"
            },
            {
                "annotation_id": "A00002", "segment_id": "V001_SEG0002",
                "annotation_type": "rep", "start_frame": 10, "end_frame": 20,
                "activity_state": "active", "exercise": "squat", "phase": "none",
                "set_id": 1, "rep_id": 1, "form_label": "unlabeled"
            },
        ]
    }
    import pytest
    with pytest.raises(ValueError, match="fully contained in an active"):
        validate_annotations(document, 21)


def test_phase_without_matching_rep_is_rejected():
    document = {
        "annotations": [
            {
                "annotation_id": "A00001", "segment_id": "V001_SEG0001",
                "annotation_type": "activity_state", "start_frame": 0, "end_frame": 49,
                "activity_state": "active", "phase": "none", "form_label": "unlabeled"
            },
            {
                "annotation_id": "A00002", "segment_id": "V001_SEG0002",
                "annotation_type": "phase", "start_frame": 10, "end_frame": 20,
                "activity_state": "active", "exercise": "squat", "phase": "hold",
                "set_id": 1, "rep_id": 1, "form_label": "unlabeled"
            },
        ]
    }
    import pytest
    with pytest.raises(ValueError, match="without a matching rep"):
        validate_annotations(document, 50)
