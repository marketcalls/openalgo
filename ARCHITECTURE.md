# OpenAlgo Architecture Documentation

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture Diagram](#architecture-diagram)
3. [Core Components](#core-components)
4. [Data Flow](#data-flow)
5. [Security Architecture](#security-architecture)
6. [Database Schema](#database-schema)
7. [API Architecture](#api-architecture)
8. [WebSocket Architecture](#websocket-architecture)
9. [Broker Integration Pattern](#broker-integration-pattern)
10. [Deployment Architecture](#deployment-architecture)
11. [Scalability Considerations](#scalability-considerations)

---

## System Overview

OpenAlgo is a broker-agnostic algorithmic trading platform built with Flask (Python) that acts as a bridge between trading platforms (Amibroker, TradingView, Python scripts, etc.) and broker APIs.

### Key Characteristics
- **Language**: Python 3.12+
- **Framework**: Flask 3.0.3
- **Architecture Pattern**: Modular Monolith with Service-Oriented Architecture
- **Database**: SQLite (default) / PostgreSQL (production)
- **Real-time Communication**: WebSocket (via python-socketio) + ZeroMQ
- **Deployment**: Docker + Docker Compose

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Client Applications                          │
│  ┌──────────┐  ┌───────────┐  ┌────────┐  ┌──────┐  ┌──────────┐  │
│  │Amibroker │  │TradingView│  │ Python │  │Excel │  │ Chartink │  │
│  └────┬─────┘  └─────┬─────┘  └───┬────┘  └──┬───┘  └────┬─────┘  │
└───────┼──────────────┼────────────┼──────────┼───────────┼─────────┘
        │              │            │          │           │
        │         HTTP/HTTPS + WebSocket (port 8765)       │
        │              │            │          │           │
┌───────┼──────────────┼────────────┼──────────┼───────────┼─────────┐
│       │              │            │          │           │         │
│   ┌───▼──────────────▼────────────▼──────────▼───────────▼─────┐   │
│   │              Rate Limiter & CORS Handler                    │   │
│   └────────────────────────────┬────────────────────────────────┘   │
│                                │                                     │
│   ┌────────────────────────────▼────────────────────────────────┐   │
│   │            Content Security Policy Middleware               │   │
│   └────────────────────────────┬────────────────────────────────┘   │
│                                │                                     │
│   ┌────────────────────────────▼────────────────────────────────┐   │
│   │              Security Middleware (IP Ban Check)             │   │
│   └────────────────────────────┬────────────────────────────────┘   │
│                                │                                     │
│   ┌────────────────────────────▼────────────────────────────────┐   │
│   │               Traffic Logger (API Monitoring)               │   │
│   └────────────────────────────┬────────────────────────────────┘   │
│                                │                                     │
│                    ┌───────────▼──────────┐                          │
│                    │   Flask Application  │                          │
│                    │     (app.py)         │                          │
│                    └───────────┬──────────┘                          │
│                                │                                     │
│              ┌─────────────────┼─────────────────┐                   │
│              │                 │                 │                   │
│    ┌─────────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐            │
│    │   Blueprints   │  │  RESTx API  │  │  WebSocket  │            │
│    │   (23 modules) │  │   (v1)      │  │   Proxy     │            │
│    └────────┬───────┘  └──────┬──────┘  └──────┬──────┘            │
│             │                 │                 │                   │
│             └────────┬────────┴─────────────────┘                   │
│                      │                                              │
│            ┌─────────▼──────────┐                                   │
│            │  Service Layer     │                                   │
│            │  (48+ services)    │                                   │
│            └─────────┬──────────┘                                   │
│                      │                                              │
│         ┌────────────┼────────────┐                                 │
│         │            │            │                                 │
│  ┌──────▼─────┐ ┌───▼────┐ ┌────▼────────┐                        │
│  │  Database  │ │ Broker │ │  External   │                        │
│  │   Layer    │ │ APIs   │ │  Services   │                        │
│  │(11 modules)│ │ (27+)  │ │ (Telegram)  │                        │
│  └──────┬─────┘ └───┬────┘ └─────────────┘                        │
│         │           │                                              │
└─────────┼───────────┼──────────────────────────────────────────────┘
          │           │
     ┌────▼───┐  ┌────▼──────────────┐
     │ SQLite │  │ Broker WebSockets │
     │   or   │  │  (via ZeroMQ)     │
     │  PG    │  └───────────────────┘
     └────────┘
```

---

## Core Components

### 1. Application Layer (`app.py`)
**Responsibilities:**
- Flask application initialization
- Blueprint registration (23 blueprints)
- Middleware configuration (CSRF, CORS, CSP, Rate Limiting)
- Security middleware initialization
- Database initialization (11 database modules)
- Session management with IST timezone (expires at 3:30 AM)
- Error handlers (404, 500, 403, 429)
- WebSocket proxy server integration

**Key Features:**
- Factory pattern for app creation
- Parallel database initialization
- Dynamic cookie security based on HTTPS
- CSRF protection with webhook exemptions
- Auto-start Telegram bot on startup

### 2. Blueprint Layer (23 Blueprints)
Modular route handlers organized by functionality:

| Blueprint | Purpose |
|-----------|---------|
| `auth` | Authentication & login |
| `dashboard` | Main dashboard UI |
| `orders` | Order management UI |
| `search` | Symbol search |
| `apikey` | API key management |
| `log` | Logging UI |
| `tv_json` | TradingView webhook handler |
| `gc_json` | Google Sheets webhook handler |
| `platforms` | Platform integrations |
| `brlogin` | Broker login & OAuth |
| `core` | Core functionality |
| `analyzer` | Trade analyzer & paper trading |
| `settings` | Application settings |
| `chartink` | Chartink integration |
| `traffic` | Traffic monitoring |
| `latency` | Latency monitoring |
| `strategy` | Strategy management |
| `master_contract_status` | Symbol contract status |
| `websocket_example` | WebSocket examples |
| `pnltracker` | PnL tracking |
| `python_strategy` | Python strategy execution |
| `telegram` | Telegram bot management |
| `security` | Security settings |
| `sandbox` | Paper trading sandbox |
| `health` | Health check endpoints |

### 3. Service Layer (48+ Services)
Business logic and orchestration:

**Order Services:**
- `place_order_service.py` - Order placement logic
- `modify_order_service.py` - Order modification
- `cancel_order_service.py` - Order cancellation
- `split_order_service.py` - Large order splitting
- `basket_order_service.py` - Basket order handling
- `smart_order_service.py` - Smart order routing

**Market Data Services:**
- `market_data_service.py` - Market data aggregation
- `quote_service.py` - Real-time quotes
- `history_service.py` - Historical data

**WebSocket Services:**
- `websocket_service.py` - WebSocket management
- `websocket_adapter.py` - Broker-specific adapters

**External Integration Services:**
- `telegram_bot_service.py` - Telegram bot
- `telegram_alert_service.py` - Alert notifications
- `chartink_service.py` - Chartink integration

**Analysis Services:**
- `analyzer_service.py` - Trade analysis
- `latency_monitor.py` - Performance monitoring
- `traffic_logger.py` - Request logging

### 4. Database Layer (11 Database Modules)

| Module | Purpose |
|--------|---------|
| `auth_db.py` | User authentication, token encryption |
| `user_db.py` | User management |
| `apilog_db.py` | API request logs |
| `traffic_db.py` | Traffic monitoring, IP bans, 404 tracking |
| `latency_db.py` | Performance metrics |
| `analyzer_db.py` | Trade analysis data |
| `settings_db.py` | Application settings |
| `telegram_db.py` | Telegram bot config |
| `chartink_db.py` | Chartink webhooks |
| `strategy_db.py` | Strategy definitions |
| `sandbox_db.py` | Paper trading data |

### 5. Broker Integration Layer (27+ Brokers)
Each broker integration follows a standard pattern:

```
broker/
├── <broker_name>/
│   ├── api/
│   │   ├── auth_api.py        # Login & session management
│   │   ├── order_api.py       # Order operations
│   │   ├── funds.py           # Account funds
│   │   └── data.py            # Market data
│   ├── mapping/
│   │   └── transform_data.py  # Symbol mapping
│   └── websocket/
│       └── broker_adapter.py  # WebSocket streaming
```

---

## Data Flow

### 1. Order Placement Flow

```
Client (TradingView/Amibroker)
    │
    │ POST /api/v1/placeorder
    │ Headers: { apikey: "xxx" }
    │
    ▼
Rate Limiter (10 req/sec)
    │
    ▼
Security Middleware (IP ban check)
    │
    ▼
Traffic Logger (log request)
    │
    ▼
API Key Validation (auth_db.py)
    │
    ▼
Request Schema Validation (Marshmallow)
    │
    ▼
Place Order Service
    │
    ├──► Symbol Transformation (broker-specific format)
    │
    ├──► Broker API Call (order_api.py)
    │
    ├──► Latency Recording (latency_db.py)
    │
    └──► API Log (apilog_db.py)
    │
    ▼
Response (JSON)
```

### 2. Real-time Market Data Flow

```
Broker WebSocket (port varies by broker)
    │
    ▼
Broker Adapter (transforms to OpenAlgo format)
    │
    ▼
ZeroMQ Publisher (message bus)
    │
    ▼
ZeroMQ Subscriber (WebSocket Proxy)
    │
    ▼
WebSocket Proxy Server (port 8765)
    │
    ▼
Authenticated Clients (browser, apps)
```

### 3. Authentication Flow

```
User Login
    │
    │ POST /auth/login
    │ Body: { username, password, broker, totp }
    │
    ▼
CSRF Token Validation
    │
    ▼
Rate Limiter (5/min, 25/hour)
    │
    ▼
Password Verification (Argon2 hashing)
    │
    ▼
TOTP Verification (if enabled)
    │
    ▼
Broker Authentication
    │
    ├──► Broker API Login
    │
    ├──► Token Encryption (Fernet)
    │
    └──► Token Storage (encrypted in DB)
    │
    ▼
Session Creation (expires 3:30 AM IST)
    │
    ▼
Redirect to Dashboard
```

---

## Security Architecture

### 1. Multi-Layer Security

```
┌─────────────────────────────────────────────┐
│  Layer 1: Network Security                  │
│  - Rate Limiting (Flask-Limiter)            │
│  - IP Banning (security_middleware)         │
│  - CORS Policy (cors.py)                    │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│  Layer 2: Application Security              │
│  - Content Security Policy (csp.py)         │
│  - CSRF Protection (Flask-WTF)              │
│  - Secure Headers (X-Frame-Options, etc.)   │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│  Layer 3: Authentication & Authorization    │
│  - API Key Authentication                   │
│  - Session Management                       │
│  - TOTP (Two-Factor Authentication)         │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│  Layer 4: Data Security                     │
│  - Argon2 Password Hashing                  │
│  - Fernet Token Encryption                  │
│  - API Key Pepper                           │
│  - Log Sanitization                         │
└─────────────────────────────────────────────┘
```

### 2. Encryption Details

**Password Hashing:**
```python
# Argon2id (winner of Password Hashing Competition)
# Time cost: 2
# Memory cost: 102400 KB
# Parallelism: 8
# Salt: 16 bytes (auto-generated)
```

**Token Encryption:**
```python
# Fernet (symmetric encryption using AES-128)
# Key derivation: PBKDF2
# Iterations: 100,000
# Salt: Per-user basis
```

**API Key Security:**
```python
# Storage: Argon2 hash + Fernet encryption
# Pepper: Additional secret layer
# Cache: SHA256 key-based caching with TTL
```

### 3. Rate Limiting Strategy

| Endpoint Type | Limit | Window |
|---------------|-------|--------|
| Login | 5 requests | per minute |
| Login | 25 requests | per hour |
| API General | 50 requests | per second |
| Orders | 10 requests | per second |
| Smart Orders | 2 requests | per second |
| Webhooks | 100 requests | per minute |

**Algorithm:** Moving Window (more accurate than fixed window)

---

## Database Schema

### Core Tables

```sql
-- User Authentication
CREATE TABLE auth (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,  -- Argon2
    broker TEXT NOT NULL,
    api_key TEXT NOT NULL,  -- Hashed + Encrypted
    totp_secret TEXT,  -- TOTP for 2FA
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
);

-- API Keys
CREATE TABLE api_keys (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    key_hash TEXT NOT NULL,  -- Argon2 hash
    key_encrypted TEXT NOT NULL,  -- Fernet encryption
    name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used TIMESTAMP,
    is_active BOOLEAN DEFAULT 1,
    FOREIGN KEY (user_id) REFERENCES auth(id)
);

-- API Logs
CREATE TABLE api_logs (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    endpoint TEXT NOT NULL,
    method TEXT NOT NULL,
    user_id INTEGER,
    broker TEXT,
    status_code INTEGER,
    latency_ms REAL,
    ip_address TEXT,
    request_body TEXT,  -- Sanitized
    response_body TEXT,  -- Sanitized
    FOREIGN KEY (user_id) REFERENCES auth(id)
);

-- Traffic Monitoring
CREATE TABLE traffic_logs (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    method TEXT NOT NULL,
    status_code INTEGER,
    user_agent TEXT,
    referer TEXT
);

-- IP Bans
CREATE TABLE banned_ips (
    id INTEGER PRIMARY KEY,
    ip_address TEXT UNIQUE NOT NULL,
    reason TEXT,
    banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    banned_until TIMESTAMP,
    is_permanent BOOLEAN DEFAULT 0
);

-- 404 Tracking (reconnaissance detection)
CREATE TABLE error_404_logs (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address TEXT NOT NULL,
    path TEXT NOT NULL,
    count INTEGER DEFAULT 1
);

-- Latency Monitoring
CREATE TABLE latency_logs (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    endpoint TEXT NOT NULL,
    broker TEXT,
    operation TEXT,  -- place_order, get_quote, etc.
    latency_ms REAL NOT NULL,
    success BOOLEAN DEFAULT 1
);
```

### Connection Pooling Configuration

**PostgreSQL:**
```python
pool_size = 50  # Base connections
max_overflow = 100  # Additional connections
pool_timeout = 30  # Wait timeout
pool_recycle = 3600  # Recycle after 1 hour
```

**SQLite:**
```python
poolclass = NullPool  # Prevents connection exhaustion
check_same_thread = False  # Allow multi-threading
```

---

## API Architecture

### RESTful API Design

**Base Path:** `/api/v1/`

**Authentication:** API Key in header or query parameter
```
Authorization: Bearer <api_key>
or
?apikey=<api_key>
```

**Response Format:**
```json
{
    "status": "success|error",
    "data": {},
    "message": "Human-readable message",
    "timestamp": "2024-01-01T00:00:00Z"
}
```

### API Categories

**1. Order Management**
```
POST   /api/v1/placeorder       - Place regular order
POST   /api/v1/placesmartorder  - Smart order with position sizing
POST   /api/v1/basketorder      - Multiple orders in one request
POST   /api/v1/splitorder       - Split large order into chunks
PUT    /api/v1/modifyorder      - Modify existing order
DELETE /api/v1/cancelorder      - Cancel specific order
DELETE /api/v1/cancelallorder   - Cancel all pending orders
POST   /api/v1/closeposition    - Close open position
```

**2. Account & Portfolio**
```
GET /api/v1/funds          - Get account balance & margins
GET /api/v1/orderbook      - All orders for the day
GET /api/v1/tradebook      - Executed trades
GET /api/v1/positionbook   - Current positions
GET /api/v1/holdings       - Demat holdings
GET /api/v1/openposition   - Specific position details
GET /api/v1/orderstatus    - Real-time order status
```

**3. Market Data**
```
GET /api/v1/quotes         - Real-time quotes
GET /api/v1/history        - Historical OHLC data
GET /api/v1/depth          - Market depth/order book
WS  /api/v1/ticker         - Live price stream
```

**4. Utility**
```
GET /api/v1/search         - Search symbols
GET /api/v1/symbol         - Symbol details
GET /api/v1/expiry         - Option expiry dates
GET /api/v1/intervals      - Supported time intervals
GET /api/v1/ping           - Test connectivity
```

### API Documentation

**Swagger UI:** Available at `/api/v1/`
**Auto-generated** from Flask-RESTX decorators

---

## WebSocket Architecture

### 1. Unified WebSocket Proxy Server

**Port:** 8765
**Protocol:** WebSocket + ZeroMQ
**Purpose:** Centralized hub for real-time market data

### 2. Architecture Components

```
┌────────────────────────────────────────────┐
│  Broker WebSocket APIs (various ports)     │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐      │
│  │ Zerodha │ │  Angel  │ │  Dhan   │ ...  │
│  └────┬────┘ └────┬────┘ └────┬────┘      │
└───────┼───────────┼───────────┼────────────┘
        │           │           │
        ▼           ▼           ▼
┌────────────────────────────────────────────┐
│  Broker-Specific Adapters                  │
│  (Transform to unified OpenAlgo format)    │
└────────────────┬───────────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────────┐
│  ZeroMQ Publisher (Message Bus)            │
│  - Dynamic port binding                    │
│  - Pub-Sub pattern                         │
└────────────────┬───────────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────────┐
│  ZeroMQ Subscriber (WebSocket Proxy)       │
│  - Receives from all broker adapters       │
│  - Routes to authenticated clients         │
└────────────────┬───────────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────────┐
│  WebSocket Server (port 8765)              │
│  - Client authentication                   │
│  - Subscription management                 │
│  - Auto-reconnection support               │
└────────────────┬───────────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────────┐
│  Connected Clients (browsers, apps)        │
└────────────────────────────────────────────┘
```

### 3. Message Formats

**Subscription Request:**
```json
{
    "action": "subscribe",
    "mode": "ltp|quote|depth",
    "symbols": ["RELIANCE-EQ", "TCS-EQ"]
}
```

**Market Data Response:**
```json
{
    "type": "tick",
    "mode": "ltp",
    "symbol": "RELIANCE-EQ",
    "ltp": 2450.50,
    "timestamp": "2024-01-01T09:30:00Z"
}
```

### 4. Subscription Modes

| Mode | Data Included |
|------|---------------|
| `ltp` | Last traded price only |
| `quote` | OHLC, LTP, volume, change% |
| `depth` | Full market depth (5/20/30 levels) |

---

## Broker Integration Pattern

### Standard Integration Structure

Every broker integration must implement:

1. **Authentication API** (`auth_api.py`)
   - `login(credentials)` - Authenticate user
   - `refresh_token()` - Refresh access token
   - `logout()` - End session

2. **Order API** (`order_api.py`)
   - `place_order(params)` - Place order
   - `modify_order(params)` - Modify order
   - `cancel_order(order_id)` - Cancel order
   - `get_order_book()` - Fetch orders
   - `get_trade_book()` - Fetch trades
   - `get_positions()` - Fetch positions

3. **Funds API** (`funds.py`)
   - `get_funds()` - Get account balance
   - `get_margins()` - Get margin details

4. **Data API** (`data.py`)
   - `get_quotes(symbols)` - Realtime quotes
   - `get_history(symbol, interval, from, to)` - Historical data
   - `get_depth(symbol)` - Market depth
   - `search_symbols(query)` - Symbol search

5. **Symbol Mapping** (`transform_data.py`)
   - `to_broker_symbol(openalgo_symbol)` - Convert to broker format
   - `to_openalgo_symbol(broker_symbol)` - Convert to OpenAlgo format

6. **WebSocket Adapter** (`broker_adapter.py`)
   - `connect()` - Establish WebSocket connection
   - `subscribe(symbols, mode)` - Subscribe to symbols
   - `unsubscribe(symbols)` - Unsubscribe
   - `on_message(callback)` - Handle incoming data

### Symbol Format Standardization

**OpenAlgo Format:** `SYMBOL-EXCHANGE`
Examples:
- `RELIANCE-EQ` (Equity)
- `NIFTY24JAN21000CE` (Options)
- `CRUDEOIL24JANFUT` (Futures)

Each broker adapter transforms to/from broker-specific formats.

---

## Deployment Architecture

### Docker Deployment

```yaml
# docker-compose.yaml
services:
  openalgo:
    build: .
    ports:
      - "${PORT:-5000}:5000"
      - "${WEBSOCKET_PORT:-8765}:8765"
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./strategies:/app/strategies
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - BROKER=${BROKER}
    restart: unless-stopped
```

### Production Recommendations

**Web Server:** Gunicorn (4-8 workers) + Nginx
**Database:** PostgreSQL 14+
**Cache:** Redis 7+ (for sessions, rate limiting)
**Load Balancer:** Nginx / HAProxy
**Monitoring:** Prometheus + Grafana
**Logging:** ELK Stack / Loki

### Minimum Hardware Requirements

- **CPU:** 1 vCPU (2+ recommended)
- **RAM:** 2GB (or 0.5GB + 2GB swap)
- **Disk:** 1GB minimum
- **Network:** Stable internet connection

---

## Scalability Considerations

### Current Limitations (Single Instance)

1. **SQLite Database** - Not suitable for multi-instance deployment
2. **Memory-based Rate Limiting** - Doesn't scale across instances
3. **In-memory Sessions** - Lost on restart
4. **No Load Balancing** - Single point of failure

### Scaling to Multi-Instance

**Required Changes:**

1. **Database Migration**
   ```
   SQLite → PostgreSQL
   - Enable connection pooling
   - Use read replicas for queries
   ```

2. **Cache Layer**
   ```
   Add Redis for:
   - Session storage
   - Distributed rate limiting
   - API response caching
   - Broker token caching
   ```

3. **Load Balancing**
   ```
   Nginx/HAProxy → [OpenAlgo Instance 1]
                 → [OpenAlgo Instance 2]
                 → [OpenAlgo Instance N]
   ```

4. **WebSocket Scaling**
   ```
   Use Redis Pub/Sub for WebSocket message distribution:
   Broker Adapters → Redis Pub/Sub → WebSocket Instances
   ```

5. **Shared File Storage**
   ```
   NFS / S3 for:
   - Strategy files
   - Logs (or use centralized logging)
   ```

### Horizontal Scaling Architecture

```
                      ┌───────────┐
                      │    CDN    │
                      └─────┬─────┘
                            │
                      ┌─────▼─────┐
                      │  Nginx    │
                      │  (Load    │
                      │  Balancer)│
                      └─────┬─────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
   ┌────▼────┐         ┌────▼────┐        ┌────▼────┐
   │OpenAlgo │         │OpenAlgo │        │OpenAlgo │
   │Instance1│         │Instance2│        │Instance3│
   └────┬────┘         └────┬────┘        └────┬────┘
        │                   │                   │
        └───────────────────┼───────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
   ┌────▼────┐         ┌────▼────┐        ┌────▼────┐
   │  Redis  │         │PostgreSQL│       │  Redis  │
   │ (Cache) │         │   (DB)   │       │(Pub/Sub)│
   └─────────┘         └──────────┘       └─────────┘
```

---

## Monitoring & Observability

### Built-in Monitoring

1. **Latency Monitor** (`/latency`)
   - Track order execution time
   - Per-broker performance
   - Success/failure rates

2. **Traffic Monitor** (`/traffic`)
   - API request analytics
   - Endpoint-specific metrics
   - Error rate tracking
   - IP-based tracking

3. **PnL Tracker** (`/pnl`)
   - Real-time profit/loss
   - Intraday PnL curve
   - Maximum drawdown
   - TradingView charts

### Health Check Endpoints

- `GET /health/` - Basic health status
- `GET /health/ready` - Readiness check (DB, env vars)
- `GET /health/live` - Liveness probe
- `GET /health/startup` - Startup completion check
- `GET /health/metrics` - Basic metrics (CPU, memory)

### Recommended External Monitoring

**Metrics Collection:**
```python
# Add Prometheus exporter
from prometheus_flask_exporter import PrometheusMetrics
metrics = PrometheusMetrics(app)
```

**Distributed Tracing:**
```python
# Add OpenTelemetry
from opentelemetry import trace
from opentelemetry.exporter.jaeger import JaegerExporter
```

**Structured Logging:**
```python
# Convert to JSON logging
import logging_json
logger = logging_json.getLogger()
```

---

## Security Best Practices

### Current Security Measures ✅

1. **Authentication:** Argon2 password hashing
2. **Encryption:** Fernet token encryption
3. **CSRF:** Flask-WTF protection
4. **CSP:** Content Security Policy headers
5. **Rate Limiting:** Moving-window algorithm
6. **IP Banning:** Automatic reconnaissance detection
7. **Log Sanitization:** Sensitive data filtering
8. **Secure Sessions:** HttpOnly, Secure, SameSite cookies

### Additional Recommendations

1. **Security Headers Audit**
   ```python
   Strict-Transport-Security: max-age=31536000; includeSubDomains
   X-Content-Type-Options: nosniff
   X-Frame-Options: DENY
   Permissions-Policy: geolocation=(), microphone=()
   ```

2. **API Key Rotation**
   - Implement key expiration
   - Force rotation every 90 days
   - Revoke unused keys

3. **Audit Logging**
   - Log all authentication attempts
   - Log API key usage
   - Log permission changes

4. **Vulnerability Scanning**
   - Regular dependency updates
   - SAST with Bandit
   - Container scanning with Trivy
   - Penetration testing

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2024-01 | Initial architecture documentation |

---

## Contributing

For architecture changes, please:
1. Open an issue for discussion
2. Create architectural diagrams
3. Update this document
4. Submit PR with implementation

## License

AGPL V3.0
