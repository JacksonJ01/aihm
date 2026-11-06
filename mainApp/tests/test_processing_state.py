from aihumo.processing_state import ProcessingState


def test_processing_state_quick_and_full_compatibility():
    state = ProcessingState.new(
        session_id="S1",
        video_id="V1",
        source_fingerprint={"path": "/video.mp4", "size_bytes": 10, "modified_ns": 11, "sha256": "source"},
        model_fingerprint={"path": "/model.task", "size_bytes": 20, "modified_ns": 21, "sha256": "model"},
        config_fingerprint="cfg",
    )
    assert state.compatible_quickly_with(
        source_fingerprint={"path": "/video.mp4", "size_bytes": 10, "modified_ns": 11},
        model_fingerprint={"path": "/model.task", "size_bytes": 20, "modified_ns": 21},
        config_fingerprint="cfg",
    )
    assert state.compatible_with(
        source_fingerprint={"path": "/video.mp4", "size_bytes": 10, "modified_ns": 11, "sha256": "source"},
        model_fingerprint={"path": "/model.task", "size_bytes": 20, "modified_ns": 21, "sha256": "model"},
        config_fingerprint="cfg",
    )
    assert not state.compatible_with(
        source_fingerprint={"path": "/video.mp4", "size_bytes": 10, "modified_ns": 11, "sha256": "changed"},
        model_fingerprint={"path": "/model.task", "size_bytes": 20, "modified_ns": 21, "sha256": "model"},
        config_fingerprint="cfg",
    )
