import numpy as np

from aihumo.features import FeatureEngine
from tests.test_features import make_frame_data


def test_anatomical_centers_and_baseline_normalization():
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
    result = FeatureEngine(cfg).build(df)
    assert {"hip_center_x", "shoulder_center_x", "torso_center_x", "knee_center_x", "ankle_center_x"}.issubset(result.dataframe.columns)
    assert "n11_x" in result.dataframe
    # Shoulder midpoint is x=.5 and torso midpoint is x=.5 in this synthetic frame.
    assert np.isclose(result.dataframe["torso_center_x"].iloc[0], 1.425)


def test_acceleration_is_derivative_of_velocity():
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
    result = FeatureEngine(cfg).build(df)
    # Finite-difference acceleration for x=t^2 should approach 2.
    values = result.dataframe["lm0_acceleration_magnitude"].to_numpy()
    assert np.isnan(values[:2]).all()
    assert np.isfinite(values[2:]).all()
    assert np.allclose(values[2:], 2.0, atol=1e-6)
