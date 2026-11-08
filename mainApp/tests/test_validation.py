import pandas as pd
import pytest

from aihumo.validation import validate_frame_dataframe


def test_duplicate_columns_rejected(detail):
    columns = ["session_id", "video_id", "camera_id", "timestamp_s", "frame_id", "frame_id"]
    df = pd.DataFrame([["S1", "V1", "C1", 0.0, 0, 0]], columns=columns)
    detail(input=f"1 frame with columns {columns}", expected="Duplicate feature column error")
    with pytest.raises(ValueError, match="Duplicate feature columns detected") as error:
        validate_frame_dataframe(df)
    detail(observed=str(error.value))
