import pandas as pd
import pytest

from aihumo.validation import validate_frame_dataframe


def test_duplicate_columns_rejected():
    df = pd.DataFrame([[1, 2]], columns=["frame_id", "frame_id"])
    with pytest.raises(ValueError):
        validate_frame_dataframe(df)
