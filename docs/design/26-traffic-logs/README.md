# 26 - Traffic Logs

## Overview

OpenAlgo logs all HTTP traffic for monitoring, debugging, and security analysis. Traffic logs capture request/response metadata without sensitive data.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Traffic Logging Architecture                          │
└──────────────────────────────────────────────────────────────────────────────┘

                              HTTP Request
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Traffic Logger Middleware                              │
│                              (WSGI)                                          │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Capture Request Data:                                               │   │
│  │  - Timestamp                                                         │   │
│  │  - Client IP (from proxy headers)                                    │   │
│  │  - HTTP Method                                                       │   │
│  │  - Request Path                                                      │   │
│  │  - Host Header                                                       │   │
│  │  - User ID (if authenticated)                                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                   │                                          │
│                                   ▼                                          │
│                           Flask Application                                  │
│                                   │                                          │
│                                   ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Capture Response Data:                                              │   │
│  │  - Status Code                                                       │   │
│  │  - Response Duration (ms)                                            │   │
│  │  - Error Message (if any)                                            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                   │                                          │
│                                   ▼                                          │
│                          Write to logs.db                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Database Schema

### traffic_logs Table

```
┌────────────────────────────────────────────────────┐
│               traffic_logs table                    │
├──────────────┬──────────────┬──────────────────────┤
│ Column       │ Type         │ Description          │
├──────────────┼──────────────┼──────────────────────┤
│ id           │ INTEGER PK   │ Auto-increment       │
│ timestamp    │ DATETIME     │ Request time         │
│ client_ip    │ VARCHAR(50)  │ Client IP address    │
│ method       │ VARCHAR(10)  │ GET/POST/PUT/DELETE  │
│ path         │ VARCHAR(500) │ Request path         │
│ status_code  │ INTEGER      │ HTTP status code     │
│ duration_ms  │ FLOAT        │ Response time        │
│ host         │ VARCHAR(500) │ Host header          │
│ error        │ VARCHAR(500) │ Error message        │
│ user_id      │ INTEGER      │ User ID (nullable)   │
└──────────────┴──────────────┴──────────────────────┘
```

### Indexes

```sql
CREATE INDEX idx_traffic_timestamp ON traffic_logs(timestamp);
CREATE INDEX idx_traffic_client_ip ON traffic_logs(client_ip);
CREATE INDEX idx_traffic_status_code ON traffic_logs(status_code);
CREATE INDEX idx_traffic_user_id ON traffic_logs(user_id);
CREATE INDEX idx_traffic_ip_timestamp ON traffic_logs(client_ip, timestamp);
```

## Implementation

### WSGI Middleware

```python
class TrafficLoggerMiddleware:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        start_time = time.perf_counter()
        client_ip = get_real_ip_from_environ(environ)

        captured_status = [None]

        def custom_start_response(status, headers, exc_info=None):
            captured_status[0] = int(status.split()[0])
            return start_response(status, headers, exc_info)

        response = self.app(environ, custom_start_response)

        duration = (time.perf_counter() - start_time) * 1000

        log_traffic(
            client_ip=client_ip,
            method=environ.get('REQUEST_METHOD'),
            path=environ.get('PATH_INFO'),
            status_code=captured_status[0],
            duration_ms=duration,
            host=environ.get('HTTP_HOST')
        )

        return response
```

### Initialization

```python
from utils.traffic_logger import init_traffic_logging

app = Flask(__name__)
init_traffic_logging(app)
```

## Dashboard

### Access
```
/logs/traffic
```

### Dashboard View

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         Traffic Dashboard                                   │
│                                                                             │
│  Total Requests: 15,234     Errors: 123 (0.8%)     Avg Response: 45ms      │
│                                                                             │
│ ┌─────────────────────────────────────────────────────────────────────────┐│
│ │ Requests per Hour (Last 24h)                                             ││
│ │                                                                          ││
│ │  1000 ┤                      ╭╮                                          ││
│ │   800 ┤                   ╭──╯╰──╮                                       ││
│ │   600 ┤               ╭───╯      ╰───╮                                   ││
│ │   400 ┤           ╭───╯              ╰───╮                               ││
│ │   200 ┤       ╭───╯                      ╰───╮                           ││
│ │     0 ┼───────────────────────────────────────────────────────           ││
│ │       00:00   06:00   12:00   18:00   24:00                              ││
│ └─────────────────────────────────────────────────────────────────────────┘│
│                                                                             │
│ ┌─────────────────────────────────────────────────────────────────────────┐│
│ │ Status Code Distribution                                                 ││
│ │                                                                          ││
│ │  200 OK         ████████████████████████████████  85%                   ││
│ │  301 Redirect   ██████  8%                                              ││
│ │  404 Not Found  ███  4%                                                 ││
│ │  500 Error      █  2%                                                   ││
│ │  Other          █  1%                                                   ││
│ └─────────────────────────────────────────────────────────────────────────┘│
│                                                                             │
│ ┌─────────────────────────────────────────────────────────────────────────┐│
│ │ Recent Requests                                                          ││
│ │                                                                          ││
│ │ Time      │ Method │ Path              │ Status │ Duration │ IP         ││
│ ├───────────┼────────┼───────────────────┼────────┼──────────┼────────────┤│
│ │ 09:30:15  │ POST   │ /api/v1/placeorder│ 200    │ 85ms     │ 192.168.1.5││
│ │ 09:30:16  │ GET    │ /dashboard        │ 200    │ 15ms     │ 192.168.1.5││
│ │ 09:30:20  │ POST   │ /api/v1/positions │ 200    │ 45ms     │ 10.0.0.25  ││
│ │ 09:30:25  │ GET    │ /api/v1/invalid   │ 404    │ 5ms      │ 172.16.0.1 ││
│ └─────────────────────────────────────────────────────────────────────────┘│
└────────────────────────────────────────────────────────────────────────────┘
```

## Filtering Options

### By Status Code

```python
# Filter 5xx errors
logs = TrafficLog.query.filter(
    TrafficLog.status_code >= 500
).all()

# Filter client errors
logs = TrafficLog.query.filter(
    TrafficLog.status_code.between(400, 499)
).all()
```

### By Time Range

```python
from datetime import datetime, timedelta

# Last 24 hours
since = datetime.now() - timedelta(hours=24)
logs = TrafficLog.query.filter(
    TrafficLog.timestamp >= since
).all()
```

### By IP Address

```python
# Specific IP
logs = TrafficLog.query.filter(
    TrafficLog.client_ip == '192.168.1.100'
).all()
```

## Analytics Queries

### Request Volume by Hour

```sql
SELECT
    DATE_TRUNC('hour', timestamp) as hour,
    COUNT(*) as requests
FROM traffic_logs
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY hour
ORDER BY hour
```

### Top Endpoints

```sql
SELECT
    path,
    COUNT(*) as hits,
    AVG(duration_ms) as avg_duration
FROM traffic_logs
GROUP BY path
ORDER BY hits DESC
LIMIT 10
```

### Error Rate

```sql
SELECT
    DATE_TRUNC('hour', timestamp) as hour,
    COUNT(*) as total,
    SUM(CASE WHEN status_code >= 500 THEN 1 ELSE 0 END) as errors,
    (SUM(CASE WHEN status_code >= 500 THEN 1 ELSE 0 END)::float / COUNT(*)) * 100 as error_rate
FROM traffic_logs
GROUP BY hour
ORDER BY hour
```

### Slowest Endpoints

```sql
SELECT
    path,
    AVG(duration_ms) as avg_duration,
    MAX(duration_ms) as max_duration
FROM traffic_logs
GROUP BY path
ORDER BY avg_duration DESC
LIMIT 10
```

## Data Exclusions

### Not Logged

To protect privacy and reduce noise:

```python
EXCLUDED_PATHS = [
    '/static/',
    '/favicon.ico',
    '/health',
    '/_ping'
]

def should_log(path):
    return not any(path.startswith(p) for p in EXCLUDED_PATHS)
```

### Sensitive Data

- Request body NOT logged
- Response body NOT logged
- Headers NOT logged (except Host)
- Cookies NOT logged

## Retention

### Automatic Cleanup

```python
def cleanup_old_logs(days=30):
    cutoff = datetime.now() - timedelta(days=days)
    TrafficLog.query.filter(
        TrafficLog.timestamp < cutoff
    ).delete()
    db.session.commit()
```

### Scheduled Task

```python
# Run daily cleanup
scheduler.add_job(
    cleanup_old_logs,
    'cron',
    hour=2,
    minute=0
)
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `utils/traffic_logger.py` | WSGI middleware |
| `database/traffic_db.py` | Traffic model |
| `utils/ip_helper.py` | IP resolution |
| `blueprints/logs.py` | Dashboard routes |
| `frontend/src/pages/Traffic.tsx` | React dashboard |
