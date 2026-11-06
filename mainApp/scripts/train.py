from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader

from aihumo.config import load_config
from aihumo.dataset import MultiTaskWindowDataset, collate_multitask
from aihumo.evaluate import evaluate_multitask_model
from aihumo.model import MultiTaskTemporalModel
from aihumo.scaling import FeatureScaler


def seed_all(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _load_manifest(dataset_dir: Path) -> dict[str, Any]:
    path = dataset_dir / "dataset_manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing dataset manifest: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _fit_scaler(dataset_dir: Path, feature_names: list[str]) -> FeatureScaler:
    with np.load(dataset_dir / "train.npz", allow_pickle=False) as data:
        X = data["X"].astype(np.float32)
    if X.size == 0:
        raise RuntimeError("Training split contains no windows.")
    scaler = FeatureScaler().fit(X, feature_names=feature_names)
    scaler.save(dataset_dir / "normalization.json")
    return scaler


def _class_weights(target: np.ndarray, num_classes: int, device: torch.device) -> torch.Tensor | None:
    if num_classes < 2:
        return None
    values = target.reshape(-1)
    values = values[values >= 0]
    if values.size == 0:
        return None
    counts = np.bincount(values.astype(np.int64), minlength=num_classes).astype(np.float64)
    weights = np.zeros(num_classes, dtype=np.float32)
    present = counts > 0
    weights[present] = float(values.size) / (float(present.sum()) * counts[present])
    # A zero weight for a class absent from training is safe, but keeping it at
    # zero also makes accidental validation-only classes contribute no loss.
    return torch.tensor(weights, dtype=torch.float32, device=device)


def _binary_pos_weight(target: np.ndarray, device: torch.device) -> torch.Tensor | None:
    values = target.reshape(-1).astype(np.float64)
    positives = float(values.sum())
    negatives = float(len(values) - positives)
    if positives <= 0:
        return None
    return torch.tensor(negatives / positives, dtype=torch.float32, device=device)


def _loss_for_target(
    name: str,
    spec: dict[str, Any],
    outputs: dict[str, torch.Tensor],
    targets: dict[str, torch.Tensor],
    mappings: dict[str, dict[str, int]],
    train_target_array: np.ndarray,
    device: torch.device,
) -> torch.Tensor:
    task = str(spec.get("task"))
    prediction = outputs[name]
    target = targets[name]
    weight = float(spec.get("weight", 1.0))

    if task in {"classification", "sequence_classification"}:
        valid = target >= 0
        if not bool(valid.any()):
            return prediction.sum() * 0.0
        num_classes = len(mappings.get(name, {}))
        class_weight = _class_weights(train_target_array, num_classes, device)
        if task == "sequence_classification":
            prediction = prediction.reshape(-1, prediction.shape[-1])
            target = target.reshape(-1)
            valid = target >= 0
            prediction = prediction[valid]
            target = target[valid]
        criterion = nn.CrossEntropyLoss(weight=class_weight)
        return weight * criterion(prediction, target)

    if task == "sequence_binary":
        pos_weight = _binary_pos_weight(train_target_array, device)
        criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
        return weight * criterion(prediction, target)

    if task == "regression":
        mask = torch.isfinite(target)
        if not bool(mask.any()):
            return prediction.sum() * 0.0
        return weight * nn.MSELoss()(prediction[mask], target[mask])

    raise ValueError(f"Unsupported trainable target task: {task}")


def _effective_target_specs(
    target_specs: dict[str, dict[str, Any]],
    mappings: dict[str, dict[str, int]],
    train_target_arrays: dict[str, np.ndarray],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Remove trainable targets that have no learnable supervision in training."""
    effective = {name: dict(spec) for name, spec in target_specs.items()}
    skipped: list[str] = []
    for name, spec in effective.items():
        if not spec.get("enabled", True) or not spec.get("trainable", False):
            continue
        task = str(spec.get("task"))
        if task in {"classification", "sequence_classification"} and len(mappings.get(name, {})) < 2:
            spec["trainable"] = False
            skipped.append(f"{name}: fewer than two training classes")
            continue
        if task == "sequence_binary":
            values = train_target_arrays.get(name)
            if values is None:
                spec["trainable"] = False
                skipped.append(f"{name}: training target array is missing")
                continue
            finite = np.isfinite(values)
            positives = int(np.sum(values[finite] > 0.5))
            negatives = int(np.sum(values[finite] <= 0.5))
            if positives == 0:
                spec["trainable"] = False
                skipped.append(f"{name}: no positive training samples")
            elif negatives == 0:
                spec["trainable"] = False
                skipped.append(f"{name}: no negative training samples")
    return effective, skipped


def _compute_loss(
    model: MultiTaskTemporalModel,
    loader: DataLoader,
    target_specs: dict[str, dict[str, Any]],
    train_target_arrays: dict[str, np.ndarray],
    mappings: dict[str, dict[str, int]],
    device: torch.device,
    training: bool,
    optimizer=None,
    grad_clip_norm: float = 0.0,
) -> float:
    total_loss = 0.0
    seen = 0
    model.train(training)
    context = torch.enable_grad() if training else torch.no_grad()
    with context:
        for x, targets, _ in loader:
            x = x.to(device, non_blocking=True)
            targets = {name: value.to(device, non_blocking=True) for name, value in targets.items()}
            if training:
                optimizer.zero_grad(set_to_none=True)
            outputs = model(x)
            losses = []
            for name, spec in target_specs.items():
                if not spec.get("enabled", True) or not spec.get("trainable", False) or name not in outputs:
                    continue
                losses.append(_loss_for_target(
                    name, spec, outputs, targets, mappings,
                    train_target_arrays[name], device,
                ))
            if not losses:
                raise RuntimeError("No trainable model targets are available for this dataset.")
            loss = sum(losses)
            if training:
                loss.backward()
                if grad_clip_norm > 0:
                    torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip_norm)
                optimizer.step()
            total_loss += float(loss.item()) * x.size(0)
            seen += x.size(0)
    return total_loss / max(1, seen)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train an AIHuMo multi-task temporal model.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--config", default="configs/config.json")
    parser.add_argument("--dataset-dir", default="")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    cfg = load_config(root / args.config)
    seed_all(int(cfg.get("training", {}).get("seed", 42)))

    dataset_dir = Path(args.dataset_dir) if args.dataset_dir else root / "data" / "datasets" / cfg["dataset"]["experiment_name"]
    if not dataset_dir.is_absolute():
        dataset_dir = root / dataset_dir
    manifest = _load_manifest(dataset_dir)
    target_specs = manifest["targets"]
    mappings = manifest.get("label_mappings", {})
    feature_names = list(manifest["feature_columns"])
    with np.load(dataset_dir / "train.npz", allow_pickle=False) as train_data:
        raw_train_target_arrays = {
            name: train_data[f"target_{name}"]
            for name, spec in target_specs.items()
            if spec.get("enabled", True) and spec.get("trainable", False) and f"target_{name}" in train_data.files
        }
    effective_specs, skipped = _effective_target_specs(target_specs, mappings, raw_train_target_arrays)

    scaler = _fit_scaler(dataset_dir, feature_names)
    train_ds = MultiTaskWindowDataset(dataset_dir / "train.npz", dataset_dir / "train_metadata.json", target_specs, scaler=scaler)
    val_path = dataset_dir / "val.npz"
    test_path = dataset_dir / "test.npz"
    val_ds = MultiTaskWindowDataset(val_path, dataset_dir / "val_metadata.json", target_specs, scaler=scaler) if val_path.exists() else None
    test_ds = MultiTaskWindowDataset(test_path, dataset_dir / "test_metadata.json", target_specs, scaler=scaler) if test_path.exists() else None
    if len(train_ds) == 0:
        raise RuntimeError("Training dataset has zero usable windows.")

    batch_size = int(cfg["training"].get("batch_size", 32))
    num_workers = int(cfg["training"].get("num_workers", 0))
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=num_workers, collate_fn=collate_multitask)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=num_workers, collate_fn=collate_multitask) if val_ds and len(val_ds) else None
    test_loader = DataLoader(test_ds, batch_size=batch_size, shuffle=False, num_workers=num_workers, collate_fn=collate_multitask) if test_ds and len(test_ds) else None

    x0, _, _ = train_ds[0]
    model = MultiTaskTemporalModel(
        num_features=x0.shape[-1],
        target_specs=effective_specs,
        label_mappings=mappings,
        channels=tuple(cfg["model"]["channels"]),
        kernels=tuple(cfg["model"]["kernels"]),
        dropout=float(cfg["model"]["dropout"]),
    )

    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was explicitly requested but is not available.")
    device = torch.device("cuda" if args.device == "cuda" or (args.device == "auto" and torch.cuda.is_available()) else "cpu")
    model.to(device)

    train_npz = np.load(dataset_dir / "train.npz", allow_pickle=False)
    train_target_arrays = {
        name: train_npz[f"target_{name}"]
        for name, spec in effective_specs.items()
        if spec.get("enabled", True) and spec.get("trainable", False) and f"target_{name}" in train_npz.files
    }
    if not train_target_arrays:
        raise RuntimeError("No trainable target arrays remain after validation. Add more labeled classes or change the experiment target selection.")

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(cfg["training"]["learning_rate"]),
        weight_decay=float(cfg["training"]["weight_decay"]),
    )
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min", factor=0.5, patience=2)
    grad_clip_norm = float(cfg["training"].get("grad_clip_norm", 0.0))

    model_dir = root / "models" / str(manifest["experiment_name"])
    report_dir = root / "reports" / str(manifest["experiment_name"])
    model_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    history: list[dict[str, Any]] = []
    best_val = float("inf")
    best_epoch = 0
    patience_left = int(cfg["training"].get("patience", 5))

    for epoch in range(1, int(cfg["training"]["epochs"]) + 1):
        train_loss = _compute_loss(
            model, train_loader, effective_specs, train_target_arrays, mappings,
            device, training=True, optimizer=optimizer, grad_clip_norm=grad_clip_norm,
        )
        val_loss = train_loss if val_loader is None else _compute_loss(
            model, val_loader, effective_specs, train_target_arrays, mappings,
            device, training=False,
        )
        scheduler.step(val_loss)

        row = {
            "epoch": epoch,
            "train_loss": float(train_loss),
            "val_loss": float(val_loss),
            "learning_rate": float(optimizer.param_groups[0]["lr"]),
        }
        history.append(row)
        print(
            f"epoch={epoch:03d} train_loss={train_loss:.4f} "
            f"val_loss={val_loss:.4f} lr={optimizer.param_groups[0]['lr']:.6g}"
        )

        if val_loss < best_val:
            best_val = val_loss
            best_epoch = epoch
            patience_left = int(cfg["training"].get("patience", 5))
            torch.save({
                "model_state": model.state_dict(),
                "num_features": int(x0.shape[-1]),
                "target_specs": effective_specs,
                "label_mappings": mappings,
                "config": cfg,
                "dataset_manifest": manifest,
                "feature_names": feature_names,
                "best_val_loss": float(best_val),
                "best_epoch": best_epoch,
                "normalization": "data/datasets/%s/normalization.json" % manifest["experiment_name"],
            }, model_dir / "aihumo_multitask_best.pt")
        else:
            patience_left -= 1
            if patience_left <= 0:
                print("Early stopping.")
                break

    train_npz.close()

    training_report = {
        "experiment_name": manifest["experiment_name"],
        "device": str(device),
        "epochs_completed": len(history),
        "best_epoch": best_epoch,
        "best_val_loss": best_val,
        "history": history,
        "effective_target_specs": effective_specs,
        "skipped_targets": skipped,
        "normalization": str(dataset_dir / "normalization.json"),
    }
    (report_dir / "training_history.json").write_text(json.dumps(training_report, indent=2), encoding="utf-8")

    checkpoint_path = model_dir / "aihumo_multitask_best.pt"
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model_state"])
    if test_loader is not None:
        results = evaluate_multitask_model(model, test_loader, device, mappings, effective_specs)
        results["experiment_name"] = manifest["experiment_name"]
        results["checkpoint"] = str(checkpoint_path)
        (report_dir / "test_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
