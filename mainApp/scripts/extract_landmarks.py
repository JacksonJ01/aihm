from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from aihumo.config import load_config, resolve_path
from aihumo.processing import process_video


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compatibility entry point. New recordings should use scripts/process_video.py so the complete Mode 0 pipeline runs."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--config", default="configs/config.json")
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    cfg = load_config(root / args.config)
    manifest = pd.read_csv(root / args.manifest)
    model_path = resolve_path(root, cfg["pose"]["model_path"])

    for _, row in manifest.iterrows():
        source = Path(str(row["video_path"]))
        if not source.is_absolute():
            source = root / source
        result = process_video(
            source_video=source,
            model_path=model_path,
            cfg=cfg,
            identifiers={
                "session_id": str(row["session_id"]),
                "video_id": str(row["video_id"]),
                "camera_id": str(row["camera_id"]),
                "participant_id": str(row.get("participant_id", "") or ""),
            },
            optional_metadata={"description": str(row.get("description", "") or "")},
            output_root=root / "data/processed",
            progress_callback=lambda fraction, message: print(f"[{fraction:6.1%}] {message}"),
        )
        print(json.dumps({"video_id": row["video_id"], "features": str(result.features_path)}, indent=2))


if __name__ == "__main__":
    main()
