from pathlib import Path
import argparse
import json
from aihumo.config import load_config
from aihumo.features import build_features


def main():
    parser = argparse.ArgumentParser(description="Build a final AIHuMo feature Parquet from raw landmarks.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--config", default="configs/config.json")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--width", type=int, help="Source video width if recording metadata is unavailable.")
    parser.add_argument("--height", type=int, help="Source video height if recording metadata is unavailable.")
    args = parser.parse_args()
    frame_size = None
    if args.width is not None or args.height is not None:
        if not args.width or not args.height or min(args.width, args.height) <= 0:
            parser.error("--width and --height must both be positive.")
        frame_size = (args.width, args.height)
    root = Path(args.root)
    cfg = load_config(root / args.config)
    manifest = build_features(root / args.input, root / args.output, cfg, frame_size=frame_size)
    out_manifest = root / args.output
    out_manifest = out_manifest.with_name(out_manifest.stem + "_feature_manifest.json")
    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    out_manifest.write_text(json.dumps(manifest["manifest"], indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
