from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch.utils.data import Dataset


class MultiTaskWindowDataset(Dataset):
    """Torch dataset for experiment NPZ files produced by dataset_builder."""

    def __init__(
        self,
        npz_path: str | Path,
        metadata_path: str | Path,
        target_specs: dict[str, dict[str, Any]],
        scaler=None,
    ):
        self.npz_path = Path(npz_path)
        with np.load(self.npz_path, allow_pickle=False) as data:
            self.X = data["X"].astype(np.float32)
            enabled_specs = {
                name: dict(spec)
                for name, spec in target_specs.items()
                if spec.get("enabled", True) and spec.get("task") not in {"identity", "evaluation_only"}
            }
            self.target_specs = enabled_specs
            self.target_names = [
                name for name, spec in enabled_specs.items()
                if f"target_{name}" in data.files
            ]
            self.targets = {
                name: data[f"target_{name}"].copy()
                for name in self.target_names
            }

        self.meta = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
        if len(self.X) != len(self.meta):
            raise ValueError(f"Dataset length mismatch: X={len(self.X)}, metadata={len(self.meta)}")
        if self.X.ndim != 3:
            raise ValueError(f"Expected X with shape [N, T, F], got {self.X.shape}")

        if scaler is not None and len(self.X):
            self.X = scaler.transform(self.X)

    def __len__(self) -> int:
        return len(self.X)

    def __getitem__(self, idx: int):
        x = torch.from_numpy(self.X[idx]).float()
        targets: dict[str, torch.Tensor] = {}
        for name in self.target_names:
            task = str(self.target_specs[name].get("task"))
            values = self.targets[name]
            if task in {"classification", "sequence_classification"}:
                targets[name] = torch.as_tensor(values[idx], dtype=torch.long)
            elif task == "sequence_binary":
                targets[name] = torch.as_tensor(values[idx], dtype=torch.float32)
            elif task == "regression":
                targets[name] = torch.as_tensor(values[idx], dtype=torch.float32)
            else:
                raise ValueError(f"Unsupported target task: {task}")
        return x, targets, self.meta[idx]


def collate_multitask(batch):
    xs, targets, metas = zip(*batch)
    x = torch.stack([value.transpose(0, 1) for value in xs])
    target_batch: dict[str, torch.Tensor] = {}
    for name in targets[0]:
        target_batch[name] = torch.stack([item[name] for item in targets])
    return x, target_batch, list(metas)


class WindowDataset(Dataset):
    """Compatibility API for the original exercise-only classifier."""

    def __init__(
        self,
        npz_path: str | Path,
        metadata_path: str | Path,
        label_to_id: dict[str, int] | None = None,
        scaler=None,
    ):
        with np.load(npz_path, allow_pickle=False) as data:
            X = data["X"].astype(np.float32)
        all_meta = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
        label_to_id = label_to_id or {}
        valid_indices = []
        labels = []
        for index, metadata in enumerate(all_meta):
            label = metadata.get("exercise_label", metadata.get("targets", {}).get("exercise", "unknown"))
            if label != "unknown" and label in label_to_id:
                valid_indices.append(index)
                labels.append(label_to_id[label])
        self.X = X[valid_indices]
        self.y = np.asarray(labels, dtype=np.int64)
        self.meta = [all_meta[index] for index in valid_indices]
        if scaler is not None and len(self.X):
            self.X = scaler.transform(self.X)

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        return torch.from_numpy(self.X[idx]).float().transpose(0, 1), torch.tensor(self.y[idx], dtype=torch.long), self.meta[idx]


def collate_windows(batch):
    xs, ys, metas = zip(*batch)
    return torch.stack(xs), torch.stack(ys), list(metas)
