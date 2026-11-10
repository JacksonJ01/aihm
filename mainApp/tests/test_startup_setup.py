from pathlib import Path

from PyQt6.QtWidgets import QTabWidget

from app.AIHuMoDataStudio import HomeWindow
from app.preferences import DesktopPreferences, PreferenceStore, PreferencesDialog, StartupSetupDialog


def test_startup_setup_persists_participant_and_starter_video(qt_app, tmp_path):
    store = PreferenceStore(tmp_path / "settings.json")
    dialog = StartupSetupDialog(store)
    dialog.participant_edit.setText("P001")
    video = tmp_path / "starter.mp4"
    video.write_bytes(b"video placeholder")
    dialog.video_edit.setText(str(video))
    dialog._save()

    loaded = PreferenceStore(tmp_path / "settings.json").values
    assert loaded.setup_completed is True
    assert loaded.participants == ("P001",)
    assert loaded.default_participant == "P001"
    assert loaded.starter_video == str(video)
    assert dialog.setup == {"participant": "P001", "video": str(video), "open_video": True}


def test_startup_setup_skip_is_persisted_without_a_video(qt_app, tmp_path):
    store = PreferenceStore(tmp_path / "settings.json")
    dialog = StartupSetupDialog(store)
    dialog._skip()

    loaded = PreferenceStore(tmp_path / "settings.json").values
    assert loaded.setup_completed is True
    assert loaded.starter_video == ""
    assert dialog.setup == {}


def test_starter_artifacts_finds_processed_feature_pair(tmp_path):
    session = tmp_path / "S001"
    video_dir = session / "video"
    features_dir = session / "features"
    video_dir.mkdir(parents=True)
    features_dir.mkdir()
    video = video_dir / "V001_skeleton.mp4"
    parquet = features_dir / "V001_features.parquet"
    video.write_bytes(b"video")
    parquet.write_bytes(b"parquet")

    found_video, found_parquet = HomeWindow._starter_artifacts(video)
    assert found_video == video
    assert found_parquet == parquet


def test_extended_preferences_round_trip_and_bounds(tmp_path):
    path = tmp_path / "settings.json"
    store = PreferenceStore(path)
    store.save(DesktopPreferences(
        default_camera_name="side_camera",
        default_playback_speed=5.0,
        autosave_interval_s=45,
        theme="Dark",
        confidence_threshold=0.8,
        smoothing_method="Savitzky-Golay",
        default_annotation_layer="set",
        auto_update_context=True,
    ))
    loaded = PreferenceStore(path).values
    assert loaded.default_camera_name == "side_camera"
    assert loaded.default_playback_speed == 5.0
    assert loaded.autosave_interval_s == 45
    assert loaded.theme == "Dark"
    assert loaded.confidence_threshold == 0.8
    assert loaded.smoothing_method == "Savitzky-Golay"
    assert loaded.default_annotation_layer == "set"


def test_legacy_preferences_keep_new_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"default_frame_jump": 12, "participants": ["P001"]}', encoding="utf-8")
    loaded = PreferenceStore(path).values
    assert loaded.default_frame_jump == 12
    assert loaded.default_camera_name == "camera_01"
    assert loaded.default_playback_speed == 1.0
    assert loaded.auto_update_context is True


def test_preferences_dialog_exposes_optimization_pages(qt_app, tmp_path):
    dialog = PreferencesDialog(PreferenceStore(tmp_path / "settings.json"))
    # Use the visible tab labels rather than implementation-specific child
    # names so this remains stable if the settings layout is reorganized.
    tab_widget = next(widget for widget in dialog.findChildren(QTabWidget))
    labels = [tab_widget.tabText(index) for index in range(tab_widget.count())]
    assert {"General", "Timeline & graphs", "Playback", "Visualization", "Data & processing", "Annotation"} <= set(labels)

