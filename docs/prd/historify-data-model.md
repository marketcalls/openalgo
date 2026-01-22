# Historify Data Model

Complete documentation for DuckDB schema and data model used in Historify.

## Overview

Historify uses DuckDB for efficient columnar storage of historical OHLCV data with on-the-fly timeframe aggregation.

## Why DuckDB?

| Feature | DuckDB | SQLite |
|---------|--------|--------|
| Columnar storage | Yes (OLAP optimized) | No (row-based) |
| Compression | Excellent (~10x) | Minimal |
| Analytical queries | Very fast | Slower |
| Time-series aggregation | Built-in | Manual |
| File size per 1M candles | ~50MB | ~500MB |

## Database Location

```
openalgo/
└── db/
    └── historify.duckdb    # Historical data storage
```

## Schema Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         historify.duckdb                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────┐     ┌────────────────────┐                         │
│  │    market_data     │     │     watchlist      │                         │
│  │    (OHLCV data)    │     │   (tracked syms)   │                         │
│  └────────────────────┘     └────────────────────┘                         │
│                                                                              │
│  ┌────────────────────┐     ┌────────────────────┐                         │
│  │   download_jobs    │     │    job_items       │                         │
│  │   (bulk jobs)      │     │  (per-symbol)      │                         │
│  └────────────────────┘     └────────────────────┘                         │
│                                                                              │
│  ┌────────────────────┐     ┌────────────────────┐                         │
│  │  symbol_metadata   │     │   data_catalog     │                         │
│  │   (F&O info)       │     │  (date ranges)     │                         │
│  └────────────────────┘     └────────────────────┘                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Table Definitions

### market_data

Primary table for storing OHLCV candles.

```sql
CREATE TABLE market_data (
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    interval VARCHAR NOT NULL,     -- '1m', 'D'
    timestamp TIMESTAMP NOT NULL,
    open DOUBLE NOT NULL,
    high DOUBLE NOT NULL,
    low DOUBLE NOT NULL,
    close DOUBLE NOT NULL,
    volume BIGINT NOT NULL,
    oi BIGINT,                     -- Open Interest (F&O only)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (symbol, exchange, interval, timestamp)
);

-- Indexes for fast querying
CREATE INDEX idx_market_data_symbol ON market_data(symbol, exchange);
CREATE INDEX idx_market_data_timestamp ON market_data(timestamp);
CREATE INDEX idx_market_data_interval ON market_data(interval);
```

### watchlist

Tracked symbols for data management.

```sql
CREATE TABLE watchlist (
    id INTEGER PRIMARY KEY,
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    user_id VARCHAR NOT NULL,
    display_name VARCHAR,
    token VARCHAR,                  -- Broker token ID
    lot_size INTEGER DEFAULT 1,
    tick_size DOUBLE DEFAULT 0.05,
    instrument_type VARCHAR,        -- EQ, FUT, OPT, IDX
    expiry DATE,                    -- For F&O
    strike DOUBLE,                  -- For Options
    option_type VARCHAR,            -- CE, PE
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(symbol, exchange, user_id)
);
```

### download_jobs

Bulk download job tracking.

```sql
CREATE TABLE download_jobs (
    id INTEGER PRIMARY KEY,
    user_id VARCHAR NOT NULL,
    job_name VARCHAR,
    status VARCHAR DEFAULT 'pending',  -- pending, running, paused, completed, failed
    total_items INTEGER DEFAULT 0,
    completed_items INTEGER DEFAULT 0,
    failed_items INTEGER DEFAULT 0,
    start_date DATE,
    end_date DATE,
    interval VARCHAR DEFAULT '1m',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT
);
```

### job_items

Per-symbol status within a bulk job.

```sql
CREATE TABLE job_items (
    id INTEGER PRIMARY KEY,
    job_id INTEGER REFERENCES download_jobs(id),
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    status VARCHAR DEFAULT 'pending',  -- pending, downloading, completed, failed, skipped
    records_downloaded INTEGER DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX idx_job_items_job ON job_items(job_id);
```

### symbol_metadata

F&O symbol metadata cache.

```sql
CREATE TABLE symbol_metadata (
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    underlying VARCHAR,             -- For derivatives
    expiry DATE,
    strike DOUBLE,
    option_type VARCHAR,            -- CE, PE
    lot_size INTEGER,
    tick_size DOUBLE,
    token VARCHAR,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (symbol, exchange)
);
```

### data_catalog

Tracks available data ranges per symbol.

```sql
CREATE TABLE data_catalog (
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    interval VARCHAR NOT NULL,
    first_date DATE NOT NULL,
    last_date DATE NOT NULL,
    record_count BIGINT DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (symbol, exchange, interval)
);
```

## Data Operations

### Insert OHLCV Data

```python
def insert_ohlcv(conn, symbol, exchange, interval, data):
    """Insert OHLCV data with upsert logic"""
    conn.execute("""
        INSERT INTO market_data (symbol, exchange, interval, timestamp, open, high, low, close, volume, oi)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (symbol, exchange, interval, timestamp)
        DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            oi = EXCLUDED.oi
    """, [
        symbol, exchange, interval,
        data['timestamp'], data['open'], data['high'],
        data['low'], data['close'], data['volume'], data.get('oi')
    ])
```

### Query OHLCV Data

```python
def get_ohlcv(conn, symbol, exchange, interval, start_date, end_date):
    """Retrieve OHLCV data for date range"""
    result = conn.execute("""
        SELECT timestamp, open, high, low, close, volume, oi
        FROM market_data
        WHERE symbol = ?
          AND exchange = ?
          AND interval = ?
          AND timestamp >= ?
          AND timestamp <= ?
        ORDER BY timestamp
    """, [symbol, exchange, interval, start_date, end_date])

    return result.fetchdf()  # Returns pandas DataFrame
```

### Aggregate Timeframes On-The-Fly

```python
def aggregate_timeframe(conn, symbol, exchange, target_interval, start_date, end_date):
    """
    Aggregate 1-minute data to higher timeframes.
    Supported: 5m, 15m, 30m, 1h from 1m base data.
    """
    interval_minutes = {
        '5m': 5, '15m': 15, '30m': 30, '1h': 60
    }

    minutes = interval_minutes.get(target_interval)
    if not minutes:
        raise ValueError(f"Unsupported interval: {target_interval}")

    result = conn.execute("""
        SELECT
            time_bucket(INTERVAL ? MINUTES, timestamp) AS timestamp,
            FIRST(open) AS open,
            MAX(high) AS high,
            MIN(low) AS low,
            LAST(close) AS close,
            SUM(volume) AS volume,
            LAST(oi) AS oi
        FROM market_data
        WHERE symbol = ?
          AND exchange = ?
          AND interval = '1m'
          AND timestamp >= ?
          AND timestamp <= ?
        GROUP BY time_bucket(INTERVAL ? MINUTES, timestamp)
        ORDER BY timestamp
    """, [minutes, symbol, exchange, start_date, end_date, minutes])

    return result.fetchdf()
```

## Indexing Strategy

### Primary Queries

| Query Type | Index Used |
|------------|------------|
| Single symbol date range | `idx_market_data_symbol` |
| All symbols for date | `idx_market_data_timestamp` |
| Specific interval only | `idx_market_data_interval` |

### Query Performance

| Operation | Data Size | Expected Time |
|-----------|-----------|---------------|
| Single day, 1 symbol | ~375 rows | < 10ms |
| 1 year daily, 1 symbol | ~250 rows | < 5ms |
| 1 year 1m, 1 symbol | ~93,750 rows | < 50ms |
| Aggregation (1m → 1h) | 1 year | < 100ms |

## Data Storage Estimates

### Per Candle Storage

| Field | Size (bytes) |
|-------|--------------|
| symbol | ~10 |
| exchange | ~4 |
| interval | ~2 |
| timestamp | 8 |
| OHLCV | 40 |
| oi | 8 |
| **Total (uncompressed)** | ~72 |
| **Compressed** | ~15-20 |

### Storage Projections

| Scenario | Raw Size | Compressed |
|----------|----------|------------|
| 100 symbols × 1 year × 1m | ~2.7 GB | ~500 MB |
| 100 symbols × 1 year × D | ~1.8 MB | ~400 KB |
| 1000 symbols × 1 year × D | ~18 MB | ~4 MB |

## Data Integrity

### Duplicate Prevention

```sql
-- Unique constraint prevents duplicates
PRIMARY KEY (symbol, exchange, interval, timestamp)

-- Upsert pattern updates existing records
ON CONFLICT DO UPDATE SET ...
```

### Gap Detection

```python
def detect_gaps(conn, symbol, exchange, interval, start_date, end_date):
    """Detect missing data gaps"""
    result = conn.execute("""
        WITH expected_times AS (
            SELECT generate_series(
                ?::TIMESTAMP,
                ?::TIMESTAMP,
                INTERVAL '1 minute'
            ) AS timestamp
        ),
        actual_times AS (
            SELECT timestamp
            FROM market_data
            WHERE symbol = ? AND exchange = ? AND interval = ?
        )
        SELECT e.timestamp
        FROM expected_times e
        LEFT JOIN actual_times a ON e.timestamp = a.timestamp
        WHERE a.timestamp IS NULL
          AND EXTRACT(HOUR FROM e.timestamp) >= 9
          AND EXTRACT(HOUR FROM e.timestamp) < 16
    """, [start_date, end_date, symbol, exchange, interval])

    return result.fetchdf()
```

## Export Functions

### Export to CSV

```python
def export_to_csv(conn, symbol, exchange, interval, start_date, end_date, filepath):
    """Export data to CSV file"""
    conn.execute("""
        COPY (
            SELECT timestamp, open, high, low, close, volume, oi
            FROM market_data
            WHERE symbol = ?
              AND exchange = ?
              AND interval = ?
              AND timestamp >= ?
              AND timestamp <= ?
            ORDER BY timestamp
        ) TO ? (HEADER, DELIMITER ',')
    """, [symbol, exchange, interval, start_date, end_date, filepath])
```

### Export to Parquet

```python
def export_to_parquet(conn, symbol, exchange, interval, start_date, end_date, filepath):
    """Export data to Parquet file"""
    conn.execute("""
        COPY (
            SELECT timestamp, open, high, low, close, volume, oi
            FROM market_data
            WHERE symbol = ?
              AND exchange = ?
              AND interval = ?
              AND timestamp >= ?
              AND timestamp <= ?
            ORDER BY timestamp
        ) TO ? (FORMAT PARQUET)
    """, [symbol, exchange, interval, start_date, end_date, filepath])
```

### Export to DataFrame

```python
def to_dataframe(conn, symbol, exchange, interval, start_date, end_date):
    """Return data as pandas DataFrame"""
    result = conn.execute("""
        SELECT timestamp, open, high, low, close, volume, oi
        FROM market_data
        WHERE symbol = ? AND exchange = ? AND interval = ?
          AND timestamp >= ? AND timestamp <= ?
        ORDER BY timestamp
    """, [symbol, exchange, interval, start_date, end_date])

    return result.fetchdf()
```

## Connection Management

```python
import duckdb
from contextlib import contextmanager

DATABASE_PATH = 'db/historify.duckdb'

@contextmanager
def get_connection():
    """Get DuckDB connection with context manager"""
    conn = duckdb.connect(DATABASE_PATH)
    try:
        yield conn
    finally:
        conn.close()

# Usage
with get_connection() as conn:
    df = get_ohlcv(conn, 'SBIN', 'NSE', '1m', '2024-01-01', '2024-01-31')
```

## Related Documentation

| Document | Description |
|----------|-------------|
| [Historify PRD](./historify.md) | Product requirements |
| [Download Engine](./historify-download-engine.md) | Bulk download management |
| [API Reference](./historify-api-reference.md) | Complete API documentation |
