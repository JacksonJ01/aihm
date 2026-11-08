from __future__ import annotations

import numpy as np

EPSILON = 1e-8


def angle_degrees(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Return angle ABC in degrees, or NaN for invalid/degenerate vectors."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    c = np.asarray(c, dtype=float)
    ba = a - b
    bc = c - b
    denom = np.linalg.norm(ba) * np.linalg.norm(bc)
    if not np.isfinite(denom) or denom <= EPSILON:
        return np.nan
    cosine = np.clip(np.dot(ba, bc) / denom, -1.0, 1.0)
    return float(np.degrees(np.arccos(cosine)))


def midpoint(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (np.asarray(a, dtype=float) + np.asarray(b, dtype=float)) / 2.0


def distance(a: np.ndarray, b: np.ndarray) -> float:
    value = np.linalg.norm(np.asarray(a, dtype=float) - np.asarray(b, dtype=float))
    return float(value) if np.isfinite(value) else np.nan


def vectorized_angles(points: np.ndarray, targets: dict[str, list[int]]) -> dict[str, np.ndarray]:
    """Calculate A-B-C angles for points shaped [frames, landmarks, coordinates]."""
    output: dict[str, np.ndarray] = {}
    for name, (a, b, c) in targets.items():
        ba = points[:, a, :] - points[:, b, :]
        bc = points[:, c, :] - points[:, b, :]
        ba_norm = np.linalg.norm(ba, axis=1)
        bc_norm = np.linalg.norm(bc, axis=1)
        denom = ba_norm * bc_norm
        values = np.full(points.shape[0], np.nan, dtype=float)
        valid = np.isfinite(denom) & (denom > EPSILON)
        if np.any(valid):
            cosine = np.sum(ba[valid] * bc[valid], axis=1) / denom[valid]
            values[valid] = np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0)))
        output[name] = values
    return output


def vectorized_point_angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Calculate angle ABC for frame-aligned XY or XYZ points."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    c = np.asarray(c, dtype=float)
    if a.shape != b.shape or a.shape != c.shape or a.ndim != 2 or a.shape[1] not in (2, 3):
        raise ValueError("Point angle inputs must have matching shape [frames, 2 or 3].")
    ba = a - b
    bc = c - b
    denom = np.linalg.norm(ba, axis=1) * np.linalg.norm(bc, axis=1)
    values = np.full(a.shape[0], np.nan, dtype=float)
    valid = np.isfinite(denom) & (denom > EPSILON)
    if np.any(valid):
        cosine = np.sum(ba[valid] * bc[valid], axis=1) / denom[valid]
        values[valid] = np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0)))
    return values


def vectorized_distances(points: np.ndarray, definitions: dict[str, list[int]]) -> dict[str, np.ndarray]:
    output: dict[str, np.ndarray] = {}
    for name, (a, b) in definitions.items():
        delta = points[:, a, :] - points[:, b, :]
        values = np.linalg.norm(delta, axis=1)
        values[~np.isfinite(values)] = np.nan
        output[name] = values
    return output
