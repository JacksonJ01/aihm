from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .storage import save_json_atomic


@dataclass(frozen=True)
class RepDetectionConfig:
    """Configuration for the deterministic, suggestion-only rep detector.

    Amplitude answers *how much* a signal moves. Period/frequency answers *how
    often* the cycle repeats. The detector uses both measurements and never
    writes predictions into annotations.json.
    """

    window_seconds: float = 5.0
    window_stride_seconds: float = 1.0
    min_rep_seconds: float = 0.75
    max_rep_seconds: float = 8.0
    smoothing_seconds: float = 0.15
    min_amplitude: float = 0.08
    min_prominence: float = 0.04
    min_confidence: float = 0.45
    signal_candidates: list[str] = field(default_factory=lambda: [
        "angle_left_knee",
        "angle_right_knee",
        "angle_left_elbow",
        "angle_right_elbow",
        "distance_left_hip_left_knee",
        "distance_right_hip_right_knee",
    ])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RepDetectionConfig":
        allowed = {field_name for field_name in cls.__dataclass_fields__}
        values = {key: value for key, value in data.items() if key in allowed}
        return cls(**values)


@dataclass(frozen=True)
class RepCandidate:
    start_frame: int
    end_frame: int
    start_time_s: float
    end_time_s: float
    period_s: float
    frequency_hz: float
    amplitude: float
    prominence: float
    signal_name: str
    confidence: float
    local_period_s: float | None = None
    period_consistency: float = 0.0


@dataclass(frozen=True)
class RepDetectionResult:
    candidates: list[RepCandidate]
    diagnostics: dict[str, Any]

    @property
    def count(self) -> int:
        return len(self.candidates)

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "source": "derived rep-detection suggestion",
            "authoritative_source": "annotations.json",
            "candidates": [asdict(item) for item in self.candidates],
            "diagnostics": self.diagnostics,
        }


class RepDetector:
    """Baseline periodic-motion analyzer for human-reviewed rep suggestions."""

    def __init__(self, config: RepDetectionConfig | None = None):
        self.config = config or RepDetectionConfig()

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "RepDetector":
        return cls(RepDetectionConfig.from_dict(config.get("rep_detection", {})))

    @staticmethod
    def _infer_fps(df: pd.DataFrame) -> float:
        if "fps" in df.columns:
            values = pd.to_numeric(df["fps"], errors="coerce").dropna()
            if not values.empty and float(values.iloc[0]) > 0:
                return float(values.iloc[0])
        timestamps = pd.to_numeric(df["timestamp_s"], errors="coerce").to_numpy(dtype=float)
        dt = np.diff(timestamps)
        valid = dt[np.isfinite(dt) & (dt > 0)]
        if valid.size == 0:
            raise ValueError("Cannot infer FPS for repetition detection.")
        return float(1.0 / np.median(valid))

    @staticmethod
    def _smooth(values: np.ndarray, window_frames: int) -> np.ndarray:
        if window_frames <= 1:
            return values.copy()
        window_frames = int(window_frames)
        kernel = np.ones(window_frames, dtype=float) / float(window_frames)
        return np.convolve(values, kernel, mode="same")

    @staticmethod
    def _normalize(values: np.ndarray) -> np.ndarray:
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            return np.full_like(values, np.nan, dtype=float)
        lo, hi = np.percentile(finite, [5, 95])
        scale = float(hi - lo)
        if scale < 1e-9:
            scale = float(np.max(finite) - np.min(finite))
        if scale < 1e-9:
            return np.zeros_like(values, dtype=float)
        center = float(np.median(finite))
        return (values - center) / scale

    @staticmethod
    def estimate_period_from_window(
        signal: np.ndarray,
        fps: float,
        min_period_frames: int,
        max_period_frames: int,
    ) -> float | None:
        """Estimate period in seconds from one signal window using autocorrelation."""
        if len(signal) < 4:
            return None
        finite = np.isfinite(signal)
        if finite.sum() < max(10, min_period_frames * 2):
            return None
        values = signal.copy()
        indices = np.arange(len(values))
        values[~finite] = np.interp(indices[~finite], indices[finite], values[finite])
        values = values - np.mean(values)
        denom = float(np.dot(values, values))
        if denom <= 1e-12:
            return None
        corr = np.correlate(values, values, mode="full")[len(values) - 1:]
        corr /= denom
        lo = max(1, int(min_period_frames))
        hi = min(len(corr) - 1, int(max_period_frames))
        if hi < lo:
            return None
        lag = lo + int(np.argmax(corr[lo:hi + 1]))
        if corr[lag] <= 0:
            return None
        return float(lag / fps)

    def estimate_local_periods(self, signal: np.ndarray, fps: float) -> list[dict[str, float]]:
        """Estimate cadence independently across overlapping sliding windows."""
        min_period_frames = max(2, int(round(self.config.min_rep_seconds * fps)))
        max_period_frames = max(min_period_frames + 1, int(round(self.config.max_rep_seconds * fps)))
        window_frames = max(
            max_period_frames * 2,
            int(round(self.config.window_seconds * fps)),
        )
        stride_frames = max(1, int(round(self.config.window_stride_seconds * fps)))
        if len(signal) < window_frames:
            period = self.estimate_period_from_window(signal, fps, min_period_frames, min(max_period_frames, len(signal) - 1))
            return [{"start_index": 0.0, "end_index": float(max(0, len(signal) - 1)), "period_s": period}] if period else []

        windows: list[dict[str, float]] = []
        for start in range(0, len(signal) - window_frames + 1, stride_frames):
            end = start + window_frames
            period = self.estimate_period_from_window(signal[start:end], fps, min_period_frames, max_period_frames)
            if period is not None:
                windows.append({"start_index": float(start), "end_index": float(end - 1), "period_s": float(period)})
        return windows

    @staticmethod
    def _local_extrema(signal: np.ndarray, min_distance: int) -> tuple[list[int], list[int]]:
        peaks: list[int] = []
        troughs: list[int] = []
        for index in range(1, len(signal) - 1):
            if not np.isfinite(signal[index - 1:index + 2]).all():
                continue
            if signal[index] >= signal[index - 1] and signal[index] > signal[index + 1]:
                if not peaks or index - peaks[-1] >= min_distance:
                    peaks.append(index)
                elif signal[index] > signal[peaks[-1]]:
                    peaks[-1] = index
            if signal[index] <= signal[index - 1] and signal[index] < signal[index + 1]:
                if not troughs or index - troughs[-1] >= min_distance:
                    troughs.append(index)
                elif signal[index] < signal[troughs[-1]]:
                    troughs[-1] = index
        return peaks, troughs

    @staticmethod
    def _nearest_local_period(local_periods: list[dict[str, float]], center_index: int) -> float | None:
        if not local_periods:
            return None
        best = min(local_periods, key=lambda item: abs((item["start_index"] + item["end_index"]) / 2.0 - center_index))
        return float(best["period_s"])

    @staticmethod
    def _period_consistency(local_periods: list[dict[str, float]], period_s: float, center_index: int, window_radius: int) -> float:
        if not local_periods:
            return 0.0
        nearby = [
            item["period_s"]
            for item in local_periods
            if abs((item["start_index"] + item["end_index"]) / 2.0 - center_index) <= window_radius
        ]
        if not nearby:
            nearby = [item["period_s"] for item in local_periods]
        median_period = float(np.median(nearby))
        relative_error = abs(period_s - median_period) / max(median_period, 1e-9)
        return float(max(0.0, 1.0 - min(1.0, relative_error)))

    def _detect_signal(self, df: pd.DataFrame, signal_name: str) -> tuple[list[RepCandidate], dict[str, Any]]:
        fps = self._infer_fps(df)
        values = pd.to_numeric(df[signal_name], errors="coerce").to_numpy(dtype=float)
        finite = np.isfinite(values)
        if finite.sum() < 8:
            return [], {"signal": signal_name, "reason": "insufficient_finite_samples"}
        if not finite.all():
            indices = np.arange(len(values))
            values[~finite] = np.interp(indices[~finite], indices[finite], values[finite])

        smooth_frames = max(1, int(round(self.config.smoothing_seconds * fps)))
        smooth = self._smooth(values, smooth_frames)
        normalized = self._normalize(smooth)
        min_period_frames = max(2, int(round(self.config.min_rep_seconds * fps)))
        max_period_frames = max(min_period_frames + 1, int(round(self.config.max_rep_seconds * fps)))
        min_extrema_distance = max(1, min_period_frames // 2)
        peaks, troughs = self._local_extrema(normalized, min_extrema_distance)
        local_periods = self.estimate_local_periods(normalized, fps)
        window_radius = max(1, int(round(self.config.window_seconds * fps / 2.0)))

        candidates: list[RepCandidate] = []
        for extrema in (peaks, troughs):
            for start_idx, end_idx in zip(extrema, extrema[1:]):
                period_frames = end_idx - start_idx
                if period_frames < min_period_frames or period_frames > max_period_frames:
                    continue
                segment = normalized[start_idx:end_idx + 1]
                amplitude = float(np.nanmax(segment) - np.nanmin(segment))
                if amplitude < self.config.min_amplitude:
                    continue

                left = max(0, start_idx - period_frames // 2)
                right = min(len(normalized), end_idx + period_frames // 2 + 1)
                neighborhood = normalized[left:right]
                local_range = float(np.nanmax(neighborhood) - np.nanmin(neighborhood))
                prominence = amplitude / max(local_range, 1e-9)
                if prominence < self.config.min_prominence:
                    continue

                period_s = float(period_frames / fps)
                frequency = float(1.0 / period_s)
                center = int(round((start_idx + end_idx) / 2.0))
                local_period = self._nearest_local_period(local_periods, center)
                consistency = self._period_consistency(local_periods, period_s, center, window_radius)
                amplitude_score = min(1.0, amplitude / max(self.config.min_amplitude * 3.0, 1e-9))
                prominence_score = min(1.0, prominence / max(self.config.min_prominence * 2.0, 1e-9))
                confidence = float(0.4 * amplitude_score + 0.3 * prominence_score + 0.3 * consistency)
                if confidence < self.config.min_confidence:
                    continue

                candidates.append(RepCandidate(
                    start_frame=int(df["frame_id"].iloc[start_idx]),
                    end_frame=int(df["frame_id"].iloc[end_idx]),
                    start_time_s=float(df["timestamp_s"].iloc[start_idx]),
                    end_time_s=float(df["timestamp_s"].iloc[end_idx]),
                    period_s=period_s,
                    frequency_hz=frequency,
                    amplitude=amplitude,
                    prominence=float(prominence),
                    signal_name=signal_name,
                    confidence=confidence,
                    local_period_s=local_period,
                    period_consistency=consistency,
                ))

        diagnostics = {
            "signal": signal_name,
            "finite_fraction": float(finite.mean()),
            "smoothing_frames": smooth_frames,
            "peak_count": len(peaks),
            "trough_count": len(troughs),
            "sliding_window_seconds": float(self.config.window_seconds),
            "sliding_window_stride_seconds": float(self.config.window_stride_seconds),
            "local_period_estimates_s": [item["period_s"] for item in local_periods],
            "local_frequency_estimates_hz": [1.0 / item["period_s"] for item in local_periods],
        }
        return candidates, diagnostics

    def detect_segment(self, df: pd.DataFrame, *, activity_state: str = "active") -> RepDetectionResult:
        """Analyze one manually identified activity segment.

        The method is intentionally suggestion-only. It does not change the
        feature table or annotations.json.
        """
        if df.empty:
            return RepDetectionResult([], {"reason": "empty_dataframe"})
        if activity_state and "activity_state_label" in df.columns:
            df = df[df["activity_state_label"].astype(str) == activity_state].copy()
        if df.empty:
            return RepDetectionResult([], {"reason": "no_matching_activity_state"})

        all_candidates: list[RepCandidate] = []
        diagnostics: dict[str, Any] = {"signals": {}, "config": asdict(self.config)}
        for signal_name in self.config.signal_candidates:
            if signal_name not in df.columns:
                diagnostics["signals"][signal_name] = {"reason": "missing_column"}
                continue
            candidates, signal_diag = self._detect_signal(df.reset_index(drop=True), signal_name)
            diagnostics["signals"][signal_name] = signal_diag
            all_candidates.extend(candidates)

        # Coincident candidates from multiple signals are support for one cycle,
        # not separate repetitions. Keep the highest-confidence representative.
        all_candidates.sort(key=lambda item: (item.start_time_s, item.end_time_s, -item.confidence))
        merged: list[RepCandidate] = []
        for candidate in all_candidates:
            if not merged:
                merged.append(candidate)
                continue

            existing = merged[-1]
            overlap = max(0.0, min(existing.end_time_s, candidate.end_time_s) - max(existing.start_time_s, candidate.start_time_s))
            shorter = min(existing.period_s, candidate.period_s)
            overlap_fraction = overlap / max(shorter, 1e-9)
            period_relative_error = abs(existing.period_s - candidate.period_s) / max(existing.period_s, candidate.period_s, 1e-9)

            # Peak-to-peak and trough-to-trough candidates for the same cycle are
            # offset by roughly half a period and therefore overlap substantially.
            # Treat those as one proposed repetition. The same rule also combines
            # coincident evidence from different signals.
            if overlap_fraction >= 0.40 and period_relative_error <= 0.25:
                if candidate.confidence > existing.confidence:
                    merged[-1] = candidate
            else:
                merged.append(candidate)

        diagnostics["candidate_count_before_merge"] = len(all_candidates)
        diagnostics["candidate_count_after_merge"] = len(merged)
        return RepDetectionResult(merged, diagnostics)


def save_rep_suggestions(result: RepDetectionResult, path: str | Path) -> None:
    save_json_atomic(result.to_document(), path)
