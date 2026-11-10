"""Read-only projection of saved annotation intervals onto a graph clock."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import cycle
import re

import numpy as np

from aihumo.annotations import PHASES

LAYERS = {
    "activity": "Activity", "exercise": "Exercise", "set": "Sets", "rep": "Repetitions",
    "phase": "Phases", "form": "Form observations", "quality": "Tracking quality", "other": "Other intervals",
}
ZOOM_STAGES = ("activity", "set", "rep", "phase")
DEFAULT_THRESHOLDS = (3600, 300, 60, 15)
QUALITY_COLUMNS = ("target_status", "pose_present")
SEMANTIC_COLORS = {
    "activity": {"active": "#239653", "idle": "#778491", "transition": "#ba8124"},
    "phase": dict(zip(sorted(PHASES - {"none"}), cycle(("#663fc2", "#266cc8", "#b38020")))),
    "quality": {"lost": "#d02c4f", "occluded": "#d27d30", "partially_occluded": "#ba9028",
                "unavailable": "#657684"},
}
LAYER_COLORS = ("#239653", "#25808b", "#3676be", "#7956b9", "#663fc2", "#bf3e62", "#cc7131", "#778491")


def timeline_preferences(raw=None):
    """Fill missing settings and ignore invalid values in older settings files."""
    raw = raw if isinstance(raw, dict) else {}
    thresholds = raw.get("thresholds")
    if not valid_thresholds(thresholds):
        thresholds = DEFAULT_THRESHOLDS
    saved_layers = raw.get("layers")
    layers = {}
    for key, default_color in zip(LAYERS, LAYER_COLORS):
        saved = saved_layers.get(key) if isinstance(saved_layers, dict) else {}
        saved = saved if isinstance(saved, dict) else {}
        opacity = saved.get("opacity")
        semantic = saved.get("semantic")
        layers[key] = {
            "visible": saved.get("visible", key not in ("form", "quality", "other")) is True,
            "alternate": saved.get("alternate", key in ("set", "rep")) is True,
            "color": _color(saved.get("color"), default_color),
            "alternate_color": _color(saved.get("alternate_color"), "#7197cf"),
            "opacity": float(opacity) if type(opacity) in (int, float) and 0 <= opacity <= 1 else 0.16,
            "semantic": {name: _color(semantic.get(name) if isinstance(semantic, dict) else None, color)
                         for name, color in SEMANTIC_COLORS.get(key, {}).items()},
        }
    style = raw.get("style")
    return {"style": style if style in ("Off", "Overlay", "Timeline") else "Off",
            "auto": raw.get("auto", True) is True, "thresholds": list(thresholds), "layers": layers}


def valid_thresholds(values):
    return (isinstance(values, (list, tuple)) and len(values) == len(ZOOM_STAGES)
            and all(type(value) is int and 1 <= value <= 86400 for value in values)
            and all(left >= right for left, right in zip(values, values[1:])))


def _color(value, fallback):
    return value if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) else fallback


@dataclass(frozen=True)
class Interval:
    layer: str
    start: float
    end: float
    label: str
    annotation_id: str = ""
    semantic: str = ""
    alternate: bool = False


def project_intervals(rows, times, frames):
    """Convert the annotation schema's inclusive frame ends to display spans."""
    if not len(times):
        return ()
    positive = np.diff(times)
    positive = positive[np.isfinite(positive) & (positive > 0)]
    tail = float(np.median(positive)) if len(positive) else 1 / 30
    lookup = {int(frame): index for index, frame in enumerate(frames) if np.isfinite(frame)}
    if not lookup:
        return ()
    first, last = min(lookup), max(lookup)
    boundaries = np.r_[times, times[-1] + tail]
    intervals = []
    counters = defaultdict(int)
    exercises = set()

    def append(layer, start, end, label, row, semantic=""):
        index = counters[layer]
        counters[layer] += 1
        intervals.append(Interval(layer, float(boundaries[start]), float(boundaries[end + 1]),
                                  str(label), str(row.get("annotation_id", "")), semantic, index % 2 == 1))

    valid_rows = (row for row in rows if type(row.get("start_frame")) is int and type(row.get("end_frame")) is int)
    for row in sorted(valid_rows, key=lambda item: (item["start_frame"], item["end_frame"])):
        start_frame, end_frame = row.get("start_frame"), row.get("end_frame")
        start, end = lookup.get(max(start_frame, first)), lookup.get(min(end_frame, last))
        if start is None or end is None or start > end or not np.isfinite(boundaries[[start, end + 1]]).all():
            continue
        kind = row.get("annotation_type")
        state = str(row.get("activity_state") or "Unknown")
        if kind == "activity_state":
            append("activity", start, end, state.title(), row, state)
        elif kind == "set":
            exercise = row.get("exercise")
            if exercise:
                # Exercise identity lives on the saved set in this schema.
                token = start, end, exercise
                if token not in exercises:
                    exercises.add(token)
                    append("exercise", start, end, exercise, row)
            append("set", start, end, f"Set {row.get('set_id', '')}", row)
        elif kind == "rep":
            append("rep", start, end, f"Rep {row.get('rep_id', '')}", row)
        elif kind == "phase":
            phase = str(row.get("phase", ""))
            if phase and phase != "none":
                append("phase", start, end, phase.title(), row, phase)
        elif kind == "form_interval":
            issues = row.get("issue_type") or []
            issues = [issues] if isinstance(issues, str) else issues
            categories = row.get("error_category") or []
            categories = [categories] if isinstance(categories, str) else categories
            label = ", ".join(map(str, categories or issues or [row.get("form_label") or "Form observation"]))
            if "tracking_quality" in issues:
                append("quality", start, end, label, row)
            if not issues or any(issue != "tracking_quality" for issue in issues):
                append("form", start, end, label, row)
        elif kind == "general":
            append("other", start, end, state.title(), row)
    return tuple(intervals)


def tracking_intervals(dataframe, times):
    """Collapse consecutive saved tracking failures into inspectable spans."""
    if not len(times):
        return ()
    status = (dataframe["target_status"].fillna("").to_numpy()
              if "target_status" in dataframe else np.full(len(times), ""))
    if "pose_present" in dataframe:
        status = np.where((status == "") & (dataframe["pose_present"].to_numpy(dtype=float, na_value=np.nan) == 0),
                          "unavailable", status)
    changes = np.r_[0, np.flatnonzero(status[1:] != status[:-1]) + 1, len(times)]
    tail = times[-1] + (max(1e-6, times[-1] - times[-2]) if len(times) > 1 else 1 / 30)
    return tuple(
        Interval("quality", float(times[start]), float(times[end] if end < len(times) else tail),
                 status[start].replace("_", " ").title(), semantic=status[start])
        for start, end in zip(changes, changes[1:]) if status[start] in SEMANTIC_COLORS["quality"]
    )


def visible_layers(settings, duration):
    activity, sets, reps, phases = settings["thresholds"]
    thresholds = dict(activity=activity, exercise=activity, set=sets, rep=reps, phase=phases,
                      form=phases, quality=phases, other=activity)
    return tuple(key for key in LAYERS if settings["layers"][key]["visible"]
                 and (not settings["auto"] or duration <= thresholds[key]))


def interval_color(item, layer):
    return layer["semantic"].get(item.semantic) or (
        layer["alternate_color"] if layer["alternate"] and item.alternate else layer["color"]
    )
