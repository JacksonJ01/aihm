from __future__ import annotations

import torch
from torch import nn


class TemporalConvBackbone(nn.Module):
    """Shape-preserving temporal CNN: [B, F, T] -> [B, T, H]."""

    def __init__(self, num_features: int, channels=(64, 128), kernels=(7, 5), dropout=0.2):
        super().__init__()
        if len(channels) != len(kernels) or not channels:
            raise ValueError("channels and kernels must have the same non-zero length")
        layers = []
        in_channels = int(num_features)
        for out_channels, kernel in zip(channels, kernels):
            kernel = int(kernel)
            if kernel <= 0 or kernel % 2 == 0:
                raise ValueError("Temporal CNN kernels must be positive odd integers.")
            layers.extend([
                nn.Conv1d(in_channels, int(out_channels), kernel, padding=kernel // 2),
                nn.BatchNorm1d(int(out_channels)),
                nn.ReLU(),
                nn.Dropout(float(dropout)),
            ])
            in_channels = int(out_channels)
        self.layers = nn.Sequential(*layers)
        self.output_channels = in_channels

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.layers(x).transpose(1, 2)


class MultiTaskTemporalModel(nn.Module):
    """Shared temporal backbone with configurable sequence/window heads.

    Local repetition and set numbers are identifiers, not universal classes, so
    `rep_id` and `set_id` are intentionally excluded as trainable model heads.
    Repetition learning uses `rep_boundary` plus temporal phase structure instead.
    """

    def __init__(
        self,
        num_features: int,
        target_specs: dict[str, dict],
        label_mappings: dict[str, dict[str, int]],
        channels=(64, 128),
        kernels=(7, 5),
        dropout=0.2,
    ):
        super().__init__()
        self.backbone = TemporalConvBackbone(num_features, channels, kernels, dropout)
        hidden = self.backbone.output_channels
        self.target_specs = {name: dict(spec) for name, spec in target_specs.items()}
        self.label_mappings = label_mappings
        self.heads = nn.ModuleDict()

        for name, spec in self.target_specs.items():
            if not spec.get("enabled", True) or not spec.get("trainable", False):
                continue
            task = spec.get("task")
            if task in {"classification", "sequence_classification"}:
                num_classes = len(label_mappings.get(name, {}))
                if num_classes < 2:
                    # The trainer excludes these targets from the effective training
                    # configuration. Keeping the guard here prevents accidental use.
                    continue
                self.heads[name] = nn.Linear(hidden, num_classes)
            elif task in {"sequence_binary", "regression"}:
                self.heads[name] = nn.Linear(hidden, 1)
            else:
                raise ValueError(f"Unsupported trainable target task: {task}")

    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        temporal = self.backbone(x)
        pooled = temporal.mean(dim=1)
        outputs: dict[str, torch.Tensor] = {}
        for name, head in self.heads.items():
            task = self.target_specs[name].get("task")
            if task == "sequence_classification":
                outputs[name] = head(temporal)
            elif task == "sequence_binary":
                outputs[name] = head(temporal).squeeze(-1)
            elif task == "classification":
                outputs[name] = head(pooled)
            elif task == "regression":
                outputs[name] = head(pooled).squeeze(-1)
        return outputs


class CNNBaseline(nn.Module):
    """Compatibility exercise-only classifier."""

    def __init__(self, num_features: int, num_classes: int, channels=(64, 128), kernels=(7, 5), dropout=0.2):
        super().__init__()
        self.backbone = TemporalConvBackbone(num_features, channels, kernels, dropout)
        self.head = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(self.backbone.output_channels, num_classes),
        )

    def forward(self, x):
        temporal = self.backbone(x)
        return self.head(temporal.mean(dim=1))
