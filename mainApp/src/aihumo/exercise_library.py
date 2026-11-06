"""Versioned starter exercise and observable form-deviation catalog.

The catalog is deliberately data-only: it supplies annotation choices and graph
presets, but never turns an angle threshold into an automatic form judgment.
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

LIBRARY_VERSION = "1.1.0"

_FAMILIES = {
    "squat": ["bodyweight_squat", "goblet_squat", "sumo_squat"],
    "hinge": ["romanian_deadlift", "conventional_deadlift", "good_morning"],
    "lunge": ["forward_lunge", "reverse_lunge", "lateral_lunge"],
    "push": ["push_up", "shoulder_press", "bench_press", "dips"],
    "pull": ["biceps_curl", "bent_over_row", "pull_up"],
    "carry": ["farmers_carry", "suitcase_carry", "overhead_carry"],
    "rotate": ["russian_twist", "woodchopper", "standing_torso_rotation"],
    "core": ["plank", "side_plank", "dead_bug"],
    "jump_conditioning": ["jump_squat", "jumping_jack", "broad_jump"],
    "walking_locomotion": ["walking", "running_in_place", "mountain_climber"],
}

# These labels are intentionally compact PascalCase labels for the annotation
# UI.  The stable snake_case family and exercise IDs remain the storage/API
# contract so existing annotations and graph presets continue to load.
_MOVEMENT_TYPE_LABELS = {
    "squat": "Squat",
    "hinge": "Hinge",
    "lunge": "Lunge",
    "push": "Push",
    "pull": "Pull",
    "carry": "Carry",
    "rotate": "Twist",
    "core": "Core",
    "jump_conditioning": "Jump",
    "walking_locomotion": "Locomotion",
}


def pascal_case(value: str) -> str:
    """Return a stable UI label without changing the persisted identifier."""
    words = [part for part in re.split(r"[^A-Za-z0-9]+", str(value or "")) if part]
    return "".join(word[:1].upper() + word[1:] for word in words)

_ANGLE_PRESETS = {
    "bodyweight_squat": ["left_knee", "right_knee", "left_hip", "right_hip", "left_ankle", "right_ankle", "torso_nose_shoulder_hip", "torso_vertical"],
    "goblet_squat": ["left_knee", "right_knee", "left_hip", "right_hip", "torso_vertical"],
    "sumo_squat": ["left_knee", "right_knee", "left_hip", "right_hip", "torso_vertical"],
    "biceps_curl": ["left_elbow", "right_elbow", "left_shoulder", "right_shoulder"],
    "push_up": ["left_elbow", "right_elbow", "left_shoulder", "right_shoulder", "torso_vertical"],
    "romanian_deadlift": ["left_hip", "right_hip", "left_knee", "right_knee", "torso_vertical"],
    "shoulder_press": ["left_shoulder", "right_shoulder", "left_elbow", "right_elbow"],
    "forward_lunge": ["left_knee", "right_knee", "left_hip", "right_hip", "left_ankle", "right_ankle"],
    "dips": ["left_elbow", "right_elbow", "left_shoulder", "right_shoulder", "torso_vertical"],
}

_ERRORS = [
    ("trunk_compensation", "Trunk compensation", "Observable change in torso orientation during the movement."),
    ("asymmetry", "Left/right asymmetry", "Observable difference between bilateral movement patterns."),
    ("limited_range", "Limited range of motion", "The observed interval does not reach the intended range; context is required."),
    ("tempo_variation", "Tempo variation", "Observable change in movement speed or timing."),
    ("joint_alignment", "Joint alignment variation", "Observable alignment change in the selected view."),
]


def _definition(exercise_id: str, family: str) -> dict[str, Any]:
    return {
        "exerciseId": exercise_id,
        "name": exercise_id.replace("_", " ").title(),
        "displayName": pascal_case(exercise_id),
        "family": family,
        "movementType": _MOVEMENT_TYPE_LABELS.get(family, pascal_case(family)),
        "libraryVersion": LIBRARY_VERSION,
        "anglePreset": list(_ANGLE_PRESETS.get(exercise_id, [])),
        "phaseSchema": ["eccentric", "concentric", "hold"],
        "candidateErrors": [e[0] for e in _ERRORS[:4]],
        "viewObservability": ["front", "side", "three_quarter"],
        "notes": "Candidate annotations require human evidence; applicability is view- and context-dependent.",
    }


def starter_library() -> dict[str, Any]:
    exercises = []
    for family, ids in _FAMILIES.items():
        exercises.extend(_definition(exercise_id, family) for exercise_id in ids)
    return {
        "schemaVersion": "1.0",
        "libraryVersion": LIBRARY_VERSION,
        "exercises": exercises,
        "errors": [
            {"errorId": error_id, "name": name, "definition": definition,
             "states": ["observed", "absent", "unknown"], "appliesTo": "exercise and view must be assessed"}
            for error_id, name, definition in _ERRORS
        ],
    }


def get_exercise(exercise_id: str) -> dict[str, Any] | None:
    for item in starter_library()["exercises"]:
        if item["exerciseId"] == exercise_id:
            return deepcopy(item)
    return None


def movement_type_options() -> list[str]:
    """Return movement types in catalog order for a linked UI dropdown."""
    return list(dict.fromkeys(_MOVEMENT_TYPE_LABELS.get(family, pascal_case(family)) for family in _FAMILIES))


def exercise_options(movement_type: str | None = None) -> list[tuple[str, str]]:
    """Return ``(PascalCase label, stable exerciseId)`` pairs for the UI."""
    wanted = str(movement_type or "").strip()
    result: list[tuple[str, str]] = []
    for family, ids in _FAMILIES.items():
        label = _MOVEMENT_TYPE_LABELS.get(family, pascal_case(family))
        if wanted and wanted != label:
            continue
        result.extend((pascal_case(exercise_id), exercise_id) for exercise_id in ids)
    return result


def exercise_ui_values(exercise_id: str | None) -> tuple[str, str]:
    """Map a stored ID or display label to ``(movementType, displayName)``."""
    value = str(exercise_id or "").strip()
    for family, ids in _FAMILIES.items():
        for candidate in ids:
            if value in {candidate, pascal_case(candidate), candidate.replace("_", " ").title()}:
                return _MOVEMENT_TYPE_LABELS.get(family, pascal_case(family)), pascal_case(candidate)
    return "", pascal_case(value) if value else ""


def angle_preset(exercise_id: str | None) -> list[str]:
    return list(_ANGLE_PRESETS.get(str(exercise_id or ""), []))
