from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.constants import CANONICAL_COLUMNS, INDIA_TIMEZONE
from data.excel_to_parquet import read_tabular_file, write_columnar
from data.quality_audit import audit_market_data
from data.session_filter import filter_indian_market_hours


def normalize_market_data(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> pd.DataFrame:
    working = df.copy()
    if "timestamp" not in working.columns:
        if "datetime" not in working.columns:
            raise ValueError("Input market data must contain timestamp or datetime.")
        working["timestamp"] = (
            pd.to_datetime(working["datetime"], utc=True).astype("int64") // 10**9
        )

    if "datetime" not in working.columns:
        working["datetime"] = pd.to_datetime(working["timestamp"], unit="s", utc=True)

    working["datetime"] = pd.to_datetime(working["datetime"], utc=True)
    working["symbol"] = symbol
    working["timeframe"] = timeframe
    working = working[[column for column in CANONICAL_COLUMNS if column in working.columns]].copy()
    working["datetime"] = working["datetime"].dt.tz_convert(INDIA_TIMEZONE).dt.strftime(
        "%Y-%m-%dT%H:%M:%S%z"
    )
    filtered = filter_indian_market_hours(working, timeframe)
    filtered = filtered.reset_index(drop=True)
    return filtered


def prepare_file(
    input_path: str | Path,
    output_root: str | Path,
    symbol: str,
    timeframe: str,
) -> dict[str, object]:
    raw = read_tabular_file(input_path)
    prepared = normalize_market_data(raw, symbol=symbol, timeframe=timeframe)
    report = audit_market_data(prepared)
    destination = Path(output_root) / symbol / f"{timeframe}.parquet"
    saved = write_columnar(prepared, destination)
    return {
        "saved_path": str(saved),
        "audit": report.to_dict(),
        "rows": len(prepared),
    }


if __name__ == "__main__":
    example_input = Path(r"D:\TV_proj\output\reliance_timeframes\RELIANCE_15m_5029bars.csv")
    example_output = Path(__file__).resolve().parents[2] / "examples" / "prepared_output"
    print(prepare_file(example_input, example_output, symbol="RELIANCE", timeframe="15m"))
