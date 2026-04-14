# 21 - Admin Section

## Overview

The Admin section provides system configuration and management capabilities including freeze quantity management, market holidays, market timings, and security monitoring.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          Admin Section Architecture                           │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                              Admin Dashboard                                 │
│                              /admin                                          │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  Freeze Qty     │  │   Holidays      │  │  Market Timings │             │
│  │  Management     │  │   Calendar      │  │  Configuration  │             │
│  │  /admin/freeze  │  │  /admin/holidays│  │  /admin/timings │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                    │                    │                       │
│           └────────────────────┼────────────────────┘                       │
│                                │                                             │
│                                ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     Admin API Endpoints                              │   │
│  │                     /admin/api/*                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          Monitoring Dashboards                               │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │    Security     │  │    Traffic      │  │    Latency      │             │
│  │   Dashboard     │  │   Dashboard     │  │   Dashboard     │             │
│  │ /logs/security  │  │  /logs/traffic  │  │  /logs/latency  │             │
│  │                 │  │                 │  │                 │             │
│  │  - IP bans      │  │  - HTTP logs    │  │  - Order RTT    │             │
│  │  - 404 tracking │  │  - Request/sec  │  │  - Percentiles  │             │
│  │  - API abuse    │  │  - Error rates  │  │  - SLA metrics  │             │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Freeze Quantity Management

### Purpose
Manage F&O freeze quantity limits for automatic order splitting.

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/api/freeze` | List all freeze quantities |
| POST | `/admin/api/freeze` | Add new entry |
| PUT | `/admin/api/freeze/<id>` | Update entry |
| DELETE | `/admin/api/freeze/<id>` | Delete entry |
| POST | `/admin/api/freeze/upload` | Bulk CSV upload |

### Database Schema

```
┌────────────────────────────────────────────────────┐
│                 qty_freeze table                    │
├──────────────┬──────────────┬──────────────────────┤
│ Column       │ Type         │ Description          │
├──────────────┼──────────────┼──────────────────────┤
│ id           │ INTEGER PK   │ Auto-increment       │
│ exchange     │ VARCHAR(10)  │ NFO, BFO, CDS, MCX   │
│ symbol       │ VARCHAR(50)  │ Trading symbol       │
│ freeze_qty   │ INTEGER      │ Max order quantity   │
└──────────────┴──────────────┴──────────────────────┘
```

### Example Request

```json
// POST /admin/api/freeze
{
    "exchange": "NFO",
    "symbol": "NIFTY",
    "freeze_qty": 1800
}
```

### Common Freeze Quantities

| Symbol | Exchange | Freeze Qty |
|--------|----------|------------|
| NIFTY | NFO | 1800 |
| BANKNIFTY | NFO | 900 |
| FINNIFTY | NFO | 1800 |
| SENSEX | BFO | 1000 |

## Market Holidays Management

### Purpose
Maintain trading holidays calendar for all exchanges.

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/api/holidays?year=2024` | Get holidays for year |
| POST | `/admin/api/holidays` | Add new holiday |
| DELETE | `/admin/api/holidays/<id>` | Delete holiday |

### Database Schema

```
┌────────────────────────────────────────────────────┐
│               market_holidays table                 │
├──────────────────┬──────────────┬──────────────────┤
│ Column           │ Type         │ Description      │
├──────────────────┼──────────────┼──────────────────┤
│ id               │ INTEGER PK   │ Auto-increment   │
│ holiday_date     │ DATE         │ Holiday date     │
│ description      │ VARCHAR(255) │ Holiday name     │
│ holiday_type     │ VARCHAR(50)  │ Type of holiday  │
│ year             │ INTEGER      │ Year             │
└──────────────────┴──────────────┴──────────────────┘

┌────────────────────────────────────────────────────┐
│           market_holiday_exchanges table            │
├──────────────────┬──────────────┬──────────────────┤
│ Column           │ Type         │ Description      │
├──────────────────┼──────────────┼──────────────────┤
│ holiday_id       │ INTEGER FK   │ Holiday reference│
│ exchange_code    │ VARCHAR(10)  │ Exchange code    │
│ is_open          │ BOOLEAN      │ Exchange open?   │
└──────────────────┴──────────────┴──────────────────┘
```

### Holiday Types

| Type | Description |
|------|-------------|
| TRADING_HOLIDAY | Full market closure |
| SETTLEMENT_HOLIDAY | Settlement closed |
| SPECIAL_SESSION | Muhurat trading |

### Supported Exchanges

- NSE (National Stock Exchange)
- BSE (Bombay Stock Exchange)
- NFO (NSE F&O)
- BFO (BSE F&O)
- MCX (Multi Commodity Exchange)
- CDS (Currency Derivatives)
- BCD (BSE Currency Derivatives)

### Example Request

```json
// POST /admin/api/holidays
{
    "holiday_date": "2024-01-26",
    "description": "Republic Day",
    "holiday_type": "TRADING_HOLIDAY",
    "exchanges": ["NSE", "BSE", "NFO", "BFO", "MCX", "CDS"]
}
```

## Market Timings Configuration

### Purpose
Configure trading session timings for each exchange.

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/api/timings` | Get all timings |
| PUT | `/admin/api/timings/<exchange>` | Update timing |
| POST | `/admin/api/timings/check` | Check for date |

### Default Timings

| Exchange | Market Open | Market Close |
|----------|-------------|--------------|
| NSE | 09:15 | 15:30 |
| BSE | 09:15 | 15:30 |
| NFO | 09:15 | 15:30 |
| BFO | 09:15 | 15:30 |
| CDS | 09:00 | 17:00 |
| BCD | 09:00 | 17:00 |
| MCX | 09:00 | 23:55 |

### Example Request

```json
// PUT /admin/api/timings/NSE
{
    "start_time": "09:15",
    "end_time": "15:30"
}
```

## System Settings

### Analyzer Mode Toggle

```
GET  /settings/analyze-mode          → Get current mode
POST /settings/analyze-mode/live     → Switch to live
POST /settings/analyze-mode/analyze  → Switch to analyzer
```

### Settings Schema

```
┌────────────────────────────────────────────────────┐
│                  settings table                     │
├────────────────────┬──────────┬────────────────────┤
│ Column             │ Type     │ Description        │
├────────────────────┼──────────┼────────────────────┤
│ id                 │ INT PK   │ Single row (id=1)  │
│ analyze_mode       │ BOOLEAN  │ Live/Analyzer mode │
│ smtp_server        │ VARCHAR  │ SMTP server        │
│ smtp_port          │ INTEGER  │ SMTP port          │
│ smtp_password_enc  │ TEXT     │ Encrypted password │
│ security_404_threshold    │ INT │ 404 ban limit   │
│ security_api_threshold    │ INT │ API ban limit   │
│ security_ban_duration     │ INT │ Ban hours       │
└────────────────────┴──────────┴────────────────────┘
```

## Security Dashboard

### Access
```
/logs/security
```

### Features

```
┌─────────────────────────────────────────────────────────────────┐
│                    Security Dashboard                            │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  IP Bans                                                   │  │
│  │                                                            │  │
│  │  IP Address      │ Reason        │ Expires     │ Actions  │  │
│  │  192.168.1.100   │ 404 abuse     │ 24h         │ Unban    │  │
│  │  10.0.0.50       │ API brute     │ Permanent   │ Unban    │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Security Thresholds                                       │  │
│  │                                                            │  │
│  │  404 Errors:  20/day  → Auto-ban for 24 hours             │  │
│  │  API Abuse:   10/day  → Auto-ban for 48 hours             │  │
│  │  Repeat Offender: 3 bans → Permanent                       │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Security Tables

#### ip_bans
Stores banned IP addresses with expiry.

#### error_404_tracker
Tracks 404 errors per IP (threshold: 20/day).

#### invalid_api_key_tracker
Tracks invalid API attempts per IP (threshold: 10/day).

## Traffic Dashboard

### Access
```
/logs/traffic
```

### Features

- HTTP request logging
- Request/response metrics
- Error rate monitoring
- API endpoint statistics

## Latency Dashboard

### Access
```
/logs/latency
```

### Features

- Order execution latency
- Round-trip time (RTT)
- Percentile metrics (P50, P90, P95, P99)
- SLA compliance tracking

### SLA Thresholds

| Metric | Target |
|--------|--------|
| P50 | < 100ms |
| P90 | < 150ms |
| P99 | < 200ms |

## Access Control

### Session Validation

```python
@admin_bp.route('/api/freeze')
@check_session_validity
def get_freeze_quantities():
    # Only authenticated users can access
    pass
```

### Rate Limiting

| Endpoint | Limit |
|----------|-------|
| Default API | 50/second |
| CSV Upload | 10/minute |

## React Components

### File Structure

```
frontend/src/pages/admin/
├── AdminIndex.tsx      # Main dashboard
├── FreezeQty.tsx       # Freeze quantity UI
├── Holidays.tsx        # Holiday calendar
└── MarketTimings.tsx   # Market timings
```

### API Client

```typescript
// frontend/src/api/admin.ts

export const adminApi = {
  getFreezeQuantities: () => api.get('/admin/api/freeze'),
  addFreezeQty: (data) => api.post('/admin/api/freeze', data),
  updateFreezeQty: (id, data) => api.put(`/admin/api/freeze/${id}`, data),
  deleteFreezeQty: (id) => api.delete(`/admin/api/freeze/${id}`),
  uploadFreezeCSV: (file) => api.post('/admin/api/freeze/upload', file),

  getHolidays: (year) => api.get(`/admin/api/holidays?year=${year}`),
  addHoliday: (data) => api.post('/admin/api/holidays', data),
  deleteHoliday: (id) => api.delete(`/admin/api/holidays/${id}`),

  getTimings: () => api.get('/admin/api/timings'),
  updateTiming: (exchange, data) => api.put(`/admin/api/timings/${exchange}`, data)
};
```

## System Permissions

### Endpoint
```
GET /api/system
```

### Checks

| Path | Required Permission |
|------|---------------------|
| .env | 0o600 (rw-------) |
| encryption_keys/ | 0o700 (rwx------) |
| db/*.db | 0o600 (rw-------) |
| logs/ | 0o755 (rwxr-xr-x) |

## Key Files Reference

| File | Purpose |
|------|---------|
| `blueprints/admin.py` | Admin routes |
| `database/qty_freeze_db.py` | Freeze quantities |
| `database/market_calendar_db.py` | Holidays/timings |
| `database/settings_db.py` | Settings table |
| `database/traffic_db.py` | Security tables |
| `services/security.py` | Security service |
| `frontend/src/pages/admin/` | React components |
| `frontend/src/api/admin.ts` | API client |
