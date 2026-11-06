import numpy as np
import pandas as pd

from aihumo.features import FeatureEngine


def make_frame_data(n=4):
    rows = []
    for frame in range(n):
        row = {"session_id": "S1", "video_id": "V1", "participant_id": "P1", "camera_id": "C1", "frame_id": frame, "timestamp_s": frame / 30.0, "fps": 30.0, "pose_present": 1}
        for i in range(33):
            row[f"lm{i}_x"] = 0.1 * i + frame * 0.01
            row[f"lm{i}_y"] = 0.2 * i
            row[f"lm{i}_z"] = 0.01 * i
            row[f"lm{i}_visibility"] = 1.0
            row[f"lm{i}_presence"] = 1.0
            row[f"world{i}_x"] = row[f"lm{i}_x"]
            row[f"world{i}_y"] = row[f"lm{i}_y"]
            row[f"world{i}_z"] = row[f"lm{i}_z"]
        # Make shoulders distinct and stable.
        row["lm11_x"] = 0.0
        row["lm12_x"] = 1.0
        row["lm11_y"] = row["lm12_y"] = 0.0
        row["lm11_z"] = row["lm12_z"] = 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def test_feature_engine_single_pass_result():
    cfg = {
        "features": {"use_raw_xyz": True, "use_world_xyz": True, "normalize_landmarks": True, "normalization_center": "shoulders", "normalization_scale": "shoulder_width", "use_angles": True, "use_distances": True, "distance_space": "normalized", "use_velocity": True, "use_acceleration": True},
        "angles": {"targets": {"left_elbow": [11, 13, 15]}},
        "distances": {"targets": {"shoulders": [11, 12]}},
    }
    result = FeatureEngine(cfg).build(make_frame_data())
    assert len(result.dataframe) == 4
    assert result.dataframe["n0_vx"].isna().iloc[0]
    assert result.dataframe["n0_ax"].isna().iloc[0]
    assert "angle_left_elbow" in result.dataframe
    assert "distance_shoulders" in result.dataframe
    assert len(result.feature_columns) > 0
