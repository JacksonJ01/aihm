"""Local desktop preferences and the shared Mode 0 participant picker."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import logging
from pathlib import Path
import re

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QDoubleSpinBox, QHBoxLayout, QInputDialog, QLabel, QListWidget, QLineEdit, QMessageBox, QPushButton, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget,
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
    starter_video: str = ""
    setup_completed: bool = False
    default_frame_jump: int = DEFAULT_FRAME_JUMP
    default_camera_name: str = "camera_01"
    default_viewpoint: str = ""
    default_playback_speed: float = 1.0
    playback_loop: bool = False
    autosave_interval_s: int = 30
    interface_scale: float = 1.0
    theme: str = "System"
    arrow_keys_navigate: bool = True
    loop_selected_interval: bool = False
    pause_at_annotation_boundary: bool = False
    default_visualization_mode: str = "2D"
    show_skeleton_by_default: bool = True
    show_midpoint_overlay: bool = False
    show_angle_overlay: bool = False
    raw_curves_by_default: bool = True
    graph_time_window_s: float = 1.0
    zoom_to_annotation: bool = True
    smoothing_method: str = "None"
    smoothing_window: int = 5
    confidence_threshold: float = 0.5
    missing_landmark_policy: str = "Show gaps"
    derivative_gap_policy: str = "Do not cross gaps"
    generate_graph_previews: bool = True
    export_graph_images: bool = False
    output_versioning: str = "Create new version"
    default_annotation_layer: str = "activity_state"
    default_activity_state: str = "active"
    default_phase_schema: str = "eccentric, concentric, hold"
    auto_update_context: bool = True
    inherit_annotation_context: bool = True
    default_form_label: str = "unlabeled"
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
            starter_video = data.get("starter_video")
            jump = data.get("default_frame_jump")
            def text(name, fallback=""):
                value = data.get(name, fallback)
                return value.strip() if isinstance(value, str) else fallback

            def bounded_number(name, fallback, low, high, integer=False):
                value = data.get(name, fallback)
                if integer and type(value) is int:
                    return max(low, min(high, value))
                if not integer and isinstance(value, (int, float)) and not isinstance(value, bool):
                    return max(low, min(high, float(value)))
                return fallback

            def flag(name, fallback):
                return data.get(name, fallback) if type(data.get(name, fallback)) is bool else fallback

            self.values = DesktopPreferences(
                **colors, participants=participants,
                default_participant=default if default in participants else "",
                starter_video=starter_video.strip() if isinstance(starter_video, str) else "",
                # Existing settings files are already configured users. Only a
                # brand-new settings file should show the optional first-run flow.
                setup_completed=bool(data.get("setup_completed", True)),
                default_frame_jump=jump if type(jump) is int and 1 <= jump <= MAX_FRAME_JUMP else DEFAULT_FRAME_JUMP,
                default_camera_name=text("default_camera_name", "camera_01"),
                default_viewpoint=text("default_viewpoint"),
                default_playback_speed=bounded_number("default_playback_speed", 1.0, 0.1, 5.0),
                playback_loop=flag("playback_loop", False),
                autosave_interval_s=bounded_number("autosave_interval_s", 30, 0, 3600, integer=True),
                interface_scale=bounded_number("interface_scale", 1.0, 0.75, 2.0),
                theme=text("theme", "System") if text("theme", "System") in {"System", "Light", "Dark", "High contrast"} else "System",
                arrow_keys_navigate=flag("arrow_keys_navigate", True),
                loop_selected_interval=flag("loop_selected_interval", False),
                pause_at_annotation_boundary=flag("pause_at_annotation_boundary", False),
                default_visualization_mode=text("default_visualization_mode", "2D") if text("default_visualization_mode", "2D") in {"2D", "3D"} else "2D",
                show_skeleton_by_default=flag("show_skeleton_by_default", True),
                show_midpoint_overlay=flag("show_midpoint_overlay", False),
                show_angle_overlay=flag("show_angle_overlay", False),
                raw_curves_by_default=flag("raw_curves_by_default", True),
                graph_time_window_s=bounded_number("graph_time_window_s", 1.0, 0.05, 86400.0),
                zoom_to_annotation=flag("zoom_to_annotation", True),
                smoothing_method=text("smoothing_method", "None") if text("smoothing_method", "None") in {"None", "Moving average", "Exponential moving average", "Savitzky-Golay"} else "None",
                smoothing_window=bounded_number("smoothing_window", 5, 3, 101, integer=True),
                confidence_threshold=bounded_number("confidence_threshold", 0.5, 0.0, 1.0),
                missing_landmark_policy=text("missing_landmark_policy", "Show gaps"),
                derivative_gap_policy=text("derivative_gap_policy", "Do not cross gaps"),
                generate_graph_previews=flag("generate_graph_previews", True),
                export_graph_images=flag("export_graph_images", False),
                output_versioning=text("output_versioning", "Create new version"),
                default_annotation_layer=text("default_annotation_layer", "activity_state"),
                default_activity_state=text("default_activity_state", "active"),
                default_phase_schema=text("default_phase_schema", "eccentric, concentric, hold"),
                auto_update_context=flag("auto_update_context", True),
                inherit_annotation_context=flag("inherit_annotation_context", True),
                default_form_label=text("default_form_label", "unlabeled"),
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


class StartupSetupDialog(QDialog):
    """Optional first-run setup for a participant and an opening video.

    The selected video is only bookmarked; it is never copied or uploaded.
    When it has a matching processed feature Parquet, the launcher opens the
    graph viewer. Otherwise it opens Mode 0 with the source video prefilled.
    """

    def __init__(self, store: PreferenceStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("AIHuMo first-run setup")
        self.resize(560, 260)
        outer = QVBoxLayout(self)
        intro = QLabel(
            "This optional setup remembers a participant ID and an opening video "
            "for this computer. You can skip it and configure everything later."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        form = QFormLayout()
        self.participant_edit = QLineEdit(store.values.default_participant)
        self.participant_edit.setPlaceholderText("e.g. P001 or Alex")
        form.addRow("Participant ID (optional)", self.participant_edit)

        video_row = QWidget()
        video_layout = QHBoxLayout(video_row)
        video_layout.setContentsMargins(0, 0, 0, 0)
        self.video_edit = QLineEdit(store.values.starter_video)
        self.video_edit.setPlaceholderText("Choose a source or processed skeleton video")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_video)
        video_layout.addWidget(self.video_edit, 1)
        video_layout.addWidget(browse)
        form.addRow("Starter video (optional)", video_row)
        outer.addLayout(form)

        self.open_video = QCheckBox("Open the starter video after setup")
        self.open_video.setChecked(bool(store.values.starter_video))
        self.open_video.setEnabled(bool(store.values.starter_video))
        self.video_edit.textChanged.connect(self._starter_video_changed)
        outer.addWidget(self.open_video)

        actions = QHBoxLayout()
        skip = QPushButton("Skip setup")
        skip.clicked.connect(self._skip)
        actions.addWidget(skip)
        actions.addStretch(1)
        save = QPushButton("Save and continue")
        save.setDefault(True)
        save.clicked.connect(self._save)
        actions.addWidget(save)
        outer.addLayout(actions)
        self.setup = {}

    def _starter_video_changed(self, text: str) -> None:
        has_video = bool(text.strip())
        if has_video and not self.open_video.isEnabled():
            self.open_video.setChecked(True)
        self.open_video.setEnabled(has_video)

    def _browse_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose starter video", "",
            "Video Files (*.mp4 *.mov *.avi *.mkv *.webm);;All Files (*)",
        )
        if path:
            self.video_edit.setText(path)

    def _persist(self) -> None:
        participant = self.participant_edit.text().strip()
        participants = tuple(dict.fromkeys((*self.store.values.participants, participant))) if participant else self.store.values.participants
        video = self.video_edit.text().strip()
        self.store.save(replace(
            self.store.values,
            participants=participants,
            default_participant=participant if participant else self.store.values.default_participant,
            starter_video=video,
            setup_completed=True,
        ))
        self.setup = {"participant": participant, "video": video, "open_video": bool(video and self.open_video.isChecked())}

    def _save(self) -> None:
        try:
            self._persist()
        except OSError as exc:
            QMessageBox.warning(self, "Could not save setup", str(exc))
            return
        self.accept()

    def _skip(self) -> None:
        try:
            self.store.save(replace(self.store.values, setup_completed=True))
        except OSError as exc:
            QMessageBox.warning(self, "Could not save setup", str(exc))
            return
        self.setup = {}
        self.reject()


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

        # Keep the existing General and Timeline pages stable while exposing
        # the broader desktop controls as additive preference pages.  Every
        # control has a safe default so older settings files remain valid.
        playback = QWidget(); tabs.addTab(playback, "Playback")
        playback_form = QFormLayout(playback)
        self.default_camera_name = QLineEdit(store.values.default_camera_name)
        self.default_viewpoint = QLineEdit(store.values.default_viewpoint)
        self.default_playback_speed = QDoubleSpinBox(); self.default_playback_speed.setRange(0.1, 5.0); self.default_playback_speed.setSingleStep(0.1); self.default_playback_speed.setValue(store.values.default_playback_speed); self.default_playback_speed.setSuffix("×")
        self.playback_loop = QCheckBox("Loop playback"); self.playback_loop.setChecked(store.values.playback_loop)
        self.autosave_interval_s = QSpinBox(); self.autosave_interval_s.setRange(0, 3600); self.autosave_interval_s.setValue(store.values.autosave_interval_s); self.autosave_interval_s.setSuffix(" s")
        self.interface_scale = QDoubleSpinBox(); self.interface_scale.setRange(0.75, 2.0); self.interface_scale.setSingleStep(0.05); self.interface_scale.setValue(store.values.interface_scale); self.interface_scale.setSuffix("×")
        self.theme = QComboBox(); self.theme.addItems(("System", "Light", "Dark", "High contrast")); self.theme.setCurrentText(store.values.theme)
        playback_form.addRow("Default camera name", self.default_camera_name)
        playback_form.addRow("Default viewpoint", self.default_viewpoint)
        playback_form.addRow("Default playback speed", self.default_playback_speed)
        playback_form.addRow(self.playback_loop)
        playback_form.addRow("Autosave interval", self.autosave_interval_s)
        playback_form.addRow("Interface scale", self.interface_scale)
        playback_form.addRow("Theme", self.theme)

        visualization = QWidget(); tabs.addTab(visualization, "Visualization")
        visualization_form = QFormLayout(visualization)
        self.default_visualization_mode = QComboBox(); self.default_visualization_mode.addItems(("2D", "3D")); self.default_visualization_mode.setCurrentText(store.values.default_visualization_mode)
        self.show_skeleton_by_default = QCheckBox("Show skeleton by default"); self.show_skeleton_by_default.setChecked(store.values.show_skeleton_by_default)
        self.show_midpoint_overlay = QCheckBox("Show midpoint overlay by default"); self.show_midpoint_overlay.setChecked(store.values.show_midpoint_overlay)
        self.show_angle_overlay = QCheckBox("Show angle overlay by default"); self.show_angle_overlay.setChecked(store.values.show_angle_overlay)
        self.raw_curves_by_default = QCheckBox("Show raw curves by default"); self.raw_curves_by_default.setChecked(store.values.raw_curves_by_default)
        self.graph_time_window_s = QDoubleSpinBox(); self.graph_time_window_s.setRange(0.05, 86400.0); self.graph_time_window_s.setDecimals(2); self.graph_time_window_s.setValue(store.values.graph_time_window_s); self.graph_time_window_s.setSuffix(" s")
        self.zoom_to_annotation = QCheckBox("Zoom graphs to the selected annotation"); self.zoom_to_annotation.setChecked(store.values.zoom_to_annotation)
        self.arrow_keys_navigate = QCheckBox("Arrow keys always navigate frames"); self.arrow_keys_navigate.setChecked(store.values.arrow_keys_navigate)
        self.loop_selected_interval = QCheckBox("Loop the selected interval"); self.loop_selected_interval.setChecked(store.values.loop_selected_interval)
        self.pause_at_annotation_boundary = QCheckBox("Pause at annotation boundaries"); self.pause_at_annotation_boundary.setChecked(store.values.pause_at_annotation_boundary)
        visualization_form.addRow("Default viewer", self.default_visualization_mode)
        for control in (self.show_skeleton_by_default, self.show_midpoint_overlay, self.show_angle_overlay,
                        self.raw_curves_by_default, self.zoom_to_annotation, self.arrow_keys_navigate,
                        self.loop_selected_interval, self.pause_at_annotation_boundary):
            visualization_form.addRow(control)
        visualization_form.addRow("Default graph window", self.graph_time_window_s)

        data_page = QWidget(); tabs.addTab(data_page, "Data & processing")
        data_form = QFormLayout(data_page)
        self.smoothing_method = QComboBox(); self.smoothing_method.addItems(("None", "Moving average", "Exponential moving average", "Savitzky-Golay")); self.smoothing_method.setCurrentText(store.values.smoothing_method)
        self.smoothing_window = QSpinBox(); self.smoothing_window.setRange(3, 101); self.smoothing_window.setSingleStep(2); self.smoothing_window.setValue(store.values.smoothing_window)
        self.confidence_threshold = QDoubleSpinBox(); self.confidence_threshold.setRange(0.0, 1.0); self.confidence_threshold.setSingleStep(0.05); self.confidence_threshold.setValue(store.values.confidence_threshold)
        self.missing_landmark_policy = QComboBox(); self.missing_landmark_policy.addItems(("Show gaps", "Interpolate for display", "Hide invalid frames")); self.missing_landmark_policy.setCurrentText(store.values.missing_landmark_policy)
        self.derivative_gap_policy = QComboBox(); self.derivative_gap_policy.addItems(("Do not cross gaps", "Allow documented interpolation")); self.derivative_gap_policy.setCurrentText(store.values.derivative_gap_policy)
        self.generate_graph_previews = QCheckBox("Generate graph previews after Mode 0"); self.generate_graph_previews.setChecked(store.values.generate_graph_previews)
        self.export_graph_images = QCheckBox("Export PNG/SVG graph images"); self.export_graph_images.setChecked(store.values.export_graph_images)
        self.output_versioning = QComboBox(); self.output_versioning.addItems(("Create new version", "Require confirmation", "Reuse only explicitly selected version")); self.output_versioning.setCurrentText(store.values.output_versioning)
        data_form.addRow("Smoothing", self.smoothing_method)
        data_form.addRow("Smoothing window", self.smoothing_window)
        data_form.addRow("Confidence threshold", self.confidence_threshold)
        data_form.addRow("Missing landmark policy", self.missing_landmark_policy)
        data_form.addRow("Derivative gap policy", self.derivative_gap_policy)
        data_form.addRow(self.generate_graph_previews)
        data_form.addRow(self.export_graph_images)
        data_form.addRow("Output versioning", self.output_versioning)

        annotation_page = QWidget(); tabs.addTab(annotation_page, "Annotation")
        annotation_form = QFormLayout(annotation_page)
        self.default_annotation_layer = QComboBox(); self.default_annotation_layer.addItems(("activity_state", "set", "rep", "phase", "form_interval", "other")); self.default_annotation_layer.setCurrentText(store.values.default_annotation_layer)
        self.default_activity_state = QComboBox(); self.default_activity_state.addItems(("active", "idle", "transition")); self.default_activity_state.setCurrentText(store.values.default_activity_state)
        self.default_phase_schema = QLineEdit(store.values.default_phase_schema)
        self.auto_update_context = QCheckBox("Update context automatically over saved frames"); self.auto_update_context.setChecked(store.values.auto_update_context)
        self.inherit_annotation_context = QCheckBox("Inherit parent set/rep context"); self.inherit_annotation_context.setChecked(store.values.inherit_annotation_context)
        self.default_form_label = QComboBox(); self.default_form_label.addItems(("unlabeled", "good", "acceptable", "poor")); self.default_form_label.setCurrentText(store.values.default_form_label)
        annotation_form.addRow("Default annotation layer", self.default_annotation_layer)
        annotation_form.addRow("Default activity state", self.default_activity_state)
        annotation_form.addRow("Default phases", self.default_phase_schema)
        annotation_form.addRow(self.auto_update_context)
        annotation_form.addRow(self.inherit_annotation_context)
        annotation_form.addRow("Default form label", self.default_form_label)

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
            starter_video=self.store.values.starter_video,
            setup_completed=self.store.values.setup_completed,
            default_frame_jump=self.default_frame_jump.value(),
            default_camera_name=self.default_camera_name.text().strip(),
            default_viewpoint=self.default_viewpoint.text().strip(),
            default_playback_speed=self.default_playback_speed.value(),
            playback_loop=self.playback_loop.isChecked(),
            autosave_interval_s=self.autosave_interval_s.value(),
            interface_scale=self.interface_scale.value(),
            theme=self.theme.currentText(),
            arrow_keys_navigate=self.arrow_keys_navigate.isChecked(),
            loop_selected_interval=self.loop_selected_interval.isChecked(),
            pause_at_annotation_boundary=self.pause_at_annotation_boundary.isChecked(),
            default_visualization_mode=self.default_visualization_mode.currentText(),
            show_skeleton_by_default=self.show_skeleton_by_default.isChecked(),
            show_midpoint_overlay=self.show_midpoint_overlay.isChecked(),
            show_angle_overlay=self.show_angle_overlay.isChecked(),
            raw_curves_by_default=self.raw_curves_by_default.isChecked(),
            graph_time_window_s=self.graph_time_window_s.value(),
            zoom_to_annotation=self.zoom_to_annotation.isChecked(),
            smoothing_method=self.smoothing_method.currentText(),
            smoothing_window=self.smoothing_window.value(),
            confidence_threshold=self.confidence_threshold.value(),
            missing_landmark_policy=self.missing_landmark_policy.currentText(),
            derivative_gap_policy=self.derivative_gap_policy.currentText(),
            generate_graph_previews=self.generate_graph_previews.isChecked(),
            export_graph_images=self.export_graph_images.isChecked(),
            output_versioning=self.output_versioning.currentText(),
            default_annotation_layer=self.default_annotation_layer.currentText(),
            default_activity_state=self.default_activity_state.currentText(),
            default_phase_schema=self.default_phase_schema.text().strip(),
            auto_update_context=self.auto_update_context.isChecked(),
            inherit_annotation_context=self.inherit_annotation_context.isChecked(),
            default_form_label=self.default_form_label.currentText(),
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
