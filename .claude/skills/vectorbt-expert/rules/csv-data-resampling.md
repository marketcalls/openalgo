---
name: csv-data-resampling
description: Loading CSV market data and resampling to different timeframes
metadata:
  tags: csv, data, resample, timeframe, ohlcv, minute, daily, hourly
---

# CSV Data Loading & Resampling

## Load Minute-Level CSV Data

```python
import pandas as pd
from pathlib import Path

csv_file = Path("data") / "NIFTYF.csv"
df = pd.read_csv(
    csv_file,
    usecols=["Ticker", "Date", "Time", "Open", "High", "Low", "Close", "Volume"]
)

# Build datetime index
df["datetime"] = pd.to_datetime(df["Date"] + " " + df["Time"])
df = df.set_index("datetime").sort_index()
df = df.drop(columns=["Date", "Time", "Ticker"])
```

## Resample to Different Timeframes

```python
def resample_df(df, tf="D"):
    if tf == "D":
        return df.resample("D").agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
        }).dropna()
    elif tf == "H":
        # 60-min bars aligned to Indian market open (09:15)
        return df.resample("60min", origin="start_day", offset="9h15min").agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
        }).dropna()
    elif tf == "5min":
        return df.resample("5min", origin="start_day", offset="9h15min",
                           label="right", closed="right").agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
        }).dropna()
    else:
        raise ValueError("Unsupported timeframe")

timeframe = "H"
df_resampled = resample_df(df, tf=timeframe)
close = df_resampled["Close"]
```

## Best Practices

- Always use `origin="start_day"` with `offset="9h15min"` for Indian market bar alignment
- Use `label="right", closed="right"` for intraday bars (a 9:15-9:20 bar is labeled 9:20)
- Apply `.dropna()` after resampling to remove empty bars (weekends, holidays)
- Verify bar count after resampling matches expected trading sessions

## Load from DuckDB and Resample

For DuckDB-stored 1-minute data (faster than CSV):

```python
import duckdb
import pandas as pd

DB_PATH = r"path/to/market_data.duckdb"

con = duckdb.connect(DB_PATH, read_only=True)
df = con.execute("""
    SELECT date, time, open, high, low, close, volume
    FROM ohlcv WHERE symbol = 'RELIANCE' ORDER BY date, time
""").fetchdf()
con.close()

# Build datetime index
df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str))
df = df.set_index("datetime").sort_index()
df = df.drop(columns=["date", "time"])

# Resample to 5-min
df_5m = df.resample("5min", origin="start_day", offset="9h15min",
                     label="right", closed="right").agg({
    "open": "first", "high": "max", "low": "min",
    "close": "last", "volume": "sum"
}).dropna()
close = df_5m["close"]
```

### OpenAlgo Historify DuckDB Format

Historify stores timestamps as Unix epoch seconds:

```python
HISTORIFY_DB = r"path/to/openalgo/db/historify.duckdb"

con = duckdb.connect(HISTORIFY_DB, read_only=True)
df = con.execute("""
    SELECT timestamp, open, high, low, close, volume
    FROM market_data
    WHERE symbol = 'RELIANCE' AND exchange = 'NSE' AND interval = '1m'
    ORDER BY timestamp
""").fetchdf()
con.close()

df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
df = df.set_index("datetime").sort_index()
df = df.drop(columns=["timestamp"])

# Resample same as above
df_5m = df.resample("5min", origin="start_day", offset="9h15min",
                     label="right", closed="right").agg({
    "open": "first", "high": "max", "low": "min",
    "close": "last", "volume": "sum"
}).dropna()
```
