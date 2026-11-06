from __future__ import annotations

from collections import OrderedDict
import logging
import sys
from pathlib import Path

import cv2
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from PyQt6.QtCore import QEvent, QTimer, Qt
from PyQt6.QtGui import QColor, QImage, QKeySequence, QPixmap, QShortcut, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QDockWidget, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QScrollArea,
    QPushButton, QDoubleSpinBox, QSpinBox, QSplitter, QTableView, QTextEdit, QSizePolicy,
    QVBoxLayout, QWidget,
)

from aihumo.annotations import (
    ACTIVITY_STATES,
    ANNOTATION_TYPES,
    AnnotationState,
    annotation_to_frame_targets,
    annotation_warnings,
    build_rep_summary,
    validate_annotations,
    save_annotation_parquet,
)
from aihumo.config import load_config
from aihumo.rep_detection import RepDetector, save_rep_suggestions
from aihumo.storage import load_json, save_json_atomic
from aihumo.exercise_library import (
    exercise_options,
    exercise_ui_values,
    get_exercise,
    movement_type_options,
)
from .common import DataFrameModel
from .joint_graph import JointGraphWidget

LOGGER = logging.getLogger("AIHuMoDataStudio.Mode1")

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
        self.movement_type.currentIndexChanged.connect(self._refresh_exercises)
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

    def set_value(self, value: str | None) -> None:
        if not value:
            # An annotation may intentionally have no exercise. Clear stale
            # selections from the previously edited row instead of leaving a
            # misleading exercise name visible in the editor.
            self.movement_type.setCurrentIndex(0)
            self._refresh_exercises()
            self.exercise_name.setCurrentIndex(0)
            return
        movement_type, exercise_label = exercise_ui_values(value)
        if movement_type:
            movement_index = self.movement_type.findData(movement_type)
            if movement_index >= 0:
                self.movement_type.setCurrentIndex(movement_index)
        self._refresh_exercises()
        exercise_id = str(value).strip()
        exercise_index = self.exercise_name.findData(exercise_id)
        if exercise_index < 0:
            exercise_index = self.exercise_name.findText(exercise_label)
        if exercise_index >= 0:
            self.exercise_name.setCurrentIndex(exercise_index)

    def value(self) -> str | None:
        return self.exercise_name.currentData() or None


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
        form.addRow("Movement type", self.exercise_selector.movement_type)
        form.addRow("Exercise name", self.exercise_selector.exercise_name)
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
        self.exercise_selector.movement_type.setEnabled(is_set)
        self.exercise_selector.exercise_name.setEnabled(is_set)
        self.set_id.setEnabled(is_set)
        self.rep_id.setEnabled(is_rep)
        self.auto_rep_id.setEnabled(is_rep)
        self.phase.setEnabled(is_phase)
        self.form_label.setEnabled(False)
        self.form_score_enabled.setEnabled(False)
        self.form_score.setEnabled(False)
        self.issue_type.setEnabled(is_form)
        self.error_category.setEnabled(is_form)
        self.affected_joints.setEnabled(is_form)
        if not is_form:
            self.issue_type.set_checked_values([])
            self.error_category.set_checked_values([])
            self.affected_joints.set_checked_values([])
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
            "exercise": self.exercise_selector.value() if layer == "set" else None,
            "phase": self.phase.currentData() if layer == "phase" else "none",
            "rep_id": None if layer != "rep" or self.rep_id.value() < 1 else self.rep_id.value(),
            "set_id": None if layer != "set" or self.set_id.value() < 1 else self.set_id.value(),
            "form_label": "unlabeled",
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


class AnnotationStudio(QMainWindow):
    """Mode 1: manual activity-state segments plus nested reps/phases."""

    def __init__(self, video_path: str | Path, parquet_path: str | Path, annotation_json_path: str | Path | None = None, metadata_path: str | Path | None = None, parent=None):
        super().__init__(parent)
        self.video_path = Path(video_path)
        self.parquet_path = Path(parquet_path)
        default_annotation_dir = self.parquet_path.parent.parent / "annotations"
        default_annotation_name = self.parquet_path.stem.replace("_features", "_annotations") + ".json"
        self.annotation_json_path = Path(annotation_json_path) if annotation_json_path else default_annotation_dir / default_annotation_name
        self.annotation_parquet_path = self.annotation_json_path.with_suffix(".parquet")
        rep_summary_stem = self.annotation_json_path.stem.replace("_annotations", "_rep_summary")
        if rep_summary_stem == self.annotation_json_path.stem:
            rep_summary_stem = f"{rep_summary_stem}_rep_summary"
        self.rep_summary_path = self.annotation_json_path.with_name(rep_summary_stem + ".json")
        self.metadata_path = Path(metadata_path) if metadata_path else self.parquet_path.with_name(self.parquet_path.stem.replace("_features", "_metadata") + ".json")
        self.dataframe = pd.read_parquet(self.parquet_path)
        if self.dataframe.empty:
            raise ValueError(f"Feature Parquet is empty: {self.parquet_path}")
        if "frame_id" not in self.dataframe.columns or not self.dataframe["frame_id"].is_monotonic_increasing:
            raise ValueError("Feature Parquet frame_id must be present and ordered for synchronized navigation.")
        self.metadata = load_json(self.metadata_path) if self.metadata_path.exists() else {}
        self.annotation_state: AnnotationState | None = None
        self.current_frame = 0
        self.total_frames = 0
        self._current_video_pixmap: QPixmap | None = None
        # The thumbnail strip is a five-slot sliding window, not a slideshow.
        # Keep a small LRU cache of already scaled thumbnails so stepping back
        # and forth does not seek/decode the same frames repeatedly.
        self._thumbnail_cache: OrderedDict[int, QPixmap] = OrderedDict()
        self._thumbnail_cache_limit = 21
        self._thumbnail_size = (132, 82)
        self._thumbnail_placeholder = QPixmap(*self._thumbnail_size)
        self._thumbnail_placeholder.fill(QColor("#20242b"))
        self._layout_initialized = False
        self.range_capture: RangeCaptureDialog | None = None
        self.annotation_start_frame: int | None = None
        self.cap = cv2.VideoCapture(str(self.video_path))
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open processed video: {self.video_path}")
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or len(self.dataframe))
        if self.total_frames != len(self.dataframe):
            raise ValueError(
                f"Video/feature frame mismatch: video={self.total_frames}, features={len(self.dataframe)}. "
                "Choose the matching processed video and canonical feature Parquet."
            )
        self.fps = float(self.cap.get(cv2.CAP_PROP_FPS) or self.metadata.get("source_fps", 30.0))
        # Keyboard navigation is deliberately independent of source FPS.
        # Left/Right = one frame; Up/Down = this configurable jump.
        self.frame_jump = 15
        self._load_annotations()
        self._build_ui()
        self._setup_shortcuts()
        resume_frame = self.annotation_state.last_completed_frame if self.annotation_state else 0
        resume_frame = max(0, min(int(resume_frame or 0), max(0, self.total_frames - 1)))
        self.goto_frame(resume_frame)
        self._refresh_summary()

    def _load_annotations(self) -> None:
        metadata = dict(self.metadata)
        for key in ("session_id", "video_id", "participant_id", "camera_id"):
            if key not in metadata and key in self.dataframe.columns:
                metadata[key] = str(self.dataframe[key].iloc[0])
        metadata.setdefault("features_parquet", str(self.parquet_path))
        metadata.setdefault("processed_video", str(self.video_path))
        if self.annotation_json_path.exists():
            self.annotation_state = AnnotationState.load(self.annotation_json_path, metadata)
            validate_annotations(self.annotation_state.to_document(), len(self.dataframe))
        else:
            self.annotation_state = AnnotationState.new(metadata)
            self._add_initial_setup_interval_if_untracked()
            self._persist_annotations(show_error=False)

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
        self.setMinimumSize(960, 640)
        central = QWidget()
        main = QVBoxLayout(central)

        header = QHBoxLayout()
        header.addWidget(QLabel("Mode 1 Annotation Studio"), 1)
        self.frame_spin = QSpinBox()
        self.frame_spin.setRange(0, max(0, self.total_frames - 1))
        self.frame_spin.valueChanged.connect(self.goto_frame)
        header.addWidget(QLabel("Frame"))
        header.addWidget(self.frame_spin)
        header.addWidget(QLabel("Jump"))
        self.jump_spin = QSpinBox()
        self.jump_spin.setRange(1, 10000)
        self.jump_spin.setValue(self.frame_jump)
        self.jump_spin.valueChanged.connect(lambda value: setattr(self, "frame_jump", int(value)))
        self.jump_spin.setToolTip("Frames moved by Up/Down and the −Jump/+Jump buttons.")
        header.addWidget(self.jump_spin)
        self.graph_toggle_button = QPushButton("Joint graphs")
        self.graph_toggle_button.setCheckable(True)
        self.graph_toggle_button.setToolTip(
            "Show all registered joint-angle graphs from the canonical feature Parquet."
        )
        header.addWidget(self.graph_toggle_button)
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
        left_layout = QVBoxLayout(left)
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
        self.thumbnail_row = QHBoxLayout()
        self.thumbnail_labels: list[QLabel] = []
        for _ in range(5):
            label = QLabel()
            # Permanent slots prevent frame 0 (where two neighbors are out of
            # range) from changing the row's size hint when those slots later
            # receive real images.
            label.setFixedSize(*self._thumbnail_size)
            label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("border: 1px solid #9aa4b2; background: #20242b;")
            label.setPixmap(self._thumbnail_placeholder)
            self.thumbnail_labels.append(label)
            self.thumbnail_row.addWidget(label)
        self.thumbnail_row.addStretch(1)
        left_layout.addLayout(self.thumbnail_row)
        controls = QHBoxLayout()
        for text, callback in [
            ("◀", lambda: self.goto_frame(self.current_frame - 1)),
            ("▶", lambda: self.goto_frame(self.current_frame + 1)),
            ("−Jump", lambda: self.goto_frame(self.current_frame - self.frame_jump)),
            ("+Jump", lambda: self.goto_frame(self.current_frame + self.frame_jump)),
            ("Home", lambda: self.goto_frame(0)),
            ("End", lambda: self.goto_frame(self.total_frames - 1)),
            ("Mark segment (W)", self.start_range_capture),
            ("Rep analysis (R)", self.analyze_current_active_segment),
        ]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            controls.addWidget(button)
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
        annotations_layout.addWidget(QLabel("Temporal annotations"))
        self.annotation_model = DataFrameModel()
        self.annotation_table = QTableView()
        self.annotation_table.setModel(self.annotation_model)
        self.annotation_table.setAlternatingRowColors(True)
        self.annotation_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.annotation_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.annotation_table.clicked.connect(self._load_selected_annotation)
        # Header + three normal table rows, with a little breathing room.
        self.annotation_table.setMinimumHeight(180)
        self.annotation_table.setToolTip(
            "Click an annotation row to load it into the editor. "
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
        self.joint_graph_widget = JointGraphWidget(self.dataframe, self)
        self.joint_graph_widget.frameSelected.connect(self.goto_frame)
        self.graph_dock = QDockWidget("Joint graphs", self)
        self.graph_dock.setObjectName("JointGraphsDock")
        self.graph_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.graph_dock.setWidget(self.joint_graph_widget)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.graph_dock)
        self.graph_dock.hide()
        self.graph_toggle_button.toggled.connect(self.graph_dock.setVisible)
        self.graph_dock.visibilityChanged.connect(self.graph_toggle_button.setChecked)
        self.refresh_annotation_table()

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
        self.editor_auto_context = QCheckBox("Auto-fill from timeline")
        self.editor_auto_context.setChecked(True)
        self.editor_auto_context.setToolTip(
            "When W starts a new annotation, reuse the activity, exercise, set, "
            "rep, and phase context already covering the current frame."
        )
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
        form.addRow("Movement type", self.editor_exercise_selector.movement_type)
        form.addRow("Exercise name", self.editor_exercise_selector.exercise_name)
        form.addRow("Context", self.editor_auto_context)
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
        buttons.addWidget(QPushButton("Start / reset (W)", clicked=self.start_range_capture))
        self.editor_save_button = QPushButton("Save range (S)")
        self.editor_save_button.clicked.connect(self.finish_embedded_annotation)
        buttons.addWidget(self.editor_save_button)
        clear_button = QPushButton("Clear selected")
        clear_button.setToolTip("Delete the selected temporal annotation. Editor fields are left unchanged.")
        clear_button.clicked.connect(self.clear_embedded_annotation)
        buttons.addWidget(clear_button)
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
        self.editor_form_label.setEnabled(False)
        self.editor_issue_type.setEnabled(is_form)
        self.editor_issue_category.setEnabled(is_form)
        self.editor_affected_joints.setEnabled(is_form)
        if not is_form:
            self.editor_form_label.setCurrentText("unlabeled")
            self.editor_issue_type.set_checked_values([])
            self.editor_issue_category.set_checked_values([])
            self.editor_affected_joints.set_checked_values([])
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
            exclude_id=getattr(self, "annotation_edit_id", None),
        )

        if layer != "activity_state":
            state = context.get("activity_state")
            if state in ACTIVITY_STATES:
                self.editor_activity_state.setCurrentText(str(state))

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

    def clear_embedded_annotation(self) -> None:
        """Delete the selected saved annotation, leaving editor fields intact.

        The temporal row is the source of the selection. If a row was loaded,
        ``annotation_edit_id`` identifies it; otherwise the selected table row
        is used. Parent annotations are protected when their children still
        exist, because deleting them would make the saved hierarchy invalid.
        """
        annotation_id = getattr(self, "annotation_edit_id", None)
        if not annotation_id and hasattr(self, "annotation_table"):
            selected_rows = self.annotation_table.selectionModel().selectedRows()
            if selected_rows:
                row = int(selected_rows[0].row())
                if 0 <= row < len(self.annotations):
                    annotation_id = str(self.annotations[row].get("annotation_id"))
        if not annotation_id:
            self.annotation_status.setText("Select a temporal annotation row before pressing Clear selected.")
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
            "Clear selected annotation",
            f"Delete {annotation_id} from the temporal annotations?\n\nThis cannot be undone from the editor.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.annotation_state.remove(str(annotation_id))
            if not self._persist_annotations(show_error=True):
                return
        except Exception as exc:
            LOGGER.exception("Annotation deletion failed")
            QMessageBox.critical(self, "Clear failed", f"The annotation was not cleared.\n\n{type(exc).__name__}: {exc}")
            return

        self.annotation_start_frame = None
        self.annotation_edit_id = None
        self.annotation_edit_end_frame = None
        self.annotation_edit_loaded = False
        if hasattr(self, "editor_save_button"):
            self.editor_save_button.setText("Save range (S)")
        self.refresh_annotation_table()
        self._refresh_summary()
        self.annotation_status.setText(f"Cleared {annotation_id}. Editor fields were left unchanged.")

    def finish_embedded_annotation(self) -> None:
        if self.annotation_start_frame is None:
            self.annotation_status.setText("Press W first to capture the start frame.")
            return
        start_frame = int(self.annotation_start_frame)
        if self.editor_range_mode.currentData() == "point":
            end_frame = start_frame
        elif self.annotation_edit_loaded and self.current_frame == start_frame and self.annotation_edit_end_frame is not None:
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
        if getattr(self, "annotation_edit_id", None):
            existing = next(
                (item for item in self.annotations if item.get("annotation_id") == self.annotation_edit_id),
                None,
            )
        if existing is None:
            existing = next(
                (
                    item for item in self.annotations
                    if int(item.get("start_frame", -1)) == start_frame
                    and int(item.get("end_frame", -1)) == end_frame
                    and item.get("annotation_type") == layer
                ),
                None,
            )
        inherited, _ = self._context_for_frame(
            start_frame,
            exclude_id=existing.get("annotation_id") if existing else None,
        )
        activity_state = self.editor_activity_state.currentText()
        if activity_state not in ACTIVITY_STATES:
            activity_state = inherited.get("activity_state") or "active"

        # Only the selected layer writes its owned hierarchy values.  The
        # disabled controls are display-only inherited context from a parent.
        exercise = None
        set_id = None
        rep_id = None
        phase = "none"
        if layer == "set":
            exercise = self.editor_exercise_selector.value()
            set_id = self.editor_set_id.value() if self.editor_set_id.value() >= 1 else None
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
            "annotation_id": existing.get("annotation_id") if existing else self.annotation_state.next_annotation_id(),
            "segment_id": existing.get("segment_id") if existing else self.annotation_state.next_segment_id(),
            "annotation_type": layer,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "start_time_s": start_time,
            "end_time_s": end_time,
            "duration_s": max(0.0, end_time - start_time),
            "activity_state": activity_state,
            "exercise": exercise,
            "set_id": set_id,
            "rep_id": rep_id,
            "phase": phase,
            "form_label": "unlabeled",
            "issue_type": self.editor_issue_type.checked_values() if layer == "form_interval" else [],
            "error_category": self.editor_issue_category.checked_values() if layer == "form_interval" else [],
            "affected_joints": self.editor_affected_joints.checked_values() if layer == "form_interval" else [],
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
            if existing:
                self.annotation_state.replace(values["annotation_id"], values)
            else:
                self.annotation_state.add(values)
            self._sync_descendant_contexts()
            if self._persist_annotations(show_error=True):
                self.annotation_start_frame = None
                self.annotation_edit_id = None
                self.annotation_edit_end_frame = None
                self.annotation_edit_loaded = False
                if hasattr(self, "editor_save_button"):
                    self.editor_save_button.setText("Save range (S)")
                self.refresh_annotation_table(select_annotation_id=values["annotation_id"])
                self._refresh_summary()
                self.goto_frame(self.current_frame)
                self.editor_range_label.setText(f"Saved frames {start_frame}–{end_frame}. Press W for another entry.")
                self.annotation_status.setText(f"Saved {values['annotation_id']} / {values['segment_id']}.")
        except Exception as exc:
            LOGGER.exception("Embedded annotation save failed")
            QMessageBox.critical(self, "Annotation save failed", f"{type(exc).__name__}: {exc}")

    def _load_selected_annotation(self, index) -> None:
        """Load a table row into the embedded editor for an in-place update."""
        row = int(index.row())
        if row < 0 or row >= len(self.annotations):
            return
        annotation = self.annotations[row]
        self.annotation_edit_id = str(annotation.get("annotation_id"))
        self.annotation_edit_end_frame = int(annotation.get("end_frame", annotation.get("start_frame", 0)))
        self.annotation_edit_loaded = True
        start_frame = int(annotation.get("start_frame", 0))
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
        self.goto_frame(start_frame)
        # Re-resolve disabled fields after the video is at the selected row's
        # start.  This fills inherited activity/exercise/set/rep/phase values
        # from the surrounding hierarchy without making them editable.
        self._refresh_editor_options()
        self.editor_range_label.setText(
            f"Editing {self.annotation_edit_id}: frames {start_frame}–{self.annotation_edit_end_frame}. "
            "Navigate and press S to update, or press W to reset the start."
        )
        self.annotation_status.setText(
            f"Loaded {self.annotation_edit_id}. Changes will replace this annotation when saved."
        )
        if hasattr(self, "editor_save_button"):
            self.editor_save_button.setText("Update selected (S)")

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
        matching = [
            item for item in self.annotations
            if self._frame_in_annotation(item, frame)
            and (exclude_id is None or str(item.get("annotation_id")) != str(exclude_id))
        ]
        if not matching:
            return dict(self.annotation_state.current_context if self.annotation_state else {}), False

        # Form intervals are overlays.  They describe an issue at a frame but
        # must not replace the exercise hierarchy shown in the top context bar.
        matching = [item for item in matching if item.get("annotation_type") != "form_interval"]
        if not matching:
            return dict(self.annotation_state.current_context if self.annotation_state else {}), False
        priority = {"general": 0, "activity_state": 1, "set": 2, "rep": 3, "phase": 4}
        resolved: dict = {}
        for item in sorted(matching, key=lambda value: priority.get(str(value.get("annotation_type")), 0)):
            if item.get("activity_state"):
                resolved["activity_state"] = item["activity_state"]
            for key in ("exercise", "set_id", "rep_id", "phase"):
                value = item.get(key)
                if value not in (None, "", "none"):
                    resolved[key] = value
        if "activity_state" not in resolved and any(item.get("activity_state") == "active" for item in matching):
            resolved["activity_state"] = "active"
        return resolved, True

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
            item.setContext(Qt.ShortcutContext.WindowShortcut)
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
        # S is the explicit range/update command in Mode 1. Application scope
        # makes it reliable even when a combo box or notes editor still owns
        # focus; this prevents the previous behavior where S was merely typed
        # into the notes field and the temporal row stayed unchanged.
        self.shortcut_finish_annotation.setContext(Qt.ShortcutContext.ApplicationShortcut)
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
        self._update_navigation_shortcuts(None, self.focusWidget())

    def _update_navigation_shortcuts(self, _old, focused) -> None:
        """Let text/edit controls consume arrows; restore frame navigation outside them."""
        text_control = isinstance(focused, (QLineEdit, QTextEdit, QComboBox, QAbstractSpinBox))
        for item in getattr(self, "_navigation_shortcuts", []):
            item.setEnabled(not text_control)

    def eventFilter(self, watched, event):
        # This filter is installed at QApplication scope so arrow/S handling
        # still works when a child editor owns focus.  Do not process events
        # from another window, however: the old unscoped mouse branch could
        # steal focus from other dialogs/apps and made shutdown interrupts
        # appear to originate at this callback.
        if QApplication.activeWindow() is not self:
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.KeyPress:
            if (
                event.key() == Qt.Key.Key_S
                and event.modifiers() == Qt.KeyboardModifier.NoModifier
                and (self.annotation_start_frame is not None or self.annotation_edit_loaded)
            ):
                # S is the Mode 1 range/update command. Child editors such as
                # QTextEdit otherwise consume it and insert a character before
                # QShortcut can see it, which made the table appear unchanged.
                self.finish_embedded_annotation()
                event.accept()
                return True
        if event.type() == QEvent.Type.MouseButtonPress:
            focused = QApplication.focusWidget()
            if not isinstance(focused, (QLineEdit, QTextEdit, QComboBox, QAbstractSpinBox)):
                self.setFocus(Qt.FocusReason.MouseFocusReason)
        return super().eventFilter(watched, event)

    def _row_for_frame(self, frame: int) -> pd.Series:
        if self.dataframe.empty:
            raise ValueError("Feature DataFrame is empty.")
        frame = max(0, min(int(frame), self.total_frames - 1))
        matches = self.dataframe.index[self.dataframe["frame_id"] == frame]
        if len(matches):
            return self.dataframe.loc[matches[0]]
        return self.dataframe.iloc[frame]

    def goto_frame(self, frame_number: int):
        frame_number = max(0, min(int(frame_number), max(0, self.total_frames - 1)))
        self.current_frame = frame_number
        if hasattr(self, "frame_spin"):
            self.frame_spin.blockSignals(True)
            self.frame_spin.setValue(frame_number)
            self.frame_spin.blockSignals(False)
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ok, frame = self.cap.read()
        if not ok:
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
        self._current_video_pixmap = QPixmap.fromImage(image)
        self._render_video_pixmap()
        self._refresh_thumbnails()
        row = self._row_for_frame(frame_number)
        self.current_frame_context_label.setText(self._frame_info(row))
        self._refresh_context_label()
        if hasattr(self, "joint_graph_widget"):
            self.joint_graph_widget.set_current_frame(frame_number)

    def _render_video_pixmap(self) -> None:
        """Fit the cached frame to the current pane without changing layout."""
        if (
            self._current_video_pixmap is None
            or not hasattr(self, "video_label")
            or self.video_label.size().isEmpty()
        ):
            return
        self.video_label.setPixmap(
            self._current_video_pixmap.scaled(
                self.video_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event) -> None:
        # Re-render only the cached image.  No splitter sizes or widget
        # geometry are changed here, so maximizing/restoring or clicking a
        # control cannot create the small layout shifts seen previously.
        super().resizeEvent(event)
        self._render_video_pixmap()

    def _refresh_thumbnails(self) -> None:
        """Show a stable five-frame preview around the current frame.

        Out-of-range slots keep a fixed placeholder pixmap.  Valid thumbnails
        are stored in a small LRU cache, so the strip behaves like a sliding
        linked window without causing a disk seek and decode for every arrow
        press.
        """
        for label, frame_number in zip(self.thumbnail_labels, range(self.current_frame - 2, self.current_frame + 3)):
            if frame_number < 0 or frame_number >= self.total_frames:
                label.setPixmap(self._thumbnail_placeholder)
                label.setStyleSheet("border: 1px solid #9aa4b2; background: #20242b;")
                continue
            thumbnail = self._thumbnail_cache.get(frame_number)
            if thumbnail is None:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
                ok, frame = self.cap.read()
                if not ok:
                    label.setPixmap(self._thumbnail_placeholder)
                    label.setStyleSheet("border: 1px solid #9aa4b2; background: #20242b;")
                    continue
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = QImage(
                    rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888
                ).copy()
                thumbnail = QPixmap.fromImage(image).scaled(
                    self._thumbnail_size[0],
                    self._thumbnail_size[1],
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._thumbnail_cache[frame_number] = thumbnail
                while len(self._thumbnail_cache) > self._thumbnail_cache_limit:
                    self._thumbnail_cache.popitem(last=False)
            else:
                self._thumbnail_cache.move_to_end(frame_number)
            label.setPixmap(thumbnail)
            border = "#20c55a" if frame_number == self.current_frame else "#9aa4b2"
            label.setStyleSheet(f"border: 3px solid {border}; background: #20242b;")

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
        state = self.annotation_state.to_document() if self.annotation_state else {"annotations": []}
        warnings = annotation_warnings(state, self.total_frames)
        state_segments = [a for a in self.annotations if a.get("annotation_type") == "activity_state"]
        active_segments = [a for a in state_segments if a.get("activity_state") == "active"]
        covered = set()
        for item in state_segments:
            covered.update(range(int(item["start_frame"]), int(item["end_frame"]) + 1))
        active_covered = set()
        for item in active_segments:
            active_covered.update(range(int(item["start_frame"]), int(item["end_frame"]) + 1))
        reps = build_rep_summary(state)
        coverage = len(covered) / max(1, self.total_frames)
        active_coverage = len(active_covered) / max(1, self.total_frames)
        status = self.annotation_state.status if self.annotation_state else "unknown"
        self.summary_label.setText(
            f"Annotations: {len(self.annotations)} | Reps: {len(reps)} | "
            f"Activity coverage: {coverage:.1%} | Active coverage: {active_coverage:.1%} | "
            f"Session status: {status} | Warnings: {len(warnings)}"
        )
        self._refresh_context_label()

    def _next_rep_id_from_context(self) -> int | None:
        context = self.annotation_state.current_context if self.annotation_state else {}
        set_id = context.get("set_id")
        if set_id is None:
            return None
        return self.annotation_state.next_rep_id(int(set_id)) if self.annotation_state else None

    def open_context_dialog(self):
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
        form.addRow("Set ID", set_spin)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.annotation_state.set_context(
                activity_state=state_combo.currentText(),
                exercise=exercise_selector.value(),
                set_id=set_spin.value() if set_spin.value() >= 1 else None,
            )
            self._persist_annotations(show_error=True)
            self._refresh_context_label()

    def start_range_capture(self):
        if getattr(self, "editor_auto_context", None) is not None and self.editor_auto_context.isChecked():
            self._apply_context_to_editor(self.current_frame)
            if (
                self.editor_annotation_type.currentData() == "set"
                and not getattr(self, "annotation_edit_loaded", False)
            ):
                context, _ = self._context_for_frame(self.current_frame)
                # Set IDs are local to the current Activity interval.  When
                # this frame is not already inside a set, start the manual
                # set counter at N/A/0 so the next save assigns 1 locally.
                if context.get("set_id") is None:
                    self.editor_set_id.setValue(0)
        self.annotation_start_frame = self.current_frame
        if hasattr(self, "editor_range_mode") and self.editor_range_mode.currentData() == "point":
            self.editor_range_label.setText(f"Point captured at frame {self.current_frame}. Press S to save it.")
        else:
            self.editor_range_label.setText(f"Start captured at frame {self.current_frame}. Navigate, then press S to save.")
        self.annotation_status.setText(
            f"Capturing range from frame {self.current_frame}. Use ←/→ or ±1s, then press S."
        )

    def set_range_status(self, start_frame: int, end_frame: int):
        start_time = float(self._row_for_frame(start_frame)["timestamp_s"])
        end_time = float(self._row_for_frame(end_frame)["timestamp_s"])
        self.annotation_status.setText(
            f"Capturing range: {start_frame}–{end_frame} ({start_time:.3f}s–{end_time:.3f}s). Press S to finish."
        )

    def cancel_range_capture(self):
        self.annotation_start_frame = None
        self.range_capture = None
        self.annotation_status.setText("Range cancelled. Press W to start a new range.")

    def complete_range_capture(self, start_frame: int, end_frame: int):
        self.annotation_start_frame = None
        self.range_capture = None
        start_time = float(self._row_for_frame(start_frame)["timestamp_s"])
        end_time = float(self._row_for_frame(end_frame)["timestamp_s"])
        existing = next(
            (
                annotation for annotation in self.annotations
                if int(annotation.get("start_frame", -1)) == start_frame
                and int(annotation.get("end_frame", -1)) == end_frame
            ),
            None,
        )
        context = self.annotation_state.current_context if self.annotation_state else {}
        defaults = {"exercise": self.metadata.get("exercise_hint", "")}
        segment_id = existing.get("segment_id") if existing else self.annotation_state.next_segment_id()
        dialog = AnnotationDialog(
            start_frame, end_frame, start_time, end_time, context, self,
            existing=existing, defaults=defaults, segment_id=segment_id,
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
        values["annotation_id"] = existing.get("annotation_id") if existing else self.annotation_state.next_annotation_id()
        values["segment_id"] = segment_id
        values["duration_s"] = max(0.0, end_time - start_time)
        try:
            if existing:
                self.annotation_state.replace(values["annotation_id"], values)
            else:
                self.annotation_state.add(values)
            if self._persist_annotations(show_error=True):
                self.refresh_annotation_table(select_annotation_id=values["annotation_id"])
                self._refresh_summary()
                self.annotation_status.setText(
                    f"Saved {values['annotation_id']} / {segment_id}: frames {start_frame}–{end_frame}. Press W for another range."
                )
        except Exception as exc:
            LOGGER.exception("Annotation checkpoint failed")
            QMessageBox.critical(self, "Annotation checkpoint failed", f"Annotation remains in memory.\n\n{type(exc).__name__}: {exc}")

    def _effective_annotation_for_display(self, annotation: dict) -> dict:
        """Return table values with parent context filled into child rows."""
        display = dict(annotation)
        kind = str(annotation.get("annotation_type"))
        if kind in {"set", "rep", "phase", "form_interval"}:
            context, _ = self._context_for_frame(
                int(annotation.get("start_frame", 0)),
                exclude_id=str(annotation.get("annotation_id")),
            )
            for key in ("exercise", "set_id", "rep_id", "phase"):
                if display.get(key) in (None, "", "none") and context.get(key) not in (None, "", "none"):
                    display[key] = context[key]
            if not display.get("activity_state") and context.get("activity_state"):
                display["activity_state"] = context["activity_state"]
        return display

    def refresh_annotation_table(self, select_annotation_id: str | None = None):
        columns = [
            "Annotation ID", "Segment ID", "Layer", "Boundary", "Start frame", "End frame",
            "Start time (s)", "End time (s)", "Duration (s)", "Activity", "Movement type",
            "Exercise name", "Set", "Rep", "Phase", "Form", "Form score", "Notes",
            "Issue type", "Issue category", "Affected joints",
        ]
        rows = []
        for annotation in self.annotations:
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
        self.annotation_model.set_dataframe(pd.DataFrame(rows, columns=columns))
        if select_annotation_id:
            row = next(
                (
                    index for index, item in enumerate(self.annotations)
                    if str(item.get("annotation_id")) == str(select_annotation_id)
                ),
                None,
            )
            if row is not None:
                self.annotation_table.selectRow(int(row))
                self.annotation_table.scrollTo(self.annotation_model.index(int(row), 0))

    def _persist_annotations(self, *, show_error: bool) -> bool:
        if self.annotation_state is None:
            return False
        document = self.annotation_state.to_document()
        validate_annotations(document, len(self.dataframe))
        try:
            # JSON is authoritative. A failed derived Parquet export must never erase it.
            save_json_atomic(document, self.annotation_json_path)
        except Exception as exc:
            LOGGER.exception("Annotation JSON persistence failed")
            if show_error:
                QMessageBox.critical(self, "Annotation save failed", f"Could not save the JSON source of truth.\n\n{type(exc).__name__}: {exc}")
            return False
        try:
            save_annotation_parquet(document, self.annotation_parquet_path)
            if self.rep_summary_path.resolve() == self.annotation_json_path.resolve():
                raise RuntimeError("Derived repetition summary path must not equal the annotation source path")
            save_json_atomic({"schema_version": "1.0", "source": "derived_from_annotations.json", "repetitions": build_rep_summary(document)}, self.rep_summary_path)
        except Exception as exc:
            LOGGER.exception("Derived annotation export failed")
            if show_error:
                QMessageBox.warning(self, "Derived export warning", f"Annotations were saved to JSON, but a derived file could not be updated.\n\n{type(exc).__name__}: {exc}")
        return True

    def save_annotations(self):
        if self._persist_annotations(show_error=True):
            self.refresh_annotation_table(); self._refresh_summary()
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
        mask = (self.dataframe["frame_id"] >= int(item["start_frame"])) & (self.dataframe["frame_id"] <= int(item["end_frame"]))
        segment_df = self.dataframe.loc[mask].copy()
        labeled = annotation_to_frame_targets(segment_df, self.annotation_state.to_document())
        config = load_config(PROJECT_ROOT / "configs" / "config.json")
        result = RepDetector.from_config(config) if hasattr(RepDetector, "from_config") else RepDetector()
        detection = result.detect_segment(labeled, activity_state="active")
        suggestions_path = self.annotation_json_path.with_name(self.annotation_json_path.stem.replace("_annotations", "_rep_suggestions") + ".json")
        save_rep_suggestions(detection, suggestions_path)
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
        if self.range_capture is not None:
            self.range_capture.close()
        self.cap.release()
        event.accept()


def open_annotation_studio(parent=None, video_path=None, parquet_path=None):
    if video_path is None:
        video_path, _ = QFileDialog.getOpenFileName(parent, "Select processed skeleton video", "", "Video Files (*.mp4 *.mov *.avi *.mkv);;All Files (*)")
        if not video_path:
            return
    if parquet_path is None:
        parquet_path, _ = QFileDialog.getOpenFileName(parent, "Select feature Parquet", "", "Parquet (*.parquet);;All Files (*)")
        if not parquet_path:
            return
    window = AnnotationStudio(video_path, parquet_path, parent=parent)
    # Qt resolves this against the active monitor's available work area.  It
    # avoids the previous 1450x920 hard-coded geometry and keeps the splitter
    # proportions stable when the user starts navigating or editing fields.
    window.showMaximized()
    return window
