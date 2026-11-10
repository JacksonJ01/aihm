from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import logging
import sys
from pathlib import Path
from time import monotonic

import cv2
import pandas as pd
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from PyQt6.QtCore import QEvent, QSignalBlocker, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QImage, QKeySequence, QPixmap, QShortcut, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QScrollArea,
    QPushButton, QDoubleSpinBox, QSlider, QSpinBox, QSplitter, QTableView, QTextEdit, QSizePolicy,
    QVBoxLayout, QWidget,
)

from aihumo.annotations import (
    ACTIVITY_STATES,
    ANNOTATION_TYPES,
    AnnotationState,
    AnnotationWarning,
    annotation_to_frame_targets,
    annotation_warning_details,
    annotation_warnings,
    build_rep_summary,
    validate_annotations,
    save_annotation_parquet,
)
from aihumo.config import load_config
from aihumo.features import CROSS_MEAN_PREFIX, LEGACY_ANGLE_PREFIX, MEAN_ANGLE_PREFIX, PROJECTED_ANGLE_PREFIX, TORSO_ANGLE_PREFIX, WORLD_ANGLE_PREFIX
from aihumo.rep_detection import RepDetector, save_rep_suggestions
from aihumo.storage import annotation_json_for_features, load_json, save_json_atomic
from aihumo.exercise_library import (
    exercise_options,
    exercise_ui_values,
    get_exercise,
    movement_type_options,
    pascal_case,
)
from .angle_overlay import SKELETON_COLUMNS, OverlayTrace, frame_angle_labels, midpoint_overlay_button, paint_angle_labels, paint_skeleton
from .common import DataFrameModel, ReviewWindow, close_and_return
from .graph_viewer import InteractiveGraphViewer, open_graph_viewer
from .joint_graph import GraphAngleSelection, graph_angle_traces
from .playback import FrameBuffer, FrameNavigationButton, FramePlayback, open_review_video, review_window_is_covered
from .preferences import DEFAULT_FRAME_JUMP, MAX_FRAME_JUMP

LOGGER = logging.getLogger("AIHuMoDataStudio.Mode1")


class AnnotationFileChangedError(ValueError):
    """A loaded annotation document has since changed on disk."""


class AnnotationTableModel(DataFrameModel):
    """Show non-fatal warnings beside the rows that they reference."""

    def __init__(self):
        super().__init__()
        self._warning_tooltips: dict[str, str] = {}
        self._warning_background = QBrush(QColor(230, 55, 65, 36))

    def set_warnings(self, warnings: list[AnnotationWarning]) -> None:
        messages_by_id: dict[str, list[str]] = {}
        for warning in warnings:
            for annotation_id in warning.annotation_ids:
                messages_by_id.setdefault(annotation_id, []).append(warning.message)
        self._warning_tooltips = {
            annotation_id: "\n".join(messages) for annotation_id, messages in messages_by_id.items()
        }
        if self.rowCount() and self.columnCount():
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1),
                [Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.BackgroundRole],
            )

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role in (Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.BackgroundRole):
            annotation_id = str(self._dataframe.iat[index.row(), 0])
            tooltip = self._warning_tooltips.get(annotation_id)
            if tooltip:
                return tooltip if role == Qt.ItemDataRole.ToolTipRole else self._warning_background
        return super().data(index, role)


_LAYER_LABELS = {
    "activity_state": "Activity interval",
    "set": "Set interval",
    "rep": "Repetition interval",
    "phase": "Phase interval",
    "form_interval": "Form interval",
    "general": "Other interval",
}

_LAYER_OPTIONS = [
    ("Activity interval", "activity_state"),
    ("Set interval", "set"),
    ("Repetition interval", "rep"),
    ("Phase interval", "phase"),
    ("Form interval", "form_interval"),
    ("Other interval", "general"),
]

_CAMERA_ANGLE_OPTIONS = [
    ("N/A", "N/A"),
    ("Front", "Front"),
    ("Side", "Side"),
    ("Rear", "Rear"),
    ("Three-quarter", "Three-quarter"),
    ("Low angle", "Low angle"),
    ("High angle", "High angle"),
    ("Camera adjustment", "Camera adjustment"),
    ("Unknown", "Unknown"),
]

_ISSUE_TYPE_LABELS = {
    "none": "N/A",
    "form_deviation": "Form deviation",
    "tracking_quality": "Tracking quality",
}

_ISSUE_CATEGORIES = [
    "N/A",
    "Joint alignment",
    "Motion blur",
    "Landmark drift",
    "Occlusion",
    "Pose dropout",
    "Camera motion",
    "Trunk compensation",
    "Asymmetry",
    "Limited range of motion",
    "Tempo variation",
    "Other",
]

_EXERCISE_ERROR_LABELS = {
    "trunk_compensation": "Trunk compensation",
    "asymmetry": "Left/right asymmetry",
    "limited_range": "Limited range of motion",
    "tempo_variation": "Tempo variation",
    "joint_alignment": "Joint alignment variation",
}

_JOINT_OPTIONS = [
    ("Nose", "nose"),
    ("Left eye", "left_eye"), ("Right eye", "right_eye"),
    ("Left ear", "left_ear"), ("Right ear", "right_ear"),
    ("Mouth left", "mouth_left"), ("Mouth right", "mouth_right"),
    ("Left shoulder", "left_shoulder"), ("Right shoulder", "right_shoulder"),
    ("Left elbow", "left_elbow"), ("Right elbow", "right_elbow"),
    ("Left wrist", "left_wrist"), ("Right wrist", "right_wrist"),
    ("Left hip", "left_hip"), ("Right hip", "right_hip"),
    ("Left knee", "left_knee"), ("Right knee", "right_knee"),
    ("Left ankle", "left_ankle"), ("Right ankle", "right_ankle"),
    ("Left heel", "left_heel"), ("Right heel", "right_heel"),
    ("Left foot index", "left_foot_index"), ("Right foot index", "right_foot_index"),
]


def _value_list(value) -> list[str]:
    """Return a de-duplicated list for legacy scalar or new list fields."""
    if value is None:
        return []
    raw_values = value.split(",") if isinstance(value, str) else value
    if not isinstance(raw_values, (list, tuple, set)):
        raw_values = [raw_values]
    result: list[str] = []
    for raw_value in raw_values:
        text = str(raw_value).strip()
        if text and text not in {"N/A", "none"} and text not in result:
            result.append(text)
    return result


def _format_issue_types(value) -> str:
    labels = [_ISSUE_TYPE_LABELS.get(item, item) for item in _value_list(value)]
    return ", ".join(labels) if labels else "N/A"


def _format_values(value) -> str:
    values = _value_list(value)
    return ", ".join(values) if values else "N/A"


def _issue_categories_for_exercise(exercise_id: str | None) -> list[str]:
    """Return stable, human-readable issue choices for the selected exercise.

    The catalog supplies exercise-specific candidate deviations.  Tracking
    quality choices remain available for every exercise because fast motion,
    blur, occlusion, and dropped landmarks are data-quality observations, not
    automatic judgments about form.
    """
    labels = ["N/A"]
    exercise = get_exercise(exercise_id or "")
    for error_id in (exercise or {}).get("candidateErrors", []):
        label = _EXERCISE_ERROR_LABELS.get(str(error_id), str(error_id).replace("_", " ").title())
        if label not in labels:
            labels.append(label)
    for label in _ISSUE_CATEGORIES[2:]:
        if label not in labels:
            labels.append(label)
    return labels


class CheckableComboBox(QComboBox):
    """Reliable multi-select dropdown used by issue and joint fields.

    QComboBox still performs its normal current-item update after a popup row
    is pressed.  That update can overwrite a read-only line edit after our
    checkbox was toggled, which is why the old UI sometimes displayed stale
    values.  Refreshing from the model on data changes, on the next event-loop
    turn, and when the popup closes keeps the visible text synchronized with
    the checked state in every case.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText("N/A")
        self.setModel(QStandardItemModel(self))
        self.view().pressed.connect(self._toggle_item)
        self.model().dataChanged.connect(lambda *_args: self._refresh_text())

    def add_checkable_item(self, label: str, value: str) -> None:
        item = QStandardItem(label)
        item.setData(value, Qt.ItemDataRole.UserRole)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Unchecked)
        self.model().appendRow(item)

    def _toggle_item(self, index) -> None:
        item = self.model().itemFromIndex(index)
        item.setCheckState(
            Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked
        )
        self._refresh_text()
        QTimer.singleShot(0, self._refresh_text)

    def showPopup(self) -> None:
        self._refresh_text()
        super().showPopup()

    def hidePopup(self) -> None:
        super().hidePopup()
        self._refresh_text()

    def _refresh_text(self) -> None:
        labels = [
            self.model().item(row).text()
            for row in range(self.model().rowCount())
            if self.model().item(row).checkState() == Qt.CheckState.Checked
        ]
        self.lineEdit().setText(", ".join(labels) if labels else "N/A")

    def checked_values(self) -> list[str]:
        return [
            str(self.model().item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.model().rowCount())
            if self.model().item(row).checkState() == Qt.CheckState.Checked
            and str(self.model().item(row).data(Qt.ItemDataRole.UserRole) or "")
        ]

    def clear_items(self) -> None:
        self.model().clear()
        self._refresh_text()

    def set_checked_values(self, values) -> None:
        wanted = set(_value_list(values))
        for row in range(self.model().rowCount()):
            item = self.model().item(row)
            item.setCheckState(
                Qt.CheckState.Checked if str(item.data(Qt.ItemDataRole.UserRole)) in wanted else Qt.CheckState.Unchecked
            )
        self._refresh_text()


class ExerciseSelector:
    """Linked PascalCase movement/exercise selectors backed by stable IDs."""

    def __init__(self, parent: QWidget, initial_value: str | None = None):
        self.movement_type = QComboBox(parent)
        self.movement_type.addItem("N/A", "")
        for movement_type in movement_type_options():
            self.movement_type.addItem(movement_type, movement_type)
        self.exercise_name = QComboBox(parent)
        self.exercise_name.addItem("N/A", "")
        self.exercise_variation = QComboBox(parent)
        self.exercise_variation.addItem("Default variation", "")
        self.custom_exercise = QLineEdit(parent)
        self.custom_exercise.setPlaceholderText("Enter a new exercise name")
        self.custom_exercise.hide()
        self.movement_type.currentIndexChanged.connect(self._refresh_exercises)
        self.exercise_name.currentIndexChanged.connect(self._refresh_variations)
        self._refresh_exercises()
        self.set_value(initial_value)

    def _refresh_exercises(self, _index: int = -1) -> None:
        previous_id = self.exercise_name.currentData()
        options = exercise_options(self.movement_type.currentData())
        self.exercise_name.blockSignals(True)
        self.exercise_name.clear()
        self.exercise_name.addItem("N/A", "")
        for label, exercise_id in options:
            self.exercise_name.addItem(label, exercise_id)
        if previous_id:
            index = self.exercise_name.findData(previous_id)
            if index >= 0:
                self.exercise_name.setCurrentIndex(index)
        self.exercise_name.blockSignals(False)
        is_other = self.movement_type.currentData() == "Other"
        self.exercise_name.setVisible(not is_other)
        self.custom_exercise.setVisible(is_other)
        self._refresh_variations()

    def _refresh_variations(self, _index: int = -1) -> None:
        exercise = get_exercise(self.exercise_name.currentData() or "") or {}
        previous = self.exercise_variation.currentData()
        self.exercise_variation.blockSignals(True)
        self.exercise_variation.clear()
        self.exercise_variation.addItem("Default variation", "")
        for variation in exercise.get("variationOptions", []):
            self.exercise_variation.addItem(pascal_case(variation), variation)
        if previous:
            index = self.exercise_variation.findData(previous)
            if index >= 0:
                self.exercise_variation.setCurrentIndex(index)
        self.exercise_variation.blockSignals(False)

    def set_value(self, value: str | None) -> None:
        if not value:
            # An annotation may intentionally have no exercise. Clear stale
            # selections from the previously edited row instead of leaving a
            # misleading exercise name visible in the editor.
            self.movement_type.setCurrentIndex(0)
            self._refresh_exercises()
            self.exercise_name.setCurrentIndex(0)
            self._refresh_variations()
            return
        movement_type, exercise_label = exercise_ui_values(value)
        if movement_type:
            movement_index = self.movement_type.findData(movement_type)
            if movement_index < 0:
                # Preserve saved exercise IDs from retired movement menus.
                self.custom_exercise.setText(str(value).strip())
                self.movement_type.setCurrentIndex(self.movement_type.findData("Other"))
                return
            self.movement_type.setCurrentIndex(movement_index)
        self._refresh_exercises()
        exercise_id = str(value).strip()
        exercise_index = self.exercise_name.findData(exercise_id)
        if exercise_index < 0:
            exercise_index = self.exercise_name.findText(exercise_label)
        if exercise_index >= 0:
            self.exercise_name.setCurrentIndex(exercise_index)
        self._refresh_variations()

    def value(self) -> str | None:
        if self.movement_type.currentData() == "Other":
            return self.custom_exercise.text().strip() or None
        return self.exercise_name.currentData() or None

    def variation(self) -> str | None:
        return self.exercise_variation.currentData() or None


class RangeCaptureDialog(QDialog):
    """Non-modal range capture window used between W (start) and S (end)."""

    def __init__(self, studio: "AnnotationStudio", start_frame: int):
        super().__init__(studio)
        self.studio = studio
        self.start_frame = int(start_frame)
        self.end_frame = int(start_frame)
        self.setWindowTitle("AIHuMo — Mark Annotation Range")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setModal(False)
        self.setFixedSize(500, 250)

        layout = QVBoxLayout(self)
        title = QLabel("Marking annotation range")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)
        self.range_label = QLabel()
        self.range_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.range_label.setStyleSheet("font-size: 16px;")
        layout.addWidget(self.range_label)
        self.instruction_label = QLabel(
            f"Use ← / → to move one frame. ↑ / ↓ to move ±{studio.frame_jump} frames.\n"
            "Press S to finish the range and enter labels."
        )
        self.instruction_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.instruction_label.setWordWrap(True)
        layout.addWidget(self.instruction_label)

        cancel_button = QPushButton("Cancel (Esc)")
        cancel_button.clicked.connect(self.reject)
        layout.addWidget(cancel_button)

        self._shortcut("Left", Qt.Key.Key_Left, lambda: self._move(-1))
        self._shortcut("Right", Qt.Key.Key_Right, lambda: self._move(1))
        self._shortcut("Up", Qt.Key.Key_Up, lambda: self._move(self.studio.frame_jump))
        self._shortcut("Down", Qt.Key.Key_Down, lambda: self._move(-self.studio.frame_jump))
        self.shortcut_finish = QShortcut(QKeySequence("S"), self)
        self.shortcut_finish.setContext(Qt.ShortcutContext.WindowShortcut)
        self.shortcut_finish.activated.connect(self.finish_range)
        self.shortcut_cancel = QShortcut(QKeySequence("Esc"), self)
        self.shortcut_cancel.setContext(Qt.ShortcutContext.WindowShortcut)
        self.shortcut_cancel.activated.connect(self.reject)
        self._refresh()

    def _shortcut(self, name: str, key, callback) -> None:
        shortcut = QShortcut(QKeySequence(key), self)
        shortcut.setObjectName(name)
        shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut.activated.connect(callback)

    def _move(self, delta: int) -> None:
        self.studio.goto_frame(self.studio.current_frame + delta)
        self.end_frame = self.studio.current_frame
        self._refresh()

    def _refresh(self) -> None:
        start_time = float(self.studio._row_for_frame(self.start_frame)["timestamp_s"])
        end_time = float(self.studio._row_for_frame(self.end_frame)["timestamp_s"])
        self.range_label.setText(
            f"Start: frame {self.start_frame} ({start_time:.3f}s)\n"
            f"End: frame {self.end_frame} ({end_time:.3f}s)\n"
            f"Duration: {max(0.0, end_time - start_time):.3f}s"
        )
        self.studio.set_range_status(self.start_frame, self.end_frame)

    def finish_range(self) -> None:
        if self.end_frame < self.start_frame:
            QMessageBox.warning(self, "Invalid range", "End frame must be at or after the start frame.")
            return
        self.accept()
        self.studio.complete_range_capture(self.start_frame, self.end_frame)

    def reject(self) -> None:
        self.studio.cancel_range_capture()
        super().reject()


class AnnotationDialog(QDialog):
    """Choose the semantic annotation layer after a temporal range is captured."""

    def __init__(
        self,
        start_frame: int,
        end_frame: int,
        start_time: float,
        end_time: float,
        context: dict,
        parent=None,
        existing: dict | None = None,
        defaults: dict | None = None,
        segment_id: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle("AIHuMo — Annotation")
        self.resize(600, 650)
        existing = existing or {}
        defaults = defaults or {}
        context = context or {}
        self._start_frame = int(start_frame)
        self._end_frame = int(end_frame)
        self._start_time = float(start_time)
        self._end_time = float(end_time)

        form = QFormLayout(self)
        self.segment_label = QLabel(segment_id or str(existing.get("segment_id", "")))
        self.segment_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.range_label = QLabel(
            f"Frames {start_frame}–{end_frame} | {start_time:.3f}s–{end_time:.3f}s | "
            f"Duration {max(0.0, end_time - start_time):.3f}s"
        )
        self.range_label.setWordWrap(True)

        self.annotation_type = QComboBox()
        for label, value in _LAYER_OPTIONS:
            self.annotation_type.addItem(label, value)
        self._set_combo_data(self.annotation_type, existing.get("annotation_type"), context.get("annotation_type", "activity_state"))

        self.activity_state = QComboBox()
        self.activity_state.addItems(sorted(ACTIVITY_STATES))
        default_state = existing.get("activity_state", context.get("activity_state", "active"))
        self._set_combo(self.activity_state, default_state)

        self.camera_angle = QComboBox()
        for label, value in _CAMERA_ANGLE_OPTIONS:
            self.camera_angle.addItem(label, value)
        self._set_combo_data(
            self.camera_angle,
            existing.get("camera_angle", context.get("camera_angle")),
            "N/A",
        )

        exercise_default = existing.get("exercise", defaults.get("exercise", context.get("exercise", ""))) or ""
        self.exercise_selector = ExerciseSelector(self, str(exercise_default))

        self.set_id = QSpinBox()
        self.set_id.setRange(0, 10_000)
        self.set_id.setSpecialValueText("N/A")
        set_value = existing.get("set_id", context.get("set_id"))
        self.set_id.setValue(int(set_value) if set_value is not None else 0)
        self.rep_id = QSpinBox()
        self.rep_id.setRange(0, 100_000)
        self.rep_id.setSpecialValueText("N/A")
        rep_value = existing.get("rep_id", context.get("rep_id"))
        self.rep_id.setValue(int(rep_value) if rep_value is not None else 0)
        self.auto_rep_id = QCheckBox("Auto")
        self.auto_rep_id.setChecked(True)

        self.phase = QComboBox()
        self.phase.addItem("N/A", "none")
        self.phase.addItems(["eccentric", "concentric", "hold"])
        self._set_combo(self.phase, existing.get("phase", "none"))

        self.form_label = QComboBox()
        self.form_label.addItems(["unlabeled", "good", "acceptable", "poor"])
        self._set_combo(self.form_label, existing.get("form_label", "unlabeled"))

        self.form_score_enabled = QCheckBox("Use score")
        self.form_score = QDoubleSpinBox()
        self.form_score.setRange(0, 1)
        self.form_score.setDecimals(3)
        self.form_score.setSingleStep(0.05)
        score = existing.get("form_score")
        self.form_score_enabled.setChecked(score is not None)
        self.form_score.setValue(float(score) if score is not None else 0.0)

        form_row = QWidget()
        form_row_layout = QHBoxLayout(form_row)
        form_row_layout.setContentsMargins(0, 0, 0, 0)
        form_row_layout.addWidget(self.form_score_enabled)
        form_row_layout.addWidget(self.form_score)

        self.issue_type = CheckableComboBox(self)
        for value, label in _ISSUE_TYPE_LABELS.items():
            self.issue_type.add_checkable_item(label, "" if value == "none" else value)
        self.issue_type.set_checked_values(existing.get("issue_type", []))
        self.error_category = CheckableComboBox(self)
        for label in _ISSUE_CATEGORIES:
            self.error_category.add_checkable_item(label, "" if label == "N/A" else label)
        self.error_category.set_checked_values(existing.get("error_category", []))
        self.affected_joints = CheckableComboBox(self)
        for label, value in _JOINT_OPTIONS:
            self.affected_joints.add_checkable_item(label, value)
        self.affected_joints.set_checked_values(existing.get("affected_joints", []))
        self.notes = QTextEdit(str(existing.get("notes", "") or ""))
        self.notes.setMaximumHeight(90)

        form.addRow("Segment ID", self.segment_label)
        form.addRow("Range", self.range_label)
        form.addRow("Annotation layer", self.annotation_type)
        form.addRow("Activity state", self.activity_state)
        form.addRow("Camera angle", self.camera_angle)
        form.addRow("Movement type", self.exercise_selector.movement_type)
        form.addRow("Exercise name", self.exercise_selector.exercise_name)
        form.addRow("New exercise", self.exercise_selector.custom_exercise)
        form.addRow("Exercise variation", self.exercise_selector.exercise_variation)
        form.addRow("Set ID", self.set_id)
        form.addRow("Rep ID", self._with_checkbox(self.rep_id, self.auto_rep_id))
        form.addRow("Phase", self.phase)
        form.addRow("Form", self.form_label)
        form.addRow("Form score", form_row)
        form.addRow("Issue type", self.issue_type)
        form.addRow("Issue category", self.error_category)
        form.addRow("Affected joints", self.affected_joints)
        form.addRow("Notes", self.notes)

        self.annotation_type.currentIndexChanged.connect(self._update_layer_ui)
        self.exercise_selector.exercise_name.currentIndexChanged.connect(self._refresh_issue_categories)
        self._update_layer_ui()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self._accept_checked)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @staticmethod
    def _with_checkbox(widget, checkbox: QCheckBox) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widget, 1)
        layout.addWidget(checkbox)
        return container

    @staticmethod
    def _set_combo(combo: QComboBox, value) -> None:
        if value is not None:
            index = combo.findText(str(value))
            if index >= 0:
                combo.setCurrentIndex(index)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value, fallback) -> None:
        value = value or fallback
        if value is None:
            return
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _accept_checked(self) -> None:
        layer = self.annotation_type.currentData()
        state = self.activity_state.currentText()
        if layer == "activity_state" and state not in ACTIVITY_STATES:
            QMessageBox.warning(self, "Invalid activity state", "Choose idle, transition, or active.")
            return
        if layer in {"set", "rep", "phase"}:
            if layer in {"rep", "phase"} and self.set_id.value() < 1:
                QMessageBox.warning(self, "Missing set ID", "Rep/phase annotations require a positive set ID.")
                return
            if self.rep_id.value() < 1 and not self.auto_rep_id.isChecked():
                QMessageBox.warning(self, "Missing rep ID", "Enter a positive rep ID or leave automatic assignment enabled.")
                return
            if layer == "phase" and self.rep_id.value() < 1 and self.auto_rep_id.isChecked():
                QMessageBox.warning(self, "Missing rep ID", "Phase annotations need an existing repetition ID; automatic phase assignment is not supported.")
                return
        self.accept()

    def _update_layer_ui(self) -> None:
        layer = self.annotation_type.currentData()
        is_activity = layer == "activity_state"
        is_set = layer == "set"
        is_rep = layer == "rep"
        is_phase = layer == "phase"
        is_form = layer == "form_interval"
        self.activity_state.setEnabled(True)
        self.camera_angle.setEnabled(is_activity)
        self.exercise_selector.movement_type.setEnabled(is_set)
        self.exercise_selector.exercise_name.setEnabled(is_set)
        self.set_id.setEnabled(is_set)
        self.rep_id.setEnabled(is_rep)
        self.auto_rep_id.setEnabled(is_rep)
        self.phase.setEnabled(is_phase)
        self.form_label.setEnabled(is_form)
        self.form_score_enabled.setEnabled(False)
        self.form_score.setEnabled(False)
        self.issue_type.setEnabled(is_form)
        self.error_category.setEnabled(is_form)
        self.affected_joints.setEnabled(is_form)
        if not is_form:
            self.issue_type.set_checked_values([])
            self.error_category.set_checked_values([])
            self.affected_joints.set_checked_values([])
        if not is_activity:
            self.camera_angle.setCurrentIndex(self.camera_angle.findData("N/A"))
        if is_activity:
            self.phase.setCurrentText("none")
            self.rep_id.setValue(0)
            self.set_id.setValue(0)
        elif layer in {"set", "general", "form_interval"}:
            self.rep_id.setValue(0)
            if layer in {"general", "form_interval"}:
                self.set_id.setValue(0)
                self.phase.setCurrentText("none")

    def _refresh_issue_categories(self, _index: int = -1) -> None:
        current = self.error_category.checked_values()
        choices = _issue_categories_for_exercise(self.exercise_selector.value())
        self.error_category.clear_items()
        for label in choices:
            self.error_category.add_checkable_item(label, "" if label == "N/A" else label)
        self.error_category.set_checked_values([value for value in current if value in choices])

    def values(self) -> dict:
        layer = str(self.annotation_type.currentData())
        state = self.activity_state.currentText()
        return {
            "annotation_type": layer,
            "activity_state": state,
            "camera_angle": self.camera_angle.currentData() if layer == "activity_state" else None,
            "exercise": self.exercise_selector.value() if layer == "set" else None,
            "phase": self.phase.currentData() if layer == "phase" else "none",
            "rep_id": None if layer != "rep" or self.rep_id.value() < 1 else self.rep_id.value(),
            "set_id": None if layer != "set" or self.set_id.value() < 1 else self.set_id.value(),
            "form_label": self.form_label.currentText() if layer == "form_interval" else "unlabeled",
            "form_score": None,
            "issue_type": self.issue_type.checked_values() if layer == "form_interval" else [],
            "error_category": self.error_category.checked_values() if layer == "form_interval" else [],
            "affected_joints": self.affected_joints.checked_values() if layer == "form_interval" else [],
            "notes": self.notes.toPlainText().strip(),
            "start_frame": self.start_spin_value,
            "end_frame": self.end_spin_value,
            "start_time_s": self.start_time_value,
            "end_time_s": self.end_time_value,
        }

    @property
    def start_spin_value(self) -> int:
        return self._start_frame

    @property
    def end_spin_value(self) -> int:
        return self._end_frame

    @property
    def start_time_value(self) -> float:
        return self._start_time

    @property
    def end_time_value(self) -> float:
        return self._end_time


class AnnotationStudio(ReviewWindow):
    """Mode 1: manual activity-state segments plus nested reps/phases."""

    closed = pyqtSignal()

    def __init__(self, video_path: str | Path, parquet_path: str | Path, annotation_json_path: str | Path | None = None, metadata_path: str | Path | None = None, parent=None, *, frame_jump: int = DEFAULT_FRAME_JUMP, embedded: bool = False):
        super().__init__(parent)
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self._embedded = embedded
        self.video_path = Path(video_path)
        self.parquet_path = Path(parquet_path)
        self.annotation_json_path = Path(annotation_json_path) if annotation_json_path else annotation_json_for_features(self.parquet_path)
        self.annotation_parquet_path = self.annotation_json_path.with_suffix(".parquet")
        rep_summary_stem = self.annotation_json_path.stem.replace("_annotations", "_rep_summary")
        if rep_summary_stem == self.annotation_json_path.stem:
            rep_summary_stem = f"{rep_summary_stem}_rep_summary"
        self.rep_summary_path = self.annotation_json_path.with_name(rep_summary_stem + ".json")
        metadata_name = self.parquet_path.stem.replace("_features", "_metadata") + ".json"
        standard_sidecar = self.parquet_path.parent.parent / "metadata" / metadata_name
        if metadata_path:
            self.metadata_path = Path(metadata_path)
        elif standard_sidecar.is_file():
            self.metadata_path = standard_sidecar
        else:
            self.metadata_path = self.parquet_path.with_name(metadata_name)
        overlay_angle_prefixes = (LEGACY_ANGLE_PREFIX, f"{CROSS_MEAN_PREFIX}angle_", f"{MEAN_ANGLE_PREFIX}angle_")
        self._feature_columns = pq.read_schema(self.parquet_path).names
        display_columns = {"frame_id", "timestamp_s", "session_id", "video_id", "participant_id", "camera_id", "pose_present"}
        display_columns.update(SKELETON_COLUMNS)
        columns = [name for name in self._feature_columns
                   if name in display_columns or name.startswith(overlay_angle_prefixes)]
        self.dataframe = pd.read_parquet(self.parquet_path, columns=columns)
        if self.dataframe.empty:
            raise ValueError(f"Feature Parquet is empty: {self.parquet_path}")
        if "frame_id" not in self.dataframe.columns or not self.dataframe["frame_id"].is_monotonic_increasing:
            raise ValueError("Feature Parquet frame_id must be present and ordered for synchronized navigation.")
        self.metadata = load_json(self.metadata_path) if self.metadata_path.exists() else {}
        self.annotation_state: AnnotationState | None = None
        self.current_frame = 0
        self._deferred_linked_frame = None
        self._mirrored_overlay_dirty = False
        self.annotation_graph_window: InteractiveGraphViewer | None = None
        self._linked_graph_viewer: InteractiveGraphViewer | None = None
        self._graph_angle_selection: GraphAngleSelection | None = None
        self.total_frames = 0
        self._current_video_pixmap: QPixmap | None = None
        self._layout_initialized = False
        self.range_capture: RangeCaptureDialog | None = None
        self.annotation_start_frame: int | None = None
        self.annotation_edit_id: str | None = None
        self.annotation_edit_end_frame: int | None = None
        self._annotation_save_failed = False
        self._open_video()
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open processed video: {self.video_path}")
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or len(self.dataframe))
        if self.total_frames != len(self.dataframe):
            self.cap.release()
            raise ValueError(
                f"Video/feature frame mismatch: video={self.total_frames}, features={len(self.dataframe)}. "
                "Choose the matching processed video and canonical feature Parquet."
            )
        self.fps = float(self.cap.get(cv2.CAP_PROP_FPS) or self.metadata.get("source_fps", 30.0))
        traces_by_source = graph_angle_traces(self.dataframe.columns)
        self._mirrored_angle_traces = next(iter(traces_by_source.values()), ())
        default_traces = []
        for joint in ("elbow", "shoulder", "hip", "knee"):
            for side in ("left", "right"):
                name = f"{side}_{joint}"
                for prefix in (TORSO_ANGLE_PREFIX, PROJECTED_ANGLE_PREFIX, WORLD_ANGLE_PREFIX, LEGACY_ANGLE_PREFIX):
                    column = f"{prefix}{name}"
                    if column in self.dataframe:
                        default_traces.append(OverlayTrace(f"{LEGACY_ANGLE_PREFIX}{name}", column, "#f2c94c"))
                        break
        self._default_angle_traces = tuple(default_traces)
        # Keyboard navigation is deliberately independent of source FPS.
        # Left/Right = one frame; Up/Down = this configurable jump.
        self.frame_jump = frame_jump
        self._load_annotations()
        self._build_ui()
        self._setup_shortcuts()
        self._open_frame_buffer()
        resume_frame = self.annotation_state.last_completed_frame if self.annotation_state else 0
        resume_frame = max(0, min(int(resume_frame or 0), max(0, self.total_frames - 1)))
        if not embedded:
            self.goto_frame(resume_frame)
        self._refresh_summary()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def _open_video(self):
        self.cap, self._decode_path, self._baked = open_review_video(
            self.video_path, self.metadata, len(self.dataframe), timestamps=self.dataframe["timestamp_s"],
        )
        self._midpoints_baked = self._baked and bool(self.metadata.get("skeleton_midpoints_baked"))

    def _open_frame_buffer(self):
        size = tuple(int(self.cap.get(prop)) for prop in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT))
        self._frame_buffer = FrameBuffer(self._decode_path, self.total_frames, size,
                                         timestamps=getattr(self.cap, "timestamps", None))

    def _close_video(self):
        self._frame_buffer.close()
        self.cap.release()

    def _load_annotations(self) -> None:
        metadata = dict(self.metadata)
        for key in ("session_id", "video_id", "participant_id", "camera_id"):
            if key not in metadata and key in self.dataframe.columns:
                metadata[key] = str(self.dataframe[key].iloc[0])
        metadata.setdefault("features_parquet", str(self.parquet_path))
        metadata.setdefault("processed_video", str(self.video_path))
        self._saved_annotation_document = self._read_saved_annotation()
        if self._saved_annotation_document is not None:
            self.annotation_state = AnnotationState.from_document(self._saved_annotation_document, metadata)
            validate_annotations(self.annotation_state.to_document(), len(self.dataframe))
        else:
            self.annotation_state = AnnotationState.new(metadata)
            self._add_initial_setup_interval_if_untracked()
            if not self._embedded:
                self._persist_annotations(show_error=False)

    def _read_saved_annotation(self):
        try:
            return load_json(self.annotation_json_path)
        except FileNotFoundError:
            return None

    def _check_annotation_revision(self):
        document = self._read_saved_annotation()
        if document != self._saved_annotation_document:
            raise AnnotationFileChangedError(
                f"{self.annotation_json_path.name} changed on disk. Reopen the recording to load the latest annotations."
            )
        return document

    def _add_initial_setup_interval_if_untracked(self) -> None:
        """Create a non-destructive setup interval for a brand-new session.

        This is deliberately conservative: it only runs when there are no
        annotations yet and the first 340 frames contain no detected pose.
        It records setup as ``general``/``idle`` (shown as ``Other interval``)
        so it never claims that the participant was exercising. Sparse pose
        positives below 10% of the first 340 frames are treated as setup noise.
        Existing annotation files are never rewritten by this helper.
        """
        if self.annotation_state is None or self.annotation_state.annotations:
            return
        if len(self.dataframe) == 0:
            return
        pose_column = "pose_present"
        sample_end = min(340, len(self.dataframe))
        if pose_column in self.dataframe.columns:
            detected = pd.to_numeric(
                self.dataframe[pose_column].iloc[:sample_end], errors="coerce"
            ).fillna(0).astype(bool)
            # A handful of isolated MediaPipe positives during camera setup
            # are not stable participant coverage.  Require meaningful
            # coverage before deciding that this is already an exercise
            # interval; this avoids turning setup false positives into an
            # Activity interval.
            detected_fraction = float(detected.mean()) if sample_end else 0.0
            if detected_fraction >= 0.10:
                return
        else:
            # Without an explicit detection flag we cannot infer that the
            # person was absent, so leave the new session empty for review.
            return
        end_frame = min(339, len(self.dataframe) - 1)
        if end_frame < 0:
            return
        start_time = float(self._row_for_frame(0)["timestamp_s"])
        end_time = float(self._row_for_frame(end_frame)["timestamp_s"])
        self.annotation_state.add({
            "annotation_id": self.annotation_state.next_annotation_id(),
            "segment_id": self.annotation_state.next_segment_id(),
            "annotation_type": "general",
            "start_frame": 0,
            "end_frame": end_frame,
            "start_time_s": start_time,
            "end_time_s": end_time,
            "duration_s": max(0.0, end_time - start_time),
            "activity_state": "idle",
            "exercise": None,
            "set_id": None,
            "rep_id": None,
            "phase": "none",
            "form_label": "unlabeled",
            "issue_type": [],
            "error_category": [],
            "affected_joints": [],
            "notes": "Automatic setup interval: no pose detected in the first 340 frames.",
        })

    @property
    def annotations(self) -> list[dict]:
        return self.annotation_state.annotations if self.annotation_state else []

    def _build_ui(self) -> None:
        self.setWindowTitle(f"AIHuMo Annotation Studio — {self.metadata.get('video_id', self.parquet_path.stem)}")
        # The launcher opens this window maximized.  Keep a modest fallback
        # minimum so a manually restored window still fits on a normal laptop;
        # the scroll areas/splitters below are allowed to absorb the rest.
        if not self._embedded:
            self.setMinimumSize(960, 640)
        central = QWidget()
        main = QVBoxLayout(central)

        header = QHBoxLayout()
        self.back_button = QPushButton("Back to menu")
        self.back_button.setToolTip("Close the annotation workspace and return to the launcher.")
        self.back_button.clicked.connect(self._back)
        header.addWidget(self.back_button)
        self.workspace_label = QLabel("Mode 1 Annotation Studio")
        header.addWidget(self.workspace_label, 1)
        self.frame_spin = QSpinBox()
        self.frame_spin.setRange(0, max(0, self.total_frames - 1))
        self.frame_spin.valueChanged.connect(self.goto_frame)
        header.addWidget(QLabel("Frame"))
        header.addWidget(self.frame_spin)
        header.addWidget(QLabel("Jump"))
        self.jump_spin = QSpinBox()
        self.jump_spin.setRange(1, MAX_FRAME_JUMP)
        self.jump_spin.setValue(self.frame_jump)
        self.jump_spin.valueChanged.connect(lambda value: setattr(self, "frame_jump", int(value)))
        self.jump_spin.setToolTip("Frames moved by Up/Down and the −Jump/+Jump buttons.")
        header.addWidget(self.jump_spin)
        self.graph_viewer_button = QPushButton("Interactive Graph Viewer")
        self.graph_viewer_button.setToolTip("Open this recording and frame in the graph viewer.")
        self.graph_viewer_button.clicked.connect(self.open_annotation_graph)
        header.addWidget(self.graph_viewer_button)
        main.addLayout(header)

        context_group = QGroupBox("Current annotation context")
        context_layout = QHBoxLayout(context_group)
        context_layout.setContentsMargins(10, 4, 10, 4)
        self.current_frame_context_label = QLabel()
        self.current_frame_context_label.setWordWrap(False)
        self.current_frame_context_label.setStyleSheet("font-weight: 600;")
        self.context_label = QLabel()
        self.context_label.setWordWrap(False)
        context_layout.addWidget(self.current_frame_context_label, 3)
        context_layout.addWidget(self.context_label, 1)
        context_layout.addWidget(QPushButton("Set context…", clicked=self.open_context_dialog))
        main.addWidget(context_group)

        self.annotation_status = QLabel("Ready. Press W to start an annotation range.")
        self.annotation_status.setWordWrap(True)
        self.annotation_status.setStyleSheet("font-weight: 600;")
        main.addWidget(self.annotation_status)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        main.addWidget(self.summary_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        self.video_layout = left_layout = QVBoxLayout(left)
        self.overlay_controls = overlay_controls = QHBoxLayout()
        self.overlay_button = QPushButton("Display Overlay")
        self.overlay_button.setCheckable(True)
        self.overlay_button.setToolTip("Show left and right elbow, shoulder, hip, and knee angles by default.")
        self.overlay_button.toggled.connect(lambda: self._render_video_pixmap())
        overlay_controls.addWidget(self.overlay_button)
        self.skeleton_button = QPushButton("Show Skeleton")
        self.skeleton_button.setCheckable(True)
        self.skeleton_button.setChecked(True)
        self.skeleton_button.setEnabled(not self._baked)
        self.skeleton_button.setToolTip("The matching clean video is unavailable or could not be verified." if self._baked
                                        else "Show the skeleton from saved image landmarks.")
        self.skeleton_button.toggled.connect(lambda: self._render_video_pixmap())
        overlay_controls.addWidget(self.skeleton_button)
        self.midpoint_button = midpoint_overlay_button(self.dataframe.columns, baked=self._midpoints_baked)
        self.midpoint_button.toggled.connect(lambda: self._render_video_pixmap())
        overlay_controls.addWidget(self.midpoint_button)
        self.mirror_angles_button = QPushButton("Mirror selected graph angles")
        self.mirror_angles_button.setCheckable(True)
        self.mirror_angles_button.setToolTip(
            "Use the graph's default angles or the selection you made in the Interactive Graph Viewer."
        )
        self.mirror_angles_button.toggled.connect(lambda: self._render_video_pixmap())
        overlay_controls.addWidget(self.mirror_angles_button)
        overlay_controls.addStretch(1)
        left_layout.addLayout(overlay_controls)
        self.video_label = QLabel("No frame")
        # Keep the video readable without forcing the annotation pane narrow.
        # Aligning the image to the top uses the otherwise empty space above
        # the video while the horizontal splitter remains user-adjustable.
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.video_label.setMinimumSize(0, 0)
        # Ignore the pixmap's intrinsic size.  Otherwise each replacement
        # frame can alter QLabel's size hint and make the horizontal splitter
        # recalculate its pane widths.
        self.video_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        left_layout.addWidget(self.video_label, 1)
        self.playback = self._create_playback()
        self.frame_slider = None
        if not self._embedded:
            self.frame_slider = QSlider(Qt.Orientation.Horizontal)
            self.frame_slider.setRange(0, self.total_frames - 1)
            self.frame_slider.setAccessibleName("Video position")
            self.frame_slider.setToolTip("Drag to scrub through the recording frame by frame.")
            self.frame_slider.valueChanged.connect(self.goto_frame)
            self.frame_slider.sliderPressed.connect(lambda: self.playback.pause(refresh=False))
            self.frame_slider.sliderReleased.connect(self._refresh_paused_frame)
            left_layout.addWidget(self.frame_slider)
        controls = QHBoxLayout()
        self.play_button = self.playback.button
        self.speed_control = self.playback.speed.control()
        controls.addWidget(self._navigation_button("◀", -1))
        controls.addWidget(self.play_button)
        controls.addWidget(self._navigation_button("▶", 1))
        controls.addWidget(self.speed_control)
        controls.addWidget(self._navigation_button("−Jump", -1, jump=True))
        controls.addWidget(self._navigation_button("+Jump", 1, jump=True))
        controls.addWidget(QPushButton("Mark segment (W)", clicked=self.start_range_capture))
        controls.addWidget(QPushButton("Rep analysis (R)", clicked=self.analyze_current_active_segment))
        left_layout.addLayout(controls)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)

        self.annotation_editor_container = QWidget()
        editor_layout = QVBoxLayout(self.annotation_editor_container)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        self._build_embedded_annotation_editor(editor_layout)
        self.annotation_editor_scroll = QScrollArea()
        self.annotation_editor_scroll.setWidgetResizable(True)
        self.annotation_editor_scroll.setMinimumSize(0, 0)
        self.annotation_editor_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.annotation_editor_scroll.setWidget(self.annotation_editor_container)
        self.annotation_editor_container.setMinimumSize(0, 0)
        self.annotation_editor_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        annotations_container = QWidget()
        annotations_layout = QVBoxLayout(annotations_container)
        annotations_layout.setContentsMargins(0, 0, 0, 0)
        table_header = QHBoxLayout()
        table_header.addWidget(QLabel("Temporal annotations"), 1)
        self.show_all_annotation_layers = QCheckBox("Show all layers")
        self.show_all_annotation_layers.setToolTip("Show the full table or only rows for the editor's current layer.")
        table_header.addWidget(self.show_all_annotation_layers)
        self.edit_selected_button = QPushButton("Edit selected (A)", clicked=self.edit_selected_annotation)
        self.edit_selected_button.setToolTip("Load the selected row. Press S to save changes to that row.")
        self.delete_selected_button = QPushButton("Delete selected…", clicked=self.clear_embedded_annotation)
        table_header.addWidget(self.edit_selected_button)
        table_header.addWidget(self.delete_selected_button)
        annotations_layout.addLayout(table_header)
        self.annotation_model = AnnotationTableModel()
        self.annotation_table = QTableView()
        self.annotation_table.setModel(self.annotation_model)
        self.annotation_table.setAlternatingRowColors(True)
        self.annotation_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.annotation_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.annotation_table.selectionModel().selectionChanged.connect(self._refresh_annotation_actions)
        self.show_all_annotation_layers.toggled.connect(self._refresh_annotation_layer)
        self.editor_annotation_type.currentIndexChanged.connect(self._refresh_annotation_layer)
        # Header + three normal table rows, with a little breathing room.
        self.annotation_table.setMinimumHeight(180)
        self.annotation_table.setToolTip(
            "Click a row to select it. Use Edit selected (A) to load it into the editor. "
            "Hover over a tinted row to see its warning. "
            "Drag the divider above this table to show more or fewer rows."
        )
        annotations_layout.addWidget(self.annotation_table, 1)

        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.setChildrenCollapsible(False)
        right_splitter.addWidget(self.annotation_editor_scroll)
        right_splitter.addWidget(annotations_container)
        right_splitter.setStretchFactor(0, 2)
        right_splitter.setStretchFactor(1, 3)
        right_splitter.setSizes([540, 260])
        right_splitter.setToolTip("Drag this divider to resize the annotation menu and temporal annotation table.")
        right_layout.addWidget(right_splitter, 1)

        buttons = QHBoxLayout()
        buttons.addWidget(QPushButton("Save (Ctrl+S)", clicked=self.save_annotations))
        buttons.addWidget(QPushButton("Mark session complete", clicked=self.mark_session_complete))
        right_layout.addLayout(buttons)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        # Initial proportions are applied once.  The maximized window and
        # splitter stretch factors then let Qt resize both panes without
        # shifting the layout when a field/button receives focus.
        splitter.setSizes([850, 600])
        self.main_splitter = splitter
        main.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.refresh_annotation_table()

    def _back(self):
        close_and_return(self, self._linked_graph_viewer)

    def _navigation_button(self, text, direction, *, jump=False):
        return FrameNavigationButton(
            text, playback=self.playback, pause=self._pause_review, direction=direction, jump=jump,
            seek=lambda: self.goto_frame(self.current_frame + direction * (self.frame_jump if jump else 1)),
        )

    def _create_playback(self):
        playback = FramePlayback(
            self, timestamps=pd.to_numeric(self.dataframe["timestamp_s"], errors="coerce").to_numpy(dtype=float),
            position=lambda: self.current_frame, display_frame=self._show_frame,
            refresh_paused_frame=self._refresh_paused_frame, fps=self.fps,
            ready_frame=lambda target, displayed: self._frame_buffer.ready_for_playback(target, displayed),
        )
        playback.starting.connect(self.resume_review)
        playback.starting.connect(self._pause_linked_graph)
        playback.paused.connect(lambda: self._frame_buffer.request(self.current_frame))
        playback.paused.connect(lambda: self._sync_linked_graph_frame(playing=False))
        return playback

    def open_annotation_graph(self) -> None:
        """Preview the current recording without registering launcher resume progress."""
        self._pause_review()
        viewer = self.annotation_graph_window or self._linked_graph_viewer
        try:
            if viewer is None:
                viewer = open_graph_viewer(
                    self, video_path=self.video_path, parquet_path=self.parquet_path,
                    frame=self.current_frame,
                    annotation_preview=True, frame_jump=self.frame_jump,
                    annotation_json_path=self.annotation_json_path,
                )
                self.annotation_graph_window = viewer
                viewer.graph.select_annotation(self._selected_annotation_id())
                viewer.closed.connect(self._clear_annotation_graph_window)
                viewer.frame_changed.connect(self._follow_graph_frame)
                viewer.playback.starting.connect(self._pause_review)
                if self._graph_angle_selection is not None:
                    viewer.graph.restore_angle_selection(self._graph_angle_selection)
                viewer.graph.traceSelectionChanged.connect(self._update_mirrored_angles)
                self._update_mirrored_angles()
            elif viewer.current_frame != self.current_frame and not viewer.goto_frame(self.current_frame):
                raise ValueError(f"Could not show annotation frame {self.current_frame}.")
            viewer.activate_review()
            viewer.overlay_button.setChecked(self.overlay_button.isChecked())
            viewer.raise_()
            viewer.activateWindow()
        except Exception as exc:
            LOGGER.exception("Could not open annotation graph viewer")
            QMessageBox.critical(self, "Could Not Open Interactive Graph Viewer", str(exc))

    def _clear_annotation_graph_window(self) -> None:
        self.annotation_graph_window = None
        if self._linked_graph_viewer is not None:
            self._update_mirrored_angles()

    def link_graph_viewer(self, viewer: InteractiveGraphViewer) -> None:
        if self._linked_graph_viewer is viewer:
            return
        self._unlink_graph_viewer()
        self._linked_graph_viewer = viewer
        self.back_button.setText("Back to graph viewer")
        self.back_button.setToolTip("Close the annotation workspace and return to the linked graph viewer.")
        viewer.closed.connect(self._unlink_graph_viewer)
        viewer.frame_changed.connect(self._follow_graph_frame)
        viewer.playback.starting.connect(self._pause_review)
        viewer.graph.traceSelectionChanged.connect(self._update_mirrored_angles)
        self._update_mirrored_angles()

    def _unlink_graph_viewer(self) -> None:
        viewer = self._linked_graph_viewer
        if viewer is None:
            return
        self._linked_graph_viewer = None
        viewer.closed.disconnect(self._unlink_graph_viewer)
        viewer.frame_changed.disconnect(self._follow_graph_frame)
        viewer.playback.starting.disconnect(self._pause_review)
        viewer.graph.traceSelectionChanged.disconnect(self._update_mirrored_angles)
        self.back_button.setText("Back to menu")
        self.back_button.setToolTip("Close the annotation workspace and return to the launcher.")

    def _update_mirrored_angles(self) -> None:
        viewer = self.annotation_graph_window or self._linked_graph_viewer
        if viewer is None:
            return
        graph = viewer.graph
        self._graph_angle_selection = graph.angle_selection()
        self._mirrored_angle_traces = graph.overlay_traces()
        if self.overlay_button.isChecked() and self.mirror_angles_button.isChecked():
            if self.review_suspended:
                self._mirrored_overlay_dirty = True
            else:
                self._render_video_pixmap()

    def _follow_graph_frame(self, frame):
        viewer = self.annotation_graph_window or self._linked_graph_viewer
        if frame == self.current_frame:
            self._deferred_linked_frame = None
        elif self.review_suspended or (viewer is not None and viewer.playback.playing and review_window_is_covered(self)):
            self._deferred_linked_frame = frame
        else:
            self.goto_frame(frame)

    def _flush_linked_frame(self):
        if self._deferred_linked_frame is not None:
            self.goto_frame(self._deferred_linked_frame)

    def _pause_linked_graph(self):
        viewer = self.annotation_graph_window or self._linked_graph_viewer
        if viewer is not None:
            viewer._pause_review()

    def _sync_linked_graph_frame(self, *, playing):
        viewer = self.annotation_graph_window or self._linked_graph_viewer
        if viewer is not None:
            viewer.follow_annotation_frame(self.current_frame, playing=playing)

    def _pause_review(self):
        self.playback.pause(refresh=False)

    def _resume_review(self):
        self._flush_linked_frame()
        if self._mirrored_overlay_dirty:
            self._render_video_pixmap()

    def _build_embedded_annotation_editor(self, parent_layout: QVBoxLayout) -> None:
        """Build the always-visible annotation editor used by W/S workflow."""
        group = QGroupBox("Annotation menu")
        form = QFormLayout(group)
        self.editor_annotation_type = QComboBox()
        for label, value in _LAYER_OPTIONS:
            self.editor_annotation_type.addItem(label, value)
        self.editor_annotation_type.setToolTip(
            "Activity interval: broad exercise context; it may contain gaps.\n"
            "Set interval: one exercise set containing repetitions.\n"
            "Repetition interval: one complete repetition.\n"
            "Phase interval: eccentric, concentric, or hold.\n"
            "Form interval: a bounded form or tracking-quality observation that may overlap the hierarchy.\n"
            "Other interval: an event that does not fit those layers."
        )
        self.editor_annotation_type.currentIndexChanged.connect(self._refresh_editor_options)
        self.editor_range_mode = QComboBox()
        self.editor_range_mode.addItem("Frame interval", "interval")
        self.editor_range_mode.addItem("Single frame", "point")
        self.editor_range_mode.currentIndexChanged.connect(self._refresh_editor_options)
        self.editor_activity_state = QComboBox(); self.editor_activity_state.addItems(sorted(ACTIVITY_STATES))
        self.editor_exercise_selector = ExerciseSelector(
            group, str(self.metadata.get("exercise_hint", "") or "")
        )
        self.editor_camera_angle = QComboBox()
        for label, value in _CAMERA_ANGLE_OPTIONS:
            self.editor_camera_angle.addItem(label, value)
        metadata_camera_angle = self.metadata.get("camera_angle") or self.metadata.get("viewpoint")
        if metadata_camera_angle:
            self.editor_camera_angle.setCurrentText(str(metadata_camera_angle))
        self.editor_set_id = QSpinBox(); self.editor_set_id.setRange(0, 10000); self.editor_set_id.setSpecialValueText("N/A"); self.editor_set_id.setValue(0)
        self.editor_rep_id = QSpinBox(); self.editor_rep_id.setRange(0, 100000); self.editor_rep_id.setSpecialValueText("N/A"); self.editor_rep_id.setValue(0)
        self.editor_phase = QComboBox()
        self.editor_form_label = QComboBox(); self.editor_form_label.addItems(["unlabeled", "good", "acceptable", "poor"])
        self.editor_issue_type = CheckableComboBox(group)
        for value, label in _ISSUE_TYPE_LABELS.items():
            self.editor_issue_type.add_checkable_item(label, "" if value == "none" else value)
        self.editor_issue_category = CheckableComboBox(group)
        for label in _ISSUE_CATEGORIES:
            self.editor_issue_category.add_checkable_item(label, "" if label == "N/A" else label)
        self.editor_affected_joints = CheckableComboBox(group)
        for label, value in _JOINT_OPTIONS:
            self.editor_affected_joints.add_checkable_item(label, value)
        self.editor_exercise_selector.exercise_name.currentIndexChanged.connect(
            lambda _index: self._refresh_editor_options()
        )
        self.editor_notes = QTextEdit(); self.editor_notes.setMaximumHeight(55)
        self.editor_range_label = QLabel("Press W to capture a start frame, navigate, then press S to save.")
        self.editor_range_label.setWordWrap(True)
        form.addRow("Layer", self.editor_annotation_type)
        form.addRow("Boundary", self.editor_range_mode)
        form.addRow("Activity", self.editor_activity_state)
        form.addRow("Camera angle", self.editor_camera_angle)
        form.addRow("Movement type", self.editor_exercise_selector.movement_type)
        form.addRow("Exercise name", self.editor_exercise_selector.exercise_name)
        form.addRow("New exercise", self.editor_exercise_selector.custom_exercise)
        form.addRow("Exercise variation", self.editor_exercise_selector.exercise_variation)
        form.addRow("Set", self.editor_set_id)
        form.addRow("Rep", self.editor_rep_id)
        form.addRow("Phase", self.editor_phase)
        form.addRow("Form", self.editor_form_label)
        form.addRow("Issue type", self.editor_issue_type)
        form.addRow("Issue category", self.editor_issue_category)
        form.addRow("Affected joints", self.editor_affected_joints)
        form.addRow("Notes", self.editor_notes)
        form.addRow("Range", self.editor_range_label)
        buttons = QHBoxLayout()
        buttons.addWidget(QPushButton("Start new range (W)", clicked=self.start_range_capture))
        self.editor_save_button = QPushButton("Save range (S)")
        self.editor_save_button.clicked.connect(self.finish_embedded_annotation)
        buttons.addWidget(self.editor_save_button)
        self.editor_cancel_edit_button = QPushButton("Cancel edit (D)", clicked=self.cancel_annotation_edit)
        self.editor_cancel_edit_button.setToolTip("Leave edit mode and deselect the row without saving changes.")
        buttons.addWidget(self.editor_cancel_edit_button)
        form.addRow(buttons)
        parent_layout.addWidget(group)
        self._refresh_editor_options()

    def _refresh_editor_options(self) -> None:
        if not hasattr(self, "editor_annotation_type"):
            return
        if getattr(self, "_updating_editor_context", False):
            return
        self._updating_editor_context = True
        try:
            self._refresh_editor_options_impl()
        finally:
            self._updating_editor_context = False

    def _refresh_editor_options_impl(self) -> None:
        layer = self.editor_annotation_type.currentData()
        is_activity = layer == "activity_state"
        is_set = layer == "set"
        is_rep = layer == "rep"
        is_phase = layer == "phase"
        is_form = layer == "form_interval"

        # Boundary, activity, and notes are common annotation attributes.
        # Every other control is writable only by its owning layer; inherited
        # values are filled below before these controls are disabled.
        self.editor_range_mode.setEnabled(True)
        self.editor_activity_state.setEnabled(True)
        self.editor_camera_angle.setEnabled(is_activity)
        self.editor_notes.setEnabled(True)
        self.editor_exercise_selector.movement_type.setEnabled(is_set)
        self.editor_exercise_selector.exercise_name.setEnabled(is_set)
        self.editor_set_id.setEnabled(is_set)
        self.editor_rep_id.setEnabled(is_rep)
        self.editor_phase.setEnabled(is_phase)

        exercise = get_exercise(self.editor_exercise_selector.value() or "")
        phases = list((exercise or {}).get("phaseSchema", [])) or ["eccentric", "concentric", "hold"]
        current = self.editor_phase.currentData() or self.editor_phase.currentText()
        self.editor_phase.blockSignals(True)
        self.editor_phase.clear()
        self.editor_phase.addItem("N/A", "none")
        for phase in phases:
            self.editor_phase.addItem(str(phase), str(phase))
        index = self.editor_phase.findData(current)
        self.editor_phase.setCurrentIndex(max(0, index))
        self.editor_phase.blockSignals(False)

        # Issue fields are meaningful only on a Form interval.  Keeping them
        # disabled and visibly N/A on hierarchy/setup layers prevents a stale
        # tracking issue from being accidentally attached to a set or phase.
        self.editor_form_label.setEnabled(is_form)
        self.editor_issue_type.setEnabled(is_form)
        self.editor_issue_category.setEnabled(is_form)
        self.editor_affected_joints.setEnabled(is_form)
        if not is_form:
            self.editor_form_label.setCurrentText("unlabeled")
            self.editor_issue_type.set_checked_values([])
            self.editor_issue_category.set_checked_values([])
            self.editor_affected_joints.set_checked_values([])
        if not is_activity:
            self.editor_camera_angle.setCurrentIndex(self.editor_camera_angle.findData("N/A"))
        current_categories = self.editor_issue_category.checked_values()
        category_choices = _issue_categories_for_exercise(self.editor_exercise_selector.value())
        self.editor_issue_category.clear_items()
        for label in category_choices:
            self.editor_issue_category.add_checkable_item(label, "" if label == "N/A" else label)
        self.editor_issue_category.set_checked_values(
            [value for value in current_categories if value in category_choices]
        )
        self._populate_inherited_editor_values(layer)

    def _populate_inherited_editor_values(self, layer: str | None = None) -> None:
        """Populate read-only hierarchy fields from the current frame context.

        The selected layer remains the only layer that can write its own
        hierarchy fields.  For example, a repetition can display the parent
        exercise and set, but only the repetition number is editable there.
        """
        layer = str(layer or self.editor_annotation_type.currentData())
        context, _ = self._context_for_frame(
            self.current_frame,
            exclude_id=self.annotation_edit_id,
        )

        if layer != "activity_state":
            state = context.get("activity_state")
            if state in ACTIVITY_STATES:
                self.editor_activity_state.setCurrentText(str(state))
            camera_angle = context.get("camera_angle")
            if camera_angle:
                camera_index = self.editor_camera_angle.findData(str(camera_angle))
                if camera_index >= 0:
                    self.editor_camera_angle.setCurrentIndex(camera_index)

        if layer != "set":
            self.editor_exercise_selector.set_value(context.get("exercise"))
            if layer == "form_interval":
                current_categories = self.editor_issue_category.checked_values()
                choices = _issue_categories_for_exercise(self.editor_exercise_selector.value())
                self.editor_issue_category.clear_items()
                for label in choices:
                    self.editor_issue_category.add_checkable_item(label, "" if label == "N/A" else label)
                self.editor_issue_category.set_checked_values(
                    [value for value in current_categories if value in choices]
                )
        if layer not in {"set"}:
            set_id = context.get("set_id")
            self.editor_set_id.setValue(max(0, int(set_id))) if set_id is not None else self.editor_set_id.setValue(0)
        if layer != "rep":
            rep_id = context.get("rep_id")
            self.editor_rep_id.setValue(max(0, int(rep_id))) if rep_id is not None else self.editor_rep_id.setValue(0)
        if layer != "phase":
            phase = str(context.get("phase") or "none")
            phase_index = self.editor_phase.findData(phase)
            self.editor_phase.setCurrentIndex(phase_index if phase_index >= 0 else self.editor_phase.findData("none"))

    def _selected_annotation_id(self) -> str | None:
        rows = self.annotation_table.selectionModel().selectedRows()
        return rows[0].data() if rows else None

    def _refresh_annotation_actions(self) -> None:
        selected_id = self._selected_annotation_id()
        viewer = self.annotation_graph_window or self._linked_graph_viewer
        if viewer is not None:
            viewer.graph.select_annotation(selected_id)
        if self.annotation_edit_id is not None and selected_id != self.annotation_edit_id:
            self._discard_annotation_edit()
            self.annotation_status.setText("Edit cancelled. Press A to edit the selected row or W for a new range.")
        self.edit_selected_button.setEnabled(selected_id is not None)
        self.delete_selected_button.setEnabled(selected_id is not None)
        self.editor_cancel_edit_button.setEnabled(selected_id is not None)

    def _reset_annotation_draft(self) -> None:
        self.annotation_start_frame = None
        self.annotation_edit_id = None
        self.annotation_edit_end_frame = None
        self.editor_save_button.setText("Save range (S)")
        self.editor_range_label.setText("Press W to capture a start frame, navigate, then press S to save.")

    def _discard_annotation_edit(self) -> None:
        self._reset_annotation_draft()
        self.editor_notes.clear()
        self.editor_annotation_type.setCurrentIndex(0)
        self.editor_range_mode.setCurrentIndex(0)
        self.editor_activity_state.setCurrentIndex(0)
        camera = self.metadata.get("camera_angle") or self.metadata.get("viewpoint")
        self.editor_camera_angle.setCurrentIndex(max(0, self.editor_camera_angle.findData(camera)))
        self._refresh_editor_options()

    def cancel_annotation_edit(self) -> None:
        editing = self.annotation_edit_id is not None
        if editing:
            self._discard_annotation_edit()
        self.annotation_table.selectionModel().clear()
        if self.annotation_start_frame is None:
            message = "Edit cancelled." if editing else "Selection cleared."
            self.annotation_status.setText(f"{message} Press W to start a new range.")

    def clear_embedded_annotation(self) -> None:
        """Delete the selected saved annotation after checking its children."""
        annotation_id = self._selected_annotation_id()
        if not annotation_id:
            self.annotation_status.setText("Select a temporal annotation row before deleting.")
            return

        target = next((item for item in self.annotations if item.get("annotation_id") == annotation_id), None)
        if target is None:
            self.annotation_status.setText("The selected annotation no longer exists. Refresh the table and try again.")
            return
        target_type = str(target.get("annotation_type"))
        dependents = []
        for item in self.annotations:
            if item.get("annotation_id") == annotation_id:
                continue
            item_type = str(item.get("annotation_type"))
            if target_type == "activity_state" and item_type in {"set", "rep", "phase"}:
                if (
                    int(target.get("start_frame", 0)) <= int(item.get("start_frame", 0))
                    and int(item.get("end_frame", 0)) <= int(target.get("end_frame", 0))
                ):
                    dependents.append(item)
            elif target_type == "set" and item_type in {"rep", "phase"}:
                if item.get("set_id") == target.get("set_id"):
                    dependents.append(item)
            elif target_type == "rep" and item_type == "phase":
                if (
                    item.get("set_id") == target.get("set_id")
                    and item.get("rep_id") == target.get("rep_id")
                ):
                    dependents.append(item)
        if dependents:
            QMessageBox.warning(
                self,
                "Cannot clear parent annotation",
                f"{target_type.title()} {annotation_id} still has {len(dependents)} nested annotation(s). "
                "Clear the child rows first.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Delete selected annotation",
            f"Delete {annotation_id} from the temporal annotations?\n\nThis cannot be undone from the editor.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        previous_state = self.annotation_state
        previous_save_failed = self._annotation_save_failed
        self.annotation_state = deepcopy(previous_state)
        saved = False
        try:
            self.annotation_state.remove(str(annotation_id))
            saved = self._persist_annotations(show_error=True)
            if not saved:
                return
        except Exception as exc:
            LOGGER.exception("Annotation deletion failed")
            QMessageBox.critical(self, "Clear failed", f"The annotation was not cleared.\n\n{type(exc).__name__}: {exc}")
            return
        finally:
            if not saved:
                self.annotation_state = previous_state
                self._annotation_save_failed = previous_save_failed

        self._reset_annotation_draft()
        self.refresh_annotation_table()
        self._refresh_summary()
        self.annotation_status.setText(f"Cleared {annotation_id}. Editor fields were left unchanged.")

    def finish_embedded_annotation(self) -> None:
        self.playback.pause()
        if self.annotation_start_frame is None:
            self.annotation_status.setText("Press W first to capture the start frame.")
            return
        start_frame = int(self.annotation_start_frame)
        if self.editor_range_mode.currentData() == "point":
            end_frame = start_frame
        elif self.annotation_edit_end_frame is not None and self.current_frame == start_frame:
            # Loading a row moves the video to its start. Saving without
            # navigating should edit its labels while preserving its range.
            end_frame = int(self.annotation_edit_end_frame)
        else:
            end_frame = int(self.current_frame)
        if end_frame < start_frame:
            start_frame, end_frame = end_frame, start_frame
        self._save_embedded_annotation(start_frame, end_frame)

    @staticmethod
    def _contains_range(parent: dict, start_frame: int, end_frame: int) -> bool:
        return (
            int(parent.get("start_frame", 0)) <= int(start_frame)
            and int(end_frame) <= int(parent.get("end_frame", 0))
        )

    def _nearest_parent(self, annotation_type: str, start_frame: int, end_frame: int, *, exclude_id: str | None = None) -> dict | None:
        candidates = [
            item for item in self.annotations
            if item.get("annotation_type") == annotation_type
            and (exclude_id is None or str(item.get("annotation_id")) != str(exclude_id))
            and self._contains_range(item, start_frame, end_frame)
        ]
        return min(
            candidates,
            key=lambda item: (
                int(item.get("end_frame", 0)) - int(item.get("start_frame", 0)),
                int(item.get("start_frame", 0)),
                str(item.get("annotation_id", "")),
            ),
            default=None,
        )

    def _next_set_id_for_range(self, start_frame: int, end_frame: int, *, exclude_id: str | None = None) -> int:
        """Assign set numbers locally to the containing activity interval."""
        activity = self._nearest_parent("activity_state", start_frame, end_frame, exclude_id=exclude_id)
        sets = [
            item for item in self.annotations
            if item.get("annotation_type") == "set"
            and item.get("set_id") is not None
            and (exclude_id is None or str(item.get("annotation_id")) != str(exclude_id))
            and (activity is None or self._contains_range(activity, int(item["start_frame"]), int(item["end_frame"])))
        ]
        return max((int(item["set_id"]) for item in sets), default=0) + 1

    def _next_rep_id_for_range(self, set_id: int, start_frame: int, end_frame: int, *, exclude_id: str | None = None) -> int:
        parent_set = self._nearest_parent("set", start_frame, end_frame, exclude_id=exclude_id)
        reps = [
            item for item in self.annotations
            if item.get("annotation_type") == "rep"
            and item.get("set_id") is not None
            and int(item.get("set_id")) == int(set_id)
            and (exclude_id is None or str(item.get("annotation_id")) != str(exclude_id))
            and (parent_set is None or self._contains_range(parent_set, int(item["start_frame"]), int(item["end_frame"])))
        ]
        return max((int(item["rep_id"]) for item in reps if item.get("rep_id") is not None), default=0) + 1

    def _sync_descendant_contexts(self) -> None:
        """Propagate parent exercise/set identity to saved descendants.

        A child stores the effective IDs needed by the existing Parquet/export
        contract, but those values are not independently editable in its UI.
        Updating a set therefore refreshes its repetitions and phases before
        the JSON/derived Parquet checkpoint is written.
        """
        for item in self.annotations:
            kind = str(item.get("annotation_type"))
            if kind == "rep":
                parent = self._nearest_parent("set", int(item["start_frame"]), int(item["end_frame"]))
                if parent is not None:
                    item["exercise"] = parent.get("exercise")
                    item["set_id"] = parent.get("set_id")
            elif kind == "phase":
                parent = self._nearest_parent("rep", int(item["start_frame"]), int(item["end_frame"]))
                if parent is not None:
                    item["exercise"] = parent.get("exercise")
                    item["set_id"] = parent.get("set_id")
                    item["rep_id"] = parent.get("rep_id")

    def _save_embedded_annotation(self, start_frame: int, end_frame: int) -> None:
        layer = str(self.editor_annotation_type.currentData())
        start_time = float(self._row_for_frame(start_frame)["timestamp_s"])
        end_time = float(self._row_for_frame(end_frame)["timestamp_s"])
        existing = None
        if self.annotation_edit_id is not None:
            existing = next(
                (item for item in self.annotations if item.get("annotation_id") == self.annotation_edit_id),
                None,
            )
            if existing is None:
                self.annotation_status.setText("The row being edited no longer exists. Press D to cancel the edit.")
                return
        inherited, _ = self._context_for_frame(
            start_frame,
            exclude_id=existing.get("annotation_id") if existing else None,
        )
        activity_state = self.editor_activity_state.currentText()
        if activity_state not in ACTIVITY_STATES:
            activity_state = inherited.get("activity_state") or "active"
        is_form = layer == "form_interval"
        retained = existing if existing and existing.get("annotation_type") == layer else {}

        # Only the selected layer writes its owned hierarchy values.  The
        # disabled controls are display-only inherited context from a parent.
        exercise = None
        set_id = None
        rep_id = None
        phase = "none"
        camera_angle = None
        if layer == "set":
            exercise = self.editor_exercise_selector.value()
            set_id = self.editor_set_id.value() if self.editor_set_id.value() >= 1 else None
        elif layer == "activity_state":
            camera_angle = self.editor_camera_angle.currentData() or "N/A"
        elif layer == "rep":
            exercise = inherited.get("exercise") or (existing or {}).get("exercise")
            set_id = inherited.get("set_id") or (existing or {}).get("set_id")
            rep_id = self.editor_rep_id.value() if self.editor_rep_id.value() >= 1 else None
        elif layer == "phase":
            exercise = inherited.get("exercise") or (existing or {}).get("exercise")
            set_id = inherited.get("set_id") or (existing or {}).get("set_id")
            rep_id = inherited.get("rep_id") or (existing or {}).get("rep_id")
            phase = self.editor_phase.currentData() or "none"

        values = {
            **(existing or {}),
            "annotation_id": existing.get("annotation_id") if existing else self.annotation_state.next_annotation_id(),
            "segment_id": existing.get("segment_id") if existing else self.annotation_state.next_segment_id(),
            "annotation_type": layer,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "start_time_s": start_time,
            "end_time_s": end_time,
            "duration_s": max(0.0, end_time - start_time),
            "activity_state": activity_state,
            "camera_angle": camera_angle,
            "exercise": exercise,
            "set_id": set_id,
            "rep_id": rep_id,
            "phase": phase,
            "form_label": self.editor_form_label.currentText() if is_form else retained.get("form_label", "unlabeled"),
            "form_score": retained.get("form_score"),
            "issue_type": self.editor_issue_type.checked_values() if is_form else [],
            "error_category": self.editor_issue_category.checked_values() if is_form else [],
            "affected_joints": self.editor_affected_joints.checked_values() if is_form else [],
            "notes": self.editor_notes.toPlainText().strip() or None,
        }
        if layer == "set" and values["set_id"] is None:
            values["set_id"] = self._next_set_id_for_range(
                start_frame,
                end_frame,
                exclude_id=values["annotation_id"] if existing else None,
            )
        if layer == "rep" and values["rep_id"] is None:
            if values["set_id"] is None:
                QMessageBox.warning(self, "Repetition needs a set", "Choose a set number before saving a repetition.")
                return
            values["rep_id"] = self._next_rep_id_for_range(
                values["set_id"],
                start_frame,
                end_frame,
                exclude_id=values["annotation_id"] if existing else None,
            )
        if layer == "phase" and values["rep_id"] is None:
            QMessageBox.warning(self, "Phase needs a repetition", "Choose the parent set and repetition before saving a phase.")
            return
        try:
            if self._commit_annotation(values, existing):
                self._reset_annotation_draft()
                self.refresh_annotation_table(select_annotation_id=values["annotation_id"])
                self._refresh_summary()
                self.goto_frame(self.current_frame)
                self.editor_range_label.setText(f"Saved frames {start_frame}–{end_frame}. Press W for another entry.")
                self.annotation_status.setText(f"Saved {values['annotation_id']} / {values['segment_id']}.")
        except Exception as exc:
            LOGGER.exception("Embedded annotation save failed")
            QMessageBox.critical(self, "Annotation save failed", f"{type(exc).__name__}: {exc}")

    def _commit_annotation(self, values: dict, existing: dict | None = None) -> bool:
        """Keep the saved state intact if validation or the JSON write fails."""
        previous_state = self.annotation_state
        previous_save_failed = self._annotation_save_failed
        self.annotation_state = deepcopy(previous_state)
        saved = False
        try:
            if existing is None:
                self.annotation_state.add(values)
            else:
                self.annotation_state.replace(existing["annotation_id"], values)
                if {existing["annotation_type"], values["annotation_type"]} & {"set", "rep"}:
                    self._sync_descendant_contexts()
            effective_context, _ = self._context_for_frame(values["end_frame"])
            self.annotation_state.current_context.update(effective_context)
            saved = self._persist_annotations(show_error=True)
            return saved
        finally:
            if not saved:
                self.annotation_state = previous_state
                self._annotation_save_failed = previous_save_failed

    def edit_selected_annotation(self) -> None:
        """Arm an update only through the explicit edit command."""
        selected_id = self._selected_annotation_id()
        if selected_id is None:
            self.annotation_status.setText("Select a temporal annotation row before pressing A.")
            return
        if self.annotation_edit_id == selected_id:
            return
        annotation = next((item for item in self.annotations if item.get("annotation_id") == selected_id), None)
        if annotation is None:
            self.annotation_status.setText("The selected annotation no longer exists. Select another row.")
            return
        start_frame = int(annotation.get("start_frame", 0))
        end_frame = int(annotation.get("end_frame", start_frame))
        if not self._annotation_range_available(start_frame, end_frame):
            return
        if not self.goto_frame(start_frame):
            return
        self.annotation_edit_id = selected_id
        self.annotation_edit_end_frame = end_frame
        self.annotation_start_frame = start_frame

        layer_index = self.editor_annotation_type.findData(annotation.get("annotation_type"))
        if layer_index >= 0:
            self.editor_annotation_type.setCurrentIndex(layer_index)
        range_mode = "point" if start_frame == self.annotation_edit_end_frame else "interval"
        range_index = self.editor_range_mode.findData(range_mode)
        if range_index >= 0:
            self.editor_range_mode.setCurrentIndex(range_index)
        state = annotation.get("activity_state")
        if state in ACTIVITY_STATES:
            self.editor_activity_state.setCurrentText(str(state))
        camera_angle = str(annotation.get("camera_angle") or "N/A")
        camera_index = self.editor_camera_angle.findData(camera_angle)
        if camera_index >= 0:
            self.editor_camera_angle.setCurrentIndex(camera_index)
        self.editor_exercise_selector.set_value(annotation.get("exercise"))
        self.editor_set_id.setValue(int(annotation.get("set_id") or 0))
        self.editor_rep_id.setValue(int(annotation.get("rep_id") or 0))
        self._refresh_editor_options()
        phase = str(annotation.get("phase") or "none")
        if self.editor_phase.findData(phase) >= 0:
            self.editor_phase.setCurrentIndex(self.editor_phase.findData(phase))
        form_index = self.editor_form_label.findText(str(annotation.get("form_label") or "unlabeled"))
        if form_index >= 0:
            self.editor_form_label.setCurrentIndex(form_index)
        self.editor_issue_type.set_checked_values(annotation.get("issue_type", []))
        self.editor_issue_category.set_checked_values(annotation.get("error_category", []))
        self.editor_affected_joints.set_checked_values(annotation.get("affected_joints", []))
        self.editor_notes.setPlainText(str(annotation.get("notes") or ""))
        self.editor_range_label.setText(
            f"Editing {self.annotation_edit_id}: frames {start_frame}–{self.annotation_edit_end_frame}. "
            "Press S to update, D to cancel, or W to start a new range."
        )
        self.annotation_status.setText(
            f"Editing {self.annotation_edit_id}. Press S to update this row or D to cancel."
        )
        self.editor_save_button.setText("Update selected (S)")

    def _annotation_range_available(self, start_frame, end_frame):
        return True

    @staticmethod
    def _frame_in_annotation(annotation: dict, frame: int) -> bool:
        try:
            return int(annotation.get("start_frame", -1)) <= int(frame) <= int(annotation.get("end_frame", -1))
        except (TypeError, ValueError):
            return False

    def _context_for_frame(self, frame: int, exclude_id: str | None = None) -> tuple[dict, bool]:
        """Resolve reusable context from annotations covering a frame.

        This is intentionally a display/editor convenience only. It does not
        rewrite annotations while the user navigates. More-specific layers
        (phase, repetition, set) override broad activity coverage.
        """
        cache = getattr(self, "_frame_context_cache", None)
        if cache is None:
            cache = self._frame_context_cache = OrderedDict()
        if exclude_id is None and frame in cache:
            context, automatic = cache[frame]
            cache.move_to_end(frame)
            return dict(context), automatic

        matching = [
            item for item in self.annotations
            if self._frame_in_annotation(item, frame)
            and (exclude_id is None or str(item.get("annotation_id")) != str(exclude_id))
        ]
        if not matching:
            result = dict(self.annotation_state.current_context if self.annotation_state else {}), False
            if exclude_id is None:
                cache[frame] = result
                while len(cache) > 4096:
                    cache.popitem(last=False)
            return result

        # Form intervals are overlays.  They describe an issue at a frame but
        # must not replace the exercise hierarchy shown in the top context bar.
        matching = [item for item in matching if item.get("annotation_type") != "form_interval"]
        if not matching:
            result = dict(self.annotation_state.current_context if self.annotation_state else {}), False
            if exclude_id is None:
                cache[frame] = result
                while len(cache) > 4096:
                    cache.popitem(last=False)
            return result
        priority = {"general": 0, "activity_state": 1, "set": 2, "rep": 3, "phase": 4}
        resolved: dict = {}
        for item in sorted(matching, key=lambda value: priority.get(str(value.get("annotation_type")), 0)):
            if item.get("activity_state"):
                resolved["activity_state"] = item["activity_state"]
            for key in ("camera_angle", "exercise", "set_id", "rep_id", "phase"):
                value = item.get(key)
                if value not in (None, "", "none"):
                    resolved[key] = value
        if "activity_state" not in resolved and any(item.get("activity_state") == "active" for item in matching):
            resolved["activity_state"] = "active"
        result = resolved, True
        if exclude_id is None:
            cache[frame] = result
            while len(cache) > 4096:
                cache.popitem(last=False)
        return dict(resolved), True

    def _apply_context_to_editor(self, frame: int) -> None:
        """Fill the next annotation from the timeline without manual re-entry."""
        context, _ = self._context_for_frame(frame)
        if not context:
            return
        state = context.get("activity_state")
        if state in ACTIVITY_STATES:
            self.editor_activity_state.setCurrentText(str(state))
        if context.get("exercise"):
            self.editor_exercise_selector.set_value(str(context["exercise"]))
        set_id = context.get("set_id")
        if set_id is not None:
            self.editor_set_id.setValue(max(0, int(set_id)))
        rep_id = context.get("rep_id")
        if rep_id is not None:
            self.editor_rep_id.setValue(max(0, int(rep_id)))
        self._refresh_editor_options()
        phase = str(context.get("phase") or "none")
        if self.editor_phase.findData(phase) >= 0:
            self.editor_phase.setCurrentIndex(self.editor_phase.findData(phase))
        self.annotation_status.setText(
            f"Context reused from the timeline at frame {frame}. Press S to save or adjust it."
        )

    def _setup_shortcuts(self) -> None:
        def shortcut(sequence, callback):
            item = QShortcut(QKeySequence(sequence), self)
            item.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut if self._embedded else Qt.ShortcutContext.WindowShortcut)
            item.activated.connect(callback)
            return item
        self.shortcut_left = shortcut(Qt.Key.Key_Left, lambda: self.goto_frame(self.current_frame - 1))
        self.shortcut_right = shortcut(Qt.Key.Key_Right, lambda: self.goto_frame(self.current_frame + 1))
        self.shortcut_up = shortcut(Qt.Key.Key_Up, lambda: self.goto_frame(self.current_frame + self.frame_jump))
        self.shortcut_down = shortcut(Qt.Key.Key_Down, lambda: self.goto_frame(self.current_frame - self.frame_jump))
        self.shortcut_home = shortcut(Qt.Key.Key_Home, lambda: self.goto_frame(0))
        self.shortcut_end = shortcut(Qt.Key.Key_End, lambda: self.goto_frame(self.total_frames - 1))
        self.shortcut_annotate = shortcut("W", self.start_range_capture)
        self.shortcut_finish_annotation = shortcut("S", self.finish_embedded_annotation)
        self.shortcut_edit_annotation = shortcut("A", self.edit_selected_annotation)
        self.shortcut_cancel_edit = shortcut("D", self.cancel_annotation_edit)
        for item in (self.shortcut_annotate, self.shortcut_finish_annotation,
                     self.shortcut_edit_annotation, self.shortcut_cancel_edit):
            item.setAutoRepeat(False)
        self.shortcut_save = shortcut("Ctrl+S", self.save_annotations)
        self.shortcut_rep_analysis = shortcut("R", self.analyze_current_active_segment)
        self._navigation_shortcuts = [
            self.shortcut_left, self.shortcut_right, self.shortcut_up,
            self.shortcut_down, self.shortcut_home, self.shortcut_end,
        ]
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._update_navigation_shortcuts)
            app.installEventFilter(self)
            self._navigation_hooks_installed = True
        self._update_navigation_shortcuts(None, self.focusWidget())

    def _update_navigation_shortcuts(self, _old, focused) -> None:
        """Let text/edit controls consume arrows; restore frame navigation outside them."""
        text_control = isinstance(focused, (QLineEdit, QTextEdit, QComboBox, QAbstractSpinBox))
        for item in getattr(self, "_navigation_shortcuts", []):
            item.setEnabled(not text_control)
        if focused is not None and (
            self.annotation_editor_container.isAncestorOf(focused)
            or focused is self.annotation_table or self.annotation_table.isAncestorOf(focused)
        ):
            self.playback.pause()

    def eventFilter(self, watched, event):
        # The application-wide mouse filter must leave other windows' focus alone.
        if QApplication.activeWindow() is not self.window() or not self.isVisible():
            return super().eventFilter(watched, event)
        if self._embedded and (not isinstance(watched, QWidget) or not self.isAncestorOf(watched)):
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.MouseButtonPress:
            focused = QApplication.focusWidget()
            if not isinstance(focused, (QLineEdit, QTextEdit, QComboBox, QAbstractSpinBox)):
                self.setFocus(Qt.FocusReason.MouseFocusReason)
        return super().eventFilter(watched, event)

    def _row_for_frame(self, frame: int) -> pd.Series:
        if self.dataframe.empty:
            raise ValueError("Feature DataFrame is empty.")
        frame = max(0, min(int(frame), self.total_frames - 1))
        row = self.dataframe.iloc[frame]
        if row["frame_id"] == frame:
            return row
        matches = self.dataframe.index[self.dataframe["frame_id"] == frame]
        if len(matches):
            return self.dataframe.loc[matches[0]]
        return row

    def goto_frame(self, frame_number: int) -> bool:
        self._deferred_linked_frame = None
        self.playback.pause(refresh=False)
        return self._show_frame(frame_number)

    def _show_frame(self, frame_number: int) -> bool:
        frame_number = max(0, min(int(frame_number), max(0, self.total_frames - 1)))
        self._frame_buffer.request(frame_number, playback=self.playback.playing, direction=self.playback.direction)
        ok, frame = self._frame_buffer.read(self.cap, frame_number)
        if not ok:
            self._sync_frame_position(self.current_frame)
            self.annotation_status.setText(f"Could not decode video frame {frame_number}.")
            return False
        self._present_frame(frame_number, frame)
        return True

    def _sync_frame_position(self, frame_number):
        with QSignalBlocker(self.frame_spin):
            self.frame_spin.setValue(frame_number)
        if self.frame_slider is not None:
            with QSignalBlocker(self.frame_slider):
                self.frame_slider.setValue(frame_number)

    def _present_frame(self, frame_number, frame=None, *, playing=None):
        self.current_frame = frame_number
        self._sync_frame_position(frame_number)
        row = self._row_for_frame(frame_number)
        playing = self.playback.playing if playing is None else playing
        if frame is not None:
            image = QImage(frame.data, frame.shape[1], frame.shape[0], frame.strides[0], QImage.Format.Format_BGR888)
            self._current_video_pixmap = QPixmap.fromImage(image)
        self._render_video_pixmap(row, playing=playing)
        self.current_frame_context_label.setText(self._frame_info(row))
        now = monotonic()
        update_status = not playing or now - getattr(self, "_last_playback_status_at", 0.0) >= 0.1
        if update_status:
            self._last_playback_status_at = now
            self._refresh_context_label()
        if not playing and self.annotation_edit_id is None:
            self._populate_inherited_editor_values()
        self._sync_linked_graph_frame(playing=playing)

    def _refresh_paused_frame(self) -> None:
        if self.annotation_edit_id is None:
            self._populate_inherited_editor_values()

    def _render_video_pixmap(self, row: pd.Series | None = None, *, playing: bool | None = None) -> None:
        """Fit the cached frame to the current pane without changing layout."""
        if (
            self._current_video_pixmap is None
            or not hasattr(self, "video_label")
            or self.video_label.size().isEmpty()
        ):
            return
        playing = self.playback.playing if playing is None else playing
        display = self._current_video_pixmap.scaled(
            self.video_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            (Qt.TransformationMode.FastTransformation if playing
             else Qt.TransformationMode.SmoothTransformation),
        )
        self._paint_overlays(display, row)
        self.video_label.setPixmap(display)
        self._mirrored_overlay_dirty = False

    def _paint_overlays(self, display, row=None):
        body = self.skeleton_button.isChecked() and not self._baked
        midpoints = self.midpoint_button.isChecked() and not self._midpoints_baked
        if body or midpoints or self.overlay_button.isChecked():
            row = self._row_for_frame(self.current_frame) if row is None else row
        if body or midpoints:
            paint_skeleton(display, row, draw_body=body, draw_centerline=midpoints)
        if self.overlay_button.isChecked():
            traces = self._mirrored_angle_traces if self.mirror_angles_button.isChecked() else self._default_angle_traces
            paint_angle_labels(display, frame_angle_labels(row, traces))

    def resizeEvent(self, event) -> None:
        # Re-render only the cached image.  No splitter sizes or widget
        # geometry are changed here, so maximizing/restoring or clicking a
        # control cannot create the small layout shifts seen previously.
        super().resizeEvent(event)
        self._render_video_pixmap()

    def _frame_info(self, row: pd.Series) -> str:
        return (
            f"Session: {self.metadata.get('session_id', row.get('session_id', ''))} | "
            f"Video: {self.metadata.get('video_id', row.get('video_id', ''))} | "
            f"Participant: {self.metadata.get('participant_id', row.get('participant_id', ''))} | "
            f"Camera: {self.metadata.get('camera_id', row.get('camera_id', ''))} | "
            f"Frame: {int(row['frame_id'])} / {self.total_frames - 1} | "
            f"Time: {float(row['timestamp_s']):.3f}s | FPS: {self.fps:.3f}"
        )

    def _refresh_context_label(self):
        context, automatic = self._context_for_frame(self.current_frame)
        self.context_label.setText(
            f"{'Frame context' if automatic else 'Session defaults'}: "
            f"State: {context.get('activity_state') or '—'} | "
            f"Exercise: {context.get('exercise') or '—'} | "
            f"Set: {context.get('set_id') or '—'} | "
            f"Last rep: {context.get('rep_id') or '—'}"
        )

    def _refresh_summary(self):
        if hasattr(self, "_frame_context_cache"):
            self._frame_context_cache.clear()
        state = self.annotation_state.to_document() if self.annotation_state else {"annotations": []}
        warnings = annotation_warning_details(state, self.total_frames)
        self.annotation_model.set_warnings(warnings)
        # Validated activity intervals are disjoint. Count their lengths
        # instead of allocating a set with an entry for every covered frame.
        covered = active_covered = 0
        for item in self.annotations:
            if item.get("annotation_type") == "activity_state":
                length = int(item["end_frame"]) - int(item["start_frame"]) + 1
                covered += length
                if item.get("activity_state") == "active":
                    active_covered += length
        reps = build_rep_summary(state)
        coverage = covered / max(1, self.total_frames)
        active_coverage = active_covered / max(1, self.total_frames)
        status = self.annotation_state.status if self.annotation_state else "unknown"
        self.summary_label.setText(
            f"Annotations: {len(self.annotations)} | Reps: {len(reps)} | "
            f"Activity coverage: {coverage:.1%} | Active coverage: {active_coverage:.1%} | "
            f"Session status: {status} | Warnings: {len(warnings)}"
        )
        self.summary_label.setToolTip("\n".join(warning.message for warning in warnings))
        self._refresh_context_label()

    def _next_rep_id_from_context(self) -> int | None:
        context = self.annotation_state.current_context if self.annotation_state else {}
        set_id = context.get("set_id")
        if set_id is None:
            return None
        return self.annotation_state.next_rep_id(int(set_id)) if self.annotation_state else None

    def open_context_dialog(self):
        self.playback.pause()
        dialog = QDialog(self)
        dialog.setWindowTitle("Set annotation context")
        form = QFormLayout(dialog)
        state_combo = QComboBox(); state_combo.addItems(sorted(ACTIVITY_STATES))
        exercise_selector = ExerciseSelector(
            dialog,
            str(self.annotation_state.current_context.get("exercise", "") if self.annotation_state else ""),
        )
        set_spin = QSpinBox(); set_spin.setRange(0, 10_000); set_spin.setSpecialValueText("N/A"); set_spin.setValue(int(self.annotation_state.current_context.get("set_id") or 0) if self.annotation_state else 0)
        _state = self.annotation_state.current_context.get("activity_state") if self.annotation_state else "active"
        if _state in ACTIVITY_STATES: state_combo.setCurrentText(_state)
        form.addRow("Activity state", state_combo)
        form.addRow("Movement type", exercise_selector.movement_type)
        form.addRow("Exercise name", exercise_selector.exercise_name)
        form.addRow("New exercise", exercise_selector.custom_exercise)
        form.addRow("Exercise variation", exercise_selector.exercise_variation)
        form.addRow("Set ID", set_spin)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.annotation_state.set_context(
                activity_state=state_combo.currentText(),
                exercise=exercise_selector.value(),
                set_id=set_spin.value() if set_spin.value() >= 1 else None,
            )
            if hasattr(self, "_frame_context_cache"):
                self._frame_context_cache.clear()
            self._persist_annotations(show_error=True)
            self._refresh_context_label()

    def start_range_capture(self):
        self.playback.pause()
        if self.annotation_edit_id is not None:
            self._discard_annotation_edit()
        self.annotation_table.selectionModel().clear()
        self._apply_context_to_editor(self.current_frame)
        if self.editor_annotation_type.currentData() == "set":
            context, _ = self._context_for_frame(self.current_frame)
            # Set IDs are local to the current Activity interval.  When
            # this frame is not already inside a set, start at N/A/0.
            if context.get("set_id") is None:
                self.editor_set_id.setValue(0)
        self.annotation_start_frame = self.current_frame
        if hasattr(self, "editor_range_mode") and self.editor_range_mode.currentData() == "point":
            self.editor_range_label.setText(f"Point captured at frame {self.current_frame}. Press S to save it.")
        else:
            self.editor_range_label.setText(f"Start captured at frame {self.current_frame}. Navigate, then press S to save.")
        self.annotation_status.setText(
            f"Capturing range from frame {self.current_frame}. Use ←/→ or ±Jump, then press S."
        )

    def set_range_status(self, start_frame: int, end_frame: int):
        start_time = float(self._row_for_frame(start_frame)["timestamp_s"])
        end_time = float(self._row_for_frame(end_frame)["timestamp_s"])
        self.annotation_status.setText(
            f"Capturing range: {start_frame}–{end_frame} ({start_time:.3f}s–{end_time:.3f}s). Press S to finish."
        )

    def cancel_range_capture(self):
        self._reset_annotation_draft()
        self.range_capture = None
        self.annotation_status.setText("Range cancelled. Press W to start a new range.")

    def complete_range_capture(self, start_frame: int, end_frame: int):
        self._reset_annotation_draft()
        self.range_capture = None
        start_time = float(self._row_for_frame(start_frame)["timestamp_s"])
        end_time = float(self._row_for_frame(end_frame)["timestamp_s"])
        context = self.annotation_state.current_context if self.annotation_state else {}
        defaults = {"exercise": self.metadata.get("exercise_hint", "")}
        segment_id = self.annotation_state.next_segment_id()
        dialog = AnnotationDialog(
            start_frame, end_frame, start_time, end_time, context, self,
            defaults=defaults, segment_id=segment_id,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.annotation_status.setText("Range captured but not labeled. Press W to start another range.")
            return

        values = dialog.values()
        layer = values["annotation_type"]
        if layer == "set" and values["set_id"] is None:
            values["set_id"] = self._next_set_id_for_range(start_frame, end_frame)
        if layer == "rep" and values["rep_id"] is None:
            if values["set_id"] is None:
                QMessageBox.warning(self, "Repetition needs a set", "Choose a set number before saving a repetition.")
                return
            values["rep_id"] = self._next_rep_id_for_range(values["set_id"], start_frame, end_frame)
        if layer == "phase" and values["rep_id"] is None:
            QMessageBox.warning(self, "Phase requires repetition", "Enter or choose an existing repetition before saving a phase.")
            return
        values["annotation_id"] = self.annotation_state.next_annotation_id()
        values["segment_id"] = segment_id
        values["duration_s"] = max(0.0, end_time - start_time)
        try:
            if self._commit_annotation(values):
                self.refresh_annotation_table(select_annotation_id=values["annotation_id"])
                self._refresh_summary()
                self.annotation_status.setText(
                    f"Saved {values['annotation_id']} / {segment_id}: frames {start_frame}–{end_frame}. Press W for another range."
                )
        except Exception as exc:
            LOGGER.exception("Annotation checkpoint failed")
            QMessageBox.critical(self, "Annotation checkpoint failed", f"{type(exc).__name__}: {exc}")

    def _effective_annotation_for_display(self, annotation: dict) -> dict:
        """Return table values with parent context filled into child rows."""
        display = dict(annotation)
        kind = str(annotation.get("annotation_type"))
        if kind in {"set", "rep", "phase", "form_interval"}:
            context, _ = self._context_for_frame(
                int(annotation.get("start_frame", 0)),
                exclude_id=str(annotation.get("annotation_id")),
            )
            for key in ("camera_angle", "exercise", "set_id", "rep_id", "phase"):
                if display.get(key) in (None, "", "none") and context.get(key) not in (None, "", "none"):
                    display[key] = context[key]
            if not display.get("activity_state") and context.get("activity_state"):
                display["activity_state"] = context["activity_state"]
        return display

    def _refresh_annotation_layer(self):
        self.refresh_annotation_table(select_annotation_id=self._selected_annotation_id())

    def refresh_annotation_table(self, select_annotation_id: str | None = None):
        columns = [
            "Annotation ID", "Segment ID", "Layer", "Boundary", "Start frame", "End frame",
            "Start time (s)", "End time (s)", "Duration (s)", "Activity", "Movement type",
            "Camera angle", "Exercise name", "Set", "Rep", "Phase", "Form", "Form score", "Notes",
            "Issue type", "Issue category", "Affected joints",
        ]
        layer = self.editor_annotation_type.currentData()
        show_all = self.show_all_annotation_layers.isChecked()
        # Keep the row being edited visible if the user changes its layer.
        visible = [item for item in self.annotations if show_all or item.get("annotation_type") == layer
                   or item.get("annotation_id") == self.annotation_edit_id]
        rows = []
        for annotation in visible:
            display = self._effective_annotation_for_display(annotation)
            movement_type, exercise_name = exercise_ui_values(display.get("exercise"))
            start_frame = int(display.get("start_frame", 0))
            end_frame = int(display.get("end_frame", start_frame))
            row = {
                "Annotation ID": display.get("annotation_id"),
                "Segment ID": display.get("segment_id"),
                "Layer": _LAYER_LABELS.get(str(display.get("annotation_type")), "N/A"),
                "Boundary": "Single frame" if start_frame == end_frame else "Frame interval",
                "Start frame": start_frame,
                "End frame": end_frame,
                "Start time (s)": display.get("start_time_s"),
                "End time (s)": display.get("end_time_s"),
                "Duration (s)": display.get("duration_s"),
                "Activity": display.get("activity_state"),
                "Movement type": movement_type or "N/A",
                "Camera angle": display.get("camera_angle") or "N/A",
                "Exercise name": exercise_name or "N/A",
                "Set": display.get("set_id"),
                "Rep": display.get("rep_id"),
                "Phase": display.get("phase"),
                "Form": display.get("form_label"),
                "Form score": display.get("form_score"),
                "Notes": display.get("notes"),
                "Issue type": _format_issue_types(display.get("issue_type")),
                "Issue category": _format_values(display.get("error_category")),
                "Affected joints": _format_values(display.get("affected_joints")),
            }
            # Display-only marker: the persisted annotation remains JSON null
            # for fields that do not apply to activity/general intervals.
            for key in ("Set", "Rep", "Phase"):
                if row.get(key) is None:
                    row[key] = "N/A"
            if row.get("Phase") == "none":
                row["Phase"] = "N/A"
            if not row.get("Issue category"):
                row["Issue category"] = "N/A"
            if not row.get("Affected joints"):
                row["Affected joints"] = "N/A"
            rows.append(row)
        with QSignalBlocker(self.annotation_table.selectionModel()):
            self.annotation_model.set_dataframe(pd.DataFrame(rows, columns=columns))
            if select_annotation_id:
                row = next(
                    (index for index, item in enumerate(visible) if item.get("annotation_id") == select_annotation_id),
                    None,
                )
                if row is not None:
                    self.annotation_table.selectRow(row)
                    self.annotation_table.scrollTo(self.annotation_model.index(row, 0))
        self._refresh_annotation_actions()

    def _persist_annotations(self, *, show_error: bool) -> bool:
        if self.annotation_state is None:
            return False
        document = self.annotation_state.to_document()
        try:
            self._check_annotation_revision()
            validate_annotations(document, len(self.dataframe))
            # JSON is authoritative. A failed derived Parquet export must never erase it.
            save_json_atomic(document, self.annotation_json_path)
        except AnnotationFileChangedError as exc:
            self._annotation_save_failed = False
            if show_error:
                QMessageBox.critical(self, "Annotation file changed", str(exc))
            return False
        except Exception as exc:
            self._annotation_save_failed = True
            LOGGER.exception("Annotation JSON persistence failed")
            if show_error:
                QMessageBox.critical(self, "Annotation save failed", f"Could not save the JSON source of truth.\n\n{type(exc).__name__}: {exc}")
            return False
        self._saved_annotation_document = deepcopy(document)
        self._annotation_save_failed = False
        viewer = self.annotation_graph_window or self._linked_graph_viewer
        if viewer is not None:
            viewer._refresh_graph_annotations(viewer.graph)
        self._export_annotation_derivatives(document, show_error=show_error)
        return True

    def _export_annotation_derivatives(self, document, *, show_error):
        try:
            save_annotation_parquet(document, self.annotation_parquet_path)
            if self.rep_summary_path.resolve() == self.annotation_json_path.resolve():
                raise RuntimeError("Derived repetition summary path must not equal the annotation source path")
            save_json_atomic({"schema_version": "1.0", "source": "derived_from_annotations.json", "repetitions": build_rep_summary(document)}, self.rep_summary_path)
        except Exception as exc:
            LOGGER.exception("Derived annotation export failed")
            if show_error:
                QMessageBox.warning(self, "Derived export warning", f"Annotations were saved to JSON, but a derived file could not be updated.\n\n{type(exc).__name__}: {exc}")

    def save_annotations(self):
        if self._persist_annotations(show_error=True):
            self.refresh_annotation_table(select_annotation_id=self._selected_annotation_id())
            self._refresh_summary()
            self.annotation_status.setText(f"Saved JSON source of truth: {self.annotation_json_path.name}")

    def mark_session_complete(self):
        if not self.annotations:
            QMessageBox.warning(self, "No annotations", "Add activity-state annotations before marking the session complete.")
            return
        warnings = annotation_warnings(self.annotation_state.to_document(), self.total_frames)
        message = "Mark the annotation session complete?"
        if warnings:
            message += f"\n\nThere are {len(warnings)} non-fatal warning(s). You can still complete the session."
        result = QMessageBox.question(self, "Complete annotation session", message)
        if result != QMessageBox.StandardButton.Yes:
            return
        self.annotation_state.status = "completed"
        if self._persist_annotations(show_error=True):
            self._refresh_summary()
            self.annotation_status.setText("Annotation session marked complete.")

    def analyze_current_active_segment(self):
        self.playback.pause()
        active = [
            item for item in self.annotations
            if item.get("annotation_type") == "activity_state"
            and item.get("activity_state") == "active"
            and int(item["start_frame"]) <= self.current_frame <= int(item["end_frame"])
        ]
        if not active:
            QMessageBox.information(self, "Rep analysis", "The current frame is not inside a manually annotated active segment. Mark the activity-state segment first.")
            return
        item = active[-1]
        config = load_config(PROJECT_ROOT / "configs" / "config.json")
        detector = RepDetector.from_config(config)
        wanted = {"frame_id", "timestamp_s", "fps", *detector.config.signal_candidates}
        stem = self.annotation_json_path.stem
        suggestions_stem = stem.removesuffix("_annotations") + "_rep_suggestions"
        suggestions_path = self.annotation_json_path.with_name(suggestions_stem + ".json")
        try:
            if suggestions_path.resolve() == self.annotation_json_path.resolve():
                raise ValueError("The suggestions path points to the annotation file.")
            segment = pd.read_parquet(
                self.parquet_path, columns=[name for name in self._feature_columns if name in wanted],
                filters=[("frame_id", ">=", int(item["start_frame"])), ("frame_id", "<=", int(item["end_frame"]))],
            )
            labeled = annotation_to_frame_targets(segment, self.annotation_state.to_document())
            detection = detector.detect_segment(labeled, activity_state="active")
            save_rep_suggestions(detection, suggestions_path)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Rep analysis unavailable", str(error))
            return
        self.annotation_status.setText(
            f"Rep analysis suggests {detection.count} candidate cycle(s). Suggestions saved separately and did not alter annotations."
        )
        QMessageBox.information(
            self, "Rep analysis",
            f"Candidate repetitions: {detection.count}\n\n"
            f"Saved to: {suggestions_path}\n\n"
            "These are analysis suggestions only. Manual annotations remain ground truth."
        )

    def closeEvent(self, event):
        self.playback.pause(refresh=False)
        if self._annotation_save_failed and not self._confirm_pending_save():
            event.ignore()
            return
        if self.annotation_start_frame is not None:
            choice = QMessageBox.question(
                self, "Leave the annotation editor?",
                "An annotation range is open. Leave and discard any unsubmitted edits?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if choice != QMessageBox.StandardButton.Discard:
                event.ignore()
                return
        if self.annotation_graph_window is not None:
            self.annotation_graph_window.close()
        self._unlink_graph_viewer()
        app = QApplication.instance()
        if app is not None and getattr(self, "_navigation_hooks_installed", False):
            app.removeEventFilter(self)
            app.focusChanged.disconnect(self._update_navigation_shortcuts)
            self._navigation_hooks_installed = False
        if self.range_capture is not None:
            self.range_capture.close()
        self._close_video()
        self._current_video_pixmap = None
        event.accept()
        self.closed.emit()

    def _confirm_pending_save(self):
        if self._annotation_save_failed:
            choice = QMessageBox.warning(
                self, "Annotations could not be saved",
                "Retry saving the annotation changes before leaving?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if (choice == QMessageBox.StandardButton.Cancel
                    or (choice == QMessageBox.StandardButton.Save and not self._persist_annotations(show_error=True))):
                return False
            self._annotation_save_failed = False
        return True


def open_annotation_studio(parent=None, video_path=None, parquet_path=None, *,
                           metadata_path=None, annotation_json_path=None,
                           frame_jump=DEFAULT_FRAME_JUMP):
    if video_path is None:
        video_path, _ = QFileDialog.getOpenFileName(parent, "Select processed skeleton video", "", "Video Files (*.mp4 *.mov *.avi *.mkv);;All Files (*)")
        if not video_path:
            return
    if parquet_path is None:
        parquet_path, _ = QFileDialog.getOpenFileName(parent, "Select feature Parquet", "", "Parquet (*.parquet);;All Files (*)")
        if not parquet_path:
            return
    window = AnnotationStudio(
        video_path, parquet_path, annotation_json_path=annotation_json_path,
        metadata_path=metadata_path, parent=parent, frame_jump=frame_jump,
    )
    # Qt resolves this against the active monitor's available work area.  It
    # avoids the previous 1450x920 hard-coded geometry and keeps the splitter
    # proportions stable when the user starts navigating or editing fields.
    window.showMaximized()
    return window
