---
name: duckdb-data
description: Loading market data directly from DuckDB databases for backtesting - supports both custom DuckDB and OpenAlgo Historify format
metadata:
  tags: duckdb, data, database, historify, ohlcv, backtest, direct-db
---

# DuckDB Direct Data Loading

Use this when the user has a DuckDB database with OHLCV data and wants to backtest without going through OpenAlgo API. This is the fastest way to load data for backtesting.

## Two Supported DuckDB Formats

### 1. Custom DuckDB (User-Created)

User-created databases with any schema. Common format:

```python
import duckdb
import pandas as pd

DB_PATH = r"path/to/market_data.duckdb"

con = duckdb.connect(DB_PATH, read_only=True)
df = con.execute("""
    SELECT date, time, open, high, low, close, volume
    FROM ohlcv
    WHERE symbol = 'RELIANCE'
    ORDER BY date, time
""").fetchdf()
con.close()

# Build datetime index
df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str))
df = df.set_index("datetime").sort_index()
df = df.drop(columns=["date", "time"])
```

**Always inspect the schema first** if unsure:

```python
con = duckdb.connect(DB_PATH, read_only=True)
print(con.execute("SHOW TABLES").fetchdf())
print(con.execute("DESCRIBE ohlcv").fetchdf())
print(con.execute("SELECT * FROM ohlcv LIMIT 5").fetchdf())
con.close()
```

### 2. OpenAlgo Historify DuckDB

OpenAlgo stores historical data in `db/historify.duckdb` with a specific schema.

**Schema: `market_data` table**

```sql
CREATE TABLE market_data (
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    interval VARCHAR NOT NULL,      -- '1m' or 'D' (storage intervals)
    timestamp BIGINT NOT NULL,      -- Unix epoch seconds
    open DOUBLE NOT NULL,
    high DOUBLE NOT NULL,
    low DOUBLE NOT NULL,
    close DOUBLE NOT NULL,
    volume BIGINT NOT NULL,
    oi BIGINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (symbol, exchange, interval, timestamp)
)
```

**Key differences from custom DuckDB:**
- `timestamp` is Unix epoch seconds (BIGINT), not DATE + TIME
- Has `exchange` and `interval` columns for filtering
- Storage intervals are only `1m` and `D` (other intervals are computed on-the-fly)
- Has `oi` (open interest) column

**Loading Historify data:**

```python
import duckdb
import pandas as pd

HISTORIFY_DB = r"path/to/openalgo/db/historify.duckdb"

con = duckdb.connect(HISTORIFY_DB, read_only=True)
df = con.execute("""
    SELECT timestamp, open, high, low, close, volume
    FROM market_data
    WHERE symbol = 'SBIN'
      AND exchange = 'NSE'
      AND interval = '1m'
    ORDER BY timestamp
""").fetchdf()
con.close()

# Convert epoch seconds to datetime index
df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
df = df.set_index("datetime").sort_index()
df = df.drop(columns=["timestamp"])
```

## Auto-Detection: Which Format?

When given a DuckDB path, auto-detect the format:

```python
import duckdb

def detect_duckdb_format(db_path):
    """Detect if DuckDB is OpenAlgo Historify or custom format."""
    con = duckdb.connect(db_path, read_only=True)
    tables = con.execute("SHOW TABLES").fetchdf()["name"].tolist()
    con.close()

    if "market_data" in tables:
        # Check for Historify schema
        con = duckdb.connect(db_path, read_only=True)
        cols = con.execute("DESCRIBE market_data").fetchdf()["column_name"].tolist()
        con.close()
        if all(c in cols for c in ["symbol", "exchange", "interval", "timestamp"]):
            return "historify"
    if "ohlcv" in tables:
        return "custom_ohlcv"
    return "unknown"
```

## Loading Functions

### load_from_custom_duckdb

```python
def load_from_duckdb(db_path, symbol, table="ohlcv"):
    """Load OHLCV data from a custom DuckDB database."""
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute(f"""
        SELECT date, time, open, high, low, close, volume
        FROM {table}
        WHERE symbol = ?
        ORDER BY date, time
    """, [symbol]).fetchdf()
    con.close()

    df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str))
    df = df.set_index("datetime").sort_index()
    df = df.drop(columns=["date", "time"])
    return df
```

### load_from_historify

```python
def load_from_historify(db_path, symbol, exchange="NSE", interval="1m"):
    """Load OHLCV data from OpenAlgo Historify DuckDB."""
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute("""
        SELECT timestamp, open, high, low, close, volume
        FROM market_data
        WHERE symbol = ? AND exchange = ? AND interval = ?
        ORDER BY timestamp
    """, [symbol.upper(), exchange.upper(), interval]).fetchdf()
    con.close()

    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
    df = df.set_index("datetime").sort_index()
    df = df.drop(columns=["timestamp"])
    return df
```

## Resampling DuckDB Data

After loading 1-min data from either format, resample to target timeframe:

```python
def resample_ohlcv(df, timeframe="5min"):
    """Resample OHLCV data with Indian market alignment (09:15 open)."""
    return df.resample(
        timeframe, origin="start_day", offset="9h15min",
        label="right", closed="right"
    ).agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).dropna()
```

## Multi-Symbol Loading (Portfolio)

```python
def load_multi_symbol(db_path, symbols, table="ohlcv"):
    """Load multiple symbols and return wide-format close prices."""
    con = duckdb.connect(db_path, read_only=True)
    close_dict = {}
    for sym in symbols:
        df = con.execute(f"""
            SELECT date, time, close
            FROM {table}
            WHERE symbol = ?
            ORDER BY date, time
        """, [sym]).fetchdf()
        df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str))
        df = df.set_index("datetime").sort_index()
        close_dict[sym] = df["close"]
    con.close()
    return pd.DataFrame(close_dict)
```

## DuckDB Pivot for Wide Format (Memory Efficient)

Let DuckDB do the pivot on disk instead of pandas:

```python
con = duckdb.connect(db_path, read_only=True)
df_wide = con.execute("""
    PIVOT (
        SELECT date || ' ' || time AS dt, symbol, close
        FROM ohlcv
        WHERE symbol IN ('RELIANCE', 'SBIN', 'INFY', 'TCS')
    ) ON symbol USING first(close)
    ORDER BY dt
""").fetchdf()
con.close()

df_wide["datetime"] = pd.to_datetime(df_wide["dt"])
df_wide = df_wide.set_index("datetime").drop(columns=["dt"])
```

## Indicators and Signal Utilities Without openalgo.ta

Indicators default to `openalgo.ta` project-wide (see [indicators-signals](./indicators-signals.md)). If the standalone DuckDB environment does not have the `openalgo` package installed at all, fall back to TA-Lib for indicators instead - this is the one case where TA-Lib is used without the user explicitly requesting it, since there is no other indicator source available:

```python
try:
    from openalgo import ta
    ema = ta.ema
    exrem = ta.exrem
except ImportError:
    import talib as tl

    def ema(data, period):
        return pd.Series(tl.EMA(data.values, timeperiod=period), index=data.index)

    def exrem(signal1, signal2):
        result = signal1.copy()
        active = False
        for i in range(len(signal1)):
            if active:
                result.iloc[i] = False
            if signal1.iloc[i] and not active:
                active = True
            if signal2.iloc[i]:
                active = False
        return result
```

When using standalone DuckDB (without OpenAlgo installed) and only the signal helper is needed, implement it inline:

```python
def exrem(signal1, signal2):
    """Keep only the first signal1=True before a signal2=True (replaces ta.exrem)."""
    result = signal1.copy()
    active = False
    for i in range(len(signal1)):
        if active:
            result.iloc[i] = False
        if signal1.iloc[i] and not active:
            active = True
        if signal2.iloc[i]:
            active = False
    return result
```

Or try importing openalgo.ta with a fallback:

```python
try:
    from openalgo import ta
    exrem = ta.exrem
except ImportError:
    def exrem(signal1, signal2):
        result = signal1.copy()
        active = False
        for i in range(len(signal1)):
            if active:
                result.iloc[i] = False
            if signal1.iloc[i] and not active:
                active = True
            if signal2.iloc[i]:
                active = False
        return result
```

## Best Practices

- Always use `read_only=True` when loading data for backtesting (prevents accidental writes)
- Always `con.close()` after loading — DuckDB uses exclusive file locks on Windows
- For Historify, filter by `exchange` AND `interval` — the table has all exchanges and intervals mixed
- Historify stores only `1m` and `D` intervals physically — resample for other timeframes
- For large datasets (500+ symbols), use DuckDB PIVOT instead of pandas concat for memory efficiency
- Use parameterized queries (`?` placeholders) to prevent SQL injection
