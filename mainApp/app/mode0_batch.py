from __future__ import annotations

"""Batch Mode 0 processing for one participant across multiple session folders.

The batch dialog deliberately keeps shared metadata separate from recording
identity.  A selected folder represents one session; every video discovered
under that folder receives a unique video ID and is processed independently.
This prevents a convenient multi-folder action from accidentally merging
recordings or creating one ambiguous Parquet file for several videos.
"""

import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from aihumo.config import load_config
from aihumo.processing import process_video, processing_job_status
from .preferences import ParticipantPicker, PreferenceStore
from .processing_resume import processing_fields, restore_processing_fields

LOGGER = logging.getLogger("AIHuMoDataStudio.Mode0Batch")

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
CAMERA_ANGLE_OPTIONS = [
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


def safe_identifier(value: str, fallback: str) -> str:
    """Make a stable filesystem-safe ID without silently returning an empty ID."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip()).strip("_-")
    return cleaned or fallback


def discover_session_videos(folder: str | Path) -> list[Path]:
    """Return videos below *folder* in deterministic order, without duplicates."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        return []
    found: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
            found[str(path.resolve()).casefold()] = path.resolve()
    return sorted(found.values(), key=lambda path: str(path).casefold())


def unique_video_id(stem: str, used: set[str]) -> str:
    base = safe_identifier(stem, "video")
    candidate = base
    suffix = 2
    while candidate.casefold() in {item.casefold() for item in used}:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def infer_camera_angle(stem: str) -> str:
    """Infer only an explicit filename hint; otherwise leave the value N/A."""
    normalized = re.sub(r"[^a-z0-9]+", "_", stem.casefold())
    tokens = set(filter(None, normalized.split("_")))
    if "three_quarter" in normalized or "threequarter" in normalized or "3q" in tokens:
        return "Three-quarter"
    for token, label in (
        ("front", "Front"),
        ("side", "Side"),
        ("rear", "Rear"),
        ("back", "Rear"),
        ("low", "Low angle"),
        ("high", "High angle"),
    ):
        if token in tokens:
            return label
    return "N/A"


@dataclass
class BatchRecording:
    folder: Path
    session_id: str
    source_video: Path
    video_id: str
    camera_id: str
    camera_angle: str


class BatchProcessingWorker(QObject):
    progress = pyqtSignal(float, str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal(str)

    def __init__(self, jobs: list[dict[str, Any]]):
        super().__init__()
        self.jobs = jobs
        self.cancel_requested = False

    def cancel(self) -> None:
        self.cancel_requested = True

    def run(self) -> None:
        results = []
        total = max(1, len(self.jobs))
        try:
            for index, job in enumerate(self.jobs):
                if self.cancel_requested:
                    raise InterruptedError("Batch processing was cancelled before the next recording.")
                name = f"{job['identifiers']['session_id']}/{job['identifiers']['video_id']}"

                def on_progress(fraction: float, message: str, *, base=index) -> None:
                    overall = (base + max(0.0, min(1.0, fraction))) / total
                    self.progress.emit(overall, f"{name}: {message}")

                result = process_video(
                    **job,
                    progress_callback=on_progress,
                    cancel_check=lambda: self.cancel_requested,
                )
                results.append(result)
            self.finished.emit(results)
        except InterruptedError as exc:
            self.cancelled.emit(str(exc))
        except Exception as exc:
            LOGGER.exception("Batch video processing failed")
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class BatchSessionDialog(QDialog):
    """Select multiple session folders and process them with shared metadata."""

    def __init__(self, parent=None, *, preferences: PreferenceStore | None = None):
        super().__init__(parent)
        self.setWindowTitle("AIHuMo — Process Multiple Session Folders")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint)
        self.resize(900, 820)
        self.setWindowState(Qt.WindowState.WindowMaximized)
        self.results: list[Any] = []
        self.thread: QThread | None = None
        self.worker: BatchProcessingWorker | None = None
        self._finish_after_thread_stops = False
        self.config_path = PROJECT_ROOT / "configs" / "config.json"
        self._folders: list[Path] = []
        self._session_ids: dict[Path, str] = {}
        self._recordings: list[BatchRecording] = []

        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        description = QLabel(
            "Each selected folder becomes one session. Videos inside a folder are "
            "processed independently; participant and camera metadata below is shared."
        )
        description.setWordWrap(True)
        body.addWidget(description)

        folder_buttons = QHBoxLayout()
        self.add_folder_button = QPushButton("Add session folder…")
        self.remove_folder_button = QPushButton("Remove selected")
        self.add_folder_button.clicked.connect(self.add_folder)
        self.remove_folder_button.clicked.connect(self.remove_selected_folder)
        folder_buttons.addWidget(self.add_folder_button)
        folder_buttons.addWidget(self.remove_folder_button)
        folder_buttons.addStretch(1)
        body.addLayout(folder_buttons)

        self.folder_list = QListWidget()
        self.folder_list.setMinimumHeight(130)
        body.addWidget(self.folder_list)

        recordings_description = QLabel(
            "Recordings found. Each row is processed separately. For multiple camera angles "
            "in one session, set the Camera ID and Camera angle on each row. Rows default to "
            "distinct camera IDs; obvious filename hints such as front/side are detected."
        )
        recordings_description.setWordWrap(True)
        body.addWidget(recordings_description)
        self.recording_table = QTableWidget(0, 5)
        self.recording_table.setHorizontalHeaderLabels([
            "Session", "Video ID", "Source video", "Camera ID", "Camera angle"
        ])
        self.recording_table.setMinimumHeight(180)
        self.recording_table.setAlternatingRowColors(True)
        self.recording_table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.EditKeyPressed
            | QTableWidget.EditTrigger.SelectedClicked
        )
        header = self.recording_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        body.addWidget(self.recording_table)

        form = QFormLayout()
        self.preferences = preferences or PreferenceStore(PROJECT_ROOT / ".aihumo" / "settings.json")
        self.participant_picker = ParticipantPicker(self.preferences)
        self.participant_edit = self.participant_picker.edit
        self.camera_id_edit = QLineEdit(self.preferences.values.default_camera_name or "camera_01")
        self.camera_name_edit = QLineEdit(self.preferences.values.default_camera_name)
        self.camera_angle_combo = QComboBox()
        for label, value in CAMERA_ANGLE_OPTIONS:
            self.camera_angle_combo.addItem(label, value)
        self.apply_camera_defaults_button = QPushButton("Apply shared camera defaults to all rows")
        self.apply_camera_defaults_button.clicked.connect(self.apply_camera_defaults)
        self.recording_date_edit = QLineEdit()
        self.environment_edit = QLineEdit()
        self.operator_edit = QLineEdit()
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(70)
        self.model_edit = QLineEdit()
        self.output_edit = QLineEdit(str(PROJECT_ROOT / "data" / "processed"))
        self.open_mode1_check = QCheckBox("Open the first completed recording in Mode 1")
        self.open_mode1_check.setChecked(True)
        form.addRow("Participant ID*", self.participant_picker)
        form.addRow("Camera ID*", self.camera_id_edit)
        form.addRow("Camera name", self.camera_name_edit)
        form.addRow("Camera angle", self.camera_angle_combo)
        form.addRow("Per-recording camera values", self.apply_camera_defaults_button)
        form.addRow("Recording date", self.recording_date_edit)
        form.addRow("Environment", self.environment_edit)
        form.addRow("Operator / annotator", self.operator_edit)
        form.addRow("Shared notes", self.notes_edit)
        form.addRow("MediaPipe model", self._browse_row(self.model_edit, self.browse_model, "MediaPipe Task (*.task);;All Files (*)"))
        form.addRow("Output root", self._browse_row(self.output_edit, self.browse_output, ""))
        form.addRow("Next step", self.open_mode1_check)
        body.addLayout(form)

        self.status = QLabel("Add at least one session folder and provide the participant ID.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Process folders")
        self.buttons.accepted.connect(self.start_processing)
        self.buttons.rejected.connect(self.cancel_or_close)
        layout.addWidget(self.buttons)

        default_model = PROJECT_ROOT / "full_model" / "pose_landmarker_full.task"
        if default_model.exists():
            self.model_edit.setText(str(default_model))
        self.refresh_recording_table()

    @staticmethod
    def _browse_row(edit: QLineEdit, callback, file_filter: str):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        button = QPushButton("Browse…")
        button.clicked.connect(callback)
        row_layout.addWidget(edit, 1)
        row_layout.addWidget(button)
        return row

    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select a session folder")
        if not folder:
            return
        path = Path(folder).expanduser().resolve()
        if path in self._folders:
            return
        videos = discover_session_videos(path)
        if not videos:
            QMessageBox.warning(self, "No videos found", f"No supported videos were found under:\n{path}")
            return
        self._folders.append(path)
        self.refresh_folder_list()

    def remove_selected_folder(self) -> None:
        row = self.folder_list.currentRow()
        if row < 0:
            return
        self._folders.pop(row)
        self.refresh_folder_list()

    def resume_setup(self):
        fields = processing_fields(self)
        fields["folders"] = [{"path": str(path), "session": self._session_ids[path]} for path in self._folders]
        fields["recordings"] = [
            {"folder": str(row.folder), "session": row.session_id, "source": str(row.source_video),
             "videoId": row.video_id, "cameraId": row.camera_id, "cameraAngle": row.camera_angle}
            for row in self._recordings_from_table()
        ]
        return fields

    def restore_setup(self, fields):
        restore_processing_fields(self, fields)
        self._session_ids = {Path(folder["path"]): folder["session"] for folder in fields["folders"]}
        self._folders = list(self._session_ids)
        self._recordings = [
            BatchRecording(Path(row["folder"]), row["session"], Path(row["source"]), row["videoId"],
                           row["cameraId"], row["cameraAngle"])
            for row in fields["recordings"]
        ]
        self.refresh_folder_list()

    def refresh_folder_list(self) -> None:
        self.refresh_recording_table()
        self.folder_list.clear()
        for folder in self._folders:
            count = sum(recording.folder == folder for recording in self._recordings)
            self.folder_list.addItem(f"{self._session_ids[folder]}  |  {folder}  |  {count} video(s)")
        self.status.setText(
            f"{len(self._folders)} session folder(s) selected; {len(self._recordings)} recording(s) found."
            if self._folders else "Add at least one session folder and provide the participant ID."
        )

    def browse_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select MediaPipe model", str(PROJECT_ROOT / "models"), "MediaPipe Task (*.task);;All Files (*)")
        if path:
            self.model_edit.setText(path)

    def browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select output root", self.output_edit.text())
        if path:
            self.output_edit.setText(path)

    def _build_recordings(self) -> list[BatchRecording]:
        recordings: list[BatchRecording] = []
        previous = {
            (recording.folder, recording.source_video): recording
            for recording in self._recordings_from_table()
        }
        default_camera_base = safe_identifier(self.camera_id_edit.text().strip(), "camera_01")
        for folder in self._folders:
            session_id = self._session_ids.setdefault(folder, f"S{len(self._session_ids) + 1:03d}")
            sources = discover_session_videos(folder)
            used_ids = {
                previous[folder, source].video_id for source in sources if (folder, source) in previous
            }
            for recording_index, source in enumerate(sources, start=1):
                if (folder, source) in previous:
                    recordings.append(previous[folder, source])
                    continue
                if len(sources) == 1:
                    camera_id = default_camera_base
                elif default_camera_base.casefold() == "camera_01":
                    camera_id = f"camera_{recording_index:02d}"
                else:
                    camera_id = f"{default_camera_base}_{recording_index:02d}"
                inferred_angle = infer_camera_angle(source.stem)
                if inferred_angle == "N/A":
                    inferred_angle = str(self.camera_angle_combo.currentData() or "N/A")
                recordings.append(BatchRecording(
                    folder,
                    session_id,
                    source,
                    unique_video_id(source.stem, used_ids),
                    camera_id,
                    inferred_angle,
                ))
        return recordings

    def refresh_recording_table(self) -> None:
        """Rebuild the one-row-per-video table after folder selection changes."""
        if not hasattr(self, "recording_table"):
            return
        self._recordings = self._build_recordings()
        self.recording_table.setRowCount(0)
        for row, recording in enumerate(self._recordings):
            self.recording_table.insertRow(row)
            session_item = QTableWidgetItem(recording.session_id)
            session_item.setFlags(session_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.recording_table.setItem(row, 0, session_item)
            self.recording_table.setItem(row, 1, QTableWidgetItem(recording.video_id))
            source_item = QTableWidgetItem(str(recording.source_video))
            source_item.setFlags(source_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.recording_table.setItem(row, 2, source_item)
            self.recording_table.setItem(row, 3, QTableWidgetItem(recording.camera_id))
            angle_combo = QComboBox()
            for label, value in CAMERA_ANGLE_OPTIONS:
                angle_combo.addItem(label, value)
            angle_index = angle_combo.findData(recording.camera_angle)
            angle_combo.setCurrentIndex(angle_index if angle_index >= 0 else 0)
            self.recording_table.setCellWidget(row, 4, angle_combo)
        self.recording_table.resizeRowsToContents()

    def apply_camera_defaults(self) -> None:
        """Copy the shared camera defaults into every per-recording row."""
        camera_id = self.camera_id_edit.text().strip() or "camera_01"
        camera_angle = self.camera_angle_combo.currentData() or "N/A"
        for row in range(self.recording_table.rowCount()):
            item = self.recording_table.item(row, 3)
            if item is None:
                item = QTableWidgetItem()
                self.recording_table.setItem(row, 3, item)
            item.setText(camera_id)
            combo = self.recording_table.cellWidget(row, 4)
            if isinstance(combo, QComboBox):
                index = combo.findData(camera_angle)
                combo.setCurrentIndex(index if index >= 0 else 0)

    def _recordings_from_table(self) -> list[BatchRecording]:
        """Read editable per-recording identity fields before starting jobs."""
        recordings = list(self._recordings)
        for row, recording in enumerate(recordings):
            video_item = self.recording_table.item(row, 1)
            camera_item = self.recording_table.item(row, 3)
            recording.video_id = safe_identifier(video_item.text() if video_item else recording.video_id, recording.video_id)
            recording.camera_id = safe_identifier(camera_item.text() if camera_item else recording.camera_id, "camera_01")
            combo = self.recording_table.cellWidget(row, 4)
            if isinstance(combo, QComboBox):
                recording.camera_angle = str(combo.currentData() or "N/A")
        return recordings

    def _shared_metadata(self) -> dict[str, Any]:
        values = {
            "camera_name": self.camera_name_edit.text().strip() or None,
            "recording_date": self.recording_date_edit.text().strip() or None,
            "environment": self.environment_edit.text().strip() or None,
            "operator": self.operator_edit.text().strip() or None,
            "notes": self.notes_edit.toPlainText().strip() or None,
            "batch_source_folder_metadata": "shared across selected session folders",
        }
        return {key: value for key, value in values.items() if value is not None}

    def start_processing(self) -> None:
        participant_id = safe_identifier(self.participant_edit.text(), "participant")
        camera_id = safe_identifier(self.camera_id_edit.text(), "camera_01")
        model_path = Path(self.model_edit.text().strip())
        output_root = Path(self.output_edit.text().strip())
        if not self._folders:
            QMessageBox.warning(self, "No session folders", "Add at least one session folder.")
            return
        if not self.participant_edit.text().strip() or not self.camera_id_edit.text().strip():
            QMessageBox.warning(self, "Missing metadata", "Participant ID and Camera ID are required.")
            return
        if not model_path.is_file():
            QMessageBox.warning(self, "Missing MediaPipe model", "Select a valid .task model file.")
            return
        if not self.output_edit.text().strip() or (output_root.exists() and not output_root.is_dir()):
            QMessageBox.warning(self, "Missing output root", "Select an output root.")
            return

        try:
            cfg = load_config(self.config_path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Configuration error", str(exc))
            return
        optional = self._shared_metadata()
        jobs: list[dict[str, Any]] = []
        conflicts: list[str] = []
        recordings = self._recordings_from_table()
        seen_outputs: set[tuple[str, str]] = set()
        for recording in recordings:
            job_name = f"{recording.session_id}/{recording.video_id}"
            output_key = (recording.session_id.casefold(), recording.video_id.casefold())
            if output_key in seen_outputs:
                conflicts.append(f"{job_name}: duplicate Video ID in the same session")
                continue
            seen_outputs.add(output_key)
            row_camera_id = safe_identifier(recording.camera_id, camera_id)
            identifiers = {
                "participant_id": participant_id,
                "session_id": recording.session_id,
                "video_id": recording.video_id,
                "camera_id": row_camera_id,
            }
            try:
                status = processing_job_status(
                    source_video=recording.source_video,
                    model_path=model_path,
                    cfg=cfg,
                    output_root=output_root,
                    session_id=recording.session_id,
                    video_id=recording.video_id,
                    identifiers=identifiers,
                )
            except (OSError, ValueError) as exc:
                conflicts.append(f"{job_name}: {exc}")
                continue
            if status["status"] not in {"new", "resumable", "complete"}:
                conflicts.append(f"{job_name}: {status.get('message', status['status'])}")
                continue
            jobs.append({
                "source_video": recording.source_video,
                "model_path": model_path,
                "cfg": cfg,
                "identifiers": identifiers,
                "optional_metadata": {
                    **optional,
                    "camera_angle": recording.camera_angle or "N/A",
                    "viewpoint": recording.camera_angle or "N/A",
                    "session_folder": str(recording.folder),
                },
                "output_root": output_root,
                "skeleton_line_color": self.preferences.values.skeleton_line,
                "skeleton_joint_color": self.preferences.values.skeleton_joint,
            })
        if conflicts:
            QMessageBox.critical(self, "Processing conflicts", "No files were started because these outputs conflict:\n\n" + "\n".join(conflicts[:12]))
            return
        if not jobs:
            QMessageBox.information(self, "Nothing to process", "No new or resumable video jobs were found.")
            return

        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.status.setText(f"Processing {len(jobs)} recording(s) sequentially. Existing compatible jobs may resume.")
        self.thread = QThread(self)
        self.worker = BatchProcessingWorker(jobs)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.cancelled.connect(self.on_cancelled)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.worker.cancelled.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._finish_success_after_thread)
        self.thread.start()

    def on_progress(self, fraction: float, message: str) -> None:
        self.progress_bar.setValue(int(max(0.0, min(1.0, fraction)) * 1000))
        self.status.setText(message)

    def on_finished(self, results: list[Any]) -> None:
        self.results = list(results)
        self._finish_after_thread_stops = True
        self.status.setText(f"Completed and validated {len(self.results)} recording(s).")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        if self.thread is not None and self.thread.isRunning():
            self.thread.quit()
            return
        self._finish_success_after_thread()

    def _finish_success_after_thread(self) -> None:
        if not self._finish_after_thread_stops:
            return
        self._finish_after_thread_stops = False
        QMessageBox.information(self, "Batch processing complete", f"Processed {len(self.results)} recording(s).\nTheir features are stored in separate session/video Parquet artifacts.")
        self.accept()

    def on_failed(self, message: str) -> None:
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        self.status.setText("Batch processing failed. Completed jobs remain valid and recovery state was preserved.")
        QMessageBox.critical(self, "Batch processing error", message)

    def on_cancelled(self, message: str) -> None:
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        self.status.setText("Batch processing cancelled. Completed jobs remain valid.")
        QMessageBox.information(self, "Batch processing cancelled", message)

    def cancel_or_close(self) -> None:
        if self.worker and self.thread and self.thread.isRunning():
            self.worker.cancel()
            self.status.setText("Cancellation requested. The current persisted checkpoint remains recoverable.")
            self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setEnabled(False)
            return
        self.reject()

    def closeEvent(self, event) -> None:
        if self.worker and self.thread and self.thread.isRunning():
            self.cancel_or_close()
            event.ignore()
            return
        event.accept()
