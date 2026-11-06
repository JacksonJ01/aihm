import numpy as np
import pandas as pd

from aihumo.rep_detection import RepDetectionConfig, RepDetector


def test_sliding_window_rep_detection_estimates_period_and_deduplicates_extrema():
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
    result = detector.detect_segment(df)
    assert 13 <= result.count <= 16
    periods = [candidate.period_s for candidate in result.candidates]
    assert np.isclose(np.median(periods), 2.0, atol=0.05)
    local_periods = result.diagnostics["signals"]["angle_left_knee"]["local_period_estimates_s"]
    assert local_periods
    assert np.isclose(np.median(local_periods), 2.0, atol=0.1)


def test_rep_detection_ignores_non_active_frames():
    n = 300
    timestamps = np.arange(n) / 30.0
    df = pd.DataFrame({
        "frame_id": np.arange(n),
        "timestamp_s": timestamps,
        "fps": 30.0,
        "activity_state_label": ["idle"] * n,
        "angle_left_knee": np.sin(timestamps),
    })
    result = RepDetector(RepDetectionConfig(signal_candidates=["angle_left_knee"])).detect_segment(df)
    assert result.count == 0
