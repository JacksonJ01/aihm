from __future__ import annotations

from dataclasses import dataclass
import json
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
TORSO_ANGLE_PREFIX = "angle_torso2d_"
REVIEW_PREFIX = "review_"
CROSS_MEAN_PREFIX = "review_cross_mean_"
CROSS_MEAN_SOURCE = "legacy + world + torso2d"
VIEWER_FEATURE_PREFIX = "viewer_"
MEAN_ANGLE_PREFIX = "viewer_mean_"
TIME_COLUMNS = ("timeElapsedS", "timestamp_s", "time_elapsed_s")
ANGLE_PREFIXES = {
    "legacy": LEGACY_ANGLE_PREFIX, "2d": PROJECTED_ANGLE_PREFIX, "3d": WORLD_ANGLE_PREFIX,
}
ANGLE_VERTICES = {
    "angle_left_shoulder": (11,), "angle_right_shoulder": (12,),
    "angle_left_elbow": (13,), "angle_right_elbow": (14,),
    "angle_left_wrist": (15,), "angle_right_wrist": (16,),
    "angle_left_hip": (23,), "angle_right_hip": (24,),
    "angle_left_knee": (25,), "angle_right_knee": (26,),
    "angle_left_ankle": (27,), "angle_right_ankle": (28,),
    "angle_torso_nose_shoulder_hip": (11, 12),
    "angle_torso_vertical": (23, 24),
    "angle_shoulder_midpoint_hip_midpoint_knee_midpoint": (23, 24),
}
REVIEW_LANDMARKS = {
    31: "Left toe index", 32: "Right toe index", 27: "Left ankle", 28: "Right ankle",
    25: "Left knee", 26: "Right knee", 23: "Left hip", 24: "Right hip",
    11: "Left shoulder", 12: "Right shoulder", 13: "Left elbow", 14: "Right elbow",
    15: "Left wrist", 16: "Right wrist", 19: "Left hand index", 20: "Right hand index",
}
REVIEW_DISTANCE_TARGETS = {
    "elbow_to_elbow": (13, 14), "wrist_to_wrist": (15, 16),
    "knee_to_knee": (25, 26), "ankle_to_ankle": (27, 28),
    "left_shoulder_to_wrist": (11, 15), "right_shoulder_to_wrist": (12, 16),
    "left_hip_to_ankle": (23, 27), "right_hip_to_ankle": (24, 28),
}
REVIEW_DISTANCE_AXES = {"legacy": "xyz", "world": "xyz", "torso2d": "xy", "cross_mean": "xy"}


def angle_family(columns: Iterable[str], prefix: str) -> dict[str, str]:
    """Map logical joint names to column names in one angle space."""
    return {
        column.removeprefix(prefix): column for column in columns
        if column.startswith(prefix)
        and (prefix != LEGACY_ANGLE_PREFIX or not column.startswith((PROJECTED_ANGLE_PREFIX, WORLD_ANGLE_PREFIX, TORSO_ANGLE_PREFIX)))
    }


def _consecutive_frames(df: pd.DataFrame) -> np.ndarray:
    valid = np.ones(len(df), dtype=bool)
    if "frame_id" in df:
        frames = pd.to_numeric(df["frame_id"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
        valid[1:] &= np.diff(frames) == 1
    if "pose_present" in df:
        pose = pd.to_numeric(df["pose_present"], errors="coerce").fillna(0).to_numpy() == 1
        valid[1:] &= pose[1:] & pose[:-1]
    if "target_track_id" in df:
        tracks = pd.to_numeric(df["target_track_id"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
        same = (tracks[1:] == tracks[:-1]) | (np.isnan(tracks[1:]) & np.isnan(tracks[:-1]))
        valid[1:] &= same
    valid[:1] = False
    return valid


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
        """Reconstruct absent spatial families and midpoint columns without replacing saved values."""
        additions = {}
        for prefix in ANGLE_PREFIXES.values():
            saved = angle_family(df.columns, prefix)
            rebuild_family = not saved and prefix != LEGACY_ANGLE_PREFIX
            missing_midpoints = {
                name: target for name, target in self.midpoint_angle_definitions.items() if name not in saved
            }
            if not rebuild_family and not missing_midpoints:
                continue
            if prefix == PROJECTED_ANGLE_PREFIX:
                if not np.isfinite(frame_size).all() or min(frame_size) <= 0:
                    continue
                points = self._landmark_array(df, axes=("x", "y"))
                points *= frame_size
            else:
                points = self._landmark_array(df, "world" if prefix == WORLD_ANGLE_PREFIX else "lm")
            if rebuild_family:
                additions.update(self._calculate_angles(points, prefix=prefix))
            else:
                centers = self._derived_centers(points)
                midpoint_angles = self._calculate_midpoint_angles(points, centers, missing_midpoints)
                additions.update({f"{prefix}{name}": angle for name, angle in midpoint_angles.items()})
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
        if "torso_nose_shoulder_hip" in self.angle_definitions:
            values["torso_nose_shoulder_hip"] = vectorized_point_angle(
                points[:, 0, :], centers["shoulder_center"], centers["hip_center"]
            )
        values.update(self._calculate_midpoint_angles(points, centers, self.midpoint_angle_definitions))
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
    def _calculate_midpoint_angles(points: np.ndarray, centers: dict[str, np.ndarray], targets: dict) -> dict[str, np.ndarray]:
        midpoint_points = {
            "nose": points[:, 0, :],
            "shoulder_midpoint": centers["shoulder_center"],
            "hip_midpoint": centers["hip_center"],
            "knee_midpoint": centers["knee_center"],
            "ankle_midpoint": centers["ankle_center"],
        }
        values = {}
        for name, target in targets.items():
            if len(target) != 3 or any(point_name not in midpoint_points for point_name in target):
                raise ValueError(
                    f"Midpoint angle {name!r} must reference three known points: {sorted(midpoint_points)}"
                )
            values[name] = vectorized_point_angle(*(midpoint_points[point_name] for point_name in target))
        return values

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
        dt = np.diff(timestamps).reshape((-1,) + (1,) * (values.ndim - 1))
        delta = np.diff(values, axis=0)
        valid = np.isfinite(delta)
        if values.ndim > 1:
            # Keep XYZ together for each landmark. A missing joint must not
            # invalidate an unrelated joint's position or motion.
            valid = valid.all(axis=-1, keepdims=True)
        np.divide(delta, dt, out=output[1:], where=valid & np.isfinite(dt) & (dt > 0))
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
        consecutive = _consecutive_frames(df)
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
            velocity = self._derivative(motion_points, timestamps)
            velocity[~consecutive] = np.nan
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
                acceleration = self._derivative(velocity, timestamps)
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
        prepared = self.prepare_review_features(df, frame_size) if frame_size else with_viewer_features(df)
        generated_groups["viewer"] = list(prepared.columns.difference(df.columns, sort=False))
        generated.extend(generated_groups["viewer"])
        df = prepared
        manifest = self._build_manifest(df, feature_columns, generated, generated_groups)
        LOGGER.info("Feature generation complete: %d model features", len(feature_columns))
        return FeatureBuildResult(df, feature_columns, feature_columns, manifest)

    def prepare_review_features(self, df: pd.DataFrame, frame_size: tuple[float, float]) -> pd.DataFrame:
        """Build the saved review schema from native landmarks and timestamps."""
        if df.empty or not np.isfinite(frame_size).all() or min(frame_size) <= 0:
            raise ValueError("Review preparation requires frames and valid video dimensions.")
        time_name = next(name for name in TIME_COLUMNS if name in df)
        times = df[time_name].to_numpy(dtype=float)
        consecutive = _consecutive_frames(df)

        def rate(values):
            result = self._derivative(values, times)
            result[~consecutive] = np.nan
            return result

        additions = {}

        def save(name, values):
            if name not in df:
                additions[name] = values

        def torso_scaled_xy(points, centers):
            hip = centers["hip_center"][:, :2]
            torso = centers["shoulder_center"][:, :2] - hip
            scale = np.linalg.norm(torso, axis=1)
            valid = np.isfinite(scale) & (scale > 1e-6)
            normalized = np.full_like(points[:, :, :2], np.nan)
            normalized[valid] = (points[valid, :, :2] - hip[valid, None]) / scale[valid, None, None]
            return normalized, np.where(valid, scale, np.nan)

        def save_motion(prefix, points, centers):
            named = {f"lm{i}": points[:, i] for i in range(LANDMARKS)}
            named.update({f"{name}_midpoint": centers[f"{name}_center"]
                          for name in ("shoulder", "hip", "knee", "ankle")})
            for name, position in named.items():
                base = f"{prefix}{name}_"
                velocity = rate(position)
                acceleration = rate(velocity)
                for i, axis in enumerate(AXES[:position.shape[1]]):
                    save(f"{base}{axis}", position[:, i])
                    save(f"{base}v{axis}", velocity[:, i])
                    save(f"{base}a{axis}", acceleration[:, i])
                save(f"{base}speed", np.linalg.norm(velocity, axis=1))

        image = self._landmark_array(df, "lm")
        world = self._landmark_array(df, "world")
        pixels = image[:, :, :2] * frame_size
        centers = self._derived_centers(pixels)
        torso = centers["shoulder_center"] - centers["hip_center"]
        normalized, scale = torso_scaled_xy(pixels, centers)
        save("review_projected_torso_length_px", scale)
        for i, axis in enumerate("xy"):
            save(f"review_projected_torso_vector_{axis}", torso[:, i])
            for point in ("shoulder", "hip"):
                save(f"review_projected_{point}_midpoint_{axis}", centers[f"{point}_center"][:, i])

        for name, values in self._projected_angles(image[:, :, :2], frame_size).items():
            save(name, values)
        families = []
        mean_inputs = []
        for source, prefix, points in (("legacy", LEGACY_ANGLE_PREFIX, image),
                                       ("world", WORLD_ANGLE_PREFIX, world),
                                       ("torso2d", TORSO_ANGLE_PREFIX, normalized)):
            centers = self._derived_centers(points)
            angles = self._calculate_angles(points, centers, prefix=prefix)
            source_angles = {}
            for name, values in angles.items():
                save(name, values)
                source_angles[name.removeprefix(prefix)] = df[name].to_numpy(dtype=float) if name in df else values
                omega = rate(source_angles[name.removeprefix(prefix)])
                save(f"review_omega_{name}", omega)
                save(f"review_alpha_{name}", rate(omega))
            families.append(source_angles)
            targets = {**self.distance_definitions, **REVIEW_DISTANCE_TARGETS}
            for name, values in vectorized_distances(points, targets).items():
                save(f"review_{source}_distance_{name}", values)
            save_motion(f"review_{source}_", points, centers)
            mean_inputs.append(points if source == "torso2d" else torso_scaled_xy(points, centers)[0])

        # All three sources share XY only. Align the hip origin and torso scale
        # within each representation before taking the component-wise mean.
        mean_xy = (mean_inputs[0] + mean_inputs[1] + mean_inputs[2]) / 3
        mean_xy[~np.isfinite(mean_xy).all(axis=2)] = np.nan
        save_motion(CROSS_MEAN_PREFIX, mean_xy, self._derived_centers(mean_xy))

        for name in sorted(set.intersection(*(set(family) for family in families))):
            samples = np.stack([family[name] for family in families])
            counts = np.isfinite(samples).sum(axis=0).astype(np.uint8)
            valid = counts == 3
            mean = np.full(len(df), np.nan)
            mean[valid] = samples[:, valid].mean(axis=0)
            column = f"{CROSS_MEAN_PREFIX}angle_{name}"
            save(column, mean)
            save(f"{column}_source_count", counts)
            omega = rate(mean)
            save(f"review_omega_{column}", omega)
            save(f"review_alpha_{column}", rate(omega))

        prepared = pd.concat([df, pd.DataFrame(additions, index=df.index)], axis=1) if additions else df
        distances = self.prepare_review_distances(prepared)
        return pd.concat([prepared, distances], axis=1) if not distances.empty else prepared

    @staticmethod
    def prepare_review_distances(df: pd.DataFrame) -> pd.DataFrame:
        """Compute missing distance measurements from saved positions or distances."""
        times = df[next(name for name in TIME_COLUMNS if name in df)].to_numpy(dtype=float)
        consecutive = _consecutive_frames(df)

        def derivative(values):
            result = FeatureEngine._derivative(values, times)
            result[~consecutive] = np.nan
            return result

        additions = {}
        for source, axes in REVIEW_DISTANCE_AXES.items():
            for name, (first, second) in REVIEW_DISTANCE_TARGETS.items():
                distance = f"review_{source}_distance_{name}"
                rate = f"review_{source}_distance_rate_{name}"
                acceleration = f"review_{source}_distance_acceleration_{name}"
                if acceleration in df and rate in df and distance in df:
                    continue
                if distance not in df:
                    columns = [f"review_{source}_lm{index}_{axis}" for index in (first, second) for axis in axes]
                    if any(column not in df for column in columns):
                        continue
                    left, right = np.split(df[columns].to_numpy(dtype=float), 2, axis=1)
                    additions[distance] = np.linalg.norm(left - right, axis=1)
                if rate not in df:
                    values = df[distance].to_numpy(dtype=float) if distance in df else additions[distance]
                    additions[rate] = derivative(values)
                if acceleration not in df:
                    velocity = df[rate].to_numpy(dtype=float) if rate in df else additions[rate]
                    additions[acceleration] = derivative(velocity)
        return pd.DataFrame(additions, index=df.index)

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


def review_schema_metadata(columns: Iterable[str]) -> dict[bytes, bytes]:
    """Embed source, feature and unit information with the frame table."""
    angle_prefixes = ((TORSO_ANGLE_PREFIX, "torso2d"), (PROJECTED_ANGLE_PREFIX, "pixels"),
                      (WORLD_ANGLE_PREFIX, "world"), (LEGACY_ANGLE_PREFIX, "legacy"))
    units = {"legacy": "image units", "world": "m", "torso2d": "torso lengths", "pixels": "px",
             CROSS_MEAN_SOURCE: "torso lengths"}
    result = {}
    for name in columns:
        field = name
        measurement = "angle"
        if name.startswith("review_omega_"):
            field = name.removeprefix("review_omega_")
            measurement = "angular velocity"
        elif name.startswith("review_alpha_"):
            field = name.removeprefix("review_alpha_")
            measurement = "angular acceleration"
        if field.startswith(f"{CROSS_MEAN_PREFIX}angle_"):
            joint = field.removeprefix(f"{CROSS_MEAN_PREFIX}angle_")
            source = CROSS_MEAN_SOURCE
            if joint.endswith("_source_count"):
                joint = joint.removesuffix("_source_count")
                measurement = "valid source count"
        else:
            match = next(((prefix, source) for prefix, source in angle_prefixes if field.startswith(prefix)), None)
            if match is None:
                if not name.startswith(REVIEW_PREFIX):
                    continue
                if name.startswith(CROSS_MEAN_PREFIX):
                    source, feature = CROSS_MEAN_SOURCE, name.removeprefix(CROSS_MEAN_PREFIX)
                else:
                    source, _, feature = name.removeprefix(REVIEW_PREFIX).partition("_")
                    source = "pixels" if source == "projected" else source
                joint, _, axis = feature.rpartition("_")
                if feature.startswith("distance_rate_"):
                    measurement = "distance rate"
                    joint = feature.removeprefix("distance_rate_")
                elif feature.startswith("distance_acceleration_"):
                    measurement = "distance acceleration"
                    joint = feature.removeprefix("distance_acceleration_")
                elif feature.startswith("distance_") or feature == "torso_length_px":
                    measurement = "distance"
                    joint = feature.removeprefix("distance_")
                elif axis in ("vx", "vy", "vz", "speed"):
                    measurement = "speed" if axis == "speed" else "linear velocity"
                elif axis in ("ax", "ay", "az"):
                    measurement = "linear acceleration"
                else:
                    measurement = "position"
                unit = units[source]
                suffix = {"speed": "/s", "linear velocity": "/s", "linear acceleration": "/s²",
                          "distance rate": "/s", "distance acceleration": "/s²"}.get(measurement, "")
                result[name] = {"source": source, "point": joint, "measurement": measurement, "axis": axis, "unit": unit + suffix}
                continue
            prefix, source = match
            joint = field.removeprefix(prefix)
        unit = {"angle": "°", "angular velocity": "°/s", "angular acceleration": "°/s²", "valid source count": "count"}[measurement]
        result[name] = {"source": source, "joint": joint, "measurement": measurement, "unit": unit}
    return {b"aihumo.review_schema": json.dumps({"version": 4, "columns": result}).encode("utf-8")}


def with_viewer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare graph readings in bulk, retaining saved samples and source gaps."""
    time_column = next((name for name in TIME_COLUMNS if name in df), None)
    if time_column is None or df.empty:
        return df
    families = [angle_family(df.columns, prefix) for prefix in ANGLE_PREFIXES.values()]
    joints = sorted({joint for family in families for joint in family})
    additions: dict[str, np.ndarray] = {}

    def numeric(column: str) -> np.ndarray:
        if column in additions:
            return additions[column]
        return pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)

    timestamps = numeric(time_column)
    consecutive = _consecutive_frames(df)

    def derivative(values: np.ndarray) -> np.ndarray:
        result = FeatureEngine._derivative(values, timestamps)
        result[~consecutive] = np.nan
        return result

    for joint in joints:
        key = f"{LEGACY_ANGLE_PREFIX}{joint}"
        angles = [family[joint] for family in families if joint in family]
        if len(angles) == len(families):
            mean_column = f"{MEAN_ANGLE_PREFIX}{key}"
            if mean_column not in df:
                samples = np.stack([numeric(column) for column in angles])
                valid = np.isfinite(samples).all(axis=0)
                mean = np.full(len(df), np.nan)
                mean[valid] = samples[:, valid].mean(axis=0)
                additions[mean_column] = mean
            angles.append(mean_column)

        for column in angles:
            velocity = f"viewer_omega_{column}"
            acceleration = f"viewer_alpha_{column}"
            if velocity not in df:
                additions[velocity] = derivative(numeric(column))
            if acceleration not in df:
                additions[acceleration] = derivative(numeric(velocity))

        landmarks = ANGLE_VERTICES.get(key)
        if not landmarks:
            continue
        for space in ("world", "lm"):
            position_columns = [f"viewer_{space}_{key}_{axis}" for axis in AXES]
            velocity_columns = [f"viewer_world_{key}_v{axis}" for axis in AXES]
            acceleration_columns = [f"viewer_world_{key}_a{axis}" for axis in AXES]
            speed_column = f"viewer_world_{key}_speed"
            outputs = position_columns if space == "lm" else [
                *position_columns, *velocity_columns, *acceleration_columns, speed_column,
            ]
            if all(column in df for column in outputs):
                continue
            inputs = [[f"{space}{landmark}_{axis}" for axis in AXES] for landmark in landmarks]
            if not all(column in df for point in inputs for column in point):
                continue
            position = np.mean([np.column_stack([numeric(column) for column in point]) for point in inputs], axis=0)
            position[~np.isfinite(position).all(axis=1)] = np.nan
            for column, values in zip(position_columns, position.T):
                if column not in df:
                    additions[column] = values
            if space == "world":
                velocity = derivative(np.column_stack([numeric(column) for column in position_columns]))
                for column, values in zip(velocity_columns, velocity.T):
                    if column not in df:
                        additions[column] = values
                velocity = np.column_stack([numeric(column) for column in velocity_columns])
                acceleration = derivative(velocity)
                for column, values in zip(acceleration_columns, acceleration.T):
                    if column not in df:
                        additions[column] = values
                if speed_column not in df:
                    additions[speed_column] = np.linalg.norm(velocity, axis=1)

    return pd.concat([df, pd.DataFrame(additions, index=df.index)], axis=1) if additions else df


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
    save_parquet_atomic(result.dataframe, output_path, metadata=review_schema_metadata(result.dataframe.columns))
    return {"feature_count": len(result.feature_columns), "features": result.feature_columns, "rows": len(result.dataframe), "manifest": result.feature_manifest}
