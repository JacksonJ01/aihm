from __future__ import annotations

import json
from pathlib import Path

import numpy as np


class FeatureScaler:
    """Training-only feature standardizer with NaN-safe statistics."""

    def __init__(self):
        self.mean: np.ndarray | None = None
        self.std: np.ndarray | None = None
        self.feature_names: list[str] | None = None

    def fit(self, X: np.ndarray, feature_names: list[str] | None = None):
        if X.ndim != 3 or X.shape[0] == 0:
            raise ValueError("Expected non-empty X with shape [N, T, F].")
        flat = X.reshape(-1, X.shape[-1]).astype(np.float64)
        self.mean = np.nanmean(flat, axis=0)
        self.std = np.nanstd(flat, axis=0)
        self.mean[~np.isfinite(self.mean)] = 0.0
        self.std[~np.isfinite(self.std) | (self.std < 1e-6)] = 1.0
        self.feature_names = list(feature_names) if feature_names is not None else None
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        if self.mean is None or self.std is None:
            raise RuntimeError("Scaler has not been fitted.")
        result = (X.astype(np.float64) - self.mean) / self.std
        result[~np.isfinite(result)] = 0.0
        return result.astype(np.float32)

    def save(self, path: str | Path):
        if self.mean is None or self.std is None:
            raise RuntimeError("Cannot save an unfitted scaler.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "mean": self.mean.tolist(),
            "std": self.std.tolist(),
            "feature_names": self.feature_names,
        }, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path):
        obj = cls()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        obj.mean = np.asarray(data["mean"], dtype=np.float64)
        obj.std = np.asarray(data["std"], dtype=np.float64)
        obj.feature_names = data.get("feature_names")
        return obj
