import numpy as np

from aihumo.tracking import TargetStatus, TargetTracker


def make_pose(cx: float, cy: float = 0.5, scale: float = 0.2) -> np.ndarray:
    points = np.zeros((33, 3), dtype=float)
    points[:, 0] = cx
    points[:, 1] = cy
    points[:, 2] = 0.0
    points[11] = [cx - scale / 2, cy - scale / 2, 0]
    points[12] = [cx + scale / 2, cy - scale / 2, 0]
    points[23] = [cx - scale / 2, cy + scale / 2, 0]
    points[24] = [cx + scale / 2, cy + scale / 2, 0]
    points[25] = [cx - scale / 2, cy + scale, 0]
    points[26] = [cx + scale / 2, cy + scale, 0]
    points[27] = [cx - scale / 2, cy + scale * 1.5, 0]
    points[28] = [cx + scale / 2, cy + scale * 1.5, 0]
    return points


def candidate(tracker, cx, color=None):
    pose = make_pose(cx)
    return tracker.candidate_from_landmarks(pose)


def test_tracker_keeps_target_when_passerby_appears():
    cfg = {
        "enabled": True,
        "warmup_frames": 3,
        "max_missed_frames": 3,
        "reacquire_max_missed_frames": 8,
        "allow_ambiguous_auto_selection": True,
    }
    tracker = TargetTracker(cfg)
    decisions = []
    for frame in range(3):
        decisions.append(tracker.update([candidate(tracker, 0.50)], frame))
    target_id = tracker.target_track_id
    assert target_id is not None
    assert decisions[-1].status == TargetStatus.TRACKED

    decision = tracker.update([candidate(tracker, 0.52), candidate(tracker, 0.80)], 3)
    assert decision.target_track_id == target_id
    assert decision.status == TargetStatus.TRACKED


def test_tracker_does_not_substitute_passerby_during_occlusion():
    cfg = {
        "enabled": True,
        "warmup_frames": 2,
        "max_missed_frames": 3,
        "reacquire_max_missed_frames": 8,
        "allow_ambiguous_auto_selection": True,
    }
    tracker = TargetTracker(cfg)
    tracker.update([candidate(tracker, 0.50)], 0)
    tracker.update([candidate(tracker, 0.51)], 1)
    target_id = tracker.target_track_id
    decision = tracker.update([candidate(tracker, 0.85)], 2)
    assert decision.target_track_id == target_id
    assert decision.status in {TargetStatus.PARTIALLY_OCCLUDED, TargetStatus.OCCLUDED}
    assert decision.pose_confidence == 0.0


def test_tracker_reacquires_original_target():
    cfg = {
        "enabled": True,
        "warmup_frames": 2,
        "max_missed_frames": 2,
        "reacquire_max_missed_frames": 8,
        "allow_ambiguous_auto_selection": True,
    }
    tracker = TargetTracker(cfg)
    tracker.update([candidate(tracker, 0.50)], 0)
    tracker.update([candidate(tracker, 0.51)], 1)
    target_id = tracker.target_track_id
    tracker.update([], 2)
    decision = tracker.update([candidate(tracker, 0.52), candidate(tracker, 0.85)], 3)
    assert decision.target_track_id == target_id
    assert decision.status == TargetStatus.REACQUIRED
