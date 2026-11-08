from __future__ import annotations

import logging
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from .mode0_process import ProcessVideoDialog
from .mode0_batch import BatchSessionDialog
from .mode1_annotation import open_annotation_studio
from .graph_viewer import open_graph_viewer
from .preferences import PreferencesDialog, PreferenceStore
from aihumo.recent_work import RecentWorkStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
LOGGER = logging.getLogger("AIHuMoDataStudio")


class HomeWindow(QMainWindow):
    """Launcher only. Mode 0 and Mode 1 are implemented in separate modules."""

    def __init__(self, *, state_dir: Path | None = None):
        super().__init__()
        self.setWindowTitle("AIHuMo Data Studio")
        self.resize(960, 690)
        self.annotation_window = None
        self.graph_window = None
        state_dir = state_dir if state_dir is not None else PROJECT_ROOT / ".aihumo"
        self.recent_work = RecentWorkStore(state_dir / "recent_work.json")
        self.recent_graphs = RecentWorkStore(state_dir / "recent_graphs.json")
        self.preferences = PreferenceStore(state_dir / "settings.json")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(50, 45, 50, 45)

        title = QLabel("AIHuMo Data Studio")
        title.setStyleSheet("font-size: 28px; font-weight: 700;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header = QHBoxLayout()
        self.settings_button = QPushButton("⚙ Settings")
        self.settings_button.clicked.connect(self.open_settings)
        header.addSpacing(self.settings_button.sizeHint().width())
        header.addWidget(title, 1)
        header.addWidget(self.settings_button)
        layout.addLayout(header)

        subtitle = QLabel(
            "Choose a workflow. Processing and annotation are separate application modes."
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(25)

        buttons = QGridLayout()
        buttons.setHorizontalSpacing(12)
        buttons.setVerticalSpacing(12)
        self.process_button = QPushButton("Process New Video\nMode 0")
        self.batch_button = QPushButton("Process Session Folders\nMode 0 Batch")
        self.annotate_button = QPushButton("Annotate Existing Data\nMode 1")
        self.viewer_button = QPushButton("Interactive Graph Viewer\nLoad Video + Parquet")
        self.model_button = QPushButton("Model Lab\nMode 2 — Coming Soon")
        self.workflows = QButtonGroup(self)
        self.workflows.setExclusive(True)
        for button in (self.process_button, self.batch_button, self.annotate_button,
                       self.viewer_button, self.model_button):
            button.setMinimumHeight(95)
            button.setCheckable(True)
            self.workflows.addButton(button)
        self._apply_launcher_accent()
        self.process_button.clicked.connect(self.open_process)
        self.batch_button.clicked.connect(self.open_batch)
        self.annotate_button.clicked.connect(self.open_annotation)
        self.viewer_button.clicked.connect(self.open_interactive_viewer)
        self.model_button.clicked.connect(self.open_model_lab)
        buttons.addWidget(self.process_button, 0, 0)
        buttons.addWidget(self.batch_button, 0, 1)
        buttons.addWidget(self.annotate_button, 0, 2)
        buttons.addWidget(self.viewer_button, 1, 0)
        buttons.addWidget(self.model_button, 1, 1)
        layout.addLayout(buttons)
        layout.addSpacing(20)

        resumes = QHBoxLayout()
        annotation_resume, self.resume_combo, self.resume_button = self._resume_controls(
            "Resume Mode 1 Annotation", self.resume_selected_work,
        )
        graph_resume, self.graph_resume_combo, self.graph_resume_button = self._resume_controls(
            "Resume Interactive Graph Viewer", self.resume_graph_work,
        )
        resumes.addWidget(annotation_resume, 1)
        resumes.addWidget(graph_resume, 1)
        layout.addLayout(resumes)
        self.refresh_recent_work()
        self.refresh_recent_graphs()

        workflow = QLabel(
            "Mode 0 — Processing:\n"
            "Source video → MediaPipe → frame DataFrame → engineered features → artifacts\n\n"
            "Mode 1 — Annotation:\n"
            "Processed video + canonical features → synchronized frames and temporal labels\n\n"
            "Interactive Graph Viewer — Skeleton video and synchronized joint-angle inspection\n\n"
            "Mode 2 — Model Lab:\n"
            "Planned interchangeable model experiments; not connected yet"
        )
        workflow.setWordWrap(True)
        layout.addWidget(workflow)
        layout.addStretch(1)
        self.setCentralWidget(central)

    @staticmethod
    def _resume_controls(title, callback):
        group = QGroupBox(title)
        layout = QHBoxLayout(group)
        combo = QComboBox()
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(16)
        button = QPushButton("Resume")
        button.clicked.connect(callback)
        layout.addWidget(combo, 1)
        layout.addWidget(button)
        return group, combo, button

    def _apply_launcher_accent(self):
        color = self.preferences.values.launcher_accent
        for button in self.workflows.buttons():
            button.setStyleSheet(
                "QPushButton { border: 2px solid palette(mid); border-radius: 6px;"
                " background: palette(button); color: palette(button-text); padding: 7px; }"
                "QPushButton:hover { background: palette(alternate-base); }"
                f"QPushButton:checked {{ border: 3px solid {color}; }}"
            )

    def open_settings(self):
        if PreferencesDialog(self.preferences, self).exec() == QDialog.DialogCode.Accepted:
            self._apply_launcher_accent()
            for window in (self.annotation_window, self.graph_window):
                if window is not None and window.isVisible():
                    window.frame_highlight = self.preferences.values.frame_highlight
                    window._refresh_thumbnails()

    def open_process(self):
        dialog = ProcessVideoDialog(self, preferences=self.preferences)
        dialog.exec()
        if dialog.result is not None and dialog.open_mode1_check.isChecked():
            try:
                self.annotation_window = open_annotation_studio(
                    self,
                    video_path=dialog.result.processed_video_path,
                    parquet_path=dialog.result.features_path,
                    metadata_path=dialog.result.metadata_path,
                    frame_highlight=self.preferences.values.frame_highlight,
                    frame_jump=self.preferences.values.default_frame_jump,
                )
                if self.annotation_window is not None:
                    self.remember_window(self.annotation_window, dialog.result)
                    self.annotation_window.raise_()
                    self.annotation_window.activateWindow()
            except Exception as exc:
                LOGGER.exception("Could not open Mode 1 after Mode 0")
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "Could Not Open Annotation Studio", f"{type(exc).__name__}: {exc}")

    def open_batch(self):
        dialog = BatchSessionDialog(self, preferences=self.preferences)
        dialog.exec()
        if not dialog.results or not dialog.open_mode1_check.isChecked():
            return
        first = dialog.results[0]
        try:
            self.annotation_window = open_annotation_studio(
                self,
                video_path=first.processed_video_path,
                parquet_path=first.features_path,
                metadata_path=first.metadata_path,
                frame_highlight=self.preferences.values.frame_highlight,
                frame_jump=self.preferences.values.default_frame_jump,
            )
            if self.annotation_window is not None:
                self.remember_window(self.annotation_window, first)
                self.annotation_window.raise_()
                self.annotation_window.activateWindow()
        except Exception as exc:
            LOGGER.exception("Could not open first batch result in Mode 1")
            QMessageBox.critical(self, "Could Not Open Annotation Studio", f"{type(exc).__name__}: {exc}")

    def open_annotation(self):
        try:
            self.annotation_window = open_annotation_studio(
                self, frame_highlight=self.preferences.values.frame_highlight,
                frame_jump=self.preferences.values.default_frame_jump,
            )

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

    def open_interactive_viewer(self):
        self._show_graph_viewer()

    def _show_graph_viewer(self, **workspace):
        try:
            viewer = open_graph_viewer(
                self, frame_highlight=self.preferences.values.frame_highlight,
                frame_jump=self.preferences.values.default_frame_jump, **workspace,
            )
        except Exception as exc:
            LOGGER.exception("Could not open Interactive Graph Viewer")
            QMessageBox.critical(self, "Could Not Open Interactive Graph Viewer", f"{type(exc).__name__}: {exc}")
            return
        if viewer is None:
            return
        if self.graph_window is not None:
            self.graph_window.close()
        self.graph_window = viewer
        viewer.closed.connect(self._clear_graph_window)
        video, parquet = str(viewer.video_path.resolve()), str(viewer.parquet_path.resolve())
        try:
            self.recent_graphs.add(
                name=viewer.video_path.stem.removesuffix("_skeleton"),
                files={"processedVideo": video, "featuresParquet": parquet},
                last_frame=viewer.current_frame,
            )
            self.refresh_recent_graphs()
        except OSError as exc:
            LOGGER.exception("Could not save the graph workspace")
            QMessageBox.warning(self, "Graph resume unavailable", str(exc))
        viewer.position_checkpoint.connect(lambda frame: self._save_graph_position(video, parquet, frame))
        viewer.raise_()
        viewer.activateWindow()

    def _clear_graph_window(self):
        if self.graph_window is self.sender():
            self.graph_window = None

    def _save_graph_position(self, video: str, parquet: str, frame: int):
        try:
            if self.recent_graphs.save_frame(video=video, parquet=parquet, frame=frame):
                self.refresh_recent_graphs(keep_selection=True)
        except OSError:
            LOGGER.exception("Could not save the last graph frame")

    def open_model_lab(self):
        """Show the planned model families without pretending they are wired."""
        QMessageBox.information(
            self,
            "Mode 2 — Model Lab",
            "The model-training and inference pipeline is not connected yet.\n\n"
            "Planned interchangeable model families:\n"
            "• 1D CNN\n"
            "• Temporal Convolutional Network (TCN)\n"
            "• LSTM\n"
            "• Spatio-Temporal Graph Convolutional Network (ST-GCN)\n"
            "• Graph Convolutional Network (GCN)\n"
            "• Deep Neural Network (DNN)\n\n"
            "This button is a navigation placeholder for the future Mode 2 model lab.",
        )

    def remember_window(self, window, result=None):
        window.closed.connect(self._clear_annotation_window)
        video_path = Path(result.processed_video_path) if result is not None else Path(window.video_path)
        parquet_path = Path(result.features_path) if result is not None else Path(window.parquet_path)
        metadata_path = Path(result.metadata_path) if result is not None else Path(window.metadata_path)
        annotation_json = window.annotation_json_path
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

    def _clear_annotation_window(self):
        if self.annotation_window is self.sender():
            self.annotation_window = None

    def refresh_recent_work(self):
        self.resume_combo.clear()
        if not self.recent_work.items:
            self.resume_combo.addItem("No recent workspaces yet")
            self.resume_button.setEnabled(False)
            return
        for item in self.recent_work.items:
            self.resume_combo.addItem(item.get("name", "Unnamed workspace"), item)
        self.resume_button.setEnabled(True)

    def refresh_recent_graphs(self, *, keep_selection=False):
        combo = self.graph_resume_combo
        selected = combo.currentIndex() if keep_selection else 0
        combo.clear()
        for item in self.recent_graphs.items:
            name = item.get("name", "Unnamed recording")
            frame = item.get("lastFrame", 0)
            combo.addItem(f"{name} (frame {frame})", item)
        available = bool(self.recent_graphs.items)
        if available:
            combo.setCurrentIndex(min(max(selected, 0), combo.count() - 1))
        else:
            combo.addItem("No graphs opened yet")
        self.graph_resume_button.setEnabled(available)

    def _saved_workspace(self, combo):
        item = combo.currentData()
        if not isinstance(item, dict):
            return
        files = item.get("files", {})
        video = Path(files.get("processedVideo", ""))
        parquet = Path(files.get("featuresParquet", ""))
        if not video.is_file() or not parquet.is_file():
            QMessageBox.warning(self, "Workspace unavailable", "The saved video or feature Parquet path no longer exists.")
            return
        return item, video, parquet

    def resume_graph_work(self):
        workspace = self._saved_workspace(self.graph_resume_combo)
        if workspace is None:
            return
        item, video, parquet = workspace
        self.viewer_button.setChecked(True)
        viewer = self.graph_window
        if (viewer is not None and viewer.isVisible()
                and viewer.video_path.resolve() == video.resolve()
                and viewer.parquet_path.resolve() == parquet.resolve()):
            viewer.raise_()
            viewer.activateWindow()
            return
        frame = item.get("lastFrame")
        self._show_graph_viewer(
            video_path=video, parquet_path=parquet, frame=frame if isinstance(frame, int) else 0,
        )

    def resume_selected_work(self):
        workspace = self._saved_workspace(self.resume_combo)
        if workspace is None:
            return
        item, video, parquet = workspace
        files = item["files"]
        metadata = files.get("metadataJson")
        self.annotate_button.setChecked(True)
        try:
            self.annotation_window = open_annotation_studio(
                self, video_path=video, parquet_path=parquet,
                metadata_path=metadata if metadata and Path(metadata).is_file() else None,
                annotation_json_path=files.get("annotationJson") or None,
                frame_highlight=self.preferences.values.frame_highlight,
                frame_jump=self.preferences.values.default_frame_jump,
            )
            if self.annotation_window is not None:
                self.remember_window(self.annotation_window)
                self.annotation_window.raise_()
                self.annotation_window.activateWindow()
        except Exception as exc:
            LOGGER.exception("Could not resume workspace")
            QMessageBox.critical(self, "Could Not Resume Mode 1 Annotation", f"{type(exc).__name__}: {exc}")

    def closeEvent(self, event):
        if self.annotation_window is not None and not self.annotation_window.close():
            event.ignore()
            return
        if self.graph_window is not None:
            self.graph_window.close()
        super().closeEvent(event)

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
