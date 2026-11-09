import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aihumo.config import load_config
from aihumo.features import CROSS_MEAN_SOURCE, FeatureEngine, review_schema_metadata, with_viewer_features
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
    assert "review_cross_mean_angle_left_elbow" in result.feature_manifest["feature_groups"]["viewer"]
    distance = "review_world_distance_left_shoulder_to_wrist"
    assert stored[distance][0] == pytest.approx(np.linalg.norm(world[0, 11] - world[0, 15]))
    assert distance not in result.feature_columns
    rate = stored["review_world_distance_rate_left_shoulder_to_wrist"]
    assert np.isnan(rate[0])
    assert rate[1] == pytest.approx((stored[distance][1] - stored[distance][0]) / 0.04)
    assert stored["review_torso2d_distance_elbow_to_elbow"][0] == pytest.approx(
        np.linalg.norm(pixels[0, 13] - pixels[0, 14]) / np.linalg.norm(shoulder - hip)
    )
    np.testing.assert_allclose(stored["angle_torso2d_left_elbow"], stored["angle_2d_left_elbow"])
    assert not any(column.startswith("viewer_") for column in result.feature_columns)
    assert "angle_right_elbow" in result.feature_columns and "angle_2d_right_elbow" not in result.feature_columns
    cfg["features"]["model_angle_spaces"] = ["2d", "3d"]
    selected = engine.select_model_features(stored)
    assert "angle_2d_right_elbow" in selected and "angle_3d_right_elbow" in selected
    assert "angle_right_elbow" not in selected
    with pytest.raises(ValueError, match="requested 2d angle family is incomplete"):
        engine.select_model_features(stored.drop(columns="angle_2d_right_elbow"))
    detail(observed="All 15 angles match independent pixel XY and world XYZ geometry. An image gap stays separate from world data.")


def test_mean_motion_aligns_sources_and_uses_native_time_without_filling_gaps():
    engine = FeatureEngine(load_config(Path(__file__).resolve().parents[1] / "configs" / "config.json"))
    frames = pd.DataFrame({
        "frame_id": range(5), "timestamp_s": [0, .1, .3, .5, .8],
        "lm13_x": [.34, .38, .46, .50, .54], "lm13_y": .4,
        "world13_x": [.05, .2, .3, np.nan, .4], "world13_y": -.25,
        "lm11_x": .2, "lm12_x": .4, "lm11_y": .2, "lm12_y": .2,
        "lm23_x": .2, "lm24_x": .4, "lm23_y": .6, "lm24_y": .6,
        "world11_x": -.1, "world12_x": .1, "world11_y": -.5, "world12_y": -.5,
        "world23_x": -.1, "world24_x": .1, "world23_y": 0, "world24_y": 0,
    })
    prepared = engine.prepare_review_features(frames, (160, 80))
    prefix = "review_cross_mean_lm13_"
    expected_x = np.array([.4 / 3, 1 / 3, .6, np.nan, 2.6 / 3])
    expected_vx = np.diff(expected_x, prepend=np.nan) / np.diff(frames["timestamp_s"], prepend=np.nan)
    expected_ax = np.diff(expected_vx, prepend=np.nan) / np.diff(frames["timestamp_s"], prepend=np.nan)
    np.testing.assert_allclose(prepared[f"{prefix}x"], expected_x)
    np.testing.assert_allclose(prepared[f"{prefix}y"], [-.5, -.5, -.5, np.nan, -.5])
    np.testing.assert_allclose(prepared[f"{prefix}vx"], expected_vx)
    np.testing.assert_allclose(prepared[f"{prefix}ax"], expected_ax)
    np.testing.assert_allclose(prepared[f"{prefix}speed"], np.abs(expected_vx))
    metadata = json.loads(review_schema_metadata(prepared.columns)[b"aihumo.review_schema"])
    assert metadata["columns"][f"{prefix}ax"] == {
        "source": CROSS_MEAN_SOURCE, "point": "lm13", "measurement": "linear acceleration",
        "axis": "ax", "unit": "torso lengths/s²",
    }


def test_distance_preparation_reuses_saved_rates_and_respects_timing_gaps():
    frames = pd.DataFrame({
        "frame_id": [0, 1, 2, 3, 4, 6, 7, 8],
        "timestamp_s": [0, .25, .5, 1, 1.5, 2, 2.5, 3],
        "target_track_id": [1, 1, 1, 2, 2, 2, 2, 2],
        "review_world_distance_wrist_to_wrist": [1, 2, 4, 6, 7, 8, 9, 12],
        "review_legacy_distance_knee_to_knee": [1] * 8,
        "review_legacy_distance_rate_knee_to_knee": [np.nan, 2, 3, np.nan, 4, np.nan, 2, 3],
        "review_cross_mean_lm15_x": [1, 2, 4, 6, 7, 8, 9, 12],
        "review_cross_mean_lm16_x": [0] * 8,
        "review_cross_mean_lm15_y": [0] * 8,
        "review_cross_mean_lm16_y": [0] * 8,
    })
    added = FeatureEngine.prepare_review_distances(frames)
    np.testing.assert_allclose(added["review_world_distance_rate_wrist_to_wrist"],
                               [np.nan, 4, 8, np.nan, 2, np.nan, 2, 6])
    np.testing.assert_allclose(added["review_world_distance_acceleration_wrist_to_wrist"],
                               [np.nan, np.nan, 16, np.nan, np.nan, np.nan, np.nan, 8])
    np.testing.assert_allclose(added["review_legacy_distance_acceleration_knee_to_knee"],
                               [np.nan, np.nan, 4, np.nan, np.nan, np.nan, np.nan, 2])
    np.testing.assert_allclose(added["review_cross_mean_distance_wrist_to_wrist"],
                               frames["review_world_distance_wrist_to_wrist"])
    assert not set(added).intersection(frames)
    assert FeatureEngine.prepare_review_distances(pd.concat([frames, added], axis=1)).empty


def test_viewer_readings_use_native_time_and_keep_gaps():
    frames = pd.DataFrame({
        "frame_id": [0, 1, 2, 4, 5], "timestamp_s": [0.0, 0.1, 0.3, 0.5, 0.8],
        "angle_right_hip": [5, 6, 10, 22, 25],
        "angle_2d_right_hip": [15, 17, 25, 30, 35],
        "angle_3d_right_hip": [25, 31, 39, np.nan, 40],
        "world24_x": [0.0, 0.1, 0.5, 0.8, 1.1], "world24_y": 0.0, "world24_z": 0.0,
    })
    result = with_viewer_features(frames)
    np.testing.assert_allclose(result["viewer_mean_angle_right_hip"], [15, 18, 74 / 3, np.nan, 100 / 3])
    np.testing.assert_allclose(result["viewer_omega_angle_right_hip"], [np.nan, 10, 20, np.nan, 10])
    np.testing.assert_allclose(result["viewer_alpha_angle_right_hip"], [np.nan, np.nan, 50, np.nan, np.nan])
    np.testing.assert_allclose(result["viewer_world_angle_right_hip_speed"], [np.nan, 1, 2, np.nan, 1])
    assert with_viewer_features(result) is result
    pd.testing.assert_frame_equal(result[frames.columns], frames)


def test_motion_uses_each_joints_own_validity_and_never_crosses_tracking_breaks(detail):
    frames = make_frame_data(9)
    times = np.array([0, .04, .11, .15, .19, .23, .27, .31, .35])
    frames["timestamp_s"] = times
    frames["lm0_x"] = 2 * times
    frames["lm16_x"] = 3 * times
    frames.loc[2, "lm16_z"] = np.nan
    frames["target_track_id"] = [1, 1, 1, 1, 2, 2, 2, 2, 2]
    frames.loc[6, "pose_present"] = 0
    cfg = {"features": {"use_distances": False, "normalize_landmarks": False,
                        "temporal": {"spaces": ["raw"]}}}
    result = FeatureEngine(cfg).build(frames).dataframe
    np.testing.assert_allclose(result["lm0_vx"], [np.nan, 2, 2, 2, np.nan, 2, np.nan, np.nan, 2])
    np.testing.assert_allclose(result["lm16_vx"], [np.nan, 3, np.nan, np.nan, np.nan, 3, np.nan, np.nan, 3])
    np.testing.assert_allclose(result["lm0_ax"], [np.nan, np.nan, 0, 0, np.nan, np.nan, np.nan, np.nan, np.nan], atol=1e-12)
    detail(input="Irregular timing, one missing wrist coordinate, a track change, and a frame without pose.",
           observed="The unaffected landmark keeps its 2 units/s velocity. Tracking breaks invalidate both joints.")


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
