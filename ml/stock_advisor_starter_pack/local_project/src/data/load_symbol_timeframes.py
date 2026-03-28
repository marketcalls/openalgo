from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from core.constants import INDIA_TIMEZONE
from data.session_filter import filter_indian_market_hours

_FILENAME_PATTERN = re.compile(r"(?P<symbol>[A-Z0-9_]+)_(?P<timeframe>[^_]+)_(?P<bars>\d+)bars\.csv$", re.IGNORECASE)


@dataclass(slots=True)
class TimeframeDataset:
    symbol: str
    timeframe: str
    path: Path
    frame: pd.DataFrame


def discover_timeframe_csvs(root: str | Path, symbol: str) -> dict[str, Path]:
    root_path = Path(root)
    discovered: dict[str, Path] = {}
    for path in sorted(root_path.glob(f"{symbol.upper()}_*bars.csv")):
        match = _FILENAME_PATTERN.match(path.name)
        if not match:
            continue
        timeframe = match.group("timeframe")
        discovered[timeframe] = path
    return discovered


def load_timeframe_csv(path: str | Path, symbol: str, timeframe: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["symbol"] = symbol
    frame["timeframe"] = timeframe
    if "datetime" in frame.columns:
        frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True).dt.tz_convert(INDIA_TIMEZONE)
    filtered = filter_indian_market_hours(frame, timeframe).reset_index(drop=True)
    if "datetime" in filtered.columns:
        filtered["datetime"] = pd.to_datetime(filtered["datetime"], utc=True)
    if "timestamp" in filtered.columns:
        filtered["timestamp"] = filtered["timestamp"].astype(int)
    return filtered


def load_symbol_timeframes(root: str | Path, symbol: str) -> dict[str, TimeframeDataset]:
    datasets: dict[str, TimeframeDataset] = {}
    for timeframe, path in discover_timeframe_csvs(root, symbol).items():
        frame = load_timeframe_csv(path, symbol=symbol, timeframe=timeframe)
        datasets[timeframe] = TimeframeDataset(symbol=symbol, timeframe=timeframe, path=path, frame=frame)
    return datasets
