import cv2
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from aihumo.alignment import (
    SOURCE_LABELS, Recording, TimeMap, align_recording, export_ranges, export_session, frame_at,
    load_session, process_session, save_session,
)
from aihumo.storage import load_json, save_json_atomic


def write_recording(root, name, fps, duration, start, *, rate=1.0, moving=True):
    directory = root / name
    video = directory / "video" / f"{name}_skeleton.mp4"
    parquet = directory / "parquet" / f"{name}_features.parquet"
    video.parent.mkdir(parents=True)
    parquet.parent.mkdir(parents=True)
    frames = np.arange(round(fps * duration) + 1)
    times = frames / fps
    session_times = start + times * rate
    values = np.full_like(times, 160.0)
    if moving:
        for center, width, depth in [(1.5, .3, 45), (4.2, .65, 110), (8.1, .4, 70), (9.6, .22, 40)]:
            values -= depth * np.exp(-((session_times - center) / width) ** 2)
    pq.write_table(pa.table({
        "frame_id": frames, "timeElapsedS": times, "timestamp_s": times, "angle_left_knee": values + 4,
        "angle_torso2d_left_knee": values, "angle_3d_left_knee": values - 3,
        "review_cross_mean_angle_left_knee": values,
        "review_omega_angle_torso2d_left_knee": times * 10,
        "review_alpha_angle_torso2d_left_knee": times * 20,
    }), parquet)
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), fps, (40, 32))
    assert writer.isOpened()
    try:
        for index in frames:
            writer.write(np.full((32, 40, 3), index % 230, dtype=np.uint8))
    finally:
        writer.release()
    return parquet, video


def test_aligns_three_cameras_and_exports_only_longer_native_ranges(tmp_path):
    front, front_video = write_recording(tmp_path, "front", 30, 10, 0)
    side, side_video = write_recording(tmp_path, "side", 15, 13, -2)
    rear, rear_video = write_recording(tmp_path, "rear", 30, 12, -1)
    recordings, maps, start, end = process_session([side, front, rear])
    assert (start, end) == (0, 10)
    assert [mapping.offset for mapping in maps] == pytest.approx([-2, 0, -1], abs=1 / 15)
    assert all(not mapping.needs_review for mapping in maps)
    assert {source for source, _ in recordings[0].angles} == set(SOURCE_LABELS)
    ranges = export_ranges(recordings, maps, start, end)
    assert ranges == [(30, 180), (0, 300), (30, 330)]
    assert [frame_at(r, m, 4.2, *bounds) for r, m, bounds in zip(recordings, maps, ranges)] == [93, 126, 156]
    with pytest.raises(ValueError, match="shortest"):
        export_ranges(recordings, maps, 0.5, 10)

    original_sizes = [path.stat().st_size for path in (side_video, front_video, rear_video)]
    output = export_session(tmp_path, recordings, maps, start, end)
    loaded, loaded_maps, new_start, new_end = load_session(output / "alignment.json")
    assert loaded_maps == maps
    assert [recording.features for recording in loaded] == [side, front, rear]
    assert (new_start, new_end) == (start, end)
    manifest = load_json(output / "alignment.json")
    manifest["cameras"][1]["features"] = manifest["cameras"][0]["features"]
    duplicate = tmp_path / "duplicate-alignment.json"
    save_json_atomic(manifest, duplicate)
    with pytest.raises(ValueError, match="distinct feature Parquet"):
        load_session(duplicate)
    with pytest.raises(ValueError, match="distinct feature Parquet"):
        save_session(duplicate, [recordings[0], recordings[0], recordings[2]], maps, start, end)
    for protected in (front, front_video, tmp_path / "front" / "annotations" / "front_annotations.json"):
        with pytest.raises(ValueError, match="separate alignment file"):
            save_session(protected, recordings, maps, start, end)
    clips = load_json(output / "clips.json")["clips"]
    assert clips[1]["video"] == str(front_video)
    assert original_sizes == [path.stat().st_size for path in (side_video, front_video, rear_video)]
    for clip, fps, count in zip(clips, (15, 30, 30), (151, 301, 301)):
        capture = cv2.VideoCapture(clip["video"])
        try:
            assert capture.get(cv2.CAP_PROP_FPS) == pytest.approx(fps)
            assert capture.get(cv2.CAP_PROP_FRAME_COUNT) == count
            ok, frame = capture.read()
            assert ok
            assert frame.mean() == pytest.approx(clip["sourceFirstFrame"], abs=8)
        finally:
            capture.release()


def test_missing_motion_is_available_for_manual_alignment(tmp_path):
    front, _ = write_recording(tmp_path, "front", 30, 10, 0)
    empty, _ = write_recording(tmp_path, "empty", 15, 12, -1, moving=False)
    recordings, maps, start, end = process_session([front, empty])
    assert (start, end) == (0, 10)
    assert maps == [TimeMap(), TimeMap(needs_review=True)]
    assert align_recording(*recordings).score is None


def test_estimates_clock_drift_from_multiple_motion_windows(tmp_path):
    rng = np.random.default_rng(16)
    centers = rng.uniform(0, 96, size=60)
    widths = rng.uniform(0.15, 0.8, size=60)
    weights = rng.uniform(10, 40, size=60)

    def recording(name, fps, duration, offset, rate):
        frames = np.arange(fps * duration + 1)
        times = frames / fps + 0.0015 * np.sin(frames)
        difference = times[:, None] * rate + offset - centers
        angles = 150 - (np.exp(-(difference / widths) ** 2) * weights).sum(axis=1)
        return Recording(tmp_path / name, tmp_path / name, name, times, {("world", "left_knee"): angles})

    reference = recording("front", 30, 96, 0, 1)
    candidate = recording("side", 15, 100, -2.4, 1.007)
    mapping = align_recording(reference, candidate)
    assert not mapping.needs_review
    assert mapping.offset == pytest.approx(-2.4, abs=0.09)
    assert mapping.rate == pytest.approx(1.007, abs=0.001)
    assert mapping.session_time(96) == pytest.approx(-2.4 + 1.007 * 96, abs=0.09)


def test_sessions_reject_more_than_four_cameras(tmp_path):
    with pytest.raises(ValueError, match="between 2 and 4"):
        process_session([tmp_path / "unused"] * 5)
    saved = tmp_path / "alignment.json"
    save_json_atomic({"version": 1, "cameras": [{}] * 5}, saved)
    with pytest.raises(ValueError, match="between 2 and 4"):
        load_session(saved)


def test_aligned_annotation_workspace_uses_mode_one_controls(tmp_path, monkeypatch, qt_app):
    from types import SimpleNamespace
    from matplotlib.backend_bases import MouseEvent
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from PyQt6.QtCore import QCoreApplication, QEvent, Qt
    from PyQt6.QtGui import QKeyEvent, QPalette
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QPushButton, QSlider

    from app import aligned_graph_viewer
    from app.graph_viewer import InteractiveGraphViewer
    from app.mode2_alignment import SessionAlignmentWindow
    from app.mode1_annotation import AnnotationStudio

    app = qt_app
    paths = [write_recording(tmp_path, f"camera-{i}", fps, duration, offset)[0]
             for i, (fps, duration, offset) in enumerate(((30, 10, 0), (15, 13, -2), (30, 12, -1), (24, 14, -3)))]
    viewer = SessionAlignmentWindow(None, tmp_path)
    viewer.resize(1100, 680)
    viewer.show()
    try:
        assert not viewer.alignment_controls.isVisible() and not viewer.session_slider.isEnabled()
        for count in (2, 3, 4, 2):
            viewer._open_session(process_session(paths[:count]), tmp_path / "saved.json")
            viewer._refresh_controls()
            app.processEvents()
            assert len(viewer.panes) == count
            assert viewer.selected_camera == 0
            assert (viewer.panes[0].buffer.behind, viewer.panes[0].buffer.ahead) == (50, 50)
            assert (viewer.panes[1].buffer.behind, viewer.panes[1].buffer.ahead) == (16, 48)
            assert isinstance(viewer.studio, AnnotationStudio)
            assert not viewer.studio.isWindow()
            assert viewer.studio.window() is viewer
            assert viewer.studio.video_layout.indexOf(viewer.grid) == 1
            assert viewer.studio.annotation_table.isVisible()
            assert viewer.centralWidget().layout().itemAt(1).widget() is viewer.stack
            assert viewer.studio.isAncestorOf(viewer.alignment_controls)
            assert [button for button in viewer.findChildren(QPushButton)
                    if button.isVisible() and button.text() == "Play"] == [viewer.studio.play_button]
            play_bottom = viewer.studio.play_button.mapTo(viewer, viewer.studio.play_button.rect().bottomRight()).y()
            assert viewer.alignment_controls.mapTo(viewer, viewer.alignment_controls.rect().topLeft()).y() > play_bottom
            assert viewer.session_transport.isAncestorOf(viewer.session_time_label)
            assert viewer.session_time_label.isVisible()
            assert viewer.session_transport.mapTo(viewer, viewer.session_transport.rect().bottomRight()).y() < play_bottom
            assert [slider for slider in viewer.findChildren(QSlider) if slider.isVisible()] == [viewer.session_slider]
            for control in (viewer.start, viewer.end, viewer.reset_button,
                            viewer.compare_button, viewer.offset, viewer.drift, viewer.status):
                assert control.isVisible() and viewer.alignment_controls.isAncestorOf(control)
                assert viewer.rect().contains(control.mapTo(viewer, control.rect().bottomRight()))
            assert viewer.rect().contains(
                viewer.studio.play_button.mapTo(viewer, viewer.studio.play_button.rect().bottomRight())
            )
            grid = viewer.grid.layout()
            rows = 1 if count == 2 else 2
            assert grid.rowCount() == rows
            for index, pane in enumerate(viewer.panes):
                assert pane.isVisible() and pane.button.image_rect().isValid()
                assert grid.itemAtPosition(*divmod(index, 2)).widget() is pane
                if count == 2:
                    assert pane.height() == viewer.grid.height()
            if count == 3:
                assert grid.itemAtPosition(1, 1) is None

            viewer._render(4.2)
            assert [pane.frame_id for pane in viewer.panes] == [126, 93, 156, 173][:count]
            side_button = viewer.panes[1].button
            # Click the blank margin to confirm the full tile remains selectable.
            QTest.mouseClick(side_button, Qt.MouseButton.LeftButton, pos=side_button.rect().topLeft())
            assert viewer.selected_camera == viewer.preview_buttons.checkedId() == 1
            assert (viewer.panes[1].buffer.behind, viewer.panes[1].buffer.ahead) == (50, 50)
            assert (viewer.panes[0].buffer.behind, viewer.panes[0].buffer.ahead) == (16, 48)
            assert viewer.current_time == 4.2
            assert viewer.studio.current_frame == 93
            assert viewer.studio.video_layout.indexOf(viewer.grid) == 1
            assert viewer.studio.isAncestorOf(viewer.alignment_controls)
            assert viewer.studio.frame_spin.value() == 93
            assert viewer.studio.isAncestorOf(viewer.session_transport)
            assert [slider for slider in viewer.findChildren(QSlider) if slider.isVisible()] == [viewer.session_slider]
            assert not viewer.studio.annotation_json_path.exists()
            side_pane = viewer.panes[1]
            tile_size = side_pane.size()
            image = side_button.image_rect()
            highlight = side_button.palette().color(QPalette.ColorRole.Highlight)
            snapshot = side_button.grab()
            pixels, scale = snapshot.toImage(), snapshot.devicePixelRatio()
            y = round(image.center().y() * scale)
            assert pixels.pixelColor(round((image.left() - 3) * scale), y) == highlight
            assert pixels.pixelColor(0, y) != highlight
            viewer.studio.camera_view.setCurrentText("Maximize Selected")
            app.processEvents()
            assert [pane for pane in viewer.panes if pane.isVisible()] == [side_pane]
            grid = viewer.grid.layout()
            assert grid.getItemPosition(grid.indexOf(side_pane)) == (0, 0, rows, 2)
            assert side_pane.width() > tile_size.width() and side_pane.height() >= tile_size.height()
            assert side_pane.button.image_rect().height() >= image.height()
            if rows == 2:
                assert side_pane.height() > tile_size.height()
                assert side_pane.button.image_rect().height() > image.height()
            assert viewer.current_time == 4.2 and viewer.studio.current_frame == 93
            viewer.studio.camera_view.setCurrentText("Show Multi View")
            app.processEvents()
            assert all(pane.isVisible() for pane in viewer.panes)
            assert all(grid.itemAtPosition(*divmod(i, 2)).widget() is pane for i, pane in enumerate(viewer.panes))

        studio = viewer.studio
        now = 100.0
        monkeypatch.setattr(aligned_graph_viewer, "monotonic", lambda: now)
        assert studio.play_button.isVisible() and studio.play_button.isEnabled()
        for pane, target in zip(viewer.panes, (132, 96)):
            assert pane.buffer.read(pane.capture, target)[0]
        QTest.mouseClick(studio.play_button, Qt.MouseButton.LeftButton)
        assert studio.playback.playing and studio.play_button.text() == "Pause"
        now += 0.2
        studio.playback.advance()
        assert [pane.frame_id for pane in viewer.panes] == [132, 96]
        assert viewer.session_time_label.text() == "Session 4.400 s"
        studio.play_button.click()
        assert not studio.playback.playing and studio.play_button.text() == "Play"
        viewer.session_slider.setValue(viewer.session_slider.maximum() // 2)
        assert viewer.current_time == pytest.approx(5.0)
        assert [pane.frame_id for pane in viewer.panes] == [150, 105]
        viewer._render(4.2)
        studio.start_range_capture()
        studio.goto_frame(105)
        studio.finish_embedded_annotation()
        front, side = viewer.studios[0], viewer.studios[1]
        front_row = load_json(front.annotation_json_path)["annotations"][0]
        side_row = load_json(side.annotation_json_path)["annotations"][0]
        assert (front_row["start_frame"], front_row["end_frame"]) == (126, 150)
        assert (side_row["start_frame"], side_row["end_frame"]) == (93, 105)
        assert front_row["aligned_annotation_id"] == side_row["aligned_annotation_id"]
        assert not front.annotation_parquet_path.samefile(side.annotation_parquet_path)
        for saved, bounds in ((front, (126, 150)), (side, (93, 105))):
            rows = pq.read_table(saved.annotation_parquet_path, columns=["start_frame", "end_frame"]).to_pylist()
            assert rows == [{"start_frame": bounds[0], "end_frame": bounds[1]}]

        studio.annotation_scope.setCurrentIndex(1)
        studio.goto_frame(120)
        studio.start_range_capture()
        studio.goto_frame(125)
        studio.finish_embedded_annotation()
        assert len(load_json(front.annotation_json_path)["annotations"]) == 1
        assert len(load_json(side.annotation_json_path)["annotations"]) == 2
        assert pq.read_metadata(front.annotation_parquet_path).num_rows == 1
        assert pq.read_metadata(side.annotation_parquet_path).num_rows == 2

        studio.camera_view.setCurrentText("Maximize Selected")
        graph_reads = []
        read_recording = InteractiveGraphViewer._read_recording

        def track_graph_read(graph_viewer, path):
            graph_reads.append(path)
            return read_recording(graph_viewer, path)

        monkeypatch.setattr(InteractiveGraphViewer, "_read_recording", track_graph_read)
        studio.play_button.click()
        assert studio.playback.playing
        studio.open_annotation_graph()
        graph_viewer = viewer.aligned_graph
        side_graph = graph_viewer.graph
        assert viewer.review_suspended and not studio.playback.playing
        studio.speed_control.setCurrentIndex(studio.speed_control.findData(2.0))
        assert graph_viewer.speed_control.currentData() == 2.0
        graph_viewer.play_button.click()
        assert graph_viewer.playback.playing and not studio.playback.playing
        assert studio.play_button.text() == "Play"
        graph_viewer.play_button.click()
        assert not graph_viewer.playback.playing
        assert viewer.window() is viewer
        key = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier)
        assert graph_viewer.eventFilter(viewer, key) is False
        assert all(graph_pane.buffer is pane.buffer and graph_pane.capture is pane.capture
                   for pane, graph_pane in zip(viewer.panes, graph_viewer.panes))
        assert graph_viewer.selected_camera == 1
        assert graph_viewer.current_frame == 125
        assert graph_viewer.camera_view.currentText() == "Maximize Selected"
        assert [pane.isVisible() for pane in graph_viewer.panes] == [False, True]
        graph_viewer.camera_view.setCurrentText("Show Multi View")
        assert studio.camera_view.currentText() == "Show Multi View"
        assert all(pane.isVisible() for pane in graph_viewer.panes)
        assert graph_viewer.preview.layout().rowCount() == 1
        assert all(pane.height() == graph_viewer.preview.height() for pane in graph_viewer.panes)
        assert graph_viewer.current_frame == studio.current_frame == 125
        assert graph_viewer.graph.axis.get_xlabel() == "Session time (s)"
        assert graph_viewer.graph.dataframe["frame_id"].iloc[0] == 30
        graph_viewer.frame_spin.setValue(120)
        assert graph_viewer.current_frame == 120
        assert studio.current_frame == 125
        assert [pane.frame_id for pane in graph_viewer.panes] == [180, 120]
        assert list(graph_viewer.graph._cursor.get_xdata()) == [6.0, 6.0]
        graph = graph_viewer.graph
        graph._on_scroll(SimpleNamespace(inaxes=graph.axis, xdata=1.5, button="up"))
        assert sum(graph.axis.get_xlim()) / 2 == pytest.approx(6.0)
        assert [pane.frame_id for pane in graph_viewer.panes] == [180, 120]

        viewer.open_comparison(viewer=graph_viewer)
        comparison = viewer.comparison
        canvas = comparison.findChild(FigureCanvasQTAgg)
        axes, = canvas.figure.axes
        cursor = axes.lines[-1]
        assert list(cursor.get_xdata()) == [6.0, 6.0]
        seek_toggle = next(button for button in comparison.findChildren(QPushButton) if button.text() == "Zoom to Seek")
        assert not seek_toggle.isChecked() and not graph.zoom_to_seek.isChecked()
        next(button for button in comparison.findChildren(QPushButton) if button.text() == "+").click()
        canvas.draw()
        x, y = axes.transData.transform((4.0, sum(axes.get_ylim()) / 2))
        event = MouseEvent("scroll_event", canvas, x, y, button="up", step=1)
        canvas.callbacks.process("scroll_event", event)
        assert sum(axes.get_xlim()) / 2 == pytest.approx(6.0)
        assert [pane.frame_id for pane in graph_viewer.panes] == [180, 120]
        canvas.draw()
        x, y = axes.transData.transform((7.0, sum(axes.get_ylim()) / 2))
        event = MouseEvent("scroll_event", canvas, x, y, button="up", step=1, key="control")
        canvas.callbacks.process("scroll_event", event)
        assert sum(axes.get_xlim()) / 2 == pytest.approx(6.0)
        assert list(cursor.get_xdata()) == [6.0, 6.0]
        graph.zoom_to_seek.click()
        assert seek_toggle.isChecked()
        assert seek_toggle.text() == graph.zoom_to_seek.text() == "Zoom at Playhead"
        canvas.draw()
        x, y = axes.transData.transform((7.0, sum(axes.get_ylim()) / 2))
        event = MouseEvent("scroll_event", canvas, x, y, button="up", step=1)
        canvas.callbacks.process("scroll_event", event)
        assert sum(axes.get_xlim()) / 2 == pytest.approx(7.0)
        assert list(cursor.get_xdata()) == [7.0, 7.0]
        assert [pane.frame_id for pane in graph_viewer.panes] == [210, 135]
        canvas.draw()
        x, y = axes.transData.transform((6.6, sum(axes.get_ylim()) / 2))
        event = MouseEvent("scroll_event", canvas, x, y, button="down", step=-1)
        canvas.callbacks.process("scroll_event", event)
        assert list(cursor.get_xdata()) == pytest.approx([6.6, 6.6])
        assert [pane.frame_id for pane in graph_viewer.panes] == [198, 129]
        seek_toggle.click()
        assert not graph.zoom_to_seek.isChecked()
        assert seek_toggle.text() == graph.zoom_to_seek.text() == "Zoom to Seek"
        seek_toggle.click()
        graph_viewer.frame_spin.setValue(125)
        time = viewer.current_time
        assert list(cursor.get_xdata()) == [time, time]
        assert [pane.frame_id for pane in graph_viewer.panes] == [190, 125]
        assert studio.current_frame == 125
        comparison.close()
        graph_viewer.camera_view.setCurrentText("Maximize Selected")
        graph_viewer.select_camera(0)
        front_graph = graph_viewer.graph
        assert front_graph.zoom_to_seek.isChecked()
        assert graph_viewer.current_frame == 190
        assert viewer.selected_camera == 1 and viewer.studio.current_frame == 125
        assert [pane.isVisible() for pane in graph_viewer.panes] == [True, False]
        assert [pane.isVisible() for pane in viewer.panes] == [False, True]
        graph_viewer.select_camera(1)
        assert graph_viewer.graph is side_graph and graph_viewer.current_frame == 125
        assert side_graph.zoom_to_seek.isChecked()
        graph_viewer.select_camera(0)
        assert graph_viewer.graph is front_graph and graph_viewer.current_frame == 190
        assert graph_reads == [paths[1], paths[0]]
        graph_viewer.close()
        assert viewer.selected_camera == 0
        assert viewer.studio.current_frame == 190
        assert viewer.studio.camera_view.currentText() == "Maximize Selected"
        assert all(pane.capture.isOpened() for pane in viewer.panes)
        assert viewer.studio.goto_frame(191)
    finally:
        viewer.close()
        viewer.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_aligned_annotation_layers_filter_and_save_across_four_camera_angles(tmp_path, monkeypatch, qt_app):
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QMessageBox

    from app.mode2_alignment import SessionAlignmentWindow

    app = qt_app
    angles = ("Front", "Side", "Rear", "Three-quarter")
    paths = []
    for index, (angle, fps, duration, offset) in enumerate(
        zip(angles, (30, 15, 30, 24), (10, 13, 12, 14), (0, -2, -1, -3))
    ):
        name = f"camera-{index}"
        features, _ = write_recording(tmp_path, name, fps, duration, offset)
        save_json_atomic({"video_id": name, "camera_angle": angle},
                         features.parent.parent / "metadata" / f"{name}_metadata.json")
        paths.append(features)
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _, title, body: errors.append((title, body)))
    monkeypatch.setattr(QMessageBox, "warning", lambda _, title, body: errors.append((title, body)))
    viewer = SessionAlignmentWindow(None, tmp_path)
    viewer.show()
    saved_alignment = tmp_path / "alignment.json"
    layers = {
        "activity_state": (30, 270), "set": (60, 240), "rep": (90, 150),
        "phase": (96, 132), "form_interval": (105, 120),
    }
    try:
        result = process_session(paths)
        save_session(saved_alignment, *result)
        viewer._open_session(load_session(saved_alignment), saved_alignment)
        studio = viewer.studio
        for layer, (first, last) in layers.items():
            studio.editor_annotation_type.setCurrentIndex(studio.editor_annotation_type.findData(layer))
            assert studio.annotation_model.rowCount() == 0
            assert studio.editor_form_label.isEnabled() == (layer == "form_interval")
            assert studio.editor_phase.isEnabled() == (layer == "phase")
            assert studio.editor_rep_id.isEnabled() == (layer == "rep")
            assert studio.editor_set_id.isEnabled() == (layer == "set")
            assert studio.editor_camera_angle.isEnabled() == (layer == "activity_state")
            assert studio.goto_frame(first)
            studio.start_range_capture()
            if layer == "activity_state":
                studio.editor_activity_state.setCurrentText("active")
            elif layer == "set":
                studio.editor_exercise_selector.set_value("bodyweight_squat")
                studio.editor_set_id.setValue(1)
            elif layer == "phase":
                studio.editor_phase.setCurrentIndex(studio.editor_phase.findData("eccentric"))
            elif layer == "form_interval":
                studio.editor_form_label.setCurrentText("poor")
                studio.editor_issue_type.set_checked_values(["form_deviation"])
                studio.editor_affected_joints.set_checked_values(["left_knee"])
            assert studio.goto_frame(last)
            studio.finish_embedded_annotation()
            assert not errors
            assert studio.annotation_model.rowCount() == 1

        all_ids = {}
        for index, angle in enumerate(angles):
            camera = viewer.studios[index]
            rows = {row["annotation_type"]: row for row in load_json(camera.annotation_json_path)["annotations"]}
            assert rows.keys() == layers.keys()
            recording, mapping = viewer.recordings[index], viewer.maps[index]
            for layer, (first, last) in layers.items():
                row = rows[layer]
                expected = [frame_at(recording, mapping, frame / 30, *viewer.ranges[index]) for frame in (first, last)]
                assert [row["start_frame"], row["end_frame"]] == expected
                assert [row["start_time_s"], row["end_time_s"]] == pytest.approx(recording.times[expected])
                assert all_ids.setdefault(layer, row["aligned_annotation_id"]) == row["aligned_annotation_id"]
            assert rows["activity_state"]["camera_angle"] == angle
            assert rows["set"]["exercise"] == rows["rep"]["exercise"] == rows["phase"]["exercise"] == "bodyweight_squat"
            assert rows["rep"]["rep_id"] == rows["phase"]["rep_id"] == 1
            assert rows["phase"]["phase"] == "eccentric"
            assert rows["form_interval"]["form_label"] == "poor"
            assert rows["form_interval"]["affected_joints"] == ["left_knee"]
            parquet = pq.read_table(camera.annotation_parquet_path).to_pylist()
            assert {row["annotation_type"]: row["form_label"] for row in parquet}["form_interval"] == "poor"

        viewer._open_session(load_session(saved_alignment), saved_alignment)
        studio = viewer.studio
        studio.editor_annotation_type.setCurrentIndex(studio.editor_annotation_type.findData("form_interval"))
        viewer._select_camera(1)
        studio = viewer.studio
        assert studio.editor_annotation_type.currentData() == "form_interval"
        assert studio.annotation_model.rowCount() == 1
        studio.show_all_annotation_layers.setChecked(True)
        assert studio.annotation_model.rowCount() == 5
        studio.show_all_annotation_layers.setChecked(False)
        studio.annotation_table.selectRow(0)
        studio.edit_selected_annotation()
        assert studio.editor_form_label.currentText() == "poor"
        studio.editor_form_label.setCurrentText("acceptable")
        studio.finish_embedded_annotation()
        assert not errors
        assert studio.annotation_model.rowCount() == 1
        studio.annotation_scope.setCurrentIndex(studio.annotation_scope.findData(False))
        assert studio.goto_frame(90)
        studio.start_range_capture()
        studio.editor_form_label.setCurrentText("good")
        assert studio.goto_frame(95)
        studio.finish_embedded_annotation()
        assert not errors
        assert studio.annotation_model.rowCount() == 2
        for index, features in enumerate(paths):
            annotation = features.parent.parent / "annotations" / f"camera-{index}_annotations.json"
            expected_labels = ["acceptable", "good"] if index == 1 else ["poor"]
            rows = load_json(annotation)["annotations"]
            assert len(rows) == 4 + len(expected_labels)
            assert [row["form_label"] for row in rows if row["annotation_type"] == "form_interval"] == expected_labels
            form = pq.read_table(annotation.with_suffix(".parquet"), filters=[("annotation_type", "=", "form_interval")])
            assert form["form_label"].to_pylist() == expected_labels
    finally:
        if viewer.studio is not None:
            viewer.studio.annotation_start_frame = None
        viewer.close()
        viewer.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.fixture
def mixed_rate_studio(tmp_path, monkeypatch, qt_app):
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QMessageBox

    from app.mode2_alignment import SessionAlignmentWindow

    app = qt_app
    front, _ = write_recording(tmp_path, "front", 30, 10, 0)
    side, _ = write_recording(tmp_path, "side", 15, 13, -2)
    messages = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _, title, body: messages.append(body))
    monkeypatch.setattr(QMessageBox, "warning", lambda _, title, body: messages.append(body))
    viewer = SessionAlignmentWindow(None, tmp_path)
    viewer._open_session(process_session([front, side]), tmp_path / "alignment.json")
    try:
        yield viewer, messages
    finally:
        for studio in viewer.studios.values():
            studio.annotation_start_frame = None
        viewer.close()
        viewer.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def capture_annotation(studio, first, last, *, notes=""):
    assert studio.goto_frame(first)
    studio.start_range_capture()
    studio.editor_notes.setPlainText(notes)
    assert studio.goto_frame(last)
    studio.finish_embedded_annotation()


def test_adjacent_activity_intervals_survive_rounding_to_slower_camera(mixed_rate_studio):
    viewer, messages = mixed_rate_studio
    side, mapping, bounds = viewer.recordings[1], viewer.maps[1], viewer.ranges[1]
    first_end = next(i for i in range(90, 100)
                     if frame_at(side, mapping, i / 30, *bounds) == frame_at(side, mapping, (i + 1) / 30, *bounds))
    capture_annotation(viewer.studio, 60, first_end)
    capture_annotation(viewer.studio, first_end + 1, 120)
    assert not messages
    front_rows, side_rows = (studio.annotations for studio in viewer.studios.values())
    assert front_rows[0]["end_frame"] + 1 == front_rows[1]["start_frame"]
    assert side_rows[0]["end_frame"] + 1 == side_rows[1]["start_frame"]
    studio = viewer.studio
    studio.editor_annotation_type.setCurrentIndex(studio.editor_annotation_type.findData("set"))
    capture_annotation(studio, first_end + 1, 110)
    assert not messages
    side_set = next(row for row in viewer.studios[1].annotations if row["annotation_type"] == "set")
    assert side_set["start_frame"] == side_rows[1]["start_frame"]


def test_shared_save_preserves_changes_from_another_annotation_window(mixed_rate_studio):
    viewer, messages = mixed_rate_studio
    capture_annotation(viewer.studio, 30, 90)
    front, side = (viewer.studios[index].annotation_json_path for index in range(2))
    original = front.read_bytes()
    external = load_json(side)
    external["annotations"][0]["notes"] = "Edited in another window"
    save_json_atomic(external, side)
    capture_annotation(viewer.studio, 120, 150)
    assert any("reopen" in message.lower() for message in messages)
    assert front.read_bytes() == original
    assert load_json(side) == external
    viewer._select_camera(1)
    viewer.studio.annotation_scope.setCurrentIndex(viewer.studio.annotation_scope.findData(False))
    capture_annotation(viewer.studio, 90, 105)
    assert "reopen" in messages[-1].lower()
    assert load_json(side) == external


def test_failed_shared_save_rolls_back_and_can_retry(mixed_rate_studio, monkeypatch):
    from app import mode2_alignment

    viewer, messages = mixed_rate_studio
    capture_annotation(viewer.studio, 30, 90)
    studios = list(viewer.studios.values())
    paths = [path for studio in studios for path in (studio.annotation_json_path, studio.annotation_parquet_path)]
    original = [path.read_bytes() for path in paths]

    def fail_second_camera(document, path):
        if path == studios[1].annotation_json_path:
            raise OSError("Cannot write side annotations")
        return save_json_atomic(document, path)

    with monkeypatch.context() as failure:
        failure.setattr(mode2_alignment, "save_json_atomic", fail_second_camera)
        capture_annotation(viewer.studio, 120, 150)
    assert "Cannot write side annotations" in messages.pop()
    assert [path.read_bytes() for path in paths] == original
    assert [len(studio.annotations) for studio in studios] == [1, 1]
    assert viewer.studio.annotation_start_frame == 120
    viewer.studio.finish_embedded_annotation()
    assert not messages
    assert [len(studio.annotations) for studio in studios] == [2, 2]


def test_mode_two_does_not_shorten_existing_row_outside_trim(mixed_rate_studio):
    viewer, messages = mixed_rate_studio
    studio = viewer.studio
    capture_annotation(studio, 30, 150, notes="Original range")
    original = studio.annotation_json_path.read_bytes()
    viewer._set_window((2.0, 7.0))
    viewer._update_review()
    studio.annotation_table.selectRow(0)
    studio.edit_selected_annotation()
    assert studio.annotation_edit_id is None
    assert "trim" in studio.annotation_status.text().lower()
    studio.finish_embedded_annotation()
    assert studio.annotation_json_path.read_bytes() == original
    assert not messages


def test_shared_auto_rep_numbers_use_each_cameras_own_set(mixed_rate_studio):
    viewer, messages = mixed_rate_studio
    capture_annotation(viewer.studio, 30, 240)
    studio = viewer.studio
    studio.editor_annotation_type.setCurrentIndex(studio.editor_annotation_type.findData("set"))
    capture_annotation(studio, 45, 220)

    viewer._select_camera(1)
    studio = viewer.studio
    studio.annotation_scope.setCurrentIndex(studio.annotation_scope.findData(False))
    studio.editor_annotation_type.setCurrentIndex(studio.editor_annotation_type.findData("rep"))
    capture_annotation(studio, 55, 62)

    viewer._select_camera(0)
    studio = viewer.studio
    assert studio.editor_annotation_type.currentData() == "rep"
    capture_annotation(studio, 90, 120)
    assert not messages
    front, side = ([row for row in studio.annotations if row["annotation_type"] == "rep"]
                   for studio in viewer.studios.values())
    assert [row["rep_id"] for row in front] == [1]
    assert [row["rep_id"] for row in side] == [1, 2]
    assert front[0]["aligned_annotation_id"] == side[1]["aligned_annotation_id"]


def test_comparison_cursor_moves_when_trim_moves_past_playhead(mixed_rate_studio):
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

    viewer, messages = mixed_rate_studio
    viewer.open_comparison()
    canvas = viewer.comparison.findChild(FigureCanvasQTAgg)
    viewer._set_window((2.0, 7.0))
    viewer._update_review()
    assert not messages
    assert viewer.studio.current_frame == 60
    assert canvas.figure.axes[0].lines[-1].get_xdata() == [2.0, 2.0]
