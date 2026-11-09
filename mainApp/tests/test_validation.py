import pandas as pd
import pytest

from aihumo.validation import validate_artifacts, validate_frame_dataframe
from tests.test_features import make_frame_data


def test_duplicate_columns_rejected(detail):
    columns = ["session_id", "video_id", "camera_id", "timestamp_s", "frame_id", "frame_id"]
    df = pd.DataFrame([["S1", "V1", "C1", 0.0, 0, 0]], columns=columns)
    detail(input=f"1 frame with columns {columns}", expected="Duplicate feature column error")
    with pytest.raises(ValueError, match="Duplicate feature columns detected") as error:
        validate_frame_dataframe(df)
    detail(observed=str(error.value))


@pytest.mark.parametrize(("column", "values", "error"), [
    ("frame_id", [0, 1.5, 2], "contiguous integers"),
    ("timestamp_s", [0, 0.04, float("inf")], "finite"),
    ("timestamp_s", [0, 0.04, 0.04], "strictly increasing"),
    ("delta_time_s", [None, 0.02, 0.02], "match elapsed"),
    ("source_frame_index", [0, 2.5, 3], "nonnegative integers"),
    ("camera_id", ["C1", "C2", "C2"], "identify one recording"),
])
def test_frame_validation_rejects_corrupt_timing_and_identity(column, values, error, detail):
    frames = make_frame_data(3)
    frames[column] = values
    detail(input=f"{column} = {values}", expected=error)
    with pytest.raises(ValueError, match=error) as failure:
        validate_frame_dataframe(frames)
    detail(observed=str(failure.value))


@pytest.mark.parametrize("column", ["timestamp_s", "camera_id", "source_frame_index"])
def test_valid_artifacts_cannot_disagree_on_frame_mapping(tmp_path, column, detail):
    raw = make_frame_data(3)
    raw["source_frame_index"] = [0, 1, 2]
    features = raw.copy()
    features[column] = {
        "timestamp_s": [0.0, 0.043, 0.081],
        "camera_id": ["C2"] * 3,
        "source_frame_index": [1, 2, 3],
    }[column]
    landmarks_path, features_path = tmp_path / "raw.parquet", tmp_path / "features.parquet"
    raw.to_parquet(landmarks_path)
    features.to_parquet(features_path)
    source, skeleton, metadata, manifest = (tmp_path / name for name in (
        "source.mp4", "skeleton.mp4", "metadata.json", "manifest.json",
    ))
    for path in (source, skeleton, metadata, manifest):
        path.write_bytes(b"must reject mismatched features before decoding")
    with pytest.raises(ValueError, match=f"disagree on {column}") as failure:
        validate_artifacts(source_video=source, processed_video=skeleton, landmarks_path=landmarks_path,
                           features_path=features_path, metadata_path=metadata, manifest_path=manifest)
    detail(input=f"Both Parquet files have three valid rows, with different {column}.", observed=str(failure.value))
