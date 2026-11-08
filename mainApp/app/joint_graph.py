"""Timestamp-aware joint-angle graphs shared by the desktop workspaces."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from PyQt6.QtCore import QSignalBlocker, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib import colormaps
from matplotlib.colors import to_hex

from aihumo.features import LEGACY_ANGLE_PREFIX, PROJECTED_ANGLE_PREFIX, WORLD_ANGLE_PREFIX, angle_family

from .angle_overlay import ANGLE_VERTICES, OverlayTrace, angle_name

TIME_COLUMNS = ("timeElapsedS", "timestamp_s", "time_elapsed_s")
PROJECTED_SOURCE = "Video plane (2D)"
WORLD_SOURCE = "Estimated world (3D)"
SAVED_SOURCE = "Legacy (normalized image)"
ANGLE_SOURCES = {
    PROJECTED_SOURCE: PROJECTED_ANGLE_PREFIX,
    WORLD_SOURCE: WORLD_ANGLE_PREFIX,
    SAVED_SOURCE: LEGACY_ANGLE_PREFIX,
}
ANGLE_AXIS_LABELS = {
    PROJECTED_SOURCE: "Projected angle (°)",
    WORLD_SOURCE: "Estimated 3D angle (°)",
    SAVED_SOURCE: "Legacy angle (°)",
}


@dataclass(frozen=True)
class GraphAngleSelection:
    source: str
    checked: frozenset[str]


class JointGraphWidget(QWidget):
    """Interactive graph of all registered joint-angle features.

    The x-axis is always the source elapsed-time column. No fixed duration or
    FPS is assumed, so the same widget works for short clips and long sessions.
    Matplotlib's toolbar provides zoom/pan; the wheel handler adds centered
    horizontal zoom, and clicking the graph seeks the synchronized video.
    """

    frameSelected = pyqtSignal(int)
    navigationStarted = pyqtSignal()
    traceSelectionChanged = pyqtSignal()

    def __init__(self, dataframe: pd.DataFrame, parent=None, *, link_video: bool = False):
        super().__init__(parent)
        # The frame table belongs to the caller. This widget only reads it.
        self.dataframe = dataframe
        self.time_column = next((name for name in TIME_COLUMNS if name in dataframe), None)
        self.frame_column = "frame_id" if "frame_id" in dataframe.columns else None
        self._angle_sources = {}
        for source, prefix in ANGLE_SOURCES.items():
            columns = angle_family(dataframe.columns, prefix)
            if columns:
                self._angle_sources[source] = {
                    f"{LEGACY_ANGLE_PREFIX}{joint}": self._numeric_column(column)
                    for joint, column in columns.items()
                }
        self.angle_columns = sorted({column for values in self._angle_sources.values() for column in values})
        self._times = self._numeric_column(self.time_column) if self.time_column else np.array([])
        self._frame_ids = self._numeric_column(self.frame_column) if self.frame_column else np.arange(len(dataframe))
        self._values = next(iter(self._angle_sources.values()), {})
        self._time_rows = np.flatnonzero(np.isfinite(self._times))
        self._time_rows = self._time_rows[np.argsort(self._times[self._time_rows], kind="stable")]
        self._ordered_times = self._times[self._time_rows]
        self._full_xlim: tuple[float, float] = (0.0, 1.0)
        if len(self._ordered_times):
            low, high = float(self._ordered_times[0]), float(self._ordered_times[-1])
            self._full_xlim = (low, high if high > low else low + 1)
        self._cursor = None
        self._hover_dot = None
        self._hover_sample = None
        self._active_row: int | None = None
        self._selected_trace: str | None = None
        self._lines = {}
        self.trace_checks: dict[str, QCheckBox] = {}
        self._last_current_time: float | None = None
        self._updating_limits = False
        self._link_video = link_video
        self._following_video = False
        self._drag_xlim = None
        self._viewport_seek = QTimer(self)
        self._viewport_seek.setSingleShot(True)
        self._viewport_seek.timeout.connect(self._seek_view_center)

        controls = QHBoxLayout()
        self.follow_frame = QCheckBox("Follow frame")
        self.follow_frame.setToolTip("Keep the current frame visible while navigating the video.")
        self.linked_frame_label = QLabel()
        if link_video:
            self.follow_frame.hide()
            self.linked_frame_label.setToolTip("The vertical cursor marks the exact frame shown in the video.")
            controls.addWidget(self.linked_frame_label)
        else:
            controls.addWidget(self.follow_frame)
        reset_button = QPushButton("Reset zoom")
        reset_button.clicked.connect(self.reset_zoom)
        controls.addWidget(reset_button)
        zoom_in = QPushButton("+")
        zoom_in.setToolTip("Zoom in around the current graph center")
        zoom_in.clicked.connect(lambda: self._scale_x(0.6))
        controls.addWidget(zoom_in)
        zoom_out = QPushButton("−")
        zoom_out.setToolTip("Zoom out around the current graph center")
        zoom_out.clicked.connect(lambda: self._scale_x(1.7))
        controls.addWidget(zoom_out)
        controls.addStretch(1)

        detail_controls = QHBoxLayout()
        detail_controls.addWidget(QLabel("Detail window"))
        self.detail_window_spin = QDoubleSpinBox()
        self.detail_window_spin.setRange(0.05, 86400.0)
        self.detail_window_spin.setDecimals(2)
        self.detail_window_spin.setSingleStep(0.25)
        self.detail_window_spin.setValue(1.0)
        self.detail_window_spin.setSuffix(" s")
        self.detail_window_spin.setToolTip(
            "Choose the visible source-time window. At 1 second, all native frames in that second are shown."
        )
        detail_controls.addWidget(self.detail_window_spin)
        zoom_window = QPushButton("Zoom to window")
        zoom_window.setToolTip("Center the selected detail window on the current frame or graph center.")
        zoom_window.clicked.connect(self.zoom_to_detail_window)
        detail_controls.addWidget(zoom_window)
        self.show_points = QCheckBox("Frame points")
        self.show_points.setChecked(True)
        self.show_points.setToolTip("Show individual Parquet samples when the visible window is detailed enough.")
        self.show_points.toggled.connect(self._update_visible_detail)
        detail_controls.addWidget(self.show_points)
        self.auto_y = QCheckBox("Auto-scale Y")
        self.auto_y.setChecked(True)
        self.auto_y.setToolTip("Fit the angle range to the data currently visible in the time window.")
        self.auto_y.toggled.connect(self._update_visible_detail)
        detail_controls.addWidget(self.auto_y)
        detail_controls.addStretch(1)
        angle_controls = QHBoxLayout()
        angle_controls.addWidget(QLabel("Angle source"))
        self.angle_source = QComboBox()
        self.angle_source.addItems(self._angle_sources)
        self.angle_source.setEnabled(len(self._angle_sources) > 1)
        self.angle_source.setToolTip(
            "Video plane uses pixel XY. Estimated world uses MediaPipe world XYZ. "
            "Legacy uses the original normalized-image angle calculation."
        )
        self.angle_source.currentTextChanged.connect(self._change_angle_source)
        angle_controls.addWidget(self.angle_source)
        angle_controls.addStretch(1)
        self.point_info = QLabel("Zoom or hover to inspect native frame samples.")
        self.sample_card = QLabel()
        self.sample_card.setTextFormat(Qt.TextFormat.PlainText)
        self.sample_card.setWordWrap(True)
        self.sample_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.sample_card.setFixedHeight(6 * self.sample_card.fontMetrics().lineSpacing() + 16)

        self.figure = Figure(figsize=(9, 3.8))
        self.axis = self.figure.add_subplot(111)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_click)
        self.canvas.mpl_connect("button_release_event", self._on_graph_release)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("axes_leave_event", self._clear_hover)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addLayout(detail_controls)
        layout.addLayout(angle_controls)
        layout.addWidget(self.toolbar)
        chart = QHBoxLayout()
        chart.addWidget(self.canvas, 1)
        chart.addWidget(self._build_legend())
        layout.addLayout(chart, 1)
        layout.addWidget(self.point_info)
        layout.addWidget(self.sample_card)
        self._redraw_series()

    def _numeric_column(self, column: str) -> np.ndarray:
        return pd.to_numeric(self.dataframe[column], errors="coerce").to_numpy(dtype=float)

    def _build_legend(self) -> QGroupBox:
        legend = QGroupBox("Joint traces")
        layout = QVBoxLayout(legend)
        actions = QHBoxLayout()
        for label, visible in (("Show all", True), ("Hide all", False)):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, visible=visible: self._set_all_traces(visible))
            actions.addWidget(button)
        layout.addLayout(actions)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(155)
        scroll.setMaximumWidth(222)
        contents = QWidget()
        rows = QVBoxLayout(contents)
        colors = colormaps["tab20"].colors
        palette = colors[::2] + colors[1::2]
        self._trace_colors = {}
        for index, column in enumerate(self.angle_columns):
            color = to_hex(palette[index % len(palette)])
            self._trace_colors[column] = color
            row = QHBoxLayout()
            swatch = QLabel()
            swatch.setFixedSize(12, 4)
            swatch.setStyleSheet(f"background: {color}")
            row.addWidget(swatch)
            check = QCheckBox(self._display_name(column))
            check.setChecked(True)
            check.toggled.connect(lambda checked, column=column: self._refresh_trace_visibility(
                column if checked else None
            ))
            row.addWidget(check, 1)
            rows.addLayout(row)
            self.trace_checks[column] = check
        rows.addStretch(1)
        scroll.setWidget(contents)
        layout.addWidget(scroll)
        return legend

    def _set_all_traces(self, visible: bool) -> None:
        for column in self._values:
            check = self.trace_checks[column]
            blocked = check.blockSignals(True)
            check.setChecked(visible)
            check.blockSignals(blocked)
        self._refresh_trace_visibility()

    def _refresh_trace_visibility(self, selected: str | None = None) -> None:
        if selected is not None:
            self._selected_trace = selected
        for column, line in self._lines.items():
            line.set_visible(self.trace_checks[column].isChecked())
        self._clear_hover()
        self._show_current_sample()
        self._update_visible_detail()
        self.traceSelectionChanged.emit()

    def _change_angle_source(self, source: str) -> None:
        self._values = self._angle_sources[source]
        self._redraw_series()
        self.traceSelectionChanged.emit()

    def angle_selection(self) -> GraphAngleSelection:
        return GraphAngleSelection(
            self.angle_source.currentText(),
            frozenset(joint for joint, check in self.trace_checks.items() if check.isChecked()),
        )

    def restore_angle_selection(self, selection: GraphAngleSelection) -> None:
        for joint, check in self.trace_checks.items():
            with QSignalBlocker(check):
                check.setChecked(joint in selection.checked)
        if selection.source in self._angle_sources and selection.source != self.angle_source.currentText():
            self.angle_source.setCurrentText(selection.source)
        else:
            self._refresh_trace_visibility()

    def overlay_traces(self) -> tuple[OverlayTrace, ...]:
        prefix = ANGLE_SOURCES.get(self.angle_source.currentText())
        if prefix is None:
            return ()
        return tuple(
            OverlayTrace(joint, f"{prefix}{joint.removeprefix(LEGACY_ANGLE_PREFIX)}", self._trace_colors[joint])
            for joint, line in self._lines.items() if line.get_visible()
        )

    def _rows_between(self, low: float, high: float) -> np.ndarray:
        start = self._ordered_times.searchsorted(low, side="left")
        stop = self._ordered_times.searchsorted(high, side="right")
        return self._time_rows[start:stop]

    @staticmethod
    def _display_name(column: str) -> str:
        if column == "angle_torso_nose_shoulder_hip":
            return "Neck at Shoulder Midpoint"
        return angle_name(column)

    def _redraw_series(self) -> None:
        xlim = self.axis.get_xlim() if self._cursor is not None else self._full_xlim
        self.axis.clear()
        self._lines = {}
        self._hover_dot = None
        self._hover_sample = None
        self.axis.set_xlabel("Elapsed source time (s)")
        self.axis.set_ylabel(ANGLE_AXIS_LABELS.get(self.angle_source.currentText(), "Joint angle (°)"))
        self.axis.set_title("AIHuMo — Joint-angle graphs")
        self.axis.grid(True, alpha=0.25)
        for column, check in self.trace_checks.items():
            check.setEnabled(column in self._values)
        if not self.time_column or self.dataframe.empty:
            self.axis.text(0.5, 0.5, "No timestamped angle features available", ha="center", va="center")
            self._show_current_sample()
            self.canvas.draw_idle()
            return
        for column, values in self._values.items():
            line, = self.axis.plot(
                self._times,
                values,
                linewidth=1.0,
                label=self._display_name(column),
                color=self._trace_colors[column],
                visible=self.trace_checks[column].isChecked(),
                marker="o",
                markersize=3.0,
                markeredgewidth=0.0,
            )
            self._lines[column] = line
        self.figure.subplots_adjust(left=0.14, right=0.97, bottom=0.16, top=0.88)
        self.axis.set_xlim(*xlim)
        cursor_time = self._last_current_time
        if cursor_time is None:
            cursor_time = self._full_xlim[0]
        self._cursor = self.axis.axvline(cursor_time, color="#20c55a", linewidth=1.5, alpha=0.9)
        self._hover_dot, = self.axis.plot([], [], "o", markersize=8, markerfacecolor="white",
                                         markeredgewidth=2, zorder=10, visible=False)
        self.axis.callbacks.connect("xlim_changed", self._on_xlim_changed)
        self._show_current_sample()
        self._update_visible_detail()
        self.canvas.draw_idle()

    def set_current_frame(self, frame: int) -> None:
        if self._cursor is None or self.dataframe.empty or not self.time_column:
            return
        index = int(np.clip(frame, 0, len(self.dataframe) - 1))
        if self.frame_column and self._frame_ids[index] != frame:
            matches = np.flatnonzero(self._frame_ids == frame)
            if len(matches):
                index = int(matches[0])
        if not np.isfinite(self._times[index]):
            return
        current_time = float(self._times[index])
        self._active_row = index
        self._last_current_time = current_time
        self._cursor.set_xdata([current_time, current_time])
        if self._link_video:
            self.linked_frame_label.setText(f"Frame {frame:,} | {current_time:.6f} s")
            self._viewport_seek.stop()
        if self._link_video or self.follow_frame.isChecked():
            low, high = self.axis.get_xlim()
            width = high - low
            if width > 0 and not (low <= current_time <= high):
                # Following playback changes the viewport, but is never a
                # request to seek the video back to the viewport center.
                self._following_video = True
                try:
                    self._set_xlim_centered(current_time, width)
                finally:
                    self._following_video = False
        if self._hover_sample is None:
            self._show_current_sample()
        self.canvas.draw_idle()

    def zoom_to_detail_window(self) -> None:
        """Show a precise source-time window without resampling the Parquet."""
        if not self.time_column or self.dataframe.empty:
            return
        center = self._last_current_time
        if center is None:
            low, high = self.axis.get_xlim()
            center = (low + high) / 2.0
        width = min(float(self.detail_window_spin.value()), self._full_xlim[1] - self._full_xlim[0])
        if width <= 0:
            return
        self._set_xlim_centered(center, width)

    def _set_xlim_centered(self, center: float, width: float) -> None:
        full_low, full_high = self._full_xlim
        width = min(max(float(width), 1e-9), max(full_high - full_low, 1e-9))
        center = min(max(float(center), full_low), full_high)
        new_low = center - width / 2.0
        new_high = center + width / 2.0
        if new_low < full_low:
            new_high += full_low - new_low
            new_low = full_low
        if new_high > full_high:
            new_low -= new_high - full_high
            new_high = full_high
        self.axis.set_xlim(max(full_low, new_low), min(full_high, new_high))
        self._update_visible_detail()
        self.canvas.draw_idle()

    def reset_zoom(self) -> None:
        self.axis.set_xlim(*self._full_xlim)
        self._update_visible_detail()
        self.canvas.draw_idle()

    def _scale_x(self, factor: float, center: float | None = None) -> None:
        low, high = self.axis.get_xlim()
        center = float(center if center is not None else (low + high) / 2.0)
        half_width = (high - low) * float(factor) / 2.0
        new_low = max(self._full_xlim[0], center - half_width)
        new_high = min(self._full_xlim[1], center + half_width)
        if new_high - new_low > 1e-9:
            self.axis.set_xlim(new_low, new_high)
            self._update_visible_detail()
            self.canvas.draw_idle()

    def _on_scroll(self, event) -> None:
        if event.inaxes is not self.axis or event.xdata is None:
            return
        self._scale_x(0.65 if event.button == "up" else 1.55, event.xdata)

    def _on_xlim_changed(self, _axis) -> None:
        if not self._updating_limits:
            self._clear_hover()
            self._update_visible_detail()
            if self._link_video and not self._following_video and self._drag_xlim is None:
                if self._cursor_outside_view():
                    self.navigationStarted.emit()
                    # Wait for Matplotlib to finish applying the toolbar or
                    # scroll action before video-driven updates can follow it.
                    self._viewport_seek.start(0)
                else:
                    self._viewport_seek.stop()

    def _cursor_outside_view(self) -> bool:
        low, high = self.axis.get_xlim()
        return self._last_current_time is not None and not low <= self._last_current_time <= high

    def _seek_view_center(self, *, pan: bool = False) -> None:
        if pan or self._cursor_outside_view():
            low, high = self.axis.get_xlim()
            self._seek_timestamp((low + high) / 2)

    def _on_graph_release(self, event) -> None:
        if self._drag_xlim is None:
            return
        previous, self._drag_xlim = self._drag_xlim, None
        current = self.axis.get_xlim()
        if current != previous:
            # A horizontal drag selects the new view's center. A zoom keeps
            # the current frame when its timestamp remains in the window.
            pan = getattr(self.toolbar.mode, "name", "") == "PAN" and event.button == 1
            self._seek_view_center(pan=pan)

    def _update_visible_detail(self) -> None:
        """Toggle point markers and optional Y autoscale for the visible window."""
        if not self.time_column or self.dataframe.empty:
            return
        low, high = self.axis.get_xlim()
        rows = self._rows_between(low, high)
        sample_count = len(rows)
        for line in self._lines.values():
            if self.show_points.isChecked() and sample_count <= 240:
                line.set_marker("o")
                line.set_markersize(3.0)
            else:
                line.set_marker("none")
        active = [column for column, line in self._lines.items() if line.get_visible()]
        if self.auto_y.isChecked() and len(rows):
            bounds = []
            for column in active:
                values = self._values[column][rows]
                finite = values[np.isfinite(values)]
                if len(finite):
                    bounds.append((float(finite.min()), float(finite.max())))
            if bounds:
                minimum = min(low for low, _ in bounds)
                maximum = max(high for _, high in bounds)
                spread = max(maximum - minimum, 1.0)
                margin = spread * 0.08
                self._updating_limits = True
                try:
                    self.axis.set_ylim(minimum - margin, maximum + margin)
                finally:
                    self._updating_limits = False
        self.point_info.setText(
            f"{len(active)}/{len(self._lines)} traces | {sample_count} native samples | "
            f"{max(0.0, high - low):.3f} s in view"
        )
        self.canvas.draw_idle()

    def _on_motion(self, event) -> None:
        if event.inaxes is not self.axis or event.xdata is None or getattr(event, "buttons", ()):
            self._clear_hover()
            return
        # Limit the search to a small horizontal neighborhood, then compare
        # actual 2D pixel distances so crossing traces are distinguishable.
        radius = 12 * self.canvas.devicePixelRatioF()
        inverse = self.axis.transData.inverted()
        x1, x2 = inverse.transform([(event.x - radius, event.y), (event.x + radius, event.y)])[:, 0]
        low, high = self.axis.get_xlim()
        rows = self._rows_between(max(low, min(x1, x2)), min(high, max(x1, x2)))
        best = None
        best_distance = radius ** 2
        y_low, y_high = sorted(self.axis.get_ylim())
        for column, line in self._lines.items():
            if not line.get_visible() or not len(rows):
                continue
            values = self._values[column][rows]
            visible = rows[np.isfinite(values) & (values >= y_low) & (values <= y_high)]
            if not len(visible):
                continue
            points = np.column_stack((self._times[visible], self._values[column][visible]))
            pixels = self.axis.transData.transform(points)
            distances = np.sum((pixels - (event.x, event.y)) ** 2, axis=1)
            closest = int(np.argmin(distances))
            if distances[closest] < best_distance:
                best = (column, int(visible[closest]))
                best_distance = distances[closest]
        if best is None:
            self._clear_hover()
        elif best != self._hover_sample:
            column, row = best
            self._hover_sample = best
            self._selected_trace = column
            self._show_sample(column, row, hovered=True)
            self.canvas.draw_idle()

    def _set_sample_card(self, text: str, color: str) -> None:
        self.sample_card.setText(text)
        style = (
            f"padding: 5px; border: 2px solid {color}; border-radius: 4px;"
            "background: palette(base); color: palette(text);"
        )
        if self.sample_card.styleSheet() != style:
            self.sample_card.setStyleSheet(style)

    def _clear_hover(self, _event=None) -> None:
        if self._hover_sample is None:
            return
        self._hover_sample = None
        self._show_current_sample()
        self.canvas.draw_idle()

    def _show_current_sample(self) -> None:
        selected = self._selected_trace
        if selected not in self._lines or not self._lines[selected].get_visible():
            selected = next((column for column, line in self._lines.items() if line.get_visible()), None)
        if selected is not None and self._active_row is not None:
            self._show_sample(selected, self._active_row)
        else:
            if self._hover_dot is not None:
                self._hover_dot.set_visible(False)
            self._set_sample_card("Hover near a visible trace to inspect its closest frame sample.", "palette(mid)")

    def _show_sample(self, column: str, row: int, *, hovered: bool = False) -> None:
        color = self._trace_colors[column]
        value = self._values[column][row]
        if np.isfinite(value):
            self._hover_dot.set_data([self._times[row]], [value])
            self._hover_dot.set_markeredgecolor(color)
            self._hover_dot.set_visible(True)
        else:
            self._hover_dot.set_visible(False)
        self._set_sample_card(self._describe_sample(column, row, hovered=hovered), color)

    def _difference(self, current, previous, row: int):
        if row < 1 or current is None or previous is None:
            return None
        elapsed = self._times[row] - self._times[row - 1]
        if (not np.isfinite(elapsed) or elapsed <= 0
                or self._frame_ids[row] - self._frame_ids[row - 1] != 1
                or not np.all(np.isfinite(current)) or not np.all(np.isfinite(previous))):
            return None
        return (current - previous) / elapsed

    def _joint_position(self, row: int, landmarks: tuple[int, ...], space: str):
        if row < 0 or not landmarks:
            return None
        sample = self.dataframe.iloc[row]
        try:
            points = np.array([
                [sample.get(f"{space}{index}_{axis}", np.nan) for axis in "xyz"]
                for index in landmarks
            ], dtype=float)
        except (TypeError, ValueError):
            return None
        return points.mean(axis=0) if np.isfinite(points).all() else None

    @staticmethod
    def _format_xyz(values) -> str:
        return "(" + ", ".join(f"{value:.3f}" for value in values) + ")"

    def _describe_sample(self, column: str, row: int, *, hovered: bool = False) -> str:
        frame = self._frame_ids[row]
        frame = int(frame) if np.isfinite(frame) else "unknown"
        values = self._values[column]
        angle = f"{values[row]:.2f}°" if np.isfinite(values[row]) else "unavailable"
        sample_kind = "hovered sample" if hovered else "current"
        lines = [
            f"{self._display_name(column)}   |   Angle {angle}",
            f"Video frame {frame} ({sample_kind})   |   Source time {self._times[row]:.6f} s",
        ]
        omega = self._difference(values[row], values[row - 1], row) if row >= 1 else None
        if omega is not None:
            line = f"Angular velocity {omega:+.2f} °/s"
            if row >= 2:
                previous = self._difference(values[row - 1], values[row - 2], row - 1)
                alpha = self._difference(omega, previous, row)
                if alpha is not None:
                    line += f"   |   Angular acceleration {alpha:+.2f} °/s²"
            lines.append(line)
        landmarks = ANGLE_VERTICES.get(column, ())
        world = self._joint_position(row, landmarks, "world")
        if world is not None:
            lines.append(f"World XYZ (m, hip-relative) {self._format_xyz(world)}")
            previous = self._joint_position(row - 1, landmarks, "world")
            velocity = self._difference(world, previous, row)
            if velocity is not None:
                lines.append(f"Velocity XYZ (m/s) {self._format_xyz(velocity)}   |   Speed {np.linalg.norm(velocity):.3f} m/s")
                previous_velocity = self._difference(previous, self._joint_position(row - 2, landmarks, "world"), row - 1)
                acceleration = self._difference(velocity, previous_velocity, row)
                if acceleration is not None:
                    lines.append(f"Acceleration XYZ (m/s²) {self._format_xyz(acceleration)}")
        else:
            image = self._joint_position(row, landmarks, "lm")
            if image is not None:
                lines.append(f"Image landmark XYZ (normalized) {self._format_xyz(image)}")
        return "\n".join(lines)

    def _on_click(self, event) -> None:
        if event.inaxes is not self.axis or event.xdata is None:
            return
        if self.toolbar.mode:
            if self._link_video and event.button in (1, 3):
                self._viewport_seek.stop()
                self._drag_xlim = self.axis.get_xlim()
                self.navigationStarted.emit()
            return
        if event.button == 1:
            self._viewport_seek.stop()
            self._seek_timestamp(event.xdata)

    def _seek_timestamp(self, time: float) -> None:
        if not self.frame_column or not len(self._ordered_times):
            return
        index = int(self._ordered_times.searchsorted(time))
        candidates = self._time_rows[max(0, index - 1):index + 1]
        nearest = candidates[np.argmin(np.abs(self._times[candidates] - time))]
        if np.isfinite(self._frame_ids[nearest]):
            self.frameSelected.emit(int(self._frame_ids[nearest]))
