# Python Strategies API Reference

Complete API documentation for the Python Strategy Hosting feature.

## Endpoints Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/python/new` | POST | Upload new strategy |
| `/python/start/<id>` | POST | Start strategy execution |
| `/python/stop/<id>` | POST | Stop strategy execution |
| `/python/delete/<id>` | POST | Delete strategy and logs |
| `/python/schedule/<id>` | POST | Configure schedule |
| `/python/unschedule/<id>` | POST | Remove schedule |
| `/python/logs/<id>` | GET | View strategy logs |
| `/python/logs/<id>/stream` | GET | Stream logs (SSE) |
| `/python/api/strategies` | POST | List all strategies |
| `/python/api/status/<id>` | GET | Get strategy status |

---

## Upload Strategy

Upload a new Python strategy file.

### Request

```http
POST /python/new
Content-Type: multipart/form-data
```

**Form Data:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `strategy_file` | file | Yes | Python script file (.py) |
| `name` | string | No | Display name (defaults to filename) |

### Response

```json
{
  "status": "success",
  "strategy_id": "ema_crossover_20240115_093045",
  "message": "Strategy uploaded successfully"
}
```

### Errors

| Code | Message |
|------|---------|
| 400 | No file provided |
| 400 | Invalid file type (must be .py) |
| 500 | Failed to save strategy |

---

## Start Strategy

Start executing a strategy in a subprocess.

### Request

```http
POST /python/start/<strategy_id>
```

### Response

```json
{
  "status": "success",
  "strategy_id": "ema_crossover_20240115",
  "pid": 12345,
  "message": "Strategy started"
}
```

### Errors

| Code | Message |
|------|---------|
| 404 | Strategy not found |
| 409 | Strategy already running |
| 500 | Failed to start strategy |

---

## Stop Strategy

Stop a running strategy gracefully.

### Request

```http
POST /python/stop/<strategy_id>
```

### Response

```json
{
  "status": "success",
  "strategy_id": "ema_crossover_20240115",
  "message": "Strategy stopped"
}
```

### Errors

| Code | Message |
|------|---------|
| 404 | Strategy not found |
| 409 | Strategy not running |

---

## Delete Strategy

Delete strategy file and associated logs.

### Request

```http
POST /python/delete/<strategy_id>
```

### Response

```json
{
  "status": "success",
  "message": "Strategy deleted"
}
```

### Errors

| Code | Message |
|------|---------|
| 404 | Strategy not found |
| 409 | Cannot delete running strategy |

---

## Configure Schedule

Set automatic start/stop schedule for a strategy.

### Request

```http
POST /python/schedule/<strategy_id>
Content-Type: application/json
```

**Body:**

```json
{
  "start_time": "09:20",
  "stop_time": "15:15",
  "days": ["mon", "tue", "wed", "thu", "fri"]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `start_time` | string | Yes | Start time in HH:MM format (IST) |
| `stop_time` | string | Yes | Stop time in HH:MM format (IST) |
| `days` | array | Yes | Days to run: `mon`, `tue`, `wed`, `thu`, `fri`, `sat` |

### Response

```json
{
  "status": "success",
  "strategy_id": "ema_crossover_20240115",
  "schedule": {
    "start_time": "09:20",
    "stop_time": "15:15",
    "days": ["mon", "tue", "wed", "thu", "fri"]
  },
  "message": "Schedule configured"
}
```

### Errors

| Code | Message |
|------|---------|
| 400 | Invalid time format |
| 400 | Invalid days |
| 404 | Strategy not found |

---

## Remove Schedule

Remove automatic schedule from a strategy.

### Request

```http
POST /python/unschedule/<strategy_id>
```

### Response

```json
{
  "status": "success",
  "message": "Schedule removed"
}
```

---

## View Logs

Get historical logs for a strategy.

### Request

```http
GET /python/logs/<strategy_id>
```

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `lines` | int | 100 | Number of lines to return |
| `offset` | int | 0 | Skip first N lines |

### Response

```json
{
  "status": "success",
  "logs": [
    "2024-01-15 09:20:01 - Starting strategy for SBIN",
    "2024-01-15 09:20:02 - Fetched historical data",
    "2024-01-15 09:20:03 - EMA5=625.50, EMA10=623.20",
    "2024-01-15 09:20:03 - BUY signal generated"
  ]
}
```

---

## Stream Logs (SSE)

Real-time log streaming via Server-Sent Events.

### Request

```http
GET /python/logs/<strategy_id>/stream
Accept: text/event-stream
```

### Response

```
event: log
data: {"timestamp": "2024-01-15T09:20:01", "message": "Starting strategy"}

event: log
data: {"timestamp": "2024-01-15T09:20:02", "message": "BUY signal generated"}

event: status
data: {"status": "running", "pid": 12345}
```

### Event Types

| Event | Description |
|-------|-------------|
| `log` | New log line from strategy |
| `status` | Status change (running/stopped) |
| `error` | Error occurred |

---

## List Strategies

Get all strategies for current user.

### Request

```http
POST /python/api/strategies
```

### Response

```json
{
  "status": "success",
  "strategies": [
    {
      "strategy_id": "ema_crossover_20240115",
      "name": "EMA Crossover",
      "file_path": "ema_crossover.py",
      "is_running": true,
      "is_scheduled": true,
      "schedule_start": "09:20",
      "schedule_stop": "15:15",
      "schedule_days": ["mon", "tue", "wed", "thu", "fri"],
      "pid": 12345,
      "last_started": "2024-01-15T09:20:00",
      "last_stopped": null
    },
    {
      "strategy_id": "rsi_strategy_20240110",
      "name": "RSI Strategy",
      "file_path": "rsi_strategy.py",
      "is_running": false,
      "is_scheduled": false,
      "schedule_start": null,
      "schedule_stop": null,
      "schedule_days": [],
      "pid": null,
      "last_started": "2024-01-10T09:20:00",
      "last_stopped": "2024-01-10T15:15:00"
    }
  ]
}
```

---

## Get Strategy Status

Get detailed status for a specific strategy.

### Request

```http
GET /python/api/status/<strategy_id>
```

### Response

```json
{
  "status": "success",
  "strategy": {
    "strategy_id": "ema_crossover_20240115",
    "name": "EMA Crossover",
    "is_running": true,
    "pid": 12345,
    "uptime_seconds": 3600,
    "memory_mb": 45.2,
    "last_log": "BUY signal generated",
    "schedule": {
      "enabled": true,
      "start_time": "09:20",
      "stop_time": "15:15",
      "days": ["mon", "tue", "wed", "thu", "fri"],
      "next_start": "2024-01-16T09:20:00",
      "next_stop": "2024-01-15T15:15:00"
    }
  }
}
```

---

## Status Update Events (SSE)

Real-time status updates for all strategies.

### Request

```http
GET /python/api/status/stream
Accept: text/event-stream
```

### Response

```
event: status
data: {"strategy_id": "ema_crossover", "status": "running", "pid": 12345}

event: status
data: {"strategy_id": "rsi_strategy", "status": "stopped", "exit_code": 0}

event: schedule
data: {"strategy_id": "ema_crossover", "event": "scheduled_stop", "time": "15:15"}
```

---

## Strategy Script Environment

When a strategy runs, these environment variables are available:

| Variable | Description |
|----------|-------------|
| `OPENALGO_APIKEY` | API key for OpenAlgo requests |
| `OPENALGO_HOST` | OpenAlgo server URL |
| `PYTHONUNBUFFERED` | Set to '1' for real-time output |

### Using OpenAlgo SDK in Strategy

```python
#!/usr/bin/env python
import os
from openalgo import api

# Get credentials from environment
API_KEY = os.getenv('OPENALGO_APIKEY')
HOST = os.getenv('OPENALGO_HOST', 'http://127.0.0.1:5000')

# Initialize client
client = api(api_key=API_KEY, host=HOST)

# Place orders
response = client.placeorder(
    symbol='SBIN',
    exchange='NSE',
    action='BUY',
    quantity=100,
    price_type='MARKET',
    product='MIS'
)

# Get market data
quotes = client.quotes(symbol='SBIN', exchange='NSE')
print(f"LTP: {quotes['ltp']}")

# Get positions
positions = client.positions()
print(f"Open positions: {len(positions)}")
```

---

## Error Response Format

All endpoints return errors in this format:

```json
{
  "status": "error",
  "error_code": "STRATEGY_NOT_FOUND",
  "message": "Strategy with ID 'xyz' not found"
}
```

### Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `STRATEGY_NOT_FOUND` | 404 | Strategy ID doesn't exist |
| `STRATEGY_RUNNING` | 409 | Cannot perform action on running strategy |
| `STRATEGY_NOT_RUNNING` | 409 | Strategy is not currently running |
| `INVALID_FILE_TYPE` | 400 | Uploaded file is not a Python script |
| `INVALID_SCHEDULE` | 400 | Schedule parameters are invalid |
| `SCHEDULE_NOT_FOUND` | 404 | Strategy has no schedule configured |
| `INTERNAL_ERROR` | 500 | Server-side error |

---

## Rate Limits

| Endpoint | Limit |
|----------|-------|
| `/python/new` | 10 uploads/minute |
| `/python/start/*` | 30 requests/minute |
| `/python/logs/*` | 60 requests/minute |
| `/python/api/*` | 120 requests/minute |

## Related Documentation

| Document | Description |
|----------|-------------|
| [Python Strategies PRD](./python-strategies.md) | Product requirements |
| [Process Management](./python-strategies-process-management.md) | Subprocess handling |
| [Scheduling Guide](./python-strategies-scheduling.md) | Market-aware scheduling |
