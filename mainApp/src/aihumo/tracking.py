from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import cv2
import numpy as np


class TargetStatus(str, Enum):
    SEARCHING = "searching"
    TRACKED = "tracked"
    PARTIALLY_OCCLUDED = "partially_occluded"
    OCCLUDED = "occluded"
    LOST = "lost"
    REACQUIRED = "reacquired"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class PoseCandidate:
    """One MediaPipe pose candidate represented in normalized image coordinates."""

    landmarks: np.ndarray
    bbox: tuple[float, float, float, float]
    pose_quality: float
    appearance: np.ndarray | None = None

    @property
    def center(self) -> np.ndarray:
        x1, y1, x2, y2 = self.bbox
        return np.array([(x1 + x2) / 2.0, (y1 + y2) / 2.0], dtype=float)

    @property
    def area(self) -> float:
        x1, y1, x2, y2 = self.bbox
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)


@dataclass
class Track:
    track_id: int
    bbox: tuple[float, float, float, float]
    landmarks: np.ndarray
    pose_quality: float
    appearance: np.ndarray | None
    last_frame: int
    missed_frames: int = 0
    hits: int = 1
    age: int = 1
    center_velocity: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=float))
    area_velocity: float = 0.0
    last_match_score: float = 1.0

    @property
    def center(self) -> np.ndarray:
        x1, y1, x2, y2 = self.bbox
        return np.array([(x1 + x2) / 2.0, (y1 + y2) / 2.0], dtype=float)

    @property
    def area(self) -> float:
        x1, y1, x2, y2 = self.bbox
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)

    def predicted_center(self) -> np.ndarray:
        return self.center + self.center_velocity

    def predicted_bbox(self) -> tuple[float, float, float, float]:
        dx, dy = self.center_velocity
        x1, y1, x2, y2 = self.bbox
        return (x1 + dx, y1 + dy, x2 + dx, y2 + dy)

    def to_document(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "bbox": list(self.bbox),
            "landmarks": self.landmarks.tolist(),
            "pose_quality": float(self.pose_quality),
            "appearance": self.appearance.tolist() if self.appearance is not None else None,
            "last_frame": int(self.last_frame),
            "missed_frames": int(self.missed_frames),
            "hits": int(self.hits),
            "age": int(self.age),
            "center_velocity": self.center_velocity.tolist(),
            "area_velocity": float(self.area_velocity),
            "last_match_score": float(self.last_match_score),
        }

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "Track":
        return cls(
            track_id=int(document["track_id"]),
            bbox=tuple(float(value) for value in document["bbox"]),
            landmarks=np.asarray(document["landmarks"], dtype=float),
            pose_quality=float(document["pose_quality"]),
            appearance=(np.asarray(document["appearance"], dtype=float) if document.get("appearance") is not None else None),
            last_frame=int(document["last_frame"]),
            missed_frames=int(document.get("missed_frames", 0)),
            hits=int(document.get("hits", 1)),
            age=int(document.get("age", 1)),
            center_velocity=np.asarray(document.get("center_velocity", [0.0, 0.0]), dtype=float),
            area_velocity=float(document.get("area_velocity", 0.0)),
            last_match_score=float(document.get("last_match_score", 0.0)),
        )


@dataclass(frozen=True)
class TrackingDecision:
    status: TargetStatus
    target_track_id: int | None
    target_confidence: float
    pose_confidence: float
    bbox: tuple[float, float, float, float] | None
    occlusion_ratio: float
    reacquisition_flag: bool
    target_selection_method: str

    @property
    def pose_valid(self) -> bool:
        return self.status in {TargetStatus.TRACKED, TargetStatus.REACQUIRED} and self.pose_confidence > 0.0


class TargetTracker:
    """Lightweight multi-person tracker for participant identity continuity.

    It deliberately does not perform face recognition or claim to know the person's
    real-world identity. It maintains identity continuity within one video using
    motion, box geometry, pose similarity, and a lightweight appearance signature.
    """

    def __init__(self, cfg: dict[str, Any] | None = None):
        cfg = cfg or {}
        self.enabled = bool(cfg.get("enabled", True))
        self.max_tracks = max(1, int(cfg.get("max_tracks", 8)))
        self.max_missed_frames = max(1, int(cfg.get("max_missed_frames", 45)))
        self.reacquire_max_missed_frames = max(self.max_missed_frames, int(cfg.get("reacquire_max_missed_frames", 90)))
        self.min_match_score = float(cfg.get("min_match_score", 0.42))
        self.reacquire_match_score = float(cfg.get("reacquire_match_score", 0.55))
        self.warmup_frames = max(1, int(cfg.get("warmup_frames", 15)))
        self.min_selection_score = float(cfg.get("min_selection_score", 0.40))
        self.ambiguity_margin = float(cfg.get("ambiguity_margin", 0.08))
        self.allow_ambiguous_auto_selection = bool(cfg.get("allow_ambiguous_auto_selection", True))
        weights = cfg.get("matching_weights", {})
        self.w_iou = float(weights.get("iou", 0.30))
        self.w_center = float(weights.get("center", 0.25))
        self.w_scale = float(weights.get("scale", 0.10))
        self.w_pose = float(weights.get("pose", 0.20))
        self.w_appearance = float(weights.get("appearance", 0.15))
        self.tracks: dict[int, Track] = {}
        self.next_track_id = 1
        self.target_track_id: int | None = None
        self.frame_index = -1
        self.target_was_missing = False
        self.target_selection_method = "auto_primary_participant"

    @staticmethod
    def _clip_bbox(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        x1, y1, x2, y2 = bbox
        return (float(np.clip(x1, 0.0, 1.0)), float(np.clip(y1, 0.0, 1.0)),
                float(np.clip(x2, 0.0, 1.0)), float(np.clip(y2, 0.0, 1.0)))

    @staticmethod
    def candidate_from_landmarks(landmarks: np.ndarray, frame_bgr: np.ndarray | None = None) -> PoseCandidate | None:
        points = np.asarray(landmarks, dtype=float)
        if points.shape != (33, 3):
            return None
        xy = points[:, :2]
        finite = np.isfinite(xy).all(axis=1)
        if finite.sum() < 4:
            return None
        valid = xy[finite]
        x1, y1 = valid.min(axis=0)
        x2, y2 = valid.max(axis=0)
        width = max(1e-6, x2 - x1)
        height = max(1e-6, y2 - y1)
        bbox = TargetTracker._clip_bbox((x1, y1, x2, y2))
        visible = points[:, 0:2]
        quality = float(finite.mean())
        appearance = None
        if frame_bgr is not None:
            appearance = TargetTracker._appearance_signature(frame_bgr, bbox)
        return PoseCandidate(points.copy(), bbox, quality, appearance)

    @staticmethod
    def _appearance_signature(frame_bgr: np.ndarray, bbox: tuple[float, float, float, float]) -> np.ndarray | None:
        height, width = frame_bgr.shape[:2]
        x1, y1, x2, y2 = bbox
        left = max(0, min(width - 1, int(x1 * width)))
        top = max(0, min(height - 1, int(y1 * height)))
        right = max(left + 1, min(width, int(x2 * width)))
        bottom = max(top + 1, min(height, int(y2 * height)))
        crop = frame_bgr[top:bottom, left:right]
        if crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [12, 8], [0, 180, 0, 256]).astype(float).ravel()
        norm = np.linalg.norm(hist)
        if norm <= 1e-12:
            return None
        return hist / norm

    @staticmethod
    def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        if intersection <= 0.0:
            return 0.0
        area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
        area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
        union = area_a + area_b - intersection
        return intersection / union if union > 0 else 0.0

    @staticmethod
    def _center_similarity(track: Track, candidate: PoseCandidate) -> float:
        predicted = track.predicted_center()
        distance = float(np.linalg.norm(predicted - candidate.center))
        scale = max(0.05, np.sqrt(max(track.area, candidate.area)))
        return float(np.exp(-distance / scale))

    @staticmethod
    def _scale_similarity(track: Track, candidate: PoseCandidate) -> float:
        if track.area <= 0 or candidate.area <= 0:
            return 0.0
        ratio = candidate.area / track.area
        return float(np.exp(-abs(np.log(max(ratio, 1e-8)))))

    @staticmethod
    def _pose_similarity(a: np.ndarray, b: np.ndarray) -> float:
        if a.shape != b.shape:
            return 0.0
        pa = a[:, :2].copy()
        pb = b[:, :2].copy()
        for points in (pa, pb):
            center = np.nanmean(points[[11, 12, 23, 24]], axis=0)
            scale = np.nanmean([
                np.linalg.norm(points[11] - points[12]),
                np.linalg.norm(points[23] - points[24]),
            ])
            if np.isfinite(center).all() and np.isfinite(scale) and scale > 1e-6:
                points -= center
                points /= scale
        mask = np.isfinite(pa).all(axis=1) & np.isfinite(pb).all(axis=1)
        if mask.sum() < 5:
            return 0.0
        error = float(np.mean(np.linalg.norm(pa[mask] - pb[mask], axis=1)))
        return float(np.exp(-error / 0.75))

    @staticmethod
    def _appearance_similarity(a: np.ndarray | None, b: np.ndarray | None) -> float:
        if a is None or b is None or a.shape != b.shape:
            return 0.0
        value = float(np.dot(a, b) / max(1e-12, np.linalg.norm(a) * np.linalg.norm(b)))
        return float(np.clip((value + 1.0) / 2.0, 0.0, 1.0))

    def _match_score(self, track: Track, candidate: PoseCandidate) -> float:
        iou = self._iou(track.predicted_bbox(), candidate.bbox)
        center = self._center_similarity(track, candidate)
        scale = self._scale_similarity(track, candidate)
        pose = self._pose_similarity(track.landmarks, candidate.landmarks)
        appearance = self._appearance_similarity(track.appearance, candidate.appearance)
        total = (
            self.w_iou * iou
            + self.w_center * center
            + self.w_scale * scale
            + self.w_pose * pose
            + self.w_appearance * appearance
        )
        return float(np.clip(total, 0.0, 1.0))

    def _create_track(self, candidate: PoseCandidate) -> Track:
        track = Track(
            track_id=self.next_track_id,
            bbox=candidate.bbox,
            landmarks=candidate.landmarks.copy(),
            pose_quality=candidate.pose_quality,
            appearance=candidate.appearance.copy() if candidate.appearance is not None else None,
            last_frame=self.frame_index,
        )
        self.next_track_id += 1
        return track

    def _update_track(self, track: Track, candidate: PoseCandidate, score: float) -> None:
        old_center = track.center
        old_area = track.area
        track.bbox = candidate.bbox
        track.landmarks = candidate.landmarks.copy()
        track.pose_quality = candidate.pose_quality
        track.appearance = candidate.appearance.copy() if candidate.appearance is not None else track.appearance
        track.center_velocity = candidate.center - old_center
        track.area_velocity = candidate.area - old_area
        track.last_frame = self.frame_index
        track.missed_frames = 0
        track.hits += 1
        track.age += 1
        track.last_match_score = score

    def _select_initial_target(self) -> tuple[int | None, bool]:
        candidates = [track for track in self.tracks.values() if track.missed_frames == 0]
        if not candidates:
            return None, False
        frame_center = np.array([0.5, 0.5])
        scored: list[tuple[float, Track]] = []
        max_area = max(track.area for track in candidates) or 1.0
        for track in candidates:
            centrality = float(np.exp(-np.linalg.norm(track.center - frame_center) / 0.5))
            area_score = float(np.clip(track.area / max_area, 0.0, 1.0))
            persistence = float(np.clip(track.hits / max(1, self.warmup_frames), 0.0, 1.0))
            quality = float(np.clip(track.pose_quality, 0.0, 1.0))
            score = 0.40 * persistence + 0.30 * area_score + 0.20 * centrality + 0.10 * quality
            scored.append((score, track))
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        ambiguous = len(scored) > 1 and (best_score - second_score) < self.ambiguity_margin
        if best_score < self.min_selection_score:
            return None, ambiguous
        if ambiguous and not self.allow_ambiguous_auto_selection:
            return None, True
        self.target_track_id = best.track_id
        return best.track_id, ambiguous

    def update(self, candidates: list[PoseCandidate], frame_index: int) -> TrackingDecision:
        self.frame_index = int(frame_index)
        if not self.enabled:
            raise RuntimeError("TargetTracker.update() cannot be used when tracking is disabled.")

        for track in self.tracks.values():
            track.age += 1
            track.missed_frames += 1

        available_tracks = [track for track in self.tracks.values() if track.missed_frames <= self.reacquire_max_missed_frames]
        matches: list[tuple[float, int, int]] = []
        for track in available_tracks:
            for candidate_index, candidate in enumerate(candidates):
                score = self._match_score(track, candidate)
                threshold = self.reacquire_match_score if track.track_id == self.target_track_id and track.missed_frames > 0 else self.min_match_score
                if score >= threshold:
                    matches.append((score, track.track_id, candidate_index))
        matches.sort(reverse=True)
        used_tracks: set[int] = set()
        used_candidates: set[int] = set()
        for score, track_id, candidate_index in matches:
            if track_id in used_tracks or candidate_index in used_candidates:
                continue
            track = self.tracks[track_id]
            self._update_track(track, candidates[candidate_index], score)
            used_tracks.add(track_id)
            used_candidates.add(candidate_index)

        for candidate_index, candidate in enumerate(candidates):
            if candidate_index in used_candidates:
                continue
            if len(self.tracks) >= self.max_tracks:
                break
            track = self._create_track(candidate)
            self.tracks[track.track_id] = track

        stale = [track_id for track_id, track in self.tracks.items() if track.missed_frames > self.reacquire_max_missed_frames and track_id != self.target_track_id]
        for track_id in stale:
            del self.tracks[track_id]

        if self.target_track_id is None and self.frame_index + 1 >= self.warmup_frames:
            selected, ambiguous = self._select_initial_target()
            if selected is None:
                return TrackingDecision(
                    TargetStatus.AMBIGUOUS if ambiguous else TargetStatus.SEARCHING,
                    None,
                    0.0,
                    0.0,
                    None,
                    1.0,
                    False,
                    self.target_selection_method,
                )

        if self.target_track_id is None:
            return TrackingDecision(TargetStatus.SEARCHING, None, 0.0, 0.0, None, 1.0, False, self.target_selection_method)

        target = self.tracks.get(self.target_track_id)
        if target is None:
            self.target_was_missing = True
            return TrackingDecision(TargetStatus.LOST, self.target_track_id, 0.0, 0.0, None, 1.0, False, self.target_selection_method)

        if target.missed_frames == 0:
            reacquired = self.target_was_missing
            self.target_was_missing = False
            status = TargetStatus.REACQUIRED if reacquired else TargetStatus.TRACKED
            confidence = float(np.clip(0.65 * target.last_match_score + 0.35 * target.pose_quality, 0.0, 1.0))
            return TrackingDecision(status, target.track_id, confidence, target.pose_quality, target.bbox, 0.0, reacquired, self.target_selection_method)

        self.target_was_missing = True
        if target.missed_frames <= 3:
            status = TargetStatus.PARTIALLY_OCCLUDED
        elif target.missed_frames <= self.max_missed_frames:
            status = TargetStatus.OCCLUDED
        else:
            status = TargetStatus.LOST
        occlusion_ratio = float(np.clip(target.missed_frames / max(1, self.max_missed_frames), 0.0, 1.0))
        return TrackingDecision(status, target.track_id, 0.0, 0.0, target.predicted_bbox(), occlusion_ratio, False, self.target_selection_method)

    def to_document(self) -> dict[str, Any]:
        return {
            "frame_index": self.frame_index,
            "next_track_id": self.next_track_id,
            "target_track_id": self.target_track_id,
            "target_was_missing": self.target_was_missing,
            "target_selection_method": self.target_selection_method,
            "tracks": [track.to_document() for track in self.tracks.values()],
        }

    @classmethod
    def from_document(cls, cfg: dict[str, Any], document: dict[str, Any]) -> "TargetTracker":
        tracker = cls(cfg)
        tracker.frame_index = int(document.get("frame_index", -1))
        tracker.next_track_id = int(document.get("next_track_id", 1))
        target = document.get("target_track_id")
        tracker.target_track_id = int(target) if target is not None else None
        tracker.target_was_missing = bool(document.get("target_was_missing", False))
        tracker.target_selection_method = str(document.get("target_selection_method", "auto_primary_participant"))
        tracker.tracks = {
            int(item["track_id"]): Track.from_document(item)
            for item in document.get("tracks", [])
        }
        return tracker
