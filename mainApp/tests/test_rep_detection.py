import numpy as np
import pandas as pd

from aihumo.rep_detection import RepDetectionConfig, RepDetector


def test_sliding_window_rep_detection_estimates_period_and_deduplicates_extrema(detail):
    fps = 30.0
    n = 900
    timestamps = np.arange(n) / fps
    signal = 0.5 + 0.2 * np.sin(2 * np.pi * 0.5 * timestamps)
    df = pd.DataFrame({
        "frame_id": np.arange(n),
        "timestamp_s": timestamps,
        "fps": fps,
        "activity_state_label": ["active"] * n,
        "angle_left_knee": signal,
    })
    detector = RepDetector(RepDetectionConfig(
        signal_candidates=["angle_left_knee"],
        window_seconds=5.0,
        window_stride_seconds=1.0,
        min_rep_seconds=1.0,
        max_rep_seconds=3.0,
        smoothing_seconds=0.1,
        min_amplitude=0.05,
        min_prominence=0.01,
        min_confidence=0.0,
    ))
    detail(input=f"{n} active frames at {fps:g} FPS; knee signal repeats every 2 s",
           expected="13 to 16 candidates; median global and local periods near 2 s")
    result = detector.detect_segment(df)
    periods = [candidate.period_s for candidate in result.candidates]
    local_periods = result.diagnostics["signals"]["angle_left_knee"]["local_period_estimates_s"]
    global_median = f"{np.median(periods):.3f} s" if periods else "no candidates"
    local_median = f"{np.median(local_periods):.3f} s" if local_periods else "no estimates"
    detail(observed=f"{result.count} candidates; median period={global_median}; "
           f"{len(local_periods)} local estimates, median={local_median}")
    assert 13 <= result.count <= 16
    assert np.isclose(np.median(periods), 2.0, atol=0.05)
    assert local_periods
    assert np.isclose(np.median(local_periods), 2.0, atol=0.1)


def test_rep_detection_ignores_non_active_frames(detail):
    n = 300
    timestamps = np.arange(n) / 30.0
    df = pd.DataFrame({
        "frame_id": np.arange(n),
        "timestamp_s": timestamps,
        "fps": 30.0,
        "activity_state_label": ["idle"] * n,
        "angle_left_knee": np.sin(timestamps),
    })
    detail(input=f"{n} idle frames at 30 FPS with a changing knee signal", expected="0 rep candidates")
    result = RepDetector(RepDetectionConfig(signal_candidates=["angle_left_knee"])).detect_segment(df)
    detail(observed=f"{result.count} rep candidates")
    assert result.count == 0
