from __future__ import annotations

from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def software_version() -> str:
    try:
        return version("aihumo-pipeline")
    except PackageNotFoundError:
        return "development"


def build_metadata(
    *,
    cfg: dict,
    identifiers: dict,
    source_video: Path,
    processed_video: Path,
    landmarks_parquet: Path,
    features_parquet: Path,
    video_info: dict,
    optional_metadata: dict,
) -> dict:
    return {
        "project": cfg.get("project", {}).get("name", "AIHuMo"),
        "dataset_version": cfg.get("project", {}).get("dataset_version", "0.1.0"),
        **identifiers,
        "source_video": str(source_video),
        "processed_video": str(processed_video),
        "landmarks_parquet": str(landmarks_parquet),
        "features_parquet": str(features_parquet),
        **optional_metadata,
        "resolution": {"width": video_info["width"], "height": video_info["height"]},
        "source_fps": video_info["source_fps"],
        "frame_count": video_info["frame_count"],
        "duration_s": video_info["duration_s"],
        "codec": video_info.get("codec"),
        "frame_interval_s": video_info["frame_interval_s"],
        "processing_timestamp": utc_now_iso(),
        "software_version": software_version(),
        "processing_version": cfg.get("project", {}).get("processing_version", "1.0.0"),
    }
