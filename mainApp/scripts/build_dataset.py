from __future__ import annotations

import argparse
import json
from pathlib import Path

from aihumo.config import load_config
from aihumo.dataset_builder import build_dataset_experiment


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an experiment-specific AIHuMo ML dataset.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--config", default="configs/config.json")
    parser.add_argument("--video-manifest", required=True)
    parser.add_argument("--experiment", default="")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    cfg = load_config(root / args.config)
    output_dir = build_dataset_experiment(
        root=root,
        manifest_path=args.video_manifest,
        cfg=cfg,
        experiment_name=args.experiment or cfg.get("dataset", {}).get("experiment_name", "experiment_001"),
    )
    manifest = json.loads((output_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    print(json.dumps({
        "dataset_dir": str(output_dir),
        "features": manifest["feature_count"],
        "window_frames": manifest["windows"]["window_frames"],
        "splits": manifest["split_summaries"],
        "targets": manifest["training_target_policy"],
    }, indent=2))


if __name__ == "__main__":
    main()
