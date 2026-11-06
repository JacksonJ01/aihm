from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from aihumo.dataset import MultiTaskWindowDataset, collate_multitask
from aihumo.evaluate import evaluate_multitask_model
from aihumo.model import MultiTaskTemporalModel
from aihumo.scaling import FeatureScaler


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a saved AIHuMo model on its held-out test split.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--checkpoint", default="")
    parser.add_argument("--dataset-dir", default="")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    checkpoint_path = Path(args.checkpoint) if args.checkpoint else None
    if checkpoint_path is None:
        raise ValueError("--checkpoint is required for multi-task evaluation.")
    if not checkpoint_path.is_absolute():
        checkpoint_path = root / checkpoint_path
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)

    dataset_dir = Path(args.dataset_dir) if args.dataset_dir else root / "data" / "datasets" / checkpoint["dataset_manifest"]["experiment_name"]
    if not dataset_dir.is_absolute():
        dataset_dir = root / dataset_dir

    target_specs = checkpoint["target_specs"]
    mappings = checkpoint["label_mappings"]
    feature_names = list(checkpoint.get("feature_names", checkpoint["dataset_manifest"]["feature_columns"]))
    scaler = FeatureScaler.load(dataset_dir / "normalization.json")
    test_ds = MultiTaskWindowDataset(
        dataset_dir / "test.npz",
        dataset_dir / "test_metadata.json",
        target_specs,
        scaler=scaler,
    )
    if len(test_ds) == 0:
        raise RuntimeError("Held-out test split contains no windows.")

    loader = DataLoader(
        test_ds,
        batch_size=args.batch_size,
        shuffle=False,
        collate_fn=collate_multitask,
    )

    x0, _, _ = test_ds[0]
    model = MultiTaskTemporalModel(
        num_features=x0.shape[-1],
        target_specs=target_specs,
        label_mappings=mappings,
        channels=tuple(checkpoint["config"]["model"]["channels"]),
        kernels=tuple(checkpoint["config"]["model"]["kernels"]),
        dropout=float(checkpoint["config"]["model"]["dropout"]),
    )
    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available.")
    model.load_state_dict(checkpoint["model_state"])
    model.to(device)

    results = evaluate_multitask_model(model, loader, device, mappings, target_specs)
    results.update({
        "experiment_name": checkpoint["dataset_manifest"]["experiment_name"],
        "checkpoint": str(checkpoint_path),
        "dataset_dir": str(dataset_dir),
        "feature_count": len(feature_names),
        "test_samples": len(test_ds),
    })

    report_dir = root / "reports" / str(checkpoint["dataset_manifest"]["experiment_name"])
    report_dir.mkdir(parents=True, exist_ok=True)
    output_path = report_dir / "test_results.json"
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
