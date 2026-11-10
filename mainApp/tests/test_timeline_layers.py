from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.joint_graph import ALL_GRAPHS_MODE, JointGraphWidget, extrema_samples
from app.playback import FrameBuffer, FramePlayback
from app.preferences import DesktopPreferences, PreferenceStore, TimelineSettingsPanel
from app.timeline_layers import interval_color, project_intervals, timeline_preferences, visible_layers


def test_native_annotation_ranges_and_zoom():
    times = np.array([0.0, 0.04, 0.15, 0.2, 0.24])
    rows = [
        {"annotation_type": "activity_state", "start_frame": 0, "end_frame": 4, "activity_state": "active"},
        {"annotation_type": "set", "start_frame": 0, "end_frame": 1, "exercise": "Squat", "set_id": 1},
        {"annotation_type": "set", "start_frame": 2, "end_frame": 4, "exercise": "Curl", "set_id": 2},
        {"annotation_type": "rep", "start_frame": 2, "end_frame": 3, "rep_id": 1},
        {"annotation_type": "phase", "start_frame": 3, "end_frame": 3, "phase": "hold", "annotation_id": "A1"},
        {"annotation_type": "form_interval", "start_frame": 1, "end_frame": 3,
         "issue_type": ["tracking_quality", "form_deviation"]},
    ]
    regions = project_intervals(rows, times, np.arange(len(times)))
    phase = next(item for item in regions if item.annotation_id == "A1")
    assert (phase.start, phase.end) == (0.2, 0.24)
    assert {item.layer for item in regions} == {"activity", "exercise", "set", "rep", "phase", "quality", "form"}
    settings = timeline_preferences()
    sets = [item for item in regions if item.layer == "set"]
    layer = settings["layers"]["set"]
    assert interval_color(sets[0], layer) != interval_color(sets[1], layer)
    assert interval_color(sets[0], layer) == interval_color(sets[1], {**layer, "alternate": False})
    assert visible_layers(settings, 900) == ("activity", "exercise")
    assert visible_layers(settings, 120) == ("activity", "exercise", "set")
    assert "rep" in visible_layers(settings, 20) and "phase" not in visible_layers(settings, 20)
    assert "phase" in visible_layers(settings, 4)
    settings["auto"] = False
    settings["layers"]["rep"]["visible"] = False
    assert "phase" in visible_layers(settings, 3600) and "rep" not in visible_layers(settings, 1)


def test_timeline_overlay_uses_saved_data_and_four_slots(qt_app):
    count = 54_000  # 30 minutes at 30 FPS
    angle = np.linspace(5, 175, count)
    angle[200:700] = np.nan
    angle[1210], angle[1525] = 180, 0
    frame = pd.DataFrame({"frame_id": np.arange(count), "timestamp_s": np.arange(count) / 30,
                          "angle_left_knee": angle, "review_legacy_lm25_speed": 0.25,
                          "review_legacy_lm25_y": 1.0, "pose_present": 1})
    graph = JointGraphWidget(frame, link_video=True)
    try:
        graph.resize(1024, 700)
        graph.show()
        graph.set_graph_mode(ALL_GRAPHS_MODE)
        graph.angle_source.setCurrentText("Legacy (normalized image)")
        graph.landmark_component.setCurrentIndex(graph.landmark_component.findData("positions-speed"))
        graph.set_annotations([
            {"annotation_type": "activity_state", "start_frame": 0, "end_frame": 300},
            {"annotation_type": "rep", "start_frame": 5, "end_frame": 45, "rep_id": 1},
            {"annotation_type": "phase", "start_frame": 15, "end_frame": 20, "phase": "hold", "annotation_id": "A1"},
        ])
        graph.annotation_style.setCurrentText("Overlay")
        assert len(graph._annotation_artists) == 4
        graph.axis.set_xlim(0.0, 3.0)
        graph.canvas.draw()
        angles, position, distance, speed = graph.figure.axes
        assert speed.get_position().bounds[:2] == pytest.approx(
            (position.get_position().x0, distance.get_position().y0))
        assert all(axis.get_xlim() == (0.0, 3.0) for axis in graph.figure.axes)
        collections = angles.collections
        assert len(collections) == 3
        assert collections[0].get_zorder() < collections[1].get_zorder() < collections[2].get_zorder()
        assert collections[-1].get_zorder() < graph._lines["angle_left_knee"].get_zorder()
        assert len(graph._lines["angle_left_knee"].get_xdata()) == 92
        graph.reset_zoom()
        y = graph._lines["angle_left_knee"].get_ydata()
        assert len(y) < count // 10 and np.isnan(y).any() and 0 in y and 180 in y
        graph.annotation_style.setCurrentText("Timeline")
        graph.axis.set_xlim(0.0, 3.0)
        selected = []
        graph.frameSelected.connect(selected.append)
        row = graph._visible_annotation_layers(3).index("phase")
        graph._on_click(SimpleNamespace(inaxes=graph.axis, xdata=0.55, ydata=row, button=1))
        assert graph._selected_annotation == "A1" and selected[-1] in (16, 17)
        graph.set_current_frame(17)
        assert graph._cursor.get_xdata()[0] == pytest.approx(17 / 30)
        pd.testing.assert_series_equal(frame["angle_left_knee"], pd.Series(angle, name="angle_left_knee"))
    finally:
        graph.close()
        graph.dispose()


def test_timeline_preferences_survive_reload_and_reset(qt_app, tmp_path):
    store = PreferenceStore(tmp_path / "settings.json")
    values = timeline_preferences()
    values["style"] = "Overlay"
    values["layers"]["phase"]["semantic"]["hold"] = "#135790"
    values["layers"]["phase"]["opacity"] = 0.47
    values["layers"]["phase"]["visible"] = False
    store.save(DesktopPreferences(timeline=values))
    assert PreferenceStore(store.path).values.timeline == values
    panel = TimelineSettingsPanel(values)
    assert panel.values() == values
    panel._load(timeline_preferences())
    assert panel.values() == timeline_preferences()


def test_viewer_reloads_saved_annotations_without_rewriting_artifacts(qt_app, tmp_path):
    from app.graph_viewer import InteractiveGraphViewer
    from aihumo.storage import annotation_json_for_features, save_json_atomic
    from tests.test_desktop_recovery import write_video

    video = tmp_path / "clip_skeleton.mp4"
    features = tmp_path / "parquet" / "clip_features.parquet"
    features.parent.mkdir()
    write_video(video, 10)
    pd.DataFrame({"frame_id": range(10), "timestamp_s": np.arange(10) / 30,
                  "angle_left_knee": np.linspace(30, 90, 10)}).to_parquet(features, index=False)
    annotations = annotation_json_for_features(features)
    save_json_atomic({"annotations": [{"annotation_id": "A1", "annotation_type": "phase",
                                        "phase": "hold", "start_frame": 3, "end_frame": 4}]}, annotations)
    feature_bytes, annotation_bytes = features.read_bytes(), annotations.read_bytes()
    viewer = InteractiveGraphViewer(video, features)
    try:
        viewer.graph.annotation_style.setCurrentText("Timeline")
        assert viewer.graph._annotation_intervals[0].annotation_id == "A1"
        assert features.read_bytes() == feature_bytes and annotations.read_bytes() == annotation_bytes
        save_json_atomic({"annotations": []}, annotations)
        viewer._refresh_graph_annotations(viewer.graph)
        assert not viewer.graph._annotation_intervals
        assert features.read_bytes() == feature_bytes
    finally:
        viewer.close()


def test_frame_buffer_recovers_from_failed_catch_up(monkeypatch):
    monkeypatch.setattr("app.playback.Thread.start", lambda _: None)
    monkeypatch.setattr("app.playback.Thread.join", lambda *args, **kwargs: None)
    buffer = FrameBuffer("mock", 400, (1920, 1080))
    buffer.request(4, playback=True)
    assert buffer.ready_for_playback(50, 4) is None
    buffer._failed.add(50)
    # The elapsed clock is already outside the prefetched window. The failed
    # catch-up frame must go to the foreground decoder instead of waiting.
    assert buffer.ready_for_playback(110, 4) == 50
    buffer.request(50, playback=True)
    buffer._frames[55] = np.zeros((1, 1, 3), dtype=np.uint8)
    assert buffer.ready_for_playback(56, 50) == 55
    buffer.close()


def test_five_times_playback_keeps_advancing(qt_app, monkeypatch):
    from PyQt6.QtWidgets import QWidget
    clock = [0.0]
    shown = [0]
    parent = QWidget()
    monkeypatch.setattr("app.playback.monotonic", lambda: clock[0])
    playback = FramePlayback(parent, timestamps=np.arange(700) / 30, position=lambda: shown[-1],
                             display_frame=lambda index: shown.append(index) or True,
                             refresh_paused_frame=lambda: None)
    assert max(playback.speed.OPTIONS) == 5
    playback.start(speed=10)
    for step in range(1, 31):
        clock[0] = step * 0.02
        playback.advance()
        assert playback.playing
    assert shown[-1] == 90
    playback.pause()


def test_extrema_samples_keeps_native_frames_at_close_zoom():
    assert extrema_samples(np.arange(60)) == slice(None)
