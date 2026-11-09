"""Timestamp-aware joint-angle graphs shared by the desktop workspaces."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from html import escape
import logging
from math import ceil
from threading import Lock
from time import monotonic

import numpy as np
import pandas as pd
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QSignalBlocker, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib import colormaps
from matplotlib.colors import to_hex
from matplotlib.gridspec import GridSpecBase
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator

from aihumo.features import (
    ANGLE_VERTICES, CROSS_MEAN_PREFIX, LEGACY_ANGLE_PREFIX, MEAN_ANGLE_PREFIX,
    REVIEW_DISTANCE_TARGETS, REVIEW_LANDMARKS, REVIEW_PREFIX, TIME_COLUMNS, TORSO_ANGLE_PREFIX,
    VIEWER_FEATURE_PREFIX, WORLD_ANGLE_PREFIX, angle_family,
)

from .angle_overlay import OverlayTrace, angle_name
from .graph_navigation import FrameZoomToolbar, centered_time_limits, wheel_zoom_factor, zoom_to_seek_button

TORSO_SOURCE = "Torso-normalized 2D"
WORLD_SOURCE = "Estimated world (3D)"
SAVED_SOURCE = "Legacy (normalized image)"
MEAN_SOURCE = "Mean of three sources"
ANGLE_MODE = "Joint angles"
LANDMARK_MODE = "Landmark movement"
DISTANCE_MODE = "Landmarks Distances"
ALL_GRAPHS_MODE = "Show All Graphs"
GRAPH_MODES = (ANGLE_MODE, LANDMARK_MODE, DISTANCE_MODE, ALL_GRAPHS_MODE)
MOTION_SOURCES = {TORSO_SOURCE: ("torso2d", "torso lengths"), WORLD_SOURCE: ("world", "m"),
                  SAVED_SOURCE: ("legacy", "normalized image units"), MEAN_SOURCE: ("cross_mean", "torso lengths")}
POSITION_STYLES = {"x": "-", "y": "--", "z": ":"}
ANGLE_SOURCES = {
    TORSO_SOURCE: TORSO_ANGLE_PREFIX,
    WORLD_SOURCE: WORLD_ANGLE_PREFIX,
    SAVED_SOURCE: LEGACY_ANGLE_PREFIX,
}
ANGLE_AXIS_LABELS = {
    TORSO_SOURCE: "Torso-normalized angle (°)",
    WORLD_SOURCE: "Estimated 3D angle (°)",
    SAVED_SOURCE: "Legacy angle (°)",
    MEAN_SOURCE: "Mean angle (°)",
}


def graph_angle_traces(columns: Iterable[str]) -> dict[str, tuple[OverlayTrace, ...]]:
    """Describe the graph's traces in source preference order without opening it."""
    columns = tuple(columns)
    sources = {}
    for source, prefix in ANGLE_SOURCES.items():
        family = angle_family(columns, prefix)
        if family:
            sources[source] = {f"{LEGACY_ANGLE_PREFIX}{joint}": column for joint, column in family.items()}
    for prefix in (CROSS_MEAN_PREFIX, MEAN_ANGLE_PREFIX):
        means = {column.removeprefix(prefix): column for column in columns
                 if column.startswith(f"{prefix}angle_") and not column.endswith("_source_count")}
        if means:
            sources[MEAN_SOURCE] = means
            break

    joints = sorted({joint for family in sources.values() for joint in family})
    colors = colormaps["tab20"].colors
    palette = colors[::2] + colors[1::2]
    trace_colors = {joint: to_hex(palette[index % len(palette)]) for index, joint in enumerate(joints)}
    return {
        source: tuple(OverlayTrace(joint, column, trace_colors[joint]) for joint, column in family.items())
        for source, family in sources.items()
    }


@dataclass(frozen=True)
class GraphAngleSelection:
    source: str
    checked: frozenset[str]


@dataclass
class _AnglePanel:
    axis: Axes
    source: str
    values: dict[str, np.ndarray]
    kind: str
    component: str = ""
    compact: bool = False
    time_axis: str = "full"
    lines: dict[str, Line2D] = field(default_factory=dict)
    cursor: Line2D | None = None
    sample_dot: Line2D | None = None


@dataclass
class _TraceWindow:
    limits: tuple[float, float]
    samples: int
    times: np.ndarray
    values: dict[Axes, dict[str, np.ndarray]]
    y_bounds: dict[tuple[str, str, str], tuple[float, float]]


@dataclass(frozen=True)
class _PanelImage:
    position: tuple[float, float, float, float]
    title: str
    ylabel: str
    ylim: tuple[float, float]
    message: str
    traces: tuple[tuple[str, str, np.ndarray], ...]
    compact: bool
    time_axis: str
    position_axes: str
    time_label: str


_PLOT_RENDERER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="AIHuMo graph prefetch")
_PLOT_RENDER_SLOT = Lock()
_TRACE_STYLE = dict(linewidth=1.0, markersize=3.0, markeredgewidth=0.0)
_DIVIDER_COLOR = "#a9b3bf"
_PANEL_DIVIDER_WIDTH = 0.7
_GROUP_DIVIDER_WIDTH = 1.7


def _style_panel(axis: Axes, title: str, ylabel: str, compact: bool, time_axis: str, position_axes: str = "",
                 time_label: str = "Elapsed source time (s)") -> None:
    axis.grid(True, alpha=0.25)
    font = 9 if compact else None
    axis.set_title(title, fontsize=font)
    axis.set_ylabel(ylabel, fontsize=8 if compact else None)
    axis.tick_params(axis="x", labelbottom=time_axis != "hidden")
    if time_axis == "full":
        axis.set_xlabel(time_label, fontsize=font)
    if compact:
        axis.tick_params(labelsize=8)
        axis.xaxis.set_major_locator(MaxNLocator(nbins=4))
        axis.yaxis.set_major_locator(MaxNLocator(nbins=4))
    if position_axes:
        handles = [Line2D([], [], color="#404040", linestyle=POSITION_STYLES[key], label=key.upper())
                   for key in position_axes]
        axis.legend(handles=handles, loc="upper right", ncols=len(handles), fontsize=7, framealpha=0.9)


def _plot_divider(figure: Figure, x, y, width: float) -> Line2D:
    return figure.add_artist(Line2D(x, y, transform=figure.transFigure,
                                    color=_DIVIDER_COLOR, linewidth=width))


def _frame_details_html(title, angle_lines, motion_lines, distance_lines) -> str:
    sections = (("Joint angles", angle_lines, 24), ("Landmark movement", motion_lines, 53),
                ("Landmark distances", distance_lines, 23))
    cells = []
    for index, (name, lines, width) in enumerate(sections):
        divider = f"border-left: 1px solid {_DIVIDER_COLOR}; padding-left: 7px;" if index else ""
        body = "<br>".join(map(escape, lines))
        cells.append(f'<td width="{width}%" valign="top" style="{divider} padding-right: 5px;">'
                     f'<b>{name}</b><br>{body}</td>')
    return f'<b>{escape(title)}</b><table width="100%" style="border-collapse: collapse;"><tr>{"".join(cells)}</tr></table>'


# Size the readout for its longest headings, units, and formatted values
# instead of letting the current sample resize the plot on each hover.
_FRAME_DETAILS_RESERVATION = _frame_details_html(
    "Frame Details · Legacy (normalized image) | Video frame 999999 (hovered sample) | Source time 99999.999999 s",
    ("Hip Midpoint | Angle unavailable | Valid sources: 3/3",
     "Angular velocity +99999.99 °/s", "Angular acceleration -99999.99 °/s²"),
    ("Right shoulder | XYZ position (normalized image units): -99999.9999",
     "Position XYZ (normalized image units) (-99999.999, -99999.999, -99999.999)",
     "Velocity (normalized image units/s) (-99999.999, -99999.999, -99999.999)",
     "Acceleration (normalized image units/s²) (-99999.999, -99999.999, -99999.999)",
     "Speed 99999.999 normalized image units/s"),
    ("Right shoulder to wrist", "Distance (normalized image units): 99999.9999",
     "Distance rate (normalized image units/s): -99999.9999",
     "Distance acceleration (normalized image units/s²): -99999.9999"),
)


def _draw_window_image(size, dpi, facecolor, limits, times, panels, marker, dividers):
    # The worker owns this entire Agg figure. Only its finished pixels leave
    # the worker, and the live Qt canvas and artists stay on the main thread.
    figure = Figure(figsize=size, dpi=dpi, facecolor=facecolor)
    canvas = FigureCanvasAgg(figure)
    for x, y, width in dividers:
        _plot_divider(figure, x, y, width)
    for panel in panels:
        axis = figure.add_axes(panel.position)
        _style_panel(axis, panel.title, panel.ylabel, panel.compact, panel.time_axis, panel.position_axes, panel.time_label)
        axis.set_xlim(*limits)
        axis.set_ylim(*panel.ylim)
        if panel.message:
            axis.text(0.5, 0.5, panel.message, transform=axis.transAxes, ha="center", va="center",
                      fontsize=9, wrap=True)
        for color, linestyle, values in panel.traces:
            axis.plot(times, values, color=color, linestyle=linestyle, marker=marker, **_TRACE_STYLE)
    try:
        canvas.draw()
        return canvas.copy_from_bbox(figure.bbox)
    finally:
        figure.clear()


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

    def __init__(self, dataframe: pd.DataFrame, parent=None, *, link_video: bool = False,
                 timeline: np.ndarray | None = None, time_bounds: tuple[float, float] | None = None):
        super().__init__(parent)
        # The frame table belongs to the caller. This widget only reads it.
        self.dataframe = dataframe
        self._disposed = False
        self._viewer_values = {
            column: dataframe[column].to_numpy(dtype=float, copy=False)
            for column in dataframe if column.startswith((VIEWER_FEATURE_PREFIX, REVIEW_PREFIX))
        }
        self._trace_window_cache = OrderedDict()
        self._last_hover_at = 0.0
        self.time_column = next((name for name in TIME_COLUMNS if name in dataframe), None)
        self.frame_column = "frame_id" if "frame_id" in dataframe.columns else None
        self._traces_by_source = graph_angle_traces(dataframe.columns)
        self._angle_sources = {
            source: {trace.joint: self._numeric_column(trace.column) for trace in traces}
            for source, traces in self._traces_by_source.items()
        }
        self._trace_colors = {
            trace.joint: trace.color for traces in self._traces_by_source.values() for trace in traces
        }
        self.angle_columns = sorted(self._trace_colors)
        self._graph_mode = ANGLE_MODE
        self._angle_source_before_motion = next(iter(self._angle_sources), "")
        self._legend_rows = {}
        self._metric_labels = {f"landmark_{index}": name for index, name in REVIEW_LANDMARKS.items()}
        self._metric_labels.update({f"distance_{name}": name.replace("_", " ").capitalize() for name in REVIEW_DISTANCE_TARGETS})
        self._trace_configurations = {
            ANGLE_MODE: self.angle_columns,
            LANDMARK_MODE: tuple(f"landmark_{index}" for index in REVIEW_LANDMARKS),
            DISTANCE_MODE: tuple(f"distance_{name}" for name in REVIEW_DISTANCE_TARGETS),
        }
        palette = colormaps["tab20"].colors
        self._trace_colors.update({key: to_hex(palette[index % len(palette)]) for index, key in enumerate(self._metric_labels)})
        self._source_times = self._numeric_column(self.time_column) if self.time_column else np.array([])
        self._times = self._source_times if timeline is None else timeline
        self._time_label = "Elapsed source time (s)" if timeline is None else "Session time (s)"
        self._frame_ids = self._numeric_column(self.frame_column) if self.frame_column else np.arange(len(dataframe))
        self._native_time_order = bool(
            np.isfinite(self._times).all() and (self._times[1:] >= self._times[:-1]).all()
        )
        if self._native_time_order:
            self._time_rows = np.arange(len(self._times))
            self._ordered_times = self._times
        else:
            self._time_rows = np.flatnonzero(np.isfinite(self._times))
            self._time_rows = self._time_rows[np.argsort(self._times[self._time_rows], kind="stable")]
            self._ordered_times = self._times[self._time_rows]
        self._full_xlim: tuple[float, float] = (0.0, 1.0)
        if len(self._ordered_times):
            low, high = float(self._ordered_times[0]), float(self._ordered_times[-1])
            self._full_xlim = (low, high if high > low else low + 1)
        if time_bounds is not None:
            self._full_xlim = time_bounds
        self._panels: dict[Axes, _AnglePanel] = {}
        self._hover_sample: tuple[Axes, str, int] | None = None
        self._active_row: int | None = None
        self._selected_trace: str | None = None
        self.trace_checks: dict[str, QCheckBox] = {}
        self._last_current_time: float | None = None
        self._last_details_update = float("-inf")
        self._link_video = link_video
        self._following_video = False
        self._drag_xlim = None
        self._source_groups: list[tuple[Axes, Axes]] = []
        self._source_dividers: list[Line2D] = []
        self._panel_dividers: list[tuple[GridSpecBase, Line2D, Line2D]] = []
        self._next_window_limits = None
        self._next_window: _TraceWindow | None = None
        self._window_image: Future | None = None
        self._image_geometry = None
        self._window_prefetch = QTimer(self)
        self._window_prefetch.setSingleShot(True)
        self._window_prefetch.timeout.connect(self._warm_next_window)

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
        zoom_in.setToolTip("Zoom in around the selected frame cursor")
        zoom_in.clicked.connect(lambda: self._scale_x(0.6))
        controls.addWidget(zoom_in)
        zoom_out = QPushButton("−")
        zoom_out.setToolTip("Zoom out around the selected frame cursor")
        zoom_out.clicked.connect(lambda: self._scale_x(1.7))
        controls.addWidget(zoom_out)
        self.zoom_to_seek = zoom_to_seek_button(self)
        if link_video:
            controls.addWidget(self.zoom_to_seek)
        else:
            self.zoom_to_seek.hide()
        controls.addStretch(1)

        detail_controls = QHBoxLayout()
        detail_controls.addWidget(QLabel("Detail window"))
        self.detail_window_label = QLabel("—")
        self.detail_window_label.setToolTip(
            "Start time, end time, and duration of the visible graph window."
        )
        detail_controls.addWidget(self.detail_window_label)
        self.show_points = QCheckBox("Frame points")
        self.show_points.setToolTip("Show individual Parquet samples when the visible window is detailed enough.")
        self.show_points.toggled.connect(self._update_visible_detail)
        detail_controls.addWidget(self.show_points)
        self.auto_y = QCheckBox("Auto-scale Y")
        self.auto_y.setChecked(True)
        self.auto_y.setToolTip("Fit the vertical range to the data currently visible in the time window.")
        self.auto_y.toggled.connect(self._update_visible_detail)
        detail_controls.addWidget(self.auto_y)
        detail_controls.addStretch(1)
        angle_controls = QHBoxLayout()
        self.source_label = QLabel("Source values")
        angle_controls.addWidget(self.source_label)
        self.angle_source = QComboBox()
        self.angle_source.addItems(self._angle_sources)
        self.angle_source.setToolTip(
            "Missing sources or readings can be added with Prepare existing recording."
        )
        self.angle_source.currentTextChanged.connect(self._change_angle_source)
        angle_controls.addWidget(self.angle_source)
        self.show_all_sources = QCheckBox("Show All")
        self.show_all_sources.setToolTip(
            "Compare the saved sources for this view. Source values selects the frame details."
        )
        self.show_all_sources.toggled.connect(self._toggle_all_sources)
        angle_controls.addWidget(self.show_all_sources)
        self.landmark_component = QComboBox()
        for label, value in (("X", "x"), ("Y", "y"), ("Z", "z"), ("All (X, Y)", "positions"),
                             ("Speed", "speed"), ("X, Y + speed", "positions-speed")):
            self.landmark_component.addItem(label, value)
        self.landmark_component.setCurrentIndex(1)
        self.landmark_component.setToolTip("Choose a saved position component or speed for the landmark traces.")
        self.landmark_component.currentTextChanged.connect(lambda _: self._redraw_series())
        self.landmark_component.hide()
        angle_controls.addWidget(self.landmark_component)
        angle_controls.addStretch(1)
        self.point_info = QLabel("Zoom or hover to inspect native frame samples.")
        self.sample_card = QLabel()
        self.sample_card.setTextFormat(Qt.TextFormat.RichText)
        self.sample_card.setWordWrap(True)
        self.sample_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._card_sizing_key = None
        self.sample_card.setFixedHeight(7 * self.sample_card.fontMetrics().lineSpacing() + 14)
        self.sample_card.installEventFilter(self)

        self.figure = Figure(figsize=(9, 3.8))
        self.axis = self.figure.add_subplot(111)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self._plot_background = None
        self.toolbar = FrameZoomToolbar(self.canvas, self, self._scale_x, seek_on_zoom=self._seek_on_zoom)
        self._canvas_connections = [
            self.canvas.mpl_connect(event, callback) for event, callback in (
                ("draw_event", self._cache_plot_background),
                ("resize_event", self._invalidate_plot_background),
                ("scroll_event", self._on_scroll),
                ("button_press_event", self._on_click),
                ("button_release_event", self._on_graph_release),
                ("motion_notify_event", self._on_motion),
                ("axes_leave_event", self._clear_hover),
            )
        ]

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addLayout(detail_controls)
        layout.addLayout(angle_controls)
        missing_sources = [source for source in (TORSO_SOURCE, WORLD_SOURCE, SAVED_SOURCE)
                           if not any(np.isfinite(values).any() for values in self._angle_sources.get(source, {}).values())]
        if missing_sources:
            notice = QLabel(f"Missing saved sources: {', '.join(missing_sources)}. Use Prepare existing recording.")
            notice.setWordWrap(True)
            layout.addWidget(notice)
        layout.addWidget(self.toolbar)
        chart = QHBoxLayout()
        self.chart_scroll = QScrollArea()
        self.chart_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.chart_scroll.setWidgetResizable(True)
        self.chart_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chart_scroll.setWidget(self.canvas)
        self.chart_scroll.verticalScrollBar().valueChanged.connect(self._paint_frame_artists)
        self.canvas.installEventFilter(self)
        chart.addWidget(self.chart_scroll, 1)
        self.trace_legend = self._build_legend()
        chart.addWidget(self.trace_legend)
        layout.addLayout(chart, 1)
        layout.addWidget(self.point_info)
        layout.addWidget(self.sample_card)
        self._redraw_series()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.sample_card and event.type() in (QEvent.Type.Resize, QEvent.Type.FontChange):
            self._reserve_sample_card_height()
        if (watched is self.canvas and event.type() == QEvent.Type.Wheel
                and self._graph_mode == ALL_GRAPHS_MODE and self.show_all_sources.isChecked()
                and not event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)):
            bar = self.chart_scroll.verticalScrollBar()
            pixels = event.pixelDelta().y()
            if pixels:
                bar.setValue(bar.value() - pixels)
            elif event.angleDelta().y():
                QApplication.sendEvent(bar, event)
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def _reserve_sample_card_height(self) -> None:
        font = self.sample_card.font()
        width = self.sample_card.width()
        key = width, font.toString()
        if width <= 14 or key == self._card_sizing_key:
            return
        self._card_sizing_key = key
        document = QTextDocument()
        document.setDefaultFont(font)
        document.setDocumentMargin(0)
        document.setHtml(_FRAME_DETAILS_RESERVATION)
        document.setTextWidth(width - 14)
        self.sample_card.setFixedHeight(ceil(document.size().height()) + 14)

    def _numeric_column(self, column: str) -> np.ndarray:
        return pd.to_numeric(self.dataframe[column], errors="coerce").to_numpy(dtype=float, copy=False)

    def _build_legend(self) -> QGroupBox:
        legend = QGroupBox("Joint traces")
        layout = QVBoxLayout(legend)
        self.trace_configuration = QComboBox()
        self.trace_configuration.setAccessibleName("Trace configuration")
        for label, kind in (("Angles", ANGLE_MODE), ("Landmarks", LANDMARK_MODE), ("Distances", DISTANCE_MODE)):
            self.trace_configuration.addItem(label, kind)
        layout.addWidget(self.trace_configuration)
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
        available = set(self.angle_columns)
        for source in MOTION_SOURCES:
            for kind, component in ((LANDMARK_MODE, "positions"), (LANDMARK_MODE, "speed"), (DISTANCE_MODE, "")):
                available.update(self._trace_key(key) for key in self._plot_values(source, kind, component))
        for column in (*self.angle_columns, *self._metric_labels):
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            swatch = QLabel()
            swatch.setFixedSize(12, 4)
            swatch.setStyleSheet(f"background: {self._trace_colors[column]}")
            row.addWidget(swatch)
            check = QCheckBox(self._display_name(column))
            check.setChecked(True)
            check.setEnabled(column in available)
            check.toggled.connect(lambda checked, column=column: self._refresh_trace_visibility(
                column if checked else None, angles_changed=column in self.angle_columns
            ))
            row.addWidget(check, 1)
            rows.addWidget(container)
            self._legend_rows[column] = container
            self.trace_checks[column] = check
        rows.addStretch(1)
        scroll.setWidget(contents)
        layout.addWidget(scroll)
        self.trace_configuration.currentIndexChanged.connect(self._show_trace_configuration)
        self._show_trace_configuration()
        return legend

    def _show_trace_configuration(self) -> None:
        columns = self._trace_configurations[self.trace_configuration.currentData()]
        for column, row in self._legend_rows.items():
            row.setVisible(column in columns)

    def _set_all_traces(self, visible: bool) -> None:
        kind = self.trace_configuration.currentData()
        for column in self._trace_configurations[kind]:
            check = self.trace_checks[column]
            if check.isEnabled():
                with QSignalBlocker(check):
                    check.setChecked(visible)
        self._refresh_trace_visibility(angles_changed=kind == ANGLE_MODE)

    @staticmethod
    def _trace_key(column: str) -> str:
        return column.split("|", 1)[0]

    def _apply_trace_visibility(self) -> None:
        for panel in self._panels.values():
            for column, line in panel.lines.items():
                key = self._trace_key(column)
                line.set_visible(self.trace_checks[key].isChecked())

    def _refresh_trace_visibility(self, selected: str | None = None, *, angles_changed: bool = True) -> None:
        self.cancel_playback_render()
        self._trace_window_cache.clear()
        if selected is not None:
            self._selected_trace = selected
        self._apply_trace_visibility()
        self._hover_sample = None
        self._show_current_sample()
        self._update_visible_detail()
        if angles_changed:
            self.traceSelectionChanged.emit()

    @staticmethod
    def _motion_axes(source: str) -> str:
        return "xyz" if source in (WORLD_SOURCE, SAVED_SOURCE) else "xy"

    def _update_component_options(self) -> None:
        show_depth = self.show_all_sources.isChecked() or "z" in self._motion_axes(self.angle_source.currentText())
        axes = "X, Y, Z" if show_depth else "X, Y"
        with QSignalBlocker(self.landmark_component):
            self.landmark_component.model().item(self.landmark_component.findData("z")).setEnabled(show_depth)
            self.landmark_component.setItemText(self.landmark_component.findData("positions"), f"All ({axes})")
            self.landmark_component.setItemText(self.landmark_component.findData("positions-speed"), f"{axes} + speed")
            if not show_depth and self.landmark_component.currentData() == "z":
                self.landmark_component.setCurrentIndex(self.landmark_component.findData("y"))

    def _change_angle_source(self, source: str) -> None:
        if self._graph_mode in (ANGLE_MODE, ALL_GRAPHS_MODE) and source in self._angle_sources:
            self._angle_source_before_motion = source
        self._update_component_options()
        if self.show_all_sources.isChecked():
            self._hover_sample = None
            self._show_current_sample()
            self._paint_frame_artists()
        else:
            self._redraw_series()
        self.traceSelectionChanged.emit()

    def set_graph_mode(self, mode: str, *, redraw: bool = True) -> None:
        if mode == self._graph_mode:
            return
        previous_source = self.angle_source.currentText()
        self._graph_mode = mode
        if mode in self._trace_configurations:
            self.trace_configuration.setCurrentIndex(self.trace_configuration.findData(mode))
        self.landmark_component.setVisible(mode in (LANDMARK_MODE, ALL_GRAPHS_MODE))
        options = list(self._angle_sources) if mode == ANGLE_MODE else list(MOTION_SOURCES)
        selected = self._angle_source_before_motion if mode == ANGLE_MODE else previous_source
        with QSignalBlocker(self.angle_source):
            self.angle_source.clear()
            self.angle_source.addItems(options)
            if selected in options:
                self.angle_source.setCurrentText(selected)
        self._update_component_options()
        if redraw:
            self._redraw_series()
            self.traceSelectionChanged.emit()

    def copy_view_from(self, other: JointGraphWidget) -> None:
        def plot_options():
            return (self._graph_mode, self.angle_source.currentText(), self.show_all_sources.isChecked(),
                    self.show_points.isChecked(), self.auto_y.isChecked(), self.landmark_component.currentData(),
                    tuple(checkbox.isChecked() for checkbox in self.trace_checks.values()))

        previous_options = plot_options()
        self.set_graph_mode(other._graph_mode, redraw=False)
        with QSignalBlocker(self.angle_source), QSignalBlocker(self.show_all_sources), QSignalBlocker(self.show_points), \
                QSignalBlocker(self.auto_y), QSignalBlocker(self.landmark_component):
            source = other.angle_source.currentText()
            if self.angle_source.findText(source) >= 0:
                self.angle_source.setCurrentText(source)
            if other._angle_source_before_motion in self._angle_sources:
                self._angle_source_before_motion = other._angle_source_before_motion
            self.show_all_sources.setChecked(other.show_all_sources.isChecked())
            self.show_points.setChecked(other.show_points.isChecked())
            self.auto_y.setChecked(other.auto_y.isChecked())
            self.landmark_component.setCurrentIndex(self.landmark_component.findData(other.landmark_component.currentData()))
        for key, checkbox in self.trace_checks.items():
            if key in other.trace_checks and other.trace_checks[key].isEnabled() and checkbox.isEnabled():
                with QSignalBlocker(checkbox):
                    checkbox.setChecked(other.trace_checks[key].isChecked())
        self._selected_trace = other._selected_trace
        self.trace_configuration.setCurrentIndex(self.trace_configuration.findData(other.trace_configuration.currentData()))
        self._update_component_options()
        left, right = other.axis.get_xlim()
        low, high = self._full_xlim
        limits = max(left, low), min(right, high)
        if limits[0] >= limits[1]:
            limits = self._full_xlim
        if previous_options != plot_options():
            self._redraw_series(limits)
        elif self.axis.get_xlim() != limits:
            self.axis.set_xlim(*limits)

    def _plot_values(self, source: str, kind: str, component: str) -> dict[str, np.ndarray]:
        if kind == ANGLE_MODE:
            return self._angle_sources.get(source, {})
        space = MOTION_SOURCES.get(source, ("", ""))[0]
        if kind == LANDMARK_MODE:
            axes = self._motion_axes(source)
            suffixes = axes if component == "positions" else (component,)
            if component == "z" and "z" not in axes:
                return {}
            names = {
                f"landmark_{index}|{suffix}" if component == "positions" else f"landmark_{index}":
                f"review_{space}_lm{index}_{suffix}"
                for index in REVIEW_LANDMARKS for suffix in suffixes
            }
        else:
            names = {f"distance_{name}": f"review_{space}_distance_{name}" for name in REVIEW_DISTANCE_TARGETS}
        return {key: self._viewer_values[name] for key, name in names.items() if name in self._viewer_values}

    def _toggle_all_sources(self, checked: bool) -> None:
        self._update_component_options()
        self._redraw_series()

    def angle_selection(self) -> GraphAngleSelection:
        return GraphAngleSelection(
            self._angle_source_before_motion,
            frozenset(joint for joint in self.angle_columns if self.trace_checks[joint].isChecked()),
        )

    def restore_angle_selection(self, selection: GraphAngleSelection) -> None:
        for joint in self.angle_columns:
            check = self.trace_checks[joint]
            with QSignalBlocker(check):
                check.setChecked(joint in selection.checked)
        if selection.source in self._angle_sources and selection.source != self.angle_source.currentText():
            self.angle_source.setCurrentText(selection.source)
            if not self.show_all_sources.isChecked():
                return
        self._refresh_trace_visibility()

    def overlay_traces(self) -> tuple[OverlayTrace, ...]:
        return tuple(
            trace for trace in self._traces_by_source.get(self._angle_source_before_motion, ())
            if self.trace_checks[trace.joint].isChecked()
        )

    def _rows_between(self, low: float, high: float) -> np.ndarray:
        start = self._ordered_times.searchsorted(low, side="left")
        stop = self._ordered_times.searchsorted(high, side="right")
        return self._time_rows[start:stop]

    def _display_name(self, column: str) -> str:
        if column in self._metric_labels:
            return self._metric_labels[column]
        if column == "angle_torso_nose_shoulder_hip":
            return "Neck at Shoulder Midpoint"
        return angle_name(column)

    def _redraw_series(self, xlim: tuple[float, float] | None = None) -> None:
        if self._disposed:
            return
        self.cancel_playback_render()
        self._trace_window_cache.clear()
        self._drag_xlim = None
        if xlim is None:
            xlim = self.axis.get_xlim() if self._panels else self._full_xlim
        self.figure.clear()
        self._panels.clear()
        self._source_groups.clear()
        self._source_dividers.clear()
        self._panel_dividers.clear()
        self._hover_sample = None
        compare = self.show_all_sources.isChecked()
        all_graphs = self._graph_mode == ALL_GRAPHS_MODE
        selected_source = self.angle_source.currentText()
        sources = tuple(MOTION_SOURCES) if compare else (selected_source,)
        self.trace_legend.setHidden(compare or all_graphs)
        component = self.landmark_component.currentData()
        grouped_height = 485 if component == "positions-speed" else 382
        gap_space = 92 * (len(sources) - 1)
        scroll_groups = all_graphs and compare
        self.chart_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if scroll_groups else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.chart_scroll.setToolTip(
            ("Scroll through source groups. Shift+scroll zooms. "
             "Turn on Zoom to Seek to move the playhead when zooming.")
            if scroll_groups else "Scroll to zoom. Turn on Zoom to Seek to move the playhead when zooming."
        )
        self.canvas.setMinimumHeight(grouped_height * len(sources) + gap_space if scroll_groups else 0)

        def add_panel(slot, source, kind, title, compact, time_axis="full"):
            if kind == LANDMARK_MODE and component == "positions-speed":
                split = slot.subgridspec(2, 1, height_ratios=(2, 1), hspace=0.20)
                entries = ((split[0], "positions", title, "hidden"), (split[1], "speed", "", time_axis))
            else:
                entries = ((slot, component if kind == LANDMARK_MODE else "", title, time_axis),)
            for cell, part, heading, time_labels in entries:
                axis = self.figure.add_subplot(cell)
                values = self._plot_values(source, kind, part)
                panel = _AnglePanel(axis, source, values, kind, part, compact, time_labels)
                self._draw_panel(panel, xlim, heading)
                axis.callbacks.connect("xlim_changed", self._on_xlim_changed)

        if all_graphs:
            groups = self.figure.add_gridspec(len(sources), 1, hspace=0.35)
            for i, source in enumerate(sources):
                grid = groups[i].subgridspec(2, 2, wspace=0.52, hspace=0.78)
                heading = f"{source}\n{ANGLE_MODE}" if compare else ANGLE_MODE
                add_panel(grid[0, 0], source, ANGLE_MODE, heading, True)
                top_axis = self.figure.axes[-1]
                add_panel(grid[0, 1], source, LANDMARK_MODE, LANDMARK_MODE, True)
                add_panel(grid[1, 0], source, DISTANCE_MODE, DISTANCE_MODE, True)
                self._source_groups.append((top_axis, self.figure.axes[-1]))
                self._add_panel_dividers(grid, _PANEL_DIVIDER_WIDTH if compare else _GROUP_DIVIDER_WIDTH)
            self._source_dividers = [
                _plot_divider(self.figure, [0.04, 0.96], [0, 0], _GROUP_DIVIDER_WIDTH) for _ in sources[1:]
            ]
        elif compare:
            grid = self.figure.add_gridspec(2, 2)
            for i, source in enumerate(sources):
                row, col = divmod(i, 2)
                add_panel(grid[row, col], source, self._graph_mode, source, True, "ticks" if row == 0 else "full")
            self._add_panel_dividers(grid, _GROUP_DIVIDER_WIDTH)
        else:
            grid = self.figure.add_gridspec(1, 1)
            add_panel(grid[0], selected_source, self._graph_mode, f"AIHuMo — {self._graph_mode}", False)
        self.axis = next(iter(self._panels))
        self._adjust_plot_margins()
        self._apply_trace_visibility()
        self.toolbar.update()
        self._show_current_sample()
        self._update_visible_detail()

    def _add_panel_dividers(self, grid: GridSpecBase, width: float) -> None:
        horizontal = _plot_divider(self.figure, [], [], width)
        vertical = _plot_divider(self.figure, [], [], width)
        self._panel_dividers.append((grid, horizontal, vertical))

    def _adjust_plot_margins(self) -> None:
        width = max(1, self.canvas.width())
        height = max(1, self.canvas.height())
        top_space = 54 if len(self.figure.axes) > 1 else 38
        self.figure.subplots_adjust(
            left=min(0.29, max(0.11, 72 / width)), right=0.96,
            bottom=min(0.24, 45 / height), top=1 - min(0.22, top_space / height),
            wspace=0.52, hspace=0.78,
        )
        for line, (_, above), (below, _) in zip(self._source_dividers, self._source_groups, self._source_groups[1:]):
            y = (above.get_position().y0 + below.get_position().y1) / 2
            line.set_ydata([y, y])
        for grid, horizontal, vertical in self._panel_dividers:
            top_left = grid[0, 0].get_position(self.figure)
            top_right = grid[0, 1].get_position(self.figure)
            bottom_left = grid[1, 0].get_position(self.figure)
            # Leave space for right-hand Y labels and any upper-row time caption.
            x = top_left.x1 + (top_right.x0 - top_left.x1) / 3
            gutter = 3 if self._graph_mode == ALL_GRAPHS_MODE else 2
            y = bottom_left.y1 + (top_left.y0 - bottom_left.y1) / gutter
            horizontal.set_data([0.04, 0.96], [y, y])
            vertical.set_data([x, x], [bottom_left.y0, top_left.y1])

    @property
    def _lines(self) -> dict[str, Line2D]:
        return self._panels[self.axis].lines

    @property
    def _cursor(self) -> Line2D | None:
        return self._panels[self.axis].cursor

    @property
    def _hover_dot(self) -> Line2D | None:
        return self._panels[self.axis].sample_dot

    def _draw_panel(self, panel: _AnglePanel, xlim: tuple[float, float], title: str) -> None:
        axis = panel.axis
        self._panels[axis] = panel
        position_axes = self._motion_axes(panel.source) if panel.component == "positions" and panel.values else ""
        _style_panel(axis, title, self._axis_label(panel), panel.compact, panel.time_axis, position_axes, self._time_label)
        if panel.kind == ANGLE_MODE:
            axis.set_ylim(0, 180)
        axis.set_xlim(*xlim)
        if not any(np.isfinite(values).any() for values in panel.values.values()):
            message = "No saved comparison samples" if panel.source == MEAN_SOURCE else "Saved source unavailable"
            axis.text(0.5, 0.5, message, transform=axis.transAxes, ha="center", va="center", fontsize=9, wrap=True)
        for column in panel.values:
            key, _, component = column.partition("|")
            line, = axis.plot(
                [], [], label=self._display_name(key), color=self._trace_colors[key],
                linestyle=POSITION_STYLES.get(component, "-"),
                marker="o", **_TRACE_STYLE,
            )
            panel.lines[column] = line
        cursor_time = self._last_current_time
        if cursor_time is None:
            cursor_time = self._full_xlim[0]
        panel.cursor = axis.axvline(cursor_time, color="#20c55a", linewidth=1.5, alpha=0.9, animated=True)
        panel.sample_dot, = axis.plot([], [], "o", markersize=8, markerfacecolor="white",
                                      markeredgewidth=2, zorder=10, visible=False, animated=True)

    def _draw_frame_artists(self, visible_y=None) -> None:
        for panel in self._panels.values():
            if visible_y is not None and (panel.axis.bbox.ymax < visible_y[0] or panel.axis.bbox.ymin > visible_y[1]):
                continue
            for artist in (panel.cursor, panel.sample_dot):
                if artist is not None and artist.get_visible():
                    panel.axis.draw_artist(artist)

    def _cache_plot_background(self, _event) -> None:
        if not self.canvas.is_saving():
            self._plot_background = self.canvas.copy_from_bbox(self.figure.bbox)
            self._draw_frame_artists()

    def _invalidate_plot_background(self, _event=None) -> None:
        self._plot_background = None
        self.cancel_playback_render()
        self._adjust_plot_margins()

    def _paint_frame_artists(self) -> None:
        if self._disposed or not self.canvas.isVisible() or self.window().isMinimized():
            return
        if self._plot_background is None:
            self.canvas.draw_idle()
            return
        visible = self.canvas.visibleRegion().boundingRect()
        if visible.isEmpty():
            return
        if visible == self.canvas.rect():
            self.canvas.restore_region(self._plot_background)
            self._draw_frame_artists()
        else:
            # Qt and the saved Agg pixel region both use top-origin rows.
            dpr = self.canvas.device_pixel_ratio
            background = np.asarray(self._plot_background)
            pixels = np.asarray(self.canvas.get_renderer().buffer_rgba())
            if pixels.shape != background.shape:
                self.canvas.draw_idle()
                return
            height, width = background.shape[:2]
            left, top = int(visible.x() * dpr), int(visible.y() * dpr)
            right = min(width, ceil((visible.x() + visible.width()) * dpr))
            bottom = min(height, ceil((visible.y() + visible.height()) * dpr))
            if right <= left or bottom <= top:
                return
            pixels[top:bottom, left:right] = background[top:bottom, left:right]
            self._draw_frame_artists((height - bottom, height - top))
        self.canvas.update(visible)

    def set_current_frame(self, frame: int, *, playing: bool = False) -> None:
        if self._disposed or self._cursor is None or self.dataframe.empty or not self.time_column:
            return
        index = int(np.clip(frame, 0, len(self.dataframe) - 1))
        if self.frame_column and self._frame_ids[index] != frame:
            first = self._frame_ids[0]
            relative = frame - int(first) if np.isfinite(first) else -1
            if 0 <= relative < len(self._frame_ids) and self._frame_ids[relative] == frame:
                index = relative
            else:
                matches = np.flatnonzero(self._frame_ids == frame)
                if len(matches):
                    index = int(matches[0])
        if not np.isfinite(self._times[index]):
            return
        current_time = float(self._times[index])
        if self._active_row != index:
            self._hover_sample = None
        self._active_row = index
        self._last_current_time = current_time
        for panel in self._panels.values():
            panel.cursor.set_xdata([current_time, current_time])
        if self._link_video:
            self.linked_frame_label.setText(f"Frame {frame:,} | {current_time:.6f} s")
        if not playing:
            self.cancel_playback_render()
        if self._link_video or self.follow_frame.isChecked():
            low, high = self.axis.get_xlim()
            width = high - low
            outside = not low <= current_time <= high
            next_limits = self._playback_window(low, high) if playing and width > 0 else None
            if next_limits is not None and high - current_time <= min(3.0, width):
                render_ahead = self._can_render_ahead()
                if current_time > next_limits[1]:
                    if render_ahead and self._window_image is not None:
                        next_limits = self._next_window_limits
                    else:
                        next_limits = self._centered_limits(current_time + width * 0.4, width)
                needs_image = render_ahead and not self._window_prefetch.isActive() and (
                    self._window_image is None or (outside and self._image_geometry != self._plot_geometry())
                )
                if self._next_window_limits != next_limits or (needs_image and self._window_image is not None):
                    self.cancel_playback_render()
                    self._next_window_limits = next_limits
                    self._window_prefetch.start(0)
                elif needs_image:
                    self._window_prefetch.start(0)
            if width > 0 and outside:
                # Following playback changes the viewport, but is never a
                # request to seek the video back to the viewport center.
                self._following_video = True
                try:
                    if next_limits is None:
                        self._set_xlim_centered(current_time, width)
                    elif not render_ahead or (self._window_image is not None and self._window_image.done()):
                        self.axis.set_xlim(*next_limits)
                    # If the image is still rendering, video playback continues
                    # and the next timer tick can install the completed image.
                finally:
                    self._following_video = False
        now = monotonic()
        if self._hover_sample is None and (
                not playing or (self.canvas.isVisible() and not self.window().isMinimized()
                                and now - self._last_details_update >= 0.1)):
            self._last_details_update = now
            self._show_current_sample()
        self._paint_frame_artists()

    def _playback_window(self, low: float, high: float) -> tuple[float, float] | None:
        if high >= self._full_xlim[1]:
            return None
        width = high - low
        end = min(self._full_xlim[1], high + width * 0.9)
        return end - width, end

    def cancel_playback_render(self) -> None:
        self._window_prefetch.stop()
        self._next_window_limits = None
        self._next_window = None
        self._image_geometry = None
        if self._window_image is not None:
            self._window_image.cancel()
            self._window_image = None

    def finish_playback(self) -> None:
        if self._active_row is not None:
            self.set_current_frame(int(self._frame_ids[self._active_row]))
        else:
            self.cancel_playback_render()

    def release_render_cache(self) -> None:
        self.cancel_playback_render()
        self._plot_background = None

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._hover_sample = None
        for connection in self._canvas_connections:
            self.canvas.mpl_disconnect(connection)
        self._canvas_connections.clear()
        self.release_render_cache()
        self.figure.clear()
        self._panels.clear()
        self._source_groups.clear()
        self._source_dividers.clear()
        self._panel_dividers.clear()
        self._angle_sources.clear()
        self._viewer_values.clear()
        self._trace_window_cache.clear()
        self.dataframe = pd.DataFrame()
        self._times = self._source_times = self._ordered_times = self._frame_ids = np.array([])

    def _can_render_ahead(self) -> bool:
        return (
            self._link_video and self.canvas.isVisible() and not self.window().isMinimized()
            and self._plot_background is not None
            and all(axis.get_xscale() == axis.get_yscale() == "linear" for axis in self._panels)
        )

    def _plot_geometry(self):
        return (
            tuple(self.figure.get_size_inches()), self.figure.dpi,
            tuple(axis.get_position().bounds for axis in self._panels),
            tuple(axis.get_ylim() for axis in self._panels) if not self.auto_y.isChecked() else (),
        )

    def _warm_next_window(self) -> None:
        if self._next_window_limits is not None:
            if self._next_window is None:
                self._next_window = self._prepare_trace_window(self._next_window_limits)
            window = self._next_window
            if not self._can_render_ahead():
                return
            self._image_geometry = self._plot_geometry()
            size, dpi, positions, _ = self._image_geometry
            panels = tuple(
                _PanelImage(
                    position, axis.get_title(), axis.get_ylabel(),
                    (self._window_y_limits(window, panel) or axis.get_ylim()) if self.auto_y.isChecked() else axis.get_ylim(),
                    axis.texts[0].get_text() if axis.texts else "",
                    tuple((line.get_color(), line.get_linestyle(), window.values[axis][column])
                          for column, line in panel.lines.items() if line.get_visible()),
                    panel.compact, panel.time_axis,
                    self._motion_axes(panel.source) if panel.component == "positions" and panel.values else "",
                    self._time_label,
                )
                for (axis, panel), position in zip(self._panels.items(), positions)
            )
            if not _PLOT_RENDER_SLOT.acquire(blocking=False):
                return
            try:
                self._window_image = _PLOT_RENDERER.submit(
                    _draw_window_image, size, dpi, self.figure.get_facecolor(), window.limits,
                    window.times, panels, self._window_marker(window),
                    tuple((line.get_xdata(), line.get_ydata(), line.get_linewidth())
                          for line in self.figure.artists if isinstance(line, Line2D)),
                )
            except BaseException:
                _PLOT_RENDER_SLOT.release()
                raise
            self._window_image.add_done_callback(lambda _: _PLOT_RENDER_SLOT.release())

    def _prepare_trace_window(self, limits: tuple[float, float]) -> _TraceWindow:
        visibility = tuple(
            (panel.source, panel.kind, panel.component,
             tuple(column for column, line in panel.lines.items() if line.get_visible()))
            for panel in self._panels.values()
        )
        key = (tuple(float(value) for value in limits), visibility)
        cached = self._trace_window_cache.get(key)
        if cached is not None:
            self._trace_window_cache.move_to_end(key)
            return cached
        start = self._ordered_times.searchsorted(limits[0], side="left")
        stop = self._ordered_times.searchsorted(limits[1], side="right")
        # Include one neighboring sample for lines that cross the view edges.
        rows = slice(start, stop)
        drawing_rows = slice(max(0, start - 1), stop + 1)
        if not self._native_time_order:
            rows = self._time_rows[rows]
            drawing_rows = self._time_rows[drawing_rows]
        slices = {}
        bounds = {}
        for axis, panel in self._panels.items():
            slices[axis] = {column: panel.values[column][drawing_rows] for column in panel.lines}
            for column, line in panel.lines.items():
                if line.get_visible() and stop > start:
                    values = panel.values[column][rows]
                    finite = values[np.isfinite(values)]
                    if len(finite):
                        key = self._scale_group(panel)
                        low, high = bounds.get(key, (np.inf, -np.inf))
                        bounds[key] = (min(low, float(finite.min())), max(high, float(finite.max())))
        result = _TraceWindow(limits, stop - start, self._times[drawing_rows], slices, bounds)
        self._trace_window_cache[key] = result
        while len(self._trace_window_cache) > 6:
            self._trace_window_cache.popitem(last=False)
        return result

    def _centered_limits(self, center: float, width: float) -> tuple[float, float]:
        return centered_time_limits(self._full_xlim, center, width)

    def _set_xlim_centered(self, center: float, width: float) -> None:
        limits = self._centered_limits(center, width)
        if limits != self.axis.get_xlim():
            self.axis.set_xlim(*limits)

    def reset_zoom(self) -> None:
        self.axis.set_xlim(*self._full_xlim)

    def _scale_x(self, factor: float) -> None:
        low, high = self.axis.get_xlim()
        center = self._last_current_time if self._last_current_time is not None else (low + high) / 2.0
        if self._full_xlim[1] > self._full_xlim[0]:
            self._set_xlim_centered(center, (high - low) * factor)

    def _on_scroll(self, event) -> None:
        if event.inaxes not in self._panels or event.xdata is None:
            return
        self._drag_xlim = None
        factor = wheel_zoom_factor(event)
        if factor == 1:
            return
        self._seek_on_zoom(event.xdata)
        self._scale_x(factor)

    def _seek_on_zoom(self, time):
        if self._link_video and self.zoom_to_seek.isChecked():
            self._seek_timestamp(time)

    def _on_xlim_changed(self, axis: Axes) -> None:
        if self._disposed:
            return
        xlim = axis.get_xlim()
        # Keep one time range regardless of which panel the toolbar moves.
        for other in self._panels:
            if other is not axis and other.get_xlim() != xlim:
                other.set_xlim(*xlim, emit=False)
        self._hover_sample = None
        if not self._following_video:
            self._show_current_sample()
        self._update_visible_detail()

    def _on_graph_release(self, event) -> None:
        if self._drag_xlim is None:
            return
        previous, self._drag_xlim = self._drag_xlim, None
        current = self.axis.get_xlim()
        if current != previous and getattr(self.toolbar.mode, "name", "") == "PAN" and event.button == 1:
            self._seek_timestamp(sum(current) / 2)

    def _update_visible_detail(self) -> None:
        """Update the time readout, point markers, and Y scale for the visible window."""
        if not self.time_column or self.dataframe.empty:
            return
        low, high = self.axis.get_xlim()
        duration = high - low
        self.detail_window_label.setText(f"{low:.3f}–{high:.3f} s ({duration:.3f} s visible)")
        limits = (low, high)
        window = self._next_window
        image = None
        if window is None or window.limits != limits:
            window = self._prepare_trace_window(limits)
        elif (self._following_video and self._window_image is not None and self._window_image.done()
              and self._image_geometry == self._plot_geometry()):
            try:
                image = self._window_image.result()
            except Exception:
                logging.getLogger(__name__).exception("Could not pre-render graph window")
        self.cancel_playback_render()
        sample_count = window.samples
        marker = self._window_marker(window)
        trace_count = active_count = 0
        for axis, panel in self._panels.items():
            trace_count += len(panel.lines)
            for column, line in panel.lines.items():
                line.set_data(window.times, window.values[axis][column])
                line.set_marker(marker)
                if line.get_visible():
                    active_count += 1
        for axis, panel in self._panels.items():
            ylim = self._window_y_limits(window, panel)
            if ylim is not None and (self.auto_y.isChecked() or axis.get_autoscaley_on()):
                axis.set_ylim(*ylim)
        self.point_info.setText(f"{active_count}/{trace_count} traces | {sample_count} native samples")
        if image is None:
            self._plot_background = None
            self.canvas.draw_idle()
        else:
            self._plot_background = image

    def _window_marker(self, window: _TraceWindow) -> str:
        return "o" if self.show_points.isChecked() and window.samples <= 240 else "none"

    @staticmethod
    def _scale_group(panel: _AnglePanel) -> tuple[str, str, str]:
        units = "°" if panel.kind == ANGLE_MODE else MOTION_SOURCES.get(panel.source, ("", ""))[1]
        return panel.kind, panel.component, units

    def _window_y_limits(self, window: _TraceWindow, panel: _AnglePanel) -> tuple[float, float] | None:
        bounds = window.y_bounds.get(self._scale_group(panel))
        if bounds is None:
            return None
        minimum, maximum = bounds
        margin = max(maximum - minimum, 1.0 if panel.kind == ANGLE_MODE else 0.01) * 0.08
        return minimum - margin, maximum + margin

    def _on_motion(self, event) -> None:
        now = monotonic()
        if now - self._last_hover_at < 1 / 30:
            return
        self._last_hover_at = now
        panel = self._panels.get(event.inaxes)
        if panel is None or event.xdata is None or getattr(event, "buttons", ()):
            self._clear_hover()
            return
        # Limit the search to a small horizontal neighborhood, then compare
        # actual 2D pixel distances so crossing traces are distinguishable.
        radius = 12 * self.canvas.devicePixelRatioF()
        axis = panel.axis
        inverse = axis.transData.inverted()
        x1, x2 = inverse.transform([(event.x - radius, event.y), (event.x + radius, event.y)])[:, 0]
        low, high = axis.get_xlim()
        rows = self._rows_between(max(low, min(x1, x2)), min(high, max(x1, x2)))
        best = None
        best_distance = radius ** 2
        y_low, y_high = sorted(axis.get_ylim())
        for column, line in panel.lines.items():
            if not line.get_visible() or not len(rows):
                continue
            values = panel.values[column][rows]
            visible = rows[np.isfinite(values) & (values >= y_low) & (values <= y_high)]
            if not len(visible):
                continue
            points = np.column_stack((self._times[visible], panel.values[column][visible]))
            pixels = axis.transData.transform(points)
            distances = np.sum((pixels - (event.x, event.y)) ** 2, axis=1)
            closest = int(np.argmin(distances))
            if distances[closest] < best_distance:
                best = (column, int(visible[closest]))
                best_distance = distances[closest]
        if best is None:
            self._clear_hover()
        elif (axis, *best) != self._hover_sample:
            column, row = best
            self._hover_sample = (axis, column, row)
            self._selected_trace = self._trace_key(column)
            self._show_sample(panel, column, row, hovered=True)
            self._paint_frame_artists()

    def _set_sample_card(self, text: str, color: str) -> None:
        self.sample_card.setText(text)
        style = (
            f"padding: 5px; border: 2px solid {color}; border-radius: 4px;"
            "background: palette(base); color: palette(text);"
        )
        if self.sample_card.styleSheet() != style:
            self.sample_card.setStyleSheet(style)

    def _clear_hover(self, _event=None) -> None:
        if self._hover_sample is None or sip.isdeleted(self.angle_source):
            return
        self._hover_sample = None
        self._show_current_sample()
        self._paint_frame_artists()

    def _show_current_sample(self) -> None:
        source = self.angle_source.currentText()
        panels = [panel for panel in self._panels.values() if panel.source == source]
        row = self._active_row
        if row is not None:
            for panel in panels:
                selected = next((key for key, line in panel.lines.items()
                                 if self._trace_key(key) == self._selected_trace and line.get_visible()), None)
                if selected is not None:
                    self._show_sample(panel, selected, row)
                    return
            for panel in panels:
                selected = next((key for key, line in panel.lines.items() if line.get_visible()), None)
                if selected is not None:
                    self._show_sample(panel, selected, row)
                    return
        for panel in self._panels.values():
            if panel.sample_dot is not None:
                panel.sample_dot.set_visible(False)
        if row is not None:
            self._set_sample_card(self._describe_sample(source, row), "palette(mid)")
        else:
            self._set_sample_card("<b>Frame Details</b><br>Hover near a trace or choose a video frame.", "palette(mid)")

    def _show_sample(self, panel: _AnglePanel, column: str, row: int, *, hovered: bool = False) -> None:
        for other in self._panels.values():
            if other is not panel and other.sample_dot is not None:
                other.sample_dot.set_visible(False)
        color = self._trace_colors[self._trace_key(column)]
        value = panel.values[column][row]
        if np.isfinite(value):
            panel.sample_dot.set_data([self._times[row]], [value])
            panel.sample_dot.set_markeredgecolor(color)
            panel.sample_dot.set_visible(True)
        else:
            panel.sample_dot.set_visible(False)
        self._set_sample_card(self._describe_sample(panel.source, row, panel, column, hovered=hovered), color)

    def _viewer_value(self, column: str, row: int) -> float:
        values = self._viewer_values.get(column)
        return values[row] if values is not None else np.nan

    def _viewer_vector(self, prefix: str, row: int, axes: str = "xyz") -> tuple[float, ...] | None:
        values = tuple(self._viewer_value(f"{prefix}{axis}", row) for axis in axes)
        return values if np.isfinite(values).all() else None

    @staticmethod
    def _format_xyz(values) -> str:
        return "(" + ", ".join(f"{value:.3f}" for value in values) + ")"

    def _axis_label(self, panel: _AnglePanel) -> str:
        if panel.kind == ANGLE_MODE:
            return "Angle (°)" if panel.compact else ANGLE_AXIS_LABELS.get(panel.source, "Joint angle (°)")
        unit = MOTION_SOURCES.get(panel.source, ("", ""))[1]
        if panel.compact and panel.source == SAVED_SOURCE:
            unit = "image units"
        if panel.kind == DISTANCE_MODE:
            return f"Distance ({unit})"
        if panel.component == "speed":
            return f"Speed ({unit}/s)"
        axes = self._motion_axes(panel.source).upper() if panel.component == "positions" else panel.component.upper()
        return f"{axes} position ({unit})"

    def _angle_detail(self, source: str, key: str, row: int) -> list[str]:
        angles = self._angle_sources.get(source, {})
        if key not in angles:
            return ["Angle unavailable"]
        value = angles[key][row]
        angle = f"{value:.2f}°" if np.isfinite(value) else "unavailable"
        lines = [f"{self._display_name(key)} | Angle {angle}"]
        if source == MEAN_SOURCE:
            prefix = CROSS_MEAN_PREFIX if f"{CROSS_MEAN_PREFIX}{key}" in self._viewer_values else MEAN_ANGLE_PREFIX
            saved = f"{prefix}{key}"
            count = self._viewer_value(f"{saved}_source_count", row)
            if np.isfinite(count):
                lines[0] += f" | Valid sources: {int(count)}/3"
        else:
            saved = ANGLE_SOURCES[source] + key.removeprefix(LEGACY_ANGLE_PREFIX)
        prefix = "review" if f"review_omega_{saved}" in self._viewer_values else "viewer"
        for field, label, units in (("omega", "Angular velocity", "°/s"), ("alpha", "Angular acceleration", "°/s²")):
            value = self._viewer_value(f"{prefix}_{field}_{saved}", row)
            reading = f"{value:+.2f} {units}" if np.isfinite(value) else "unavailable"
            lines.append(f"{label} {reading}")
        return lines

    def _motion_detail(self, source: str, point: str, angle: str, row: int) -> list[str]:
        space, units = MOTION_SOURCES.get(source, ("", ""))
        axes = self._motion_axes(source)
        position_units = f"{units}, hip-relative" if source in (TORSO_SOURCE, WORLD_SOURCE, MEAN_SOURCE) else units
        base = f"review_{space}_{point}_"
        if source == WORLD_SOURCE and f"{base}x" not in self._viewer_values:
            base = f"viewer_world_{angle}_"
        lines = []
        for prefix, label, unit in (("", f"Position {axes.upper()}", position_units),
                                    ("v", "Velocity", f"{units}/s"), ("a", "Acceleration", f"{units}/s²")):
            values = self._viewer_vector(f"{base}{prefix}", row, axes)
            reading = self._format_xyz(values) if values is not None else "unavailable"
            lines.append(f"{label} ({unit}) {reading}")
        speed = self._viewer_value(f"{base}speed", row)
        lines.append(f"Speed {speed:.3f} {units}/s" if np.isfinite(speed) else "Speed unavailable")
        return lines

    def _describe_sample(self, source: str, row: int, panel: _AnglePanel | None = None,
                         column: str = "", *, hovered: bool = False) -> str:
        key = self._trace_key(column)
        angle = key if key.startswith("angle_") else ""
        angles = self._angle_sources.get(source, {})
        index = None
        if key.startswith("landmark_"):
            index = int(key.removeprefix("landmark_"))
        elif key.startswith("distance_"):
            indices = REVIEW_DISTANCE_TARGETS[key.removeprefix("distance_")]
            index = indices[0]
        if not angle:
            angle = next((name for name in angles if ANGLE_VERTICES.get(name) == (index,)), "")
            angle = angle or next(iter(angles), "")
        vertex = ANGLE_VERTICES.get(angle, ())
        if index is None and len(vertex) == 1:
            index = vertex[0]
        point = f"lm{index}" if index is not None else {(11, 12): "shoulder_midpoint", (23, 24): "hip_midpoint"}.get(vertex, "")
        if not point:
            space = MOTION_SOURCES.get(source, ("", ""))[0]
            index = next((i for i in REVIEW_LANDMARKS if f"review_{space}_lm{i}_x" in self._viewer_values), None)
            if index is not None:
                point = f"lm{index}"
        if key.startswith("distance_"):
            pair = key.removeprefix("distance_")
        else:
            pair = next((name for name, pair in REVIEW_DISTANCE_TARGETS.items() if index in pair), "knee_to_knee")
        space, units = MOTION_SOURCES.get(source, ("", ""))
        distance = self._viewer_value(f"review_{space}_distance_{pair}", row)
        rate = self._viewer_value(f"review_{space}_distance_rate_{pair}", row)
        acceleration = self._viewer_value(f"review_{space}_distance_acceleration_{pair}", row)
        distance_lines = [
            self._display_name(f"distance_{pair}"),
            f"Distance ({units}): {distance:.4f}" if np.isfinite(distance) else "Distance unavailable",
            f"Distance rate ({units}/s): {rate:+.4f}" if np.isfinite(rate) else "Distance rate unavailable",
            (f"Distance acceleration ({units}/s²): {acceleration:+.4f}"
             if np.isfinite(acceleration) else "Distance acceleration unavailable"),
        ]
        motion_lines = self._motion_detail(source, point, angle, row)
        if index in REVIEW_LANDMARKS:
            motion_lines.insert(0, REVIEW_LANDMARKS[index])
        if panel is not None and panel.kind == LANDMARK_MODE:
            value = panel.values[column][row]
            if np.isfinite(value):
                motion_lines[0] = f"{self._display_name(key)} | {self._axis_label(panel)}: {value:.4f}"
        frame = self._frame_ids[row]
        frame = int(frame) if np.isfinite(frame) else "unknown"
        sample = "hovered sample" if hovered else "current"
        title = f"Frame Details · {source} | Video frame {frame} ({sample}) | Source time {self._source_times[row]:.6f} s"
        return _frame_details_html(title, self._angle_detail(source, angle, row), motion_lines, distance_lines)

    def _on_click(self, event) -> None:
        if event.inaxes not in self._panels or event.xdata is None:
            return
        if self.toolbar.mode:
            if self._link_video and event.button in (1, 3):
                if getattr(self.toolbar.mode, "name", "") == "PAN" and event.button == 1:
                    self._drag_xlim = self.axis.get_xlim()
                self.navigationStarted.emit()
            return
        if event.button == 1:
            self._seek_timestamp(event.xdata)

    def _seek_timestamp(self, time: float) -> None:
        if not self.frame_column or not len(self._ordered_times):
            return
        index = int(self._ordered_times.searchsorted(time))
        candidates = self._time_rows[max(0, index - 1):index + 1]
        nearest = candidates[np.argmin(np.abs(self._times[candidates] - time))]
        if np.isfinite(self._frame_ids[nearest]):
            self.frameSelected.emit(int(self._frame_ids[nearest]))
