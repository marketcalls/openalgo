# 18 - Database Structure

## Overview

OpenAlgo uses **5 separate databases** for data isolation, performance optimization, and specialized use cases. This separation prevents contention and allows each database to be optimized for its specific workload.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         Database Architecture                                 │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                           5 Separate Databases                               │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │   openalgo.db   │  │    logs.db      │  │   latency.db    │             │
│  │   (Main DB)     │  │   (Traffic)     │  │  (Performance)  │             │
│  │                 │  │                 │  │                 │             │
│  │  - Users        │  │  - traffic_logs │  │  - order_latency│             │
│  │  - Auth tokens  │  │  - ip_bans      │  │                 │             │
│  │  - API keys     │  │  - error_404    │  │  Metrics:       │             │
│  │  - Settings     │  │  - api_tracker  │  │  - RTT          │             │
│  │  - Orders       │  │                 │  │  - Overhead     │             │
│  │  - Strategies   │  │                 │  │  - Percentiles  │             │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘             │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐                                   │
│  │   sandbox.db    │  │ historify.duckdb│                                   │
│  │  (Paper Trade)  │  │ (Market Data)   │                                   │
│  │                 │  │                 │                                   │
│  │  - Virtual ₹1Cr │  │  - OHLCV data   │                                   │
│  │  - Positions    │  │  - Watchlists   │                                   │
│  │  - Holdings     │  │                 │                                   │
│  │  - Trades       │  │  DuckDB format  │                                   │
│  │  - Daily P&L    │  │  (columnar)     │                                   │
│  └─────────────────┘  └─────────────────┘                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Database 1: Main Database (openalgo.db)

### Location
```
db/openalgo.db
```

### Core Tables

#### users
```
┌────────────────────────────────────────────────────┐
│                    users table                      │
├──────────────┬──────────────┬──────────────────────┤
│ Column       │ Type         │ Description          │
├──────────────┼──────────────┼──────────────────────┤
│ id           │ INTEGER PK   │ Auto-increment       │
│ username     │ VARCHAR(80)  │ Unique login         │
│ email        │ VARCHAR(120) │ Unique email         │
│ password_hash│ VARCHAR(255) │ Argon2 hash + pepper │
│ totp_secret  │ VARCHAR(32)  │ 2FA secret           │
│ is_admin     │ BOOLEAN      │ Admin flag           │
└──────────────┴──────────────┴──────────────────────┘
```

#### auth
```
┌────────────────────────────────────────────────────┐
│                    auth table                       │
├──────────────┬──────────────┬──────────────────────┤
│ Column       │ Type         │ Description          │
├──────────────┼──────────────┼──────────────────────┤
│ id           │ INTEGER PK   │ Auto-increment       │
│ name         │ VARCHAR(255) │ User identifier      │
│ auth         │ TEXT         │ Encrypted token      │
│ feed_token   │ TEXT         │ Encrypted feed token │
│ broker       │ VARCHAR(20)  │ Broker name          │
│ user_id      │ VARCHAR(255) │ Broker user ID       │
│ is_revoked   │ BOOLEAN      │ Token revoked flag   │
└──────────────┴──────────────┴──────────────────────┘
```

#### api_keys
```
┌────────────────────────────────────────────────────┐
│                  api_keys table                     │
├──────────────┬──────────────┬──────────────────────┤
│ Column       │ Type         │ Description          │
├──────────────┼──────────────┼──────────────────────┤
│ id           │ INTEGER PK   │ Auto-increment       │
│ user_id      │ VARCHAR      │ User identifier      │
│ api_key_hash │ TEXT         │ Argon2 hash          │
│ api_key_enc  │ TEXT         │ Fernet encrypted     │
│ created_at   │ DATETIME     │ Creation timestamp   │
│ order_mode   │ VARCHAR(20)  │ auto / semi_auto     │
└──────────────┴──────────────┴──────────────────────┘
```

#### settings
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
│ security_404_threshold    │ INT │ 404 ban threshold│
│ security_api_threshold    │ INT │ API ban threshold│
│ security_ban_duration     │ INT │ Ban hours        │
└────────────────────┴──────────┴────────────────────┘
```

#### strategies
```
┌────────────────────────────────────────────────────┐
│                 strategies table                    │
├──────────────────┬──────────────┬──────────────────┤
│ Column           │ Type         │ Description      │
├──────────────────┼──────────────┼──────────────────┤
│ id               │ INTEGER PK   │ Auto-increment   │
│ name             │ VARCHAR(255) │ Strategy name    │
│ webhook_id       │ VARCHAR(36)  │ UUID for webhooks│
│ user_id          │ VARCHAR(255) │ Owner            │
│ platform         │ VARCHAR(50)  │ tradingview, etc │
│ is_active        │ BOOLEAN      │ Active flag      │
│ is_intraday      │ BOOLEAN      │ Intraday mode    │
│ trading_mode     │ VARCHAR(10)  │ LONG/SHORT/BOTH  │
│ start_time       │ VARCHAR(5)   │ HH:MM            │
│ end_time         │ VARCHAR(5)   │ HH:MM            │
│ squareoff_time   │ VARCHAR(5)   │ HH:MM            │
└──────────────────┴──────────────┴──────────────────┘
```

#### flow_workflows
```
┌────────────────────────────────────────────────────┐
│               flow_workflows table                  │
├──────────────────┬──────────────┬──────────────────┤
│ Column           │ Type         │ Description      │
├──────────────────┼──────────────┼──────────────────┤
│ id               │ INTEGER PK   │ Auto-increment   │
│ name             │ VARCHAR(255) │ Workflow name    │
│ description      │ TEXT         │ Description      │
│ nodes            │ JSON         │ Node definitions │
│ edges            │ JSON         │ Connections      │
│ is_active        │ BOOLEAN      │ Active flag      │
│ webhook_token    │ VARCHAR(64)  │ Webhook ID       │
│ webhook_secret   │ VARCHAR(64)  │ HMAC secret      │
│ api_key          │ VARCHAR(255) │ Stored API key   │
└──────────────────┴──────────────┴──────────────────┘
```

#### pending_orders (Action Center)
```
┌────────────────────────────────────────────────────┐
│              pending_orders table                   │
├──────────────────┬──────────────┬──────────────────┤
│ Column           │ Type         │ Description      │
├──────────────────┼──────────────┼──────────────────┤
│ id               │ INTEGER PK   │ Auto-increment   │
│ user_id          │ VARCHAR(255) │ User identifier  │
│ api_type         │ VARCHAR(50)  │ placeorder, etc  │
│ order_data       │ TEXT         │ JSON order data  │
│ status           │ VARCHAR(20)  │ pending/approved │
│ created_at       │ DATETIME     │ Creation (UTC)   │
│ created_at_ist   │ VARCHAR(50)  │ Creation (IST)   │
│ approved_by      │ VARCHAR(255) │ Approver         │
│ broker_order_id  │ VARCHAR(255) │ Broker order ID  │
└──────────────────┴──────────────┴──────────────────┘
```

## Database 2: Logs Database (logs.db)

### Location
```
db/logs.db
```

### Tables

#### traffic_logs
```
┌────────────────────────────────────────────────────┐
│                traffic_logs table                   │
├──────────────┬──────────────┬──────────────────────┤
│ Column       │ Type         │ Description          │
├──────────────┼──────────────┼──────────────────────┤
│ id           │ INTEGER PK   │ Auto-increment       │
│ timestamp    │ DATETIME     │ Request time         │
│ client_ip    │ VARCHAR(50)  │ Client IP address    │
│ method       │ VARCHAR(10)  │ HTTP method          │
│ path         │ VARCHAR(500) │ Request path         │
│ status_code  │ INTEGER      │ HTTP status          │
│ duration_ms  │ FLOAT        │ Response time (ms)   │
│ host         │ VARCHAR(500) │ Host header          │
│ error        │ VARCHAR(500) │ Error message        │
│ user_id      │ INTEGER      │ User ID if logged in │
└──────────────┴──────────────┴──────────────────────┘
```

#### ip_bans
```
┌────────────────────────────────────────────────────┐
│                  ip_bans table                      │
├──────────────┬──────────────┬──────────────────────┤
│ Column       │ Type         │ Description          │
├──────────────┼──────────────┼──────────────────────┤
│ id           │ INTEGER PK   │ Auto-increment       │
│ ip_address   │ VARCHAR(50)  │ Banned IP            │
│ ban_reason   │ VARCHAR(200) │ Reason for ban       │
│ ban_count    │ INTEGER      │ Number of offenses   │
│ banned_at    │ DATETIME     │ Ban timestamp        │
│ expires_at   │ DATETIME     │ Expiry (NULL=perm)   │
│ is_permanent │ BOOLEAN      │ Permanent flag       │
│ created_by   │ VARCHAR(50)  │ system / manual      │
└──────────────┴──────────────┴──────────────────────┘
```

#### error_404_tracker
```
Tracks 404 errors per IP for bot detection
Threshold: 20 errors/day → auto-ban
```

#### invalid_api_key_tracker
```
Tracks invalid API key attempts per IP
Threshold: 10 attempts/day → auto-ban
```

## Database 3: Latency Database (latency.db)

### Location
```
db/latency.db
```

### Table: order_latency

```
┌────────────────────────────────────────────────────┐
│               order_latency table                   │
├──────────────────┬──────────────┬──────────────────┤
│ Column           │ Type         │ Description      │
├──────────────────┼──────────────┼──────────────────┤
│ id               │ INTEGER PK   │ Auto-increment   │
│ timestamp        │ DATETIME     │ Log time         │
│ order_id         │ VARCHAR(100) │ Order ID         │
│ broker           │ VARCHAR(50)  │ Broker name      │
│ symbol           │ VARCHAR(50)  │ Trading symbol   │
│ order_type       │ VARCHAR(20)  │ MARKET/LIMIT/SL  │
│ rtt_ms           │ FLOAT        │ Round-trip time  │
│ validation_ms    │ FLOAT        │ Pre-request      │
│ response_ms      │ FLOAT        │ Post-response    │
│ overhead_ms      │ FLOAT        │ OpenAlgo overhead│
│ total_latency_ms │ FLOAT        │ End-to-end time  │
│ status           │ VARCHAR(20)  │ SUCCESS/FAILED   │
└──────────────────┴──────────────┴──────────────────┘
```

### Metrics Tracked

| Metric | Description |
|--------|-------------|
| rtt_ms | Network round-trip to broker |
| validation_ms | Request validation time |
| response_ms | Response processing time |
| overhead_ms | Total OpenAlgo overhead |
| P50, P90, P95, P99 | Latency percentiles |

## Database 4: Sandbox Database (sandbox.db)

### Location
```
db/sandbox.db
```

### Purpose
Isolated paper trading with ₹1 Crore virtual capital.

### Tables

#### sandbox_orders
```
┌────────────────────────────────────────────────────┐
│               sandbox_orders table                  │
├──────────────────┬──────────────┬──────────────────┤
│ Column           │ Type         │ Description      │
├──────────────────┼──────────────┼──────────────────┤
│ id               │ INTEGER PK   │ Auto-increment   │
│ orderid          │ VARCHAR(50)  │ Unique order ID  │
│ user_id          │ VARCHAR(50)  │ User identifier  │
│ symbol           │ VARCHAR(50)  │ Trading symbol   │
│ exchange         │ VARCHAR(20)  │ NSE/NFO/MCX      │
│ action           │ VARCHAR(10)  │ BUY/SELL         │
│ quantity         │ INTEGER      │ Order quantity   │
│ price            │ DECIMAL      │ Order price      │
│ price_type       │ VARCHAR(20)  │ MARKET/LIMIT/SL  │
│ product          │ VARCHAR(20)  │ CNC/MIS/NRML     │
│ order_status     │ VARCHAR(20)  │ open/complete    │
│ margin_blocked   │ DECIMAL      │ Margin held      │
└──────────────────┴──────────────┴──────────────────┘
```

#### sandbox_positions
```
┌────────────────────────────────────────────────────┐
│             sandbox_positions table                 │
├──────────────────┬──────────────┬──────────────────┤
│ Column           │ Type         │ Description      │
├──────────────────┼──────────────┼──────────────────┤
│ id               │ INTEGER PK   │ Auto-increment   │
│ user_id          │ VARCHAR(50)  │ User identifier  │
│ symbol           │ VARCHAR(50)  │ Trading symbol   │
│ exchange         │ VARCHAR(20)  │ Exchange         │
│ product          │ VARCHAR(20)  │ Product type     │
│ quantity         │ INTEGER      │ Net quantity     │
│ average_price    │ DECIMAL      │ Entry price      │
│ ltp              │ DECIMAL      │ Last traded price│
│ pnl              │ DECIMAL      │ Unrealized P&L   │
│ margin_blocked   │ DECIMAL      │ Position margin  │
└──────────────────┴──────────────┴──────────────────┘
```

#### sandbox_funds
```
┌────────────────────────────────────────────────────┐
│               sandbox_funds table                   │
├──────────────────┬──────────────┬──────────────────┤
│ Column           │ Type         │ Description      │
├──────────────────┼──────────────┼──────────────────┤
│ id               │ INTEGER PK   │ Auto-increment   │
│ user_id          │ VARCHAR(50)  │ Unique user      │
│ total_capital    │ DECIMAL      │ ₹1 Crore default │
│ available_balance│ DECIMAL      │ Cash available   │
│ used_margin      │ DECIMAL      │ Blocked margin   │
│ realized_pnl     │ DECIMAL      │ All-time P&L     │
│ today_realized   │ DECIMAL      │ Today's P&L      │
│ unrealized_pnl   │ DECIMAL      │ Open position MTM│
└──────────────────┴──────────────┴──────────────────┘
```

### Sandbox Configuration

| Config Key | Default | Description |
|------------|---------|-------------|
| starting_capital | ₹1,00,00,000 | Initial capital |
| equity_mis_leverage | 5x | Intraday equity leverage |
| futures_leverage | 10x | F&O leverage |
| nse_bse_square_off | 15:15 | Auto square-off time |
| mcx_square_off | 23:30 | MCX square-off time |

## Database 5: Historical Data (historify.duckdb)

### Location
```
db/historify.duckdb
```

### Format
DuckDB (columnar, analytics-optimized)

### Table: market_data

```
┌────────────────────────────────────────────────────┐
│               market_data table                     │
├──────────────┬──────────────┬──────────────────────┤
│ Column       │ Type         │ Description          │
├──────────────┼──────────────┼──────────────────────┤
│ symbol       │ VARCHAR      │ Trading symbol       │
│ exchange     │ VARCHAR      │ Exchange code        │
│ interval     │ VARCHAR      │ 1m, 5m, 15m, 1h, 1d  │
│ timestamp    │ BIGINT       │ UNIX timestamp       │
│ open         │ DOUBLE       │ OHLC open            │
│ high         │ DOUBLE       │ OHLC high            │
│ low          │ DOUBLE       │ OHLC low             │
│ close        │ DOUBLE       │ OHLC close           │
│ volume       │ BIGINT       │ Trading volume       │
│ oi           │ BIGINT       │ Open interest        │
└──────────────┴──────────────┴──────────────────────┘

Primary Key: (symbol, exchange, interval, timestamp)
```

## Connection Pooling

### SQLite Configuration

```python
# NullPool for thread safety
from sqlalchemy.pool import NullPool

engine = create_engine(
    'sqlite:///db/openalgo.db',
    poolclass=NullPool,  # Create/close per request
    connect_args={'timeout': 30}
)
```

### PostgreSQL Configuration (Production)

```python
engine = create_engine(
    DATABASE_URL,
    pool_size=50,
    max_overflow=100,
    pool_timeout=30,
    pool_pre_ping=True
)
```

## Security Features

### Encryption

| Data Type | Method |
|-----------|--------|
| Passwords | Argon2 + pepper |
| API keys | Argon2 hash + Fernet encrypt |
| Auth tokens | Fernet (AES-128 CBC) |
| SMTP passwords | Fernet |

### Caching Strategy

| Cache | TTL | Purpose |
|-------|-----|---------|
| Auth tokens | Session expiry | Fast auth lookup |
| Verified API keys | 10 hours | Reduce hashing |
| Invalid API keys | 5 minutes | Block brute force |
| Settings | 1 hour | Config cache |
| Strategies | 5-10 minutes | Webhook lookup |

## Database Relationships

```
┌─────────────┐     ┌─────────────────────┐
│   users     │────<│      api_keys       │
└─────────────┘     └─────────────────────┘
      │
      │             ┌─────────────────────┐
      └────────────<│       auth          │
                    └─────────────────────┘

┌─────────────┐     ┌─────────────────────┐
│ strategies  │────<│ strategy_symbol_map │
└─────────────┘     └─────────────────────┘

┌──────────────┐     ┌─────────────────────┐
│flow_workflows│────<│workflow_executions  │
└──────────────┘     └─────────────────────┘

┌─────────────┐     ┌─────────────────────┐
│  holidays   │────<│ holiday_exchanges   │
└─────────────┘     └─────────────────────┘
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `database/user_db.py` | User table |
| `database/auth_db.py` | Auth and API keys |
| `database/settings_db.py` | Settings table |
| `database/strategy_db.py` | Strategies |
| `database/flow_db.py` | Flow workflows |
| `database/action_center_db.py` | Pending orders |
| `database/traffic_db.py` | Logs database |
| `database/latency_db.py` | Latency metrics |
| `database/sandbox_db.py` | Sandbox tables |
| `database/historify_db.py` | DuckDB historical |
