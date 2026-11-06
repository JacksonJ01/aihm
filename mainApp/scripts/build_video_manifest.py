from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover processed AIHuMo recordings and build the manifest consumed by dataset building."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--processed-root", default="data/processed")
    parser.add_argument("--output", default="data/datasets/video_manifest.csv")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    processed_root = Path(args.processed_root)
    if not processed_root.is_absolute():
        processed_root = root / processed_root

    rows: list[dict] = []
    for metadata_path in sorted(processed_root.glob("*/**/metadata/*_metadata.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        session_id = str(metadata.get("session_id", metadata_path.parent.parent.parent.name))
        video_id = str(metadata.get("video_id", metadata_path.stem.replace("_metadata", "")))
        annotation_path = metadata_path.parent.parent / "annotations" / f"{video_id}_annotations.json"
        state_path = metadata_path.parent.parent / ".processing" / "processing_state.json"

        annotation_status = "missing"
        if annotation_path.exists():
            try:
                annotation_document = json.loads(annotation_path.read_text(encoding="utf-8"))
                annotation_status = str(annotation_document.get("annotation_session", {}).get("status", "in_progress"))
            except json.JSONDecodeError:
                annotation_status = "invalid_json"

        rows.append({
            "session_id": session_id,
            "video_id": video_id,
            "participant_id": metadata.get("participant_id", ""),
            "camera_id": metadata.get("camera_id", ""),
            "source_video": metadata.get("source_video", ""),
            "processed_video": metadata.get("processed_video", ""),
            "features_path": metadata.get("features_parquet", ""),
            "landmarks_path": metadata.get("landmarks_parquet", ""),
            "metadata_path": str(metadata_path),
            "annotation_json": str(annotation_path),
            "annotation_status": annotation_status,
            "processing_state": str(state_path) if state_path.exists() else "",
            "source_fps": metadata.get("source_fps"),
            "frame_count": metadata.get("frame_count"),
            "duration_s": metadata.get("duration_s"),
            "exercise_hint": metadata.get("exercise_hint", ""),
            "viewpoint": metadata.get("viewpoint", ""),
            "environment": metadata.get("environment", ""),
        })

    if not rows:
        raise RuntimeError(f"No processed metadata files found under {processed_root}")

    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows).sort_values(["session_id", "video_id"]).reset_index(drop=True)
    frame.to_csv(output, index=False)
    print(f"Wrote {len(frame)} recordings to {output}")
    print(frame[["session_id", "video_id", "participant_id", "annotation_status"]].to_string(index=False))


if __name__ == "__main__":
    main()
