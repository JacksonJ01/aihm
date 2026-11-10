from aihumo.workspace import WorkspaceSnapshot, WorkspaceStore


def test_workspace_snapshot_round_trip(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.json")
    item = store.upsert(WorkspaceSnapshot(
        mode=3,
        files={"processedVideo": "video.mp4", "featuresParquet": "features.parquet"},
        identifiers={"participantId": "P001"},
        current_frame=42,
        graph_source="torso2d",
        selected_joints=["left_knee"],
        layer_filter=["set", "rep"],
        layout={"splitter": [600, 900]},
    ))
    reopened = WorkspaceStore(tmp_path / "workspaces.json")
    assert len(reopened.items) == 1
    loaded = reopened.items[0]
    assert loaded.workspace_id == item.workspace_id
    assert loaded.current_frame == 42
    assert loaded.selected_joints == ["left_knee"]
    assert loaded.layout == {"splitter": [600, 900]}


def test_workspace_frame_update_is_atomic_and_validated(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.json")
    item = store.upsert(WorkspaceSnapshot())
    assert store.update_frame(item.workspace_id, 12) is True
    assert store.update_frame(item.workspace_id, 12) is False
    assert store.items[0].current_frame == 12
    try:
        store.update_frame(item.workspace_id, -1)
    except ValueError:
        pass
    else:
        raise AssertionError("negative workspace frames must be rejected")
