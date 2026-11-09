from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def save_parquet(df: pd.DataFrame, path: str | Path) -> Path:
    """Compatibility wrapper for the single Arrow-backed Parquet writer."""
    return save_parquet_atomic(df, path)


def save_parquet_atomic(df: pd.DataFrame, path: str | Path, *, metadata: dict[bytes, bytes] | None = None) -> Path:
    """Write a complete Parquet file and replace the destination atomically."""
    if df.columns.duplicated().any():
        raise ValueError(
            "Refusing to save Parquet with duplicate columns: "
            f"{df.columns[df.columns.duplicated()].tolist()}"
        )

    table = pa.Table.from_pandas(df, preserve_index=False).replace_schema_metadata({
        b"aihumo.storage": b"pyarrow",
        b"aihumo.index": b"false",
        **(metadata or {}),
    })
    return save_arrow_parquet_atomic(table, path)


def save_arrow_parquet_atomic(table: pa.Table | pa.RecordBatchReader, path: str | Path, *,
                              verify: bool = False, expected_rows: int | None = None) -> Path:
    """Replace the destination with a complete Arrow table, preserving its schema."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        if isinstance(table, pa.RecordBatchReader):
            with pq.ParquetWriter(temp_path, table.schema, compression="snappy") as writer:
                for batch in table:
                    writer.write_batch(batch)
        else:
            pq.write_table(table, temp_path, compression="snappy")
            expected_rows = table.num_rows
        if verify:
            with pq.ParquetFile(temp_path) as written:
                if written.metadata.num_rows != expected_rows or not written.schema_arrow.equals(table.schema, check_metadata=True):
                    raise ValueError("The prepared Parquet failed its row-count or schema check.")
        with temp_path.open("rb") as handle:
            try:
                os.fsync(handle.fileno())
            except OSError:
                # Some Windows/PyArrow combinations expose the completed
                # temporary file with a non-syncable descriptor. The atomic
                # replace remains the durability boundary in that case.
                pass
        os.replace(temp_path, path)
        return path
    finally:
        temp_path.unlink(missing_ok=True)


def load_parquet(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Parquet file does not exist: {path}")
    return pd.read_parquet(path)


def annotation_json_for_features(features: Path) -> Path:
    name = features.stem.replace("_features", "_annotations") + ".json"
    return features.parent.parent / "annotations" / name


def feature_parquet_candidates(directory: str | Path, video_id: str) -> list[Path]:
    """Return feature artifacts for one video, excluding raw/annotation data."""
    directory = Path(directory)
    patterns = (f"{video_id}_features*.parquet", f"{video_id}_feature*.parquet")
    candidates = {path for pattern in patterns for path in directory.glob(pattern)}
    return sorted(candidates)


def assert_single_canonical_feature_parquet(directory: str | Path, video_id: str, canonical: str | Path) -> None:
    """Prevent legacy scripts from silently leaving duplicate feature files."""
    canonical = Path(canonical).resolve()
    duplicates = [path for path in feature_parquet_candidates(directory, video_id) if path.resolve() != canonical]
    if duplicates:
        names = ", ".join(str(path) for path in duplicates)
        raise FileExistsError(
            f"Duplicate feature Parquet artifacts found for {video_id}: {names}. "
            "Remove or archive them before processing; AIHuMo will not choose one silently."
        )


def save_json(data: dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return path


def save_json_atomic(data: dict[str, Any], path: str | Path) -> Path:
    """Serialize JSON completely before atomically replacing the destination."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)

    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        return path
    finally:
        temp_path.unlink(missing_ok=True)


def load_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"JSON file does not exist: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
