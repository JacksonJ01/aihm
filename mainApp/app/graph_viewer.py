"""Read-only desktop workspace for synchronized skeleton video and joint traces."""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
import logging
from pathlib import Path
import re

import cv2
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from PyQt6.QtCore import QEvent, QSignalBlocker, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSizePolicy,
    QSlider, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from aihumo.features import (
    CROSS_MEAN_PREFIX, CROSS_MEAN_SOURCE, LEGACY_ANGLE_PREFIX, MEAN_ANGLE_PREFIX, REVIEW_LANDMARKS,
    TIME_COLUMNS, VIEWER_FEATURE_PREFIX,
)
from aihumo.annotations import AnnotationState
from aihumo.storage import annotation_json_for_features, load_json

from .angle_overlay import SKELETON_COLUMNS, AngleLabel, frame_angle_labels, midpoint_overlay_button, paint_angle_labels, paint_skeleton
from .common import ReviewWindow, close_and_return
from .joint_graph import GRAPH_MODES, MEAN_SOURCE, JointGraphWidget, SAVED_SOURCE, TORSO_SOURCE, WORLD_SOURCE
from .playback import FrameBuffer, FrameNavigationButton, FramePlayback, open_review_video, review_window_is_covered
from .preferences import DEFAULT_FRAME_JUMP, MAX_FRAME_JUMP
from .timeline_layers import QUALITY_COLUMNS


ARROW_FRAME_STEPS = {
    Qt.Key.Key_Left: -1,
    Qt.Key.Key_Down: -1,
    Qt.Key.Key_Right: 1,
    Qt.Key.Key_Up: 1,
}


def review_metadata(parquet_path: Path) -> dict:
    name = parquet_path.stem.removesuffix("_features") + "_metadata.json"
    sidecars = (parquet_path.parent.parent / "metadata" / name, parquet_path.with_name(name))
    return next((load_json(candidate) for candidate in sidecars if candidate.is_file()), {})


@dataclass(frozen=True)
class GraphRecording:
    frames: pd.DataFrame
    overlay_frames: pd.DataFrame
    timestamps: np.ndarray
    measurements: dict
    metadata: dict


class SkeletonPreview(QLabel):
    """Scale the current frame without letting the image set the pane size."""

    def __init__(self, draw_skeleton):
        super().__init__("Skeleton video")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._frame = QPixmap()
        self._labels: tuple[AngleLabel, ...] = ()
        self._draw_skeleton = draw_skeleton
        self._smooth = True

    def show_frame(self, frame: QPixmap, labels: tuple[AngleLabel, ...] = (), *, smooth: bool = True) -> None:
        self._frame = frame
        self._smooth = smooth
        self.show_angle_labels(labels)

    def show_angle_labels(self, labels: tuple[AngleLabel, ...]) -> None:
        self._labels = labels
        self._fit_frame()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_frame()

    def _fit_frame(self) -> None:
        if not self._frame.isNull() and not self.size().isEmpty():
            display = self._frame.scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                (Qt.TransformationMode.SmoothTransformation if self._smooth
                 else Qt.TransformationMode.FastTransformation),
            )
            self._draw_skeleton(display)
            paint_angle_labels(display, self._labels)
            self.setPixmap(display)


class InteractiveGraphViewer(ReviewWindow):
    """Browse feature samples and saved annotations without modifying them."""

    position_checkpoint = pyqtSignal(int)
    frame_changed = pyqtSignal(int)
    annotation_requested = pyqtSignal()
    closed = pyqtSignal()
    viewer_title = "AIHuMo Interactive Graph Viewer (2D) · Mode 3"

    def __init__(self, video_path: str | Path, parquet_path: str | Path, parent=None, *,
                 annotation_preview: bool = False,
                 frame_jump: int = DEFAULT_FRAME_JUMP, initial_frame: int | None = 0,
                 annotation_json_path=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(f"{self.viewer_title} — {Path(video_path).stem}")
        self.current_frame = 0
        self._deferred_linked_frame = None
        self.annotation_preview = annotation_preview
        self._annotation_path_override = annotation_json_path
        self._annotation_revision = None
        self._annotation_graph = None
        owner = parent
        while owner is not None and not hasattr(owner, "preferences"):
            owner = owner.parentWidget()
        self._preference_store = getattr(owner, "preferences", None)
        self._checkpoint_timer = QTimer(self)
        self._checkpoint_timer.setSingleShot(True)
        self._checkpoint_timer.setInterval(750)
        self._checkpoint_timer.timeout.connect(self._checkpoint_position)
        self._set_recording(video_path, parquet_path)
        self._open_capture()
        try:
            self._build_ui(self._frames, frame_jump)
            if initial_frame is not None and not self.goto_frame(initial_frame):
                raise ValueError("Could not decode the first skeleton video frame.")
        except Exception:
            self._close_capture()
            raise
        QApplication.instance().installEventFilter(self)

    def _set_recording(self, video_path, parquet_path):
        parquet_path = Path(parquet_path)
        recording = self._read_recording(parquet_path)
        self.video_path, self.parquet_path = Path(video_path), parquet_path
        self._frames = recording.frames
        self._measurements = recording.measurements
        self._overlay_frames = recording.overlay_frames
        self.timestamps = recording.timestamps
        self.total_frames = len(recording.frames)
        self.metadata = recording.metadata

    def _read_recording(self, parquet_path):
        with pq.ParquetFile(parquet_path) as parquet:
            names = parquet.schema_arrow.names
            metadata = parquet.schema_arrow.metadata or {}
        measurements = json.loads(metadata.get(b"aihumo.review_schema", b"{}")).get("columns", {})
        time_column = next((name for name in TIME_COLUMNS if name in names), None)
        angles = [name for name in names if name.startswith(LEGACY_ANGLE_PREFIX)]
        extra_columns = self._extra_feature_columns(names)
        if "frame_id" not in names or not time_column or not (angles or extra_columns):
            raise ValueError("Select a matching feature Parquet with frame IDs, source timestamps, and graph data.")
        overlay_columns = [name for name in names if name in SKELETON_COLUMNS]
        indices = "|".join(map(str, REVIEW_LANDMARKS))
        points = rf"(?:lm(?:{indices})|(?:shoulder|hip)_midpoint)"
        reading_pattern = rf"review_(?:legacy|world|torso2d|cross_mean)_{points}_(?:[va]?[xyz]|speed)"
        viewer_columns = [name for name in names if name.startswith((VIEWER_FEATURE_PREFIX, "review_omega_", "review_alpha_", f"{CROSS_MEAN_PREFIX}angle_"))
                          or re.fullmatch(reading_pattern, name)
                          or re.fullmatch(r"review_(?:legacy|world|torso2d|cross_mean)_distance_.+", name)]
        wanted = list(dict.fromkeys(["frame_id", time_column, *angles, *overlay_columns, *viewer_columns,
                                    *extra_columns, *(name for name in QUALITY_COLUMNS if name in names)]))
        frames = pd.read_parquet(parquet_path, columns=wanted)
        mean_columns = [name for name in viewer_columns if name.startswith((f"{CROSS_MEAN_PREFIX}angle_", f"{MEAN_ANGLE_PREFIX}angle_"))
                        and not name.endswith("_source_count")]
        ids = pd.to_numeric(frames["frame_id"], errors="coerce").to_numpy(dtype=float)
        timestamps = pd.to_numeric(frames[time_column], errors="coerce").to_numpy(dtype=float)
        if not len(frames) or not np.array_equal(ids, np.arange(len(frames))):
            raise ValueError("Feature frame IDs must run from 0 through the last video frame.")
        if not np.isfinite(timestamps).all() or np.any(np.diff(timestamps) < 0):
            raise ValueError("Feature timestamps must be finite and ordered.")
        # Keep one owner for the selected Parquet columns. The overlay used to
        # duplicate a potentially large subset of the same frame table.
        return GraphRecording(frames, frames,
                              timestamps, measurements, review_metadata(parquet_path))

    def _extra_feature_columns(self, columns):
        return ()

    def _open_capture(self):
        self.cap, self._decode_path, self._baked = open_review_video(
            self.video_path, self.metadata, self.total_frames, timestamps=self.timestamps,
        )
        self._midpoints_baked = self._baked and bool(self.metadata.get("skeleton_midpoints_baked"))
        self._frame_buffer = None
        try:
            if not self.cap.isOpened():
                raise ValueError(f"Could not open skeleton video: {self.video_path}")
            if int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) != self.total_frames:
                raise ValueError("Video frame count differs from the selected Parquet. Choose a matching pair.")
            size = tuple(int(self.cap.get(prop)) for prop in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT))
            self._frame_buffer = FrameBuffer(self._decode_path, self.total_frames, size,
                                             timestamps=getattr(self.cap, "timestamps", None))
        except Exception:
            self.cap.release()
            raise

    def _close_capture(self):
        self._frame_buffer.close()
        self.cap.release()

    def _back(self):
        close_and_return(self)

    def _build_preview(self):
        return SkeletonPreview(self._paint_skeleton)

    def _create_playback(self):
        playback = FramePlayback(
            self, timestamps=self.timestamps, position=lambda: self.current_frame,
            display_frame=self._show_frame, refresh_paused_frame=self._refresh_paused_frame,
            fps=self.cap.get(cv2.CAP_PROP_FPS),
            ready_frame=self._frame_buffer.ready_for_playback,
        )
        playback.starting.connect(self.resume_review)
        playback.paused.connect(lambda: self._frame_buffer.request(self.current_frame))
        playback.paused.connect(lambda: self.frame_changed.emit(self.current_frame))
        return playback

    def _build_ui(self, frames: pd.DataFrame, frame_jump: int) -> None:
        self.splitter = splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        layout = QVBoxLayout(left)
        video_header = QHBoxLayout()
        self.back_button = QPushButton("Back to annotation" if self.annotation_preview else "Back to menu")
        self.back_button.setToolTip("Close the graph viewer and return to the previous window (Esc).")
        self.back_button.clicked.connect(self._back)
        video_header.addWidget(self.back_button)
        video_header.addStretch(1)
        self.overlay_button = QPushButton("Display Overlay")
        self.overlay_button.setCheckable(True)
        self.overlay_button.setToolTip("Label the checked graph angles beside their joints on the video.")
        self.overlay_button.toggled.connect(self._refresh_angle_overlay)
        video_header.addWidget(self.overlay_button)
        self.skeleton_button = QPushButton("Show Skeleton")
        self.skeleton_button.setCheckable(True)
        self.skeleton_button.setChecked(True)
        self._update_skeleton_control()
        self.skeleton_button.toggled.connect(self._refresh_angle_overlay)
        video_header.addWidget(self.skeleton_button)
        self.graph_mode = QComboBox()
        self.graph_mode.addItems(GRAPH_MODES)
        self.graph_mode.setAccessibleName("Graph view")
        self.midpoint_button = midpoint_overlay_button(self._overlay_frames.columns, baked=self._midpoints_baked)
        self.midpoint_button.toggled.connect(self._refresh_angle_overlay)
        video_header.addWidget(self.midpoint_button)
        self._back_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._back_shortcut.activated.connect(self.back_button.click)
        layout.addLayout(video_header)
        self._build_review_controls(layout, frame_jump)
        self.graph = self._new_graph(frames)
        self.graph_mode.currentTextChanged.connect(lambda mode: self.graph.set_graph_mode(mode))
        splitter.addWidget(left)
        splitter.addWidget(self.graph)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([400, 900])
        self.setCentralWidget(splitter)

    def _update_skeleton_control(self):
        self.skeleton_button.setEnabled(not self._baked)
        self.skeleton_button.setToolTip("The matching clean video is unavailable or could not be verified." if self._baked
                                        else "Show the skeleton from saved image landmarks.")

    def _build_review_controls(self, layout, frame_jump):
        self.graph_picker = graph_picker = QHBoxLayout()
        graph_picker.addWidget(QLabel("Graph view"))
        graph_picker.addWidget(self.graph_mode)
        graph_picker.addStretch()
        if not self.annotation_preview and self.parentWidget() is not None:
            self.open_annotations_button = QPushButton("Open annotations")
            self.open_annotations_button.setToolTip("Open this recording in Mode 1 at the current frame.")
            self.open_annotations_button.clicked.connect(self._request_annotations)
            graph_picker.addWidget(self.open_annotations_button)
        layout.addLayout(graph_picker)
        self.preview = self._build_preview()
        layout.addWidget(self.preview, 1)

        self.frame_label = QLabel()
        layout.addWidget(self.frame_label)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, self.total_frames - 1)
        self.slider.valueChanged.connect(self.goto_frame)
        layout.addWidget(self.slider)

        buttons = QHBoxLayout()
        self.playback = self._create_playback()
        self.play_button = self.playback.button
        self.speed_control = self.playback.speed.control()
        previous = self._navigation_button("Previous", -1)
        following = self._navigation_button("Next", 1)
        self.frame_spin = QSpinBox()
        self.frame_spin.setRange(0, self.total_frames - 1)
        self.frame_spin.valueChanged.connect(self.goto_frame)
        for widget in (previous, self.play_button, following, self.speed_control, QLabel("Frame"), self.frame_spin):
            buttons.addWidget(widget)
        layout.addLayout(buttons)

        jumps = QHBoxLayout()
        self.jump_spin = QSpinBox()
        self.jump_spin.setRange(1, MAX_FRAME_JUMP)
        self.jump_spin.setValue(frame_jump)
        self.jump_spin.setToolTip("Frames moved by Up/Down and the −Jump/+Jump buttons.")
        jumps.addWidget(self._navigation_button("−Jump", -1, jump=True))
        jumps.addWidget(self._navigation_button("+Jump", 1, jump=True))
        jumps.addWidget(QLabel("Jump"))
        jumps.addWidget(self.jump_spin)
        jumps.addStretch(1)
        layout.addLayout(jumps)

    def _navigation_button(self, text, direction, *, jump=False):
        return FrameNavigationButton(
            text, playback=self.playback, pause=self._pause_review, direction=direction, jump=jump,
            seek=lambda: self.goto_frame(self.current_frame + direction * (self.jump_spin.value() if jump else 1)),
        )

    def _new_graph(self, frames, **timeline):
        settings = self._preference_store.values.timeline if self._preference_store is not None else None
        graph = JointGraphWidget(frames, link_video=True, annotation_settings=settings, **timeline)
        if self._preference_store is not None:
            graph.annotationOptionsChanged.connect(self._save_graph_options)
        self._refresh_graph_annotations(graph)
        graph.navigationStarted.connect(self.playback.pause)
        graph.frameSelected.connect(self.goto_frame)
        graph.traceSelectionChanged.connect(self._refresh_angle_overlay)
        measurements = QPushButton("Frame measurements")
        measurements.setEnabled(bool(self._measurements))
        measurements.setToolTip("Inspect saved midpoint positions and distances at the current frame.")
        measurements.clicked.connect(self._show_measurements)
        graph.annotation_controls.addWidget(measurements)
        return graph

    def _save_graph_options(self, options):
        store = self._preference_store
        current = store.values
        layers = {key: {**layer, "visible": options["visible"][key]}
                  for key, layer in current.timeline["layers"].items()}
        timeline = {**current.timeline, "style": options["style"], "auto": options["auto"], "layers": layers}
        try:
            store.save(replace(current, timeline=timeline))
        except OSError:
            logging.getLogger(__name__).exception("Could not save timeline preferences")

    def _refresh_graph_annotations(self, graph):
        path = (Path(self._annotation_path_override) if self._annotation_path_override
                else annotation_json_for_features(self.parquet_path))
        try:
            try:
                stat = path.stat()
                version = path, stat.st_mtime_ns, stat.st_size
            except FileNotFoundError:
                version = path, None
            if graph is self._annotation_graph and version == self._annotation_revision:
                return
            rows = AnnotationState.load(path, self.metadata).annotations if len(version) == 3 else []
            graph.set_annotations(rows)
            self._annotation_graph = graph
            self._annotation_revision = version
        except (OSError, ValueError, TypeError, KeyError):
            logging.getLogger(__name__).exception("Could not read graph annotations from %s", path)
            graph.set_annotations([])
            graph.annotation_hint.setText("Could not read saved annotations")

    def _decode(self, index: int) -> QPixmap:
        ok, frame = self._frame_buffer.read(self.cap, index)
        if not ok:
            return QPixmap()
        height, width = frame.shape[:2]
        image = QImage(frame.data, width, height, frame.strides[0], QImage.Format.Format_BGR888)
        return QPixmap.fromImage(image)

    def goto_frame(self, frame: int) -> bool:
        self._deferred_linked_frame = None
        self.playback.pause(refresh=False)
        return self._show_frame(frame)

    def follow_annotation_frame(self, frame, *, playing):
        if frame == self.current_frame:
            self._deferred_linked_frame = None
        elif self.review_suspended or (playing and review_window_is_covered(self)):
            self._deferred_linked_frame = frame
        else:
            self.goto_frame(frame)

    def _flush_linked_frame(self):
        if self._deferred_linked_frame is not None:
            self.goto_frame(self._deferred_linked_frame)

    def _pause_review(self):
        self.playback.pause(refresh=False)
        self.graph.cancel_playback_render()

    def _resume_review(self):
        self._refresh_graph_annotations(self.graph)
        self._flush_linked_frame()

    def _show_frame(self, frame: int) -> bool:
        index = min(max(int(frame), 0), self.total_frames - 1)
        self._frame_buffer.request(index, playback=self.playback.playing, direction=self.playback.direction)
        pixmap = self._decode(index)
        if pixmap.isNull():
            self.frame_label.setText(f"Could not decode video frame {index}.")
            with QSignalBlocker(self.slider), QSignalBlocker(self.frame_spin):
                self.slider.setValue(self.current_frame)
                self.frame_spin.setValue(self.current_frame)
            return False
        self.current_frame = index
        self._checkpoint_timer.start()
        self.preview.show_frame(pixmap, self._angle_labels(), smooth=not self.playback.playing)
        self._update_frame_controls(index)
        return True

    def _update_frame_controls(self, index, time_label=None, *, playing=None):
        with QSignalBlocker(self.slider), QSignalBlocker(self.frame_spin):
            self.slider.setValue(index)
            self.frame_spin.setValue(index)
        time_label = time_label or f"{self.timestamps[index]:.6f} s"
        self.frame_label.setText(f"Frame {index:,} / {self.total_frames - 1:,}   |   {time_label}")
        playing = self.playback.playing if playing is None else playing
        self._update_graph_frame(index, playing=playing)
        self.frame_changed.emit(index)

    def _update_graph_frame(self, index, *, playing=False):
        self.graph.set_current_frame(index, playing=playing)

    def _angle_labels(self) -> tuple[AngleLabel, ...]:
        if not self.overlay_button.isChecked():
            return ()
        return frame_angle_labels(self._overlay_frames.iloc[self.current_frame], self.graph.overlay_traces())

    def _paint_skeleton(self, pixmap: QPixmap) -> None:
        body = self.skeleton_button.isChecked() and not self._baked
        midpoints = self.midpoint_button.isChecked() and not self._midpoints_baked
        if body or midpoints:
            paint_skeleton(pixmap, self._overlay_frames.iloc[self.current_frame], draw_body=body, draw_centerline=midpoints)

    def _refresh_angle_overlay(self) -> None:
        self.preview.show_angle_labels(self._angle_labels())

    def _show_measurements(self) -> None:
        self.playback.pause()
        sources = {TORSO_SOURCE: "torso2d", WORLD_SOURCE: "world", SAVED_SOURCE: "legacy", MEAN_SOURCE: CROSS_MEAN_SOURCE}
        names = {source: label for label, source in sources.items()}
        selected = sources.get(self.graph.angle_source.currentText(), "pixels")
        columns = {
            name: spec for name, spec in self._measurements.items()
            if (self.graph.show_all_sources.isChecked() or spec.get("source") == selected)
            and (spec.get("measurement") == "distance"
                 or (spec.get("measurement") == "position" and spec.get("point", "").endswith("_midpoint")))
        }
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Saved measurements · frame {self.current_frame:,}")
        layout = QVBoxLayout(dialog)
        if not columns:
            layout.addWidget(QLabel("No saved midpoint or distance measurements for this source."))
            dialog.exec()
            return
        try:
            saved = pq.read_table(self.parquet_path, columns=list(columns), filters=[("frame_id", "=", self.current_frame)])
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Saved measurements unavailable", str(error))
            return
        table = QTableWidget(len(columns), 4, dialog)
        table.setHorizontalHeaderLabels(["Source", "Measurement", "Value", "Unit"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, (name, spec) in enumerate(columns.items()):
            value = saved[name][0].as_py() if saved.num_rows else None
            title = spec["point"].replace("_", " ").capitalize()
            if spec["measurement"] == "position":
                title += f" {spec['axis'].upper()}"
            fields = (names.get(spec["source"], "Video pixels"), title,
                      f"{value:.4f}" if value is not None and np.isfinite(value) else "Unavailable", spec["unit"])
            for column, text in enumerate(fields):
                table.setItem(row, column, QTableWidgetItem(text))
        table.resizeColumnsToContents()
        layout.addWidget(table)
        dialog.resize(740, 500)
        dialog.exec()

    def eventFilter(self, watched, event):
        kind = event.type()
        if (kind in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress, QEvent.Type.KeyRelease)
                and isinstance(watched, QWidget) and (watched is self or self.isAncestorOf(watched))
                and watched is not self.speed_control
                and watched.window() is self.window()
                and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            step = ARROW_FRAME_STEPS.get(event.key())
            if step is not None:
                # Claim the shortcut before Qt or Matplotlib moves focus,
                # changes a control value, or navigates the plot history.
                if kind == QEvent.Type.KeyPress:
                    if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                        step *= self.jump_spin.value()
                    self.goto_frame(self.current_frame + step)
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _checkpoint_position(self) -> None:
        self.position_checkpoint.emit(self.current_frame)

    def _request_annotations(self) -> None:
        self._pause_review()
        self.annotation_requested.emit()

    def _refresh_paused_frame(self) -> None:
        self._frame_buffer.request(self.current_frame)
        self.graph.finish_playback()

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self.playback.pause(refresh=False)
        self.graph.dispose()
        self._checkpoint_timer.stop()
        self._checkpoint_position()
        self._close_capture()
        self._frames = pd.DataFrame()
        self._overlay_frames = pd.DataFrame()
        self.timestamps = np.array([])
        self.closed.emit()
        super().closeEvent(event)


def open_graph_viewer(parent=None, *, video_path=None, parquet_path=None, frame: int = 0,
                      annotation_preview: bool = False,
                      frame_jump: int = DEFAULT_FRAME_JUMP, viewer_class=InteractiveGraphViewer,
                      annotation_json_path=None):
    if video_path is None:
        video_path, _ = QFileDialog.getOpenFileName(
            parent, "Select processed skeleton video", "", "Video Files (*.mp4 *.mov *.avi *.mkv);;All Files (*)",
        )
        if not video_path:
            return None
    video_path = Path(video_path)
    if parquet_path is None:
        recording = video_path.stem.removesuffix("_skeleton")
        candidate = video_path.parent.parent / "parquet" / f"{recording}_features.parquet"
        parquet_path, _ = QFileDialog.getOpenFileName(
            parent, "Select matching feature Parquet", str(candidate if candidate.is_file() else video_path.parent),
            "Parquet (*.parquet);;All Files (*)",
        )
        if not parquet_path:
            return None
    viewer = viewer_class(
        video_path, parquet_path, parent,
        annotation_preview=annotation_preview, frame_jump=frame_jump, annotation_json_path=annotation_json_path,
    )
    if frame > 0:
        if not viewer.goto_frame(frame) and annotation_preview:
            viewer.close()
            raise ValueError(f"Could not open the graph viewer at annotation frame {frame}.")
    viewer.showMaximized()
    return viewer
