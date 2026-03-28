import pandas as pd

from features.feature_schema import align_feature_frame, infer_feature_columns


def test_feature_schema_alignment_adds_missing_columns():
    frame = pd.DataFrame({"a": [1], "b": [2]})
    features = infer_feature_columns(frame)
    aligned = align_feature_frame(pd.DataFrame({"a": [3]}), features)
    assert list(aligned.columns) == features
    assert aligned.loc[0, "b"] == 0.0
