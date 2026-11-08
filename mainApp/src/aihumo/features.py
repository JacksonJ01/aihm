from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from .geometry import vectorized_angles, vectorized_distances, vectorized_point_angle

LOGGER = logging.getLogger(__name__)
LANDMARKS = 33
AXES = ("x", "y", "z")
LEGACY_ANGLE_PREFIX = "angle_"
PROJECTED_ANGLE_PREFIX = "angle_2d_"
WORLD_ANGLE_PREFIX = "angle_3d_"
ANGLE_PREFIXES = {
    "legacy": LEGACY_ANGLE_PREFIX, "2d": PROJECTED_ANGLE_PREFIX, "3d": WORLD_ANGLE_PREFIX,
}


def angle_family(columns: Iterable[str], prefix: str) -> dict[str, str]:
    """Map logical joint names to column names in one angle space."""
    return {
        column.removeprefix(prefix): column for column in columns
        if column.startswith(prefix)
        and (prefix != LEGACY_ANGLE_PREFIX or not column.startswith((PROJECTED_ANGLE_PREFIX, WORLD_ANGLE_PREFIX)))
    }


@dataclass(frozen=True)
class FeatureBuildResult:
    dataframe: pd.DataFrame
    feature_columns: list[str]
    input_feature_columns: list[str]
    feature_manifest: dict


class FeatureEngine:
    """Build the complete frame feature table from one in-memory DataFrame."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.feature_cfg = cfg.get("features", {})
        self.angle_definitions = cfg.get("angles", {}).get("targets", {})
        self.midpoint_angle_definitions = cfg.get("angles", {}).get("midpoint_targets", {})
        self.distance_definitions = cfg.get("distances", {}).get("targets", {})

    @staticmethod
    def _landmark_array(df: pd.DataFrame, prefix: str = "lm", axes: tuple[str, ...] = AXES) -> np.ndarray:
        values = np.full((len(df), LANDMARKS, len(axes)), np.nan, dtype=float)
        for i in range(LANDMARKS):
            for axis_index, axis in enumerate(axes):
                column = f"{prefix}{i}_{axis}"
                if column in df.columns:
                    values[:, i, axis_index] = pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)
        return values

    @staticmethod
    def _derived_centers(points: np.ndarray) -> dict[str, np.ndarray]:
        hip_center = (points[:, 23, :] + points[:, 24, :]) / 2.0
        shoulder_center = (points[:, 11, :] + points[:, 12, :]) / 2.0
        torso_center = (hip_center + shoulder_center) / 2.0
        knee_center = (points[:, 25, :] + points[:, 26, :]) / 2.0
        ankle_center = (points[:, 27, :] + points[:, 28, :]) / 2.0
        head_center = (points[:, 7, :] + points[:, 8, :]) / 2.0
        return {
            "hip_center": hip_center,
            "shoulder_center": shoulder_center,
            "torso_center": torso_center,
            "knee_center": knee_center,
            "ankle_center": ankle_center,
            "head_center": head_center,
        }

    def projected_angles(self, df: pd.DataFrame, frame_size: tuple[float, float]) -> dict[str, np.ndarray]:
        """Reconstruct the configured angles in video-pixel XY without changing the frame table."""
        return self._projected_angles(self._landmark_array(df, axes=("x", "y")), frame_size, LEGACY_ANGLE_PREFIX)

    def _projected_angles(
        self, xy: np.ndarray, frame_size: tuple[float, float], prefix: str = PROJECTED_ANGLE_PREFIX,
    ) -> dict[str, np.ndarray]:
        if not np.isfinite(frame_size).all() or min(frame_size) <= 0:
            return {}
        # Image X and Y were normalized by different dimensions. Restore both
        # to pixels before taking angles and leave inferred depth out of it.
        return self._calculate_angles(xy * frame_size, prefix=prefix)

    def with_missing_spatial_angles(self, df: pd.DataFrame, frame_size: tuple[float, float]) -> pd.DataFrame:
        """Augment legacy input in memory. A saved family, including its gaps, is authoritative."""
        additions = {}
        if not angle_family(df.columns, PROJECTED_ANGLE_PREFIX):
            additions.update(self._projected_angles(self._landmark_array(df, axes=("x", "y")), frame_size))
        if not angle_family(df.columns, WORLD_ANGLE_PREFIX):
            additions.update(self._calculate_angles(self._landmark_array(df, "world"), prefix=WORLD_ANGLE_PREFIX))
        available = {name: values for name, values in additions.items() if np.isfinite(values).any()}
        return pd.concat([df, pd.DataFrame(available, index=df.index)], axis=1) if available else df

    def _calculate_angles(
        self, points: np.ndarray, centers: dict[str, np.ndarray] | None = None, *, prefix: str = LEGACY_ANGLE_PREFIX,
    ) -> dict[str, np.ndarray]:
        if centers is None:
            centers = self._derived_centers(points)
        regular_targets = {
            name: target for name, target in self.angle_definitions.items()
            if name not in {"torso_vertical", "torso_nose_shoulder_hip"}
        }
        values = vectorized_angles(points, regular_targets)
        midpoint_points = {
            "nose": points[:, 0, :],
            "shoulder_midpoint": centers["shoulder_center"],
            "hip_midpoint": centers["hip_center"],
            "knee_midpoint": centers["knee_center"],
            "ankle_midpoint": centers["ankle_center"],
        }
        if "torso_nose_shoulder_hip" in self.angle_definitions:
            values["torso_nose_shoulder_hip"] = vectorized_point_angle(
                midpoint_points["nose"], midpoint_points["shoulder_midpoint"], midpoint_points["hip_midpoint"]
            )
        for name, target in self.midpoint_angle_definitions.items():
            if len(target) != 3 or any(point_name not in midpoint_points for point_name in target):
                raise ValueError(
                    f"Midpoint angle {name!r} must reference three known points: {sorted(midpoint_points)}"
                )
            values[name] = vectorized_point_angle(*(midpoint_points[point_name] for point_name in target))
        if "torso_vertical" in self.angle_definitions:
            vector = centers["shoulder_center"] - centers["hip_center"]
            if prefix != WORLD_ANGLE_PREFIX:
                vector = vector[:, :2]
            norm = np.linalg.norm(vector, axis=1)
            tilt = np.full(len(points), np.nan, dtype=float)
            valid = np.isfinite(vector).all(axis=1) & (norm > 1e-8)
            tilt[valid] = np.degrees(np.arccos(np.clip(np.abs(vector[valid, 1]) / norm[valid], -1.0, 1.0)))
            values["torso_vertical"] = tilt
        return {f"{prefix}{name}": value for name, value in values.items()}

    @staticmethod
    def _body_geometry(points: np.ndarray, centers: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        shoulder_center = centers["shoulder_center"]
        hip_center = centers["hip_center"]
        knee_center = centers["knee_center"]
        ankle_center = centers["ankle_center"]
        shoulder_width = np.linalg.norm(points[:, 11, :] - points[:, 12, :], axis=1)
        hip_width = np.linalg.norm(points[:, 23, :] - points[:, 24, :], axis=1)
        combined_width = (shoulder_width + hip_width) / 2.0
        torso_length = np.linalg.norm(shoulder_center - hip_center, axis=1)
        torso_vector = shoulder_center - hip_center
        lower_body_vector = knee_center - hip_center
        ankle_vector = ankle_center - knee_center
        return {
            "shoulder_width": shoulder_width,
            "hip_width": hip_width,
            "combined_shoulder_hip_width": combined_width,
            "torso_length": torso_length,
            "torso_vector": torso_vector,
            "lower_body_vector": lower_body_vector,
            "ankle_vector": ankle_vector,
        }

    @staticmethod
    def _normalize(points: np.ndarray, origin: np.ndarray, scale: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        valid = (
            np.isfinite(origin).all(axis=1)
            & np.isfinite(scale)
            & (scale > 1e-8)
            & np.isfinite(points).all(axis=(1, 2))
        )
        output = np.full_like(points, np.nan)
        output[valid] = (points[valid] - origin[valid, None, :]) / scale[valid, None, None]
        return output, valid

    @staticmethod
    def _body_aligned(points: np.ndarray, shoulder_center: np.ndarray, hip_center: np.ndarray, scale: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Experimental rotation normalization using torso and shoulder axes."""
        output = np.full_like(points, np.nan)
        shoulder_vector = points[:, 12, :2] - points[:, 11, :2]
        shoulder_angle = np.arctan2(shoulder_vector[:, 1], shoulder_vector[:, 0])
        torso_vector = shoulder_center[:, :2] - hip_center[:, :2]
        torso_angle = np.arctan2(torso_vector[:, 1], torso_vector[:, 0])
        # Align the shoulder axis to +X; this is intentionally optional because it
        # removes camera/viewpoint orientation information.
        angle = shoulder_angle
        valid = np.isfinite(shoulder_center).all(axis=1) & np.isfinite(hip_center).all(axis=1) & np.isfinite(scale) & (scale > 1e-8)
        valid &= np.isfinite(angle)
        for frame in np.flatnonzero(valid):
            cos_a = np.cos(-angle[frame])
            sin_a = np.sin(-angle[frame])
            rotation = np.array([[cos_a, -sin_a], [sin_a, cos_a]])
            xy = points[frame, :, :2] - shoulder_center[frame, :2]
            output[frame, :, :2] = (xy @ rotation.T) / scale[frame]
            output[frame, :, 2] = (points[frame, :, 2] - shoulder_center[frame, 2]) / scale[frame]
        return output, valid

    @staticmethod
    def _derivative(values: np.ndarray, timestamps: np.ndarray) -> np.ndarray:
        output = np.full_like(values, np.nan, dtype=float)
        if len(values) == 0:
            return output
        dt = np.diff(timestamps, prepend=np.nan)
        if values.ndim == 1:
            delta = np.diff(values, prepend=np.nan)
            valid = np.isfinite(dt) & (dt > 0) & np.isfinite(delta) & np.isfinite(values)
            output[valid] = delta[valid] / dt[valid]
            return output
        delta = np.full_like(values, np.nan, dtype=float)
        delta[1:] = values[1:] - values[:-1]
        valid_dt = np.isfinite(dt) & (dt > 0)
        valid_values = np.isfinite(delta).all(axis=1) & np.isfinite(values).all(axis=1)
        valid = valid_dt & valid_values
        output[valid] = delta[valid] / dt[valid, None]
        return output

    @staticmethod
    def _add_vector_columns(additions: dict[str, np.ndarray], prefix: str, vectors: np.ndarray) -> list[str]:
        columns = []
        for axis_index, axis in enumerate(AXES):
            name = f"{prefix}_{axis}"
            additions[name] = vectors[:, axis_index]
            columns.append(name)
        magnitude = np.linalg.norm(vectors, axis=1)
        additions[f"{prefix}_magnitude"] = magnitude
        columns.append(f"{prefix}_magnitude")
        return columns

    @staticmethod
    def _add_point_columns(additions: dict[str, np.ndarray], prefix: str, points: np.ndarray) -> list[str]:
        """Register a named anatomical point without recalculating it."""
        columns = []
        for axis_index, axis in enumerate(AXES):
            name = f"{prefix}_{axis}"
            additions[name] = points[:, axis_index]
            columns.append(name)
        return columns

    def _normalization_representations(self, points: np.ndarray, centers: dict[str, np.ndarray], geometry: dict[str, np.ndarray]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        representations: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        enabled = self.feature_cfg.get("normalization", {}).get("representations")
        if enabled is None:
            # Backward-compatible configuration maps the old flags to the new baseline.
            if self.feature_cfg.get("normalize_landmarks", True):
                enabled = {"torso_combined_width": True}
            else:
                enabled = {}
        if not self.feature_cfg.get("normalization", {}).get("enabled", self.feature_cfg.get("normalize_landmarks", True)):
            return representations

        mapping = {
            "torso_combined_width": (centers["torso_center"], geometry["combined_shoulder_hip_width"]),
            "hip_centered": (centers["hip_center"], geometry["shoulder_width"]),
            "shoulder_centered": (centers["shoulder_center"], geometry["shoulder_width"]),
            "torso_length": (centers["torso_center"], geometry["torso_length"]),
        }
        for name, is_enabled in enabled.items():
            if not is_enabled:
                continue
            if name == "body_aligned":
                representations[name] = self._body_aligned(points, centers["shoulder_center"], centers["hip_center"], geometry["combined_shoulder_hip_width"])
            elif name in mapping:
                representations[name] = self._normalize(points, *mapping[name])
            else:
                raise ValueError(f"Unsupported normalization representation: {name}")
        return representations

    def build(
        self, frame_df: pd.DataFrame, progress_callback: Callable[[float, str], None] | None = None,
        *, frame_size: tuple[float, float] | None = None,
    ) -> FeatureBuildResult:
        if frame_df.empty:
            raise ValueError("Cannot build features from an empty frame DataFrame.")
        if frame_df.columns.duplicated().any():
            duplicates = frame_df.columns[frame_df.columns.duplicated()].tolist()
            raise ValueError(f"Duplicate input columns detected: {duplicates}")
        if "timestamp_s" not in frame_df.columns:
            raise ValueError("timestamp_s is required for temporal features.")

        df = frame_df.copy()
        raw_points = self._landmark_array(df, "lm")
        world_points = self._landmark_array(df, "world")
        centers = self._derived_centers(raw_points)
        geometry = self._body_geometry(raw_points, centers)
        additions: dict[str, np.ndarray] = {}
        generated_groups: dict[str, list[str]] = {}
        normalized_spaces: dict[str, np.ndarray] = {}
        total_steps = 7
        step = 0

        if self.feature_cfg.get("anatomical_centers", {}).get("enabled", True):
            center_names = ["hip_center", "shoulder_center", "torso_center", "knee_center", "ankle_center"]
            if self.feature_cfg.get("anatomical_centers", {}).get("head", False):
                center_names.append("head_center")
            generated_groups["anatomical_centers"] = []
            for name in center_names:
                generated_groups["anatomical_centers"].extend(self._add_vector_columns(additions, name, centers[name]))
        else:
            generated_groups["anatomical_centers"] = []
        if self.feature_cfg.get("include_anatomical_points", True):
            # These names are explicit aliases over the raw nose and the
            # already-computed bilateral centers. No midpoint is recalculated.
            point_definitions = {
                "nose": raw_points[:, 0, :],
                "shoulder_midpoint": centers["shoulder_center"],
                "hip_midpoint": centers["hip_center"],
                "knee_midpoint": centers["knee_center"],
                "ankle_midpoint": centers["ankle_center"],
            }
            generated_groups["anatomical_points"] = []
            for name, point in point_definitions.items():
                generated_groups["anatomical_points"].extend(
                    self._add_point_columns(additions, name, point)
                )
        else:
            generated_groups["anatomical_points"] = []
        for name in ("shoulder_width", "hip_width", "combined_shoulder_hip_width", "torso_length"):
            additions[name] = geometry[name]
        generated_groups["body_geometry"] = ["shoulder_width", "hip_width", "combined_shoulder_hip_width", "torso_length"]
        if self.feature_cfg.get("body_axes", {}).get("enabled", True):
            generated_groups["body_axes"] = []
            for name in ("torso_vector", "lower_body_vector", "ankle_vector"):
                generated_groups["body_axes"].extend(self._add_vector_columns(additions, name, geometry[name]))
        else:
            generated_groups["body_axes"] = []
        step += 1
        if progress_callback:
            progress_callback(step / total_steps, "Generated anatomical geometry")

        representations = self._normalization_representations(raw_points, centers, geometry)
        generated_groups["normalized_landmarks"] = []
        baseline_alias = bool(self.feature_cfg.get("normalization", {}).get("baseline_alias_n", True))
        for name, (normalized_points, valid) in representations.items():
            normalized_spaces[name] = normalized_points
            prefix = "n" if name == "torso_combined_width" and baseline_alias else {
                "torso_combined_width": "torso_norm_lm",
                "hip_centered": "hip_norm_lm",
                "shoulder_centered": "shoulder_norm_lm",
                "torso_length": "torso_length_norm_lm",
                "body_aligned": "body_aligned_lm",
            }[name]
            cols = []
            for i in range(LANDMARKS):
                for axis_index, axis in enumerate(AXES):
                    column = f"{prefix}{i}_{axis}" if prefix == "n" else f"{prefix}{i}_{axis}"
                    additions[column] = normalized_points[:, i, axis_index]
                    cols.append(column)
            generated_groups["normalized_landmarks"].extend(cols)
        step += 1
        if progress_callback:
            progress_callback(step / total_steps, "Generated configurable normalization")

        if self.feature_cfg.get("use_angles", True):
            angle_columns = self._calculate_angles(raw_points, centers)
            if frame_size is not None:
                angle_columns.update(self._projected_angles(raw_points[:, :, :2], frame_size))
            angle_columns.update(self._calculate_angles(world_points, prefix=WORLD_ANGLE_PREFIX))
            additions.update(angle_columns)
            generated_groups["angles"] = list(angle_columns)
        else:
            generated_groups["angles"] = []
        step += 1
        if progress_callback:
            progress_callback(step / total_steps, "Generated angles")

        if self.feature_cfg.get("use_distances", True):
            distance_space = self.feature_cfg.get("distance_space", "normalized")
            if distance_space == "normalized":
                baseline = normalized_spaces.get("torso_combined_width")
                if baseline is None:
                    raise ValueError("distance_space='normalized' requires the torso_combined_width normalization representation.")
                distance_points = baseline
            elif distance_space == "raw":
                distance_points = raw_points
            elif distance_space == "world":
                distance_points = world_points
            else:
                raise ValueError("distance_space must be 'normalized', 'raw', or 'world'.")
            distance_values = vectorized_distances(distance_points, self.distance_definitions)
            distance_columns = {f"distance_{name}": value for name, value in distance_values.items()}
            additions.update(distance_columns)
            generated_groups["distances"] = list(distance_columns)
        else:
            generated_groups["distances"] = []
        step += 1
        if progress_callback:
            progress_callback(step / total_steps, "Generated distances")

        timestamps = pd.to_numeric(df["timestamp_s"], errors="coerce").to_numpy(dtype=float)
        motion_spaces = self.feature_cfg.get("temporal", {}).get("spaces")
        if motion_spaces is None:
            motion_spaces = ["torso_combined_width"] if normalized_spaces else ["raw"]
        generated_groups["velocity"] = []
        generated_groups["acceleration"] = []
        for space in motion_spaces:
            if space == "raw":
                motion_points = raw_points
                prefix = "lm"
            elif space == "world":
                motion_points = world_points
                prefix = "world"
            else:
                if space not in normalized_spaces:
                    raise ValueError(f"Temporal normalization space is not enabled: {space}")
                motion_points = normalized_spaces[space]
                prefix = "n" if space == "torso_combined_width" and baseline_alias else {
                    "hip_centered": "hip_norm_lm",
                    "shoulder_centered": "shoulder_norm_lm",
                    "torso_length": "torso_length_norm_lm",
                    "body_aligned": "body_aligned_lm",
                    "torso_combined_width": "torso_norm_lm",
                }.get(space, "n")
            velocity = self._derivative(motion_points.reshape(len(motion_points), -1), timestamps).reshape(motion_points.shape)
            if self.feature_cfg.get("use_velocity", True):
                for i in range(LANDMARKS):
                    for axis_index, axis in enumerate(AXES):
                        column = f"{prefix}{i}_v{axis}" if prefix == "n" else f"{prefix}{i}_v{axis}"
                        additions[column] = velocity[:, i, axis_index]
                        generated_groups["velocity"].append(column)
                    magnitude_name = f"{prefix}{i}_speed" if prefix == "n" else f"{prefix}{i}_speed"
                    additions[magnitude_name] = np.linalg.norm(velocity[:, i, :], axis=1)
                    generated_groups["velocity"].append(magnitude_name)
            if self.feature_cfg.get("use_acceleration", True):
                acceleration = self._derivative(velocity.reshape(len(velocity), -1), timestamps).reshape(velocity.shape)
                for i in range(LANDMARKS):
                    for axis_index, axis in enumerate(AXES):
                        column = f"{prefix}{i}_a{axis}" if prefix == "n" else f"{prefix}{i}_a{axis}"
                        additions[column] = acceleration[:, i, axis_index]
                        generated_groups["acceleration"].append(column)
                    magnitude_name = f"{prefix}{i}_acceleration_magnitude"
                    additions[magnitude_name] = np.linalg.norm(acceleration[:, i, :], axis=1)
                    generated_groups["acceleration"].append(magnitude_name)
        step += 1
        if progress_callback:
            progress_callback(step / total_steps, "Generated velocity and acceleration")

        # Raw/world inputs are preserved in the source frame table; the feature
        # selection below determines which representations are model inputs.
        generated = [column for group in generated_groups.values() for column in group]
        additions_df = pd.DataFrame(additions, index=df.index)
        df = pd.concat([df, additions_df], axis=1) if not additions_df.empty else df
        if df.columns.duplicated().any():
            duplicates = df.columns[df.columns.duplicated()].tolist()
            raise ValueError(f"Feature generation created duplicate columns: {duplicates}")

        feature_columns = self.select_model_features(df)
        manifest = self._build_manifest(df, feature_columns, generated, generated_groups)
        LOGGER.info("Feature generation complete: %d model features", len(feature_columns))
        return FeatureBuildResult(df, feature_columns, feature_columns, manifest)

    def select_model_features(self, df: pd.DataFrame) -> list[str]:
        features: list[str] = []
        if self.feature_cfg.get("use_raw_xyz", True):
            features.extend(f"lm{i}_{axis}" for i in range(LANDMARKS) for axis in AXES if f"lm{i}_{axis}" in df.columns)
        if self.feature_cfg.get("use_normalized_xyz", self.feature_cfg.get("normalize_landmarks", True)):
            # Baseline compatibility alias first; additional representations can be
            # selected explicitly through model_input_spaces.
            spaces = self.feature_cfg.get("model_input_spaces", ["torso_combined_width"])
            prefixes = {
                "torso_combined_width": "n",
                "hip_centered": "hip_norm_lm",
                "shoulder_centered": "shoulder_norm_lm",
                "torso_length": "torso_length_norm_lm",
                "body_aligned": "body_aligned_lm",
            }
            for space in spaces:
                prefix = prefixes.get(space)
                if not prefix:
                    continue
                features.extend(
                    f"{prefix}{i}_{axis}" for i in range(LANDMARKS) for axis in AXES
                    if f"{prefix}{i}_{axis}" in df.columns
                )
        if self.feature_cfg.get("use_world_xyz", True):
            features.extend(f"world{i}_{axis}" for i in range(LANDMARKS) for axis in AXES if f"world{i}_{axis}" in df.columns)
        if self.feature_cfg.get("include_anatomical_centers", True):
            for name in ("hip_center", "shoulder_center", "torso_center", "knee_center", "ankle_center"):
                features.extend(f"{name}_{axis}" for axis in AXES if f"{name}_{axis}" in df.columns)
        if self.feature_cfg.get("include_anatomical_points", True):
            for name in ("nose", "shoulder_midpoint", "hip_midpoint", "knee_midpoint", "ankle_midpoint"):
                features.extend(f"{name}_{axis}" for axis in AXES if f"{name}_{axis}" in df.columns)
        if self.feature_cfg.get("include_body_geometry", True):
            features.extend(name for name in ("shoulder_width", "hip_width", "combined_shoulder_hip_width", "torso_length") if name in df.columns)
        if self.feature_cfg.get("include_body_axes", True):
            for name in ("torso_vector", "lower_body_vector", "ankle_vector"):
                features.extend(f"{name}_{axis}" for axis in AXES if f"{name}_{axis}" in df.columns)
                if f"{name}_magnitude" in df.columns:
                    features.append(f"{name}_magnitude")
        if self.feature_cfg.get("use_angles", True):
            angle_names = list(self.angle_definitions) + list(self.midpoint_angle_definitions)
            for space in self.feature_cfg.get("model_angle_spaces", ["legacy"]):
                if space not in ANGLE_PREFIXES:
                    raise ValueError(f"Unknown model angle space {space!r}. Choose legacy, 2d, or 3d.")
                prefix = ANGLE_PREFIXES[space]
                columns = [f"{prefix}{name}" for name in angle_names if f"{prefix}{name}" in df.columns]
                if space != "legacy" and angle_names and len(columns) != len(set(angle_names)):
                    raise ValueError(f"The requested {space} angle family is incomplete. Build features with the required landmarks and video dimensions.")
                features.extend(columns)
        if self.feature_cfg.get("use_distances", True):
            features.extend(f"distance_{name}" for name in self.distance_definitions if f"distance_{name}" in df.columns)
        if self.feature_cfg.get("use_velocity", True):
            features.extend(column for column in df.columns if column.startswith(("n", "lm", "world", "hip_norm", "shoulder_norm", "torso_length_norm", "body_aligned")) and ("_v" in column or column.endswith("_speed")))
        if self.feature_cfg.get("use_acceleration", True):
            features.extend(column for column in df.columns if column.startswith(("n", "lm", "world", "hip_norm", "shoulder_norm", "torso_length_norm", "body_aligned")) and ("_a" in column or "_acceleration_magnitude" in column))
        if not features:
            raise ValueError("No model input features were generated.")
        return list(dict.fromkeys(features))

    def _build_manifest(self, df: pd.DataFrame, feature_columns: list[str], generated: list[str], generated_groups: dict[str, list[str]]) -> dict:
        normalization_cfg = self.feature_cfg.get("normalization", {})
        return {
            "feature_engine": {
                "raw_xyz": bool(self.feature_cfg.get("use_raw_xyz", True)),
                "normalized_xyz": bool(self.feature_cfg.get("use_normalized_xyz", self.feature_cfg.get("normalize_landmarks", True))),
                "world_xyz": bool(self.feature_cfg.get("use_world_xyz", True)),
                "anatomical_centers": bool(self.feature_cfg.get("anatomical_centers", {}).get("enabled", True)),
                "anatomical_points": bool(self.feature_cfg.get("include_anatomical_points", True)),
                "body_axes": bool(self.feature_cfg.get("body_axes", {}).get("enabled", True)),
                "angles": bool(self.feature_cfg.get("use_angles", True)),
                "distances": bool(self.feature_cfg.get("use_distances", True)),
                "velocity": bool(self.feature_cfg.get("use_velocity", True)),
                "acceleration": bool(self.feature_cfg.get("use_acceleration", True)),
            },
            "normalization": normalization_cfg,
            "distance_space": self.feature_cfg.get("distance_space", "normalized"),
            "angle_definitions": self.angle_definitions,
            "midpoint_angle_definitions": self.midpoint_angle_definitions,
            "angle_feature_spaces": {
                space: {
                    "columns": list(angle_family(df.columns, prefix).values()),
                    "units": "degrees",
                    "coordinates": {
                        "legacy": "normalized image XYZ; normalized XY for torso tilt",
                        "2d": "source image pixels XY (normalized x × width, y × height)",
                        "3d": "MediaPipe estimated world XYZ (hip-relative); world Y-axis for torso tilt",
                    }[space],
                }
                for space, prefix in ANGLE_PREFIXES.items() if angle_family(df.columns, prefix)
            },
            "anatomical_point_definitions": {
                "nose": "raw image landmark 0",
                "shoulder_midpoint": "mean(raw image landmarks 11, 12)",
                "hip_midpoint": "mean(raw image landmarks 23, 24)",
                "knee_midpoint": "mean(raw image landmarks 25, 26)",
                "ankle_midpoint": "mean(raw image landmarks 27, 28)",
            },
            "angle_semantics": {
                "torso_nose_shoulder_hip": "angle(nose, shoulder_midpoint, hip_midpoint); vertex=shoulder_midpoint",
                "shoulder_midpoint_hip_midpoint_knee_midpoint": "angle(shoulder_midpoint, hip_midpoint, knee_midpoint); vertex=hip_midpoint",
            },
            "distance_definitions": self.distance_definitions,
            "velocity_definition": "v_t = (x_t - x_(t-1)) / (timestamp_t - timestamp_(t-1)); first/invalid samples => NaN",
            "acceleration_definition": "a_t = (v_t - v_(t-1)) / (timestamp_t - timestamp_(t-1)); insufficient/invalid samples => NaN",
            "feature_groups": generated_groups,
            "generated_columns": generated,
            "feature_count": len(feature_columns),
            "feature_names": feature_columns,
            "label_separation": {"features_are_inputs_only": True, "annotation_source_of_truth": "annotations.json"},
        }


def select_model_features(df: pd.DataFrame, cfg: dict) -> list[str]:
    return FeatureEngine(cfg).select_model_features(df)


def build_features(
    input_path: str | Path, output_path: str | Path, cfg: dict, *, frame_size: tuple[float, float] | None = None,
) -> dict:
    from .storage import load_json, save_parquet_atomic

    path = Path(input_path)
    if frame_size is None and path.stem.endswith("_landmarks"):
        name = path.stem.removesuffix("_landmarks") + "_metadata.json"
        for sidecar in (path.parent.parent / "metadata" / name, path.with_name(name)):
            if sidecar.is_file():
                try:
                    size = load_json(sidecar)["resolution"]
                    candidate = (float(size["width"]), float(size["height"]))
                    if np.isfinite(candidate).all() and min(candidate) > 0:
                        frame_size = candidate
                        break
                except (OSError, ValueError, KeyError, TypeError):
                    LOGGER.warning("Could not read video dimensions from %s", sidecar)
    result = FeatureEngine(cfg).build(pd.read_parquet(path), frame_size=frame_size)
    save_parquet_atomic(result.dataframe, output_path)
    return {"feature_count": len(result.feature_columns), "features": result.feature_columns, "rows": len(result.dataframe), "manifest": result.feature_manifest}
