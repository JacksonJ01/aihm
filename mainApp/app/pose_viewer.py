"""Mode 4 shows the saved pose at the video playhead."""
from __future__ import annotations

from time import monotonic

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Line3DCollection
from PyQt6.QtCore import QEvent, QTimer
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget

from aihumo.features import CROSS_MEAN_PREFIX, LANDMARKS
from aihumo.geometry import POSE_CONNECTIONS

from .graph_navigation import FrameZoomToolbar, wheel_zoom_factor
from .graph_viewer import InteractiveGraphViewer
from .orientation_cube import OrientationCube


POSE_SOURCES = (
    ("Estimated world (3D)", "world", "xyz", "m"),
    ("Torso-normalized (2D)", "review_torso2d_lm", "xy", "torso lengths"),
    ("Normalized image (2D)", "lm", "xy", "image units"),
    ("Mean of three sources (2D)", f"{CROSS_MEAN_PREFIX}lm", "xy", "torso lengths"),
)
_CONNECTIONS = np.asarray(POSE_CONNECTIONS)


class PosePlot(QWidget):
    def __init__(self, frames):
        super().__init__()
        self.poses = {}
        self.source = QComboBox()
        self.source.setAccessibleName("Pose source")
        for label, prefix, axes, unit in POSE_SOURCES:
            columns = [f"{prefix}{index}_{axis}" for index in range(LANDMARKS) for axis in axes]
            if not any(column in frames for column in columns):
                continue
            values = frames.reindex(columns=columns).to_numpy(dtype=np.float32).reshape(-1, LANDMARKS, len(axes))
            if not np.isfinite(values).all(axis=2).any():
                continue
            # MediaPipe Y points down. In the world view, depth is the second
            # plot axis and the vertical axis points up.
            if len(axes) == 3:
                values = values[:, :, (0, 2, 1)]
            values = values.copy()
            values[:, :, -1] *= -1
            self.poses[prefix] = values, unit
            self.source.addItem(label, prefix)
        if not self.poses:
            raise ValueError("The selected feature Parquet has no usable pose landmarks.")

        self.frame = 0
        self._render_interval = 1 / 20
        self._last_rendered_at = 0.0
        self._pending_frame = None
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._flush_pending_frame)
        self._home_bounds = {}
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Pose source"))
        controls.addWidget(self.source)
        self.rotate_button = QPushButton("Rotate", clicked=self._activate_rotation)
        self.rotate_button.setToolTip("Left-drag the 3D pose to rotate it while the video plays.")
        controls.addWidget(self.rotate_button)
        controls.addWidget(QPushButton("Reset pose view", clicked=self._reset_view))
        controls.addWidget(QPushButton("+", clicked=lambda: self._zoom_pose(0.6)))
        controls.addWidget(QPushButton("−", clicked=lambda: self._zoom_pose(1.7)))
        controls.addStretch(1)
        layout.addLayout(controls)
        self.figure = Figure(layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.orientation_cube = OrientationCube(self.canvas)
        self.orientation_cube.view_changed.connect(self._orient_pose)
        self.canvas.installEventFilter(self)
        self.toolbar = FrameZoomToolbar(self.canvas, self, self._zoom_pose, spatial=True)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("draw_event", self._sync_orientation)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, 1)
        self.detail = QLabel()
        layout.addWidget(self.detail)
        self.source.currentIndexChanged.connect(self._rebuild)
        self._rebuild()

    def _rebuild(self):
        values, unit = self.poses[self.source.currentData()]
        self.spatial = values.shape[-1] == 3
        self.rotate_button.setVisible(self.spatial)
        self.orientation_cube.setVisible(self.spatial)
        if self.spatial:
            self._activate_rotation()
        self._rendered_frame = None
        self.figure.clear()
        self.axis = self.figure.add_subplot(projection="3d" if self.spatial else None)
        if self.spatial:
            self.axis.mouse_init(zoom_btn=[])
            self.bones = Line3DCollection([], colors="#168b66", linewidths=2)
            self.axis.add_collection(self.bones, autolim=False)
            self.points, = self.axis.plot([], [], [], marker="o", linestyle="none", color="#3264ad", markersize=4)
            self.axis.set(xlabel=f"X ({unit})", ylabel=f"Depth Z ({unit})", zlabel=f"Up −Y ({unit})")
        else:
            self.bones = LineCollection([], colors="#168b66", linewidths=2)
            self.axis.add_collection(self.bones, autolim=False)
            self.points, = self.axis.plot([], [], marker="o", linestyle="none", color="#3264ad", markersize=4)
            self.axis.set(xlabel=f"X ({unit})", ylabel=f"Up −Y ({unit})", aspect="equal")
        self._reset_view()
        self.set_frame(self.frame)

    def eventFilter(self, watched, event):
        if watched is self.canvas and event.type() == QEvent.Type.Resize:
            self.orientation_cube.move(max(0, event.size().width() - self.orientation_cube.width() - 8), 8)
        return super().eventFilter(watched, event)

    def _orient_pose(self, elev, azim, roll):
        self.axis.view_init(elev=elev, azim=azim, roll=roll)
        self._sync_orientation()
        self.canvas.draw_idle()

    def _sync_orientation(self, _event=None):
        if self.spatial:
            self.orientation_cube.set_view(self.axis.elev, self.axis.azim, self.axis.roll)

    def _activate_rotation(self):
        if self.toolbar.mode.name == "PAN":
            self.toolbar.pan()
        elif self.toolbar.mode.name == "ZOOM":
            self.toolbar.zoom()

    def _reset_view(self):
        source = self.source.currentData()
        if source not in self._home_bounds:
            values, _ = self.poses[source]
            valid = values[np.isfinite(values).all(axis=2)]
            low, high = np.percentile(valid, (0.5, 99.5), axis=0)
            center = (low + high) / 2
            half = max(float((high - low).max()) * 0.6, 0.05)
            self._home_bounds[source] = np.column_stack((center - half, center + half))
        self._set_bounds(self._home_bounds[source])
        if self.spatial:
            self.axis.set_box_aspect((1, 1, 1))
            self.axis.view_init(elev=12, azim=-80)
            self._sync_orientation()
        self.toolbar.update()
        self.toolbar.push_current()
        self.canvas.draw_idle()

    def _set_bounds(self, bounds):
        self.axis.set_xlim(*bounds[0])
        self.axis.set_ylim(*bounds[1])
        if self.spatial:
            self.axis.set_zlim(*bounds[2])

    def _zoom_pose(self, factor):
        limits = [self.axis.get_xlim(), self.axis.get_ylim()]
        if self.spatial:
            limits.append(self.axis.get_zlim())
        bounds = np.asarray(limits)
        center = bounds.mean(axis=1) if self._pose_center is None else self._pose_center
        half = (bounds[:, 1] - bounds[:, 0]) / 2
        home_width = np.diff(self._home_bounds[self.source.currentData()], axis=1).ravel()
        half = np.clip(half * factor, home_width / 1000, home_width * 1000)
        self._set_bounds(np.column_stack((center - half, center + half)))
        self.canvas.draw_idle()

    def _on_scroll(self, event):
        if event.inaxes is self.axis:
            self._zoom_pose(wheel_zoom_factor(event))

    def set_frame(self, frame, *, playing=False):
        self.frame = frame
        elapsed = monotonic() - self._last_rendered_at
        if playing and self._rendered_frame is not None and elapsed < self._render_interval:
            self._pending_frame = frame
            if not self._render_timer.isActive():
                self._render_timer.start(max(1, round((self._render_interval - elapsed) * 1000)))
            return
        self._render_timer.stop()
        self._pending_frame = None
        self._render_frame(frame)

    def _flush_pending_frame(self):
        if self._pending_frame is not None:
            frame, self._pending_frame = self._pending_frame, None
            self._render_frame(frame)

    def _render_frame(self, frame):
        if frame == self._rendered_frame:
            return
        self._rendered_frame = frame
        self._last_rendered_at = monotonic()
        pose = self.poses[self.source.currentData()][0][frame]
        visible = np.isfinite(pose).all(axis=1)
        points = pose[visible]
        self._pose_center = (points.min(axis=0) + points.max(axis=0)) / 2 if len(points) else None
        segments = pose[_CONNECTIONS[visible[_CONNECTIONS].all(axis=1)]]
        self.bones.set_segments(segments)
        if self.spatial:
            self.points.set_data_3d(*points.T)
        else:
            self.points.set_data(*points.T)
        hint = "Left-drag to rotate the world pose, including during playback." if self.spatial else "Saved X and Y positions."
        message = f"{int(visible.sum())}/{LANDMARKS} landmarks. {hint}" if visible.any() else "No pose landmarks at this frame."
        self.detail.setText(f"Frame {frame:,} · {message}")
        self.canvas.draw_idle()


class PoseGraphViewer(InteractiveGraphViewer):
    viewer_title = "AIHuMo Interactive Graph Viewer (3D) · Mode 4"

    def _extra_feature_columns(self, columns):
        saved = set(columns)
        return [column for _, prefix, axes, _ in POSE_SOURCES for index in range(LANDMARKS) for axis in axes
                if (column := f"{prefix}{index}_{axis}") in saved]

    def _build_ui(self, frames, frame_jump):
        super()._build_ui(frames, frame_jump)
        self.pose_plot = PosePlot(frames)
        self.pose_tabs = QTabWidget()
        sizes = self.splitter.sizes()
        self.splitter.replaceWidget(1, self.pose_tabs)
        self.pose_tabs.addTab(self.pose_plot, "Pose")
        self.pose_tabs.addTab(self.graph, "Timeline graphs")
        self.splitter.setSizes(sizes)
        self.pose_tabs.currentChanged.connect(self._switch_pose_tab)

    def _switch_pose_tab(self):
        if self.pose_tabs.currentWidget() is self.pose_plot:
            self.graph.release_render_cache()
        self._update_graph_frame(self.current_frame, playing=self.playback.playing)

    def _update_graph_frame(self, index, *, playing=False):
        if self.pose_tabs.currentWidget() is self.pose_plot:
            self.pose_plot.set_frame(index, playing=playing)
        else:
            super()._update_graph_frame(index, playing=playing)

    def _refresh_paused_frame(self):
        if self.pose_tabs.currentWidget() is not self.pose_plot:
            super()._refresh_paused_frame()
