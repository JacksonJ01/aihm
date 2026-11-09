import numpy as np
import pandas as pd
import pytest

from aihumo.windowing import generate_window_records


@pytest.mark.parametrize("source_fps", [15.0, 24.0, 30.0, 60.0])
def test_windows_are_fixed_shape_at_canonical_model_fps(source_fps, detail):
    n = int(10 * source_fps)
    t = np.arange(n) / source_fps
    df = pd.DataFrame({
        "session_id": ["S1"] * n,
        "video_id": ["V1"] * n,
        "participant_id": ["P1"] * n,
        "camera_id": ["C1"] * n,
        "frame_id": np.arange(n),
        "timestamp_s": t,
        "fps": source_fps,
        "pose_present": [1] * n,
        "feature_a": 1 + t,
    })
    detail(input=f"{n} frames at {source_fps:g} FPS; 1 linear feature; 5 s windows with 1 s stride",
           expected="Each 30 FPS window has shape (150, 1) and keeps both FPS values")
    records = generate_window_records(
        df,
        ["feature_a"],
        window_seconds=5.0,
        stride_seconds=1.0,
        model_fps=30.0,
    )
    detail(observed=f"{len(records)} windows; shapes={sorted({record.X.shape for record in records})}")
    if records:
        detail(fps=f"source={records[0].metadata['source_fps']}; model={records[0].metadata['model_fps']}")
    assert records
    assert all(record.X.shape == (150, 1) for record in records)
    assert records[0].metadata["source_fps"] == source_fps
    assert records[0].metadata["model_fps"] == 30.0
    np.testing.assert_allclose(records[0].X[:, 0], 1 + np.arange(150) / 30)


def test_window_resampling_preserves_gaps_and_counts_only_known_targets(detail):
    times = [0.0, 0.1, 0.2, 0.3, 0.8, 0.9, 1.0]
    frames = pd.DataFrame({
        "session_id": "S1", "video_id": "V1", "camera_id": "C1",
        "frame_id": range(len(times)), "timestamp_s": times, "fps": 10,
        "pose_present": [1, 1, 0, 1, 1, 1, 1],
        "joint_a": [5, 6, 7, 8, 13, 14, 15],
        "joint_b": [8, np.nan, 8, 8, 8, 8, 8],
        "exercise_label": ["curl", None, None, "curl", None, None, None],
        "score_label": [2, np.inf, np.nan, 4, -np.inf, np.nan, np.nan],
    })
    records = generate_window_records(
        frames, ["joint_a", "joint_b"], window_seconds=1, stride_seconds=1,
        model_fps=20, min_valid_pose_fraction=.8,
        target_specs={"exercise": {"task": "classification"}, "score": {"task": "regression"}},
    )
    record, = records
    np.testing.assert_allclose(record.X[[0, 1, 2, 3, 4, 5, 6, 10, 16, 17], 0],
                               [5, 5.5, 6, 0, 0, 0, 8, 0, 13, 13.5])
    np.testing.assert_allclose(record.X[:4, 1], [8, 0, 0, 0])
    assert record.X.dtype == np.float32 and record.targets["score"] == 3
    assert record.targets["_coverage"] == {"exercise": 2 / 7, "score": 2 / 7}
    assert record.targets["_consistency"]["exercise"] == 1
    detail(input="Two joints with occlusion, a half-second frame gap, and missing or infinite labels.",
           observed="Finite adjacent observations interpolate. Gaps zero-fill and only 2/7 labels count as known.")
