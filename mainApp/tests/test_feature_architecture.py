from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aihumo.config import load_config
from aihumo.features import FeatureEngine
from aihumo.geometry import angle_degrees
from tests.test_features import make_frame_data


def test_anatomical_centers_and_baseline_normalization(detail):
    cfg = {
        "features": {
            "use_raw_xyz": False,
            "use_world_xyz": False,
            "use_normalized_xyz": True,
            "normalize_landmarks": True,
            "anatomical_centers": {"enabled": True, "head": False},
            "body_axes": {"enabled": True},
            "normalization": {
                "enabled": True,
                "representations": {"torso_combined_width": True},
                "baseline_alias_n": True,
            },
            "model_input_spaces": ["torso_combined_width"],
            "temporal": {"spaces": ["torso_combined_width"]},
            "use_angles": False,
            "use_distances": False,
            "use_velocity": False,
            "use_acceleration": False,
        },
    }
    df = make_frame_data()
    detail(input="4 frames; normalization uses combined shoulder and hip width",
           expected="Named centers, normalized shoulder, and torso center x=1.425")
    result = FeatureEngine(cfg).build(df)
    detail(observed=f"frame 0 torso center x={result.dataframe['torso_center_x'].iloc[0]:.3f}; "
           f"normalized shoulder x={result.dataframe['n11_x'].iloc[0]:.3f}")
    assert {"hip_center_x", "shoulder_center_x", "torso_center_x", "knee_center_x", "ankle_center_x"}.issubset(result.dataframe.columns)
    assert "n11_x" in result.dataframe
    assert np.isclose(result.dataframe["torso_center_x"].iloc[0], 1.425)


def test_named_anatomical_points_and_midpoint_angles(detail):
    cfg = {
        "features": {
            "use_raw_xyz": False,
            "use_world_xyz": False,
            "use_normalized_xyz": False,
            "normalize_landmarks": False,
            "anatomical_centers": {"enabled": True, "head": False},
            "include_anatomical_centers": True,
            "include_anatomical_points": True,
            "body_axes": {"enabled": False},
            "use_angles": True,
            "use_distances": False,
            "use_velocity": False,
            "use_acceleration": False,
        },
        "angles": {
            "targets": {
                "torso_nose_shoulder_hip": [0, 11, 23],
            },
            "midpoint_targets": {
                "shoulder_midpoint_hip_midpoint_knee_midpoint": [
                    "shoulder_midpoint", "hip_midpoint", "knee_midpoint"
                ],
            },
        },
    }
    detail(input="2 frames with nose, shoulders, hips, knees, and ankles",
           expected="15 named XYZ columns, 2 midpoint-based angle columns, and manifest definitions")
    result = FeatureEngine(cfg).build(make_frame_data(n=2))
    expected_points = {
        f"{point}_{axis}"
        for point in ("nose", "shoulder_midpoint", "hip_midpoint", "knee_midpoint", "ankle_midpoint")
        for axis in ("x", "y", "z")
    }
    detail(observed=f"{len(expected_points.intersection(result.dataframe.columns))} named XYZ columns; "
           f"{sum(column.startswith('angle_') for column in result.dataframe.columns)} angle columns; "
           f"midpoint definitions present={'midpoint_angle_definitions' in result.feature_manifest}")
    assert expected_points.issubset(result.dataframe.columns)
    assert "angle_torso_nose_shoulder_hip" in result.dataframe.columns
    assert "angle_shoulder_midpoint_hip_midpoint_knee_midpoint" in result.dataframe.columns
    assert "midpoint_angle_definitions" in result.feature_manifest


def test_projected_angles_use_the_correct_side_and_pixel_geometry(detail):
    cfg = load_config(Path(__file__).resolve().parents[1] / "configs" / "config.json")
    engine = FeatureEngine(cfg)
    frame_size = (1280, 720)
    pixels = np.random.default_rng(7).uniform(30, 680, size=(2, 33, 2))
    normalized = pixels / frame_size
    frames = pd.DataFrame({
        f"lm{joint}_{axis}": normalized[:, joint, index]
        for joint in range(33) for index, axis in enumerate("xy")
    })
    frames.loc[1, "lm16_x"] = np.nan
    frames["timestamp_s"] = [0.0, 0.04]
    world = np.random.default_rng(17).normal(size=(2, 33, 3))
    frames = pd.concat([frames, pd.DataFrame({
        f"world{joint}_{axis}": world[:, joint, index]
        for joint in range(33) for index, axis in enumerate("xyz")
    })], axis=1)
    actual = engine.projected_angles(frames, frame_size)
    result = engine.build(frames, frame_size=frame_size)
    stored = result.dataframe
    trios = {
        "left_shoulder": (13, 11, 23), "right_shoulder": (14, 12, 24),
        "left_elbow": (11, 13, 15), "right_elbow": (12, 14, 16),
        "left_wrist": (13, 15, 19), "right_wrist": (14, 16, 20),
        "left_hip": (11, 23, 25), "right_hip": (12, 24, 26),
        "left_knee": (23, 25, 27), "right_knee": (24, 26, 28),
        "left_ankle": (25, 27, 31), "right_ankle": (26, 28, 32),
    }
    for name, ids in trios.items():
        assert actual[f"angle_{name}"][0] == pytest.approx(angle_degrees(*pixels[0, list(ids)]))
        assert stored[f"angle_3d_{name}"][0] == pytest.approx(angle_degrees(*world[0, list(ids)]))
    shoulder, hip, knee, ankle = (
        pixels[0, [left, right]].mean(axis=0) for left, right in ((11, 12), (23, 24), (25, 26), (27, 28))
    )
    assert actual["angle_torso_nose_shoulder_hip"][0] == pytest.approx(angle_degrees(pixels[0, 0], shoulder, hip))
    assert actual["angle_shoulder_midpoint_hip_midpoint_knee_midpoint"][0] == pytest.approx(
        angle_degrees(shoulder, hip, knee)
    )
    assert actual["angle_torso_vertical"][0] == pytest.approx(
        np.degrees(np.arctan2(*np.abs(shoulder - hip)))
    )
    assert engine._derived_centers(pixels)["ankle_center"][0] == pytest.approx(ankle)
    assert len(actual) == 15 and np.isnan(actual["angle_right_elbow"][1])
    assert np.isfinite(actual["angle_left_elbow"][1])
    for column, values in actual.items():
        np.testing.assert_allclose(stored[column.replace("angle_", "angle_2d_", 1)], values)
    shoulder_3d, hip_3d, knee_3d = (world[0, [a, b]].mean(axis=0) for a, b in ((11, 12), (23, 24), (25, 26)))
    assert stored["angle_3d_torso_nose_shoulder_hip"][0] == pytest.approx(
        angle_degrees(world[0, 0], shoulder_3d, hip_3d)
    )
    assert stored["angle_3d_shoulder_midpoint_hip_midpoint_knee_midpoint"][0] == pytest.approx(
        angle_degrees(shoulder_3d, hip_3d, knee_3d)
    )
    torso = shoulder_3d - hip_3d
    assert stored["angle_3d_torso_vertical"][0] == pytest.approx(
        np.degrees(np.arctan2(np.linalg.norm(torso[[0, 2]]), abs(torso[1])))
    )
    assert np.isfinite(stored["angle_3d_right_elbow"][1])
    assert set(result.feature_manifest["angle_feature_spaces"]) == {"legacy", "2d", "3d"}
    assert "angle_right_elbow" in result.feature_columns and "angle_2d_right_elbow" not in result.feature_columns
    cfg["features"]["model_angle_spaces"] = ["2d", "3d"]
    selected = engine.select_model_features(stored)
    assert "angle_2d_right_elbow" in selected and "angle_3d_right_elbow" in selected
    assert "angle_right_elbow" not in selected
    with pytest.raises(ValueError, match="requested 2d angle family is incomplete"):
        engine.select_model_features(stored.drop(columns="angle_2d_right_elbow"))
    detail(observed="All 15 angles match independent pixel XY and world XYZ geometry. An image gap stays separate from world data.")


def test_acceleration_is_derivative_of_velocity(detail):
    df = make_frame_data(n=5)
    # Force a quadratic trajectory for landmark 0: x=t^2.
    for frame in range(5):
        t = frame / 30.0
        df.loc[frame, "lm0_x"] = t * t
    cfg = {
        "features": {
            "use_raw_xyz": False,
            "use_world_xyz": False,
            "normalize_landmarks": False,
            "use_angles": False,
            "use_distances": False,
            "use_velocity": True,
            "use_acceleration": True,
            "temporal": {"spaces": ["raw"]},
        }
    }
    detail(input="5 frames at 30 FPS; landmark 0 follows x = t^2",
           expected="First 2 samples missing, remaining acceleration magnitudes near 2.0")
    result = FeatureEngine(cfg).build(df)
    # Finite-difference acceleration for x=t^2 should approach 2.
    values = result.dataframe["lm0_acceleration_magnitude"].to_numpy()
    detail(observed=np.array2string(values, precision=6))
    assert np.isnan(values[:2]).all()
    assert np.isfinite(values[2:]).all()
    assert np.allclose(values[2:], 2.0, atol=1e-6)
