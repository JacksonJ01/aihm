"""Local desktop preferences and the shared Mode 0 participant picker."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import logging
from pathlib import Path
import re

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QInputDialog, QLabel, QListWidget, QMessageBox, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from aihumo.storage import load_json, save_json_atomic
from .timeline_layers import LAYERS, SEMANTIC_COLORS, timeline_preferences, valid_thresholds

LOGGER = logging.getLogger(__name__)
DEFAULT_FRAME_JUMP = 50
MAX_FRAME_JUMP = 10_000
COLOR_FIELDS = {
    "launcher_accent": "Selected workflow border",
    "skeleton_line": "Skeleton lines",
    "skeleton_joint": "Skeleton joints",
}


@dataclass(frozen=True)
class DesktopPreferences:
    launcher_accent: str = "#20a253"
    skeleton_line: str = "#00ff00"
    skeleton_joint: str = "#ff0000"
    participants: tuple[str, ...] = ()
    default_participant: str = ""
    default_frame_jump: int = DEFAULT_FRAME_JUMP
    timeline: dict = field(default_factory=timeline_preferences)


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
                timeline=timeline_preferences(data.get("timeline")),
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
        outer = QVBoxLayout(self)
        tabs = QTabWidget()
        outer.addWidget(tabs)
        general = QWidget()
        tabs.addTab(general, "General")
        layout = QVBoxLayout(general)
        self.timeline = TimelineSettingsPanel(store.values.timeline)
        tabs.addTab(self.timeline, "Timeline & graphs")
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
        outer.addWidget(buttons)

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
        timeline = self.timeline.values()
        if not valid_thresholds(timeline["thresholds"]):
            QMessageBox.warning(self, "Semantic zoom", "Use Activity/Exercise ≥ Set ≥ Repetition ≥ Phase.")
            return
        values = DesktopPreferences(
            **{name: button.text() for name, button in self.color_buttons.items()},
            participants=self._ids(), default_participant=self.default_participant.currentData(),
            default_frame_jump=self.default_frame_jump.value(),
            timeline=timeline,
        )
        try:
            self.store.save(values)
        except OSError as exc:
            QMessageBox.warning(self, "Could not save settings", str(exc))
            return
        self.accept()


class TimelineSettingsPanel(QWidget):
    def __init__(self, settings):
        super().__init__()
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.style = QComboBox()
        self.style.addItems(("Off", "Overlay", "Timeline"))
        form.addRow("Default view", self.style)
        self.auto = QCheckBox("Use visible duration")
        form.addRow("Semantic zoom", self.auto)
        self.thresholds = []
        for label in ("Activity / Exercise", "Set", "Repetition", "Phase / Form / Quality"):
            field = QSpinBox()
            field.setRange(1, 86400)
            field.setSuffix(" s")
            form.addRow(label, field)
            self.thresholds.append(field)
        self.category = QComboBox()
        for key, label in LAYERS.items():
            self.category.addItem(label, key)
        form.addRow("Layer appearance", self.category)
        self.layer_stack = QTabWidget()
        self.layer_stack.tabBar().hide()
        layout.addWidget(self.layer_stack, 1)
        self.fields = {}
        for key, label in LAYERS.items():
            page = QWidget()
            rows = QFormLayout(page)
            visible, alternate = QCheckBox("Show layer"), QCheckBox("Alternate neighboring intervals")
            rows.addRow(visible)
            rows.addRow(alternate)
            primary, secondary = self._color_button(), self._color_button()
            rows.addRow("Primary", primary)
            rows.addRow("Alternate", secondary)
            alternate.toggled.connect(secondary.setEnabled)
            opacity = QSpinBox()
            opacity.setRange(0, 100)
            opacity.setSuffix(" %")
            rows.addRow("Overlay opacity", opacity)
            semantic = {}
            for state in SEMANTIC_COLORS.get(key, {}):
                semantic[state] = button = self._color_button()
                rows.addRow(state.replace("_", " ").title(), button)
            self.fields[key] = visible, alternate, primary, secondary, opacity, semantic
            self.layer_stack.addTab(page, label)
        self.category.currentIndexChanged.connect(self.layer_stack.setCurrentIndex)
        layout.addWidget(QPushButton("Reset timeline settings", clicked=lambda: self._load(timeline_preferences())))
        self._load(timeline_preferences(settings))

    def _color_button(self):
        button = QPushButton()

        def choose():
            color = QColorDialog.getColor(QColor(button.text()), self, "Timeline color")
            if color.isValid():
                self._set_color(button, color.name())

        button.clicked.connect(choose)
        return button

    @staticmethod
    def _set_color(button, color):
        button.setText(color)
        button.setStyleSheet(f"border-left: 16px solid {color}; padding-left: 5px;")

    def _load(self, settings):
        self.style.setCurrentText(settings["style"])
        self.auto.setChecked(settings["auto"])
        for spin, seconds in zip(self.thresholds, settings["thresholds"]):
            spin.setValue(seconds)
        for key, (visible, alternate, primary, secondary, opacity, semantic) in self.fields.items():
            layer = settings["layers"][key]
            visible.setChecked(layer["visible"])
            alternate.setChecked(layer["alternate"])
            secondary.setEnabled(layer["alternate"])
            self._set_color(primary, layer["color"])
            self._set_color(secondary, layer["alternate_color"])
            opacity.setValue(round(layer["opacity"] * 100))
            for name, button in semantic.items():
                self._set_color(button, layer["semantic"][name])

    def values(self):
        return {
            "style": self.style.currentText(), "auto": self.auto.isChecked(),
            "thresholds": [field.value() for field in self.thresholds],
            "layers": {key: {"visible": visible.isChecked(), "alternate": alternate.isChecked(),
                             "color": primary.text(), "alternate_color": secondary.text(),
                             "opacity": opacity.value() / 100,
                             "semantic": {name: button.text() for name, button in semantic.items()}}
                       for key, (visible, alternate, primary, secondary, opacity, semantic) in self.fields.items()},
        }
