from __future__ import annotations

import logging
import sys
from pathlib import Path

from PyQt6.QtCore import QProcess, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDialog, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QSizePolicy, QStackedWidget, QStyle, QToolButton,
    QVBoxLayout, QWidget,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__" and not __package__:
    # Give direct script launches the same package context as the launcher.
    sys.path.insert(0, str(PROJECT_ROOT))
    __package__ = "app"

SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from .mode0_process import ProcessVideoDialog
from .mode0_batch import BatchSessionDialog
from .mode1_annotation import open_annotation_studio
from .mode2_alignment import SessionAlignmentWindow
from .graph_viewer import open_graph_viewer
from .common import suspend_other_reviews
from .pose_viewer import PoseGraphViewer
from .preferences import PreferencesDialog, PreferenceStore, StartupSetupDialog
from .processing_resume import processing_fields
from aihumo.recent_work import RecentWorkStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
LOGGER = logging.getLogger("AIHuMoDataStudio")

MODE_NAMES = (
    "Processing", "Annotation", "Session Alignment", "Interactive Graph Viewer (2D)",
    "Interactive Graph Viewer (3D)", "Model Suite",
)


class ModeTile(QPushButton):
    """Select on click and open on double-click or Enter."""

    open_requested = pyqtSignal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self.open_requested.emit()
        else:
            super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            if not event.isAutoRepeat():
                self.open_requested.emit()
        else:
            super().keyPressEvent(event)


class ProcessingCard(QStackedWidget):
    """One Mode 0 tile with two actions on hover or keyboard activation."""

    def __init__(self, choose_mode):
        super().__init__()
        self.face = QPushButton("Process New Video\nMode 0")
        self.face.setToolTip("Choose a single video or a video batch.")
        self.face.clicked.connect(lambda: self._reveal(choose_mode))
        self.addWidget(self.face)
        options = QWidget()
        layout = QHBoxLayout(options)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.single = QPushButton("New Video\nMode 0")
        self.batch = QPushButton("Video Batch\nMode 0")
        for button in (self.single, self.batch):
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            layout.addWidget(button, 1)
        self.addWidget(options)

    def _reveal(self, choose_mode):
        choose_mode(0)
        self.setCurrentIndex(1)
        self.single.setFocus()

    def enterEvent(self, event):
        self.setCurrentIndex(1)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setCurrentIndex(0)
        super().leaveEvent(event)


class HomeWindow(QMainWindow):
    """Launcher for the Data Studio workspaces."""

    def __init__(self, *, state_dir: Path | None = None, processed_root: Path | None = None):
        super().__init__()
        self.setWindowTitle("AIHuMo Data Studio")
        self.resize(960, 690)
        self.annotation_window = None
        self.graph_window = None
        self._graph_mode = 3
        self.alignment_window = None
        self._using_default_state = state_dir is None
        self.processed_root = processed_root if processed_root is not None else PROJECT_ROOT / "data" / "processed"
        state_dir = state_dir if state_dir is not None else PROJECT_ROOT / ".aihumo"
        self.recent_work = RecentWorkStore(state_dir / "recent_work.json")
        self.recent_graphs = RecentWorkStore(state_dir / "recent_graphs.json")
        self.recent_poses = RecentWorkStore(state_dir / "recent_poses.json")
        self.recent_alignments = RecentWorkStore(state_dir / "recent_alignments.json", identity_keys=("alignmentJson",))
        self.recent_processing = RecentWorkStore(state_dir / "recent_processing.json",
                                                 identity_keys=("sourceVideo", "batchFolders", "outputRoot", "jobId"))
        self.resume_stores = {0: self.recent_processing, 1: self.recent_work, 2: self.recent_alignments,
                              3: self.recent_graphs, 4: self.recent_poses}
        self._selected_mode = 1
        self.preferences = PreferenceStore(state_dir / "settings.json")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(50, 45, 50, 45)

        title = QLabel("AIHuMo Data Studio")
        title.setStyleSheet("font-size: 28px; font-weight: 700;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header = QHBoxLayout()
        self.setup_button = QPushButton("Setup…")
        self.setup_button.setToolTip("Run the optional participant and starter-video setup again.")
        self.setup_button.clicked.connect(self.open_startup_setup)
        self.settings_button = QPushButton("⚙ Settings")
        self.settings_button.clicked.connect(self.open_settings)
        header.addSpacing(self.setup_button.sizeHint().width() + self.settings_button.sizeHint().width())
        header.addWidget(title, 1)
        header.addWidget(self.setup_button)
        header.addWidget(self.settings_button)
        layout.addLayout(header)

        subtitle = QLabel("Click a mode to see recent work. Double-click it to open a new workspace.")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(25)

        buttons = QGridLayout()
        buttons.setHorizontalSpacing(12)
        buttons.setVerticalSpacing(12)
        for column in range(3):
            buttons.setColumnStretch(column, 1)
        self.processing_card = ProcessingCard(self._select_mode)
        self.process_button = self.processing_card.single
        self.batch_button = self.processing_card.batch
        self.annotate_button = ModeTile("Annotate Existing Data\nMode 1")
        self.alignment_button = ModeTile("Session Alignment\nMode 2")
        self.viewer_button = ModeTile("Interactive Graph Viewer (2D)\nMode 3")
        self.pose_button = ModeTile("Interactive Graph Viewer (3D)\nMode 4")
        self.model_button = ModeTile("Model Suite\nMode 5 — Coming Soon")
        self.workflows = QButtonGroup(self)
        self.workflows.setExclusive(True)
        for mode, button in enumerate((self.processing_card.face, self.annotate_button, self.alignment_button,
                                       self.viewer_button, self.pose_button, self.model_button)):
            button.setMinimumHeight(95)
            button.setCheckable(True)
            self.workflows.addButton(button, mode)
        self._apply_launcher_accent()
        self.process_button.clicked.connect(self.open_process)
        self.batch_button.clicked.connect(self.open_batch)
        for mode, (button, open_workspace) in enumerate((
            (self.annotate_button, self.open_annotation),
            (self.alignment_button, self.open_session_alignment),
            (self.viewer_button, self.open_interactive_viewer),
            (self.pose_button, lambda: self._show_graph_viewer(mode=4)),
            (self.model_button, self.open_model_suite),
        ), start=1):
            button.setToolTip("Click to update Resume. Double-click or press Enter to open.")
            button.clicked.connect(lambda _checked, mode=mode: self._select_mode(mode))
            button.open_requested.connect(open_workspace)
        buttons.addWidget(self.processing_card, 0, 0)
        buttons.addWidget(self.annotate_button, 0, 1)
        buttons.addWidget(self.alignment_button, 0, 2)
        buttons.addWidget(self.viewer_button, 1, 0)
        buttons.addWidget(self.pose_button, 1, 1)
        buttons.addWidget(self.model_button, 1, 2)
        self.prepare_button = QPushButton("Prepare existing recording…")
        self.prepare_button.setToolTip("Save review measurements from existing landmarks without rerunning pose detection.")
        self.prepare_button.clicked.connect(self.prepare_existing_recording)
        buttons.addWidget(self.prepare_button, 2, 0)
        self._prepare_process = None
        layout.addLayout(buttons)
        layout.addSpacing(20)

        self.resume_group, self.resume_combo, self.resume_button, self.resume_remove_button = self._resume_controls()
        layout.addWidget(self.resume_group)
        self._select_mode(self._selected_mode)
        if self._using_default_state and not self.preferences.values.setup_completed:
            QTimer.singleShot(0, self.open_startup_setup)

        workflow = QLabel(
            "Mode 0 — Process a new video or a batch of session folders.\n"
            "Mode 1 — Label activity, sets, reps, phases, and form.\n"
            "Mode 2 — Align and review multiple cameras on one timeline.\n"
            "Mode 3 — Inspect synchronized joint angles and landmark graphs.\n"
            "Mode 4 — Rotate the saved 3D pose or inspect its 2D projections.\n"
            "Mode 5 — Planned model training and inference."
        )
        workflow.setWordWrap(True)
        layout.addWidget(workflow)
        layout.addStretch(1)
        self.setCentralWidget(central)

    def _resume_controls(self):
        group = QGroupBox()
        layout = QHBoxLayout(group)
        combo = QComboBox()
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(16)
        button = QPushButton("Resume")
        button.clicked.connect(self.resume_current_work)
        remove = QToolButton()
        remove.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        remove.setAccessibleName("Remove from recent work")
        remove.setToolTip("Remove the selected entry from Resume history. Its files stay on disk.")
        remove.clicked.connect(self.remove_recent_work)
        layout.addWidget(combo, 1)
        layout.addWidget(button)
        layout.addWidget(remove)
        return group, combo, button, remove

    def _apply_launcher_accent(self):
        color = self.preferences.values.launcher_accent
        for button in (*self.workflows.buttons(), self.process_button, self.batch_button):
            button.setStyleSheet(
                "QPushButton { border: 2px solid palette(mid); border-radius: 6px;"
                " background: palette(button); color: palette(button-text); padding: 7px; }"
                "QPushButton:hover { background: palette(alternate-base); }"
                f"QPushButton:checked {{ border: 3px solid {color}; }}"
            )

    def _select_mode(self, mode):
        changed = self._selected_mode != mode
        self._selected_mode = mode
        self.workflows.button(mode).setChecked(True)
        self._refresh_resume(keep_selection=not changed)

    def _refresh_resume(self, *, keep_selection=True):
        mode = self._selected_mode
        previous = self.resume_combo.currentData()
        selected_files = previous.get("files") if keep_selection and isinstance(previous, dict) else None
        self.resume_group.setTitle(f"Resume Mode {mode} · {MODE_NAMES[mode]}")
        self.resume_combo.clear()
        store = self.resume_stores.get(mode)
        items = store.items if store is not None else []
        if mode == 2:
            known = {item.get("files", {}).get("alignmentJson") for item in items}
            items = list(items)
            for path in sorted(self.processed_root.glob("*/alignment.json")):
                files = {"alignmentJson": str(path.resolve())}
                if files["alignmentJson"] not in known and not store.is_dismissed(files):
                    items.append({"name": f"{path.parent.name} / {path.stem}", "files": files})
        if not items:
            self.resume_combo.addItem("No recent items for this mode")
        for item in items:
            name = item.get("name", "Unnamed workspace")
            if mode in (3, 4):
                name += f" (frame {item.get('lastFrame', 0)})"
            self.resume_combo.addItem(name, item)
            if item.get("files") == selected_files:
                self.resume_combo.setCurrentIndex(self.resume_combo.count() - 1)
        self.resume_button.setEnabled(bool(items))
        self.resume_remove_button.setEnabled(bool(items))

    def remove_recent_work(self):
        mode = self._selected_mode
        item = self.resume_combo.currentData()
        if not isinstance(item, dict):
            return
        try:
            self.resume_stores[mode].remove(item["files"], hide_discovered=mode == 2)
        except OSError as exc:
            LOGGER.exception("Could not remove the recent workspace")
            QMessageBox.warning(self, "Could Not Remove Recent Work", str(exc))
            return
        self._refresh_resume()

    def _activate_review(self, target):
        target.activate_review()
        target.raise_()
        target.activateWindow()

    def _remember_processing(self, name, fields, **files):
        try:
            self.recent_processing.add(name=name, files={**files, "outputRoot": fields.get("output")},
                                       identifiers=fields)
            if self._selected_mode == 0:
                self._refresh_resume()
        except OSError:
            LOGGER.exception("Could not save the processing setup")

    def open_settings(self):
        if PreferencesDialog(self.preferences, self).exec() == QDialog.DialogCode.Accepted:
            self._apply_launcher_accent()

    def open_startup_setup(self):
        dialog = StartupSetupDialog(self.preferences, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        setup = dialog.setup
        if setup.get("open_video") and setup.get("video"):
            QTimer.singleShot(0, lambda: self.open_starter_video(setup["video"]))

    @staticmethod
    def _starter_artifacts(video: Path) -> tuple[Path | None, Path | None]:
        """Find the processed-video/feature pair associated with a starter video."""
        stem = video.stem.removesuffix("_skeleton")
        candidates = (
            (video, video.parent.parent / "features" / f"{stem}_features.parquet"),
            (video, video.with_name(f"{stem}_features.parquet")),
            (video, video.parent / f"{stem}_features.parquet"),
        )
        for processed_video, parquet in candidates:
            if processed_video.is_file() and parquet.is_file():
                return processed_video, parquet
        return video, None

    def open_starter_video(self, raw_path: str):
        video, parquet = self._starter_artifacts(Path(raw_path).expanduser())
        if video is None or not video.is_file():
            QMessageBox.warning(self, "Starter video unavailable", "The saved starter video no longer exists.")
            return
        if parquet is not None:
            self._show_graph_viewer(mode=3, video_path=video, parquet_path=parquet)
            return
        # A raw video is not processed silently: open Mode 0 with it prefilled
        # so the user can review the participant/output choices before running.
        self.open_process(setup={
            "files": {"sourceVideo": str(video)},
            "identifiers": {"participant": self.preferences.values.default_participant},
        })

    def open_process(self, *, setup=None):
        self._select_mode(0)
        dialog = ProcessVideoDialog(self, preferences=self.preferences)
        if setup is not None:
            dialog.restore_setup(setup["files"]["sourceVideo"], setup["identifiers"])
        suspend_other_reviews()
        dialog.exec()
        video = Path(dialog.video_edit.text().strip())
        if video.is_file():
            fields = processing_fields(dialog)
            self._remember_processing(f"New Video · {video.name}", fields,
                                      sourceVideo=str(video.resolve()), jobId=f"{fields['session']}/{fields['video_id']}")
        if dialog.result is not None and dialog.open_mode1_check.isChecked():
            try:
                self.annotation_window = open_annotation_studio(
                    self,
                    video_path=dialog.result.processed_video_path,
                    parquet_path=dialog.result.features_path,
                    metadata_path=dialog.result.metadata_path,
                    frame_jump=self.preferences.values.default_frame_jump,
                )
                if self.annotation_window is not None:
                    self.remember_window(self.annotation_window, dialog.result)
                    self._activate_review(self.annotation_window)
            except Exception as exc:
                LOGGER.exception("Could not open Mode 1 after Mode 0")
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "Could Not Open Annotation Studio", f"{type(exc).__name__}: {exc}")

    def prepare_existing_recording(self):
        features, _ = QFileDialog.getOpenFileName(self, "Choose the existing feature Parquet", "", "Features (*_features.parquet)")
        if not features:
            return
        path = Path(features)
        suggested = path.parent.parent / "video" / f"{path.stem.removesuffix('_features')}_skeleton.mp4"
        video, _ = QFileDialog.getOpenFileName(self, "Choose the matching skeleton video", str(suggested), "Video (*.mp4 *.mov *.mkv *.avi)")
        if not video:
            return
        process = QProcess(self)
        self._prepare_process = process
        self.prepare_button.setEnabled(False)
        self.prepare_button.setText("Preparing recording…")

        def finished(success, message):
            if self._prepare_process is not process:
                return
            self._prepare_process = None
            self.prepare_button.setEnabled(True)
            self.prepare_button.setText("Prepare existing recording…")
            process.deleteLater()
            if success:
                QMessageBox.information(self, "Recording prepared", message)
            else:
                QMessageBox.warning(self, "Could not prepare recording", message)

        process.finished.connect(lambda code, status: finished(
            code == 0 and status == QProcess.ExitStatus.NormalExit,
            bytes(process.readAllStandardOutput() if code == 0 else process.readAllStandardError()).decode(errors="replace").strip()[-2000:]
            or "The preparation process stopped unexpectedly.",
        ))
        process.errorOccurred.connect(lambda error: finished(False, process.errorString())
                                      if error == QProcess.ProcessError.FailedToStart else None)
        arguments = ["--features", features, "--video", video]
        if getattr(sys, "frozen", False):
            arguments.insert(0, "--prepare-viewer-features")
        else:
            arguments.insert(0, str(PROJECT_ROOT / "scripts" / "prepare_viewer_features.py"))
        process.start(sys.executable, arguments)

    def open_batch(self, *, setup=None):
        self._select_mode(0)
        dialog = BatchSessionDialog(self, preferences=self.preferences)
        if setup is not None:
            dialog.restore_setup(setup["identifiers"])
        suspend_other_reviews()
        dialog.exec()
        fields = dialog.resume_setup()
        if fields["folders"]:
            folders = [folder["path"] for folder in fields["folders"]]
            name = Path(folders[0]).name
            if len(folders) > 1:
                name += f" + {len(folders) - 1} more"
            self._remember_processing(f"Video Batch · {name}", fields, batchFolders="|".join(folders))
        if not dialog.results or not dialog.open_mode1_check.isChecked():
            return
        first = dialog.results[0]
        try:
            self.annotation_window = open_annotation_studio(
                self,
                video_path=first.processed_video_path,
                parquet_path=first.features_path,
                metadata_path=first.metadata_path,
                frame_jump=self.preferences.values.default_frame_jump,
            )
            if self.annotation_window is not None:
                self.remember_window(self.annotation_window, first)
                self._activate_review(self.annotation_window)
        except Exception as exc:
            LOGGER.exception("Could not open first batch result in Mode 1")
            QMessageBox.critical(self, "Could Not Open Annotation Studio", f"{type(exc).__name__}: {exc}")

    def open_annotation(self):
        self._select_mode(1)
        try:
            self.annotation_window = open_annotation_studio(
                self,
                frame_jump=self.preferences.values.default_frame_jump,
            )

            if self.annotation_window is None:
                return
            self.remember_window(self.annotation_window)
            self._activate_review(self.annotation_window)

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

    def _show_graph_viewer(self, *, mode=3, **workspace):
        self._select_mode(mode)
        if mode == 4:
            workspace["viewer_class"] = PoseGraphViewer
        try:
            viewer = open_graph_viewer(
                self,
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
        self._graph_mode = mode
        viewer.closed.connect(self._clear_graph_window)
        viewer.annotation_requested.connect(self._open_graph_annotations)
        video, parquet = str(viewer.video_path.resolve()), str(viewer.parquet_path.resolve())
        try:
            self.resume_stores[mode].add(
                name=viewer.video_path.stem.removesuffix("_skeleton"),
                files={"processedVideo": video, "featuresParquet": parquet},
                last_frame=viewer.current_frame,
            )
            self._refresh_resume()
        except OSError as exc:
            LOGGER.exception("Could not save the graph workspace")
            QMessageBox.warning(self, "Graph resume unavailable", str(exc))
        viewer.position_checkpoint.connect(lambda frame: self._save_graph_position(mode, video, parquet, frame))
        self._activate_review(viewer)

    def _open_graph_annotations(self):
        viewer = self.sender()
        if viewer is not self.graph_window or viewer is None:
            return
        video, parquet = viewer.video_path.resolve(), viewer.parquet_path.resolve()
        window = self.annotation_window
        try:
            if window is not None and window.parquet_path.resolve() != parquet:
                if not window.close():
                    return
                window = None
            if window is None:
                files = next((item["files"] for item in self.recent_work.items
                              if item.get("files", {}).get("featuresParquet")
                              and Path(item["files"]["featuresParquet"]).resolve() == parquet), {})
                metadata = files.get("metadataJson")
                window = open_annotation_studio(
                    self, video_path=video, parquet_path=parquet,
                    metadata_path=metadata if metadata and Path(metadata).is_file() else None,
                    annotation_json_path=files.get("annotationJson") or None,
                    frame_jump=viewer.jump_spin.value(),
                )
                self.annotation_window = window
                self.remember_window(window)
            if not window.goto_frame(viewer.current_frame):
                raise ValueError(f"Could not show graph frame {viewer.current_frame} in Annotation Studio.")
            window.link_graph_viewer(viewer)
            self._select_mode(1)
            self._activate_review(window)
        except Exception as exc:
            LOGGER.exception("Could not open the graph recording in Annotation Studio")
            QMessageBox.critical(self, "Could Not Open Annotation Studio", str(exc))

    def _clear_graph_window(self):
        if self.graph_window is self.sender():
            self.graph_window = None

    def _save_graph_position(self, mode: int, video: str, parquet: str, frame: int):
        try:
            if self.resume_stores[mode].save_frame(video=video, parquet=parquet, frame=frame) and self._selected_mode == mode:
                self._refresh_resume()
        except OSError:
            LOGGER.exception("Could not save the last graph frame")

    def open_session_alignment(self):
        self._select_mode(2)
        if self.alignment_window is None:
            self.alignment_window = SessionAlignmentWindow(
                self, self.processed_root,
                frame_jump=self.preferences.values.default_frame_jump,
            )
            self.alignment_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self.alignment_window.closed.connect(self._clear_alignment_window)
            self.alignment_window.saved_alignment_opened.connect(self._remember_alignment)
        self.alignment_window.showMaximized()
        self._activate_review(self.alignment_window)

    def _clear_alignment_window(self):
        self.alignment_window = None

    def _remember_alignment(self, path):
        try:
            self.recent_alignments.add(name=f"{path.parent.name} / {path.stem}",
                                       files={"alignmentJson": str(path.resolve())})
            if self._selected_mode == 2:
                self._refresh_resume()
        except OSError:
            LOGGER.exception("Could not save the alignment bookmark")

    def open_model_suite(self):
        """Show the planned model families without pretending they are wired."""
        self._select_mode(5)
        QMessageBox.information(
            self,
            "Mode 5 — Model Suite",
            "The model-training and inference pipeline is not connected yet.\n\n"
            "Planned interchangeable model families:\n"
            "• 1D CNN\n"
            "• Temporal Convolutional Network (TCN)\n"
            "• LSTM\n"
            "• Spatio-Temporal Graph Convolutional Network (ST-GCN)\n"
            "• Graph Convolutional Network (GCN)\n"
            "• Deep Neural Network (DNN)\n\n"
            "This button is a navigation placeholder for the future Mode 5 Model Suite.",
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
        self._select_mode(1)

    def _clear_annotation_window(self):
        if self.annotation_window is self.sender():
            self.annotation_window = None

    def _saved_workspace(self):
        item = self.resume_combo.currentData()
        if not isinstance(item, dict):
            return
        files = item.get("files", {})
        video = Path(files.get("processedVideo", ""))
        parquet = Path(files.get("featuresParquet", ""))
        if not video.is_file() or not parquet.is_file():
            QMessageBox.warning(self, "Workspace unavailable", "The saved video or feature Parquet path no longer exists.")
            return
        return item, video, parquet

    def resume_current_work(self):
        mode = self._selected_mode
        item = self.resume_combo.currentData()
        if not isinstance(item, dict):
            return
        if mode in (3, 4):
            self.resume_graph_work(mode=mode)
        elif mode == 1:
            self.resume_selected_work()
        elif mode == 2:
            path = Path(item["files"]["alignmentJson"])
            if path.is_file():
                self.open_session_alignment()
                self.alignment_window.resume_alignment(path)
            else:
                QMessageBox.warning(self, "Alignment unavailable", "The saved alignment file no longer exists.")
        elif mode == 0:
            video = item["files"].get("sourceVideo")
            if video and Path(video).is_file():
                self.open_process(setup=item)
            elif not video and all(Path(folder["path"]).is_dir() for folder in item["identifiers"]["folders"]):
                self.open_batch(setup=item)
            else:
                QMessageBox.warning(self, "Processing setup unavailable", "The saved source video or session folder no longer exists.")

    def resume_graph_work(self, *, mode=3):
        self._select_mode(mode)
        workspace = self._saved_workspace()
        if workspace is None:
            return
        item, video, parquet = workspace
        viewer = self.graph_window
        if (viewer is not None and viewer.isVisible() and self._graph_mode == mode
                and viewer.video_path.resolve() == video.resolve()
                and viewer.parquet_path.resolve() == parquet.resolve()):
            self._activate_review(viewer)
            return
        frame = item.get("lastFrame")
        self._show_graph_viewer(
            mode=mode, video_path=video, parquet_path=parquet, frame=frame if isinstance(frame, int) else 0,
        )

    def resume_selected_work(self):
        self._select_mode(1)
        workspace = self._saved_workspace()
        if workspace is None:
            return
        item, video, parquet = workspace
        files = item["files"]
        metadata = files.get("metadataJson")
        try:
            self.annotation_window = open_annotation_studio(
                self, video_path=video, parquet_path=parquet,
                metadata_path=metadata if metadata and Path(metadata).is_file() else None,
                annotation_json_path=files.get("annotationJson") or None,
                frame_jump=self.preferences.values.default_frame_jump,
            )
            if self.annotation_window is not None:
                self.remember_window(self.annotation_window)
                self._activate_review(self.annotation_window)
        except Exception as exc:
            LOGGER.exception("Could not resume workspace")
            QMessageBox.critical(self, "Could Not Resume Mode 1 Annotation", f"{type(exc).__name__}: {exc}")

    def closeEvent(self, event):
        if self._prepare_process is not None:
            QMessageBox.information(self, "Recording preparation", "Wait for the current recording to finish preparing.")
            event.ignore()
            return
        if self.alignment_window is not None and not self.alignment_window.close():
            event.ignore()
            return
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
