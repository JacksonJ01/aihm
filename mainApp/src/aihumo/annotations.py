from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .metadata import utc_now_iso
from .storage import load_json, save_json_atomic, save_parquet_atomic

SCHEMA_VERSION = "1.5"
# ``form_interval`` is a sibling overlay, not a parent in the exercise
# hierarchy.  It can overlap an activity, set, repetition, or phase range and
# stores the observed tracking/form issue for only the frames where it occurs.
# ``general`` remains the stable storage ID for the UI's ``Other interval`` so
# older annotation files continue to load without being rewritten.
ANNOTATION_TYPES = {"activity_state", "set", "rep", "phase", "form_interval", "general"}
ACTIVITY_STATES = {"idle", "transition", "active"}
# Annotation phases are intentionally compact and exercise-agnostic.  Older
# files may contain top/bottom/transition; migration below maps those legacy
# values to the single hold state without changing their frame ranges.
PHASES = {"none", "eccentric", "concentric", "hold"}
UNKNOWN = "unknown"


def _canonical_value_list(value: Any, *, none_values: set[str] | None = None) -> list[str]:
    """Normalize legacy scalar or comma-separated values to a stable list.

    Older annotation files stored issue type and category as one string.  The
    editor now supports multiple selections, so JSON uses lists while loading
    remains backward-compatible with those older scalar files.
    """
    none_values = {"", "N/A", "none"} if none_values is None else none_values
    if value is None:
        return []
    raw_values = value.split(",") if isinstance(value, str) else value
    if not isinstance(raw_values, (list, tuple, set)):
        raw_values = [raw_values]
    result: list[str] = []
    for raw_value in raw_values:
        text = str(raw_value).strip()
        if text and text not in none_values and text not in result:
            result.append(text)
    return result


def _migrate_annotation(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy v1.x fields without changing the underlying range."""
    out = dict(item)
    if "activity_state" not in out:
        legacy_activity = out.get("activity")
        if legacy_activity in ACTIVITY_STATES:
            out["activity_state"] = legacy_activity
        elif legacy_activity in {"exercise", "strength_training"}:
            out["activity_state"] = "active"
        elif legacy_activity:
            out["activity_state"] = "active"
    if "annotation_type" not in out:
        if out.get("activity_state") in ACTIVITY_STATES and not any(
            out.get(key) is not None for key in ("rep_id", "set_id", "phase")
        ):
            out["annotation_type"] = "activity_state"
        elif out.get("phase") not in (None, "none"):
            out["annotation_type"] = "phase"
        elif out.get("rep_id") is not None:
            out["annotation_type"] = "rep"
        elif out.get("set_id") is not None:
            out["annotation_type"] = "set"
        else:
            out["annotation_type"] = "general"
    out.pop("activity", None)
    return out


def _canonical_annotation(annotation: dict[str, Any]) -> dict[str, Any]:
    out = _migrate_annotation(annotation)
    out["annotation_type"] = str(out.get("annotation_type", "general"))
    if out["annotation_type"] not in ANNOTATION_TYPES:
        raise ValueError(f"Unsupported annotation_type: {out['annotation_type']}")
    if out.get("phase") is None:
        out["phase"] = "none"
    if out.get("phase") in {"top", "bottom", "transition"}:
        out["phase"] = "hold"
    if out.get("form_label") is None:
        out["form_label"] = "unlabeled"
    # Camera angle is an Activity-interval property.  Child rows inherit it
    # through the resolved frame context rather than storing competing values.
    if out["annotation_type"] != "activity_state":
        out["camera_angle"] = None
    if out.get("camera_angle") is not None:
        out["camera_angle"] = str(out["camera_angle"])
    out["issue_type"] = _canonical_value_list(out.get("issue_type"))
    out["error_category"] = _canonical_value_list(out.get("error_category"))
    out["affected_joints"] = _canonical_value_list(out.get("affected_joints"))
    if out.get("form_score") is not None:
        out["form_score"] = float(out["form_score"])
    return out


@dataclass
class AnnotationState:
    """Source-of-truth annotation document with crash-safe persistence."""

    metadata: dict[str, Any]
    annotations: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    status: str = "in_progress"
    last_annotation_id: str | None = None
    last_segment_id: str | None = None
    last_completed_frame: int | None = None
    current_context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new(cls, metadata: dict[str, Any]) -> "AnnotationState":
        return cls(metadata=dict(metadata))

    @classmethod
    def load(cls, path: str | Path, metadata: dict[str, Any] | None = None) -> "AnnotationState":
        return cls.from_document(load_json(path), metadata)

    @classmethod
    def from_document(cls, document: dict[str, Any], metadata: dict[str, Any] | None = None) -> "AnnotationState":
        stored_metadata = dict(metadata or {})
        stored_metadata.update({
            key: document.get(key)
            for key in (
                "session_id", "video_id", "source_video", "processed_video",
                "features_parquet", "annotator", "participant_id", "camera_id",
            )
            if document.get(key) is not None
        })
        session = document.get("annotation_session", {})
        progress = session.get("progress", {})
        annotations = [_canonical_annotation(item) for item in document.get("annotations", [])]
        context = dict(progress.get("current_context") or {})
        state = cls(
            metadata=stored_metadata,
            annotations=annotations,
            created_at=session.get("created_at", document.get("created_at", utc_now_iso())),
            updated_at=session.get("updated_at", document.get("updated_at", utc_now_iso())),
            status=session.get("status", "in_progress"),
            last_annotation_id=progress.get("last_annotation_id"),
            last_segment_id=progress.get("last_segment_id"),
            last_completed_frame=progress.get("last_completed_frame"),
            current_context=context,
        )
        return state

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.metadata.get("session_id"),
            "video_id": self.metadata.get("video_id"),
            "participant_id": self.metadata.get("participant_id"),
            "camera_id": self.metadata.get("camera_id"),
            "source_video": self.metadata.get("source_video"),
            "processed_video": self.metadata.get("processed_video"),
            "features_parquet": self.metadata.get("features_parquet"),
            "annotator": self.metadata.get("annotator", self.metadata.get("operator")),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "annotation_schema": {
                "annotation_types": sorted(ANNOTATION_TYPES),
                "activity_states": sorted(ACTIVITY_STATES),
                "phases": sorted(PHASES),
                "camera_angle_owner": "activity_state",
                "ground_truth_source": "annotations",
            },
            "annotation_session": {
                "status": self.status,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "progress": {
                    "last_annotation_id": self.last_annotation_id,
                    "last_segment_id": self.last_segment_id,
                    "last_completed_frame": self.last_completed_frame,
                    "current_context": self.current_context,
                },
            },
            "annotations": self.annotations,
        }

    def _sort_annotations(self) -> None:
        """Order rows as a readable hierarchy without changing stable IDs."""

        def contains(parent: dict[str, Any], child: dict[str, Any]) -> bool:
            return (
                int(parent.get("start_frame", 0)) <= int(child.get("start_frame", 0))
                and int(child.get("end_frame", 0)) <= int(parent.get("end_frame", 0))
                and parent is not child
            )

        def parent_for(item: dict[str, Any], annotation_type: str) -> dict[str, Any] | None:
            candidates = [
                candidate for candidate in self.annotations
                if candidate.get("annotation_type") == annotation_type and contains(candidate, item)
            ]
            return min(
                candidates,
                key=lambda candidate: (
                    int(candidate.get("end_frame", 0)) - int(candidate.get("start_frame", 0)),
                    int(candidate.get("start_frame", 0)),
                    str(candidate.get("annotation_id", "")),
                ),
                default=None,
            )

        def key(item: dict[str, Any]) -> tuple:
            kind = str(item.get("annotation_type", "general"))
            activity = item if kind == "activity_state" else parent_for(item, "activity_state")
            root_start = int((activity or item).get("start_frame", 0))
            root_end = int((activity or item).get("end_frame", 0))
            root_id = str((activity or item).get("annotation_id", ""))
            start = int(item.get("start_frame", 0))
            end = int(item.get("end_frame", 0))

            if kind == "general":
                return (start, 0, end, root_id)
            if kind == "activity_state":
                return (root_start, 1, start, end, root_id)
            if kind == "set":
                return (root_start, 2, start, end, root_id)
            if kind == "rep":
                parent = parent_for(item, "set") or item
                return (root_start, 3, int(parent.get("start_frame", start)), start, end, root_id)
            if kind == "phase":
                parent = parent_for(item, "rep") or item
                return (root_start, 4, int(parent.get("start_frame", start)), start, end, root_id)
            # Form intervals are overlays.  Keep them after the hierarchy
            # rows that share their activity root.
            parent = (
                parent_for(item, "phase")
                or parent_for(item, "rep")
                or parent_for(item, "set")
                or activity
                or item
            )
            return (root_start, 5, int(parent.get("start_frame", start)), start, end, root_id)

        self.annotations.sort(key=key)

    def add(self, annotation: dict[str, Any]) -> dict[str, Any]:
        canonical = _canonical_annotation(annotation)
        self.annotations.append(canonical)
        self._sort_annotations()
        self._update_progress(canonical)
        return canonical

    def replace(self, annotation_id: str, annotation: dict[str, Any]) -> None:
        canonical = _canonical_annotation(annotation)
        for index, existing in enumerate(self.annotations):
            if existing.get("annotation_id") == annotation_id:
                self.annotations[index] = canonical
                self._sort_annotations()
                self._recalculate_progress()
                return
        raise KeyError(f"Unknown annotation_id: {annotation_id}")

    def remove(self, annotation_id: str) -> dict[str, Any]:
        """Remove one annotation and recompute resumable progress metadata.

        The GUI performs hierarchy checks before calling this method. Keeping
        deletion here makes the mutation explicit and prevents a UI-only list
        edit from leaving ``last_annotation_id`` or ``last_completed_frame``
        pointing at an annotation that no longer exists.
        """
        for index, existing in enumerate(self.annotations):
            if existing.get("annotation_id") == annotation_id:
                removed = self.annotations.pop(index)
                self._sort_annotations()
                self.updated_at = utc_now_iso()
                self._recalculate_progress()
                return removed
        raise KeyError(f"Unknown annotation_id: {annotation_id}")

    def set_context(
        self,
        *,
        activity_state: str | None = None,
        camera_angle: str | None = None,
        exercise: str | None = None,
        set_id: int | None = None,
        rep_id: int | None = None,
        phase: str | None = None,
    ) -> None:
        if activity_state is not None and activity_state not in ACTIVITY_STATES:
            raise ValueError(f"Unsupported activity state: {activity_state}")
        self.current_context = {
            **self.current_context,
            "activity_state": activity_state if activity_state is not None else self.current_context.get("activity_state"),
            "camera_angle": camera_angle if camera_angle is not None else self.current_context.get("camera_angle"),
            "exercise": exercise if exercise is not None else self.current_context.get("exercise", ""),
            "set_id": set_id if set_id is not None else self.current_context.get("set_id"),
            "rep_id": rep_id if rep_id is not None else self.current_context.get("rep_id"),
            "phase": phase if phase is not None else self.current_context.get("phase"),
        }
        self.updated_at = utc_now_iso()

    def _update_progress(self, annotation: dict[str, Any]) -> None:
        self.updated_at = utc_now_iso()
        self.last_annotation_id = annotation.get("annotation_id")
        self.last_segment_id = annotation.get("segment_id")
        self.last_completed_frame = int(annotation["end_frame"])
        self.current_context = {
            "activity_state": annotation.get("activity_state"),
            "camera_angle": annotation.get("camera_angle") if annotation.get("annotation_type") == "activity_state" else self.current_context.get("camera_angle"),
            "exercise": annotation.get("exercise") or self.current_context.get("exercise", ""),
            "set_id": annotation.get("set_id") if annotation.get("set_id") is not None else self.current_context.get("set_id"),
            "rep_id": annotation.get("rep_id") if annotation.get("rep_id") is not None else self.current_context.get("rep_id"),
            "phase": annotation.get("phase") if annotation.get("phase") not in (None, "none") else self.current_context.get("phase"),
        }

    def _recalculate_progress(self) -> None:
        if not self.annotations:
            self.updated_at = utc_now_iso()
            self.last_annotation_id = None
            self.last_segment_id = None
            self.last_completed_frame = None
            self.current_context = {}
            return
        last = max(self.annotations, key=lambda item: int(item.get("end_frame", -1)))
        self._update_progress(last)

    def next_annotation_id(self) -> str:
        numbers = []
        for item in self.annotations:
            value = str(item.get("annotation_id", ""))
            if value.startswith("A") and value[1:].isdigit():
                numbers.append(int(value[1:]))
        return f"A{(max(numbers) + 1 if numbers else 1):05d}"

    def next_segment_id(self) -> str:
        video_id = str(self.metadata.get("video_id", "VIDEO"))
        prefix = f"{video_id}_SEG"
        numbers = []
        for item in self.annotations:
            value = str(item.get("segment_id", ""))
            if value.startswith(prefix) and value[len(prefix):].isdigit():
                numbers.append(int(value[len(prefix):]))
        return f"{prefix}{(max(numbers) + 1 if numbers else 1):04d}"

    def next_set_id(self) -> int:
        values = [int(item["set_id"]) for item in self.annotations if item.get("set_id") is not None]
        return max(values) + 1 if values else 1

    def next_rep_id(self, set_id: int | None) -> int:
        if set_id is None:
            raise ValueError("set_id is required to assign a repetition number")
        values = [
            int(item["rep_id"])
            for item in self.annotations
            if item.get("set_id") == set_id and item.get("rep_id") is not None
        ]
        return max(values) + 1 if values else 1

    def save(self, json_path: str | Path, parquet_path: str | Path | None = None) -> None:
        self.updated_at = utc_now_iso()
        document = self.to_document()
        frame_count = self._frame_count_from_annotations()
        validate_annotations(document, frame_count)
        save_json_atomic(document, json_path)
        if parquet_path is not None:
            save_annotation_parquet(document, parquet_path)

    def _frame_count_from_annotations(self) -> int:
        if not self.annotations:
            return 2**31 - 1
        return max(int(item["end_frame"]) for item in self.annotations) + 1


def load_annotation_file(path: str | Path) -> dict:
    return load_json(path)


def build_annotation_document(*, metadata: dict, annotations: list[dict], annotator: str | None = None) -> dict:
    state = AnnotationState.new(metadata)
    for annotation in annotations:
        state.add(annotation)
    if annotator:
        state.metadata["annotator"] = annotator
    return state.to_document()


def annotation_to_dataframe(document: dict) -> pd.DataFrame:
    annotations = [_canonical_annotation(item) for item in document.get("annotations", [])]
    columns = [
        "annotation_id", "segment_id", "annotation_type", "start_frame", "end_frame",
        "start_time_s", "end_time_s", "duration_s", "activity_state", "exercise",
        "camera_angle",
        "phase", "rep_id", "set_id", "form_label", "form_score", "error_category", "notes",
        "issue_type", "affected_joints",
    ]
    rows = pd.DataFrame(annotations)
    for column in columns:
        if column not in rows.columns:
            rows[column] = pd.NA
    rows = rows[columns]
    for column in ("issue_type", "error_category", "affected_joints"):
        if column in rows.columns:
            rows[column] = rows[column].apply(
                lambda value: ",".join(str(item) for item in value)
                if isinstance(value, (list, tuple)) else value
            )
    rows.insert(0, "schema_version", document.get("schema_version", SCHEMA_VERSION))
    rows.insert(1, "session_id", document.get("session_id"))
    rows.insert(2, "video_id", document.get("video_id"))
    rows.insert(3, "participant_id", document.get("participant_id"))
    rows.insert(4, "camera_id", document.get("camera_id"))
    return rows


def save_annotation_parquet(document: dict, path: str | Path) -> None:
    save_parquet_atomic(annotation_to_dataframe(document), path)


def save_annotations(document: dict, json_path: str | Path, parquet_path: str | Path) -> None:
    save_json_atomic(document, json_path)
    save_annotation_parquet(document, parquet_path)


def annotation_to_frame_targets(
    df: pd.DataFrame,
    document: dict,
    *,
    boundary_radius_frames: int = 0,
) -> pd.DataFrame:
    """Create a temporary labeled frame table for dataset construction only.

    Labels are never written back into the immutable feature Parquet. Activity-state
    segments form the broad timeline layer; rep/phase annotations may overlap them.
    A small boundary radius can turn a one-frame rep boundary into a trainable local
    target band without changing the underlying annotation range.
    """
    out = df.copy()
    out["activity_state_label"] = UNKNOWN
    out["exercise_label"] = UNKNOWN
    out["phase_label"] = UNKNOWN
    out["rep_id_target"] = -1
    out["set_id_target"] = -1
    out["form_label"] = UNKNOWN
    out["form_score_target"] = np.nan
    out["rep_boundary_label"] = 0

    boundary_radius_frames = max(0, int(boundary_radius_frames))
    annotations = [_canonical_annotation(item) for item in document.get("annotations", [])]
    annotations.sort(key=lambda item: (int(item["start_frame"]), int(item["end_frame"])))
    frame_values = pd.to_numeric(out["frame_id"], errors="coerce")

    for item in annotations:
        start = int(item["start_frame"])
        end = int(item["end_frame"])
        mask = (frame_values >= start) & (frame_values <= end)
        annotation_type = item.get("annotation_type", "general")
        state = item.get("activity_state")
        # Only broad Activity/Other layers produce the frame-level activity
        # target.  Child activity values remain useful annotation metadata but
        # cannot overwrite the parent Activity timeline.
        if state in ACTIVITY_STATES and annotation_type in {"activity_state", "general"}:
            out.loc[mask, "activity_state_label"] = state
        if item.get("exercise"):
            out.loc[mask, "exercise_label"] = str(item["exercise"])
        if item.get("phase") not in (None, "none"):
            out.loc[mask, "phase_label"] = str(item["phase"])
        if item.get("rep_id") is not None:
            out.loc[mask, "rep_id_target"] = int(item["rep_id"])
        if item.get("set_id") is not None:
            out.loc[mask, "set_id_target"] = int(item["set_id"])
        if item.get("form_label") not in (None, "unlabeled"):
            out.loc[mask, "form_label"] = str(item["form_label"])
        if item.get("form_score") is not None:
            out.loc[mask, "form_score_target"] = float(item["form_score"])
        if annotation_type == "rep":
            start_mask = (frame_values >= start - boundary_radius_frames) & (frame_values <= start + boundary_radius_frames)
            end_mask = (frame_values >= end - boundary_radius_frames) & (frame_values <= end + boundary_radius_frames)
            out.loc[start_mask | end_mask, "rep_boundary_label"] = 1

    return out


def annotation_to_frame_mask(df: pd.DataFrame, annotation: dict[str, Any]) -> pd.DataFrame:
    """Backward-compatible alias for the temporary frame-target table."""
    # The target builder consumes a document with an ``annotations`` list;
    # callers of this legacy helper pass one annotation item directly.
    out = annotation_to_frame_targets(df, {"annotations": [annotation]})
    out["activity_label"] = out["activity_state_label"]
    return out


def build_rep_summary(document: dict) -> list[dict[str, Any]]:
    """Return a derived repetition summary; never treated as annotation truth."""
    groups: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for item in document.get("annotations", []):
        item = _canonical_annotation(item)
        if item.get("rep_id") is None:
            continue
        key = (item.get("set_id"), item.get("rep_id"), item.get("exercise") or "")
        record = groups.setdefault(key, {
            "set_id": item.get("set_id"),
            "rep_id": item.get("rep_id"),
            "exercise": item.get("exercise") or None,
            "start_frame": int(item["start_frame"]),
            "end_frame": int(item["end_frame"]),
            "phases": [],
            "form_labels": [],
            "form_scores": [],
        })
        record["start_frame"] = min(record["start_frame"], int(item["start_frame"]))
        record["end_frame"] = max(record["end_frame"], int(item["end_frame"]))
        phase = item.get("phase")
        if phase and phase != "none" and phase not in record["phases"]:
            record["phases"].append(phase)
        if item.get("form_label") not in (None, "unlabeled"):
            record["form_labels"].append(item["form_label"])
        if item.get("form_score") is not None:
            record["form_scores"].append(float(item["form_score"]))

    for record in groups.values():
        record["phases"] = list(record["phases"])
        record["form_label"] = record["form_labels"][0] if record["form_labels"] else None
        record["form_score"] = float(np.mean(record["form_scores"])) if record["form_scores"] else None
        record.pop("form_labels")
        record.pop("form_scores")
    return sorted(groups.values(), key=lambda item: (item["start_frame"], item["end_frame"]))


def validate_annotations(document: dict, frame_count: int) -> None:
    if frame_count <= 0:
        raise ValueError("frame_count must be positive")

    seen_ids: set[str] = set()
    seen_segments: set[str] = set()
    typed_ranges: dict[str, list[tuple[int, int, str]]] = {}

    for raw_item in document.get("annotations", []):
        item = _canonical_annotation(raw_item)
        start = int(item["start_frame"])
        end = int(item["end_frame"])
        if start < 0 or end < start or end >= frame_count:
            raise ValueError(f"Invalid annotation frame range: {start} -> {end}")

        annotation_id = str(item.get("annotation_id", ""))
        if not annotation_id:
            raise ValueError("Annotation is missing annotation_id")
        if annotation_id in seen_ids:
            raise ValueError(f"Duplicate annotation_id: {annotation_id}")
        seen_ids.add(annotation_id)

        segment_id = str(item.get("segment_id", ""))
        if not segment_id:
            raise ValueError(f"Annotation {annotation_id} is missing segment_id")
        if segment_id in seen_segments:
            raise ValueError(f"Duplicate segment_id: {segment_id}")
        seen_segments.add(segment_id)

        annotation_type = item.get("annotation_type")
        if annotation_type not in ANNOTATION_TYPES:
            raise ValueError(f"Unsupported annotation_type: {annotation_type}")

        state = item.get("activity_state")
        if state is not None and state not in ACTIVITY_STATES:
            raise ValueError(f"Unsupported activity_state: {state}")
        if annotation_type == "activity_state" and state not in ACTIVITY_STATES:
            raise ValueError("Activity-state annotation must specify idle, transition, or active")
        # Activity is a common editable field on every layer.  The hierarchy
        # still has to be contained in a broad active Activity interval, but a
        # child may retain an annotator-entered idle/transition state as
        # contextual metadata.

        phase = item.get("phase")
        if phase not in PHASES:
            raise ValueError(f"Unsupported phase: {phase}")
        if item.get("form_score") is not None and not 0.0 <= float(item["form_score"]) <= 1.0:
            raise ValueError("form_score must be between 0 and 1")
        if annotation_type == "set":
            if item.get("set_id") is None or int(item["set_id"]) < 1:
                raise ValueError("Set annotations require a positive set_id")
        if annotation_type == "rep":
            if item.get("set_id") is None or item.get("rep_id") is None:
                raise ValueError("Rep annotations require set_id and rep_id")
            if int(item["set_id"]) < 1 or int(item["rep_id"]) < 1:
                raise ValueError("set_id and rep_id must be positive integers")

        typed_ranges.setdefault(annotation_type, []).append((start, end, annotation_id))

    # Activity-state segments are the one layer that must form a non-overlapping timeline.
    # Rep/phase ranges intentionally may overlap state segments, but they must remain
    # inside manually labeled active movement. This preserves the intended hierarchy:
    # activity state -> active exercise -> repetition -> phase.
    ranges = sorted(typed_ranges.get("activity_state", []))
    for previous, current in zip(ranges, ranges[1:]):
        if current[0] <= previous[1]:
            raise ValueError(
                "Overlapping activity_state segments are not allowed: "
                f"{previous[2]} ({previous[0]}-{previous[1]}) and "
                f"{current[2]} ({current[0]}-{current[1]})"
            )

    canonical_items = [_canonical_annotation(item) for item in document.get("annotations", [])]
    active_segments = [
        item for item in canonical_items
        if item.get("annotation_type") == "activity_state" and item.get("activity_state") == "active"
    ]

    def _inside_active(item: dict[str, Any]) -> bool:
        return any(
            int(segment["start_frame"]) <= int(item["start_frame"])
            and int(item["end_frame"]) <= int(segment["end_frame"])
            for segment in active_segments
        )

    rep_keys = {
        (item.get("set_id"), item.get("rep_id"))
        for item in canonical_items
        if item.get("annotation_type") == "rep"
    }
    for item in canonical_items:
        annotation_type = item.get("annotation_type")
        if annotation_type in {"set", "rep", "phase"} and not _inside_active(item):
            raise ValueError(
                f"{annotation_type} annotation {item.get('annotation_id')} must be fully contained in an active activity-state segment."
            )
        if annotation_type == "phase":
            key = (item.get("set_id"), item.get("rep_id"))
            if key not in rep_keys:
                raise ValueError(
                    f"Phase annotation {item.get('annotation_id')} references set/rep {key} without a matching rep annotation."
                )
            matching_reps = [
                rep for rep in canonical_items
                if rep.get("annotation_type") == "rep"
                and rep.get("set_id") == item.get("set_id")
                and rep.get("rep_id") == item.get("rep_id")
            ]
            if not any(
                int(rep["start_frame"]) <= int(item["start_frame"])
                and int(item["end_frame"]) <= int(rep["end_frame"])
                for rep in matching_reps
            ):
                raise ValueError(
                    f"Phase annotation {item.get('annotation_id')} must be fully contained in its repetition range."
                )


@dataclass(frozen=True)
class AnnotationWarning:
    message: str
    annotation_ids: tuple[str, ...]


def annotation_warning_details(document: dict, frame_count: int) -> list[AnnotationWarning]:
    """Return non-fatal warnings and the saved rows that can explain them."""
    warnings: list[AnnotationWarning] = []

    def warn(message: str, *rows: dict) -> None:
        ids = tuple(str(row["annotation_id"]) for row in rows if row.get("annotation_id") is not None)
        warnings.append(AnnotationWarning(message, ids))

    annotations = [_canonical_annotation(item) for item in document.get("annotations", [])]
    state_segments = sorted(
        [item for item in annotations if item.get("annotation_type") == "activity_state"],
        key=lambda item: int(item["start_frame"]),
    )
    if not state_segments:
        warn("No activity-state segments have been annotated yet.")
    else:
        if int(state_segments[0]["start_frame"]) > 0:
            warn("Activity-state coverage does not begin at frame 0.", state_segments[0])
        for previous, item in zip(state_segments, state_segments[1:]):
            previous_end = int(previous["end_frame"])
            start = int(item["start_frame"])
            if start > previous_end + 1:
                first_missing = previous_end + 1
                last_missing = start - 1
                gap = f"frame {first_missing}" if first_missing == last_missing else f"frames {first_missing}–{last_missing}"
                warn(f"Activity-state gap: {gap}.", previous, item)
        last_end = int(state_segments[-1]["end_frame"])
        if last_end < frame_count - 1:
            warn(f"Activity-state coverage ends at frame {last_end}; {frame_count - 1} is the final frame.",
                 state_segments[-1])

    reps = [item for item in annotations if item.get("annotation_type") == "rep"]
    by_set: dict[Any, list[dict]] = {}
    for item in reps:
        set_id = item.get("set_id")
        rep_id = item.get("rep_id")
        if set_id is not None and rep_id is not None:
            by_set.setdefault(set_id, []).append(item)
    for set_id, items in by_set.items():
        unique = sorted({int(item["rep_id"]) for item in items})
        after_gap = {current for previous, current in zip([0, *unique[:-1]], unique) if current != previous + 1}
        if after_gap:
            affected = [item for item in items if int(item["rep_id"]) in after_gap]
            warn(f"Set {set_id} repetition IDs are not sequential from 1: {unique}.", *affected)

    active_rep_without_exercise = [
        item for item in reps
        if item.get("activity_state") == "active" and not str(item.get("exercise") or "").strip()
    ]
    if active_rep_without_exercise:
        warn(f"{len(active_rep_without_exercise)} rep annotation(s) have no exercise label.",
             *active_rep_without_exercise)

    return warnings


def annotation_warnings(document: dict, frame_count: int) -> list[str]:
    """Return non-fatal warning messages for session summaries and QA reports."""
    return [warning.message for warning in annotation_warning_details(document, frame_count)]
