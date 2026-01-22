# 22 - Log Section

## Overview

OpenAlgo provides comprehensive log viewing and management through the web interface, supporting both API order logs and general application logs.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          Log Section Architecture                            │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                           Log Types                                          │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │   API Logs      │  │  Analyzer Logs  │  │  Application    │             │
│  │   /logs         │  │                 │  │  Logs           │             │
│  │                 │  │                 │  │                 │             │
│  │  - placeorder   │  │  - Virtual      │  │  - log/*.log    │             │
│  │  - cancelorder  │  │    orders       │  │  - Console      │             │
│  │  - modifyorder  │  │  - Sandbox      │  │  - Rotating     │             │
│  │  - Response     │  │    trades       │  │                 │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                    │                    │                       │
│           └────────────────────┼────────────────────┘                       │
│                                │                                             │
│                                ▼                                             │
│           ┌─────────────────────────────────────────────────────────┐       │
│           │               Logs Database (logs.db)                    │       │
│           │               order_logs / analyzer_logs                 │       │
│           └─────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Log Types

### 1. API Order Logs

**Route:** `/logs`

Displays all API request/response pairs for order operations.

```
┌────────────────────────────────────────────────────────────────────────────┐
│                           API Logs View                                     │
│                                                                             │
│ Filters: [Date Range] [API Type ▼] [Search...]                             │
│                                                                             │
│ ┌─────────────────────────────────────────────────────────────────────────┐│
│ │ Time          │ API Type    │ Request          │ Response      │ Status ││
│ ├───────────────┼─────────────┼──────────────────┼───────────────┼────────┤│
│ │ 09:30:15 IST  │ placeorder  │ SBIN BUY 100 MIS │ orderid: 123  │ ✓      ││
│ │ 09:31:20 IST  │ placeorder  │ INFY SELL 50 CNC │ orderid: 124  │ ✓      ││
│ │ 09:35:45 IST  │ cancelorder │ orderid: 124     │ Cancelled     │ ✓      ││
│ │ 10:15:00 IST  │ placeorder  │ RELIANCE BUY 25  │ Margin error  │ ✗      ││
│ └─────────────────────────────────────────────────────────────────────────┘│
│                                                                             │
│ Pagination: [< Prev] Page 1 of 25 [Next >]                                 │
└────────────────────────────────────────────────────────────────────────────┘
```

### 2. Analyzer Logs

**Route:** `/analyzer-logs`

Logs from sandbox/paper trading mode.

### 3. Application Logs

**Location:** `log/openalgo.log`

File-based logs for debugging and monitoring.

## Database Schema

### order_logs Table

```
┌────────────────────────────────────────────────────┐
│                 order_logs table                    │
├──────────────┬──────────────┬──────────────────────┤
│ Column       │ Type         │ Description          │
├──────────────┼──────────────┼──────────────────────┤
│ id           │ INTEGER PK   │ Auto-increment       │
│ api_type     │ TEXT         │ placeorder, cancel   │
│ request_data │ TEXT         │ JSON request         │
│ response_data│ TEXT         │ JSON response        │
│ created_at   │ DATETIME     │ Timestamp (IST)      │
└──────────────┴──────────────┴──────────────────────┘
```

### analyzer_logs Table

```
┌────────────────────────────────────────────────────┐
│               analyzer_logs table                   │
├──────────────┬──────────────┬──────────────────────┤
│ Column       │ Type         │ Description          │
├──────────────┼──────────────┼──────────────────────┤
│ id           │ INTEGER PK   │ Auto-increment       │
│ api_type     │ VARCHAR(50)  │ API endpoint type    │
│ request_data │ TEXT         │ JSON request         │
│ response_data│ TEXT         │ JSON response        │
│ created_at   │ DATETIME     │ Timestamp            │
└──────────────┴──────────────┴──────────────────────┘
```

## API Endpoints

### Get Order Logs

```
GET /logs/api/orders
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| page | int | Page number (default: 1) |
| per_page | int | Items per page (default: 50) |
| api_type | string | Filter by API type |
| start_date | string | Start date (YYYY-MM-DD) |
| end_date | string | End date (YYYY-MM-DD) |
| search | string | Search in request/response |

**Response:**

```json
{
    "status": "success",
    "data": [
        {
            "id": 1,
            "api_type": "placeorder",
            "request_data": "{\"symbol\": \"SBIN\", ...}",
            "response_data": "{\"status\": \"success\", ...}",
            "created_at": "2024-01-15 09:30:15"
        }
    ],
    "pagination": {
        "page": 1,
        "per_page": 50,
        "total": 1250,
        "pages": 25
    }
}
```

## Log Filtering

### By API Type

| API Type | Description |
|----------|-------------|
| placeorder | Order placements |
| placesmartorder | Smart orders |
| modifyorder | Order modifications |
| cancelorder | Order cancellations |
| cancelallorders | Bulk cancellations |
| closeposition | Position closures |

### By Date Range

```javascript
// React component example
const [dateRange, setDateRange] = useState({
    start: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000),
    end: new Date()
});
```

### By Search Term

Searches in both request and response JSON data.

## Async Logging

### Non-Blocking Log Writes

```python
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=10)

def async_log_order(api_type, request_data, response_data):
    executor.submit(_write_log, api_type, request_data, response_data)
```

### Benefits

- Request thread not blocked
- No impact on order latency
- Guaranteed log capture

## Log Viewer Features

### React Component

```typescript
// frontend/src/pages/Logs.tsx

export function Logs() {
    const { data, isLoading } = useQuery({
        queryKey: ['logs', filters],
        queryFn: () => api.getLogs(filters),
        refetchInterval: 30000  // Auto-refresh every 30s
    });

    return (
        <DataTable
            data={data}
            columns={columns}
            pagination={true}
            search={true}
        />
    );
}
```

### Features

- Real-time updates
- Pagination
- Filtering by type/date
- Search functionality
- JSON pretty-print
- Export capability

## File Logging

### Configuration

```bash
# .env
LOG_TO_FILE=True
LOG_LEVEL=INFO
LOG_DIR=log
LOG_RETENTION=14
```

### Rotation Settings

| Setting | Value | Description |
|---------|-------|-------------|
| Max Size | 10 MB | Rotate when exceeded |
| Backup Count | 14 | Files to keep |
| Compression | None | Plain text |

### Log Format

```
[2024-01-15 09:30:15] INFO in place_order: Order placed - SBIN BUY 100 MIS
[2024-01-15 09:30:16] DEBUG in broker_api: Response: {"orderid": "123"}
[2024-01-15 09:31:00] WARNING in session: Session expiring in 5 minutes
```

## Viewing Logs

### Via Web UI

1. Navigate to `/logs`
2. Apply filters as needed
3. Click row to expand details
4. Use export for download

### Via Command Line

```bash
# View current log
tail -f log/openalgo.log

# Search for errors
grep ERROR log/openalgo.log

# View last 100 lines
tail -100 log/openalgo.log
```

## Security Considerations

### API Key Redaction

```python
def sanitize_log_data(request_data):
    """Remove sensitive fields before logging"""
    data = json.loads(request_data)
    if 'apikey' in data:
        del data['apikey']
    return json.dumps(data)
```

### Access Control

- Logs only visible to authenticated users
- Session validation required
- No public access

## Key Files Reference

| File | Purpose |
|------|---------|
| `blueprints/logs.py` | Log viewer routes |
| `database/apilog_db.py` | Order logs model |
| `database/analyzer_db.py` | Analyzer logs model |
| `utils/logging.py` | Logging configuration |
| `frontend/src/pages/Logs.tsx` | React log viewer |
