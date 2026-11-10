from contextlib import nullcontext
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import cv2
import numpy as np
import pandas as pd
import pytest
from matplotlib.backend_bases import MouseButton, MouseEvent
from PyQt6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QTimer, Qt
from PyQt6.QtGui import QTextDocument, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton, QSpinBox, QToolButton

from aihumo.annotations import AnnotationState
from aihumo.config import load_config
from aihumo.features import with_viewer_features
from aihumo.pose import iter_landmark_rows
from aihumo.processing import create_skeleton_video, process_video
from aihumo.storage import load_json, save_json_atomic
from app.AIHuMoDataStudio import HomeWindow
from app.graph_viewer import InteractiveGraphViewer
from app.joint_graph import ALL_GRAPHS_MODE, ANGLE_MODE, DISTANCE_MODE, LANDMARK_MODE, MEAN_SOURCE, WORLD_SOURCE, JointGraphWidget
from app.mode0_batch import BatchSessionDialog
from app.mode0_process import ProcessVideoDialog
from app.pose_viewer import PoseGraphViewer
from app.preferences import DesktopPreferences, PreferenceStore, PreferencesDialog


def write_video(path, frame_count):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 24, (160, 120))
    assert writer.isOpened()
    try:
        for index in range(frame_count):
            writer.write(np.full((120, 160, 3), index * 4 % 256, dtype=np.uint8))
    finally:
        writer.release()


def test_long_graph_opens_and_keeps_zoom_and_cursor(qt_app, detail):
    count = 600
    detail(input="600 frames at 60 FPS with one Right Hip trace",
           expected="Zoom buttons update the visible time range and preserve the selected frame")
    graph = JointGraphWidget(pd.DataFrame({
        "frame_id": range(count),
        "timestamp_s": np.arange(count) / 60,
        "angle_right_hip": np.linspace(0, 90, count),
    }))
    try:
        buttons = {button.text(): button for button in graph.findChildren(QPushButton)}
        assert "Zoom to window" not in buttons
        full_end = (count - 1) / 60
        assert graph.detail_window_label.text() == f"0.000–{full_end:.3f} s ({full_end:.3f} s visible)"
        assert graph._lines["angle_right_hip"].get_marker() == "none"
        graph.set_current_frame(120)
        buttons["+"].click()
        buttons["+"].click()
        limits = graph.axis.get_xlim()
        width = limits[1] - limits[0]
        assert 0 < width < full_end
        assert sum(limits) / 2 == pytest.approx(2.0)
        assert graph.detail_window_label.text() == f"{limits[0]:.3f}–{limits[1]:.3f} s ({width:.3f} s visible)"
        assert not graph.show_points.isChecked()
        assert graph._lines["angle_right_hip"].get_marker() == "none"
        graph.show_points.setChecked(True)
        assert graph._lines["angle_right_hip"].get_marker() == "o"
        graph._redraw_series()
        assert graph.axis.get_xlim() == limits
        assert list(graph._cursor.get_xdata()) == [2.0, 2.0]
        hits = []
        graph.frameSelected.connect(hits.append)
        click = SimpleNamespace(inaxes=graph.axis, xdata=2.0, button=1)
        graph.toolbar.pan()
        graph._on_click(click)
        assert hits == []
        graph.toolbar.pan()
        graph._on_click(click)
        assert hits == [120]
        buttons["−"].click()
        low, high = graph.axis.get_xlim()
        assert high - low > width
        assert graph.detail_window_label.text() == f"{low:.3f}–{high:.3f} s ({high - low:.3f} s visible)"
        assert list(graph._cursor.get_xdata()) == [2.0, 2.0]
        graph.axis.set_xlim(0, 9)
        assert graph.detail_window_label.text() == "0.000–9.000 s (9.000 s visible)"
        assert graph._lines["angle_right_hip"].get_marker() == "none"
        buttons["Reset zoom"].click()
        assert graph.detail_window_label.text() == f"0.000–{full_end:.3f} s ({full_end:.3f} s visible)"
        detail(observed=f"zoom={limits[1] - limits[0]:.3f} s; cursor=2.0 s; only normal click sought frame {hits[0]}")
    finally:
        graph.close()


def test_trace_checkboxes_and_hover_use_the_visible_nearest_joint(qt_app, detail):
    detail(input="Two angle traces at matching timestamps, with Right Hip world landmarks",
           expected="Hover overrides the current sample; moving away restores the last inspected joint at the video frame")
    timestamps = np.arange(5) / 4
    graph = JointGraphWidget(with_viewer_features(pd.DataFrame({
        "frame_id": range(5),
        "timestamp_s": timestamps,
        "angle_3d_right_hip": [40, 40.5, 42, 44.5, np.nan],
        "angle_3d_left_hip": 20 + timestamps,
        "world24_x": timestamps**2,
        "world24_y": 0.0,
        "world24_z": 0.0,
    })))
    try:
        graph.set_current_frame(3)
        graph.canvas.draw()
        x, y = graph.axis.transData.transform((0.5, 42.0))
        graph._on_motion(SimpleNamespace(inaxes=graph.axis, xdata=0.5, x=x, y=y))
        card = graph.sample_card.text()
        color = graph._lines["angle_right_hip"].get_color()
        assert "Right Hip" in card and "Angle 42.00°" in card and "Video frame 2" in card
        assert "(hovered sample)" in card
        assert "Source time 0.500000 s" in card and "Angular velocity +6.00" in card
        assert "Angular acceleration +16.00" in card and "Speed 0.750 m/s" in card
        assert "Position XYZ (m, hip-relative) (0.250, 0.000, 0.000)" in card
        assert color in graph.sample_card.styleSheet()
        assert graph._hover_dot.get_markeredgecolor() == color

        graph._clear_hover()
        current_card = graph.sample_card.text()
        assert "Right Hip" in current_card and "Angle 44.50°" in current_card
        assert "Video frame 3 (current)" in current_card
        assert list(graph._hover_dot.get_xdata()) == [timestamps[3]]
        graph.set_current_frame(4)
        assert "Angle unavailable" in graph.sample_card.text()
        assert "Video frame 4 (current)" in graph.sample_card.text()
        assert not graph._hover_dot.get_visible()

        bounds = graph.axis.get_xlim()
        graph.trace_checks["angle_right_hip"].setChecked(False)
        assert not graph._lines["angle_right_hip"].get_visible()
        assert graph._lines["angle_left_hip"].get_visible()
        assert "Left Hip" in graph.sample_card.text()
        assert list(graph._hover_dot.get_xdata()) == [timestamps[4]]
        assert graph.axis.get_xlim() == bounds
        graph._set_all_traces(False)
        assert not any(line.get_visible() for line in graph._lines.values())
        graph._set_all_traces(True)
        assert graph._lines["angle_right_hip"].get_color() == color
        detail(observed=f"Right Hip hovered at frame 2, border {color}; returned to frame 3, then showed missing angle at frame 4.")
    finally:
        graph.close()


def test_show_all_angle_sources_compares_synced_traces_and_restores_single_view(qt_app, detail):
    detail(input="Three angle sources for Right Hip with a gap in the 3D trace",
           expected="Comparison keeps one time window and computes a mean only where all sources are present")
    timestamps = [0.0, 0.12, 0.25, 0.43, 0.70]
    frames = pd.DataFrame({
        "frame_id": range(len(timestamps)), "timestamp_s": timestamps,
        "angle_torso2d_right_hip": [30.0, 42.0, 54.0, 66.0, 78.0],
        "angle_3d_right_hip": [45.0, 63.0, np.nan, 81.0, 99.0],
        "angle_right_hip": [60.0, 60.0, 78.0, 84.0, 105.0],
        "angle_left_hip": [80.0, 83.0, 84.0, 87.0, 89.0],
        "review_cross_mean_angle_right_hip": [45.0, 55.0, np.nan, 77.0, 94.0],
    })
    original_frames = frames.copy(deep=True)
    graph = JointGraphWidget(frames)
    graph.show()
    try:
        graph.angle_source.setCurrentText("Legacy (normalized image)")
        graph.trace_checks["angle_left_hip"].setChecked(False)
        selection = graph.angle_selection()
        overlay_traces = graph.overlay_traces()
        graph.set_current_frame(2)
        graph.axis.set_xlim(0.10, 0.50)
        initial_limits = graph.axis.get_xlim()
        assert graph.trace_legend.isVisible()

        graph.show_all_sources.click()
        assert not graph.trace_legend.isVisible()
        assert graph.overlay_traces() == overlay_traces
        axes = graph.figure.axes
        assert len(axes) == 4
        traces = [next(line for line in axis.lines if line.get_label() == "Right Hip") for axis in axes]
        for trace in traces:
            np.testing.assert_allclose(trace.get_xdata(), timestamps)
        for trace, column in zip(traces, ("angle_torso2d_right_hip", "angle_3d_right_hip", "angle_right_hip")):
            np.testing.assert_allclose(trace.get_ydata(), original_frames[column])
        np.testing.assert_allclose(traces[-1].get_ydata(), [45.0, 55.0, np.nan, 77.0, 94.0])
        assert len({trace.get_color() for trace in traces}) == 1
        assert all(axis.get_xlim() == initial_limits for axis in axes)
        assert all(any(line.get_color() == "#20c55a" and list(line.get_xdata()) == [0.25, 0.25]
                       for line in axis.lines) for axis in axes)

        graph._on_scroll(SimpleNamespace(inaxes=axes[-1], xdata=0.23, button="up"))
        zoomed_limits = axes[-1].get_xlim()
        assert zoomed_limits[1] - zoomed_limits[0] < initial_limits[1] - initial_limits[0]
        assert sum(zoomed_limits) / 2 == pytest.approx(timestamps[2])
        assert all(axis.get_xlim() == zoomed_limits for axis in axes)
        frames_selected = []
        graph.frameSelected.connect(frames_selected.append)
        graph._on_click(SimpleNamespace(inaxes=axes[1], xdata=0.12, button=1))
        assert frames_selected == [1]
        graph.set_current_frame(1)
        assert all(any(line.get_color() == "#20c55a" and list(line.get_xdata()) == [0.12, 0.12]
                       for line in axis.lines) for axis in axes)

        graph.canvas.draw()
        x, y = axes[-1].transData.transform((0.12, 55.0))
        graph._on_motion(SimpleNamespace(inaxes=axes[-1], xdata=0.12, x=x, y=y))
        assert "Angle 55.00°" in graph.sample_card.text()
        assert "Mean of three sources" in graph.sample_card.text()

        graph.show_all_sources.click()
        assert graph.trace_legend.isVisible()
        assert len(graph.figure.axes) == 1
        assert graph.axis.get_xlim() == zoomed_limits
        assert graph.angle_selection() == selection
        assert not graph._lines["angle_left_hip"].get_visible()
        pd.testing.assert_frame_equal(frames, original_frames)
        detail(observed="All four panels followed the same zoom, and returning kept the original source and joint selection.")
    finally:
        graph.close()


def test_graph_modes_read_saved_measurements_and_keep_the_angle_selection(qt_app):
    graph = JointGraphWidget(pd.DataFrame({
        "frame_id": [0, 1, 2], "timestamp_s": [0.0, 0.1, 0.2],
        "angle_right_hip": [45.0, 70.0, 55.0],
        "review_cross_mean_angle_right_hip": [40.0, 66.0, 50.0],
        "review_world_lm31_y": [0.10, 0.17, 0.12],
        "review_world_distance_elbow_to_elbow": [0.25, 0.30, 0.28],
    }))
    try:
        graph.angle_source.setCurrentText(MEAN_SOURCE)
        assert graph.overlay_traces()[0].column == "review_cross_mean_angle_right_hip"
        angle_selection = graph.angle_selection()
        graph.set_current_frame(1)
        graph.set_graph_mode(LANDMARK_MODE)
        graph.angle_source.setCurrentText(WORLD_SOURCE)
        np.testing.assert_allclose(graph._lines["landmark_31"].get_ydata(), [0.10, 0.17, 0.12])
        graph.canvas.draw()
        x, y = graph.axis.transData.transform((0.1, 0.17))
        graph._on_motion(SimpleNamespace(inaxes=graph.axis, xdata=0.1, x=x, y=y))
        assert "Left toe index | Y position (m): 0.1700" in graph.sample_card.text()
        graph.set_graph_mode(DISTANCE_MODE)
        graph.angle_source.setCurrentText(WORLD_SOURCE)
        np.testing.assert_allclose(graph._lines["distance_elbow_to_elbow"].get_ydata(), [0.25, 0.30, 0.28])
        assert "Distance (m): 0.3000" in graph.sample_card.text()
        graph.set_graph_mode(ANGLE_MODE)
        assert graph.angle_selection() == angle_selection
        assert "Angle 66.00°" in graph.sample_card.text()
    finally:
        graph.close()


def test_trace_configurations_filter_their_own_graphs_across_sources(qt_app):
    rows = {
        "frame_id": [0, 1], "timestamp_s": [0.0, 0.1],
        "angle_3d_right_knee": [75.0, 90.0], "angle_3d_left_knee": [90.0, 95.0],
        "angle_3d_right_wrist": [120.0, 125.0],
        "angle_torso2d_right_knee": [75.0, 90.0],
    }
    for source, axes in (("world", ("x", "y", "z", "speed")), ("torso2d", ("x", "y", "speed"))):
        for landmark in (20, 26, 27, 31):
            for axis in axes:
                rows[f"review_{source}_lm{landmark}_{axis}"] = [0.2, 0.3]
        for pair in ("knee_to_knee", "ankle_to_ankle"):
            rows[f"review_{source}_distance_{pair}"] = [0.4, 0.5]
    graph = JointGraphWidget(pd.DataFrame(rows))
    try:
        graph.angle_source.setCurrentText(WORLD_SOURCE)
        graph._set_all_traces(False)
        graph.trace_checks["angle_right_knee"].setChecked(True)
        angle_selection = graph.angle_selection()
        overlay_traces = graph.overlay_traces()
        angle_changes = []
        graph.traceSelectionChanged.connect(lambda: angle_changes.append(graph.angle_selection()))

        graph.trace_configuration.setCurrentText("Landmarks")
        assert graph._graph_mode == ANGLE_MODE
        assert graph._legend_rows["angle_right_knee"].isHidden()
        assert len([row for key, row in graph._legend_rows.items()
                    if key.startswith("landmark_") and not row.isHidden()]) == 16
        graph._set_all_traces(False)
        graph.trace_checks["landmark_20"].setChecked(True)
        graph.trace_checks["landmark_31"].setChecked(True)
        assert graph.angle_selection() == angle_selection
        assert graph.overlay_traces() == overlay_traces
        assert not angle_changes
        assert graph._lines["angle_right_knee"].get_visible()

        graph.trace_configuration.setCurrentText("Distances")
        graph.trace_checks["distance_knee_to_knee"].setChecked(False)
        graph.set_graph_mode(ALL_GRAPHS_MODE)
        graph.landmark_component.setCurrentIndex(graph.landmark_component.findData("positions-speed"))
        graph.show_all_sources.setChecked(True)
        for panel in graph._panels.values():
            if panel.source not in (WORLD_SOURCE, "Torso-normalized 2D"):
                continue
            visible = {key for key, line in panel.lines.items() if line.get_visible()}
            if panel.kind == ANGLE_MODE:
                assert visible == {"angle_right_knee"}
            elif panel.kind == LANDMARK_MODE:
                axes = "xyz" if panel.source == WORLD_SOURCE else "xy"
                expected = {"landmark_20", "landmark_31"} if panel.component == "speed" else {
                    f"landmark_{index}|{axis}" for index in (20, 31) for axis in axes
                }
                assert visible == expected
            else:
                assert visible == {"distance_ankle_to_ankle"}

        graph.show_all_sources.setChecked(False)
        graph.set_graph_mode(LANDMARK_MODE)
        assert graph.trace_configuration.currentText() == "Landmarks"
        graph.landmark_component.setCurrentText("Y")
        assert {key for key, line in graph._lines.items() if line.get_visible()} == {"landmark_20", "landmark_31"}
        graph.set_graph_mode(ANGLE_MODE)
        assert graph.trace_configuration.currentText() == "Angles"
        assert graph.angle_selection() == angle_selection
    finally:
        graph.close()


def test_playback_prepares_next_window_before_the_cursor_reaches_the_edge(qt_app, monkeypatch):
    from app import joint_graph

    render_ready = Event()
    draw = joint_graph._draw_window_image

    def wait_then_draw(*args):
        assert render_ready.wait(15)
        return draw(*args)

    monkeypatch.setattr(joint_graph, "_draw_window_image", wait_then_draw)
    times = np.arange(100) / 10
    graph = JointGraphWidget(pd.DataFrame({
        "frame_id": range(len(times)), "timestamp_s": times, "angle_torso2d_right_hip": times * 10,
    }), link_video=True)
    try:
        graph.show_all_sources.setChecked(True)
        graph.axis.set_xlim(0, 3)
        graph.set_current_frame(0)
        graph.show()
        qt_app.processEvents()
        graph.canvas.draw()
        graph.set_current_frame(24, playing=True)
        qt_app.processEvents()
        assert graph._next_window is not None
        assert graph._window_image is not None
        limits = graph._next_window.limits
        assert limits == pytest.approx((2.7, 5.7))
        graph.set_current_frame(31, playing=True)
        assert graph.axis.get_xlim() == (0, 3)
        assert list(graph._cursor.get_xdata()) == [3.1, 3.1]
        render_ready.set()
        image = graph._window_image.result(timeout=15)
        qt_app.processEvents()
        redraws = []
        graph.canvas.mpl_connect("draw_event", redraws.append)
        graph.set_current_frame(32, playing=True)
        qt_app.processEvents()
        assert graph._plot_background is image and not redraws
        assert graph._next_window is None
        assert all(axis.get_xlim() == limits for axis in graph.figure.axes)
        assert np.max(graph._lines["angle_right_hip"].get_xdata()) <= 5.8
        assert list(graph._cursor.get_xdata()) == [3.2, 3.2]
    finally:
        render_ready.set()
        graph.close()


def test_desktop_viewer_all_graphs_motion_components_and_frame_details(qt_app, tmp_path, monkeypatch):
    video = tmp_path / "clip_skeleton.mp4"
    parquet = tmp_path / "clip_features.parquet"
    write_video(video, 5)
    frames = pd.DataFrame({
        "frame_id": range(5), "timestamp_s": np.arange(5) / 24,
        "angle_3d_right_knee": 100.0,
        "review_world_lm26_x": 0.25, "review_world_lm26_y": 0.4, "review_world_lm26_z": 0.12,
        "review_world_lm26_vx": 0.1, "review_world_lm26_vy": 0.2, "review_world_lm26_vz": 0.3,
        "review_world_lm26_speed": 0.374,
        "review_world_distance_knee_to_knee": 0.6, "review_world_distance_rate_knee_to_knee": -0.2,
        "review_world_distance_acceleration_knee_to_knee": 0.125,
        "review_cross_mean_angle_right_knee": 95.0,
        "review_cross_mean_lm26_x": 0.21, "review_cross_mean_lm26_y": 0.41,
        "review_cross_mean_distance_knee_to_knee": 0.5,
        "review_cross_mean_distance_rate_knee_to_knee": -0.1,
        "review_cross_mean_distance_acceleration_knee_to_knee": 0.25,
    })
    frames.to_parquet(parquet, index=False)
    viewer = InteractiveGraphViewer(video, parquet)
    try:
        viewer.resize(1500, 900)
        viewer.show()
        graph = viewer.graph
        viewer.graph_mode.setCurrentText(ALL_GRAPHS_MODE)
        graph.angle_source.setCurrentText(WORLD_SOURCE)
        graph.landmark_component.setCurrentIndex(graph.landmark_component.findData("positions-speed"))
        assert viewer.goto_frame(3)
        qt_app.processEvents()
        graph.canvas.draw()
        assert graph.source_label.text() == "Source values"
        assert graph.landmark_component.currentText() == "X, Y, Z + speed"
        angle, position, distance, speed = graph.figure.axes
        assert position.get_position().x0 == pytest.approx(speed.get_position().x0)
        assert distance.get_position().y0 == pytest.approx(speed.get_position().y0)
        assert set(graph._panels[position].lines) == {"landmark_26|x", "landmark_26|y", "landmark_26|z"}
        assert position.get_ylim() != speed.get_ylim()
        assert all(axis.get_xlim() == angle.get_xlim() and axis.get_ylabel() for axis in graph.figure.axes)
        assert speed.get_xlabel() == "Elapsed source time (s)"
        for axis in (angle, position, speed, distance):
            assert axis.yaxis.label.get_window_extent().x0 >= 0
        card = graph.sample_card.text()
        assert "Frame Details" in card and "Angle 100.00°" in card
        assert "Position XYZ" in card and "Speed 0.374 m/s" in card
        assert "Distance rate (m/s): -0.2000" in card
        assert "Distance acceleration (m/s²): +0.1250" in card
        document = QTextDocument()
        document.setHtml(card)
        table, = document.rootFrame().childFrames()
        assert [table.cellAt(0, i).format().toTableCellFormat().leftBorder() for i in range(3)] == [0, 1, 1]
        (_, horizontal, vertical), = graph._panel_dividers
        strong_width = horizontal.get_linewidth()
        assert vertical.get_linewidth() == strong_width
        assert graph.chart_scroll.verticalScrollBar().maximum() == 0
        card_height = graph.sample_card.height()
        t = viewer.timestamps[2]
        x, y = angle.transData.transform((t, 100))
        graph._on_motion(SimpleNamespace(inaxes=angle, xdata=t, x=x, y=y))
        qt_app.processEvents()
        assert "(hovered sample)" in graph.sample_card.text()
        assert graph.sample_card.height() == card_height
        assert graph.sample_card.heightForWidth(graph.sample_card.width()) <= card_height
        graph._clear_hover()

        graph.show_all_sources.setChecked(True)
        qt_app.processEvents()
        assert graph.chart_scroll.verticalScrollBar().maximum() > 0
        visible_ranges = []
        draw_artists = graph._draw_frame_artists

        def track_draw(visible_y=None):
            visible_ranges.append(visible_y)
            draw_artists(visible_y)

        with monkeypatch.context() as scoped:
            scoped.setattr(graph, "_draw_frame_artists", track_draw)
            graph._paint_frame_artists()
        assert visible_ranges and visible_ranges[-1] is not None
        assert np.diff(visible_ranges[-1])[0] < graph._plot_background.get_extents()[3]
        assert graph.sample_card.y() >= graph.chart_scroll.geometry().bottom()
        graph.angle_source.setCurrentText(MEAN_SOURCE)
        assert "Position XY" in graph.sample_card.text() and "Position XYZ" not in graph.sample_card.text()
        assert "Angle 95.00°" in graph.sample_card.text()
        assert "Distance acceleration (torso lengths/s²): +0.2500" in graph.sample_card.text()
        assert len(graph._source_dividers) == 3
        assert len(graph._panel_dividers) == 4
        assert all(line.get_linewidth() < strong_width for _, *lines in graph._panel_dividers for line in lines)
        for line, (_, above), (below, _) in zip(graph._source_dividers, graph._source_groups, graph._source_groups[1:]):
            y, end = line.get_ydata()
            assert y == end and below.get_position().y1 < y < above.get_position().y0
            assert line.get_linewidth() == strong_width

        assert viewer.goto_frame(0)
        graph.canvas.draw()
        world_angle = graph._source_groups[1][0]
        t = viewer.timestamps[3]
        x, y = world_angle.transData.transform((t, 100))
        local = QPointF(x, graph.canvas.height() - y)

        def wheel(pixels, steps, modifiers=Qt.KeyboardModifier.NoModifier):
            event = QWheelEvent(local, QPointF(graph.canvas.mapToGlobal(local.toPoint())), QPoint(0, pixels),
                                QPoint(0, steps), Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.ScrollUpdate, False)
            QApplication.sendEvent(graph.canvas, event)

        limits = graph.axis.get_xlim()
        bar = graph.chart_scroll.verticalScrollBar()
        start = bar.value()
        wheel(-60, 0)
        assert bar.value() == start + 60 and graph.axis.get_xlim() == limits
        wheel(0, -120)
        assert bar.value() > start + 60 and graph.axis.get_xlim() == limits
        wheel(60, 0, Qt.KeyboardModifier.ShiftModifier)
        qt_app.processEvents()
        assert graph.axis.get_xlim()[0] == viewer.timestamps[0]
        assert np.diff(graph.axis.get_xlim())[0] < np.diff(limits)[0]
        assert viewer.current_frame == 0
        assert all(list(panel.cursor.get_xdata()) == [viewer.timestamps[0]] * 2 for panel in graph._panels.values())
        limits = graph.axis.get_xlim()
        x, y = world_angle.transData.transform((viewer.timestamps[2], 100))
        local = QPointF(x, graph.canvas.height() - y)
        scroll_position = bar.value()
        wheel(0, 120, Qt.KeyboardModifier.ControlModifier)
        assert viewer.current_frame == 0
        assert graph.axis.get_xlim()[0] == viewer.timestamps[0]
        graph.axis.set_xlim(*limits)
        graph.zoom_to_seek.click()
        wheel(0, 120, Qt.KeyboardModifier.ShiftModifier)
        assert np.diff(graph.axis.get_xlim())[0] < np.diff(limits)[0]
        assert viewer.current_frame == 2
        assert bar.value() == scroll_position
        assert sum(graph.axis.get_xlim()) / 2 == pytest.approx(viewer.timestamps[2])
        assert all(list(panel.cursor.get_xdata()) == [viewer.timestamps[2]] * 2 for panel in graph._panels.values())

        viewer.graph_mode.setCurrentText(ANGLE_MODE)
        qt_app.processEvents()
        assert graph.show_all_sources.isChecked()
        assert len(graph.figure.axes) == 4
        assert bar.maximum() == 0 and not graph._source_dividers
        (_, horizontal, vertical), = graph._panel_dividers
        assert horizontal.get_linewidth() == vertical.get_linewidth() == strong_width
        graph.canvas.draw()
        renderer = graph.canvas.get_renderer()
        upper = graph.figure.axes[:2]
        lower = graph.figure.axes[2:]
        divider_y = graph.figure.transFigure.transform((0, horizontal.get_ydata()[0]))[1]
        assert max(axis.get_tightbbox(renderer).y1 for axis in lower) < divider_y
        assert divider_y < min(axis.get_tightbbox(renderer).y0 for axis in upper)
        assert all(axis.get_xticklabels() for axis in upper)
        assert all(axis.get_xlabel() == "Elapsed source time (s)" for axis in lower)
    finally:
        viewer.close()


def test_show_all_angle_sources_leaves_missing_measurements_empty(qt_app):
    graph = JointGraphWidget(pd.DataFrame({
        "frame_id": [0, 1], "timestamp_s": [0.0, 0.04],
        "angle_2d_right_hip": [42.0, 60.0], "angle_right_hip": [70.0, 90.0],
    }))
    try:
        graph.show_all_sources.click()
        torso, world, legacy, mean = graph.figure.axes

        def has_hip_data(axis):
            return any(line.get_label() == "Right Hip" and np.isfinite(line.get_ydata()).any()
                       for line in axis.lines)

        assert not has_hip_data(torso)
        assert has_hip_data(legacy)
        assert not has_hip_data(world)
        assert not has_hip_data(mean)
    finally:
        graph.close()


@pytest.mark.parametrize("saved_spatial_angles", [False, True])
def test_launcher_opens_read_only_graph_workspace(qt_app, tmp_path, monkeypatch, detail, saved_spatial_angles):
    detail(input="12-frame video and Parquet with an existing annotation sidecar",
           expected="The launcher shows the graph workspace and both directions of frame navigation work")
    video = tmp_path / "clip_skeleton.mp4"
    parquet = tmp_path / "clip_features.parquet"
    annotation = tmp_path / "clip_annotations.json"
    annotation.write_bytes(b"annotation contents must stay untouched")
    write_video(video, 12)
    frames = pd.DataFrame({
        "frame_id": range(12),
        "timestamp_s": np.arange(12) / 24,
        "angle_right_knee": np.linspace(80, 120, 12),
        "lm24_x": 0.5, "lm24_y": 0.3,
        "lm26_x": 0.5, "lm26_y": 0.5,
        "lm28_x": 0.6, "lm28_y": 0.6,
    })
    if saved_spatial_angles:
        frames["angle_2d_right_knee"] = 31.0
        frames["angle_torso2d_right_knee"] = 42.0
        frames["angle_3d_right_knee"] = 90.0
        frames["review_cross_mean_angle_right_knee"] = 71.0
        frames["review_cross_mean_angle_right_knee_source_count"] = 3
        frames["review_omega_review_cross_mean_angle_right_knee"] = 15.0
        for suffix, value in {"x": .2, "y": .7, "vx": .1, "vy": .2, "ax": .3, "ay": .4, "speed": .22}.items():
            frames[f"review_cross_mean_lm26_{suffix}"] = value

        def reject_recalculation(*args, **kwargs):
            pytest.fail("The saved spatial angles should be consumed directly.")

        monkeypatch.setattr("aihumo.features.FeatureEngine._calculate_angles", reject_recalculation)
    frames.to_parquet(parquet, index=False)
    original_features = parquet.read_bytes()
    selections = iter((str(video), str(parquet)))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (next(selections), ""))
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _, title, message: errors.append(message))
    home = HomeWindow(state_dir=tmp_path / "state")
    try:
        home.show()
        assert home.viewer_button.text().startswith("Interactive Graph Viewer")
        QTest.mouseClick(home.viewer_button, Qt.MouseButton.LeftButton)
        assert home.graph_window is None
        QTest.mouseDClick(home.viewer_button, Qt.MouseButton.LeftButton)
        assert not errors
        viewer = home.graph_window
        assert isinstance(viewer, InteractiveGraphViewer)
        assert viewer.isVisible() and viewer.graph.isVisible()
        assert home.annotation_window is None
        expected_source = "Torso-normalized 2D" if saved_spatial_angles else "Legacy (normalized image)"
        assert viewer.graph.angle_source.currentText() == expected_source
        assert viewer.graph.angle_source.findText("Video plane (2D)") == -1
        assert ("Angle 42.00°" if saved_spatial_angles else "Angle 80.00°") in viewer.graph.sample_card.text()
        if saved_spatial_angles:
            viewer.graph.angle_source.setCurrentText("Estimated world (3D)")
            assert "Angle 90.00°" in viewer.graph.sample_card.text()
            viewer.graph.angle_source.setCurrentText(MEAN_SOURCE)
            card = viewer.graph.sample_card.text()
            assert "Angle 71.00°" in card and "Angular velocity +15.00 °/s" in card
            assert "Position XY (torso lengths, hip-relative) (0.200, 0.700)" in card
            assert "Velocity (torso lengths/s) (0.100, 0.200)" in card
            assert "Acceleration (torso lengths/s²) (0.300, 0.400)" in card
        viewer.graph.frameSelected.emit(7)
        assert viewer.current_frame == 7 and viewer.frame_spin.value() == 7
        viewer.slider.setValue(10)
        assert viewer.current_frame == 10
        assert list(viewer.graph._cursor.get_xdata()) == [10 / 24, 10 / 24]
        viewer.graph.angle_source.setCurrentText("Legacy (normalized image)")
        assert viewer.current_frame == 10 and "Angle 116.36°" in viewer.graph.sample_card.text()
        assert parquet.read_bytes() == original_features
        assert annotation.read_bytes() == b"annotation contents must stay untouched"
        assert viewer.back_button.isVisible() and viewer.back_button.text() == "Back to menu"
        viewer.back_button.click()
        assert home.isVisible() and home.graph_window is None and not viewer.isVisible()
        assert home.resume_group.title().startswith("Resume Mode 3")
        assert home.resume_combo.currentText().endswith("(frame 10)")
        detail(observed="Graph clicked to frame 7; slider moved to frame 10; Back returned to menu and saved frame 10.")
    finally:
        if home.graph_window is not None:
            home.graph_window.close()
        home.close()


@pytest.mark.parametrize("custom_annotation_path", [False, True])
def test_launcher_graph_opens_matching_annotation_at_current_frame(qt_app, tmp_path, monkeypatch, custom_annotation_path):
    recording = tmp_path / "recording"
    video = recording / "video" / "clip_skeleton.mp4"
    parquet = recording / "parquet" / "clip_features.parquet"
    annotation = (tmp_path / "notes.json" if custom_annotation_path
                  else recording / "annotations" / "clip_annotations.json")
    video.parent.mkdir(parents=True)
    parquet.parent.mkdir()
    write_video(video, 12)
    pd.DataFrame({
        "frame_id": range(12), "timestamp_s": np.arange(12) / 24,
        "angle_right_knee": 100.0, "lm26_x": 0.5, "lm26_y": 0.5,
    }).to_parquet(parquet, index=False)
    state = AnnotationState.new({"session_id": "S001", "video_id": "clip"})
    state.add({
        "annotation_id": "A00001", "segment_id": "clip_SEG0001",
        "annotation_type": "general", "activity_state": "idle", "start_frame": 0, "end_frame": 3,
    })
    save_json_atomic(state.to_document(), annotation)
    original = annotation.read_bytes()

    def unexpected_dialog(*args):
        pytest.fail("The matching annotation session should open without a picker or error dialog.")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", unexpected_dialog)
    monkeypatch.setattr(QMessageBox, "critical", unexpected_dialog)
    home = HomeWindow(state_dir=tmp_path / "state")
    try:
        home.show()
        if custom_annotation_path:
            home.recent_work.add(name="Custom annotation", files={
                "processedVideo": str(video), "featuresParquet": str(parquet), "annotationJson": str(annotation),
            })
        home._show_graph_viewer(video_path=video, parquet_path=parquet, frame=7)
        viewer = home.graph_window
        assert viewer.back_button.text() == "Back to menu"
        assert viewer.open_annotations_button.isVisible()
        viewer.play_button.click()
        assert viewer.playback.playing
        viewer.graph._window_prefetch.start(60_000)
        viewer.open_annotations_button.click()
        studio = home.annotation_window
        assert viewer.review_suspended and not viewer.playback.playing
        assert not viewer.graph._window_prefetch.isActive()
        assert studio.annotation_json_path == annotation
        assert studio.current_frame == 7
        assert [row["annotation_id"] for row in studio.annotations] == ["A00001"]
        assert studio.back_button.text() == "Back to graph viewer"

        studio.play_button.click()
        assert studio.playback.playing and not viewer.playback.playing
        assert studio._show_frame(8)
        studio.play_button.click()
        assert viewer.current_frame == 7 and viewer._deferred_linked_frame == 8
        studio.goto_frame(9)
        studio.start_range_capture()
        studio.graph_viewer_button.click()
        assert studio.review_suspended and not viewer.review_suspended
        assert viewer.current_frame == 9
        viewer.goto_frame(10)
        assert studio.current_frame == 9 and studio._deferred_linked_frame == 10
        viewer.open_annotations_button.click()
        assert home.annotation_window is studio and studio.current_frame == 10
        assert viewer.review_suspended and not studio.review_suspended
        assert studio.annotation_start_frame == 9
        studio.cancel_range_capture()
        studio.goto_frame(4)
        studio.overlay_button.setChecked(True)
        studio.graph_viewer_button.click()
        assert studio.annotation_graph_window is None
        assert home.graph_window is viewer and viewer.current_frame == 4
        assert viewer.overlay_button.isChecked() and viewer.preview._labels
        studio.back_button.click()
        assert home.annotation_window is None and viewer.isVisible()
        viewer.back_button.click()
        assert home.graph_window is None and home.isVisible()
        assert annotation.read_bytes() == original
    finally:
        home.close()


def test_graph_viewer_links_playback_pan_and_zoom_to_native_frames(qt_app, tmp_path, detail, monkeypatch):
    monkeypatch.setattr("app.playback.monotonic", lambda: 0.0)
    detail(input="60 video frames with irregular Parquet timestamps",
           expected="Playback follows the cursor, pan seeks on release, and zoom preserves the current frame")
    video = tmp_path / "clip_skeleton.mp4"
    parquet = tmp_path / "clip_features.parquet"
    write_video(video, 60)
    times = np.r_[0, np.cumsum(np.resize([0.025, 0.041, 0.055], 59))]
    pd.DataFrame({
        "frame_id": range(len(times)), "timestamp_s": times,
        "angle_right_knee": np.linspace(80, 120, len(times)),
    }).to_parquet(parquet, index=False)
    viewer = InteractiveGraphViewer(video, parquet)
    graph = viewer.graph
    try:
        viewer.goto_frame(8)
        zoom_in = next(button for button in graph.findChildren(QPushButton) if button.text() == "+")
        for _ in range(4):
            zoom_in.click()
        qt_app.processEvents()
        assert viewer.current_frame == 8
        graph.canvas.draw()
        graph.toolbar.pan()
        bbox = graph.axis.bbox
        y = bbox.y0 + bbox.height / 2
        start, end = bbox.x0 + bbox.width * 0.75, bbox.x0 + bbox.width * 0.25
        for name, x in (("button_press_event", start), ("motion_notify_event", end)):
            event = MouseEvent(name, graph.canvas, x, y, button=1)
            if name == "motion_notify_event" and hasattr(event, "buttons"):
                event.buttons = frozenset({MouseButton.LEFT})
            graph.canvas.callbacks.process(name, event)
        assert viewer.current_frame == 8
        name = "button_release_event"
        graph.canvas.callbacks.process(name, MouseEvent(name, graph.canvas, end, y, button=1))
        center = sum(graph.axis.get_xlim()) / 2
        panned_frame = int(np.argmin(abs(times - center)))
        assert viewer.current_frame == panned_frame > 8
        assert list(graph._cursor.get_xdata()) == [times[panned_frame]] * 2
        graph.toolbar.pan()

        # A zoom or toolbar history entry can put the selected frame offscreen.
        viewer.goto_frame(28)
        graph.axis.set_xlim(times[39], times[49])
        assert not graph.zoom_to_seek.isChecked()
        graph._on_scroll(SimpleNamespace(inaxes=graph.axis, xdata=times[45], button="up"))
        assert sum(graph.axis.get_xlim()) / 2 == pytest.approx(times[28])
        assert viewer.current_frame == 28
        graph.toolbar.pan()
        graph._on_click(SimpleNamespace(inaxes=graph.axis, xdata=times[29], button=1))
        wheel = SimpleNamespace(inaxes=graph.axis, xdata=times[29], button="up", key="control")
        graph._on_scroll(wheel)
        graph._on_graph_release(SimpleNamespace(button=1))
        assert viewer.current_frame == 28
        assert sum(graph.axis.get_xlim()) / 2 == pytest.approx(times[28])
        graph.toolbar.pan()
        graph.toolbar.zoom()
        graph.canvas.draw()
        bbox = graph.axis.bbox
        y = bbox.y0 + bbox.height / 2
        start, end = bbox.x0 + bbox.width * 0.65, bbox.x0 + bbox.width * 0.9
        for button in (MouseButton.LEFT, MouseButton.RIGHT):
            old_width = np.diff(graph.axis.get_xlim())[0]
            for name, x in (("button_press_event", start), ("button_release_event", end)):
                graph.canvas.callbacks.process(name, MouseEvent(name, graph.canvas, x, y, button=button))
            assert (np.diff(graph.axis.get_xlim())[0] < old_width) == (button == MouseButton.LEFT)
            assert sum(graph.axis.get_xlim()) / 2 == pytest.approx(times[28])
            assert viewer.current_frame == 28
        graph.toolbar.zoom()
        graph.toolbar.pan()
        old_width = np.diff(graph.axis.get_xlim())[0]
        for name, x in (("button_press_event", start), ("button_release_event", end)):
            graph.canvas.callbacks.process(name, MouseEvent(name, graph.canvas, x, y, button=MouseButton.RIGHT))
        assert np.diff(graph.axis.get_xlim())[0] < old_width
        assert sum(graph.axis.get_xlim()) / 2 == pytest.approx(times[28])
        assert viewer.current_frame == 28
        graph.toolbar.pan()
        graph.zoom_to_seek.click()
        graph.axis.set_xlim(times[24], times[34])
        graph.canvas.draw()
        graph.toolbar.zoom()
        mid_y = sum(graph.axis.get_ylim()) / 2
        for name, time in (("button_press_event", times[29]), ("button_release_event", times[31])):
            x, y = graph.axis.transData.transform((time, mid_y))
            graph.canvas.callbacks.process(name, MouseEvent(name, graph.canvas, x, y, button=MouseButton.LEFT))
        assert viewer.current_frame == 30
        graph.toolbar.zoom()
        graph.axis.set_xlim(times[24], times[34])
        graph._on_scroll(SimpleNamespace(inaxes=graph.axis, xdata=times[32], button="down"))
        assert viewer.current_frame == 32
        assert sum(graph.axis.get_xlim()) / 2 == pytest.approx(times[32])
        graph.zoom_to_seek.click()
        graph.axis.set_xlim(times[39], times[41])
        qt_app.processEvents()
        assert viewer.current_frame == 32
        graph._on_click(SimpleNamespace(inaxes=graph.axis, xdata=times[40], button=1))
        expected = 40
        assert viewer.current_frame == expected
        assert viewer.slider.value() == viewer.frame_spin.value() == expected
        assert f"{times[expected]:.6f} s" in viewer.frame_label.text()

        viewer.play_button.click()
        assert viewer.playback.timer.isActive()
        # Test cursor synchronization without depending on decoder thread timing.
        viewer.playback.ready_frame = None
        for _ in range(4):
            viewer.playback.advance()
        viewer.play_button.click()
        qt_app.processEvents()
        current = expected + 4
        assert viewer.current_frame == current
        assert list(graph._cursor.get_xdata()) == [times[current]] * 2
        assert graph.axis.get_xlim()[0] <= times[current] <= graph.axis.get_xlim()[1]
        assert graph.axis.get_xlim()[1] - graph.axis.get_xlim()[0] == pytest.approx(times[41] - times[39])
        detail(observed=f"Pan sought frame {panned_frame}; zoom held the frame; click sought {expected}; playback tracked {current}")
    finally:
        viewer.close()


def test_viewer_arrow_keys_step_frames_regardless_of_focus(qt_app, tmp_path, detail):
    detail(input="Viewer keys after clicking Previous, the plot, and the frame field",
           expected="Left/Right step one frame, Up/Down use the jump control, and Tab still moves focus")
    video = tmp_path / "clip_skeleton.mp4"
    parquet = tmp_path / "clip_features.parquet"
    write_video(video, 12)
    times = np.arange(12) / 24
    angles = np.linspace(80, 120, 12)
    pd.DataFrame({
        "frame_id": range(12), "timestamp_s": times, "angle_right_knee": angles,
    }).to_parquet(parquet, index=False)
    viewer = InteractiveGraphViewer(video, parquet)
    other_window = QSpinBox()
    try:
        viewer.resize(1200, 760)
        viewer.show()
        viewer.activateWindow()
        qt_app.processEvents()
        viewer.goto_frame(4)
        previous = next(button for button in viewer.findChildren(QPushButton) if button.text() == "Previous")
        QTest.mouseClick(previous, Qt.MouseButton.LeftButton)
        assert viewer.current_frame == 3
        QTest.keyClick(previous, Qt.Key.Key_Right)
        assert viewer.current_frame == 4
        assert qt_app.focusWidget() is previous
        QTest.keyClick(previous, Qt.Key.Key_Tab)
        assert qt_app.focusWidget() is viewer.play_button

        canvas = viewer.graph.canvas
        canvas.draw()
        x, y = viewer.graph.axis.transData.transform((times[7], angles[7]))
        scale = canvas.devicePixelRatioF()
        point = QPoint(round(x / scale), round(canvas.height() - y / scale))
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
        assert viewer.current_frame == 7
        QTest.keyClick(canvas, Qt.Key.Key_Left)
        assert viewer.current_frame == 6
        assert list(viewer.graph._cursor.get_xdata()) == [times[6]] * 2

        viewer.frame_spin.lineEdit().setFocus()
        assert viewer.jump_spin.value() == 50
        QTest.keyClick(viewer.frame_spin.lineEdit(), Qt.Key.Key_Up)
        assert viewer.current_frame == 11
        QTest.keyClick(viewer.frame_spin.lineEdit(), Qt.Key.Key_Down)
        assert viewer.current_frame == 0
        viewer.jump_spin.setValue(3)
        QTest.keyClick(canvas, Qt.Key.Key_Up)
        assert viewer.current_frame == 3
        next(button for button in viewer.findChildren(QPushButton) if button.text() == "+Jump").click()
        assert viewer.current_frame == 6
        QTest.keyClick(canvas, Qt.Key.Key_Down)
        assert viewer.current_frame == 3
        QTest.keyClick(other_window, Qt.Key.Key_Up)
        assert other_window.value() == 1 and viewer.current_frame == 3

        buttons = {button.text(): button for button in viewer.findChildren(QPushButton)}
        for label, target in (("Previous", 2), ("Next", 3), ("+Jump", 6), ("−Jump", 3)):
            start = viewer.current_frame
            viewer.play_button.click()
            assert viewer.playback.playing
            QTest.mousePress(buttons[label], Qt.MouseButton.LeftButton)
            assert not viewer.playback.playing and not viewer.playback.timer.isActive()
            assert viewer.current_frame == start
            QTest.mouseRelease(buttons[label], Qt.MouseButton.LeftButton)
            assert viewer.current_frame == target

        viewer.play_button.click()
        for _ in range(8):
            QTest.mouseClick(previous, Qt.MouseButton.LeftButton)
        qt_app.processEvents()
        assert viewer.isVisible() and not viewer.playback.playing and viewer.current_frame == 0
        detail(observed="Single-frame stepping retained focus; custom jump moved 0 → 3 → 6 → 3.")
    finally:
        other_window.close()
        viewer.close()


def test_hold_frame_controls_use_source_timing_and_release_without_a_tap(qt_app, tmp_path, monkeypatch):
    from app import playback

    video = tmp_path / "clip_skeleton.mp4"
    parquet = tmp_path / "clip_features.parquet"
    write_video(video, 30)
    pd.DataFrame({"frame_id": range(30), "timestamp_s": np.arange(30) / 24,
                  "angle_right_knee": 100.0}).to_parquet(parquet, index=False)
    now = 100.0
    monkeypatch.setattr(playback, "monotonic", lambda: now)
    viewer = InteractiveGraphViewer(video, parquet)
    try:
        viewer.show()
        viewer.activateWindow()
        qt_app.processEvents()
        viewer.playback.ready_frame = None
        assert viewer.speed_control.currentData() == 1.0
        assert viewer.jump_spin.value() == 50
        buttons = {button.text(): button for button in viewer.findChildren(playback.FrameNavigationButton)}
        for label, speed, expected in (("Previous", 2.0, 8), ("Next", 2.0, 12),
                                       ("+Jump", 2.0, 14), ("−Jump", 0.5, 9)):
            viewer.goto_frame(10)
            viewer.speed_control.setCurrentIndex(viewer.speed_control.findData(speed))
            button = buttons[label]
            QTest.mousePress(button, Qt.MouseButton.LeftButton)
            assert button._hold_timer.isActive() and button._hold_timer.interval() == 3000
            assert not viewer.playback.playing and viewer.current_frame == 10
            button._hold_timer.timeout.emit()
            assert viewer.playback.holding
            now += 2.25 / 24
            viewer.playback.advance()
            assert viewer.current_frame == expected
            QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
            assert not viewer.playback.playing and viewer.current_frame == expected
        viewer.goto_frame(0)
        previous = buttons["Previous"]
        QTest.mousePress(previous, Qt.MouseButton.LeftButton)
        previous._hold_timer.timeout.emit()
        QTest.mouseRelease(previous, Qt.MouseButton.LeftButton)
        assert not viewer.playback.playing and viewer.current_frame == 0
        viewer.play_button.click()
        assert viewer.playback.timer.interval() == 83
        viewer.speed_control.setCurrentIndex(viewer.speed_control.findData(2.0))
        assert viewer.playback.timer.interval() == 21

        viewer.goto_frame(10)
        QTest.mousePress(previous, Qt.MouseButton.LeftButton)
        previous._hold_timer.timeout.emit()
        assert viewer.playback.holding
        viewer.speed_control.setFocus()
        assert not viewer.playback.playing
        QTest.mouseRelease(previous, Qt.MouseButton.LeftButton)
        assert viewer.current_frame == 10
    finally:
        viewer.close()


def test_launcher_resumes_graph_and_annotation_independently(qt_app, tmp_path, monkeypatch, detail):
    detail(input="Same 12-frame recording for both modes, annotation ending at frame 3 and graph at frame 9",
           expected="Graph preview keeps native controls and returns to Mode 1; Back respects unfinished annotation edits")
    state_dir = tmp_path / "state"
    store = PreferenceStore(state_dir / "settings.json")
    store.save(DesktopPreferences(launcher_accent="#1155cc"))
    settings = PreferencesDialog(store)
    assert settings.default_frame_jump.value() == 50
    settings.default_frame_jump.setValue(8)
    settings._save()
    assert PreferenceStore(store.path).values.default_frame_jump == 8
    video = tmp_path / "clip_skeleton.mp4"
    parquet = tmp_path / "clip_features.parquet"
    annotation = tmp_path / "notes.json"
    write_video(video, 12)
    pd.DataFrame({
        "frame_id": range(12), "timestamp_s": np.arange(12) / 24,
        "angle_right_knee": np.linspace(80, 120, 12),
    }).to_parquet(parquet, index=False)
    state = AnnotationState.new({"session_id": "S001", "video_id": "clip"})
    state.add({
        "annotation_id": "A00001", "segment_id": "clip_SEG0001",
        "annotation_type": "general", "activity_state": "idle", "start_frame": 0, "end_frame": 3,
    })
    save_json_atomic(state.to_document(), annotation)
    before = annotation.read_bytes()
    paths = {"processedVideo": str(video), "featuresParquet": str(parquet)}
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _, title, message: errors.append(message))
    first = HomeWindow(state_dir=state_dir)
    try:
        first.recent_work.add(name="Annotation", files={**paths, "annotationJson": str(annotation)})
        first._show_graph_viewer(video_path=video, parquet_path=parquet)
        assert not errors
        first.graph_window.goto_frame(9)
    finally:
        first.close()
    qt_app.processEvents()

    def unexpected_picker(*args):
        pytest.fail("Resume should use saved paths without opening a file picker.")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", unexpected_picker)
    reopened = HomeWindow(state_dir=state_dir)
    try:
        reopened._select_mode(3)
        assert reopened.resume_combo.currentText().endswith("(frame 9)")
        reopened.resume_graph_work()
        assert not errors
        assert reopened.graph_window.current_frame == 9
        assert reopened.graph_window.jump_spin.value() == 8
        assert reopened.viewer_button.isChecked() and "#1155cc" in reopened.viewer_button.styleSheet()
        assert not hasattr(reopened.graph_window, "thumbnails")
        reopened.resume_selected_work()
        assert not errors
        assert reopened.annotation_window.current_frame == 3
        assert reopened.annotate_button.isChecked() and not reopened.viewer_button.isChecked()
        assert not hasattr(reopened.annotation_window, "thumbnail_labels")
        studio = reopened.annotation_window
        assert studio.jump_spin.value() == 8
        studio.jump_spin.setValue(4)
        assert PreferenceStore(store.path).values.default_frame_jump == 8
        resume_path = state_dir / "recent_graphs.json"
        resume_before = resume_path.read_bytes()
        assert studio.graph_viewer_button.text() == "Interactive Graph Viewer"
        studio.graph_viewer_button.click()
        assert not errors
        preview = studio.annotation_graph_window
        assert isinstance(preview, InteractiveGraphViewer)
        assert preview is not reopened.graph_window
        assert preview.isMaximized() and not preview.isFullScreen() and preview.graph.isVisible()
        for hint in (Qt.WindowType.WindowMinimizeButtonHint, Qt.WindowType.WindowMaximizeButtonHint,
                     Qt.WindowType.WindowCloseButtonHint):
            assert preview.windowFlags() & hint
        assert preview.current_frame == 3
        assert preview.jump_spin.value() == 4
        assert preview.video_path == video and preview.parquet_path == parquet
        assert preview.goto_frame(6)
        assert preview.back_button.isVisible() and preview.back_button.text() == "Back to annotation"
        preview.back_button.click()
        assert studio.annotation_graph_window is None and studio.current_frame == 6
        assert studio.isVisible() and not preview.isVisible()
        assert reopened.graph_window.current_frame == 9
        assert resume_path.read_bytes() == resume_before
        assert annotation.read_bytes() == before

        assert studio.back_button.isVisible() and studio.back_button.text() == "Back to menu"
        studio.start_range_capture()
        decisions = iter((QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Discard))
        monkeypatch.setattr(QMessageBox, "question", lambda *args: next(decisions, QMessageBox.StandardButton.Discard))
        studio.back_button.click()
        assert studio.isVisible() and studio.annotation_start_frame == 6
        studio.back_button.click()
        assert reopened.isVisible() and reopened.annotation_window is None and not studio.isVisible()
        assert annotation.read_bytes() == before
        detail(observed="Graph preview maximized with native controls. Mode 1 followed the linked preview to frame 6, and the separate graph bookmark stayed at frame 9.")
    finally:
        if reopened.annotation_window is not None:
            reopened.annotation_window.close()
        reopened.close()
        first.deleteLater()
        reopened.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_annotation_range_only_overwrites_after_explicit_edit(qt_app, tmp_path, monkeypatch):
    from app import mode1_annotation

    video = tmp_path / "clip_skeleton.mp4"
    parquet = tmp_path / "clip_features.parquet"
    annotation = tmp_path / "notes.json"
    write_video(video, 12)
    pd.DataFrame({"frame_id": range(12), "timestamp_s": np.arange(12) / 24}).to_parquet(parquet, index=False)
    state = AnnotationState.new({"session_id": "S001", "video_id": "clip"})
    for index, (start, end) in enumerate(((1, 3), (5, 7)), start=1):
        state.add({
            "annotation_id": f"A{index:05d}", "segment_id": f"clip_SEG{index:04d}",
            "annotation_type": "general", "activity_state": "idle", "start_frame": start, "end_frame": end,
            "start_time_s": start / 24, "end_time_s": end / 24, "notes": f"Original note {index}",
        })
    save_json_atomic(state.to_document(), annotation)

    messages = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _, title, body: messages.append((title, body)))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Discard)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    studio = mode1_annotation.open_annotation_studio(
        video_path=video, parquet_path=parquet, annotation_json_path=annotation,
    )
    table = studio.annotation_table
    studio.show_all_annotation_layers.setChecked(True)

    def saved_rows():
        return {item["annotation_id"]: item for item in load_json(annotation)["annotations"]}

    def select_first_row():
        index = table.model().index(0, 0)
        table.scrollTo(index)
        qt_app.processEvents()
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=table.visualRect(index).center())
        assert table.selectionModel().selectedRows()[0].row() == 0

    def press(key):
        table.setFocus()
        QTest.keyClick(table, key)

    try:
        studio.activateWindow()
        qt_app.processEvents()
        before = saved_rows()
        assert studio.goto_frame(9)
        select_first_row()
        assert studio.current_frame == 9 and studio.annotation_edit_id is None
        press(Qt.Key.Key_S)
        assert saved_rows() == before

        press(Qt.Key.Key_A)
        assert studio.annotation_edit_id == "A00001"
        assert studio.editor_notes.toPlainText() == "Original note 1"
        studio.editor_notes.setFocus()
        studio.editor_notes.selectAll()
        QTest.keyClicks(studio.editor_notes, "Discard this draft")
        assert studio.editor_notes.toPlainText() == "Discard this draft"
        assert saved_rows() == before
        press(Qt.Key.Key_D)
        assert studio.annotation_edit_id is None
        assert not table.selectionModel().selectedRows()
        press(Qt.Key.Key_S)
        assert saved_rows() == before

        select_first_row()
        studio.edit_selected_button.click()
        assert studio.annotation_edit_id == "A00001"
        studio.editor_notes.setPlainText("Update original note")
        press(Qt.Key.Key_S)
        updated = saved_rows()
        assert not messages
        assert updated.keys() == before.keys()
        assert updated["A00002"] == before["A00002"]
        assert updated["A00001"]["notes"] == "Update original note"
        assert (updated["A00001"]["start_frame"], updated["A00001"]["end_frame"]) == (1, 3)
        assert studio.annotation_edit_id is None

        def fail_save(*args, **kwargs):
            raise OSError("Cannot write annotation file")

        select_first_row()
        press(Qt.Key.Key_A)
        studio.editor_notes.setPlainText("Failed update")
        with monkeypatch.context() as failed_write:
            failed_write.setattr(mode1_annotation, "save_json_atomic", fail_save)
            press(Qt.Key.Key_S)
        assert messages.pop()[0] == "Annotation save failed"
        assert studio.annotation_edit_id == "A00001"
        assert {item["annotation_id"]: item for item in studio.annotations} == saved_rows() == updated
        studio.editor_cancel_edit_button.click()
        assert studio.annotation_edit_id is None and not table.selectionModel().selectedRows()

        select_first_row()
        press(Qt.Key.Key_A)
        press(Qt.Key.Key_W)
        assert studio.annotation_edit_id is None and studio.annotation_start_frame == 1
        studio.editor_annotation_type.setCurrentIndex(studio.editor_annotation_type.findData("general"))
        studio.editor_notes.setPlainText("Separate annotation for the same range")
        assert studio.goto_frame(3)
        press(Qt.Key.Key_S)
        after = saved_rows()
        assert not messages
        assert {key: after[key] for key in updated} == updated
        new_id, = after.keys() - updated.keys()
        assert after[new_id]["notes"] == "Separate annotation for the same range"
        assert (after[new_id]["start_frame"], after[new_id]["end_frame"]) == (1, 3)
    finally:
        studio.close()


def test_annotation_table_highlights_warning_rows_and_updates_after_edit(qt_app, tmp_path):
    from app.mode1_annotation import open_annotation_studio

    video = tmp_path / "clip_skeleton.mp4"
    parquet = tmp_path / "clip_features.parquet"
    annotation = tmp_path / "notes.json"
    write_video(video, 12)
    pd.DataFrame({"frame_id": range(12), "timestamp_s": np.arange(12) / 24}).to_parquet(parquet)
    state = AnnotationState.new({"session_id": "S001", "video_id": "clip"})
    for number, kind, activity, start, end, rep, exercise in (
        (1, "activity_state", "active", 1, 4, None, None),
        (2, "activity_state", "transition", 6, 9, None, None),
        (3, "rep", "active", 2, 2, 1, "bodyweight_squat"),
        (4, "rep", "active", 3, 3, 3, None),
        (5, "general", "idle", 0, 0, None, None),
    ):
        state.add({
            "annotation_id": f"A{number:05d}", "segment_id": f"clip_SEG{number:04d}",
            "annotation_type": kind, "activity_state": activity, "start_frame": start, "end_frame": end,
            "start_time_s": start / 24, "end_time_s": end / 24,
            "set_id": 1 if rep is not None else None, "rep_id": rep, "exercise": exercise,
        })
    save_json_atomic(state.to_document(), annotation)
    studio = open_annotation_studio(video_path=video, parquet_path=parquet, annotation_json_path=annotation)
    model = studio.annotation_model
    studio.show_all_annotation_layers.setChecked(True)

    def cell(annotation_id):
        row = next(row for row in range(model.rowCount()) if model.index(row, 0).data() == annotation_id)
        return model.index(row, 1)

    try:
        assert "Warnings: 5" in studio.summary_label.text()
        first_warning = cell("A00001").data(Qt.ItemDataRole.ToolTipRole)
        last_warning = cell("A00002").data(Qt.ItemDataRole.ToolTipRole)
        assert "does not begin at frame 0" in first_warning
        assert "ends at frame 9" in last_warning
        assert all("gap: frame 5" in tooltip for tooltip in (first_warning, last_warning))
        for annotation_id in ("A00003", "A00005"):
            assert cell(annotation_id).data(Qt.ItemDataRole.ToolTipRole) is None
            assert cell(annotation_id).data(Qt.ItemDataRole.BackgroundRole) is None
        affected = cell("A00004")
        tooltip = affected.data(Qt.ItemDataRole.ToolTipRole)
        tint = affected.data(Qt.ItemDataRole.BackgroundRole).color()
        assert 0 < tint.alpha() < 255 and tint.red() > tint.green()
        assert "not sequential" in tooltip and "no exercise label" in tooltip

        studio.annotation_table.selectRow(affected.row())
        studio.edit_selected_button.click()
        studio.editor_rep_id.setValue(2)
        studio.editor_save_button.click()
        assert "Warnings: 4" in studio.summary_label.text()
        assert "not sequential" not in cell("A00004").data(Qt.ItemDataRole.ToolTipRole)
        assert "no exercise label" in cell("A00004").data(Qt.ItemDataRole.ToolTipRole)
        saved = load_json(annotation)["annotations"]
        assert next(row for row in saved if row["annotation_id"] == "A00004")["rep_id"] == 2
    finally:
        studio.close()


def test_annotation_back_can_retry_a_failed_save(qt_app, tmp_path, monkeypatch):
    from app import mode1_annotation

    video = tmp_path / "clip_skeleton.mp4"
    parquet = tmp_path / "clip_features.parquet"
    annotation = tmp_path / "notes.json"
    write_video(video, 3)
    pd.DataFrame({"frame_id": range(3), "timestamp_s": np.arange(3) / 24}).to_parquet(parquet)
    studio = mode1_annotation.open_annotation_studio(
        video_path=video, parquet_path=parquet, annotation_json_path=annotation,
    )
    def fail_save(*args):
        raise OSError("simulated disk write failure")

    try:
        studio.annotation_state.status = "completed"
        with monkeypatch.context() as disk_error:
            disk_error.setattr(mode1_annotation, "save_json_atomic", fail_save)
            disk_error.setattr(QMessageBox, "critical", lambda *args: None)
            assert not studio._persist_annotations(show_error=False)
            monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Save)
            studio.back_button.click()
            assert studio.isVisible()
            assert load_json(annotation)["annotation_session"]["status"] == "in_progress"
        studio.back_button.click()
        assert not studio.isVisible()
        assert load_json(annotation)["annotation_session"]["status"] == "completed"
    finally:
        if studio.isVisible():
            studio.close()


def test_annotation_playback_follows_source_timestamps_and_pauses_on_seek(qt_app, tmp_path, monkeypatch, detail):
    from app import mode1_annotation, playback

    video = tmp_path / "clip_skeleton.mp4"
    parquet = tmp_path / "clip_features.parquet"
    annotation = tmp_path / "notes.json"
    write_video(video, 5)
    pd.DataFrame({
        "frame_id": range(5), "timestamp_s": [0.0, 0.020, 0.100, 0.132, 0.190],
    }).to_parquet(parquet, index=False)
    studio = mode1_annotation.open_annotation_studio(
        video_path=video, parquet_path=parquet, annotation_json_path=annotation,
    )
    before = annotation.read_bytes()
    now = 100.0
    monkeypatch.setattr(playback, "monotonic", lambda: now)
    try:
        qt_app.processEvents()
        buttons = {button.text(): button for button in studio.findChildren(QPushButton)}
        assert "Home" not in buttons and "End" not in buttons
        assert buttons["◀"].x() < studio.play_button.x() < buttons["▶"].x()
        assert studio.jump_spin.value() == 50
        studio.play_button.click()
        assert studio.play_button.text() == "Pause"
        assert studio.playback.timer.interval() == 20
        now += .020
        studio.playback.advance()
        assert studio.frame_spin.value() == studio.current_frame == 1
        assert studio.frame_slider.value() == 1
        assert studio.playback.timer.interval() == 80
        assert "0.020s" in studio.current_frame_context_label.text()
        studio.play_button.click()
        studio.playback.advance()
        assert studio.current_frame == 1 and not studio.playback.timer.isActive()
        studio.play_button.click()
        QTest.mousePress(buttons["▶"], Qt.MouseButton.LeftButton)
        assert studio.current_frame == 1 and not studio.playback.playing
        assert not studio.playback.timer.isActive()
        QTest.mouseRelease(buttons["▶"], Qt.MouseButton.LeftButton)
        assert studio.current_frame == 2 and studio.play_button.text() == "Play"
        studio.goto_frame(3)
        studio.play_button.click()
        studio.playback.advance()
        assert studio.current_frame == 4 and not studio.playback.timer.isActive()
        studio.goto_frame(0)
        studio.play_button.click()
        now += 0.14
        studio.playback.advance()
        assert studio.current_frame == 3
        studio.frame_slider.setSliderDown(True)
        assert not studio.playback.playing
        studio.frame_slider.setSliderPosition(1)
        assert studio.frame_spin.value() == studio.current_frame == 1
        assert "0.020s" in studio.current_frame_context_label.text()
        studio.frame_slider.setSliderDown(False)
        studio.frame_spin.setValue(2)
        assert studio.frame_slider.value() == studio.current_frame == 2
        assert annotation.read_bytes() == before
        detail(observed="Mode 1 used 20 ms and 80 ms source intervals; Pause, manual stepping, and EOF stopped playback.")
    finally:
        studio.close()


def test_angle_overlay_mirrors_graph_selection_source_and_frame(qt_app, tmp_path, monkeypatch, detail):
    from app import mode1_annotation

    video = tmp_path / "clip_skeleton.mp4"
    parquet = tmp_path / "clip_features.parquet"
    annotation = tmp_path / "notes.json"
    write_video(video, 3)
    pd.DataFrame({
        "frame_id": range(3), "timestamp_s": [0.0, 0.041, 0.088],
        "lm24_x": 0.65, "lm24_y": 0.55, "lm23_x": 0.35, "lm23_y": 0.55,
        "lm11_x": 0.35, "lm11_y": 0.25, "lm12_x": 0.65, "lm12_y": 0.25,
        "lm13_x": 0.28, "lm13_y": 0.40, "lm14_x": 0.72, "lm14_y": 0.40,
        "lm25_x": 0.35, "lm25_y": 0.75, "lm26_x": 0.65, "lm26_y": 0.75,
        "angle_torso2d_left_elbow": 100.0, "angle_torso2d_right_elbow": 105.0,
        "angle_torso2d_left_shoulder": 40.0, "angle_torso2d_right_shoulder": 45.0,
        "angle_torso2d_right_hip": [110.0, 120.0, np.nan],
        "angle_torso2d_left_hip": [130.0, 140.0, 145.0],
        "angle_torso2d_left_knee": 160.0, "angle_torso2d_right_knee": 155.0,
        "angle_torso2d_torso_nose_shoulder_hip": 170.0,
        "angle_torso2d_shoulder_midpoint_hip_midpoint_knee_midpoint": 165.0,
        "angle_3d_right_hip": [80.0, 90.0, np.nan],
        "angle_3d_left_hip": [85.0, 95.0, 105.0],
    }).to_parquet(parquet, index=False)
    features_before = parquet.read_bytes()
    render = mode1_annotation.paint_angle_labels
    painted = []

    def record_labels(display, labels):
        painted[:] = labels
        render(display, labels)

    monkeypatch.setattr(mode1_annotation, "paint_angle_labels", record_labels)
    studio = mode1_annotation.open_annotation_studio(
        video_path=video, parquet_path=parquet, annotation_json_path=annotation,
    )
    notes_before = annotation.read_bytes()
    try:
        qt_app.processEvents()
        assert not studio.overlay_button.isChecked()
        assert not studio.mirror_angles_button.isChecked()
        assert painted == []
        studio.overlay_button.click()
        default_labels = {label.text for label in painted}
        assert default_labels == {
            "Left Elbow 100.0°", "Right Elbow 105.0°", "Left Shoulder 40.0°", "Right Shoulder 45.0°",
            "Left Hip 130.0°", "Right Hip 110.0°", "Left Knee 160.0°", "Right Knee 155.0°",
        }
        studio.mirror_angles_button.click()
        assert studio.annotation_graph_window is None
        assert {label.text for label in painted} == default_labels | {"Neck 170.0°", "Hip Midpoint 165.0°"}
        initial_mirror = painted.copy()

        studio.graph_viewer_button.click()
        viewer = studio.annotation_graph_window
        graph = viewer.graph
        assert painted == initial_mirror
        assert viewer.overlay_button.isChecked() and viewer.preview._labels
        graph._set_all_traces(False)
        graph.trace_checks["angle_right_hip"].setChecked(True)
        viewer.overlay_button.setChecked(False)
        assert viewer.preview._labels == ()
        clean_image = viewer.preview.pixmap().toImage()
        viewer.overlay_button.click()
        label, = viewer.preview._labels
        assert label.text == "Right Hip 110.0°"
        assert (label.x, label.y) == (0.65, 0.55)
        assert label.color == graph._lines["angle_right_hip"].get_color()
        assert painted == initial_mirror
        assert viewer.preview.pixmap().toImage() != clean_image

        graph.angle_source.setCurrentText("Estimated world (3D)")
        assert [label.text for label in viewer.preview._labels] == ["Right Hip 80.0°"]
        assert viewer.goto_frame(1)
        assert [label.text for label in viewer.preview._labels] == ["Right Hip 90.0°"]
        assert studio.current_frame == 0 and painted == initial_mirror
        assert viewer.goto_frame(2) and viewer.preview._labels == ()
        viewer.back_button.click()
        assert studio.goto_frame(1)
        assert [label.text for label in painted] == ["Right Hip 90.0°"]
        studio.mirror_angles_button.click()
        assert "Left Elbow 100.0°" in {label.text for label in painted}
        studio.mirror_angles_button.click()
        assert studio.annotation_graph_window is None
        assert [label.text for label in painted] == ["Right Hip 90.0°"]

        studio.graph_viewer_button.click()
        viewer = studio.annotation_graph_window
        assert viewer.graph.angle_source.currentText() == "Estimated world (3D)"
        assert viewer.graph.angle_selection().checked == {"angle_right_hip"}
        viewer.graph._set_all_traces(False)
        assert [label.text for label in painted] == ["Right Hip 90.0°"]
        assert viewer.overlay_button.isChecked() and viewer.preview._labels == ()
        viewer.back_button.click()
        assert painted == []
        assert parquet.read_bytes() == features_before and annotation.read_bytes() == notes_before
        detail(observed="Eight joint labels by default; mirroring worked before graph open and retained the chosen source and trace after close.")
    finally:
        studio.close()


def test_preparation_saves_hip_midpoint_for_graph_and_mirror(qt_app, tmp_path, monkeypatch):
    from app import mode1_annotation
    from scripts.prepare_viewer_features import prepare_viewer_features

    video = tmp_path / "clip_skeleton.mp4"
    parquet = tmp_path / "clip_features.parquet"
    write_video(video, 3)
    frames = pd.DataFrame({
        "frame_id": [0, 1, 2], "timestamp_s": [0.0, 0.04, 0.08],
        "angle_right_hip": 100.0, "angle_2d_right_hip": 110.0, "angle_3d_right_hip": 120.0,
    })
    for space in ("lm", "world"):
        for joint, x, y in ((11, 0.3, 0.2), (12, 0.5, 0.2), (23, 0.3, 0.5), (24, 0.5, 0.5),
                            (25, 0.5, 0.7), (26, 0.7, 0.7)):
            frames[f"{space}{joint}_x"] = x
            frames[f"{space}{joint}_y"] = y
            frames[f"{space}{joint}_z"] = 0.0
    frames.loc[2, "lm26_y"] = np.nan
    frames.to_parquet(parquet, index=False)
    original_bytes = parquet.read_bytes()
    config = load_config(Path(__file__).resolve().parents[1] / "configs" / "config.json")
    count, backup = prepare_viewer_features(parquet, video, config)
    assert count and backup.read_bytes() == original_bytes
    assert prepare_viewer_features(parquet, video, config) == (0, None)
    pd.testing.assert_frame_equal(pd.read_parquet(parquet, columns=list(frames)), frames)
    def reject_recalculation(*args, **kwargs):
        pytest.fail("Review must use only saved features.")

    monkeypatch.setattr("aihumo.features.FeatureEngine.prepare_review_features", reject_recalculation)
    monkeypatch.setattr("aihumo.features.FeatureEngine.with_missing_spatial_angles", reject_recalculation)
    features_before = parquet.read_bytes()
    labels = []

    def record_labels(_, painted):
        labels[:] = painted

    monkeypatch.setattr(mode1_annotation, "paint_angle_labels", record_labels)
    studio = mode1_annotation.open_annotation_studio(
        video_path=video, parquet_path=parquet, annotation_json_path=tmp_path / "notes.json",
    )
    try:
        studio.overlay_button.click()
        studio.mirror_angles_button.click()
        assert studio.annotation_graph_window is None
        assert "Hip Midpoint 126.9°" in {label.text for label in labels}

        studio.graph_viewer_button.click()
        viewer = studio.annotation_graph_window
        graph = viewer.graph
        graph.angle_source.setCurrentText("Legacy (normalized image)")
        midpoint = graph.trace_checks["angle_shoulder_midpoint_hip_midpoint_knee_midpoint"]
        assert midpoint.isEnabled() and midpoint.isChecked()
        assert "Hip Midpoint 135.0°" in {label.text for label in viewer.preview._labels}
        midpoint.click()
        assert not any(label.text.startswith("Hip Midpoint") for label in viewer.preview._labels)
        midpoint.click()

        graph.show_all_sources.click()
        assert graph.figure.axes[0].get_title() == "Torso-normalized 2D"
        traces = [next(line for line in axis.lines if line.get_label() == "Hip Midpoint") for axis in graph.figure.axes]
        expected = [np.degrees(np.arccos(-0.6)), 135.0, 135.0]
        np.testing.assert_allclose([trace.get_ydata()[0] for trace in traces], [*expected, np.mean(expected)])
        assert np.isnan(traces[-1].get_ydata()[2])
        viewer.back_button.click()
        assert "Hip Midpoint 135.0°" in {label.text for label in labels}
        assert parquet.read_bytes() == features_before
    finally:
        studio.close()


def test_clean_video_skeleton_toggle_and_buffered_forward_frames(qt_app, tmp_path, monkeypatch):
    from app import playback
    from app.mode1_annotation import open_annotation_studio

    video = tmp_path / "clean.mp4"
    parquet = tmp_path / "clip_features.parquet"
    write_video(video, 110)
    pd.DataFrame({
        "frame_id": range(110), "timestamp_s": np.arange(110) / 24,
        "angle_right_hip": 90.0, "lm24_x": 0.65, "lm24_y": 0.55,
        "review_legacy_shoulder_midpoint_x": 0.5, "review_legacy_shoulder_midpoint_y": 0.25,
        "review_legacy_hip_midpoint_x": 0.5, "review_legacy_hip_midpoint_y": 0.7,
    }).to_parquet(parquet, index=False)
    studio = open_annotation_studio(video_path=video, parquet_path=parquet, annotation_json_path=tmp_path / "notes.json")
    try:
        qt_app.processEvents()
        assert studio.skeleton_button.isChecked() and studio.skeleton_button.isEnabled()
        assert studio.midpoint_button.isChecked() and studio.midpoint_button.isEnabled()
        before = studio.video_label.pixmap().toImage()
        studio.skeleton_button.click()
        midpoint_only = studio.video_label.pixmap().toImage()
        assert midpoint_only != before
        studio.midpoint_button.click()
        assert studio.video_label.pixmap().toImage() != midpoint_only
        assert studio.current_frame == 0 and not studio.overlay_button.isChecked()
    finally:
        studio.close()

    viewer = InteractiveGraphViewer(video, parquet)
    viewer.show()
    try:
        assert viewer.goto_frame(30)
        qt_app.processEvents()
        assert viewer.midpoint_button.isChecked() and viewer.midpoint_button.isEnabled()
        before = viewer.preview.pixmap().toImage()
        viewer.skeleton_button.click()
        midpoint_only = viewer.preview.pixmap().toImage()
        assert midpoint_only != before
        viewer.midpoint_button.click()
        assert viewer.preview.pixmap().toImage() != midpoint_only
        assert viewer.current_frame == 30 and not viewer.overlay_button.isChecked()
        for _ in range(60):
            if viewer._frame_buffer.get(55) is not None and viewer._frame_buffer.get(18) is not None:
                break
            QTest.qWait(20)
        assert viewer._frame_buffer.get(55) is not None and viewer._frame_buffer.get(18) is not None
        now = 100.0
        monkeypatch.setattr(playback, "monotonic", lambda: now)
        viewer.play_button.click()
        now += 8.5 / 24
        viewer.playback.advance()
        assert viewer.slider.value() == viewer.current_frame == 38
        assert viewer.goto_frame(2) and viewer.current_frame == 2
        assert viewer._frame_buffer.get(55) is None
        viewer.play_button.click()
        now += 88.5 / 24
        viewer.playback.advance()
        assert viewer.current_frame == 2
        viewer.playback.timer.stop()
        for _ in range(60):
            if viewer._frame_buffer.ready_for_playback(90, 2) == 90:
                break
            QTest.qWait(20)
        viewer.playback.advance()
        assert viewer.slider.value() == viewer.current_frame == 90
        buffer = viewer._frame_buffer
        with buffer._condition:
            assert len(buffer._frames) <= buffer.ahead + buffer.behind + 1
    finally:
        buffer = viewer._frame_buffer
        viewer.close()
        assert not buffer._frames and not buffer._worker.is_alive()


def test_aligned_playback_keeps_one_decode_target_while_waiting(qt_app, monkeypatch):
    from app import aligned_graph_viewer

    now = 100.0
    monkeypatch.setattr(aligned_graph_viewer, "monotonic", lambda: now)
    viewer = QPushButton()
    viewer.session = SimpleNamespace(review_window=(0.0, 12.0), current_time=0.0, pause_other_review=lambda _: None)
    targets = []

    def render(time, *, playback):
        assert playback
        targets.append(time)
        return len(targets) >= 3

    viewer.render = render
    playback = aligned_graph_viewer.AlignmentPlayback(viewer)
    playback.toggle()
    try:
        now += 4
        for _ in range(4):
            now += 0.1
            playback.advance()
        assert playback.playing
        assert targets == pytest.approx([4.1, 4.1, 4.1, 4.4])
        viewer.session.current_time = targets[-1]
        playback.start(direction=-1, hold=True, speed=2.0)
        now += 0.2
        playback.advance()
        assert playback.holding and targets[-1] == pytest.approx(4.0)
    finally:
        playback.pause(refresh=False)
        viewer.close()


def test_restarting_aligned_playback_retries_failed_prefetch(monkeypatch):
    from app.playback import FrameBuffer

    monkeypatch.setattr(FrameBuffer, "_decode", lambda self: None)
    buffer = FrameBuffer("unused.mp4", 120, (40, 32))
    try:
        buffer.request(50, playback=True)
        buffer._failed.add(51)
        buffer.request(51, playback=True)
        assert buffer._next_index() == 52
        buffer.request(50)
        buffer.request(51, playback=True)
        assert buffer._next_index() == 51
        buffer.request(50, playback=True, direction=-1)
        buffer._frames[50] = np.empty(0)
        buffer._frames[48] = np.empty(0)
        assert buffer._next_index() == 49
        assert buffer.ready_for_playback(47, 50) == 48
    finally:
        buffer.close()


def test_variable_rate_seek_checks_saved_timestamp_and_recovers_rounding():
    from app.playback import TimestampedCapture, decode_frame

    times = np.array([0, .031, .079, .11, .17])
    seeks = []
    index = 0

    def seek(property_id, timestamp_ms):
        nonlocal index
        assert property_id == cv2.CAP_PROP_POS_MSEC
        seeks.append(timestamp_ms)
        index = min(len(times) - 1, np.searchsorted(times, timestamp_ms / 1000) + 1)
        return True

    def read():
        nonlocal index
        frame = index
        index += 1
        return True, frame

    capture = TimestampedCapture(SimpleNamespace(
        read=read, set=seek, get=lambda _: times[index - 1] * 1000,
    ), times)
    capture._next_index = None
    assert decode_frame(capture, 3) == (True, 3)
    assert seeks == [110, 0]
    assert decode_frame(capture, 4) == (True, 4)
    assert seeks == [110, 0]


def test_graph_hover_can_be_cleared_after_control_is_deleted(qt_app):
    from PyQt6 import sip

    graph = JointGraphWidget(pd.DataFrame({"frame_id": [0], "timestamp_s": [0.0], "angle_left_knee": [0.0]}))
    graph._hover_sample = (graph.axis, "angle_left_knee", 0)
    sip.delete(graph.angle_source)
    graph._clear_hover()
    graph.dispose()
    assert not graph._canvas_connections and graph.dataframe.empty and not graph._panels
    graph.close()


def test_annotation_reads_rep_signals_only_for_the_selected_interval(qt_app, tmp_path, monkeypatch):
    from app.mode1_annotation import open_annotation_studio

    video = tmp_path / "clip.mp4"
    parquet = tmp_path / "clip_features.parquet"
    notes = tmp_path / "notes.json"
    write_video(video, 30)
    ids = np.arange(30)
    pd.DataFrame({
        "frame_id": ids, "timestamp_s": ids / 24, "fps": 24.0,
        "distance_left_hip_left_knee": np.sin(ids), "unused_extra_column": 3.0,
    }).to_parquet(parquet)
    state = AnnotationState.new({})
    state.add({
        "annotation_id": "A00001", "segment_id": "clip_SEG0001", "annotation_type": "activity_state",
        "activity_state": "active", "start_frame": 4, "end_frame": 20,
    })
    save_json_atomic(state.to_document(), notes)
    original_notes = notes.read_bytes()
    studio = open_annotation_studio(video_path=video, parquet_path=parquet, annotation_json_path=notes)
    reads = []
    read_parquet = pd.read_parquet

    def record_read(*args, **kwargs):
        result = read_parquet(*args, **kwargs)
        reads.append((set(result.columns), result["frame_id"].tolist()))
        return result

    monkeypatch.setattr(pd, "read_parquet", record_read)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    try:
        assert list(studio.dataframe.columns) == ["frame_id", "timestamp_s"]
        studio.goto_frame(10)
        studio.analyze_current_active_segment()
        assert reads == [({"frame_id", "timestamp_s", "fps", "distance_left_hip_left_knee"}, list(range(4, 21)))]
        assert studio.annotation_json_path.with_name("notes_rep_suggestions.json").is_file()
        assert notes.read_bytes() == original_notes
    finally:
        studio.close()


def test_launcher_opens_both_mode0_dialogs_maximized_with_title_bar(qt_app, tmp_path):
    home = HomeWindow(state_dir=tmp_path / "state")
    opened = []

    def inspect_dialog():
        dialog = QApplication.activeModalWidget()
        if dialog is not None:
            opened.append((type(dialog), dialog.isMaximized(), dialog.isFullScreen(), dialog.windowFlags()))
            dialog.reject()

    home.show()
    try:
        home.processing_card.face.click()
        assert home.processing_card.currentIndex() == 1
        assert home.resume_group.title().startswith("Resume Mode 0")
        for button in (home.batch_button, home.process_button):
            QTimer.singleShot(0, inspect_dialog)
            button.click()
        assert [kind for kind, _, _, _ in opened] == [BatchSessionDialog, ProcessVideoDialog]
        for _, maximized, fullscreen, flags in opened:
            assert maximized and not fullscreen
            assert flags & Qt.WindowType.WindowTitleHint
            assert flags & Qt.WindowType.WindowMaximizeButtonHint
            assert not flags & Qt.WindowType.FramelessWindowHint
    finally:
        home.close()


def test_launcher_resumes_pose_and_timeline_at_separate_frames(qt_app, tmp_path, monkeypatch):
    from app import playback

    video = tmp_path / "clip_skeleton.mp4"
    parquet = tmp_path / "clip_features.parquet"
    frames = np.arange(8)
    write_video(video, len(frames))
    pd.DataFrame({
        "frame_id": frames, "timestamp_s": frames / 24, "angle_right_elbow": 120 + frames,
        "world11_x": -0.2, "world11_y": -0.5, "world11_z": 0.1,
        "world13_x": frames / 20, "world13_y": -0.3, "world13_z": 0.2,
        "review_cross_mean_lm11_x": -0.3, "review_cross_mean_lm11_y": -1.0,
        "review_cross_mean_lm13_x": frames / 10, "review_cross_mean_lm13_y": -0.5,
    }).to_parquet(parquet, index=False)
    home = HomeWindow(state_dir=tmp_path / "state", processed_root=tmp_path)
    home.show()
    try:
        home._show_graph_viewer(video_path=video, parquet_path=parquet, frame=2)
        assert home.resume_group.title().startswith("Resume Mode 3")
        home._show_graph_viewer(mode=4, video_path=video, parquet_path=parquet, frame=5)
        viewer = home.graph_window
        assert isinstance(viewer, PoseGraphViewer)
        assert home.pose_button.isChecked()
        assert home.resume_group.title().startswith("Resume Mode 4")
        assert home.resume_combo.currentText().endswith("(frame 5)")
        pose = viewer.pose_plot
        assert pose.spatial and pose.axis.name == "3d"
        np.testing.assert_allclose(np.array(pose.points.get_data_3d())[:, 1], (0.25, 0.2, 0.3))
        pose.axis.view_init(elev=35, azim=20)
        viewer.frame_spin.setValue(6)
        assert pose.axis.elev == 35 and pose.axis.azim == 20
        np.testing.assert_allclose(np.array(pose.points.get_data_3d())[:, 1], (0.30, 0.2, 0.3))
        initial = np.array([pose.axis.get_xlim(), pose.axis.get_ylim(), pose.axis.get_zlim()])
        next(button for button in pose.findChildren(QPushButton) if button.text() == "+").click()
        zoomed = np.array([pose.axis.get_xlim(), pose.axis.get_ylim(), pose.axis.get_zlim()])
        np.testing.assert_allclose(zoomed.mean(axis=1), (0.05, 0.15, 0.4), atol=1e-7)
        np.testing.assert_allclose(np.diff(zoomed), 0.6 * np.diff(initial))
        assert viewer.current_frame == 6 and pose.axis.elev == 35 and pose.axis.azim == 20
        pose.canvas.draw()
        box = pose.axis.bbox
        x, y = box.x0 + box.width * 0.8, box.y0 + box.height / 2
        pose.toolbar.zoom()
        for name, drag_x in (("button_press_event", x), ("button_release_event", x - box.width / 2)):
            pose.canvas.callbacks.process(name, MouseEvent(name, pose.canvas, drag_x, y, button=MouseButton.LEFT))
        pose.toolbar.zoom()
        assert np.diff(pose.axis.get_xlim())[0] < np.diff(zoomed[0])[0]
        width = np.diff(pose.axis.get_xlim())[0]
        wheel = MouseEvent("scroll_event", pose.canvas, x, y, button="up", step=1, key="control")
        pose.canvas.callbacks.process("scroll_event", wheel)
        assert np.diff(pose.axis.get_xlim())[0] == pytest.approx(width * 0.65)
        assert viewer.current_frame == 6
        viewer.goto_frame(3)
        now = 100.0
        monkeypatch.setattr(playback, "monotonic", lambda: now)
        monkeypatch.setattr(viewer.playback, "ready_frame", lambda due, current: due)
        viewer.play_button.click()
        pose.toolbar.zoom()
        pose.rotate_button.click()
        assert viewer.playback.playing and not pose.toolbar.mode
        pose.canvas.draw()
        box = pose.axis.bbox
        origin = QPoint(round(box.x0 + box.width / 2), round(pose.canvas.height() - box.y0 - box.height / 2))
        end = origin + QPoint(30, -20)
        orientation = pose.axis.elev, pose.axis.azim
        QTest.mousePress(pose.canvas, Qt.MouseButton.LeftButton, pos=origin)
        now += 1 / 24
        viewer.playback.advance()
        QTest.mouseMove(pose.canvas, end)
        QTest.mouseRelease(pose.canvas, Qt.MouseButton.LeftButton, pos=end)
        rotated = pose.axis.elev, pose.axis.azim
        assert rotated != orientation and viewer.playback.playing
        assert viewer.current_frame == pose.frame == 4
        now += 1 / 24
        viewer.playback.advance()
        assert viewer.current_frame == pose.frame == 5
        assert (pose.axis.elev, pose.axis.azim) == rotated

        cube = pose.orientation_cube
        qt_app.processEvents()
        assert cube.isVisible() and cube._view == (pose.axis.elev, pose.axis.azim, pose.axis.roll)
        assert cube.x() + cube.width() <= pose.canvas.width()
        expected_faces = {
            "+X": (0, 0), "−X": (0, 180), "+Y": (-90, -90), "−Y": (90, -90),
            "+Z": (0, 90), "−Z": (0, -90),
        }
        for button in cube.findChildren(QToolButton):
            button.click()
            assert (pose.axis.elev, pose.axis.azim) == expected_faces.pop(button.text())
        assert not expected_faces

        for direction, expected in (
            ((1, 0, 0), (0, 0)), ((1, -1, 0), (0, -45)), ((1, -1, 1), (35.26439, -45))
        ):
            pose._orient_pose(30, -40, 0)
            polygon = next(polygon for polygon, normal in cube._regions if normal == direction)
            QTest.mouseClick(cube, Qt.MouseButton.LeftButton, pos=polygon.boundingRect().center().toPoint())
            assert (pose.axis.elev, pose.axis.azim) == pytest.approx(expected)
        start = QPoint(cube.width() // 2, 50)
        QTest.mousePress(cube, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(cube, start + QPoint(18, -12))
        QTest.mouseRelease(cube, Qt.MouseButton.LeftButton, pos=start + QPoint(18, -12))
        assert (pose.axis.elev, pose.axis.azim) == pytest.approx((23.26439, -63))
        assert viewer.playback.playing and viewer.current_frame == pose.frame == 5
        viewer.goto_frame(6)
        pose.source.setCurrentIndex(pose.source.findData("review_cross_mean_lm"))
        assert not pose.spatial and pose.axis.name == "rectilinear"
        assert not cube.isVisible()
        np.testing.assert_allclose(np.array(pose.points.get_data())[:, 1], (0.6, 0.5))
        next(button for button in pose.findChildren(QPushButton) if button.text() == "+").click()
        np.testing.assert_allclose(np.mean([pose.axis.get_xlim(), pose.axis.get_ylim()], axis=1), (0.15, 0.75))
        assert viewer.current_frame == 6
        viewer.pose_tabs.setCurrentWidget(viewer.graph)
        assert list(viewer.graph._cursor.get_xdata()) == [6 / 24] * 2
        assert not viewer.graph.zoom_to_seek.isChecked()
        viewer.graph._on_scroll(SimpleNamespace(inaxes=viewer.graph.axis, xdata=4 / 24, button="up"))
        assert viewer.current_frame == 6
        viewer.graph.zoom_to_seek.click()
        viewer.graph._on_scroll(SimpleNamespace(inaxes=viewer.graph.axis, xdata=4 / 24, button="up"))
        assert viewer.current_frame == 4
        assert list(viewer.graph._cursor.get_xdata()) == [4 / 24] * 2
        viewer.frame_spin.setValue(6)
        viewer.back_button.click()
        home._select_mode(3)
        assert home.resume_combo.currentText().endswith("(frame 2)")
        home._select_mode(4)
        assert home.resume_combo.currentText().endswith("(frame 6)")
        home.resume_button.click()
        assert isinstance(home.graph_window, PoseGraphViewer)
        assert home.graph_window.current_frame == 6
    finally:
        home.close()


def test_mode_zero_resume_restores_single_and_batch_inputs(qt_app, tmp_path, monkeypatch):
    folder = tmp_path / "capture"
    folder.mkdir()
    video = folder / "front.mp4"
    write_video(video, 2)
    home = HomeWindow(state_dir=tmp_path / "state")
    captured = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(folder))

    def configure_single():
        dialog = QApplication.activeModalWidget()
        dialog.video_edit.setText(str(video))
        dialog.session_edit.setText("S021")
        dialog.video_id_edit.setText("front_view")
        dialog.participant_edit.setText("P014")
        dialog.reject()

    def configure_batch():
        dialog = QApplication.activeModalWidget()
        dialog.add_folder()
        dialog.recording_table.item(0, 3).setText("front_cam")
        dialog.participant_edit.setText("P019")
        dialog.reject()

    def read_single():
        dialog = QApplication.activeModalWidget()
        captured.append((dialog.video_edit.text(), dialog.session_edit.text(),
                         dialog.video_id_edit.text(), dialog.participant_edit.text()))
        dialog.reject()

    def read_batch():
        dialog = QApplication.activeModalWidget()
        captured.append((dialog.recording_table.item(0, 2).text(), dialog.recording_table.item(0, 3).text(),
                         dialog.participant_edit.text()))
        dialog.reject()

    home.show()
    try:
        QTimer.singleShot(0, configure_single)
        home.open_process()
        QTimer.singleShot(0, configure_batch)
        home.open_batch()
        assert home.resume_combo.count() == 2 and home.resume_button.isEnabled()
        home.resume_combo.setCurrentIndex(home.resume_combo.findText("New Video · front.mp4"))
        QTimer.singleShot(0, read_single)
        home.resume_button.click()
        home.resume_combo.setCurrentIndex(home.resume_combo.findText("Video Batch · capture"))
        QTimer.singleShot(0, read_batch)
        home.resume_button.click()
        assert captured == [(str(video), "S021", "front_view", "P014"), (str(video), "front_cam", "P019")]
        home._select_mode(5)
        assert "Model Suite" in home.resume_group.title() and not home.resume_button.isEnabled()
    finally:
        home.close()


def test_launcher_selects_modes_before_opening_new_work(qt_app, tmp_path, monkeypatch):
    opened = []
    for mode, method in ((1, "open_annotation"), (2, "open_session_alignment"),
                         (3, "open_interactive_viewer"), (5, "open_model_suite")):
        monkeypatch.setattr(HomeWindow, method, lambda self, mode=mode: opened.append(mode))
    monkeypatch.setattr(HomeWindow, "_show_graph_viewer", lambda self, *, mode: opened.append(mode))

    home = HomeWindow(state_dir=tmp_path / "state", processed_root=tmp_path)
    home.show()
    try:
        for mode in range(1, 5):
            home.resume_stores[mode].add(name=f"Saved mode {mode}", files={"test": str(mode)})
        for mode in range(1, 6):
            tile = home.workflows.button(mode)
            for _ in range(2):
                QTest.mouseClick(tile, Qt.MouseButton.LeftButton)
                assert tile.isChecked()
                assert home.resume_group.title().startswith(f"Resume Mode {mode}")
                assert home.resume_button.isEnabled() == (mode < 5)
                if mode < 5:
                    assert home.resume_combo.currentText().startswith(f"Saved mode {mode}")
                assert opened == list(range(1, mode))
            QTest.mouseDClick(tile, Qt.MouseButton.LeftButton)
            assert opened == list(range(1, mode + 1))

        tile = home.alignment_button
        tile.setFocus()
        QTest.keyClick(tile, Qt.Key.Key_Space)
        assert tile.isChecked() and opened == [1, 2, 3, 4, 5]
        QTest.keyClick(tile, Qt.Key.Key_Return)
        assert opened == [1, 2, 3, 4, 5, 2]
    finally:
        home.close()


def test_mode_two_resume_discovers_saved_alignment(qt_app, tmp_path):
    from aihumo.alignment import process_session, save_session

    root = tmp_path / "processed"
    session = root / "S001"
    paths = []
    for name in ("front", "side"):
        base = session / name
        video = base / "video" / f"{name}_skeleton.mp4"
        parquet = base / "parquet" / f"{name}_features.parquet"
        video.parent.mkdir(parents=True)
        parquet.parent.mkdir(parents=True)
        write_video(video, 8)
        pd.DataFrame({"frame_id": range(8), "timestamp_s": np.arange(8) / 24,
                      "angle_left_knee": 120}).to_parquet(parquet, index=False)
        paths.append(parquet)
    saved = session / "alignment.json"
    save_session(saved, *process_session(paths))
    home = HomeWindow(state_dir=tmp_path / "state", processed_root=root)
    try:
        home.alignment_button.click()
        assert home.alignment_window is None
        assert home.resume_group.title().startswith("Resume Mode 2")
        assert home.resume_combo.currentData()["files"]["alignmentJson"] == str(saved)
        original = saved.read_bytes()
        home.resume_remove_button.click()
        assert not home.resume_button.isEnabled() and not home.resume_remove_button.isEnabled()
        assert saved.read_bytes() == original
        home.recent_alignments.load()
        home._refresh_resume()
        assert not home.resume_button.isEnabled()
        home._remember_alignment(saved)
        home.resume_button.click()
        window = home.alignment_window
        for _ in range(50):
            if window.job is None:
                break
            QTest.qWait(30)
        assert len(window.panes) == 2
        assert home.recent_alignments.items[0]["files"]["alignmentJson"] == str(saved)
    finally:
        home.close()


def test_remove_recent_work_keeps_other_versions_and_files(qt_app, tmp_path):
    state_dir = tmp_path / "state"
    home = HomeWindow(state_dir=state_dir)
    paths = []
    try:
        for version in ("old", "new"):
            path = tmp_path / f"{version}.parquet"
            path.write_bytes(version.encode())
            home.recent_graphs.add(name="Clip", files={"featuresParquet": str(path)}, last_frame=0)
            paths.append(path)
        home._select_mode(3)
        assert home.resume_combo.count() == 2
        home.resume_combo.setCurrentIndex(1)
        home.resume_remove_button.click()
        assert home.resume_combo.count() == 1
        assert home.resume_combo.currentData()["files"]["featuresParquet"] == str(paths[1])
        assert paths[0].read_bytes() == b"old"
        home.recent_graphs.load()
        assert len(home.recent_graphs.items) == 1
    finally:
        home.close()


def test_saved_participants_in_both_mode0_dialogs(qt_app, tmp_path, detail):
    detail(input="Two saved participant IDs with a default, plus a third ID entered from Mode 0",
           expected="Both dialogs load the default and the third ID can be saved to the shared list")
    path = tmp_path / "settings.json"
    PreferenceStore(path).save(DesktopPreferences(participants=("P001", "P002"), default_participant="P002"))
    store = PreferenceStore(path)
    single = ProcessVideoDialog(preferences=store)
    try:
        assert single.participant_edit.text() == "P002"
        single.participant_edit.setText("P003")
        single.participant_picker._save_participant()
        assert PreferenceStore(path).values.participants == ("P001", "P002", "P003")
        batch = BatchSessionDialog(preferences=store)
        try:
            assert batch.participant_edit.text() == "P002"
            assert batch.participant_picker.combo.findText("P003") >= 0
        finally:
            batch.close()
    finally:
        single.close()
    detail(observed="P002 prefilled in both; P003 persisted and appeared in the batch dropdown")


def test_skeleton_renderer_uses_custom_line_and_joint_colors(tmp_path, detail):
    detail(input="One black frame with two connected landmarks and custom pink and cyan colors",
           expected="Decoded output has pink at the line center and cyan at the landmark")
    source = tmp_path / "clip.mp4"
    output = tmp_path / "clip_skeleton.mp4"
    write_video(source, 1)
    coordinates = {f"lm{joint}_{axis}": [np.nan] for joint in range(33) for axis in "xy"}
    coordinates.update(lm11_x=[0.25], lm11_y=[0.50], lm13_x=[0.75], lm13_y=[0.50])
    create_skeleton_video(source, pd.DataFrame(coordinates), output,
                          skeleton_line_color="#ff00ff", skeleton_joint_color="#00ffff")
    cap = cv2.VideoCapture(str(output))
    try:
        ok, frame = cap.read()
        assert ok
        line, joint = frame[60, 80], frame[60, 40]
        assert line[0] > 120 and line[1] < 80 and line[2] > 120
        assert joint[0] > 120 and joint[1] > 120 and joint[2] < 80
        detail(observed=f"Encoded BGR pixels: line={line.tolist()}, joint={joint.tolist()}")
    finally:
        cap.release()


def test_resume_timing_identity_and_completed_video_validation(tmp_path, monkeypatch, detail):
    detail(input="12-frame 24 FPS MP4 with stubbed pose inference; cancel after frame 0",
           expected="Resume all frames at 1/24 s spacing; reject changed camera IDs and invalid completed MP4s")
    source = tmp_path / "clip.mp4"
    write_video(source, 12)
    model = tmp_path / "model.task"
    model.write_bytes(b"stub model")
    # Keep the real decoder, encoder, checkpoint and feature pipeline. Stub
    # inference so this test needs neither model weights nor a visible person.
    no_pose = SimpleNamespace(pose_landmarks=[], pose_world_landmarks=[])
    detector = SimpleNamespace(detect_for_video=lambda image, timestamp: no_pose)
    monkeypatch.setattr("aihumo.pose._make_landmarker", lambda *args: nullcontext(detector))
    config = load_config(Path(__file__).resolve().parents[1] / "configs" / "config.json")
    config["graphs"]["export_images"] = False
    identifiers = {
        "session_id": "S001", "video_id": "V001", "participant_id": "P001", "camera_id": "C001",
    }
    options = dict(
        source_video=source, model_path=model, cfg=config, identifiers=identifiers,
        optional_metadata={}, output_root=tmp_path / "out",
    )
    cancel = False

    def progress(_, message):
        nonlocal cancel
        if "frame 1/12" in message:
            cancel = True

    with pytest.raises(InterruptedError):
        process_video(**options, progress_callback=progress, cancel_check=lambda: cancel)
    checkpoint = options["output_root"] / "S001" / "V001" / ".processing" / "processing_state.json"
    assert load_json(checkpoint)["next_frame"] == 1
    wrong_identity = {**options, "identifiers": {**identifiers, "camera_id": "C002"}}
    with pytest.raises(ValueError, match="Recording identity conflicts.*camera_id"):
        process_video(**wrong_identity)

    result = process_video(**options)
    frames = pd.read_parquet(result.features_path)
    assert frames["frame_id"].tolist() == list(range(12))
    assert len(frames.filter(regex=r"^angle_2d_").columns) == len(frames.filter(regex=r"^angle_3d_").columns) == 15
    assert frames[["angle_2d_right_elbow", "angle_3d_right_elbow"]].isna().all().all()
    manifest = load_json(result.feature_manifest_path)
    assert "angle_2d_right_elbow" in manifest["angle_feature_spaces"]["2d"]["columns"]
    assert load_json(result.graph_manifest_path)["angleSpace"] == "video_plane_2d"
    assert np.isnan(frames.loc[0, "delta_time_s"])
    np.testing.assert_allclose(frames["delta_time_s"].iloc[1:], 1 / 24, atol=1e-6)
    resumed = process_video(**options)
    assert resumed.features_path == result.features_path
    assert resumed.graph_manifest_path == result.graph_manifest_path

    # Older completed jobs use the metadata sidecar to establish identity.
    state = load_json(checkpoint)
    del state["recording_identity"]
    save_json_atomic(state, checkpoint)
    with pytest.raises(ValueError, match="Recording identity conflicts.*camera_id"):
        process_video(**wrong_identity)

    write_video(result.processed_video_path, 8)
    with pytest.raises(ValueError, match="Skeleton video has 8 frames but features have 12"):
        process_video(**options)
    damaged = b"unreadable video"
    result.processed_video_path.write_bytes(damaged)
    with pytest.raises(ValueError, match="Cannot open skeleton video"):
        process_video(**options)
    assert result.processed_video_path.read_bytes() == damaged
    detail(observed=f"{len(frames)} frames; resume delta={frames.loc[1, 'delta_time_s']:.6f} s; "
           "changed ID, wrong frame count and unreadable MP4 rejected")


def test_regressing_decoder_timestamp_uses_monotonic_fallback(monkeypatch, detail):
    timestamps = [800.0, 800.0, 780.0, 920.0, 920.2]
    detail(input=f"Decoder timestamps at 25 FPS in milliseconds: {timestamps}",
           expected="Repeated or backward times use the frame interval; MediaPipe milliseconds increase")
    decoder_ms = iter(timestamps)
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    cap = SimpleNamespace(
        isOpened=lambda: True, read=lambda: (True, frame),
        get=lambda _: next(decoder_ms), release=lambda: None,
    )
    inference_times = []

    def detect(_, milliseconds):
        inference_times.append(milliseconds)
        return SimpleNamespace(pose_landmarks=[], pose_world_landmarks=[])

    monkeypatch.setattr("aihumo.pose.cv2.VideoCapture", lambda _: cap)
    monkeypatch.setattr("aihumo.pose._make_landmarker", lambda *args: nullcontext(
        SimpleNamespace(detect_for_video=detect)
    ))
    rows = list(iter_landmark_rows(
        "clip.mp4", "model.task", {}, {}, {"source_fps": 25, "frame_count": 5}
    ))
    detail(observed=f"source seconds={[round(row['timestamp_s'], 4) for row in rows]}; "
           f"MediaPipe milliseconds={inference_times}")
    np.testing.assert_allclose([row["timestamp_s"] for row in rows], [.8, .84, .88, .92, .9202])
    assert [row["timestamp_source"] for row in rows] == [
        "decoder", "fps_estimate", "fps_estimate", "decoder", "decoder",
    ]
    assert inference_times == [800, 840, 880, 920, 921]


def test_corrupt_batch_checkpoint_is_reported_and_row_edits_survive(qt_app, tmp_path, monkeypatch, detail):
    detail(input="Two session folders; edit the second row, remove the first folder, and supply a damaged checkpoint",
           expected="Keep session and row edits, report the damaged job, and start no worker")
    folders = [tmp_path / name for name in ("day_one", "day_two")]
    for folder in folders:
        folder.mkdir()
        (folder / "front.mp4").touch()
    model = tmp_path / "model.task"
    model.touch()
    output = tmp_path / "output"
    checkpoint = output / "S002" / "edited" / ".processing" / "processing_state.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("{", encoding="utf-8")

    dialog = BatchSessionDialog()
    try:
        selections = iter(map(str, folders))
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: next(selections))
        dialog.add_folder()
        dialog.add_folder()
        dialog.recording_table.item(1, 1).setText("edited")
        dialog.recording_table.item(1, 3).setText("camera_custom")
        dialog.recording_table.cellWidget(1, 4).setCurrentText("Side")
        dialog.folder_list.setCurrentRow(0)
        dialog.remove_selected_folder()
        [recording] = dialog._recordings_from_table()
        assert (recording.session_id, recording.video_id, recording.camera_id, recording.camera_angle) == (
            "S002", "edited", "camera_custom", "Side",
        )

        dialog.participant_edit.setText("P001")
        dialog.model_edit.setText(str(model))
        dialog.output_edit.setText(str(output))
        messages = []
        monkeypatch.setattr(QMessageBox, "critical", lambda _, title, message: messages.append(message))
        dialog.start_processing()
        assert dialog.thread is None
        assert "S002/edited: Cannot read processing checkpoint" in messages[0]
        assert "different Video ID or output folder" in messages[0]
        assert checkpoint.read_text(encoding="utf-8") == "{"
        detail(observed=f"{recording.session_id}/{recording.video_id}, "
               f"{recording.camera_id}, {recording.camera_angle}; checkpoint error shown; no worker started")
    finally:
        dialog.close()
