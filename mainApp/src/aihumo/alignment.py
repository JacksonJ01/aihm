"""Align processed recordings in elapsed seconds while preserving native frame IDs."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from tempfile import mkdtemp

import cv2
import numpy as np
import pyarrow.parquet as pq

from .features import (
    CROSS_MEAN_PREFIX, LEGACY_ANGLE_PREFIX, MEAN_ANGLE_PREFIX, TIME_COLUMNS,
    TORSO_ANGLE_PREFIX, WORLD_ANGLE_PREFIX, angle_family,
)
from .storage import annotation_json_for_features, load_json, save_json_atomic

SOURCE_LABELS = {
    "torso2d": "Torso-normalized 2D", "world": "Estimated world (3D)",
    "legacy": "Legacy (normalized image)", "mean": "Mean of three sources",
}
MAX_CAMERAS = 4


@dataclass(frozen=True)
class Recording:
    video: Path
    features: Path
    label: str
    times: np.ndarray
    angles: dict[tuple[str, str], np.ndarray]

    @property
    def fps(self) -> float:
        return (len(self.times) - 1) / (self.times[-1] - self.times[0])


@dataclass(frozen=True)
class TimeMap:
    """Map native source seconds to session seconds using offset and clock rate."""

    offset: float = 0.0
    rate: float = 1.0
    score: float | None = None
    needs_review: bool = False

    def __post_init__(self):
        if not np.isfinite(self.offset) or not np.isfinite(self.rate) or self.rate <= 0:
            raise ValueError("A time map requires a finite offset and a positive clock rate.")
        if self.score is not None and not -1 <= self.score <= 1:
            raise ValueError("Alignment similarity must be between −1 and 1.")

    def session_time(self, source_time):
        return self.offset + self.rate * source_time


def load_recording(features: Path, video: Path | None = None) -> Recording:
    features = Path(features).resolve(strict=True)
    stem = features.stem.removesuffix("_features")
    video = Path(video or features.parent.parent / "video" / f"{stem}_skeleton.mp4").resolve(strict=True)
    metadata_path = features.parent.parent / "metadata" / f"{stem}_metadata.json"
    metadata = load_json(metadata_path) if metadata_path.is_file() else {}
    with pq.ParquetFile(features) as parquet:
        columns = parquet.schema_arrow.names
        time_column = next((name for name in TIME_COLUMNS if name in columns), None)
        if time_column is None or "frame_id" not in columns:
            raise ValueError(f"{features.name} needs frame IDs and source timestamps.")
        mapping = {
            (source, joint): column
            for source, prefix in (("torso2d", TORSO_ANGLE_PREFIX), ("world", WORLD_ANGLE_PREFIX),
                                   ("legacy", LEGACY_ANGLE_PREFIX))
            for joint, column in angle_family(columns, prefix).items()
        }
        for prefix in (MEAN_ANGLE_PREFIX, CROSS_MEAN_PREFIX):
            mapping.update({
                ("mean", column.removeprefix(f"{prefix}angle_")): column for column in columns
                if column.startswith(f"{prefix}angle_") and not column.endswith("_source_count")
            })
        table = parquet.read(columns=list(dict.fromkeys(["frame_id", time_column, *mapping.values()])))
    times = np.asarray(table[time_column].to_numpy(), dtype=float)
    ids = table["frame_id"].to_numpy()
    if (len(times) < 2 or not np.array_equal(ids, np.arange(len(times))) or not np.isfinite(times).all()
            or np.any(np.diff(times) < 0) or times[-1] <= times[0]):
        raise ValueError(f"{features.name} needs ordered native frames and increasing source time.")
    label = " · ".join(filter(None, (stem, metadata.get("camera_angle") or metadata.get("camera_id"))))
    return Recording(
        video, features, label, times,
        {key: np.asarray(table[col].to_numpy(), dtype=float) for key, col in mapping.items()},
    )


def validate_video(recording: Recording) -> tuple[int, int]:
    capture = cv2.VideoCapture(str(recording.video))
    try:
        size = tuple(int(capture.get(prop)) for prop in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT))
        if (not capture.isOpened() or min(size) <= 0
                or int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) != len(recording.times)):
            raise ValueError(f"{recording.video.name} must have one frame per row in its features Parquet.")
        return size
    finally:
        capture.release()


def shortest_duration(recording: Recording) -> float:
    return float(recording.times[-1] - recording.times[0])


def _path_identity(path: Path):
    resolved = path.resolve()
    try:
        stat = resolved.stat()
    except FileNotFoundError:
        return resolved
    return (stat.st_dev, stat.st_ino) if stat.st_ino else resolved


def _validate_recording_files(videos: list[Path], features: list[Path]) -> set[Path | tuple[int, int]]:
    annotations = [annotation_json_for_features(path.resolve()) for path in features]
    seen = set()
    for label, paths in (("feature Parquet", features), ("video", videos), ("annotation file", annotations),
                         ("annotation Parquet", [path.with_suffix(".parquet") for path in annotations])):
        identities = {_path_identity(path) for path in paths}
        if len(identities) != len(paths):
            raise ValueError(f"Each camera needs a distinct {label}.")
        if seen & identities:
            raise ValueError("Videos, feature Parquets, and annotation files must have separate paths.")
        seen.update(identities)
    return seen


def process_session(feature_paths: list[Path]):
    validate_camera_count(len(feature_paths))
    recordings = [load_recording(path) for path in feature_paths]
    _validate_recording_files([recording.video for recording in recordings], [recording.features for recording in recordings])
    for recording in recordings:
        validate_video(recording)
    reference = min(recordings, key=shortest_duration)
    maps = [TimeMap() if recording is reference else align_recording(reference, recording) for recording in recordings]
    try:
        start, end = common_window(recordings, maps)
    except ValueError:
        # Leave the candidate maps available for manual correction.
        start = end = None
    return recordings, maps, start, end


def validate_camera_count(count: int) -> None:
    if not 2 <= count <= MAX_CAMERAS:
        raise ValueError(f"Choose between 2 and {MAX_CAMERAS} camera recordings.")


def common_window(recordings, maps) -> tuple[float, float]:
    validate_camera_count(len(recordings))
    if len(recordings) != len(maps):
        raise ValueError("Each camera requires a time map.")
    start = max(mapping.session_time(recording.times[0]) for recording, mapping in zip(recordings, maps))
    end = min(mapping.session_time(recording.times[-1]) for recording, mapping in zip(recordings, maps))
    if end <= start:
        raise ValueError("The recordings have no shared time window at these offsets.")
    return float(start), float(end)


def trim_frames(recording: Recording, mapping: TimeMap, start: float, end: float) -> tuple[int, int]:
    """Inclusive native frame range inside the common window."""
    low = (start - mapping.offset) / mapping.rate
    high = (end - mapping.offset) / mapping.rate
    first = int(recording.times.searchsorted(low - 1e-8, side="left"))
    last = int(recording.times.searchsorted(high + 1e-8, side="right")) - 1
    if first > last:
        raise ValueError(f"The selected window contains no frame from {recording.label}.")
    return first, last


def frame_at(recording: Recording, mapping: TimeMap, time: float, first: int, last: int) -> int:
    source = (time - mapping.offset) / mapping.rate
    index = min(last, max(first, int(recording.times.searchsorted(source))))
    previous = max(first, index - 1)
    return previous if abs(source - recording.times[previous]) <= abs(source - recording.times[index]) else index


def _resample(recording: Recording, keys, hz: float) -> np.ndarray:
    t = recording.times - recording.times[0]
    grid = np.arange(int(t[-1] * hz) + 1) / hz
    right = t.searchsorted(grid, side="right").clip(1, len(t) - 1)
    left = right - 1
    good_time = (t[right] - t[left]) <= max(0.25, 3 / recording.fps)
    result = np.full((len(grid), len(keys)), np.nan)
    for i, key in enumerate(keys):
        values = recording.angles[key]
        interpolated = np.interp(grid, t, values)
        valid = good_time & np.isfinite(interpolated)
        if valid.sum() < max(8, len(grid) * 0.15):
            continue
        low, high = np.percentile(interpolated[valid], [10, 90])
        if high - low < 3:
            continue
        scaled = np.clip((interpolated - (low + high) / 2) / (high - low), -3, 3)
        # Smooth a few samples while retaining gaps and the original motion time.
        smoothed = np.convolve(np.where(valid, scaled, 0), np.ones(5), mode="same")
        count = np.convolve(valid.astype(float), np.ones(5), mode="same")
        result[valid, i] = smoothed[valid] / count[valid]
    return result


def _lag_scores(reference: np.ndarray, candidate: np.ndarray, min_overlap: int) -> tuple[np.ndarray, np.ndarray]:
    """Per-channel Pearson correlation for each lag using only overlapping valid samples."""
    n, m = len(reference), len(candidate)
    nfft = 1 << (n + m - 2).bit_length()
    lags = np.arange(1 - m, n)
    total = np.zeros(len(lags))
    weight = np.zeros(len(lags))
    for start in range(0, reference.shape[1], 8):
        a, b = reference[:, start:start + 8], candidate[:, start:start + 8]
        am, bm = np.isfinite(a), np.isfinite(b)
        a, b = np.where(am, a, 0), np.where(bm, b, 0)
        af, ax, a2 = (np.fft.rfft(values, nfft, axis=0) for values in (am, a, a * a))
        bf, bx, b2 = (np.fft.rfft(values, nfft, axis=0).conj() for values in (bm, b, b * b))

        def corr(x, y):
            values = np.fft.irfft(x * y, nfft, axis=0)
            return np.concatenate((values[-(m - 1):], values[:n]))

        count = np.rint(corr(af, bf)).clip(0)
        denominator = count.clip(1)
        xs, ys = corr(ax, bf), corr(af, bx)
        covariance = corr(ax, bx) - xs * ys / denominator
        xv = corr(a2, bf) - xs * xs / denominator
        yv = corr(af, b2) - ys * ys / denominator
        valid = (count >= max(5, min_overlap * 0.35)) & (xv > 0.01) & (yv > 0.01)
        r = np.divide(covariance, np.sqrt(xv.clip(0) * yv.clip(0)),
                      out=np.zeros_like(covariance), where=valid)
        total += (r.clip(-1, 1) * valid * count).sum(axis=1)
        weight += (valid * count).sum(axis=1)
    overlap = np.minimum(n, lags + m) - np.maximum(0, lags)
    scores = np.divide(total, weight, out=np.full(len(lags), -np.inf),
                       where=(weight > 0) & (overlap >= min_overlap))
    return lags, scores


def _refine_clock(reference: np.ndarray, candidate: np.ndarray, lag: int, hz: float) -> tuple[float, float]:
    """Fit a small linear clock correction when distinct windows support it."""
    start, end = max(0, -lag), min(len(candidate), len(reference) - lag)
    if end - start < 30 * hz:
        return float(lag), 1.0
    width = min(int(45 * hz), (end - start) // 6)
    radius = int(2.0 * hz)
    observations = []
    for center in np.linspace(start + width, end - width, 7).astype(int):
        first, last = center - width // 2, center + width // 2
        left = max(0, first + lag - radius)
        right = min(len(reference), last + lag + radius)
        offsets, scores = _lag_scores(reference[left:right], candidate[first:last], last - first - 1)
        index = int(np.argmax(scores))
        if not np.isfinite(scores[index]) or scores[index] < 0.30 or index in (0, len(scores) - 1):
            continue
        other = scores[np.abs(offsets - offsets[index]) >= max(2, int(hz * 0.65))]
        if len(other) and scores[index] - other.max() < 0.025:
            continue
        observations.append((center, left - first + offsets[index]))
    if len(observations) < 4:
        return float(lag), 1.0
    slope = float(np.median([(b[1] - a[1]) / (b[0] - a[0]) for a, b in combinations(observations, 2)]))
    intercept = float(np.median([y - slope * x for x, y in observations]))
    errors = [abs(y - (intercept + slope * x)) for x, y in observations]
    if abs(slope) > 0.02 or np.median(errors) > hz * 0.12:
        return float(lag), 1.0
    return intercept, 1.0 + slope


def align_recording(reference: Recording, candidate: Recording) -> TimeMap:
    keys = sorted(reference.angles.keys() & candidate.angles.keys())
    if not keys:
        return TimeMap(needs_review=True)
    hz = min(15.0, reference.fps, candidate.fps)
    if min(reference.times[-1] - reference.times[0], candidate.times[-1] - candidate.times[0]) * hz < 10:
        return TimeMap(needs_review=True)
    a, b = _resample(reference, keys, hz), _resample(candidate, keys, hz)
    lags, scores = _lag_scores(a, b, max(8, int(min(len(a), len(b)) * 0.60)))
    index = int(np.argmax(scores))
    score = float(scores[index])
    if not np.isfinite(score):
        return TimeMap(needs_review=True)
    lag = int(lags[index])
    alternatives = scores[np.abs(lags - lag) >= max(2, int(1.25 * hz))]
    ambiguous = bool(score < 0.32 or (len(alternatives) and score - alternatives.max() < 0.04))
    intercept, rate = (float(lag), 1.0) if ambiguous else _refine_clock(a, b, lag, hz)
    offset = reference.times[0] + intercept / hz - rate * candidate.times[0]
    return TimeMap(float(offset), rate, score, ambiguous)


def save_session(path: Path, recordings, maps, start: float, end: float) -> None:
    low, high = common_window(recordings, maps)
    if not low <= start < end <= high:
        raise ValueError("Trim times must be within the shared window.")
    videos = [recording.video for recording in recordings]
    features = [recording.features for recording in recordings]
    if _path_identity(path) in _validate_recording_files(videos, features):
        raise ValueError("Choose a separate alignment file to preserve the camera recordings and annotations.")
    cameras = []
    for recording, mapping in zip(recordings, maps):
        first, last = trim_frames(recording, mapping, start, end)
        cameras.append({
            "video": str(recording.video), "features": str(recording.features), "frameCount": len(recording.times),
            "offsetSeconds": mapping.offset, "clockRate": mapping.rate, "similarity": mapping.score,
            "needsReview": mapping.needs_review, "firstFrame": first, "lastFrame": last,
        })
    save_json_atomic({"version": 1, "startSeconds": start, "endSeconds": end, "cameras": cameras}, path)


def load_session(path: Path) -> tuple[list[Recording], list[TimeMap], float, float]:
    document = load_json(path)
    if document.get("version") != 1 or not isinstance(document.get("cameras"), list):
        raise ValueError("Choose a version 1 AIHuMo alignment session.")
    validate_camera_count(len(document["cameras"]))
    files = _validate_recording_files([Path(camera["video"]) for camera in document["cameras"]],
                                      [Path(camera["features"]) for camera in document["cameras"]])
    if _path_identity(path) in files:
        raise ValueError("Choose an alignment file stored separately from the camera recordings and annotations.")
    recordings, maps = [], []
    for camera in document["cameras"]:
        recording = load_recording(camera["features"], camera["video"])
        validate_video(recording)
        mapping = TimeMap(float(camera["offsetSeconds"]), float(camera["clockRate"]),
                          camera.get("similarity"), bool(camera.get("needsReview")))
        if camera["frameCount"] != len(recording.times):
            raise ValueError(f"The native frame count has changed for {recording.label}.")
        recordings.append(recording)
        maps.append(mapping)
    low, high = common_window(recordings, maps)
    start, end = float(document["startSeconds"]), float(document["endSeconds"])
    if not low <= start < end <= high:
        raise ValueError("The saved trim is outside the shared time window.")
    for recording, mapping, camera in zip(recordings, maps, document["cameras"]):
        if trim_frames(recording, mapping, start, end) != (camera["firstFrame"], camera["lastFrame"]):
            raise ValueError(f"The source timestamps changed for {recording.label}.")
    return recordings, maps, start, end


def export_ranges(recordings, maps, start: float, end: float) -> list[tuple[int, int]]:
    low, high = common_window(recordings, maps)
    if not low <= start < end <= high:
        raise ValueError("Choose a trim inside the shared time window.")
    ranges = [trim_frames(recording, mapping, start, end) for recording, mapping in zip(recordings, maps)]
    shortest = min(shortest_duration(recording) for recording in recordings)
    for recording, bounds in zip(recordings, ranges):
        if shortest_duration(recording) <= shortest + 1e-8 and bounds != (0, len(recording.times) - 1):
            raise ValueError("This trim cuts the shortest camera. Adjust the offsets or trim range to keep it intact.")
    return ranges


def _write_trimmed_video(recording: Recording, path: Path, first: int, last: int) -> None:
    width, height = validate_video(recording)
    capture = cv2.VideoCapture(str(recording.video))
    writer = cv2.VideoWriter()
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not np.isfinite(fps) or fps <= 0 or not writer.open(
            str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height),
        ):
            raise ValueError(f"Could not start an MP4 export for {recording.video.name}.")
        if first and not capture.set(cv2.CAP_PROP_POS_FRAMES, first):
            raise ValueError(f"Could not seek to frame {first} in {recording.video.name}.")
        for frame_id in range(first, last + 1):
            ok, frame = capture.read()
            if not ok:
                raise ValueError(f"Could not read frame {frame_id} from {recording.video.name}.")
            writer.write(frame)
    finally:
        writer.release()
        capture.release()
    exported = cv2.VideoCapture(str(path))
    try:
        if not exported.isOpened() or int(exported.get(cv2.CAP_PROP_FRAME_COUNT)) != last - first + 1:
            raise ValueError(f"Could not verify all exported frames in {path.name}.")
    finally:
        exported.release()


def export_session(parent: Path, recordings, maps, start: float, end: float) -> Path:
    ranges = export_ranges(recordings, maps, start, end)
    output = Path(mkdtemp(prefix="aihumo-aligned-", dir=parent))
    try:
        save_session(output / "alignment.json", recordings, maps, start, end)
        clips = []
        for i, (recording, (first, last)) in enumerate(zip(recordings, ranges), 1):
            path = recording.video
            if (first, last) != (0, len(recording.times) - 1):
                path = output / f"{i:02d}-{path.stem}-trimmed.mp4"
                _write_trimmed_video(recording, path, first, last)
            clips.append({"video": str(path), "sourceFirstFrame": first, "sourceLastFrame": last})
        save_json_atomic({"clips": clips}, output / "clips.json")
    except Exception:
        for path in output.iterdir():
            path.unlink()
        output.rmdir()
        raise
    return output
