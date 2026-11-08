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


def describe_ranges(annotations):
    return ", ".join(
        f"{item['annotation_type']} [{item['start_frame']}-{item['end_frame']}]"
        for item in annotations
    )


def test_issue_fields_normalize_legacy_scalars_and_preserve_multi_select(detail):
    detail(input="Legacy scalar issue and comma-separated knees; current multi-select issue list",
           expected="Lists in annotations and comma-separated issues/categories in the export row")
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
    detail(observed=f"legacy joints={legacy['affected_joints']}; issues={parquet_row['issue_type']}; "
           f"categories={parquet_row['error_category']}")
    assert parquet_row["issue_type"] == "tracking_quality,form_deviation"
    assert parquet_row["error_category"] == "Motion blur,Joint alignment"


def test_camera_angle_is_activity_metadata_and_survives_tabular_export(detail):
    detail(input="Active interval [0-20] with camera angle 'Side'",
           expected="Side in both the canonical annotation and the tabular export")
    annotation = _canonical_annotation({
        "annotation_id": "A00001",
        "segment_id": "V001_SEG0001",
        "annotation_type": "activity_state",
        "start_frame": 0,
        "end_frame": 20,
        "activity_state": "active",
        "camera_angle": "Side",
    })
    assert annotation["camera_angle"] == "Side"
    exported = annotation_to_dataframe({"schema_version": "1.5", "annotations": [annotation]})
    detail(observed=f"canonical={annotation['camera_angle']}; export={exported.iloc[0]['camera_angle']}")
    assert exported.iloc[0]["camera_angle"] == "Side"


def test_annotation_state_round_trip_json(tmp_path, detail):
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
    detail(input="S001/V001; one squat rep [10-20]; save and reload temporary annotation JSON",
           expected="1 annotation, last frame 20, next IDs A00002 and V001_SEG0002")
    state.add(annotation)
    from aihumo.storage import save_json_atomic
    save_json_atomic(state.to_document(), path)

    restored = AnnotationState.load(path)
    detail(observed=f"{len(restored.annotations)} annotations; last frame={restored.last_completed_frame}; "
           f"next IDs={restored.next_annotation_id()}, {restored.next_segment_id()}")
    assert len(restored.annotations) == 1
    assert restored.last_completed_frame == 20
    assert restored.next_annotation_id() == "A00002"
    assert restored.next_segment_id() == "V001_SEG0002"
    assert json.loads(path.read_text())["annotation_session"]["progress"]["last_annotation_id"] == "A00001"


def test_active_interval_accepts_a_nested_rep_and_phase(detail):
    document = {
        "schema_version": "1.2",
        "annotations": [
            {"annotation_id": "A00001", "segment_id": "V001_SEG0001", "annotation_type": "activity_state", "start_frame": 0, "end_frame": 99, "activity_state": "active", "phase": "none", "form_label": "unlabeled"},
            {"annotation_id": "A00002", "segment_id": "V001_SEG0002", "annotation_type": "rep", "start_frame": 20, "end_frame": 50, "activity_state": "active", "exercise": "squat", "phase": "none", "set_id": 1, "rep_id": 1, "form_label": "unlabeled"},
            {"annotation_id": "A00003", "segment_id": "V001_SEG0003", "annotation_type": "phase", "start_frame": 25, "end_frame": 35, "activity_state": "active", "exercise": "squat", "phase": "concentric", "set_id": 1, "rep_id": 1, "form_label": "unlabeled"},
        ],
    }
    detail(input=f"100 frames; {describe_ranges(document['annotations'])}",
           expected="Validator accepts a rep and phase nested in an active range")
    validate_annotations(document, 100)
    detail(observed="Accepted")


def test_setup_gaps_and_form_intervals_are_valid_sibling_layers(detail):
    document = {
        "annotations": [
            {"annotation_id": "A00001", "segment_id": "V001_SEG0001", "annotation_type": "general", "start_frame": 0, "end_frame": 9, "activity_state": "idle", "phase": "none"},
            # Frames 10–12 are intentionally unclassified setup/gap frames.
            {"annotation_id": "A00002", "segment_id": "V001_SEG0002", "annotation_type": "activity_state", "start_frame": 13, "end_frame": 99, "activity_state": "active", "phase": "none"},
            {"annotation_id": "A00003", "segment_id": "V001_SEG0003", "annotation_type": "rep", "start_frame": 20, "end_frame": 60, "activity_state": "active", "exercise": "bodyweight_squat", "phase": "none", "set_id": 1, "rep_id": 1},
            {"annotation_id": "A00004", "segment_id": "V001_SEG0004", "annotation_type": "form_interval", "start_frame": 35, "end_frame": 40, "activity_state": "active", "exercise": "bodyweight_squat", "phase": "none", "issue_type": "tracking_quality", "error_category": "Motion blur", "affected_joints": ["left_knee", "right_knee"]},
        ],
    }
    detail(input=f"{describe_ranges(document['annotations'])}; unlabeled frames 10-12",
           expected="Validator accepts both the gap and the overlapping form interval")
    validate_annotations(document, 100)
    detail(observed="Accepted")


def test_annotation_rows_follow_activity_set_rep_phase_hierarchy(detail):
    detail(input="Insert rep, activity, phase, and set in that order",
           expected="Rows ordered activity -> set -> rep -> phase")
    state = AnnotationState.new({"video_id": "V001"})
    # Add them out of order to verify the persisted timeline is reorganized.
    state.add({"annotation_id": "A00004", "segment_id": "V001_SEG0004", "annotation_type": "rep", "start_frame": 20, "end_frame": 50, "activity_state": "active", "exercise": "bodyweight_squat", "set_id": 1, "rep_id": 1, "phase": "none"})
    state.add({"annotation_id": "A00002", "segment_id": "V001_SEG0002", "annotation_type": "activity_state", "start_frame": 10, "end_frame": 90, "activity_state": "active", "phase": "none"})
    state.add({"annotation_id": "A00005", "segment_id": "V001_SEG0005", "annotation_type": "phase", "start_frame": 25, "end_frame": 30, "activity_state": "active", "set_id": 1, "rep_id": 1, "phase": "hold"})
    state.add({"annotation_id": "A00003", "segment_id": "V001_SEG0003", "annotation_type": "set", "start_frame": 10, "end_frame": 90, "activity_state": "active", "exercise": "bodyweight_squat", "set_id": 1, "phase": "none"})
    order = [item["annotation_type"] for item in state.annotations]
    detail(observed=" -> ".join(order))
    assert order == ["activity_state", "set", "rep", "phase"]


def test_legacy_bottom_phase_migrates_to_hold(detail):
    detail(input="Legacy single-frame phase 'bottom' inside a rep", expected="Phase stored as 'hold'")
    state = AnnotationState.new({"video_id": "V001"})
    state.add({"annotation_id": "A00001", "segment_id": "V001_SEG0001", "annotation_type": "activity_state", "start_frame": 0, "end_frame": 9, "activity_state": "active", "phase": "none"})
    state.add({"annotation_id": "A00002", "segment_id": "V001_SEG0002", "annotation_type": "rep", "start_frame": 0, "end_frame": 9, "activity_state": "active", "set_id": 1, "rep_id": 1, "phase": "none"})
    state.add({"annotation_id": "A00003", "segment_id": "V001_SEG0003", "annotation_type": "phase", "start_frame": 0, "end_frame": 0, "activity_state": "active", "set_id": 1, "rep_id": 1, "phase": "bottom"})
    detail(observed=state.annotations[-1]["phase"])
    assert state.annotations[-1]["phase"] == "hold"


def test_rep_boundary_and_summary_are_derived_from_annotations(detail):
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
    detail(input=f"30 frames; {describe_ranges(document['annotations'])}; boundary radius=2 frames",
           expected="5 labels at each boundary; rep 1 summary includes hold and score 0.9")
    labeled = annotation_to_frame_targets(df, document, boundary_radius_frames=2)
    start_hits = labeled.loc[8:12, "rep_boundary_label"].sum()
    end_hits = labeled.loc[18:22, "rep_boundary_label"].sum()
    summary = build_rep_summary(document)
    detail(observed=f"start/end counts={start_hits}/{end_hits}; "
           f"rep={summary[0]['rep_id']}; phases={summary[0]['phases']}; score={summary[0]['form_score']}")
    assert start_hits == 5
    assert end_hits == 5
    assert summary[0]["rep_id"] == 1
    assert summary[0]["phases"] == ["hold"]
    assert summary[0]["form_score"] == 0.9


def test_rep_and_phase_must_be_inside_active_hierarchy(detail):
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
    detail(input=f"50 frames; {describe_ranges([base, rep, phase])}",
           expected="Validator accepts these nested bounds and matching IDs")
    validate_annotations({"annotations": [base, rep, phase]}, 50)
    detail(observed="Accepted")


def test_rep_outside_active_segment_is_rejected(detail):
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
    detail(input=describe_ranges(document["annotations"]),
           expected="Reject the rep because it falls outside the active range")
    import pytest
    with pytest.raises(ValueError, match="fully contained in an active") as error:
        validate_annotations(document, 21)
    detail(observed=str(error.value))


def test_phase_without_matching_rep_is_rejected(detail):
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
    detail(input=f"{describe_ranges(document['annotations'])}; phase references rep 1, which is absent",
           expected="Reject the phase because its rep is missing")
    import pytest
    with pytest.raises(ValueError, match="without a matching rep") as error:
        validate_annotations(document, 50)
    detail(observed=str(error.value))
