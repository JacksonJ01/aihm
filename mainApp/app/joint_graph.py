"""Interactive, timestamp-aware joint-angle graphs for Mode 1."""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib import rcParams


class CheckableFeatureComboBox(QComboBox):
    """A compact checkable list used to select graph series."""

    selectionChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText("Select joint angles")
        self.setModel(QStandardItemModel(self))
        self.view().pressed.connect(self._toggle)

    def set_options(self, options: Iterable[tuple[str, str]], selected: Iterable[str] = ()) -> None:
        selected = {str(value) for value in selected}
        model = self.model()
        model.clear()
        for label, value in options:
            item = QStandardItem(str(label))
            item.setData(str(value), Qt.ItemDataRole.UserRole)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if str(value) in selected else Qt.CheckState.Unchecked)
            model.appendRow(item)
        self._refresh_text()

    def _toggle(self, index) -> None:
        item = self.model().itemFromIndex(index)
        item.setCheckState(
            Qt.CheckState.Unchecked
            if item.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )
        self._refresh_text()
        self.selectionChanged.emit()

    def checked_values(self) -> list[str]:
        return [
            str(self.model().item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.model().rowCount())
            if self.model().item(row).checkState() == Qt.CheckState.Checked
        ]

    def _refresh_text(self) -> None:
        labels = [
            self.model().item(row).text()
            for row in range(self.model().rowCount())
            if self.model().item(row).checkState() == Qt.CheckState.Checked
        ]
        if len(labels) > 4:
            self.lineEdit().setText(f"{len(labels)} joint angles selected")
        else:
            self.lineEdit().setText(", ".join(labels) if labels else "None selected")


class JointGraphWidget(QWidget):
    """Interactive graph of all registered joint-angle features.

    The x-axis is always the source elapsed-time column. No fixed duration or
    FPS is assumed, so the same widget works for short clips and long sessions.
    Matplotlib's toolbar provides zoom/pan; the wheel handler adds centered
    horizontal zoom, and clicking the graph seeks the synchronized video.
    """

    frameSelected = pyqtSignal(int)

    def __init__(self, dataframe: pd.DataFrame, parent=None):
        super().__init__(parent)
        self.dataframe = dataframe.copy()
        self.time_column = self._find_time_column(self.dataframe)
        self.frame_column = "frame_id" if "frame_id" in self.dataframe.columns else None
        self.angle_columns: list[str] = []
        self._full_xlim: tuple[float, float] = (0.0, 1.0)
        self._cursor = None
        self._lines = {}

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Joint angles"))
        self.series_selector = CheckableFeatureComboBox(self)
        self.series_selector.setMinimumWidth(330)
        self.series_selector.selectionChanged.connect(self._redraw_series)
        controls.addWidget(self.series_selector, 1)
        self.follow_frame = QCheckBox("Follow frame")
        self.follow_frame.setToolTip("Keep the current frame visible while navigating the video.")
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

        self.figure = Figure(figsize=(9, 3.8))
        self.axis = self.figure.add_subplot(111)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_click)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, 1)
        self._load_dataframe(self.dataframe)

    @staticmethod
    def _find_time_column(dataframe: pd.DataFrame) -> str | None:
        for candidate in ("timeElapsedS", "timestamp_s", "time_elapsed_s"):
            if candidate in dataframe.columns:
                return candidate
        return None

    @staticmethod
    def _display_name(column: str) -> str:
        return column.removeprefix("angle_").replace("_", " ").title()

    def _load_dataframe(self, dataframe: pd.DataFrame) -> None:
        self.dataframe = dataframe.copy()
        self.time_column = self._find_time_column(self.dataframe)
        self.frame_column = "frame_id" if "frame_id" in self.dataframe.columns else None
        self.angle_columns = sorted(
            column for column in self.dataframe.columns if str(column).startswith("angle_")
        )
        options = [(self._display_name(column), column) for column in self.angle_columns]
        self.series_selector.set_options(options, self.angle_columns)
        if self.time_column and len(self.dataframe):
            times = pd.to_numeric(self.dataframe[self.time_column], errors="coerce").to_numpy(dtype=float)
            finite = times[np.isfinite(times)]
            if len(finite):
                low, high = float(finite.min()), float(finite.max())
                if high <= low:
                    high = low + 1.0
                self._full_xlim = (low, high)
        self._redraw_series()

    def _redraw_series(self) -> None:
        self.axis.clear()
        self._lines = {}
        self.axis.set_xlabel("Elapsed source time (s)")
        self.axis.set_ylabel("Joint angle (degrees)")
        self.axis.set_title("AIHuMo — Joint-angle graphs")
        self.axis.grid(True, alpha=0.25)
        if not self.time_column or self.dataframe.empty:
            self.axis.text(0.5, 0.5, "No timestamped angle features available", ha="center", va="center")
            self.canvas.draw_idle()
            return
        x = pd.to_numeric(self.dataframe[self.time_column], errors="coerce").to_numpy(dtype=float)
        palette = rcParams["axes.prop_cycle"].by_key().get("color", [])
        for index, column in enumerate(self.series_selector.checked_values()):
            if column not in self.dataframe.columns:
                continue
            y = pd.to_numeric(self.dataframe[column], errors="coerce").to_numpy(dtype=float)
            line, = self.axis.plot(
                x,
                y,
                linewidth=1.0,
                label=self._display_name(column),
                color=palette[index % len(palette)] if palette else None,
            )
            self._lines[column] = line
        if self._lines:
            self.axis.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize="small")
        # Reserve space for the legend explicitly. ``tight_layout`` can emit
        # warnings for long recordings with many series and a narrow dock.
        self.figure.subplots_adjust(left=0.08, right=0.78, bottom=0.16, top=0.88)
        self.axis.set_xlim(*self._full_xlim)
        self._cursor = self.axis.axvline(self._full_xlim[0], color="#20c55a", linewidth=1.5, alpha=0.9)
        self.canvas.draw_idle()

    def set_current_frame(self, frame: int) -> None:
        if self._cursor is None or self.dataframe.empty or not self.time_column:
            return
        if self.frame_column:
            frame_values = pd.to_numeric(self.dataframe[self.frame_column], errors="coerce").to_numpy(dtype=float)
            valid = np.isfinite(frame_values)
            matches = np.flatnonzero(valid & (frame_values == int(frame)))
            index = int(matches[0]) if len(matches) else int(np.clip(frame, 0, len(self.dataframe) - 1))
        else:
            index = int(np.clip(frame, 0, len(self.dataframe) - 1))
        times = pd.to_numeric(self.dataframe[self.time_column], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(times[index]):
            return
        current_time = float(times[index])
        self._cursor.set_xdata([current_time, current_time])
        if self.follow_frame.isChecked():
            low, high = self.axis.get_xlim()
            width = high - low
            if width > 0 and not (low <= current_time <= high):
                center = min(max(current_time, self._full_xlim[0]), self._full_xlim[1])
                new_low = max(self._full_xlim[0], center - width / 2.0)
                new_high = min(self._full_xlim[1], new_low + width)
                self.axis.set_xlim(new_low, new_high)
        self.canvas.draw_idle()

    def reset_zoom(self) -> None:
        self.axis.set_xlim(*self._full_xlim)
        if self._lines:
            self.axis.relim()
            self.axis.autoscale_view(scalex=False, scaley=True)
        self.canvas.draw_idle()

    def _scale_x(self, factor: float, center: float | None = None) -> None:
        low, high = self.axis.get_xlim()
        center = float(center if center is not None else (low + high) / 2.0)
        half_width = (high - low) * float(factor) / 2.0
        new_low = max(self._full_xlim[0], center - half_width)
        new_high = min(self._full_xlim[1], center + half_width)
        if new_high - new_low > 1e-9:
            self.axis.set_xlim(new_low, new_high)
            self.canvas.draw_idle()

    def _on_scroll(self, event) -> None:
        if event.inaxes is not self.axis or event.xdata is None:
            return
        self._scale_x(0.65 if event.button == "up" else 1.55, event.xdata)

    def _on_click(self, event) -> None:
        if event.inaxes is not self.axis or event.xdata is None or not self.frame_column:
            return
        times = pd.to_numeric(self.dataframe[self.time_column], errors="coerce").to_numpy(dtype=float)
        valid = np.isfinite(times)
        valid_indices = np.flatnonzero(valid)
        if not len(valid_indices):
            return
        nearest = valid_indices[int(np.argmin(np.abs(times[valid_indices] - float(event.xdata))))]
        frame = int(pd.to_numeric(self.dataframe[self.frame_column], errors="coerce").iloc[nearest])
        self.frameSelected.emit(frame)
