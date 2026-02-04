# PRD: Historify - Historical Data Management

> **Status:** 🚧 Beta - Implemented but evolving; some broker integrations may vary

## Overview

Historify is OpenAlgo's historical market data management system for downloading, storing, and exporting OHLCV data for backtesting and analysis.

## Problem Statement

Traders need historical data for:
- Backtesting strategies before live deployment
- Technical analysis and pattern recognition
- Training machine learning models

Current challenges:
- Broker APIs have rate limits and data retention limits
- No unified format across brokers
- Manual CSV downloads are tedious
- Large datasets require efficient storage

## Solution

A DuckDB-powered data management system that:
- Downloads historical data from connected broker
- Stores efficiently in columnar format
- Supports bulk downloads with job tracking
- Exports to CSV/Parquet for external tools

## Target Users

| User | Use Case |
|------|----------|
| Backtester | Download data for strategy validation |
| Quant Developer | Build ML models with historical data |
| Technical Analyst | Analyze patterns across timeframes |

## Functional Requirements

### FR1: Watchlist Management
| ID | Requirement | Priority |
|----|-------------|----------|
| FR1.1 | Add symbols to watchlist | P0 |
| FR1.2 | Bulk add from CSV | P1 |
| FR1.3 | Remove symbols | P0 |
| FR1.4 | Display symbol metadata | P2 |

### FR2: Data Download
| ID | Requirement | Priority |
|----|-------------|----------|
| FR2.1 | Download single symbol | P0 |
| FR2.2 | Bulk download (batch jobs) | P0 |
| FR2.3 | Download entire option chains | P1 |
| FR2.4 | Incremental download (append new data) | P0 |
| FR2.5 | Job pause/resume/cancel | P1 |
| FR2.6 | Progress tracking via WebSocket | P1 |

### FR3: Data Storage
| ID | Requirement | Priority |
|----|-------------|----------|
| FR3.1 | Store 1-minute and daily candles | P0 |
| FR3.2 | Compute other timeframes on-the-fly | P0 |
| FR3.3 | Store open interest for F&O | P1 |
| FR3.4 | Track data catalog (date ranges) | P0 |

### FR4: Data Export
| ID | Requirement | Priority |
|----|-------------|----------|
| FR4.1 | Export to CSV | P0 |
| FR4.2 | Export to Parquet | P1 |
| FR4.3 | Export to pandas DataFrame | P0 |
| FR4.4 | Filtered export (date range) | P1 |

### FR5: FNO Discovery
| ID | Requirement | Priority |
|----|-------------|----------|
| FR5.1 | List underlyings (NIFTY, BANKNIFTY, etc.) | P1 |
| FR5.2 | Get available expiries | P1 |
| FR5.3 | Get option chain for expiry | P1 |

## Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Storage efficiency | < 100 bytes per candle |
| Query performance | < 100ms for 1 year daily data |
| Bulk download rate | 5 symbols/second |
| Max symbols per job | 10,000 |

## Database Schema

```
┌─────────────────────────────────────────────────┐
│                  DuckDB                          │
├─────────────────────────────────────────────────┤
│ market_data     - OHLCV candles                 │
│ watchlist       - Tracked symbols               │
│ download_jobs   - Bulk job tracking             │
│ job_items       - Per-symbol status             │
│ symbol_metadata - Expiry, strike, lotsize       │
└─────────────────────────────────────────────────┘
```

## Data Flow

```
User Request → Validate → Broker History API → Transform → DuckDB → Response
                              │
                              ▼
                    Rate Limiter (5 req/sec)
```

## Supported Intervals

| Stored | Computed from 1m |
|--------|------------------|
| 1m, D  | 5m, 15m, 30m, 1h |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/historify/watchlist` | GET/POST/DELETE | Watchlist CRUD |
| `/api/v1/historify/download` | POST | Start download |
| `/api/v1/historify/jobs` | GET/POST | Job management |
| `/api/v1/historify/ohlcv` | GET | Query data |
| `/api/v1/historify/export` | GET | Export to file |

## UI Wireframe

```
┌─────────────────────────────────────────────────────────────┐
│  Historify                                    [Download All] │
├─────────────────────────────────────────────────────────────┤
│  Watchlist (25 symbols)                                      │
│  ┌─────────┬──────────┬───────────┬──────────┬───────────┐  │
│  │ Symbol  │ Exchange │ Data From │ Data To  │ Actions   │  │
│  ├─────────┼──────────┼───────────┼──────────┼───────────┤  │
│  │ SBIN    │ NSE      │ 2023-01-01│ 2024-01-15│ [↓] [×]  │  │
│  │ RELIANCE│ NSE      │ 2023-01-01│ 2024-01-15│ [↓] [×]  │  │
│  └─────────┴──────────┴───────────┴──────────┴───────────┘  │
│                                                              │
│  Active Jobs                                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Job #123: Downloading NIFTY options (45/120)  [Pause]│   │
│  │ ████████████░░░░░░░░░░░░ 37%                         │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Related Documentation

| Document | Description |
|----------|-------------|
| [Data Model](./historify-data-model.md) | DuckDB schema and storage |
| [Download Engine](./historify-download-engine.md) | Bulk download job management |
| [API Reference](./historify-api-reference.md) | Complete API documentation |

## Key Files Reference

| File | Purpose |
|------|---------|
| `blueprints/historify.py` | Web routes and API endpoints |
| `services/historify_service.py` | Core download and storage logic |
| `services/historify_scheduler_service.py` | Bulk job scheduling |
| `db/historify.duckdb` | DuckDB database file |
| `frontend/src/pages/Historify.tsx` | React watchlist/download UI |
| `frontend/src/pages/HistorifyCharts.tsx` | React chart visualization |

> **Note:** Historical data availability depends on broker API capabilities. Not all brokers support the full date range or all intervals.

## Success Metrics

| Metric | Target |
|--------|--------|
| Data accuracy | 100% match with broker |
| Download success rate | > 95% |
| Storage growth | < 1GB per 1M candles |
