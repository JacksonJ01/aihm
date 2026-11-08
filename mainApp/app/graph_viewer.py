"""Read-only desktop workspace for synchronized skeleton video and joint traces."""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import re

import cv2
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from PyQt6.QtCore import QEvent, QSignalBlocker, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QPushButton, QSizePolicy,
    QSlider, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from aihumo.config import load_config
from aihumo.features import FeatureEngine, LEGACY_ANGLE_PREFIX

from .angle_overlay import AngleLabel, frame_angle_labels, paint_angle_labels
from .common import close_and_return
from .joint_graph import JointGraphWidget, TIME_COLUMNS
from .playback import FramePlayback
from .preferences import DEFAULT_FRAME_JUMP, MAX_FRAME_JUMP


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARROW_FRAME_STEPS = {
    Qt.Key.Key_Left: -1,
    Qt.Key.Key_Down: -1,
    Qt.Key.Key_Right: 1,
    Qt.Key.Key_Up: 1,
}


class SkeletonPreview(QLabel):
    """Scale the current frame without letting the image set the pane size."""

    def __init__(self):
        super().__init__("Skeleton video")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._frame = QPixmap()
        self._labels: tuple[AngleLabel, ...] = ()

    def show_frame(self, frame: QPixmap, labels: tuple[AngleLabel, ...] = ()) -> None:
        self._frame = frame
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
                Qt.TransformationMode.SmoothTransformation,
            )
            paint_angle_labels(display, self._labels)
            self.setPixmap(display)


class InteractiveGraphViewer(QMainWindow):
    """Browse feature samples without loading or saving any annotation state."""

    position_checkpoint = pyqtSignal(int)
    closed = pyqtSignal()

    def __init__(self, video_path: str | Path, parquet_path: str | Path, parent=None, *,
                 frame_highlight: str = "#20c55a", annotation_preview: bool = False,
                 frame_jump: int = DEFAULT_FRAME_JUMP):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.video_path = Path(video_path)
        self.parquet_path = Path(parquet_path)
        self.setWindowTitle(f"AIHuMo Interactive Graph Viewer — {self.video_path.stem}")
        with pq.ParquetFile(self.parquet_path) as parquet:
            names = parquet.schema_arrow.names
        time_column = next((name for name in TIME_COLUMNS if name in names), None)
        angles = [name for name in names if name.startswith(LEGACY_ANGLE_PREFIX)]
        if "frame_id" not in names or not time_column or not angles:
            raise ValueError("Select a feature Parquet with frame IDs, source timestamps and joint angles.")
        positions = [name for name in names if re.fullmatch(r"(?:lm|world)\d+_[xyz]", name)]
        frames = pd.read_parquet(self.parquet_path, columns=["frame_id", time_column, *angles, *positions])
        ids = pd.to_numeric(frames["frame_id"], errors="coerce").to_numpy(dtype=float)
        self.timestamps = pd.to_numeric(frames[time_column], errors="coerce").to_numpy(dtype=float)
        if not len(frames) or not np.array_equal(ids, np.arange(len(frames))):
            raise ValueError("Feature frame IDs must run from 0 through the last video frame.")
        if not np.isfinite(self.timestamps).all() or np.any(np.diff(self.timestamps) < 0):
            raise ValueError("Feature timestamps must be finite and ordered.")
        self.total_frames = len(frames)
        self.current_frame = 0
        self.frame_highlight = frame_highlight
        self.annotation_preview = annotation_preview
        self._thumb_cache: OrderedDict[int, QPixmap] = OrderedDict()
        self._checkpoint_timer = QTimer(self)
        self._checkpoint_timer.setSingleShot(True)
        self._checkpoint_timer.setInterval(750)
        self._checkpoint_timer.timeout.connect(self._checkpoint_position)

        self.cap = cv2.VideoCapture(str(self.video_path))
        try:
            if not self.cap.isOpened():
                raise ValueError(f"Could not open skeleton video: {self.video_path}")
            if int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) != self.total_frames:
                raise ValueError("Video frame count differs from the selected Parquet. Choose a matching pair.")
            self._build_ui(frames, frame_jump)
            if not self.goto_frame(0):
                raise ValueError("Could not decode the first skeleton video frame.")
        except Exception:
            self.cap.release()
            raise
        QApplication.instance().installEventFilter(self)

    def _build_ui(self, frames: pd.DataFrame, frame_jump: int) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        layout = QVBoxLayout(left)
        video_header = QHBoxLayout()
        self.back_button = QPushButton("Back to annotation" if self.annotation_preview else "Back to menu")
        self.back_button.setToolTip("Close the graph viewer and return to the previous window (Esc).")
        self.back_button.clicked.connect(lambda: close_and_return(self))
        video_header.addWidget(self.back_button)
        video_header.addWidget(QLabel("Skeleton video"), 1)
        self.overlay_button = QPushButton("Display Overlay")
        self.overlay_button.setCheckable(True)
        self.overlay_button.setToolTip("Label the checked graph angles beside their joints on the video.")
        self.overlay_button.toggled.connect(self._refresh_angle_overlay)
        video_header.addWidget(self.overlay_button)
        self._back_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._back_shortcut.activated.connect(self.back_button.click)
        layout.addLayout(video_header)
        self.preview = SkeletonPreview()
        layout.addWidget(self.preview, 1)

        thumbnails = QHBoxLayout()
        self.thumbnails = []
        for _ in range(5):
            thumb = QLabel()
            thumb.setFixedHeight(68)
            thumb.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumbnails.addWidget(thumb, 1)
            self.thumbnails.append(thumb)
        layout.addLayout(thumbnails)

        self.frame_label = QLabel()
        layout.addWidget(self.frame_label)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, self.total_frames - 1)
        self.slider.valueChanged.connect(self.goto_frame)
        layout.addWidget(self.slider)

        buttons = QHBoxLayout()
        previous = QPushButton("Previous")
        previous.clicked.connect(lambda: self.goto_frame(self.current_frame - 1))
        self.playback = FramePlayback(
            self, timestamps=self.timestamps, position=lambda: self.current_frame,
            display_frame=self._show_frame, refresh_thumbnails=self._refresh_thumbnails,
            fps=self.cap.get(cv2.CAP_PROP_FPS),
        )
        self.play_button = self.playback.button
        following = QPushButton("Next")
        following.clicked.connect(lambda: self.goto_frame(self.current_frame + 1))
        self.frame_spin = QSpinBox()
        self.frame_spin.setRange(0, self.total_frames - 1)
        self.frame_spin.valueChanged.connect(self.goto_frame)
        for widget in (previous, self.play_button, following, QLabel("Frame"), self.frame_spin):
            buttons.addWidget(widget)
        layout.addLayout(buttons)

        jumps = QHBoxLayout()
        self.jump_spin = QSpinBox()
        self.jump_spin.setRange(1, MAX_FRAME_JUMP)
        self.jump_spin.setValue(frame_jump)
        self.jump_spin.setToolTip("Frames moved by Up/Down and the −Jump/+Jump buttons.")
        jumps.addWidget(QPushButton("−Jump", clicked=lambda: self.goto_frame(self.current_frame - self.jump_spin.value())))
        jumps.addWidget(QPushButton("+Jump", clicked=lambda: self.goto_frame(self.current_frame + self.jump_spin.value())))
        jumps.addWidget(QLabel("Jump"))
        jumps.addWidget(self.jump_spin)
        jumps.addStretch(1)
        layout.addLayout(jumps)

        frame_size = (self.cap.get(cv2.CAP_PROP_FRAME_WIDTH), self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        engine = FeatureEngine(load_config(PROJECT_ROOT / "configs" / "config.json"))
        self.graph = JointGraphWidget(engine.with_missing_spatial_angles(frames, frame_size), link_video=True)
        self.graph.navigationStarted.connect(self.playback.pause)
        self.graph.frameSelected.connect(self.goto_frame)
        self.graph.traceSelectionChanged.connect(self._refresh_angle_overlay)
        splitter.addWidget(left)
        splitter.addWidget(self.graph)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([500, 800])
        self.setCentralWidget(splitter)

    def _decode(self, index: int) -> QPixmap:
        if int(self.cap.get(cv2.CAP_PROP_POS_FRAMES)) != index:
            if not self.cap.set(cv2.CAP_PROP_POS_FRAMES, index):
                return QPixmap()
        ok, frame = self.cap.read()
        if not ok:
            return QPixmap()
        height, width = frame.shape[:2]
        image = QImage(frame.data, width, height, frame.strides[0], QImage.Format.Format_BGR888)
        return QPixmap.fromImage(image)

    def goto_frame(self, frame: int) -> bool:
        self.playback.pause(refresh=False)
        return self._show_frame(frame)

    def _show_frame(self, frame: int) -> bool:
        index = min(max(int(frame), 0), self.total_frames - 1)
        pixmap = self._decode(index)
        if pixmap.isNull():
            self.frame_label.setText(f"Could not decode video frame {index}.")
            with QSignalBlocker(self.slider), QSignalBlocker(self.frame_spin):
                self.slider.setValue(self.current_frame)
                self.frame_spin.setValue(self.current_frame)
            return False
        self.current_frame = index
        self._checkpoint_timer.start()
        self.preview.show_frame(pixmap, self._angle_labels())
        with QSignalBlocker(self.slider), QSignalBlocker(self.frame_spin):
            self.slider.setValue(index)
            self.frame_spin.setValue(index)
        self.frame_label.setText(f"Frame {index:,} / {self.total_frames - 1:,}   |   {self.timestamps[index]:.6f} s")
        self.graph.set_current_frame(index)
        self._remember_thumbnail(index, pixmap)
        self._refresh_thumbnails()
        return True

    def _angle_labels(self) -> tuple[AngleLabel, ...]:
        if not self.overlay_button.isChecked():
            return ()
        return frame_angle_labels(self.graph.dataframe.iloc[self.current_frame], self.graph.overlay_traces())

    def _refresh_angle_overlay(self) -> None:
        self.preview.show_angle_labels(self._angle_labels())

    def eventFilter(self, watched, event):
        kind = event.type()
        if (kind in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress, QEvent.Type.KeyRelease)
                and isinstance(watched, QWidget) and watched.window() is self
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

    def _remember_thumbnail(self, index: int, frame: QPixmap) -> QPixmap:
        thumbnail = frame.scaled(
            96, 62, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        )
        self._thumb_cache[index] = thumbnail
        self._thumb_cache.move_to_end(index)
        if len(self._thumb_cache) > 32:
            self._thumb_cache.popitem(last=False)
        return thumbnail

    def _refresh_thumbnails(self) -> None:
        for offset, label in zip(range(-2, 3), self.thumbnails):
            index = self.current_frame + offset
            thumbnail = self._thumb_cache.get(index)
            if thumbnail is None and not self.playback.playing and 0 <= index < self.total_frames:
                frame = self._decode(index)
                if not frame.isNull():
                    thumbnail = self._remember_thumbnail(index, frame)
            label.setPixmap(thumbnail if thumbnail is not None else QPixmap())
            label.setToolTip(f"Frame {index}" if thumbnail is not None else "")
            label.setStyleSheet(f"border: 2px solid {self.frame_highlight};" if offset == 0 else "border: 1px solid palette(mid);")

    def _checkpoint_position(self) -> None:
        self.position_checkpoint.emit(self.current_frame)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self.playback.pause(refresh=False)
        self._checkpoint_timer.stop()
        self._checkpoint_position()
        self.cap.release()
        self.closed.emit()
        super().closeEvent(event)


def open_graph_viewer(parent=None, *, video_path=None, parquet_path=None, frame: int = 0,
                      frame_highlight: str = "#20c55a", annotation_preview: bool = False,
                      frame_jump: int = DEFAULT_FRAME_JUMP):
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
    viewer = InteractiveGraphViewer(
        video_path, parquet_path, parent, frame_highlight=frame_highlight,
        annotation_preview=annotation_preview, frame_jump=frame_jump,
    )
    if frame > 0:
        if not viewer.goto_frame(frame) and annotation_preview:
            viewer.close()
            raise ValueError(f"Could not open the graph viewer at annotation frame {frame}.")
    viewer.showMaximized()
    return viewer
