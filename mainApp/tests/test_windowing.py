import numpy as np
import pandas as pd

from aihumo.windowing import generate_window_records


def test_windows_are_fixed_shape_at_canonical_model_fps():
    source_fps = 60.0
    n = 600
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
        "feature_a": np.sin(t),
    })
    records = generate_window_records(
        df,
        ["feature_a"],
        window_seconds=5.0,
        stride_seconds=1.0,
        model_fps=30.0,
    )
    assert records
    assert all(record.X.shape == (150, 1) for record in records)
    assert records[0].metadata["source_fps"] == source_fps
    assert records[0].metadata["model_fps"] == 30.0
