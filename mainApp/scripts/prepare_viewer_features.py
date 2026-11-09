"""Add playback features to an existing recording using its saved landmarks."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import sys

import cv2
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from aihumo.config import load_config
from aihumo.features import FeatureEngine, LEGACY_ANGLE_PREFIX, REVIEW_PREFIX, TIME_COLUMNS, review_schema_metadata
from aihumo.storage import load_json, save_arrow_parquet_atomic


def prepare_viewer_features(path: Path, video: Path, config: dict, *, distance_only: bool = False) -> tuple[int, Path | None]:
    path = path.resolve(strict=True)
    if not path.name.endswith("_features.parquet"):
        raise ValueError("Choose the recording's existing *_features.parquet file.")
    if not video.is_file():
        raise FileNotFoundError(video)
    original = path.stat()
    with pq.ParquetFile(path) as recording:
        schema = recording.schema_arrow
        row_count = recording.metadata.num_rows
    time_column = next((name for name in TIME_COLUMNS if name in schema.names), None)
    if row_count == 0 or time_column is None or "frame_id" not in schema.names:
        raise ValueError("The feature Parquet must contain native frames and source timestamps.")
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened() or int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) != row_count:
            raise ValueError("Choose a skeleton video that matches the feature file's frame count.")
        frame_size = (capture.get(cv2.CAP_PROP_FRAME_WIDTH), capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not np.isfinite(frame_size).all() or min(frame_size) <= 0:
            raise ValueError("Could not read the skeleton video's dimensions.")
    finally:
        capture.release()
    metadata_name = path.stem.removesuffix("_features") + "_metadata.json"
    sidecars = (path.parent.parent / "metadata" / metadata_name, path.with_name(metadata_name))
    metadata = next((load_json(sidecar) for sidecar in sidecars if sidecar.is_file()), {})
    expected = metadata.get("resolution", {})
    if expected and frame_size != (expected.get("width"), expected.get("height")):
        raise ValueError("The video dimensions differ from the recording metadata.")
    registered_videos = {Path(metadata[field]).name for field in ("processed_video", "source_video") if metadata.get(field)}
    if registered_videos and video.name not in registered_videos:
        raise ValueError("The selected video is not registered for this recording.")

    columns = [name for name in schema.names if name in ("frame_id", time_column, "target_track_id")
               or (name.startswith(REVIEW_PREFIX) and (not distance_only or re.fullmatch(
                   r"review_(?:legacy|world|torso2d|cross_mean)_(?:lm\d+_[xyz]|distance_.+)", name)))
               or (not distance_only and (name.startswith(LEGACY_ANGLE_PREFIX)
                                          or re.fullmatch(r"(?:lm|world)\d+_[xyz]", name)))]
    base = pq.read_table(path, columns=columns).to_pandas()
    if not np.array_equal(base["frame_id"], np.arange(len(base))):
        raise ValueError("Expected one ordered feature row per video frame.")
    times = base[time_column].to_numpy(dtype=float)
    if not np.isfinite(times).all() or np.any(np.diff(times) < 0):
        raise ValueError("Source timestamps must be finite and ordered.")
    engine = FeatureEngine(config)
    prepared = (engine.prepare_review_distances(base) if distance_only
                else engine.prepare_review_features(base, frame_size))
    new_columns = prepared.columns.difference(schema.names, sort=False)
    if not len(new_columns):
        return 0, None
    additions = [pa.array(prepared[name], from_pandas=True) for name in new_columns]
    updated_schema = pa.schema([*schema, *(pa.field(name, array.type) for name, array in zip(new_columns, additions))])
    updated_schema = updated_schema.with_metadata({**(schema.metadata or {}), **review_schema_metadata(updated_schema.names)})

    backup = path.with_suffix(".parquet.before-review-preparation.bak")
    revision = 1
    while backup.exists():
        backup = path.with_suffix(f".parquet.before-review-preparation-{revision}.bak")
        revision += 1
    def check_unchanged():
        current = path.stat()
        if (current.st_size, current.st_mtime_ns) != (original.st_size, original.st_mtime_ns):
            raise RuntimeError("The feature file changed during preparation. Try again after the recording is idle.")

    check_unchanged()
    with backup.open("xb") as target:
        try:
            with path.open("rb") as source:
                shutil.copyfileobj(source, target)
        except BaseException:
            target.close()
            backup.unlink(missing_ok=True)
            raise
    try:
        def batches():
            offset = 0
            with pq.ParquetFile(backup) as source:
                for batch in source.iter_batches(batch_size=8192):
                    new_values = [array.slice(offset, batch.num_rows) for array in additions]
                    yield pa.RecordBatch.from_arrays([*batch.columns, *new_values], schema=updated_schema)
                    offset += batch.num_rows
            check_unchanged()

        reader = pa.RecordBatchReader.from_batches(updated_schema, batches())
        save_arrow_parquet_atomic(reader, path, verify=True, expected_rows=row_count)
    except Exception:
        backup.unlink(missing_ok=True)
        raise
    return len(new_columns), backup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument("--video", required=True, type=Path, help="Matching processed skeleton MP4")
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1] / "configs" / "config.json")
    parser.add_argument("--distance-only", action="store_true", help="Backfill distance, rate, and acceleration from saved features.")
    args = parser.parse_args()
    count, backup = prepare_viewer_features(args.features, args.video, load_config(args.config), distance_only=args.distance_only)
    print(f"Added {count} columns." if count else "Playback features are already present.")
    if backup is not None:
        print(f"Original file backed up at {backup}")


if __name__ == "__main__":
    main()
