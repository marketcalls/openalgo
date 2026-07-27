# Historify API Reference

Complete API documentation for the Historify historical data management feature.

## Endpoints Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/historify/watchlist` | GET | List watchlist symbols |
| `/api/v1/historify/watchlist` | POST | Add symbol to watchlist |
| `/api/v1/historify/watchlist` | DELETE | Remove symbol from watchlist |
| `/api/v1/historify/download` | POST | Start data download |
| `/api/v1/historify/jobs` | GET | List download jobs |
| `/api/v1/historify/jobs/<id>` | GET | Get job details |
| `/api/v1/historify/jobs/<id>/pause` | POST | Pause job |
| `/api/v1/historify/jobs/<id>/resume` | POST | Resume job |
| `/api/v1/historify/jobs/<id>/cancel` | POST | Cancel job |
| `/api/v1/historify/ohlcv` | GET | Query OHLCV data |
| `/api/v1/historify/export` | GET | Export data to file |
| `/api/v1/historify/catalog` | GET | Get data catalog |
| `/api/v1/historify/fno/underlyings` | GET | List F&O underlyings |
| `/api/v1/historify/fno/expiries` | GET | Get expiry dates |
| `/api/v1/historify/fno/strikes` | GET | Get option strikes |

---

## Watchlist Endpoints

### List Watchlist

Get all symbols in the watchlist.

```http
GET /api/v1/historify/watchlist
```

**Response:**

```json
{
  "status": "success",
  "watchlist": [
    {
      "id": 1,
      "symbol": "SBIN",
      "exchange": "NSE",
      "display_name": "State Bank of India",
      "instrument_type": "EQ",
      "lot_size": 1,
      "added_at": "2024-01-15T09:00:00"
    },
    {
      "id": 2,
      "symbol": "NIFTY24JAN18000CE",
      "exchange": "NFO",
      "display_name": "NIFTY 18000 CE Jan 2024",
      "instrument_type": "OPT",
      "expiry": "2024-01-25",
      "strike": 18000,
      "option_type": "CE",
      "lot_size": 50,
      "added_at": "2024-01-15T10:00:00"
    }
  ]
}
```

### Add to Watchlist

Add a symbol to the watchlist.

```http
POST /api/v1/historify/watchlist
Content-Type: application/json
```

**Body:**

```json
{
  "symbol": "RELIANCE",
  "exchange": "NSE"
}
```

**Response:**

```json
{
  "status": "success",
  "message": "Symbol added to watchlist",
  "watchlist_item": {
    "id": 3,
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "display_name": "Reliance Industries Ltd",
    "instrument_type": "EQ",
    "lot_size": 1
  }
}
```

### Bulk Add to Watchlist

Add multiple symbols at once.

```http
POST /api/v1/historify/watchlist/bulk
Content-Type: application/json
```

**Body:**

```json
{
  "symbols": [
    {"symbol": "SBIN", "exchange": "NSE"},
    {"symbol": "HDFC", "exchange": "NSE"},
    {"symbol": "INFY", "exchange": "NSE"}
  ]
}
```

**Response:**

```json
{
  "status": "success",
  "added": 3,
  "skipped": 0,
  "message": "3 symbols added to watchlist"
}
```

### Remove from Watchlist

Remove a symbol from the watchlist.

```http
DELETE /api/v1/historify/watchlist
Content-Type: application/json
```

**Body:**

```json
{
  "symbol": "RELIANCE",
  "exchange": "NSE"
}
```

**Response:**

```json
{
  "status": "success",
  "message": "Symbol removed from watchlist"
}
```

---

## Download Endpoints

### Start Download

Start a data download job.

```http
POST /api/v1/historify/download
Content-Type: application/json
```

**Body:**

```json
{
  "symbols": [
    {"symbol": "SBIN", "exchange": "NSE"},
    {"symbol": "RELIANCE", "exchange": "NSE"}
  ],
  "start_date": "2024-01-01",
  "end_date": "2024-01-31",
  "interval": "1m"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `symbols` | array | Yes | Symbols to download |
| `start_date` | string | Yes | Start date (YYYY-MM-DD) |
| `end_date` | string | Yes | End date (YYYY-MM-DD) |
| `interval` | string | No | Data interval: `1m`, `D` (default: `1m`) |
| `incremental` | boolean | No | Only download missing data (default: `true`) |

**Response:**

```json
{
  "status": "success",
  "job_id": 123,
  "message": "Download job created",
  "job": {
    "id": 123,
    "status": "pending",
    "total_items": 2,
    "start_date": "2024-01-01",
    "end_date": "2024-01-31",
    "interval": "1m"
  }
}
```

### Download Watchlist

Download data for all watchlist symbols.

```http
POST /api/v1/historify/download/watchlist
Content-Type: application/json
```

**Body:**

```json
{
  "start_date": "2024-01-01",
  "end_date": "2024-01-31",
  "interval": "1m"
}
```

**Response:**

```json
{
  "status": "success",
  "job_id": 124,
  "message": "Download job created for 25 watchlist symbols"
}
```

---

## Job Management Endpoints

### List Jobs

Get all download jobs.

```http
GET /api/v1/historify/jobs
```

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | string | all | Filter by status |
| `limit` | int | 20 | Max results |
| `offset` | int | 0 | Pagination offset |

**Response:**

```json
{
  "status": "success",
  "jobs": [
    {
      "id": 123,
      "job_name": "Equity Download",
      "status": "running",
      "total_items": 25,
      "completed_items": 10,
      "failed_items": 1,
      "created_at": "2024-01-15T10:00:00",
      "started_at": "2024-01-15T10:00:05"
    }
  ],
  "total": 15,
  "limit": 20,
  "offset": 0
}
```

### Get Job Details

Get detailed information for a specific job.

```http
GET /api/v1/historify/jobs/<job_id>
```

**Response:**

```json
{
  "status": "success",
  "job": {
    "id": 123,
    "job_name": "Equity Download",
    "status": "running",
    "total_items": 25,
    "completed_items": 10,
    "failed_items": 1,
    "start_date": "2024-01-01",
    "end_date": "2024-01-31",
    "interval": "1m",
    "created_at": "2024-01-15T10:00:00",
    "items": [
      {
        "symbol": "SBIN",
        "exchange": "NSE",
        "status": "completed",
        "records_downloaded": 9375
      },
      {
        "symbol": "HDFC",
        "exchange": "NSE",
        "status": "downloading",
        "records_downloaded": 0
      },
      {
        "symbol": "INFY",
        "exchange": "NSE",
        "status": "failed",
        "error_message": "No data available"
      }
    ]
  }
}
```

### Pause Job

```http
POST /api/v1/historify/jobs/<job_id>/pause
```

**Response:**

```json
{
  "status": "success",
  "message": "Job paused"
}
```

### Resume Job

```http
POST /api/v1/historify/jobs/<job_id>/resume
```

**Response:**

```json
{
  "status": "success",
  "message": "Job resumed"
}
```

### Cancel Job

```http
POST /api/v1/historify/jobs/<job_id>/cancel
```

**Response:**

```json
{
  "status": "success",
  "message": "Job cancelled"
}
```

---

## Query Endpoints

### Get OHLCV Data

Query stored OHLCV data.

```http
GET /api/v1/historify/ohlcv
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | Yes | Trading symbol |
| `exchange` | string | Yes | Exchange code |
| `interval` | string | No | Data interval (default: `D`) |
| `start_date` | string | Yes | Start date (YYYY-MM-DD) |
| `end_date` | string | Yes | End date (YYYY-MM-DD) |

**Supported Intervals:**

| Interval | Description | Storage |
|----------|-------------|---------|
| `1m` | 1 minute | Stored |
| `5m` | 5 minutes | Computed from 1m |
| `15m` | 15 minutes | Computed from 1m |
| `30m` | 30 minutes | Computed from 1m |
| `1h` | 1 hour | Computed from 1m |
| `D` | Daily | Stored |

**Response:**

```json
{
  "status": "success",
  "symbol": "SBIN",
  "exchange": "NSE",
  "interval": "D",
  "data": [
    {
      "timestamp": "2024-01-02T00:00:00",
      "open": 620.50,
      "high": 625.00,
      "low": 618.25,
      "close": 623.75,
      "volume": 15000000
    },
    {
      "timestamp": "2024-01-03T00:00:00",
      "open": 624.00,
      "high": 630.00,
      "low": 622.00,
      "close": 628.50,
      "volume": 18000000
    }
  ],
  "count": 2
}
```

### Export Data

Export data to file.

```http
GET /api/v1/historify/export
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | Yes | Trading symbol |
| `exchange` | string | Yes | Exchange code |
| `interval` | string | No | Data interval (default: `D`) |
| `start_date` | string | Yes | Start date |
| `end_date` | string | Yes | End date |
| `format` | string | No | Output format: `csv`, `parquet` (default: `csv`) |

**Response:**

Returns file download with appropriate MIME type.

---

## Data Catalog Endpoints

### Get Catalog

Get available data ranges.

```http
GET /api/v1/historify/catalog
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | No | Filter by symbol |
| `exchange` | string | No | Filter by exchange |

**Response:**

```json
{
  "status": "success",
  "catalog": [
    {
      "symbol": "SBIN",
      "exchange": "NSE",
      "interval": "1m",
      "first_date": "2023-01-01",
      "last_date": "2024-01-15",
      "record_count": 93750
    },
    {
      "symbol": "SBIN",
      "exchange": "NSE",
      "interval": "D",
      "first_date": "2020-01-01",
      "last_date": "2024-01-15",
      "record_count": 1000
    }
  ]
}
```

---

## F&O Discovery Endpoints

### List Underlyings

Get available F&O underlyings.

```http
GET /api/v1/historify/fno/underlyings
```

**Response:**

```json
{
  "status": "success",
  "underlyings": [
    {"symbol": "NIFTY", "exchange": "NFO", "lot_size": 50},
    {"symbol": "BANKNIFTY", "exchange": "NFO", "lot_size": 15},
    {"symbol": "FINNIFTY", "exchange": "NFO", "lot_size": 40},
    {"symbol": "RELIANCE", "exchange": "NFO", "lot_size": 250}
  ]
}
```

### Get Expiry Dates

Get available expiry dates for underlying.

```http
GET /api/v1/historify/fno/expiries
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `underlying` | string | Yes | Underlying symbol (e.g., NIFTY) |

**Response:**

```json
{
  "status": "success",
  "underlying": "NIFTY",
  "expiries": [
    {"date": "2024-01-25", "type": "weekly"},
    {"date": "2024-02-01", "type": "weekly"},
    {"date": "2024-02-29", "type": "monthly"},
    {"date": "2024-03-28", "type": "monthly"}
  ]
}
```

### Get Option Strikes

Get available strikes for an expiry.

```http
GET /api/v1/historify/fno/strikes
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `underlying` | string | Yes | Underlying symbol |
| `expiry` | string | Yes | Expiry date (YYYY-MM-DD) |

**Response:**

```json
{
  "status": "success",
  "underlying": "NIFTY",
  "expiry": "2024-01-25",
  "strikes": [
    {"strike": 21000, "ce_symbol": "NIFTY24JAN21000CE", "pe_symbol": "NIFTY24JAN21000PE"},
    {"strike": 21050, "ce_symbol": "NIFTY24JAN21050CE", "pe_symbol": "NIFTY24JAN21050PE"},
    {"strike": 21100, "ce_symbol": "NIFTY24JAN21100CE", "pe_symbol": "NIFTY24JAN21100PE"}
  ]
}
```

### Download Option Chain

Download data for all strikes of an expiry.

```http
POST /api/v1/historify/fno/download-chain
Content-Type: application/json
```

**Body:**

```json
{
  "underlying": "NIFTY",
  "expiry": "2024-01-25",
  "start_date": "2024-01-15",
  "end_date": "2024-01-25",
  "interval": "1m"
}
```

**Response:**

```json
{
  "status": "success",
  "job_id": 125,
  "message": "Download job created for 120 option contracts"
}
```

---

## WebSocket Events

### Progress Updates

Connect to WebSocket for real-time job progress.

```javascript
const socket = io('/historify');

socket.on('historify_progress', (data) => {
    console.log(`Job ${data.job_id}: ${data.percent}%`);
    console.log(`Current: ${data.current_symbol}`);
});

socket.on('historify_complete', (data) => {
    console.log(`Job ${data.job_id} completed`);
    console.log(`Downloaded: ${data.total_records} records`);
});

socket.on('historify_error', (data) => {
    console.error(`Job ${data.job_id} error: ${data.message}`);
});
```

---

## Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `SYMBOL_NOT_FOUND` | 404 | Symbol doesn't exist |
| `INVALID_DATE_RANGE` | 400 | Invalid or reversed date range |
| `NO_DATA_AVAILABLE` | 404 | No data for requested range |
| `JOB_NOT_FOUND` | 404 | Download job not found |
| `JOB_NOT_RUNNING` | 409 | Cannot pause/cancel non-running job |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many API requests |
| `BROKER_ERROR` | 500 | Error from broker API |

## Related Documentation

| Document | Description |
|----------|-------------|
| [Historify PRD](./historify.md) | Product requirements |
| [Data Model](./historify-data-model.md) | DuckDB schema |
| [Download Engine](./historify-download-engine.md) | Bulk download management |
