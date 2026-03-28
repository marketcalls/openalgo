from __future__ import annotations

from typing import Iterable

import pandas as pd

from data.session_filter import ensure_datetime_index


def align_higher_timeframes(
    primary_df: pd.DataFrame,
    higher_frames: Iterable[tuple[str, pd.DataFrame]],
) -> pd.DataFrame:
    aligned = ensure_datetime_index(primary_df).copy()
    aligned = aligned.sort_index().reset_index()

    for timeframe, frame in higher_frames:
        higher = ensure_datetime_index(frame).sort_index().reset_index()
        merge_cols = [column for column in higher.columns if column != "timestamp_index"]
        aligned = pd.merge_asof(
            aligned.sort_values("timestamp_index"),
            higher[["timestamp_index", *merge_cols]].sort_values("timestamp_index"),
            on="timestamp_index",
            direction="backward",
            suffixes=("", f"_{timeframe}"),
        )

    return aligned.set_index("timestamp_index")
