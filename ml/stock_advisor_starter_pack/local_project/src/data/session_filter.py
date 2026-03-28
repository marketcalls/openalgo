from __future__ import annotations

import pandas as pd

from core.constants import INDIA_TIMEZONE, INTRADAY_SESSION_END, INTRADAY_SESSION_START


def ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    if isinstance(working.index, pd.DatetimeIndex):
        idx = working.index
    elif "datetime" in working.columns:
        idx = pd.to_datetime(working["datetime"], utc=True)
    elif "timestamp" in working.columns:
        idx = pd.to_datetime(working["timestamp"], unit="s", utc=True)
    else:
        raise ValueError("DataFrame needs a DatetimeIndex or datetime/timestamp column.")

    working.index = idx
    working.index.name = "timestamp_index"
    return working.sort_index()


def filter_indian_market_hours(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if timeframe.lower() in {"1day", "1d", "1month", "1mo", "1mth", "1week", "1w"}:
        return ensure_datetime_index(df)

    working = ensure_datetime_index(df)
    local_index = working.index.tz_convert(INDIA_TIMEZONE)
    mask = (local_index.strftime("%H:%M") >= INTRADAY_SESSION_START) & (
        local_index.strftime("%H:%M") <= INTRADAY_SESSION_END
    )
    return working.loc[mask].copy()
