"""Provenance-preserving angle graph generation from canonical features."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .exercise_library import LIBRARY_VERSION, angle_preset
from .features import LEGACY_ANGLE_PREFIX, PROJECTED_ANGLE_PREFIX, angle_family


def generate_angle_graphs(
    features: pd.DataFrame,
    output_dir: str | Path,
    *,
    exercise_id: str | None = None,
    feature_data_version: str | None = None,
    export_images: bool = True,
    export_dpi: int = 180,
) -> dict[str, Any]:
    """Generate optional PNG previews without recomputing pose or features.

    Invalid values remain NaN, so matplotlib renders tracking gaps rather than
    interpolating observations into apparently valid movement.
    """
    if "timestamp_s" not in features.columns:
        raise ValueError("timestamp_s is required for angle graphs")
    prefix = PROJECTED_ANGLE_PREFIX
    available = angle_family(features.columns, prefix)
    if not available:
        prefix = LEGACY_ANGLE_PREFIX
        available = angle_family(features.columns, prefix)
    names = angle_preset(exercise_id) or list(available)
    columns = [available[name] for name in names if name in available]
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "schemaVersion": "1.0",
        "exerciseId": exercise_id,
        "exerciseLibraryVersion": LIBRARY_VERSION,
        "angleFeatureIds": columns,
        "angleSpace": "video_plane_2d" if prefix == PROJECTED_ANGLE_PREFIX else "legacy",
        "units": "degrees",
        "xAxis": "timeElapsedS",
        "featureDataVersion": feature_data_version,
        "smoothing": {"enabled": False, "method": None},
        "missingValues": "preserved as gaps",
        "imageExportDpi": max(72, int(export_dpi)),
        "imageExports": [],
    }
    if export_images and columns:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        for column in columns:
            figure, axis = plt.subplots(figsize=(9, 4.5))
            axis.plot(features["timestamp_s"], pd.to_numeric(features[column], errors="coerce"), label=column.removeprefix(prefix))
            axis.set(xlabel="Elapsed time (s)", ylabel="Angle (degrees)", title=f"AIHuMo — {column}")
            axis.grid(True, alpha=0.25)
            axis.legend()
            path = output / f"{column}.png"
            figure.tight_layout()
            figure.savefig(path, dpi=max(72, int(export_dpi)))
            plt.close(figure)
            manifest["imageExports"].append(str(path))
    manifest_path = output / "graph_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["manifestPath"] = str(manifest_path)
    return manifest
