# 08 - Historify Architecture

## Overview

Historify is OpenAlgo's historical market data management system built on DuckDB, a high-performance columnar database optimized for analytical queries. It provides efficient storage, retrieval, and export of OHLCV data for backtesting and analysis.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Historify Architecture                                 │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│  React UI       │   │  REST API       │   │  Python SDK     │
│  /historify     │   │  /api/v1/       │   │  (Backtesting)  │
└────────┬────────┘   └────────┬────────┘   └────────┬────────┘
         │                     │                      │
         └─────────────────────┼──────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                     Historify Service Layer                                   │
│                                                                               │
│  ┌───────────────────┐  ┌───────────────────┐  ┌───────────────────────────┐ │
│  │  Watchlist Ops    │  │  Data Download    │  │  Export/Import           │ │
│  │  - Add/Remove     │  │  - Single Symbol  │  │  - CSV Export            │ │
│  │  - Bulk Add       │  │  - Bulk Download  │  │  - Parquet Import        │ │
│  │  - List           │  │  - Job Tracking   │  │  - DataFrame Export      │ │
│  └───────────────────┘  └───────────────────┘  └───────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        DuckDB (historify.duckdb)                              │
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  market_data (Columnar OHLCV Storage)                                  │  │
│  │  - symbol, exchange, interval, timestamp                               │  │
│  │  - open, high, low, close, volume, oi                                  │  │
│  │  - Billions of rows with fast analytical queries                       │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │    watchlist    │  │  data_catalog   │  │  download_jobs  │              │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘              │
└──────────────────────────────────────────────────────────────────────────────┘
                               │
                               │ Fetch Historical Data
                               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                      Broker History APIs                                      │
│  (Zerodha, Angel, Dhan, Fyers, etc.)                                         │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Why DuckDB?

| Feature | Benefit |
|---------|---------|
| **Columnar Storage** | Fast analytical queries on OHLCV data |
| **No Server** | Single file database, easy deployment |
| **SQL Interface** | Familiar query language |
| **Vectorized Execution** | Fast aggregations and time-series queries |
| **Parquet Support** | Native import/export |
| **Low Memory** | Efficient memory usage |

## Database Schema

**Location:** `database/historify_db.py`

### Tables

```sql
-- Main OHLCV data table
CREATE TABLE market_data (
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    interval VARCHAR NOT NULL,
    timestamp BIGINT NOT NULL,       -- Unix timestamp
    open DOUBLE NOT NULL,
    high DOUBLE NOT NULL,
    low DOUBLE NOT NULL,
    close DOUBLE NOT NULL,
    volume BIGINT NOT NULL,
    oi BIGINT DEFAULT 0,             -- Open Interest
    created_at TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (symbol, exchange, interval, timestamp)
);

-- Watchlist for tracking symbols
CREATE TABLE watchlist (
    id INTEGER PRIMARY KEY,
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    display_name VARCHAR,
    added_at TIMESTAMP DEFAULT current_timestamp,
    UNIQUE (symbol, exchange)
);

-- Data catalog for tracking downloaded ranges
CREATE TABLE data_catalog (
    id INTEGER PRIMARY KEY,
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    interval VARCHAR NOT NULL,
    first_timestamp BIGINT,
    last_timestamp BIGINT,
    record_count BIGINT DEFAULT 0,
    last_download_at TIMESTAMP,
    UNIQUE (symbol, exchange, interval)
);

-- Download jobs for bulk operations
CREATE TABLE download_jobs (
    id VARCHAR PRIMARY KEY,
    job_type VARCHAR NOT NULL,       -- 'single', 'bulk', 'watchlist'
    status VARCHAR NOT NULL,         -- 'pending', 'running', 'completed', 'failed'
    total_symbols INTEGER DEFAULT 0,
    completed_symbols INTEGER DEFAULT 0,
    failed_symbols INTEGER DEFAULT 0,
    interval VARCHAR,
    start_date VARCHAR,
    end_date VARCHAR,
    created_at TIMESTAMP,
    completed_at TIMESTAMP
);

-- Individual symbol status within a job
CREATE TABLE job_items (
    id INTEGER PRIMARY KEY,
    job_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    records_downloaded INTEGER DEFAULT 0,
    error_message VARCHAR,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);
```

## Supported Intervals

### Storage Intervals (Stored in DB)

| Interval | Description |
|----------|-------------|
| `1minute` | 1-minute candles |
| `5minute` | 5-minute candles |
| `15minute` | 15-minute candles |
| `30minute` | 30-minute candles |
| `60minute` | 1-hour candles |
| `1day` | Daily candles |

### Computed Intervals (Aggregated on-the-fly)

| Interval | Source |
|----------|--------|
| `3minute` | From 1minute |
| `10minute` | From 5minute |
| `2hour` | From 60minute |
| `4hour` | From 60minute |
| `1week` | From 1day |
| `1month` | From 1day |

## Service Layer

**Location:** `services/historify_service.py`

### Watchlist Operations

```python
def get_watchlist():
    """Get all symbols in watchlist"""
    return db_get_watchlist()

def add_to_watchlist(symbol: str, exchange: str, display_name: str = None):
    """Add symbol to watchlist"""
    if exchange not in SUPPORTED_EXCHANGES:
        raise ValueError(f"Invalid exchange: {exchange}")
    return db_add_to_watchlist(symbol, exchange, display_name)

def remove_from_watchlist(symbol: str, exchange: str):
    """Remove symbol from watchlist"""
    return db_remove_from_watchlist(symbol, exchange)

def bulk_add_to_watchlist(symbols: List[dict]):
    """Add multiple symbols at once"""
    return db_bulk_add_to_watchlist(symbols)
```

### Data Download

```python
def download_data(symbol: str, exchange: str, interval: str,
                  start_date: str, end_date: str) -> Tuple[bool, dict, int]:
    """
    Download historical data from broker and store in DuckDB.

    1. Validate inputs
    2. Call broker history API
    3. Transform to OHLCV format
    4. Upsert into DuckDB
    5. Update data catalog
    """
    # Get broker auth
    auth = get_auth_token_broker()

    # Fetch from broker
    success, data = get_history(symbol, exchange, interval, start_date, end_date, auth)

    if success:
        # Upsert to DuckDB
        records = upsert_market_data(symbol, exchange, interval, data)
        return True, {'records': records}, 200

    return False, {'error': 'Download failed'}, 500
```

### Data Retrieval

```python
def get_ohlcv_data(symbol: str, exchange: str, interval: str,
                   start: Optional[int] = None, end: Optional[int] = None):
    """
    Get OHLCV data from DuckDB.

    For storage intervals: Direct query
    For computed intervals: Aggregate from source interval
    """
    if interval in STORAGE_INTERVALS:
        return db_get_ohlcv(symbol, exchange, interval, start, end)
    elif interval in COMPUTED_INTERVALS:
        source_interval = COMPUTED_INTERVALS[interval]['source']
        return aggregate_ohlcv(symbol, exchange, source_interval, interval, start, end)
```

### Export Functions

```python
def export_to_csv(symbol: str, exchange: str, interval: str,
                  filepath: str, start: int = None, end: int = None):
    """Export data to CSV file"""
    return db_export_to_csv(symbol, exchange, interval, filepath, start, end)

def export_to_dataframe(symbol: str, exchange: str, interval: str,
                        start: int = None, end: int = None) -> pd.DataFrame:
    """Export to pandas DataFrame for analysis"""
    return export_to_dataframe(symbol, exchange, interval, start, end)
```

## Data Flow

### Download Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Data Download Flow                            │
└─────────────────────────────────────────────────────────────────┘

User Request (symbol, exchange, interval, date range)
                      │
                      ▼
┌─────────────────────────────────────────┐
│  1. Validate Inputs                      │
│     - Check symbol exists                │
│     - Validate interval                  │
│     - Parse date range                   │
└────────────────────┬────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────┐
│  2. Get Broker Auth Token                │
│     - Get from auth_db                   │
│     - Decrypt token                      │
└────────────────────┬────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────┐
│  3. Call Broker History API              │
│     - broker/{name}/api/data.py         │
│     - get_history()                      │
└────────────────────┬────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────┐
│  4. Transform to OHLCV Format            │
│     - Normalize timestamps               │
│     - Validate data quality              │
└────────────────────┬────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────┐
│  5. Upsert to DuckDB                     │
│     - INSERT OR REPLACE                  │
│     - Update data_catalog                │
└────────────────────┬────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────┐
│  6. Return Success Response              │
│     - Records inserted                   │
│     - Date range covered                 │
└─────────────────────────────────────────┘
```

### Query Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Data Query Flow                               │
└─────────────────────────────────────────────────────────────────┘

OHLCV Request (symbol, exchange, interval, time range)
                      │
                      ▼
┌─────────────────────────────────────────┐
│  Is interval in STORAGE_INTERVALS?       │
└────────────┬───────────────┬────────────┘
             │               │
            Yes              No
             │               │
             ▼               ▼
┌────────────────┐  ┌────────────────────────┐
│ Direct Query   │  │ Aggregate from source  │
│ FROM           │  │ - Get source data      │
│ market_data    │  │ - Resample timeframe   │
│ WHERE ...      │  │ - Calculate OHLCV      │
└───────┬────────┘  └───────────┬────────────┘
        │                       │
        └───────────┬───────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│  Return DataFrame/JSON                   │
│  [timestamp, open, high, low, close,     │
│   volume, oi]                            │
└─────────────────────────────────────────┘
```

## API Endpoints

### Watchlist

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/historify/watchlist` | Get watchlist |
| POST | `/api/v1/historify/watchlist` | Add to watchlist |
| DELETE | `/api/v1/historify/watchlist` | Remove from watchlist |

### Data Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/historify/download` | Download historical data |
| GET | `/api/v1/historify/ohlcv` | Get OHLCV data |
| GET | `/api/v1/historify/catalog` | Get data catalog |
| GET | `/api/v1/historify/export` | Export to CSV |

### Bulk Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/historify/jobs` | Start bulk download job |
| GET | `/api/v1/historify/jobs/{id}` | Get job status |
| DELETE | `/api/v1/historify/jobs/{id}` | Cancel job |

## Configuration

### Environment Variables

```bash
# Database path
HISTORIFY_DATABASE_PATH=db/historify.duckdb

# Download settings
HISTORIFY_BATCH_SIZE=10          # Symbols per batch
HISTORIFY_RATE_LIMIT=5           # Requests per second
```

## Supported Exchanges

| Exchange | Description |
|----------|-------------|
| `NSE` | National Stock Exchange |
| `BSE` | Bombay Stock Exchange |
| `NFO` | NSE F&O |
| `BFO` | BSE F&O |
| `CDS` | Currency Derivatives |
| `MCX` | Multi Commodity Exchange |

## Usage Example

### Python

```python
from services.historify_service import (
    add_to_watchlist,
    download_data,
    get_ohlcv_data,
    export_to_dataframe
)

# Add symbol to watchlist
add_to_watchlist('SBIN', 'NSE', 'State Bank of India')

# Download historical data
download_data('SBIN', 'NSE', '1day', '2024-01-01', '2024-12-31')

# Get OHLCV data
data = get_ohlcv_data('SBIN', 'NSE', '1day')

# Export to DataFrame for backtesting
df = export_to_dataframe('SBIN', 'NSE', '1day')
print(df.head())
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `database/historify_db.py` | DuckDB schema and queries |
| `services/historify_service.py` | Business logic |
| `blueprints/historify.py` | REST API endpoints |
| `frontend/src/pages/Historify.tsx` | React UI |
