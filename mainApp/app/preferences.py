"""Local desktop preferences and the shared Mode 0 participant picker."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import logging
from pathlib import Path
import re

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QInputDialog, QLabel, QListWidget, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from aihumo.storage import load_json, save_json_atomic

LOGGER = logging.getLogger(__name__)
DEFAULT_FRAME_JUMP = 50
MAX_FRAME_JUMP = 10_000
COLOR_FIELDS = {
    "launcher_accent": "Selected workflow border",
    "frame_highlight": "Current-frame border",
    "skeleton_line": "Skeleton lines",
    "skeleton_joint": "Skeleton joints",
}


@dataclass(frozen=True)
class DesktopPreferences:
    launcher_accent: str = "#20a253"
    frame_highlight: str = "#20c55a"
    skeleton_line: str = "#00ff00"
    skeleton_joint: str = "#ff0000"
    participants: tuple[str, ...] = ()
    default_participant: str = ""
    default_frame_jump: int = DEFAULT_FRAME_JUMP


class PreferenceStore:
    def __init__(self, path: Path):
        self.path = path
        self.values = DesktopPreferences()
        if not path.is_file():
            return
        try:
            data = load_json(path)
            if not isinstance(data, dict):
                raise ValueError("Settings must contain a JSON object.")
            colors = {
                name: color.lower() for name in COLOR_FIELDS
                if isinstance(color := data.get(name), str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color)
            }
            raw = data.get("participants")
            participants = tuple(dict.fromkeys(
                value.strip() for value in raw if isinstance(value, str) and value.strip()
            )) if isinstance(raw, list) else ()
            default = data.get("default_participant")
            jump = data.get("default_frame_jump")
            self.values = DesktopPreferences(
                **colors, participants=participants,
                default_participant=default if default in participants else "",
                default_frame_jump=jump if type(jump) is int and 1 <= jump <= MAX_FRAME_JUMP else DEFAULT_FRAME_JUMP,
            )
        except (OSError, ValueError):
            LOGGER.exception("Could not read desktop settings from %s", path)

    def save(self, values: DesktopPreferences) -> None:
        save_json_atomic(asdict(values), self.path)
        self.values = values

    def add_participant(self, participant: str) -> None:
        participant = participant.strip()
        if participant and participant not in self.values.participants:
            self.save(replace(self.values, participants=(*self.values.participants, participant)))


class ParticipantPicker(QWidget):
    def __init__(self, store: PreferenceStore, parent=None):
        super().__init__(parent)
        self.store = store
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.edit = self.combo.lineEdit()
        self.edit.setPlaceholderText("Choose or enter a participant ID")
        self.combo.addItems(store.values.participants)
        self.combo.setCurrentIndex(self.combo.findText(store.values.default_participant))
        save = QPushButton("Save participant")
        save.setToolTip("Add the entered participant ID to Settings for future recordings.")
        save.clicked.connect(self._save_participant)
        layout.addWidget(self.combo, 1)
        layout.addWidget(save)

    def _save_participant(self) -> None:
        participant = self.edit.text().strip()
        if not participant:
            QMessageBox.information(self, "Participant ID", "Enter a participant ID to save.")
            return
        try:
            self.store.add_participant(participant)
        except OSError as exc:
            QMessageBox.warning(self, "Could not save participant", str(exc))
            return
        index = self.combo.findText(participant)
        if index < 0:
            self.combo.addItem(participant)
            index = self.combo.count() - 1
        self.combo.setCurrentIndex(index)


class PreferencesDialog(QDialog):
    def __init__(self, store: PreferenceStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("AIHuMo Settings")
        self.resize(490, 470)
        layout = QVBoxLayout(self)
        colors = QFormLayout()
        self.color_buttons = {}
        for name, title in COLOR_FIELDS.items():
            button = QPushButton()
            button.clicked.connect(lambda checked=False, field=name: self._choose_color(field))
            self.color_buttons[name] = button
            self._set_color(name, getattr(store.values, name))
            colors.addRow(title, button)
        layout.addLayout(colors)
        help_text = QLabel("Skeleton colors apply when Mode 0 renders a skeleton video.")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        layout.addWidget(QLabel("Saved participant IDs"))
        self.participants = QListWidget()
        self.participants.addItems(store.values.participants)
        layout.addWidget(self.participants)
        actions = QHBoxLayout()
        actions.addWidget(QPushButton("Add participant…", clicked=self._add_participant))
        actions.addWidget(QPushButton("Remove selected", clicked=self._remove_participant))
        actions.addStretch(1)
        layout.addLayout(actions)
        self.default_participant = QComboBox()
        self._refresh_defaults(store.values.default_participant)
        defaults = QFormLayout()
        defaults.addRow("Default in Mode 0", self.default_participant)
        self.default_frame_jump = QSpinBox()
        self.default_frame_jump.setRange(1, MAX_FRAME_JUMP)
        self.default_frame_jump.setValue(store.values.default_frame_jump)
        self.default_frame_jump.setSuffix(" frames")
        self.default_frame_jump.setToolTip("Starting Up/Down jump in Mode 1 and the Interactive Graph Viewer.")
        defaults.addRow("Default frame jump", self.default_frame_jump)
        layout.addLayout(defaults)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_color(self, field: str, color: str) -> None:
        button = self.color_buttons[field]
        button.setText(color)
        button.setStyleSheet(f"border-left: 16px solid {color}; padding: 4px 12px;")

    def _choose_color(self, field: str) -> None:
        choice = QColorDialog.getColor(QColor(self.color_buttons[field].text()), self, COLOR_FIELDS[field])
        if choice.isValid():
            self._set_color(field, choice.name())

    def _ids(self) -> tuple[str, ...]:
        return tuple(self.participants.item(i).text() for i in range(self.participants.count()))

    def _refresh_defaults(self, selected: str) -> None:
        self.default_participant.clear()
        self.default_participant.addItem("Choose when processing", "")
        for participant in self._ids():
            self.default_participant.addItem(participant, participant)
        self.default_participant.setCurrentIndex(max(0, self.default_participant.findData(selected)))

    def _add_participant(self) -> None:
        text, accepted = QInputDialog.getText(self, "Add participant", "Participant ID")
        participant = text.strip()
        if accepted and participant and participant not in self._ids():
            self.participants.addItem(participant)
            self._refresh_defaults(self.default_participant.currentData())

    def _remove_participant(self) -> None:
        row = self.participants.currentRow()
        if row >= 0:
            self.participants.takeItem(row)
            self._refresh_defaults(self.default_participant.currentData())

    def _save(self) -> None:
        values = DesktopPreferences(
            **{name: button.text() for name, button in self.color_buttons.items()},
            participants=self._ids(), default_participant=self.default_participant.currentData(),
            default_frame_jump=self.default_frame_jump.value(),
        )
        try:
            self.store.save(values)
        except OSError as exc:
            QMessageBox.warning(self, "Could not save settings", str(exc))
            return
        self.accept()
