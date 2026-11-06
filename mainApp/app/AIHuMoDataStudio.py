from __future__ import annotations

import logging
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QComboBox, QDialog, QGroupBox, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from .mode0_process import ProcessVideoDialog
from .mode1_annotation import open_annotation_studio
from aihumo.recent_work import RecentWorkStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
LOGGER = logging.getLogger("AIHuMoDataStudio")


class HomeWindow(QMainWindow):
    """Launcher only. Mode 0 and Mode 1 are implemented in separate modules."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AIHuMo Data Studio")
        self.resize(850, 520)
        self.annotation_window = None
        self.recent_work = RecentWorkStore(PROJECT_ROOT / ".aihumo" / "recent_work.json")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(50, 45, 50, 45)

        title = QLabel("AIHuMo Data Studio")
        title.setStyleSheet("font-size: 28px; font-weight: 700;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(
            "Choose a workflow. Processing and annotation are separate application modes."
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(25)

        buttons = QHBoxLayout()
        self.process_button = QPushButton("Process New Video\nMode 0")
        self.annotate_button = QPushButton("Annotate Existing Data\nMode 1")
        self.process_button.setMinimumHeight(130)
        self.annotate_button.setMinimumHeight(130)
        self.process_button.clicked.connect(self.open_process)
        self.annotate_button.clicked.connect(self.open_annotation)
        buttons.addWidget(self.process_button)
        buttons.addWidget(self.annotate_button)
        layout.addLayout(buttons)
        layout.addSpacing(20)

        resume_group = QGroupBox("Resume Work")
        resume_layout = QHBoxLayout(resume_group)
        self.resume_combo = QComboBox()
        self.resume_combo.setMinimumWidth(500)
        self.resume_button = QPushButton("Resume selected")
        self.resume_button.clicked.connect(self.resume_selected_work)
        resume_layout.addWidget(self.resume_combo, 1)
        resume_layout.addWidget(self.resume_button)
        layout.addWidget(resume_group)
        self.refresh_recent_work()

        workflow = QLabel(
            "Mode 0 — Processing:\n"
            "Source video → MediaPipe → frame DataFrame → engineered features → artifacts\n\n"
            "Mode 1 — Annotation:\n"
            "Processed video + features → temporal labels → atomic JSON checkpoint + derived Parquet"
        )
        workflow.setWordWrap(True)
        layout.addWidget(workflow)
        layout.addStretch(1)
        self.setCentralWidget(central)

    def open_process(self):
        dialog = ProcessVideoDialog(self)
        dialog.exec()
        if dialog.result is not None and dialog.open_mode1_check.isChecked():
            try:
                self.annotation_window = open_annotation_studio(
                    self,
                    video_path=dialog.result.processed_video_path,
                    parquet_path=dialog.result.features_path,
                )
                if self.annotation_window is not None:
                    self.remember_window(self.annotation_window, dialog.result)
                    self.annotation_window.raise_()
                    self.annotation_window.activateWindow()
            except Exception as exc:
                LOGGER.exception("Could not open Mode 1 after Mode 0")
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "Could Not Open Annotation Studio", f"{type(exc).__name__}: {exc}")

    def open_annotation(self):
        try:
            self.annotation_window = open_annotation_studio(self)

            if self.annotation_window is None:
                return
            self.remember_window(self.annotation_window)
            self.annotation_window.raise_()
            self.annotation_window.activateWindow()

        except Exception as exc:
            LOGGER.exception("Could not open Annotation Studio")
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(
                self,
                "Could Not Open Annotation Studio",
                f"{type(exc).__name__}: {exc}",
            )

    def remember_window(self, window, result=None):
        video_path = Path(result.processed_video_path) if result is not None else Path(window.video_path)
        parquet_path = Path(result.features_path) if result is not None else Path(window.parquet_path)
        metadata_path = Path(result.metadata_path) if result is not None else Path(window.metadata_path)
        annotation_json = parquet_path.parent.parent / "annotations" / f"{parquet_path.stem.replace('_features', '_annotations')}.json"
        self.recent_work.add(
            name=f"{window.metadata.get('participant_id', '')} / {window.metadata.get('video_id', parquet_path.stem)}",
            files={
                "processedVideo": str(video_path),
                "featuresParquet": str(parquet_path),
                "metadataJson": str(metadata_path),
                "annotationJson": str(annotation_json),
            },
            identifiers={key: window.metadata.get(key) for key in ("participant_id", "session_id", "video_id", "camera_id")},
        )
        self.refresh_recent_work()

    def refresh_recent_work(self):
        self.resume_combo.clear()
        if not self.recent_work.items:
            self.resume_combo.addItem("No recent workspaces yet")
            self.resume_button.setEnabled(False)
            return
        for item in self.recent_work.items:
            files = item.get("files", {})
            self.resume_combo.addItem(item.get("name", "Unnamed workspace"), item)
        self.resume_button.setEnabled(True)

    def resume_selected_work(self):
        item = self.resume_combo.currentData()
        if not isinstance(item, dict):
            return
        files = item.get("files", {})
        video = Path(files.get("processedVideo", ""))
        parquet = Path(files.get("featuresParquet", ""))
        if not video.exists() or not parquet.exists():
            QMessageBox.warning(self, "Workspace unavailable", "The saved video or feature Parquet path no longer exists.")
            return
        try:
            self.annotation_window = open_annotation_studio(self, video_path=video, parquet_path=parquet)
            if self.annotation_window is not None:
                self.remember_window(self.annotation_window)
                self.annotation_window.raise_()
                self.annotation_window.activateWindow()
        except Exception as exc:
            LOGGER.exception("Could not resume workspace")
            QMessageBox.critical(self, "Could Not Resume Work", f"{type(exc).__name__}: {exc}")

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AIHuMo Data Studio")
    window = HomeWindow()
    # Use the desktop's native maximized state so the launcher and any
    # restored annotation window fit the active monitor without hard-coded
    # pixel geometry or a second layout jump after the first click.
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
