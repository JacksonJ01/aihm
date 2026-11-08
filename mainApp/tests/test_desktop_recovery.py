from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pandas as pd
import pytest
from matplotlib.backend_bases import MouseButton, MouseEvent
from PyQt6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton, QSpinBox

from aihumo.annotations import AnnotationState
from aihumo.config import load_config
from aihumo.pose import iter_landmark_rows
from aihumo.processing import create_skeleton_video, process_video
from aihumo.storage import load_json, save_json_atomic
from app.AIHuMoDataStudio import HomeWindow
from app.graph_viewer import InteractiveGraphViewer
from app.joint_graph import JointGraphWidget
from app.mode0_batch import BatchSessionDialog
from app.mode0_process import ProcessVideoDialog
from app.preferences import DesktopPreferences, PreferenceStore, PreferencesDialog


@pytest.fixture(scope="module")
def qt_app():
    with pytest.MonkeyPatch.context() as environment:
        environment.setenv("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        yield app
        app.closeAllWindows()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def write_video(path, frame_count):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 24, (160, 120))
    assert writer.isOpened()
    try:
        for index in range(frame_count):
            writer.write(np.full((120, 160, 3), index * 4, dtype=np.uint8))
    finally:
        writer.release()


def test_long_graph_opens_and_keeps_zoom_and_cursor(qt_app, detail):
    count = 600
    detail(input="600 frames at 60 FPS with one Right Hip trace",
           expected="Overview opens, one-second zoom and frame cursor survive redraw, and pan does not seek")
    graph = JointGraphWidget(pd.DataFrame({
        "frame_id": range(count),
        "timestamp_s": np.arange(count) / 60,
        "angle_right_hip": np.linspace(0, 90, count),
    }))
    try:
        assert graph._lines["angle_right_hip"].get_marker() == "none"
        graph.set_current_frame(120)
        graph.zoom_to_detail_window()
        limits = graph.axis.get_xlim()
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
        graph.axis.set_xlim(0, 9)
        assert graph._lines["angle_right_hip"].get_marker() == "none"
        detail(observed=f"zoom={limits[1] - limits[0]:.3f} s; cursor=2.0 s; only normal click sought frame {hits[0]}")
    finally:
        graph.close()


def test_trace_checkboxes_and_hover_use_the_visible_nearest_joint(qt_app, detail):
    detail(input="Two angle traces at matching timestamps, with Right Hip world landmarks",
           expected="Hover overrides the current sample; moving away restores the last inspected joint at the video frame")
    timestamps = np.arange(5) / 4
    graph = JointGraphWidget(pd.DataFrame({
        "frame_id": range(5),
        "timestamp_s": timestamps,
        "angle_right_hip": [40, 40.5, 42, 44.5, np.nan],
        "angle_left_hip": 20 + timestamps,
        "world24_x": timestamps**2,
        "world24_y": 0.0,
        "world24_z": 0.0,
    }))
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
        assert "World XYZ (m, hip-relative) (0.250, 0.000, 0.000)" in card
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
        frames["angle_2d_right_knee"] = 42.0
        frames["angle_3d_right_knee"] = 90.0

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
        home.viewer_button.click()
        assert not errors
        viewer = home.graph_window
        assert isinstance(viewer, InteractiveGraphViewer)
        assert viewer.isVisible() and viewer.graph.isVisible()
        assert home.annotation_window is None
        assert viewer.graph.angle_source.currentText() == "Video plane (2D)"
        assert ("Angle 42.00°" if saved_spatial_angles else "Angle 126.87°") in viewer.graph.sample_card.text()
        if saved_spatial_angles:
            viewer.graph.angle_source.setCurrentText("Estimated world (3D)")
            assert "Angle 90.00°" in viewer.graph.sample_card.text()
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
        assert home.graph_resume_combo.currentText().endswith("(frame 10)")
        detail(observed="Graph clicked to frame 7; slider moved to frame 10; Back returned to menu and saved frame 10.")
    finally:
        if home.graph_window is not None:
            home.graph_window.close()
        home.close()


def test_graph_viewer_links_playback_pan_and_zoom_to_native_frames(qt_app, tmp_path, detail):
    detail(input="60 video frames with irregular Parquet timestamps",
           expected="Playback follows the cursor, pan seeks on release, and an offscreen zoom seeks a native frame")
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
        graph.detail_window_spin.setValue(0.3)
        graph.zoom_to_detail_window()
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

        # A graph range change can also come from toolbar history or zoom.
        graph.axis.set_xlim(times[39], times[41])
        qt_app.processEvents()
        expected = int(np.argmin(abs(times - (times[39] + times[41]) / 2)))
        assert viewer.current_frame == expected
        assert viewer.slider.value() == viewer.frame_spin.value() == expected
        assert f"{times[expected]:.6f} s" in viewer.frame_label.text()

        viewer.play_button.click()
        assert viewer.playback.timer.isActive()
        for _ in range(4):
            viewer.playback.advance()
        viewer.play_button.click()
        qt_app.processEvents()
        current = expected + 4
        assert viewer.current_frame == current
        assert list(graph._cursor.get_xdata()) == [times[current]] * 2
        assert graph.axis.get_xlim()[0] <= times[current] <= graph.axis.get_xlim()[1]
        assert graph.axis.get_xlim()[1] - graph.axis.get_xlim()[0] == pytest.approx(times[41] - times[39])
        detail(observed=f"Pan sought frame {panned_frame}; zoom sought {expected}; playback tracked frame {current}")
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
        detail(observed="Single-frame stepping retained focus; custom jump moved 0 → 3 → 6 → 3.")
    finally:
        other_window.close()
        viewer.close()


def test_launcher_resumes_graph_and_annotation_independently(qt_app, tmp_path, monkeypatch, detail):
    detail(input="Same 12-frame recording for both modes, annotation ending at frame 3 and graph at frame 9",
           expected="Graph preview keeps native controls and returns to Mode 1; Back respects unfinished annotation edits")
    state_dir = tmp_path / "state"
    store = PreferenceStore(state_dir / "settings.json")
    store.save(DesktopPreferences(
        launcher_accent="#1155cc", frame_highlight="#cc2288",
    ))
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
        assert reopened.graph_resume_combo.currentText().endswith("(frame 9)")
        reopened.resume_graph_work()
        assert not errors
        assert reopened.graph_window.current_frame == 9
        assert reopened.graph_window.jump_spin.value() == 8
        assert reopened.viewer_button.isChecked() and "#1155cc" in reopened.viewer_button.styleSheet()
        assert "#cc2288" in reopened.graph_window.thumbnails[2].styleSheet()
        reopened.resume_selected_work()
        assert not errors
        assert reopened.annotation_window.current_frame == 3
        assert reopened.annotate_button.isChecked() and not reopened.viewer_button.isChecked()
        assert "#cc2288" in reopened.annotation_window.thumbnail_labels[2].styleSheet()
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
        assert studio.annotation_graph_window is None and studio.current_frame == 3
        assert studio.isVisible() and not preview.isVisible()
        assert reopened.graph_window.current_frame == 9
        assert resume_path.read_bytes() == resume_before
        assert annotation.read_bytes() == before

        assert studio.back_button.isVisible() and studio.back_button.text() == "Back to menu"
        studio.start_range_capture()
        decisions = iter((QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Discard))
        monkeypatch.setattr(QMessageBox, "question", lambda *args: next(decisions, QMessageBox.StandardButton.Discard))
        studio.back_button.click()
        assert studio.isVisible() and studio.annotation_start_frame == 3
        studio.back_button.click()
        assert reopened.isVisible() and reopened.annotation_window is None and not studio.isVisible()
        assert annotation.read_bytes() == before
        detail(observed="Graph preview maximized with native controls. Back restored frame 3. Draft cancellation kept Mode 1 open.")
    finally:
        if reopened.annotation_window is not None:
            reopened.annotation_window.close()
        reopened.close()
        first.deleteLater()
        reopened.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


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
        assert studio.playback.timer.interval() == 80
        assert "0.020s" in studio.current_frame_context_label.text()
        studio.play_button.click()
        studio.playback.advance()
        assert studio.current_frame == 1 and not studio.playback.timer.isActive()
        studio.play_button.click()
        buttons["▶"].click()
        assert studio.current_frame == 2 and studio.play_button.text() == "Play"
        studio.goto_frame(3)
        studio.play_button.click()
        studio.playback.advance()
        assert studio.current_frame == 4 and not studio.playback.timer.isActive()
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
        "angle_2d_right_hip": [110.0, 120.0, np.nan],
        "angle_2d_left_hip": [130.0, 140.0, 145.0],
        "angle_2d_shoulder_midpoint_hip_midpoint_knee_midpoint": 165.0,
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
        assert [label.text for label in painted] == ["Hip Midpoint 165.0°"]
        assert (painted[0].x, painted[0].y) == (0.50, 0.55)
        studio.mirror_angles_button.click()

        studio.graph_viewer_button.click()
        viewer = studio.annotation_graph_window
        graph = viewer.graph
        graph._set_all_traces(False)
        graph.trace_checks["angle_right_hip"].setChecked(True)
        assert not viewer.overlay_button.isChecked()
        assert viewer.preview._labels == ()
        clean_image = viewer.preview.pixmap().toImage()
        viewer.overlay_button.click()
        label, = viewer.preview._labels
        assert label.text == "Right Hip 110.0°"
        assert (label.x, label.y) == (0.65, 0.55)
        assert label.color == graph._lines["angle_right_hip"].get_color()
        assert painted == [label]
        assert viewer.preview.pixmap().toImage() != clean_image

        graph.angle_source.setCurrentText("Estimated world (3D)")
        assert [label.text for label in painted] == ["Right Hip 80.0°"]
        assert viewer.goto_frame(1)
        assert [label.text for label in viewer.preview._labels] == ["Right Hip 90.0°"]
        assert [label.text for label in painted] == ["Right Hip 80.0°"]
        assert viewer.goto_frame(2) and viewer.preview._labels == ()
        viewer.back_button.click()
        assert studio.goto_frame(1)
        assert [label.text for label in painted] == ["Right Hip 90.0°"]

        studio.graph_viewer_button.click()
        viewer = studio.annotation_graph_window
        assert viewer.graph.angle_source.currentText() == "Estimated world (3D)"
        assert viewer.graph.angle_selection().checked == {"angle_right_hip"}
        viewer.graph._set_all_traces(False)
        assert painted == []
        assert not viewer.overlay_button.isChecked()
        viewer.back_button.click()
        assert parquet.read_bytes() == features_before and annotation.read_bytes() == notes_before
        detail(observed="Only the checked right hip was labeled; source changes and frame gaps propagated and reopening retained the selection.")
    finally:
        studio.close()


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
