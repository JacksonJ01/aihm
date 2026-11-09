"""Review and trim multiple processed camera recordings on one timeline."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import QSignalBlocker, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QListWidget,
    QMessageBox, QPushButton, QSlider, QStackedWidget, QVBoxLayout, QWidget,
)

from aihumo.alignment import (
    MAX_CAMERAS, SOURCE_LABELS, common_window, export_ranges, export_session, frame_at,
    load_session, process_session, save_session, trim_frames, validate_camera_count,
)
from aihumo.annotations import validate_annotations
from aihumo.storage import save_json_atomic

from .aligned_graph_viewer import AlignedGraphViewer, AlignmentPlayback, CameraGrid, CameraPreview, update_camera_frames
from .common import ReviewWindow, close_and_return
from .graph_navigation import FrameZoomToolbar, centered_time_limits, wheel_zoom_factor, zoom_to_seek_button
from .mode1_annotation import AnnotationStudio
from .playback import FrameBuffer, PlaybackSpeed, review_window_is_covered
from .preferences import DEFAULT_FRAME_JUMP


class SessionAlignmentWindow(ReviewWindow):
    closed = pyqtSignal()
    saved_alignment_opened = pyqtSignal(object)
    camera_view_changed = pyqtSignal(int)
    zoom_to_seek_changed = pyqtSignal(bool)

    def __init__(self, parent, processed_root: Path, *, frame_jump=DEFAULT_FRAME_JUMP):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("AIHuMo · Mode 2 Session Alignment")
        self.setMinimumSize(850, 600)
        self.processed_root = processed_root
        self.frame_jump = frame_jump
        self.playback_speed = PlaybackSpeed(self)
        self.recordings, self.maps, self.ranges = [], [], []
        self.panes = []
        self.grid = None
        self.selected_camera = None
        self.camera_view = 0
        self._zoom_to_seek = False
        self.review_window = self.bounds = None
        self.current_time = 0.0
        self._review_paint_pending = False
        self._review_sync_target = None
        self.studios = {}
        self.aligned_graph = None
        self.comparison = None
        self._dirty = False
        self._saved_path = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="AIHuMo alignment")
        self.job = None
        self.job_timer = QTimer(self, interval=75)
        self.job_timer.timeout.connect(self._finish_job)

        central = QWidget()
        layout = QVBoxLayout(central)
        self.setCentralWidget(central)
        toolbar = QHBoxLayout()
        self._button(toolbar, "Back to menu", lambda: close_and_return(self))
        self.process_button = self._button(toolbar, "Process recordings…", self._choose_recordings)
        self.load_button = self._button(toolbar, "Load alignment…", self._load)
        self.save_button = self._button(toolbar, "Save alignment…", self._save)
        self.export_button = self._button(toolbar, "Export trimmed clips…", self._export)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.stack = QStackedWidget()
        self.placeholder = QLabel()
        self.placeholder.setWordWrap(True)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.placeholder)
        layout.addWidget(self.stack, 1)

        self.alignment_controls = QWidget(self.stack)
        self.alignment_controls.hide()
        footer = QVBoxLayout(self.alignment_controls)
        footer.setContentsMargins(0, 0, 0, 0)

        self.session_transport = QWidget(self.stack)
        self.session_transport.hide()
        transport = QHBoxLayout(self.session_transport)
        transport.setContentsMargins(0, 0, 0, 0)
        self.session_slider = QSlider(Qt.Orientation.Horizontal)
        self.session_slider.setRange(0, 1_000_000)
        self.session_slider.setSingleStep(1_000)
        self.session_slider.setPageStep(100_000)
        self.session_slider.setAccessibleName("Aligned session position")
        self.session_slider.setToolTip("Scrub all cameras within the current trim window.")
        self.session_slider.sliderPressed.connect(self._pause)
        self.session_slider.valueChanged.connect(self._seek_session)
        transport.addWidget(self.session_slider, 1)
        self.session_time_label = QLabel()
        transport.addWidget(self.session_time_label)

        trim = QHBoxLayout()
        self.start = self._number(trim, "Trim start (s)", 0, 0, 6, 0.1)
        self.end = self._number(trim, "Trim end (s)", 0, 0, 6, 0.1)
        self.start.valueChanged.connect(self._edit_trim)
        self.end.valueChanged.connect(self._edit_trim)
        self.reset_button = self._button(trim, "Use shared window", self._reset_trim)
        self.compare_button = self._button(trim, "Compare all cameras", self.open_comparison)
        trim.addStretch(1)
        footer.addLayout(trim)

        self.editor = QWidget(self.alignment_controls)
        edit = QHBoxLayout(self.editor)
        edit.setContentsMargins(0, 0, 0, 0)
        self.camera_edit = QLabel()
        self.camera_edit.setTextFormat(Qt.TextFormat.PlainText)
        self.offset = self._number(edit, "Offset (s)", -1e7, 1e7, 6, 0.01)
        self.drift = self._number(edit, "Clock correction (ppm)", -999999, 1e6, 3, 10)
        self.offset.valueChanged.connect(self._edit_map)
        self.drift.valueChanged.connect(self._edit_map)
        edit.insertWidget(0, QLabel("Selected camera timing"))
        edit.insertWidget(1, self.camera_edit, 1)
        footer.addWidget(self.editor)
        self.status = QLabel()
        self.status.setWordWrap(True)
        footer.addWidget(self.status)
        self._refresh_controls()
        self._show_status()

    @staticmethod
    def _button(layout, label, callback):
        button = QPushButton(label)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    @staticmethod
    def _number(layout, label, minimum, maximum, decimals, step):
        spin = QDoubleSpinBox()
        spin.setDecimals(decimals)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setKeyboardTracking(False)
        layout.addWidget(QLabel(label))
        layout.addWidget(spin)
        return spin

    def _choose_recordings(self):
        if not self._can_discard():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Process session recordings")
        dialog.resize(760, 300)
        layout = QVBoxLayout(dialog)
        info = QLabel(f"Choose 2–{MAX_CAMERAS} camera recordings from a processed session. Their Mode 0 skeleton videos are paired automatically.")
        info.setWordWrap(True)
        layout.addWidget(info)
        files = QListWidget()
        files.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(files)
        buttons = QHBoxLayout()
        layout.addLayout(buttons)
        def add(paths):
            for path in sorted(set(paths)):
                if not files.findItems(path, Qt.MatchFlag.MatchExactly):
                    files.addItem(path)

        def add_folder():
            directory = QFileDialog.getExistingDirectory(dialog, "Choose a processed session folder", str(self.processed_root))
            if directory:
                add(str(path) for path in Path(directory).glob("*/parquet/*_features.parquet"))

        def add_files():
            paths, _ = QFileDialog.getOpenFileNames(
                dialog, "Add Mode 0 feature files", str(self.processed_root), "Features (*_features.parquet)",
            )
            add(paths)

        def remove():
            for item in files.selectedItems():
                files.takeItem(files.row(item))

        def accept():
            try:
                validate_camera_count(files.count())
            except ValueError as exc:
                QMessageBox.information(dialog, "Choose recordings", str(exc))
                return
            dialog.accept()

        self._button(buttons, "Add session folder…", add_folder)
        self._button(buttons, "Add recording files…", add_files)
        self._button(buttons, "Remove selected", remove)
        buttons.addStretch(1)
        self._button(buttons, "Cancel", dialog.reject)
        self._button(buttons, "Align recordings", accept)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            paths = [Path(files.item(i).text()) for i in range(files.count())]
            self._run_job("Matching saved motion traces…", process_session, self._open_session, paths)

    def _load(self):
        if not self._can_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Load alignment", str(self.processed_root), "Alignment (*.json)")
        if path:
            self._load_alignment_file(Path(path))

    def resume_alignment(self, path):
        if self.job is None and self._saved_path != path and self._can_discard():
            self._load_alignment_file(path)

    def _load_alignment_file(self, path):
        self._run_job("Loading saved alignment…", load_session, lambda result: self._open_session(result, path), path)

    def _save(self):
        if self.review_window is None:
            return
        suggested = self._saved_path or self.recordings[0].features.parent.parent.parent / "alignment.json"
        path, _ = QFileDialog.getSaveFileName(self, "Save alignment", str(suggested), "Alignment (*.json)")
        if not path:
            return
        try:
            save_session(Path(path), self.recordings, self.maps, *self.review_window)
        except (OSError, ValueError) as exc:
            self._error(exc)
            return
        self._saved_path = Path(path)
        self._dirty = False
        self.saved_alignment_opened.emit(self._saved_path)
        self.statusBar().showMessage(f"Saved {path}", 10000)

    def _export(self):
        if self.review_window is None:
            return
        try:
            export_ranges(self.recordings, self.maps, *self.review_window)
        except ValueError as exc:
            self._error(exc)
            return
        folder = QFileDialog.getExistingDirectory(self, "Export trimmed skeleton clips to", str(self.processed_root))
        if folder:
            self._run_job("Writing trimmed skeleton clips…", export_session, self._export_finished,
                          Path(folder), self.recordings, self.maps, *self.review_window)

    def _export_finished(self, output):
        QMessageBox.information(self, "Export complete", f"Trimmed clips and alignment saved in\n{output}")

    def _run_job(self, message, work, done, *args):
        self._pause()
        self.job = self.executor.submit(work, *args), done
        self.status.setText(message)
        self.placeholder.setText(message)
        self._refresh_controls()
        self.job_timer.start()

    def _finish_job(self):
        future, done = self.job
        if not future.done():
            return
        self.job_timer.stop()
        self.job = None
        try:
            done(future.result())
        except Exception as exc:
            self._error(exc)
        finally:
            self._refresh_controls()
            self._show_status()

    def _open_session(self, result, saved_path=None):
        if not self._close_studios():
            return
        self.recordings, self.maps, start, end = result
        self._saved_path = saved_path
        self._dirty = saved_path is None
        self.current_time = start if start is not None else 0.0
        self.selected_camera = None
        try:
            shared_budget = 512 * 1024**2
            selected_budget = min(FrameBuffer.SELECTED_CAMERA_MEMORY_LIMIT, shared_budget * 3 // 4)
            inactive_budget = max(
                24 * 1024**2,
                (shared_budget - selected_budget) // max(1, len(self.recordings) - 1),
            )
            for recording in self.recordings:
                self.panes.append(CameraPreview(
                    recording, self._paint_preview,
                    memory_limit=inactive_budget, selected_memory_limit=selected_budget,
                ))
            self.grid = CameraGrid(self, self.panes, self._select_camera)
            self.preview_buttons = self.grid.buttons
            self._set_window(None if start is None else (start, end))
            self._select_camera(0)
        except Exception:
            self._close_studios()
            self.recordings, self.maps, self.ranges = [], [], []
            self.review_window = self.bounds = None
            raise
        if saved_path is not None:
            self.saved_alignment_opened.emit(saved_path)

    @property
    def studio(self):
        return self.studios.get(self.selected_camera)

    def camera_view_selector(self):
        selector = QComboBox()
        selector.addItems(("Show Multi View", "Maximize Selected"))
        selector.setAccessibleName("Camera view")
        selector.setToolTip("Show all cameras or fill the video area with the selected camera.")
        selector.setCurrentIndex(self.camera_view)
        selector.currentIndexChanged.connect(self._set_camera_view)
        self.camera_view_changed.connect(selector.setCurrentIndex)
        return selector

    def _set_camera_view(self, index):
        if self.camera_view != index:
            self.camera_view = index
            self.camera_view_changed.emit(index)

    def bind_zoom_to_seek(self, button):
        button.setChecked(self._zoom_to_seek)
        button.toggled.connect(self._set_zoom_to_seek)
        self.zoom_to_seek_changed.connect(button.setChecked)

    def _set_zoom_to_seek(self, checked):
        if self._zoom_to_seek != checked:
            self._zoom_to_seek = checked
            self.zoom_to_seek_changed.emit(checked)

    def _studio_for(self, index):
        if index not in self.studios:
            studio = AlignedAnnotationStudio(self, index)
            studio.playback.playing_changed.connect(self._sync_play_button)
            self.studios[index] = studio
            self.stack.addWidget(studio)
        return self.studios[index]

    def _close_studios(self):
        # Check every draft before closing any child, so cancel keeps the session usable.
        for studio in self.studios.values():
            if studio.annotation_start_frame is not None:
                choice = QMessageBox.question(
                    self, "Discard open annotation ranges?", "Discard the unsubmitted annotation ranges before leaving?",
                    QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if choice != QMessageBox.StandardButton.Discard:
                    return False
                break
        if any(not studio._confirm_pending_save() for studio in self.studios.values()):
            return False
        self._review_paint_pending = False
        self._review_sync_target = None
        if self.aligned_graph is not None:
            self.aligned_graph.closed.disconnect(self._close_graph)
            self.aligned_graph.close()
            self.aligned_graph = None
        if self.comparison is not None:
            self.comparison.close()
        if self.grid is not None:
            self.grid.hide()
            self.grid.setParent(self.stack)
        self.session_transport.hide()
        self.session_transport.setParent(self.stack)
        self.alignment_controls.hide()
        self.alignment_controls.setParent(self.stack)
        for studio in self.studios.values():
            studio.annotation_start_frame = None
            studio.close()
            self.stack.removeWidget(studio)
        self.studios.clear()
        if self.grid is not None:
            self.grid.deleteLater()
            self.grid = None
        for pane in self.panes:
            pane.release()
        self.panes.clear()
        self.stack.setCurrentWidget(self.placeholder)
        return True

    def _load_camera_edit(self):
        mapping = self.maps[self.selected_camera]
        with QSignalBlocker(self.offset), QSignalBlocker(self.drift):
            self.offset.setValue(mapping.offset)
            self.drift.setValue((mapping.rate - 1) * 1e6)

    def _edit_map(self):
        index = self.selected_camera
        previous = self.maps[index]
        change = ({"offset": self.offset.value()} if self.sender() is self.offset
                  else {"rate": 1 + self.drift.value() / 1e6})
        self.maps[index] = replace(previous, **change)
        self._dirty = True
        self._set_window()
        self._update_review()

    def _set_window(self, saved=None):
        self.review_window = self.bounds = None
        self.ranges = []
        try:
            self.bounds = common_window(self.recordings, self.maps)
            self.review_window = saved or self.bounds
            self.ranges = [trim_frames(recording, mapping, *self.review_window)
                           for recording, mapping in zip(self.recordings, self.maps)]
        except ValueError:
            self.review_window = None
        if self.review_window is not None:
            for spin, value in zip((self.start, self.end), self.review_window):
                with QSignalBlocker(spin):
                    spin.setRange(*self.bounds)
                    spin.setValue(value)

    def _edit_trim(self):
        low, high = self.bounds
        start = low if self.start.value() == self.start.minimum() else self.start.value()
        end = high if self.end.value() == self.end.maximum() else self.end.value()
        previous = self.review_window
        self._set_window((start, end) if low <= start < end <= high else previous)
        if self.review_window is None:
            self._set_window(previous)
        self._dirty |= self.review_window != previous
        self._update_review()

    def _reset_trim(self):
        previous = self.review_window
        self._set_window()
        self._dirty |= self.review_window != previous
        self._update_review()

    def _update_review(self):
        self._pause()
        if self.studio is not None:
            self.studio.configure_window()
        self._render(self.current_time, notify=False)
        if self.aligned_graph is not None:
            if self.aligned_graph.review_suspended:
                self.aligned_graph.alignment_changed = True
                self._review_sync_target = self.aligned_graph
            else:
                self.aligned_graph.update_window()
        if self.comparison is not None:
            if self.review_window is None:
                self.comparison.close()
            else:
                self.comparison.redraw()
                if self.studio is not None and self.panes[self.selected_camera].frame_id is not None:
                    self._sync_comparison_cursor(self.selected_camera, self.studio.current_frame)
        self._refresh_controls()
        self._show_status()

    def _select_camera(self, index, *, frames_from=None, playback=False, exact_frame=None):
        if index == self.selected_camera:
            return
        previous = self.studio
        resume = previous is not None and previous.playback.playing and not previous.playback.holding
        if previous is not None:
            previous.playback.pause(refresh=False)
        try:
            studio = self._studio_for(index)
        except (OSError, ValueError) as error:
            if previous is not None:
                self.panes[self.selected_camera].button.setChecked(True)
                if resume:
                    previous.playback.toggle()
                self._error(error)
                return
            raise
        self.selected_camera = index
        if previous is not None:
            previous.pane.buffer.set_selected_camera(False)
        self.panes[index].buffer.set_selected_camera(True)
        self.panes[index].button.setChecked(True)
        if previous is not None and studio.annotation_start_frame is None:
            layer = previous.editor_annotation_type.currentData()
            studio.editor_annotation_type.setCurrentIndex(studio.editor_annotation_type.findData(layer))
            studio.show_all_annotation_layers.setChecked(previous.show_all_annotation_layers.isChecked())
        studio.video_layout.insertWidget(1, self.grid, 1)
        self.grid.show()
        studio.video_layout.insertWidget(studio.video_layout.count() - 1, self.session_transport)
        self.session_transport.show()
        studio.video_layout.addWidget(self.alignment_controls)
        self.alignment_controls.show()
        self.stack.setCurrentWidget(studio)
        studio.configure_window()
        self.camera_edit.setText(self.recordings[index].label)
        self._load_camera_edit()
        self._render(self.current_time, frames_from=frames_from, playback=playback, exact_frame=exact_frame)
        if previous is not None:
            self.panes[previous.camera_index].draw()
        if resume:
            studio.playback.toggle()
        self._sync_play_button()
        if frames_from is None:
            studio.setFocus(Qt.FocusReason.OtherFocusReason)

    def _paint_preview(self, pane, pixmap):
        if self.studio is not None and pane is self.panes[self.selected_camera] and pane.frame_id == self.studio.current_frame:
            self.studio._paint_overlays(pixmap)

    def _toggle_session_playback(self):
        if self.studio is not None:
            self.resume_review()
            self.studio.playback.toggle()

    def _sync_play_button(self):
        if self.studio is not None:
            self.studio.play_button.setText("Pause" if self.studio.playback.playing else "Play")

    def _sync_session_position(self):
        if self.review_window is None:
            self.session_time_label.setText("Session —")
            position = 0
        else:
            start, end = self.review_window
            self.session_time_label.setText(f"Session {self.current_time:.3f} s")
            position = round((self.current_time - start) / (end - start) * self.session_slider.maximum())
        with QSignalBlocker(self.session_slider):
            self.session_slider.setValue(position)

    def _seek_session(self, position):
        if self.review_window is not None and self.studio is not None:
            self._pause()
            start, end = self.review_window
            self._render(start + (end - start) * position / self.session_slider.maximum())

    def _pause(self):
        if self.studio is not None:
            self.studio.playback.pause()
        if self.aligned_graph is not None:
            self.aligned_graph.playback.pause()

    def pause_other_review(self, playback):
        for viewer in (self.studio, self.aligned_graph):
            if viewer is not None and viewer.playback is not playback and viewer.playback.playing:
                viewer._pause_review()

    def refresh_paused_review(self, source):
        panes = self.panes if source is self.studio else source.panes
        for pane in panes:
            if pane.frame_id is not None:
                pane.buffer.request(pane.frame_id)
        if not self.review_suspended:
            self._flush_review_paint(playing=False)
            self.studio._refresh_paused_frame()
        if self.aligned_graph is not None and not self.aligned_graph.review_suspended:
            self.aligned_graph.flush_review_paint(playing=False)
            self.aligned_graph._refresh_paused_frame()

    def review_frame_changed(self, viewer, *, playback=False, exact_frame=None):
        self.pause_other_review(viewer.playback)
        from_annotation = viewer is self.studio
        target = self.aligned_graph if from_annotation else self
        if target is not None and target.review_suspended:
            self._review_sync_target = target
        else:
            self._sync_other_review(viewer, playback=playback, exact_frame=exact_frame)
        if self.comparison is not None:
            camera = self.selected_camera if from_annotation else viewer.selected_camera
            self._sync_comparison_cursor(camera, viewer.current_frame)

    def resume_review_sync(self, target):
        if self._review_sync_target is not target:
            return
        self._review_sync_target = None
        if self.review_window is None:
            if target is self.aligned_graph:
                target.alignment_changed = False
                target.update_window()
            return
        source = self.aligned_graph if target is self else self.studio
        if source is not None:
            camera = source.selected_camera if target is self else self.selected_camera
            self._sync_other_review(source, exact_frame=(camera, source.current_frame))

    def _sync_other_review(self, viewer, *, playback=False, exact_frame=None):
        if viewer is self.studio:
            camera, panes = self.selected_camera, self.panes
            if self.aligned_graph is not None:
                rebuild = self.aligned_graph.alignment_changed
                self.aligned_graph.alignment_changed = False
                if self.aligned_graph.selected_camera != camera:
                    self.aligned_graph.select_camera(camera, playback=playback,
                                                     frames_from=panes, exact_frame=exact_frame)
                elif rebuild:
                    self.aligned_graph.update_window(frames_from=panes, exact_frame=exact_frame)
                else:
                    self.aligned_graph.render(self.current_time, playback=playback,
                                              frames_from=panes, exact_frame=exact_frame)
        else:
            camera, panes = viewer.selected_camera, viewer.panes
            if self.selected_camera != camera:
                self._select_camera(camera, playback=playback, frames_from=panes, exact_frame=exact_frame)
            else:
                self._render(self.current_time, playback=playback, frames_from=panes, exact_frame=exact_frame)

    def _sync_comparison_cursor(self, camera, frame):
        frame_time = self.maps[camera].session_time(self.recordings[camera].times[frame])
        self.comparison.set_frame_time(frame_time)

    def _flush_review_paint(self, *, playing):
        if not self._review_paint_pending:
            return
        self._review_paint_pending = False
        self._sync_session_position()
        selected = self.panes[self.selected_camera]
        for pane in self.panes:
            if pane is not selected:
                pane.draw()
        if selected.frame_id is not None:
            self.studio._present_frame(selected.frame_id, playing=playing)

    def _pause_review(self):
        if self.studio is not None:
            self.studio._pause_review()

    def _resume_review(self):
        self.resume_review_sync(self)
        self._flush_review_paint(playing=True)

    def _render(self, time, *, playback=False, frames_from=None, exact_frame=None, notify=True):
        if self.review_window is None:
            self._review_paint_pending = False
            for pane in self.panes:
                pane.clear_frame("No shared frame")
            return False
        start, end = self.review_window
        time = min(end, max(start, time))
        updates = update_camera_frames(self, self.panes, time, playback=playback,
                                       frames_from=frames_from, exact_frame=exact_frame)
        if updates is None:
            return False
        self.current_time = time
        selected = self.panes[self.selected_camera]
        if selected.frame_id is None:
            self.studio.annotation_status.setText("Could not decode the selected camera frame.")
            return False
        selected_changed = selected in updates or self.studio.current_frame != selected.frame_id
        if playback and frames_from is not None and review_window_is_covered(self):
            self.studio.current_frame = selected.frame_id
            self._review_paint_pending = True
        elif self._review_paint_pending:
            self._flush_review_paint(playing=playback)
        else:
            self._sync_session_position()
            for pane in updates:
                if pane is not selected:
                    pane.draw()
            if not playback or selected_changed:
                self.studio._present_frame(selected.frame_id, playing=playback)
        if notify and frames_from is None and (not playback or updates or selected_changed):
            self.review_frame_changed(self.studio, playback=playback, exact_frame=exact_frame)
        return True

    def _refresh_controls(self):
        ready = self.job is None
        valid = ready and self.review_window is not None
        self.process_button.setEnabled(ready)
        self.load_button.setEnabled(ready)
        self.editor.setEnabled(ready and bool(self.recordings))
        self.stack.setEnabled(ready)
        for control in (self.save_button, self.export_button, self.start, self.end, self.reset_button, self.compare_button):
            control.setEnabled(valid)
        self.session_slider.setEnabled(valid and self.studio is not None)
        self._sync_play_button()
        self._sync_session_position()

    def open_graph(self):
        self._pause_review()
        if self.review_window is None:
            return
        try:
            if self.aligned_graph is None:
                self.aligned_graph = AlignedGraphViewer(
                    self, frame_jump=self.studio.frame_jump,
                    selected_camera=self.selected_camera,
                )
                self.aligned_graph.playback.playing_changed.connect(self._sync_play_button)
                self.aligned_graph.closed.connect(self._close_graph)
                if self.studio._graph_angle_selection is not None:
                    self.aligned_graph.graph.restore_angle_selection(self.studio._graph_angle_selection)
            else:
                self.aligned_graph.resume_review()
                self.aligned_graph.select_camera(self.selected_camera)
            self.aligned_graph.overlay_button.setChecked(self.studio.overlay_button.isChecked())
            self._mirror_graph()
            self.aligned_graph.activate_review()
            self.aligned_graph.showMaximized()
            self.aligned_graph.raise_()
            self.aligned_graph.activateWindow()
        except (OSError, ValueError) as error:
            self._error(error)

    def _mirror_graph(self):
        graph_viewer = self.aligned_graph
        if graph_viewer is not None and self.studio is not None and graph_viewer.selected_camera == self.selected_camera:
            self.studio._graph_angle_selection = graph_viewer.graph.angle_selection()
            self.studio._mirrored_angle_traces = graph_viewer.graph.overlay_traces()
            if not self.review_suspended:
                self.studio._render_video_pixmap()

    def _close_graph(self):
        index = self.aligned_graph.selected_camera
        self.aligned_graph = None
        self._review_sync_target = None
        if index != self.selected_camera:
            self._select_camera(index)
        elif self.studio is not None:
            self._render(self.current_time)

    def open_comparison(self, *, source=None, viewer=None):
        if self.review_window is None:
            return
        if self.comparison is not None:
            self.comparison.raise_()
            self.comparison.activateWindow()
            return
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.finished.connect(lambda: setattr(self, "comparison", None))
        dialog.setWindowTitle("AIHuMo · Compare all cameras")
        dialog.resize(1050, 630)
        layout = QVBoxLayout(dialog)
        controls = QHBoxLayout()
        sources, joints = QComboBox(), QComboBox()
        available = {key for recording in self.recordings for key in recording.angles}
        for key, label in SOURCE_LABELS.items():
            if any(family == key for family, _ in available):
                sources.addItem(label, key)
        if sources.findData(source) >= 0:
            sources.setCurrentIndex(sources.findData(source))
        controls.addWidget(QLabel("Source values"))
        controls.addWidget(sources)
        controls.addWidget(QLabel("Joint angle"))
        controls.addWidget(joints)
        self._button(controls, "Reset zoom", lambda: axes.set_xlim(*self.review_window))
        self._button(controls, "+", lambda: zoom(0.6))
        self._button(controls, "−", lambda: zoom(1.7))
        zoom_to_seek = zoom_to_seek_button(dialog)
        self.bind_zoom_to_seek(zoom_to_seek)
        controls.addWidget(zoom_to_seek)
        controls.addStretch()
        layout.addLayout(controls)
        figure = Figure(layout="constrained")
        canvas = FigureCanvasQTAgg(figure)
        axes = figure.add_subplot()
        current = viewer or self.studio
        camera = current.selected_camera if viewer is not None else self.selected_camera
        frame_time = self.maps[camera].session_time(self.recordings[camera].times[current.current_frame])
        cursor = background = None

        def zoom(factor):
            low, high = axes.get_xlim()
            limits = centered_time_limits(self.review_window, frame_time, (high - low) * factor)
            if limits != (low, high):
                axes.set_xlim(*limits)

        def seek_time(time):
            self._pause()
            if viewer is self.aligned_graph and viewer is not None:
                viewer.render(time)
            else:
                self._render(time)

        def seek_on_zoom(time):
            if zoom_to_seek.isChecked():
                seek_time(time)

        toolbar = FrameZoomToolbar(canvas, dialog, zoom, seek_on_zoom=seek_on_zoom)
        layout.addWidget(toolbar)
        layout.addWidget(canvas, 1)

        def cache_background(_event):
            nonlocal background
            if cursor is not None:
                background = canvas.copy_from_bbox(axes.bbox)
                axes.draw_artist(cursor)

        def invalidate_background(_axes):
            nonlocal background
            background = None
            canvas.draw_idle()

        def set_frame_time(time):
            nonlocal frame_time
            if time == frame_time:
                return
            frame_time = time
            cursor.set_xdata([time, time])
            low, high = axes.get_xlim()
            if not low <= time <= high:
                axes.set_xlim(*centered_time_limits(self.review_window, time, high - low))
            elif background is not None:
                canvas.restore_region(background)
                axes.draw_artist(cursor)
                canvas.blit(axes.bbox)
            else:
                canvas.draw_idle()

        def scroll(event):
            if event.inaxes is axes and event.xdata is not None:
                factor = wheel_zoom_factor(event)
                if factor == 1:
                    return
                seek_on_zoom(event.xdata)
                zoom(factor)

        def seek(event):
            if event.inaxes is axes and not toolbar.mode and event.button == 1 and event.xdata is not None:
                seek_time(event.xdata)

        canvas.mpl_connect("draw_event", cache_background)
        canvas.mpl_connect("scroll_event", scroll)
        canvas.mpl_connect("button_press_event", seek)

        def draw():
            nonlocal cursor, background
            background = None
            axes.clear()
            key = sources.currentData(), joints.currentData()
            for recording, mapping, (first, last) in zip(self.recordings, self.maps, self.ranges):
                values = recording.angles.get(key)
                if values is not None:
                    axes.plot(mapping.session_time(recording.times[first:last + 1]), values[first:last + 1],
                              label=recording.label, linewidth=1)
            if axes.lines:
                axes.legend(loc="upper right")
            axes.set(xlabel="Session time (s)", ylabel="Angle (°)", xlim=self.review_window)
            cursor = axes.axvline(frame_time, color="#16a36c", animated=True)
            axes.grid(alpha=.2)
            axes.callbacks.connect("xlim_changed", invalidate_background)
            axes.callbacks.connect("ylim_changed", invalidate_background)
            toolbar.update()
            canvas.draw_idle()

        def choose_joints():
            previous = joints.currentData()
            with QSignalBlocker(joints):
                joints.clear()
                for joint in sorted(joint for family, joint in available if family == sources.currentData()):
                    joints.addItem(joint.replace("_", " ").title(), joint)
                preferred = joints.findData(previous or "left_knee")
                if preferred >= 0:
                    joints.setCurrentIndex(preferred)
            draw()

        sources.currentIndexChanged.connect(choose_joints)
        joints.currentIndexChanged.connect(draw)
        choose_joints()
        dialog.set_frame_time = set_frame_time
        dialog.redraw = draw
        self.comparison = dialog
        dialog.show()

    def _shared_frame_range(self, origin, studio, values, first, last):
        layer = values["annotation_type"]
        start, end = values["start_frame"], values["end_frame"]
        if layer == "activity_state":
            # Consecutive intervals can round to the same frame on a slower
            # camera. Keep the earlier saved label on that boundary sample.
            peers = {row["aligned_annotation_id"]: row for row in origin.annotations
                     if row["annotation_type"] == layer and row.get("aligned_annotation_id")}
            trim_start = trim_end = False
            for row in studio.annotations:
                peer = peers.get(row.get("aligned_annotation_id"))
                if row["annotation_type"] != layer or peer is None:
                    continue
                if row["end_frame"] == first and peer["end_frame"] < start:
                    trim_start = True
                if row["start_frame"] == last and end < peer["start_frame"]:
                    trim_end = True
            first += trim_start
            last -= trim_end
        elif layer in {"set", "rep", "phase"}:
            parent_layer = {"set": "activity_state", "rep": "set", "phase": "rep"}[layer]
            parent = origin._nearest_parent(parent_layer, start, end)
            linked_id = (parent or {}).get("aligned_annotation_id")
            target_parent = next((row for row in studio.annotations
                                  if linked_id and row["annotation_type"] == parent_layer
                                  and row.get("aligned_annotation_id") == linked_id), None)
            if target_parent is not None:
                # A child's endpoint can round onto a sample assigned to the
                # neighboring activity. Keep it inside its linked parent.
                if target_parent["start_frame"] - first > 1 or last - target_parent["end_frame"] > 1:
                    raise ValueError(f"The annotation no longer fits its aligned parent on {studio.pane.recording.label}.")
                first = max(first, target_parent["start_frame"])
                last = min(last, target_parent["end_frame"])
        if first > last:
            raise ValueError(f"{studio.pane.recording.label} has no available frame for this annotation range.")
        return first, last

    def commit_shared_annotation(self, origin, values):
        if self.review_window is None:
            return False
        values["aligned_annotation_id"] = uuid4().hex
        origin_index = origin.camera_index
        mapping = self.maps[origin_index]
        origin_times = self.recordings[origin_index].times
        start = mapping.session_time(origin_times[values["start_frame"]])
        end = mapping.session_time(origin_times[values["end_frame"]])
        staged = []
        for index, (recording, target_map, bounds) in enumerate(zip(self.recordings, self.maps, self.ranges)):
            studio = self._studio_for(index)
            previous = studio._check_annotation_revision()
            state = deepcopy(studio.annotation_state)
            row = dict(values)
            if index != origin_index:
                first = frame_at(recording, target_map, start, *bounds)
                last = frame_at(recording, target_map, end, *bounds)
                first, last = self._shared_frame_range(origin, studio, values, first, last)
                source_start = float(studio._row_for_frame(first)["timestamp_s"])
                source_end = float(studio._row_for_frame(last)["timestamp_s"])
                row.update(start_frame=first, end_frame=last, start_time_s=source_start,
                           end_time_s=source_end, duration_s=source_end - source_start,
                           annotation_id=state.next_annotation_id(), segment_id=state.next_segment_id())
                layer = row["annotation_type"]
                if layer == "activity_state":
                    row["camera_angle"] = studio.metadata.get("camera_angle") or "N/A"
                elif layer == "set" and origin.editor_set_id.value() == 0:
                    row["set_id"] = studio._next_set_id_for_range(first, last)
                elif layer in {"rep", "phase"}:
                    parent_layer = "set" if layer == "rep" else "rep"
                    parent = studio._nearest_parent(parent_layer, first, last)
                    if parent is None:
                        raise ValueError(f"{recording.label} needs a matching {parent_layer} interval first.")
                    row.update(exercise=parent.get("exercise"), set_id=parent.get("set_id"))
                    if layer == "phase":
                        row["rep_id"] = parent.get("rep_id")
                    elif origin.editor_rep_id.value() == 0:
                        row["rep_id"] = studio._next_rep_id_for_range(row["set_id"], first, last)
            state.add(row)
            document = state.to_document()
            validate_annotations(document, studio.total_frames)
            staged.append((studio, state, document, previous))

        # Validate every view before writing. Roll back authoritative JSON
        # files if another camera cannot be saved, then export derivatives.
        with ExitStack() as rollback:
            for studio, _, document, previous in staged:
                path = studio.annotation_json_path
                studio._check_annotation_revision()
                save_json_atomic(document, path)
                if previous is None:
                    rollback.callback(path.unlink, missing_ok=True)
                else:
                    rollback.callback(save_json_atomic, previous, path)
            rollback.pop_all()
        for studio, state, document, _ in staged:
            studio.annotation_state = state
            studio._saved_annotation_document = deepcopy(document)
            studio._annotation_save_failed = False
            studio._export_annotation_derivatives(document, show_error=True)
            if studio is not origin:
                studio.refresh_annotation_table(select_annotation_id=studio._selected_annotation_id())
                studio._refresh_summary()
        return True

    def _show_status(self):
        if not self.recordings:
            self.placeholder.setText(
                f"Process 2–{MAX_CAMERAS} Mode 0 recordings from the same session, or load a saved alignment."
            )
            return
        if self.review_window is None:
            self.status.setText("The current offsets have no shared frame window. Adjust a camera offset to continue.")
            return
        summaries = []
        for recording, mapping, (first, last) in zip(self.recordings, self.maps, self.ranges):
            quality = " · review suggested" if mapping.needs_review else ""
            score = f" · auto match {mapping.score:.2f}" if mapping.score is not None else ""
            summaries.append(f"{recording.label} · {mapping.offset:+.3f} s · frames {first:,}–{last:,}{score}{quality}")
        self.status.setText("   |   ".join(summaries))

    def _error(self, exc):
        QMessageBox.warning(self, "Session alignment", str(exc))

    def _can_discard(self):
        return not self._dirty or QMessageBox.question(
            self, "Unsaved alignment", "Discard the unsaved alignment changes?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) == QMessageBox.StandardButton.Discard

    def closeEvent(self, event):
        if self.job is not None:
            self.statusBar().showMessage("Wait for the current alignment operation to finish.", 5000)
            event.ignore()
            return
        if not self._can_discard():
            event.ignore()
            return
        self._pause()
        if not self._close_studios():
            event.ignore()
            return
        self.executor.shutdown(wait=False)
        self.closed.emit()
        super().closeEvent(event)


class AlignedAnnotationStudio(AnnotationStudio):
    def __init__(self, session, camera_index):
        self.session = session
        self.camera_index = camera_index
        self.pane = session.panes[camera_index]
        recording = self.pane.recording
        super().__init__(recording.video, recording.features, parent=session.stack, embedded=True,
                         frame_jump=session.frame_jump)
        self.workspace_label.setText("Mode 2 Session Alignment")
        self.back_button.hide()
        self.video_label.hide()
        self.play_button.clicked.disconnect(self.playback.toggle)
        self.play_button.clicked.connect(session._toggle_session_playback)
        self.play_button.setToolTip("Play or pause all aligned cameras together.")
        self.camera_view = session.camera_view_selector()
        self.overlay_controls.insertWidget(self.overlay_controls.count() - 1, self.camera_view)
        self.annotation_scope = QComboBox()
        self.annotation_scope.addItem("All aligned cameras", True)
        self.annotation_scope.addItem("Selected camera only", False)
        self.annotation_scope.setToolTip("Scope for new annotations. Edit or delete a row to change the selected camera.")
        scope = QHBoxLayout()
        scope.addWidget(QLabel("Annotation scope"))
        scope.addWidget(self.annotation_scope, 1)
        self.annotation_editor_container.layout().insertLayout(0, scope)

    def _open_video(self):
        self.cap, self._frame_buffer = self.pane.capture, self.pane.buffer
        self._baked, self._midpoints_baked = self.pane.baked, self.pane.midpoints_baked

    def _open_frame_buffer(self):
        pass

    def _close_video(self):
        pass

    def _back(self):
        close_and_return(self.session)

    def _create_playback(self):
        return AlignmentPlayback(self, self.session.playback_speed)

    def render(self, time, *, playback=False, exact_frame=None):
        return self.session._render(time, playback=playback, exact_frame=exact_frame)

    def configure_window(self):
        valid = self.session.review_window is not None
        first, last = self.session.ranges[self.camera_index] if valid else (0, 0)
        with QSignalBlocker(self.frame_spin):
            self.frame_spin.setRange(first, last)
        self.frame_spin.setEnabled(valid)
        self.play_button.setEnabled(valid)
        self.graph_viewer_button.setEnabled(valid)

    def _show_frame(self, frame_number):
        if self.session.review_window is None:
            return False
        first, last = self.session.ranges[self.camera_index]
        frame = min(last, max(first, int(frame_number)))
        source_time = self.pane.recording.times[frame]
        return self.render(self.session.maps[self.camera_index].session_time(source_time),
                           exact_frame=(self.camera_index, frame))

    def _render_video_pixmap(self, row=None, *, playing=None):
        self.pane.draw()

    def _frame_info(self, row):
        return f"{super()._frame_info(row)} | Aligned: {self.session.current_time:.3f}s"

    def start_range_capture(self):
        if self.session.review_window is not None:
            super().start_range_capture()

    def _annotation_range_available(self, start_frame, end_frame):
        if self.session.review_window is not None:
            first, last = self.session.ranges[self.camera_index]
            if first <= start_frame <= end_frame <= last:
                return True
        self.annotation_status.setText("The annotation extends outside the current trim. Expand the trim or use Mode 1.")
        return False

    def _commit_annotation(self, values, existing=None):
        if not self._annotation_range_available(values["start_frame"], values["end_frame"]):
            return False
        if existing is None and self.annotation_scope.currentData():
            return self.session.commit_shared_annotation(self, values)
        return super()._commit_annotation(values, existing)

    def open_annotation_graph(self):
        self.session.open_graph()
