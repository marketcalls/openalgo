# 08 - Historify

## Overview

Historify is OpenAlgo's historical market data manager built on DuckDB. It downloads OHLCV data from brokers and stores it locally for backtesting and analysis.

## Architecture

```
┌──────────────┐     ┌───────────────────┐     ┌─────────────────┐
│  React UI    │────▶│ Historify Service │────▶│ Broker History  │
│  /historify  │     │                   │     │     APIs        │
└──────────────┘     └─────────┬─────────┘     └─────────────────┘
                               │
                               ▼
                     ┌─────────────────────┐
                     │  DuckDB             │
                     │  historify.duckdb   │
                     └─────────────────────┘
```

## Database (DuckDB)

**Location:** `db/historify.duckdb`

| Table | Purpose |
|-------|---------|
| `market_data` | OHLCV candles (symbol, exchange, interval, timestamp, OHLCV, oi) |
| `watchlist` | Symbols to track |
| `download_jobs` | Bulk download job tracking |
| `job_items` | Individual symbol status within jobs |
| `symbol_metadata` | Enriched symbol info (expiry, strike, lotsize) |

## Intervals

| Storage (Downloaded) | Computed (Aggregated from 1m) |
|---------------------|-------------------------------|
| `1m`, `D` | `5m`, `15m`, `30m`, `1h` |

Only 1-minute and Daily data are stored. Other timeframes are computed on-the-fly from 1-minute data.

## Key Features

- **Watchlist**: Track symbols for batch downloads
- **Bulk Download Jobs**: Download entire option chains with progress tracking
- **Pause/Resume/Cancel**: Job control with Socket.IO progress updates
- **Incremental Download**: Only fetch data after last available timestamp
- **CSV/Parquet Import/Export**: Data portability
- **FNO Discovery**: Find underlyings, expiries, and option chains

## Key Files

| File | Purpose |
|------|---------|
| `database/historify_db.py` | DuckDB schema and queries |
| `services/historify_service.py` | Business logic and job processing |
| `blueprints/historify.py` | Web UI routes |
| `frontend/src/pages/Historify.tsx` | React UI |

## Supported Exchanges

`NSE`, `BSE`, `NFO`, `BFO`, `CDS`, `MCX`
