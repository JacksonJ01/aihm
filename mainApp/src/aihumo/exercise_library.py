"""Versioned starter exercise and observable form-deviation catalog.

The catalog is deliberately data-only: it supplies annotation choices and graph
presets, but never turns an angle threshold into an automatic form judgment.
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

LIBRARY_VERSION = "1.2.0"
_RETIRED_FAMILIES = {"accessory"}  # Keep definitions available for existing annotations.

_FAMILIES = {
    "squat": ["bodyweight_squat", "goblet_squat", "back_squat", "front_squat", "sumo_squat", "box_squat", "pause_squat", "hack_squat", "leg_press", "belt_squat"],
    "hinge": ["romanian_deadlift", "conventional_deadlift", "sumo_deadlift", "kettlebell_swing", "hip_thrust", "glute_bridge", "good_morning", "cable_pull_through", "back_extension", "single_leg_romanian_deadlift"],
    "lunge": ["forward_lunge", "reverse_lunge", "walking_lunge", "lateral_lunge", "curtsy_lunge", "deficit_reverse_lunge", "bulgarian_split_squat", "front_foot_elevated_split_squat", "step_up", "jumping_lunge"],
    "push": ["push_up", "shoulder_press", "single_arm_shoulder_press", "bench_press", "incline_bench_press", "dumbbell_bench_press", "dips", "landmine_press", "machine_chest_press", "triceps_extension"],
    "pull": ["biceps_curl", "single_arm_biceps_curl", "bent_over_row", "single_arm_dumbbell_row", "seated_cable_row", "pull_up", "assisted_pull_up", "lat_pulldown", "chest_supported_row", "face_pull"],
    "carry": ["farmers_carry", "suitcase_carry", "overhead_carry", "sled_push", "sled_drag", "incline_treadmill_walk", "rowing", "cycling", "walking", "running_in_place"],
    "rotate": ["russian_twist", "woodchopper", "cable_lift", "landmine_rotation", "medicine_ball_rotational_throw", "medicine_ball_side_toss", "standing_torso_rotation", "bicycle_crunch", "windshield_wiper", "turkish_get_up"],
    "core": ["plank", "side_plank", "dead_bug", "bird_dog", "hollow_hold", "hanging_knee_raise", "ab_wheel_rollout", "pallof_press", "suitcase_hold", "cable_crunch"],
    "jump_conditioning": ["jump_squat", "box_jump", "broad_jump", "split_squat_jump", "lateral_skater_jump", "jumping_jack", "tuck_jump", "pogo_jump", "lateral_hurdle_jump", "medicine_ball_slam"],
    "accessory": ["barbell_biceps_curl", "single_arm_dumbbell_curl", "bilateral_dumbbell_curl", "triceps_extension", "overhead_triceps_extension", "face_pull", "rear_delt_fly", "lateral_raise", "front_raise", "wrist_curl"],
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
    "carry": "Locomotion",
    "rotate": "Twist",
    "core": "Core",
    "jump_conditioning": "Jump",
    "accessory": "Upper-body accessories",
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
    primary = list(_ANGLE_PRESETS.get(exercise_id, []))
    variation_map = {
        "goblet_squat": ["goblet"], "bench_press": ["flat", "incline"],
        "incline_bench_press": ["incline"], "biceps_curl": ["barbell", "bilateral"],
        "single_arm_biceps_curl": ["single_arm"], "shoulder_press": ["barbell", "dumbbell", "seated", "standing"],
    }
    return {
        "exerciseId": exercise_id,
        "name": exercise_id.replace("_", " ").title(),
        "displayName": pascal_case(exercise_id),
        "family": family,
        "movementType": _MOVEMENT_TYPE_LABELS.get(family, pascal_case(family)),
        "libraryVersion": LIBRARY_VERSION,
        "anglePreset": list(_ANGLE_PRESETS.get(exercise_id, [])),
        "exerciseName": exercise_id.replace("_", " ").title(),
        "movementCategory": _MOVEMENT_TYPE_LABELS.get(family, pascal_case(family)),
        "exerciseVariation": None,
        "variationOptions": variation_map.get(exercise_id, []),
        "equipment": [],
        "primaryJoints": primary,
        "secondaryJoints": [],
        "trackedLandmarks": primary,
        "primaryAngles": primary,
        "secondaryAngles": [],
        "movementPhases": ["eccentric", "concentric", "hold"],
        "formChecks": [e[0] for e in _ERRORS[:4]],
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
    labels = dict.fromkeys(
        _MOVEMENT_TYPE_LABELS.get(family, pascal_case(family))
        for family in _FAMILIES if family not in _RETIRED_FAMILIES
    )
    return [*labels, "Other"]


def exercise_options(movement_type: str | None = None) -> list[tuple[str, str]]:
    """Return ``(PascalCase label, stable exerciseId)`` pairs for the UI."""
    wanted = str(movement_type or "").strip()
    result: list[tuple[str, str]] = []
    for family, ids in _FAMILIES.items():
        if family in _RETIRED_FAMILIES:
            continue
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
