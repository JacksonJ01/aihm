from __future__ import annotations

import argparse
import json
from pathlib import Path

from aihumo.config import load_config, resolve_path
from aihumo.processing import process_video


def main() -> None:
    parser = argparse.ArgumentParser(description="Process one AIHuMo recording end-to-end.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--config", default="configs/config.json")
    parser.add_argument("--video", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--participant-id", default="")
    parser.add_argument("--camera-name", default="")
    parser.add_argument("--recording-date", default="")
    parser.add_argument("--exercise-hint", default="")
    parser.add_argument("--viewpoint", default="")
    parser.add_argument("--environment", default="")
    parser.add_argument("--operator", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--output-root", default="data/processed")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    cfg = load_config(root / args.config)
    model_path = Path(args.model) if args.model else resolve_path(root, cfg["pose"]["model_path"])
    video_path = Path(args.video)
    if not video_path.is_absolute():
        video_path = root / video_path

    identifiers = {
        "session_id": args.session_id,
        "video_id": args.video_id,
        "camera_id": args.camera_id,
        "participant_id": args.participant_id,
    }
    optional = {
        "camera_name": args.camera_name,
        "recording_date": args.recording_date,
        "exercise_hint": args.exercise_hint,
        "viewpoint": args.viewpoint,
        "environment": args.environment,
        "operator": args.operator,
        "notes": args.notes,
    }
    optional = {key: value for key, value in optional.items() if value}

    result = process_video(
        source_video=video_path,
        model_path=model_path,
        cfg=cfg,
        identifiers=identifiers,
        optional_metadata=optional,
        output_root=root / args.output_root,
        progress_callback=lambda fraction, message: print(f"[{fraction:6.1%}] {message}"),
    )
    print(json.dumps({
        "output_dir": str(result.output_dir),
        "landmarks": str(result.landmarks_path),
        "features": str(result.features_path),
        "skeleton_video": str(result.processed_video_path),
        "metadata": str(result.metadata_path),
        "feature_manifest": str(result.feature_manifest_path),
        "quality_report": str(result.quality_report_path),
        "processing_state": str(result.processing_state_path),
    }, indent=2))


if __name__ == "__main__":
    main()
