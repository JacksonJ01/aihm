from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from aihumo.config import load_config
from aihumo.processing import process_video, processing_job_status

LOGGER = logging.getLogger("AIHuMoDataStudio.Mode0")


class ProcessingWorker(QObject):
    progress = pyqtSignal(float, str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal(str)

    def __init__(self, kwargs: dict[str, Any]):
        super().__init__()
        self.kwargs = kwargs
        self.cancel_requested = False

    def cancel(self) -> None:
        self.cancel_requested = True

    def run(self) -> None:
        try:
            result = process_video(
                **self.kwargs,
                progress_callback=self.progress.emit,
                cancel_check=lambda: self.cancel_requested,
            )
            self.finished.emit(result)
        except InterruptedError as exc:
            self.cancelled.emit(str(exc))
        except Exception as exc:
            LOGGER.exception("Video processing failed")
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class ProcessVideoDialog(QDialog):
    """Mode 0: prepare a recording and launch crash-safe processing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AIHuMo — Process New Video")
        self.resize(800, 680)
        self.result = None
        self.thread: QThread | None = None
        self.worker: ProcessingWorker | None = None
        self._finish_after_thread_stops = False
        self.config_path = PROJECT_ROOT / "configs" / "config.json"

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.video_edit = QLineEdit()
        self.model_edit = QLineEdit()
        self.session_edit = QLineEdit("S001")
        self.video_id_edit = QLineEdit("V001")
        self.participant_edit = QLineEdit()
        self.camera_id_edit = QLineEdit("camera_01")
        self.camera_name_edit = QLineEdit()
        self.recording_date_edit = QLineEdit()
        self.exercise_edit = QLineEdit()
        self.viewpoint_edit = QLineEdit()
        self.environment_edit = QLineEdit()
        self.operator_edit = QLineEdit()
        self.notes_edit = QTextEdit(); self.notes_edit.setMaximumHeight(80)
        self.output_edit = QLineEdit(str(PROJECT_ROOT / "data" / "processed"))
        self.open_mode1_check = QCheckBox("Open Mode 1 automatically after successful processing")
        self.open_mode1_check.setChecked(True)

        form.addRow("Source video*", self._browse_row(self.video_edit, self.browse_video, "Video Files (*.mp4 *.mov *.avi *.mkv *.webm);;All Files (*)"))
        form.addRow("Session ID*", self.session_edit)
        form.addRow("Video ID*", self.video_id_edit)
        form.addRow("Participant ID*", self.participant_edit)
        form.addRow("Camera ID*", self.camera_id_edit)
        form.addRow("Camera name", self.camera_name_edit)
        form.addRow("Recording date", self.recording_date_edit)
        form.addRow("Exercise hint", self.exercise_edit)
        form.addRow("Viewpoint", self.viewpoint_edit)
        form.addRow("Environment", self.environment_edit)
        form.addRow("Operator / annotator", self.operator_edit)
        form.addRow("Notes", self.notes_edit)
        form.addRow("MediaPipe model", self._browse_row(self.model_edit, self.browse_model, "MediaPipe Task (*.task);;All Files (*)"))
        form.addRow("Output root", self._browse_row(self.output_edit, self.browse_output, ""))
        form.addRow("Next step", self.open_mode1_check)
        layout.addLayout(form)

        self.status = QLabel("Required: source video, participant ID, session ID, video ID, and camera ID.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.job_status = QLabel("")
        self.job_status.setWordWrap(True)
        layout.addWidget(self.job_status)
        self.progress_label = QLabel("")
        layout.addWidget(self.progress_label)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Process Video")
        self.buttons.accepted.connect(self.start_processing)
        self.buttons.rejected.connect(self.cancel_or_close)
        layout.addWidget(self.buttons)

        default_model = PROJECT_ROOT / "full_model" / "pose_landmarker_full.task"
        if default_model.exists():
            self.model_edit.setText(str(default_model))
        self.video_edit.textChanged.connect(self.refresh_job_status)
        self.session_edit.textChanged.connect(self.refresh_job_status)
        self.video_id_edit.textChanged.connect(self.refresh_job_status)
        self.model_edit.textChanged.connect(self.refresh_job_status)
        self.output_edit.textChanged.connect(self.refresh_job_status)

    @staticmethod
    def _browse_row(edit: QLineEdit, callback, file_filter: str):
        row = QWidget(); layout = QHBoxLayout(row); layout.setContentsMargins(0, 0, 0, 0)
        button = QPushButton("Browse…"); button.clicked.connect(callback)
        layout.addWidget(edit, 1); layout.addWidget(button)
        return row

    def browse_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select source video", "", "Video Files (*.mp4 *.mov *.avi *.mkv *.webm);;All Files (*)")
        if path:
            self.video_edit.setText(path)
            if self.video_id_edit.text() == "V001":
                self.video_id_edit.setText(Path(path).stem)

    def browse_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select MediaPipe model", str(PROJECT_ROOT / "models"), "MediaPipe Task (*.task);;All Files (*)")
        if path:
            self.model_edit.setText(path)

    def browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "Select output root", self.output_edit.text())
        if path:
            self.output_edit.setText(path)

    def refresh_job_status(self):
        source = Path(self.video_edit.text().strip())
        model = Path(self.model_edit.text().strip())
        if not source.exists() or not model.exists() or not self.session_edit.text().strip() or not self.video_id_edit.text().strip():
            self.job_status.clear()
            return
        try:
            cfg = load_config(self.config_path)
            status = processing_job_status(
                source_video=source,
                model_path=model,
                cfg=cfg,
                output_root=Path(self.output_edit.text().strip()),
                session_id=self.session_edit.text().strip(),
                video_id=self.video_id_edit.text().strip(),
            )
        except Exception as exc:
            self.job_status.setText(f"Job check failed: {type(exc).__name__}: {exc}")
            return
        if status["status"] == "resumable":
            self.job_status.setText(
                f"Existing compatible processing job found: stage={status.get('stage')}, "
                f"next frame={status.get('next_frame')}. Starting will resume it."
            )
        elif status["status"] == "complete":
            self.job_status.setText("A completed compatible processing job already exists. Results will be validated and reused.")
        elif status["status"] == "conflict":
            self.job_status.setText(status.get("message", "Existing job conflicts with current inputs."))
        elif status["status"] == "existing_artifacts_without_state":
            self.job_status.setText("Output artifacts already exist without recovery state; AIHuMo will refuse to overwrite them.")
        else:
            self.job_status.setText("No existing processing job found. A new crash-safe job will be created.")

    def start_processing(self):
        source_video = Path(self.video_edit.text().strip())
        model_path = Path(self.model_edit.text().strip())
        if not source_video.exists():
            QMessageBox.warning(self, "Missing source video", "Select a valid source video.")
            return
        if not model_path.exists():
            QMessageBox.warning(self, "Missing MediaPipe model", "Select a valid .task model file.")
            return
        required = {
            "participant_id": self.participant_edit.text().strip(),
            "session_id": self.session_edit.text().strip(),
            "video_id": self.video_id_edit.text().strip(),
            "camera_id": self.camera_id_edit.text().strip(),
        }
        if not all(required.values()):
            QMessageBox.warning(self, "Missing metadata", "Participant ID, Session ID, Video ID, and Camera ID are required.")
            return

        cfg = load_config(self.config_path)
        optional = {
            "camera_name": self.camera_name_edit.text().strip() or None,
            "recording_date": self.recording_date_edit.text().strip() or None,
            "exercise_hint": self.exercise_edit.text().strip() or None,
            "viewpoint": self.viewpoint_edit.text().strip() or None,
            "environment": self.environment_edit.text().strip() or None,
            "operator": self.operator_edit.text().strip() or None,
            "notes": self.notes_edit.toPlainText().strip() or None,
        }
        optional = {key: value for key, value in optional.items() if value is not None}
        identifiers = required

        try:
            status = processing_job_status(
                source_video=source_video,
                model_path=model_path,
                cfg=cfg,
                output_root=Path(self.output_edit.text().strip()),
                session_id=required["session_id"],
                video_id=required["video_id"],
            )
            if status["status"] == "conflict":
                QMessageBox.critical(self, "Processing conflict", status.get("message", "Existing job is incompatible."))
                return
            if status["status"] == "existing_artifacts_without_state":
                QMessageBox.critical(self, "Existing output", "AIHuMo will not overwrite an output directory that lacks a compatible recovery state. Choose a new session/video ID or inspect the existing directory.")
                return
        except Exception as exc:
            QMessageBox.critical(self, "Job check failed", f"{type(exc).__name__}: {exc}")
            return

        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.status.setText("Processing in worker thread. Recovery checkpoints are written during landmark extraction.")
        self.thread = QThread(self)
        self.worker = ProcessingWorker({
            "source_video": source_video,
            "model_path": model_path,
            "cfg": cfg,
            "identifiers": identifiers,
            "optional_metadata": optional,
            "output_root": Path(self.output_edit.text().strip()),
        })
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

    def on_progress(self, fraction: float, message: str):
        self.status.setText(message)
        self.progress_label.setText(f"Progress: {fraction * 100:.1f}%")

    def on_finished(self, result):
        self.result = result
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        self.status.setText("Processing complete and validated.")
        self._finish_after_thread_stops = True
        # The worker's finished signal also requests thread.quit(), but doing
        # it explicitly here makes the lifetime boundary clear. Do not call
        # accept() until QThread.finished; destroying this dialog first can
        # tear down MediaPipe/OpenCV state while the worker thread is alive.
        if self.thread is not None and self.thread.isRunning():
            self.thread.quit()
            return
        self._finish_success_after_thread()

    def _finish_success_after_thread(self):
        if not self._finish_after_thread_stops:
            return
        self._finish_after_thread_stops = False
        QMessageBox.information(
            self,
            "Processing complete",
            f"Features:\n{self.result.features_path}\n\n"
            f"Skeleton video:\n{self.result.processed_video_path}\n\n"
            f"Quality report:\n{self.result.quality_report_path}",
        )
        self.accept()

    def on_failed(self, message: str):
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        self.status.setText("Processing failed. The recovery state was preserved when possible.")
        QMessageBox.critical(self, "Processing error", message)
        self.refresh_job_status()

    def on_cancelled(self, message: str):
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        self.status.setText("Processing cancelled. Saved recovery checkpoints can be resumed later.")
        QMessageBox.information(self, "Processing cancelled", message)
        self.refresh_job_status()

    def cancel_or_close(self):
        if self.worker and self.thread and self.thread.isRunning():
            self.worker.cancel()
            self.status.setText("Cancellation requested. The current persisted checkpoint will remain recoverable.")
            self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setEnabled(False)
            return
        self.reject()

    def closeEvent(self, event):
        if self.worker and self.thread and self.thread.isRunning():
            self.cancel_or_close()
            event.ignore()
            return
        event.accept()
