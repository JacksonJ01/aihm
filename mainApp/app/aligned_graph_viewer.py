"""Session alignment adapter for the Interactive Graph Viewer."""
from __future__ import annotations

from collections import OrderedDict
from time import monotonic

import cv2
import numpy as np
from PyQt6.QtCore import QObject, QRect, QSignalBlocker, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import QButtonGroup, QGridLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from aihumo.alignment import SOURCE_LABELS, frame_at

from .angle_overlay import midpoint_overlay_button, paint_angle_labels
from .common import close_and_return
from .graph_viewer import InteractiveGraphViewer, review_metadata
from .playback import FrameBuffer, PlaybackSpeed, fit_video_pixmap, open_review_video, review_window_is_covered


class CameraPreviewButton(QPushButton):
    """Keep the full tile clickable and paint the highlight around its image."""

    image_margin = 5

    def __init__(self):
        super().__init__("Waiting for frame")
        self._image = QPixmap()

    def set_image(self, image, message=""):
        self._image = image
        self.setText(message)
        self.update()

    def image_rect(self):
        rect = QRect(0, 0, self._image.width(), self._image.height())
        rect.moveCenter(self.rect().center())
        return rect

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._image.isNull():
            painter.setPen(self.palette().color(QPalette.ColorRole.ButtonText))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
            return

        image = self.image_rect()
        painter.drawPixmap(image.topLeft(), self._image)
        if self.isChecked() or self.hasFocus():
            style = Qt.PenStyle.SolidLine if self.isChecked() else Qt.PenStyle.DashLine
            painter.setPen(QPen(self.palette().color(QPalette.ColorRole.Highlight), 2, style))
            painter.drawRect(image.adjusted(-3, -3, 3, 3))


class CameraPreview(QWidget):
    def __init__(self, recording, paint, *, memory_limit=FrameBuffer.DEFAULT_MEMORY_LIMIT,
                 selected_memory_limit=None, source=None):
        super().__init__()
        self.recording = recording
        self.paint = paint
        self.frame_id = self.frame = None
        self._owns_source = source is None
        self._preview_cache = OrderedDict() if source is None else source._preview_cache
        if self._owns_source:
            metadata = review_metadata(recording.features)
            self.capture, path, self.baked = open_review_video(
                recording.video, metadata, len(recording.times), timestamps=recording.times,
            )
            self.midpoints_baked = self.baked and bool(metadata.get("skeleton_midpoints_baked"))
            if not self.capture.isOpened() or int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT)) != len(recording.times):
                self.capture.release()
                raise ValueError(f"Could not open the matching video for {recording.label}.")
            size = tuple(int(self.capture.get(prop)) for prop in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT))
            self.buffer = FrameBuffer(path, len(recording.times), size, memory_limit=memory_limit,
                                      selected_memory_limit=selected_memory_limit,
                                      timestamps=getattr(self.capture, "timestamps", None))
        else:
            self.capture, self.buffer = source.capture, source.buffer
            self.baked, self.midpoints_baked = source.baked, source.midpoints_baked
        self.button = CameraPreviewButton()
        self.button.setCheckable(True)
        self.button.setAccessibleName(f"Select camera {recording.label}")
        self.button.setToolTip(f"Show graph and frame details for {recording.label}")
        self.button.setMinimumSize(85, 64)
        self.button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        label = QLabel(recording.label)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        label.setToolTip(recording.label)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        layout.addWidget(self.button, 1)

    def release(self):
        self.clear_frame("")
        if self._owns_source:
            self._preview_cache.clear()
            self.buffer.close()
            self.capture.release()

    def clear_frame(self, message):
        self.frame_id = self.frame = None
        self.button.set_image(QPixmap(), message)

    def draw(self):
        if self.frame is not None and self.isVisible() and not self.window().isMinimized():
            margin = 2 * self.button.image_margin
            width, height = max(1, self.button.width() - margin), max(1, self.button.height() - margin)
            key = self.frame_id, width, height
            pixmap = self._preview_cache.get(key)
            if pixmap is None:
                pixmap = fit_video_pixmap(self.frame, width, height)
                self._preview_cache[key] = pixmap
                if len(self._preview_cache) > 2:
                    self._preview_cache.popitem(last=False)
            else:
                self._preview_cache.move_to_end(key)
            # Share the scaled image while keeping each window's overlays independent.
            pixmap = QPixmap(pixmap)
            self.paint(self, pixmap)
            self.button.set_image(pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.draw()

    def showEvent(self, event):
        super().showEvent(event)
        self.draw()


class CameraGrid(QWidget):
    def __init__(self, session, panes, select):
        super().__init__()
        self.tiles = list(panes)
        self._rows = 1 if len(panes) == 2 else 2
        self.buttons = QButtonGroup(self)
        self.buttons.idClicked.connect(select)
        for index, pane in enumerate(panes):
            self.buttons.addButton(pane.button, index)
        panes[0].button.setChecked(True)
        self.grid_layout = QGridLayout(self)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        for row in range(self._rows):
            self.grid_layout.setRowStretch(row, 1)
        for column in range(2):
            self.grid_layout.setColumnStretch(column, 1)
        self.set_view(session.camera_view)
        self.buttons.idToggled.connect(self._selection_changed)
        session.camera_view_changed.connect(self.set_view)

    def _selection_changed(self, _index, checked):
        if checked and self.maximized:
            self.set_view(1)

    def set_view(self, index):
        self.maximized = index == 1
        selected = self.buttons.checkedId()
        for tile in self.tiles:
            self.grid_layout.removeWidget(tile)
        for index, tile in enumerate(self.tiles):
            visible = not self.maximized or index == selected
            if visible:
                if self.maximized:
                    self.grid_layout.addWidget(tile, 0, 0, self._rows, 2)
                else:
                    self.grid_layout.addWidget(tile, *divmod(index, 2))
            tile.setVisible(visible)


def update_camera_frames(session, panes, time, *, playback, frames_from=None, exact_frame=None):
    updates = []
    waiting = False
    for camera, (pane, mapping, bounds) in enumerate(zip(panes, session.maps, session.ranges)):
        index = (exact_frame[1] if exact_frame is not None and exact_frame[0] == camera
                 else frame_at(pane.recording, mapping, time, *bounds))
        if index == pane.frame_id:
            continue
        direction = -1 if pane.frame_id is not None and index < pane.frame_id else 1
        pane.buffer.request(index, playback=playback, direction=direction)
        sibling = frames_from[camera] if frames_from is not None else None
        if sibling is not None and sibling.frame_id == index:
            frame = sibling.frame
        elif playback:
            frame = pane.buffer.get(index)
        else:
            _, frame = pane.buffer.read(pane.capture, index)
        if frame is None:
            if playback:
                waiting = True
            else:
                pane.clear_frame(f"Could not decode frame {index:,}")
            continue
        updates.append((pane, index, frame))
    if waiting:
        return None
    for pane, index, frame in updates:
        pane.frame_id, pane.frame = index, frame
    return [pane for pane, _, _ in updates]


class AlignmentPlayback(QObject):
    """Drive every camera from one elapsed-time clock."""

    playing_changed = pyqtSignal()

    def __init__(self, viewer, speed=None):
        super().__init__(viewer)
        self.viewer = viewer
        self.speed = PlaybackSpeed(self) if speed is None else speed
        self.speed.changed.connect(self._change_speed)
        self.holding = False
        self.button = QPushButton("Play")
        self.button.clicked.connect(self.toggle)
        self.timer = QTimer(self, timerType=Qt.TimerType.PreciseTimer)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.advance)
        self._playing = False
        self._pending_time = None
        self._pending_since = None

    @property
    def playing(self):
        return self._playing

    def toggle(self):
        if self.playing:
            self.pause()
        else:
            self.start()

    def start(self, *, direction=1, hold=False, speed=None):
        if self.playing:
            self.pause(refresh=False)
        session = self.viewer.session
        if session.review_window is None:
            return
        session.pause_other_review(self)
        start, end = session.review_window
        boundary = end if direction > 0 else start
        if session.current_time == boundary and (hold or direction < 0 or not self.viewer.render(start)):
            return
        self._direction, self.holding, self._fixed_speed = direction, hold, speed
        self._rate = self.speed.value if speed is None else speed
        self._rebase_clock()
        self.button.setText("Pause")
        self._playing = True
        self._schedule_next_tick()
        self.playing_changed.emit()

    def _rebase_clock(self):
        self._start_time = self.viewer.session.current_time
        self._started_at = monotonic()
        self._pending_time = None
        self._pending_since = None

    def _change_speed(self):
        if self.playing and self._fixed_speed is None:
            self._rate = self.speed.value
            self._rebase_clock()
            self._schedule_next_tick()

    def _schedule_next_tick(self, *, retry=False):
        if not self.playing:
            return
        if retry:
            self.timer.start(8)
            return
        session = self.viewer.session
        delays = []
        if all(hasattr(session, name) for name in ("recordings", "maps", "ranges")):
            current = float(session.current_time)
            for recording, mapping, bounds in zip(session.recordings, session.maps, session.ranges):
                source = (current - mapping.offset) / mapping.rate
                first, last = bounds
                if self._direction > 0:
                    index = max(first, int(recording.times.searchsorted(source, side="right")))
                    if index <= last:
                        delays.append(mapping.session_time(recording.times[index]) - current)
                else:
                    index = min(last, int(recording.times.searchsorted(source, side="left")) - 1)
                    if index >= first:
                        delays.append(current - mapping.session_time(recording.times[index]))
        delay = min((value for value in delays if np.isfinite(value) and value > 0), default=1 / 60)
        self.timer.start(max(1, round(delay / max(self._rate, 1e-6) * 1000)))

    def advance(self):
        if not self.playing:
            return
        session = self.viewer.session
        start, end = session.review_window
        now = monotonic()
        # Let all decoders finish one common timestamp before requesting
        # another seek. Advancing a missed target each tick can starve a
        # slow camera when a processing job is competing for CPU.
        elapsed = (now - self._started_at) * self._direction * self._rate
        target = min(end, max(start, self._start_time + elapsed)) if self._pending_time is None else self._pending_time
        if self.viewer.render(target, playback=True):
            self._pending_time = None
            self._pending_since = None
            if target == (end if self._direction > 0 else start):
                self.pause()
            else:
                self._schedule_next_tick()
        else:
            if self._pending_time is None:
                self._pending_time, self._pending_since = target, now
            elif now - self._pending_since > 3:
                self.pause()
                session.statusBar().showMessage("Playback paused while waiting for camera frames. Scrub or press Play to retry.", 5000)
            else:
                self._schedule_next_tick(retry=True)

    def pause(self, *, refresh=True):
        if self.playing:
            self._playing = False
            self.timer.stop()
            self.holding = False
            self._pending_time = None
            self._pending_since = None
            self.button.setText("Play")
            self.playing_changed.emit()
            if refresh:
                self.viewer.session.refresh_paused_review(self.viewer)


class AlignedGraphViewer(InteractiveGraphViewer):
    viewer_title = "AIHuMo Alignment Graph Viewer · Mode 2"
    _recording_cache_limit = 640 * 1024**2

    def __init__(self, session, *, selected_camera=0, **options):
        self.session = session
        self.selected_camera = selected_camera
        self.panes = []
        self._camera_recordings = OrderedDict()
        self._standby_graph = None
        self._review_paint_pending = False
        self.alignment_changed = False
        recording = session.recordings[selected_camera]
        super().__init__(recording.video, recording.features, session, annotation_preview=True,
                         initial_frame=None, **options)
        self._active_graph_key = self._graph_key()
        self.update_window(rebuild=False)

    def _read_recording(self, parquet_path):
        stat = parquet_path.stat()
        version = stat.st_mtime_ns, stat.st_size
        saved = self._camera_recordings.get(parquet_path)
        if saved is None or saved[0] != version:
            recording = super()._read_recording(parquet_path)
            size = int(recording.frames.memory_usage(deep=True).sum())
            self._camera_recordings[parquet_path] = version, recording, size
        else:
            recording = saved[1]
        self._recording_version = version
        self._camera_recordings.move_to_end(parquet_path)
        while len(self._camera_recordings) > 4 or (
                len(self._camera_recordings) > 1
                and sum(entry[2] for entry in self._camera_recordings.values()) > self._recording_cache_limit):
            self._camera_recordings.popitem(last=False)
        return recording

    def _graph_key(self):
        return (self.parquet_path, self._recording_version, self.session.review_window,
                self.session.maps[self.selected_camera])

    def _open_capture(self):
        try:
            for pane in self.session.panes:
                self.panes.append(CameraPreview(pane.recording, self._paint_preview, source=pane))
        except Exception:
            self._close_capture()
            raise
        self._use_capture(self.selected_camera)

    def _use_capture(self, index):
        pane = self.panes[index]
        self.cap, self._frame_buffer = pane.capture, pane.buffer
        self._baked, self._midpoints_baked = pane.baked, pane.midpoints_baked

    def _close_capture(self):
        if self._standby_graph is not None:
            self._standby_graph[1].dispose()
            self._standby_graph[1].deleteLater()
            self._standby_graph = None
        self._camera_recordings.clear()
        for pane in self.panes:
            pane.release()

    def _back(self):
        close_and_return(self)

    def _build_preview(self):
        self.camera_view = self.session.camera_view_selector()
        self.graph_picker.insertWidget(2, self.camera_view)
        grid = CameraGrid(self.session, self.panes, self.select_camera)
        self.preview_buttons = grid.buttons
        self.panes[self.selected_camera].button.setChecked(True)
        return grid

    def _create_playback(self):
        return AlignmentPlayback(self, self.session.playback_speed)

    def _new_graph(self, frames):
        if self.session.review_window is None:
            graph = super()._new_graph(frames)
        else:
            index = self.selected_camera
            first, last = self.session.ranges[index]
            times = self.session.maps[index].session_time(self.timestamps[first:last + 1])
            graph = super()._new_graph(frames.iloc[first:last + 1], timeline=times, time_bounds=self.session.review_window)
        self.session.bind_zoom_to_seek(graph.zoom_to_seek)
        compare = QPushButton("Compare all cameras")
        compare.clicked.connect(lambda: self.session.open_comparison(
            source=next((key for key, label in SOURCE_LABELS.items() if label == graph.angle_source.currentText()), None),
            viewer=self,
        ))
        graph.layout().insertWidget(4, compare, alignment=Qt.AlignmentFlag.AlignLeft)
        graph.traceSelectionChanged.connect(self.session._mirror_graph)
        return graph

    def _replace_graph(self):
        previous = self.graph
        previous.cancel_playback_render()
        key = self._graph_key()
        if self._standby_graph is not None and self._standby_graph[0] == key:
            self.graph = self._standby_graph[1]
        else:
            if self._standby_graph is not None:
                self._standby_graph[1].dispose()
                self._standby_graph[1].deleteLater()
            self.graph = self._new_graph(self._frames)
        self.graph.copy_view_from(previous)
        sizes = self.splitter.sizes()
        self.splitter.replaceWidget(1, self.graph)
        self.splitter.setSizes(sizes)
        previous.hide()
        previous_recording = self._camera_recordings.get(self._active_graph_key[0])
        if previous_recording is not None and previous_recording[0] == self._active_graph_key[1]:
            previous.setParent(self)
            self._standby_graph = self._active_graph_key, previous
        else:
            previous.dispose()
            previous.deleteLater()
            self._standby_graph = None
        self._active_graph_key = key
        self.graph.show()

    def select_camera(self, index, *, frames_from=None, playback=False, exact_frame=None):
        if index == self.selected_camera:
            return
        previous = self.selected_camera
        recording = self.panes[index].recording
        try:
            self._set_recording(recording.video, recording.features)
        except (OSError, ValueError) as error:
            self.panes[previous].button.setChecked(True)
            self.session._error(error)
            return
        self.selected_camera = index
        self.panes[index].button.setChecked(True)
        self._use_capture(index)
        self._update_skeleton_control()
        midpoint = midpoint_overlay_button(self._overlay_frames.columns, baked=self._midpoints_baked)
        self.midpoint_button.setEnabled(midpoint.isEnabled())
        self.midpoint_button.setToolTip(midpoint.toolTip())
        midpoint.deleteLater()
        self.update_window(frames_from=frames_from, playback=playback, exact_frame=exact_frame)
        self.panes[previous].draw()

    def update_window(self, *, rebuild=True, frames_from=None, playback=False, exact_frame=None):
        valid = self.session.review_window is not None
        if rebuild:
            self._replace_graph()
        first, last = self.session.ranges[self.selected_camera] if valid else (0, 0)
        for control in (self.slider, self.frame_spin):
            with QSignalBlocker(control):
                control.setRange(first, last)
            control.setEnabled(valid)
        for control in (self.play_button, self.graph):
            control.setEnabled(valid)
        self.render(self.session.current_time, frames_from=frames_from, playback=playback, exact_frame=exact_frame)

    def _show_frame(self, frame):
        if self.session.review_window is None:
            return False
        first, last = self.session.ranges[self.selected_camera]
        index = min(last, max(first, int(frame)))
        return self.render(self.session.maps[self.selected_camera].session_time(self.timestamps[index]),
                           exact_frame=(self.selected_camera, index))

    def _paint_preview(self, pane, pixmap):
        if pane is self.panes[self.selected_camera] and pane.frame_id == self.current_frame:
            self._paint_skeleton(pixmap)
            paint_angle_labels(pixmap, self._angle_labels())

    def _refresh_angle_overlay(self):
        self.panes[self.selected_camera].draw()

    def flush_review_paint(self, *, playing):
        if not self._review_paint_pending:
            return
        self._review_paint_pending = False
        for pane in self.panes:
            pane.draw()
        self._update_frame_controls(self.current_frame, self._session_frame_label(), playing=playing)

    def _session_frame_label(self):
        return f"Session {self.session.current_time:.3f} s  |  Source {self.timestamps[self.current_frame]:.6f} s"

    def _resume_review(self):
        self.session.resume_review_sync(self)
        self.flush_review_paint(playing=True)

    def render(self, time, *, playback=False, frames_from=None, exact_frame=None):
        if self.session.review_window is None:
            self._review_paint_pending = False
            for pane in self.panes:
                pane.clear_frame("No shared frame")
            self.frame_label.setText("No shared frame")
            return False
        start, end = self.session.review_window
        time = min(end, max(start, time))
        updates = update_camera_frames(self.session, self.panes, time, playback=playback,
                                       frames_from=frames_from, exact_frame=exact_frame)
        if updates is None:
            return False
        self.session.current_time = time
        selected = self.panes[self.selected_camera]
        if selected.frame_id is None:
            self.frame_label.setText("Could not decode the selected camera frame.")
            return False
        selected_changed = selected in updates or self.current_frame != selected.frame_id
        self.current_frame = selected.frame_id
        if playback and frames_from is not None and review_window_is_covered(self):
            self._review_paint_pending = True
        elif self._review_paint_pending:
            self.flush_review_paint(playing=playback)
        else:
            for pane in updates:
                pane.draw()
            if not playback and selected not in updates:
                selected.draw()
            if not playback or selected_changed:
                self._update_frame_controls(self.current_frame, self._session_frame_label(), playing=playback)
        if frames_from is None and (not playback or updates or selected_changed):
            self.session.review_frame_changed(self, playback=playback, exact_frame=exact_frame)
        return True
