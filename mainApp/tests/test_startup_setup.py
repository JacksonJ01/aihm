from pathlib import Path

from app.AIHuMoDataStudio import HomeWindow
from app.preferences import PreferenceStore, StartupSetupDialog


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

