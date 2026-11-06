from __future__ import annotations

from typing import Any

import pandas as pd


def _fraction(series: pd.Series, predicate) -> float:
    if series.empty:
        return 0.0
    return float(predicate(series).mean())


def build_quality_report(df: pd.DataFrame, feature_columns: list[str] | None = None) -> dict[str, Any]:
    feature_columns = feature_columns or [
        column for column in df.columns
        if column not in {
            "session_id", "video_id", "participant_id", "camera_id",
            "frame_id", "timestamp_s", "fps",
        }
    ]

    pose_fraction = _fraction(
        pd.to_numeric(df.get("pose_present", pd.Series(index=df.index, dtype=float)), errors="coerce").fillna(0),
        lambda values: values > 0,
    )
    feature_nan = {}
    for column in feature_columns:
        values = pd.to_numeric(df[column], errors="coerce")
        feature_nan[column] = float(values.isna().mean())

    visibility_columns = [c for c in df.columns if c.endswith("_visibility")]
    visibility_summary = {}
    for column in visibility_columns:
        values = pd.to_numeric(df[column], errors="coerce")
        visibility_summary[column] = {
            "mean": float(values.mean()) if values.notna().any() else None,
            "missing_fraction": float(values.isna().mean()),
        }

    report = {
        "frame_count": int(len(df)),
        "pose_present_fraction": pose_fraction,
        "pose_missing_fraction": 1.0 - pose_fraction,
        "feature_count": int(len(feature_columns)),
        "feature_nan_fraction": feature_nan,
        "highest_missing_features": [
            {"feature": name, "nan_fraction": value}
            for name, value in sorted(feature_nan.items(), key=lambda item: item[1], reverse=True)[:20]
        ],
        "landmark_visibility": visibility_summary,
        "timestamp": {
            "start_s": float(df["timestamp_s"].iloc[0]),
            "end_s": float(df["timestamp_s"].iloc[-1]),
            "duration_s": float(df["timestamp_s"].iloc[-1] - df["timestamp_s"].iloc[0]),
        },
    }

    if "target_status" in df.columns:
        status_counts = df["target_status"].value_counts(dropna=False).to_dict()
        report["target_tracking"] = {
            "status_counts": {str(key): int(value) for key, value in status_counts.items()},
            "tracked_fraction": float(df["target_status"].isin(["tracked", "reacquired"]).mean()),
            "occluded_fraction": float(df["target_status"].isin(["partially_occluded", "occluded"]).mean()),
            "lost_fraction": float((df["target_status"] == "lost").mean()),
            "reacquisition_count": int(pd.to_numeric(df.get("reacquisition_flag", pd.Series(False, index=df.index)), errors="coerce").fillna(0).astype(bool).sum()),
            "mean_target_confidence": float(pd.to_numeric(df.get("target_confidence", pd.Series(index=df.index)), errors="coerce").mean()),
        }
    return report
