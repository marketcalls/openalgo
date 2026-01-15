# Centralized Logging System

## Overview

OpenAlgo implements a sophisticated multi-tier centralized logging system that provides comprehensive monitoring across five distinct areas:

1. **Application Logging** - Colored console output with sensitive data protection
2. **Traffic Logging** - HTTP request/response tracking with IP analytics
3. **Latency Monitoring** - Order execution performance with percentile analysis
4. **API Order Logging** - Complete audit trail of all trading operations
5. **Security Monitoring** - IP banning, 404 tracking, and API abuse detection

## Architecture

### Multi-Database Design

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Centralized Logging Architecture                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                     Application Layer                            │    │
│  │  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐       │    │
│  │  │  Flask Routes │  │   REST API    │  │   WebSocket   │       │    │
│  │  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘       │    │
│  │          │                  │                  │                │    │
│  │          └──────────────────┼──────────────────┘                │    │
│  │                             ▼                                    │    │
│  │                 ┌───────────────────────┐                       │    │
│  │                 │  utils/logging.py     │                       │    │
│  │                 │  - ColoredFormatter   │                       │    │
│  │                 │  - SensitiveDataFilter│                       │    │
│  │                 │  - TimedRotatingHandler│                      │    │
│  │                 └───────────────────────┘                       │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                     Database Layer (4 Databases)                 │    │
│  │                                                                  │    │
│  │  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐       │    │
│  │  │   logs.db     │  │  latency.db   │  │  openalgo.db  │       │    │
│  │  │  - TrafficLog │  │ - OrderLatency│  │  - OrderLog   │       │    │
│  │  │  - IPBan      │  │               │  │  - AnalyzerLog│       │    │
│  │  │  - Error404   │  │               │  │               │       │    │
│  │  │  - InvalidAPI │  │               │  │               │       │    │
│  │  └───────────────┘  └───────────────┘  └───────────────┘       │    │
│  │                                                                  │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                     File System                                  │    │
│  │                                                                  │    │
│  │  logs/                                                           │    │
│  │  ├── openalgo_2025-12-01.log                                    │    │
│  │  ├── openalgo_2025-11-30.log                                    │    │
│  │  └── ... (14-day retention)                                      │    │
│  │                                                                  │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Component Locations

| Component | File | Purpose |
|-----------|------|---------|
| Core Logging | `utils/logging.py` | ColoredFormatter, SensitiveDataFilter, file rotation |
| Traffic Logging | `database/traffic_db.py` | HTTP request tracking, IP analytics |
| Latency Monitoring | `database/latency_db.py` | Order execution performance |
| Latency Decorator | `utils/latency_monitor.py` | API endpoint timing |
| API Logging | `database/apilog_db.py` | Order audit trail |
| Security Middleware | `utils/security_middleware.py` | IP ban enforcement |

## Core Logging Infrastructure

### SensitiveDataFilter

Automatic redaction of sensitive information from all log output:

```python
# utils/logging.py
SENSITIVE_PATTERNS = [
    (r'(api[_-]?key[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(password[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(token[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(secret[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(authorization[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(Bearer\s+)[\w\-\.]+', r'\1[REDACTED]'),
]
```

**Protection Coverage:**
- API keys (all variations)
- Passwords (various formats)
- JWT/session/access tokens
- API secrets and client secrets
- Authorization headers
- Bearer tokens

### ColoredFormatter

Cross-platform colored console output with intelligent detection:

```python
LOG_COLORS = {
    'DEBUG': Fore.CYAN,
    'INFO': Fore.GREEN,
    'WARNING': Fore.YELLOW,
    'ERROR': Fore.RED,
    'CRITICAL': Fore.RED + Style.BRIGHT,
}

COMPONENT_COLORS = {
    'timestamp': Fore.BLUE,
    'module': Fore.MAGENTA,
    'reset': Style.RESET_ALL,
}
```

**Color Support Detection:**
- `FORCE_COLOR` environment variable
- `NO_COLOR` standard compliance
- Terminal capability detection (xterm, screen)
- CI environment detection (GitHub Actions, GitLab CI)
- Windows Terminal and VS Code support

### File Rotation

```python
TimedRotatingFileHandler(
    filename=log_file,
    when='midnight',        # Daily rotation
    interval=1,
    backupCount=14,         # 14-day retention
    encoding='utf-8'
)
```

### Configuration

```bash
# Environment variables
LOG_LEVEL=INFO              # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_TO_FILE=True            # Enable file logging
LOG_DIR=log                 # Directory for log files
LOG_RETENTION=14            # Days to retain
LOG_COLORS=True             # Enable colored output
LOG_FORMAT="[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
```

### Third-Party Logger Suppression

```python
# Noisy loggers suppressed to WARNING level
logging.getLogger('werkzeug').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('apscheduler').setLevel(logging.WARNING)
logging.getLogger('websockets').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('hpack').setLevel(logging.INFO)
```

## Traffic Logging System

### TrafficLog Model

```python
# database/traffic_db.py
class TrafficLog(LogBase):
    __tablename__ = 'traffic_logs'

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    client_ip = Column(String(50), nullable=False)
    method = Column(String(10), nullable=False)           # GET, POST, etc.
    path = Column(String(500), nullable=False)            # /api/v1/placeorder
    status_code = Column(Integer, nullable=False)         # 200, 403, 500
    duration_ms = Column(Float, nullable=False)           # Response time
    host = Column(String(500))
    error = Column(String(500))
    user_id = Column(Integer)

    # Performance indexes
    __table_args__ = (
        Index('idx_traffic_timestamp', 'timestamp'),
        Index('idx_traffic_client_ip', 'client_ip'),
        Index('idx_traffic_status_code', 'status_code'),
        Index('idx_traffic_user_id', 'user_id'),
        Index('idx_traffic_ip_timestamp', 'client_ip', 'timestamp'),
    )
```

### Capabilities

**Request Logging:**
- Client IP (with proxy support)
- HTTP method and path
- Status code and response time
- Host header and errors
- User ID association

**Statistics:**
```python
TrafficLog.get_stats()
# Returns:
{
    'total_requests': 15234,
    'error_requests': 127,
    'avg_duration': 45.67  # ms
}
```

## Latency Monitoring System

### OrderLatency Model

```python
# database/latency_db.py
class OrderLatency(LatencyBase):
    __tablename__ = 'order_latency'

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    order_id = Column(String(100), nullable=False)
    user_id = Column(Integer)
    broker = Column(String(50))                    # zerodha, angel, etc.
    symbol = Column(String(50))
    order_type = Column(String(20))                # PLACE, SMART, CANCEL, etc.

    # Round-trip time (comparable to Postman)
    rtt_ms = Column(Float)

    # Processing overhead breakdown
    validation_latency_ms = Column(Float)          # Pre-request processing
    response_latency_ms = Column(Float)            # Post-response processing
    overhead_ms = Column(Float)                    # Total overhead
    total_latency_ms = Column(Float, nullable=False)

    # Request/response details
    request_body = Column(JSON)
    response_body = Column(JSON)
    status = Column(String(20))                    # SUCCESS, FAILED
    error = Column(String(500))
```

### LatencyTracker Class

```python
# utils/latency_monitor.py
class LatencyTracker:
    """Tracks latencies across different stages of order execution"""

    def __init__(self):
        self.start_time = time.time()
        self.stage_times = {}
        self.request_start = None
        self.request_end = None

    def start_stage(self, stage_name):
        """Start timing a stage (validation, broker_request, broker_response)"""

    def end_stage(self):
        """End timing the current stage"""

    def get_rtt(self):
        """Get round-trip time (comparable to Postman/Bruno)"""

    def get_overhead(self):
        """Get total platform overhead"""
```

### API Endpoint Tracking

```python
# Decorator for API latency tracking
@track_latency('PLACE')
def post(self):
    """Place order endpoint"""
    pass

# API types tracked:
ORDER_TYPES = {
    'PLACE', 'SMART', 'MODIFY', 'CANCEL', 'CLOSE',
    'CANCEL_ALL', 'BASKET', 'SPLIT', 'OPTIONS', 'OPTIONS_MULTI'
}

DATA_TYPES = {
    'QUOTES', 'HISTORY', 'DEPTH', 'INTERVALS', 'FUNDS',
    'ORDERBOOK', 'TRADEBOOK', 'POSITIONBOOK', 'HOLDINGS',
    'STATUS', 'POSITION', 'INSTRUMENTS', 'SEARCH', 'SYMBOL',
    'EXPIRY', 'MARGIN', 'GREEKS', 'OPTION_SYMBOL', 'SYNTHETIC',
    'TICKER', 'PING', 'ANALYZER'
}
```

### Data Retention Policy

```python
# Order logs: Kept forever
ORDER_TYPES = {'PLACE', 'SMART', 'MODIFY', 'CANCEL', ...}

# Data logs: Auto-purged after 7 days
purge_old_data_logs(days=7)
```

### Latency Statistics

```python
OrderLatency.get_latency_stats()
# Returns:
{
    'total_orders': 5432,
    'failed_orders': 23,
    'success_rate': 99.58,
    'avg_rtt': 45.2,           # ms
    'avg_overhead': 12.3,       # ms
    'avg_total': 57.5,          # ms

    # Percentiles (using NumPy)
    'p50_total': 42.0,
    'p90_total': 78.5,
    'p95_total': 95.2,
    'p99_total': 145.8,

    # SLA metrics
    'sla_100ms': 85.2,          # % under 100ms
    'sla_150ms': 94.7,          # % under 150ms
    'sla_200ms': 98.1,          # % under 200ms

    # Per-broker breakdown
    'broker_stats': {
        'zerodha': {
            'total_orders': 2341,
            'avg_rtt': 42.1,
            'p50_total': 38.5,
            'p99_total': 125.3,
            'sla_150ms': 96.2
        },
        'angel': {
            'total_orders': 1876,
            'avg_rtt': 48.7,
            ...
        }
    }
}
```

## Security Monitoring

### IP Ban System

```python
# database/traffic_db.py
class IPBan(LogBase):
    __tablename__ = 'ip_bans'

    id = Column(Integer, primary_key=True)
    ip_address = Column(String(50), unique=True, nullable=False, index=True)
    ban_reason = Column(String(200))
    ban_count = Column(Integer, default=1)         # Repeat offense counter
    banned_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True))   # NULL = permanent
    is_permanent = Column(Boolean, default=False)
    created_by = Column(String(50), default='system')  # 'system' or 'manual'
```

**Capabilities:**
- Temporary bans (configurable duration)
- Permanent bans (auto-escalation after repeat offenses)
- Ban count tracking for repeat offenders
- Automatic expiry cleanup
- Localhost protection (127.0.0.1 never banned)

```python
# Usage
IPBan.is_ip_banned(ip_address)          # Check ban status
IPBan.ban_ip(ip, reason, duration_hours=24, permanent=False)
IPBan.unban_ip(ip_address)
IPBan.get_all_bans()                    # List active bans
```

### 404 Error Tracking (Bot Detection)

```python
class Error404Tracker(LogBase):
    __tablename__ = 'error_404_tracker'

    id = Column(Integer, primary_key=True)
    ip_address = Column(String(50), nullable=False, index=True)
    error_count = Column(Integer, default=1)
    first_error_at = Column(DateTime(timezone=True))
    last_error_at = Column(DateTime(timezone=True))
    paths_attempted = Column(Text)      # JSON array of attempted paths

    __table_args__ = (
        Index('idx_404_error_count', 'error_count'),
        Index('idx_404_first_error_at', 'first_error_at'),
    )
```

**Capabilities:**
- Track 404 errors per IP (24-hour window)
- Store last 50 attempted paths (JSON)
- Configurable threshold for suspicious activity
- Auto-cleanup of old entries
- Suspicious IP detection

```python
Error404Tracker.track_404(ip_address, path)
Error404Tracker.get_suspicious_ips(min_errors=5)
```

### Invalid API Key Tracking

```python
class InvalidAPIKeyTracker(LogBase):
    __tablename__ = 'invalid_api_key_tracker'

    id = Column(Integer, primary_key=True)
    ip_address = Column(String(50), nullable=False, index=True)
    attempt_count = Column(Integer, default=1)
    first_attempt_at = Column(DateTime(timezone=True))
    last_attempt_at = Column(DateTime(timezone=True))
    api_keys_tried = Column(Text)       # JSON array of hashed keys

    __table_args__ = (
        Index('idx_api_tracker_attempt_count', 'attempt_count'),
        Index('idx_api_tracker_first_attempt_at', 'first_attempt_at'),
    )
```

**Capabilities:**
- Track invalid API key attempts per IP
- Store last 20 attempted keys (hashed)
- 24-hour tracking window with auto-reset
- Suspicious user detection

```python
InvalidAPIKeyTracker.track_invalid_api_key(ip_address, api_key_hash)
InvalidAPIKeyTracker.get_suspicious_api_users(min_attempts=3)
```

### Security Middleware

```python
# utils/security_middleware.py
class SecurityMiddleware:
    """WSGI middleware to check for banned IPs"""

    def __call__(self, environ, start_response):
        client_ip = get_real_ip_from_environ(environ)

        if IPBan.is_ip_banned(client_ip):
            # Return 403 Forbidden
            return [b'Access Denied: Your IP has been banned']

        return self.app(environ, start_response)
```

## API Order Logging

### OrderLog Model

```python
# database/apilog_db.py
class OrderLog(Base):
    __tablename__ = 'order_logs'

    id = Column(Integer, primary_key=True)
    api_type = Column(Text, nullable=False)        # placeorder, smartorder, etc.
    request_data = Column(Text, nullable=False)    # JSON serialized
    response_data = Column(Text, nullable=False)   # JSON serialized
    created_at = Column(DateTime(timezone=True), default=func.now())
```

### Async Logging

```python
# ThreadPoolExecutor for non-blocking logging
executor = ThreadPoolExecutor(10)

def async_log_order(api_type, request_data, response_data):
    """Asynchronously log order to database"""
    # Serialize JSON data
    request_json = json.dumps(request_data)
    response_json = json.dumps(response_data)

    # Store with IST timestamp
    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)

    order_log = OrderLog(
        api_type=api_type,
        request_data=request_json,
        response_data=response_json,
        created_at=now_ist
    )
    db_session.add(order_log)
    db_session.commit()

# Usage in services
executor.submit(async_log_order, 'placeorder', request_data, response_data)
```

## Logging Restrictions & Protections

### What is NOT Logged

1. **API Keys** - Redacted to `[REDACTED]` in all logs
2. **Passwords** - Never stored in plain text
3. **Broker Auth Tokens** - Filtered from log output
4. **Request/Response Bodies** - Not stored in latency logs (space optimization)
5. **Full API Key Hashes** - Only partial hashes stored for abuse detection

### What is Protected

| Data Type | Protection Method |
|-----------|-------------------|
| API Keys | SensitiveDataFilter regex redaction |
| Passwords | SensitiveDataFilter + never logged |
| Tokens | SensitiveDataFilter regex redaction |
| Client IPs | Stored but subject to retention |
| Order Data | Logged to separate DB, IST timestamps |
| Invalid Keys | Hashed before storage |

### Configurable Thresholds

```python
# From database/settings_db.py - Security Settings
security_settings = {
    '404_threshold': 20,           # 404s before flagged
    '404_ban_duration': 24,        # Hours to ban
    'api_threshold': 10,           # Invalid API attempts before flagged
    'api_ban_duration': 48,        # Hours to ban
    'repeat_offender_limit': 3     # Bans before permanent
}
```

## Dashboard Integration

### Traffic Dashboard (`/traffic`)

- Real-time traffic statistics
- Request count by status code
- Average response times
- Per-user traffic breakdown

### Latency Dashboard (`/latency`)

- Order execution statistics
- Percentile graphs (P50, P90, P95, P99)
- SLA compliance metrics
- Per-broker performance comparison
- Historical trend analysis

### Security Dashboard (`/security`)

- Active IP bans list
- Suspicious 404 activity
- Invalid API key attempts
- Manual ban/unban controls

## Performance Considerations

### Database Optimization

- **Separate Databases**: Traffic, latency, and main DB isolated
- **Connection Pooling**: PostgreSQL uses pool_size=50, max_overflow=100
- **SQLite NullPool**: Prevents connection exhaustion
- **Indexed Queries**: All common query patterns indexed

### Async Operations

- **ThreadPoolExecutor**: 10 workers for async logging
- **Non-blocking Writes**: Order execution not delayed by logging
- **Batch Cleanup**: Old entries purged periodically

### Memory Management

- **Scoped Sessions**: Proper session cleanup after requests
- **Limited Storage**: Only last 50 paths/20 keys stored
- **Auto-purge**: Data logs cleaned after 7 days

## Best Practices

### For Developers

1. Always use `get_logger(__name__)` for module loggers
2. Use appropriate log levels (DEBUG for development, INFO for production)
3. Never log sensitive data directly (use parameterized logging)
4. Use `logger.exception()` for stack traces in error handlers

### For Operations

1. Monitor P99 latency for broker performance
2. Review security dashboard daily for suspicious activity
3. Set up alerts for error rate spikes
4. Rotate logs before disk fills (14-day default)

### For Security

1. Review 404 tracker for scanning activity
2. Monitor invalid API key patterns
3. Periodically audit permanent bans
4. Keep security thresholds appropriate for traffic volume

## Future Enhancements

### Planned Features

1. **Structured Logging**: JSON format for log aggregation
2. **Remote Logging**: Integration with ELK/CloudWatch
3. **Prometheus Metrics**: Export latency metrics
4. **Alert Integration**: Automatic alerting on error patterns
5. **Log Analytics**: ML-based anomaly detection

---

**Document Version**: 1.1.0
**Last Updated**: December 2025
**Status**: Production Ready
