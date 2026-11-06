from __future__ import annotations

import argparse
import json
from pathlib import Path

from aihumo.config import load_config
from aihumo.features import build_features
from aihumo.storage import assert_single_canonical_feature_parquet


def main() -> None:
    parser = argparse.ArgumentParser(description="Compatibility utility for legacy landmark Parquet files.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--config", default="configs/config.json")
    parser.add_argument("--input-root", default="data/processed")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    cfg = load_config(root / args.config)
    input_root = Path(args.input_root)
    if not input_root.is_absolute():
        input_root = root / input_root

    paths = sorted(input_root.glob("**/*_landmarks.parquet"))
    if not paths:
        raise RuntimeError(f"No landmark Parquet files found under {input_root}")
    for path in paths:
        output = path.with_name(path.name.replace("_landmarks.parquet", "_features.parquet"))
        assert_single_canonical_feature_parquet(path.parent, path.name.replace("_landmarks.parquet", ""), output)
        if output.exists():
            raise FileExistsError(
                f"Canonical feature Parquet already exists: {output}. "
                "Use a new processing version or remove/archive it explicitly; refusing to duplicate it."
            )
        result = build_features(path, output, cfg)
        output.with_suffix(".json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({"input": str(path), "output": str(output), "rows": result["rows"], "feature_count": result["feature_count"]}))


if __name__ == "__main__":
    main()
