# Database Schema - Sandbox Mode

## Overview

The sandbox mode uses a completely separate SQLite database (`db/sandbox.db`) with 6 core tables that handle all aspects of simulated trading - from orders to positions, trades to holdings, funds management to configuration.

**Database Location**: `db/sandbox.db`
**Environment Variable**: `SANDBOX_DATABASE_URL=sqlite:///db/sandbox.db`

## Database Configuration

### Connection Settings

```python
# database/sandbox_db.py
engine = create_engine(
    SANDBOX_DATABASE_URL,
    pool_size=20,          # Connection pool size
    max_overflow=40,       # Maximum overflow connections
    pool_timeout=10        # Timeout in seconds
)
```

### Session Management

```python
db_session = scoped_session(sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
))
```

## Table Schemas

### 1. sandbox_orders

Stores all sandbox orders with complete lifecycle tracking.

#### Schema

```sql
CREATE TABLE sandbox_orders (
    -- Primary Key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Order Identification
    orderid VARCHAR(50) UNIQUE NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    strategy VARCHAR(100),

    -- Instrument Details
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(20) NOT NULL,

    -- Order Parameters
    action VARCHAR(10) NOT NULL,           -- BUY, SELL
    quantity INTEGER NOT NULL,
    price DECIMAL(10, 2),                  -- NULL for MARKET orders
    trigger_price DECIMAL(10, 2),          -- For SL/SL-M orders
    price_type VARCHAR(20) NOT NULL,       -- MARKET, LIMIT, SL, SL-M
    product VARCHAR(20) NOT NULL,          -- CNC, NRML, MIS

    -- Order Status
    order_status VARCHAR(20) NOT NULL DEFAULT 'open',  -- open, complete, cancelled, rejected
    average_price DECIMAL(10, 2),          -- Execution price
    filled_quantity INTEGER DEFAULT 0,     -- Always 0 or quantity (no partials)
    pending_quantity INTEGER NOT NULL,
    rejection_reason TEXT,

    -- Margin Tracking
    margin_blocked DECIMAL(10, 2) DEFAULT 0.00,

    -- Timestamps
    order_timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### Indexes

```sql
CREATE INDEX idx_orderid ON sandbox_orders(orderid);
CREATE INDEX idx_user_id ON sandbox_orders(user_id);
CREATE INDEX idx_symbol ON sandbox_orders(symbol);
CREATE INDEX idx_exchange ON sandbox_orders(exchange);
CREATE INDEX idx_order_status ON sandbox_orders(order_status);
CREATE INDEX idx_user_status ON sandbox_orders(user_id, order_status);
CREATE INDEX idx_symbol_exchange ON sandbox_orders(symbol, exchange);
```

#### Constraints

```sql
-- Order status validation
CHECK (order_status IN ('open', 'complete', 'cancelled', 'rejected'))

-- Action validation
CHECK (action IN ('BUY', 'SELL'))

-- Price type validation
CHECK (price_type IN ('MARKET', 'LIMIT', 'SL', 'SL-M'))

-- Product validation
CHECK (product IN ('CNC', 'NRML', 'MIS'))
```

#### Column Details

| Column | Type | Description | Nullable | Default |
|--------|------|-------------|----------|---------|
| id | INTEGER | Auto-incrementing primary key | No | Auto |
| orderid | VARCHAR(50) | Unique order ID (SB-YYYYMMDD-HHMMSS-xxxxx) | No | - |
| user_id | VARCHAR(50) | User identifier | No | - |
| strategy | VARCHAR(100) | Strategy name for grouping | Yes | NULL |
| symbol | VARCHAR(50) | Trading symbol | No | - |
| exchange | VARCHAR(20) | Exchange (NSE, BSE, NFO, etc.) | No | - |
| action | VARCHAR(10) | BUY or SELL | No | - |
| quantity | INTEGER | Order quantity | No | - |
| price | DECIMAL(10,2) | Limit price (NULL for MARKET) | Yes | NULL |
| trigger_price | DECIMAL(10,2) | Trigger price for SL orders | Yes | NULL |
| price_type | VARCHAR(20) | Order type | No | - |
| product | VARCHAR(20) | Product type | No | - |
| order_status | VARCHAR(20) | Current order status | No | 'open' |
| average_price | DECIMAL(10,2) | Filled price | Yes | NULL |
| filled_quantity | INTEGER | Quantity filled | No | 0 |
| pending_quantity | INTEGER | Quantity pending | No | - |
| rejection_reason | TEXT | Reason if rejected | Yes | NULL |
| margin_blocked | DECIMAL(10,2) | Margin amount blocked | Yes | 0.00 |
| order_timestamp | DATETIME | Order placement time (IST) | No | NOW |
| update_timestamp | DATETIME | Last update time (IST) | No | NOW |

---

### 2. sandbox_trades

Stores executed trades created when orders fill.

#### Schema

```sql
CREATE TABLE sandbox_trades (
    -- Primary Key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Trade Identification
    tradeid VARCHAR(50) UNIQUE NOT NULL,
    orderid VARCHAR(50) NOT NULL,
    user_id VARCHAR(50) NOT NULL,

    -- Instrument Details
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(20) NOT NULL,

    -- Trade Details
    action VARCHAR(10) NOT NULL,       -- BUY, SELL
    quantity INTEGER NOT NULL,
    price DECIMAL(10, 2) NOT NULL,     -- Execution price
    product VARCHAR(20) NOT NULL,      -- CNC, NRML, MIS
    strategy VARCHAR(100),

    -- Timestamp
    trade_timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### Indexes

```sql
CREATE INDEX idx_tradeid ON sandbox_trades(tradeid);
CREATE INDEX idx_orderid ON sandbox_trades(orderid);
CREATE INDEX idx_user_id ON sandbox_trades(user_id);
CREATE INDEX idx_symbol ON sandbox_trades(symbol);
CREATE INDEX idx_exchange ON sandbox_trades(exchange);
CREATE INDEX idx_user_symbol ON sandbox_trades(user_id, symbol);
```

#### Column Details

| Column | Type | Description | Nullable | Default |
|--------|------|-------------|----------|---------|
| id | INTEGER | Auto-incrementing primary key | No | Auto |
| tradeid | VARCHAR(50) | Unique trade ID | No | - |
| orderid | VARCHAR(50) | Parent order ID | No | - |
| user_id | VARCHAR(50) | User identifier | No | - |
| symbol | VARCHAR(50) | Trading symbol | No | - |
| exchange | VARCHAR(20) | Exchange | No | - |
| action | VARCHAR(10) | BUY or SELL | No | - |
| quantity | INTEGER | Trade quantity | No | - |
| price | DECIMAL(10,2) | Execution price | No | - |
| product | VARCHAR(20) | Product type | No | - |
| strategy | VARCHAR(100) | Strategy name | Yes | NULL |
| trade_timestamp | DATETIME | Trade execution time (IST) | No | NOW |

---

### 3. sandbox_positions

Tracks open and closed positions with real-time P&L.

#### Schema

```sql
CREATE TABLE sandbox_positions (
    -- Primary Key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Position Identification
    user_id VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    product VARCHAR(20) NOT NULL,      -- CNC, NRML, MIS

    -- Position Details
    quantity INTEGER NOT NULL,          -- Net quantity (negative = short)
    average_price DECIMAL(10, 2) NOT NULL,

    -- MTM Tracking
    ltp DECIMAL(10, 2),                -- Last traded price
    pnl DECIMAL(10, 2) DEFAULT 0.00,   -- Current P&L
    pnl_percent DECIMAL(10, 4) DEFAULT 0.00,
    accumulated_realized_pnl DECIMAL(10, 2) DEFAULT 0.00,  -- Intraday accumulated P&L

    -- Margin Tracking
    margin_blocked DECIMAL(15, 2) DEFAULT 0.00,  -- Exact margin blocked for this position

    -- Timestamps
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Unique Constraint
    CONSTRAINT unique_position UNIQUE (user_id, symbol, exchange, product)
);
```

#### Indexes

```sql
CREATE INDEX idx_user_id ON sandbox_positions(user_id);
CREATE INDEX idx_symbol ON sandbox_positions(symbol);
CREATE INDEX idx_exchange ON sandbox_positions(exchange);
CREATE INDEX idx_user_product ON sandbox_positions(user_id, product);
```

#### Column Details

| Column | Type | Description | Nullable | Default |
|--------|------|-------------|----------|---------|
| id | INTEGER | Auto-incrementing primary key | No | Auto |
| user_id | VARCHAR(50) | User identifier | No | - |
| symbol | VARCHAR(50) | Trading symbol | No | - |
| exchange | VARCHAR(20) | Exchange | No | - |
| product | VARCHAR(20) | Product type | No | - |
| quantity | INTEGER | Net position (+long, -short) | No | - |
| average_price | DECIMAL(10,2) | Average entry price | No | - |
| ltp | DECIMAL(10,2) | Current LTP for MTM | Yes | NULL |
| pnl | DECIMAL(10,2) | Current P&L | Yes | 0.00 |
| pnl_percent | DECIMAL(10,4) | P&L percentage | Yes | 0.00 |
| accumulated_realized_pnl | DECIMAL(10,2) | Accumulated intraday P&L | Yes | 0.00 |
| margin_blocked | DECIMAL(15,2) | Exact margin blocked for position | Yes | 0.00 |
| created_at | DATETIME | Position creation time (IST) | No | NOW |
| updated_at | DATETIME | Last update time (IST) | No | NOW |

---

### 4. sandbox_holdings

Stores T+1 settled CNC positions.

#### Schema

```sql
CREATE TABLE sandbox_holdings (
    -- Primary Key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Holding Identification
    user_id VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(20) NOT NULL,

    -- Holding Details
    quantity INTEGER NOT NULL,
    average_price DECIMAL(10, 2) NOT NULL,

    -- MTM Tracking
    ltp DECIMAL(10, 2),
    pnl DECIMAL(10, 2) DEFAULT 0.00,
    pnl_percent DECIMAL(10, 4) DEFAULT 0.00,

    -- Settlement Tracking
    settlement_date DATE NOT NULL,     -- T+1 settlement date

    -- Timestamps
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Unique Constraint
    CONSTRAINT unique_holding UNIQUE (user_id, symbol, exchange)
);
```

#### Indexes

```sql
CREATE INDEX idx_user_id ON sandbox_holdings(user_id);
CREATE INDEX idx_symbol ON sandbox_holdings(symbol);
CREATE INDEX idx_exchange ON sandbox_holdings(exchange);
```

#### Column Details

| Column | Type | Description | Nullable | Default |
|--------|------|-------------|----------|---------|
| id | INTEGER | Auto-incrementing primary key | No | Auto |
| user_id | VARCHAR(50) | User identifier | No | - |
| symbol | VARCHAR(50) | Trading symbol | No | - |
| exchange | VARCHAR(20) | Exchange | No | - |
| quantity | INTEGER | Holdings quantity | No | - |
| average_price | DECIMAL(10,2) | Average buy price | No | - |
| ltp | DECIMAL(10,2) | Current LTP for MTM | Yes | NULL |
| pnl | DECIMAL(10,2) | Unrealized P&L | Yes | 0.00 |
| pnl_percent | DECIMAL(10,4) | P&L percentage | Yes | 0.00 |
| settlement_date | DATE | T+1 settlement date | No | - |
| created_at | DATETIME | Holding creation time (IST) | No | NOW |
| updated_at | DATETIME | Last update time (IST) | No | NOW |

---

### 5. sandbox_funds

User-wise capital and margin tracking.

#### Schema

```sql
CREATE TABLE sandbox_funds (
    -- Primary Key
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR(50) UNIQUE NOT NULL,

    -- Fund Balances
    total_capital DECIMAL(15, 2) DEFAULT 10000000.00,
    available_balance DECIMAL(15, 2) DEFAULT 10000000.00,
    used_margin DECIMAL(15, 2) DEFAULT 0.00,

    -- P&L Tracking
    realized_pnl DECIMAL(15, 2) DEFAULT 0.00,
    unrealized_pnl DECIMAL(15, 2) DEFAULT 0.00,
    total_pnl DECIMAL(15, 2) DEFAULT 0.00,

    -- Reset Tracking
    last_reset_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reset_count INTEGER DEFAULT 0,

    -- Timestamps
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### Indexes

```sql
CREATE UNIQUE INDEX idx_user_id ON sandbox_funds(user_id);
```

#### Column Details

| Column | Type | Description | Nullable | Default |
|--------|------|-------------|----------|---------|
| id | INTEGER | Auto-incrementing primary key | No | Auto |
| user_id | VARCHAR(50) | User identifier (unique) | No | - |
| total_capital | DECIMAL(15,2) | Starting capital | No | 10000000.00 |
| available_balance | DECIMAL(15,2) | Available for trading | No | 10000000.00 |
| used_margin | DECIMAL(15,2) | Margin blocked | No | 0.00 |
| realized_pnl | DECIMAL(15,2) | P&L from closed positions | No | 0.00 |
| unrealized_pnl | DECIMAL(15,2) | P&L from open positions | No | 0.00 |
| total_pnl | DECIMAL(15,2) | Total P&L | No | 0.00 |
| last_reset_date | DATETIME | Last reset timestamp | No | NOW |
| reset_count | INTEGER | Number of resets | No | 0 |
| created_at | DATETIME | Account creation time (IST) | No | NOW |
| updated_at | DATETIME | Last update time (IST) | No | NOW |

---

### 6. sandbox_config

System-wide configuration settings.

#### Schema

```sql
CREATE TABLE sandbox_config (
    -- Primary Key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Configuration
    config_key VARCHAR(100) UNIQUE NOT NULL,
    config_value TEXT NOT NULL,
    description TEXT,

    -- Timestamp
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### Indexes

```sql
CREATE UNIQUE INDEX idx_config_key ON sandbox_config(config_key);
```

#### Column Details

| Column | Type | Description | Nullable | Default |
|--------|------|-------------|----------|---------|
| id | INTEGER | Auto-incrementing primary key | No | Auto |
| config_key | VARCHAR(100) | Configuration key (unique) | No | - |
| config_value | TEXT | Configuration value | No | - |
| description | TEXT | Description | Yes | NULL |
| updated_at | DATETIME | Last update time (IST) | No | NOW |

#### Default Configuration Values

| Config Key | Default Value | Description |
|------------|---------------|-------------|
| starting_capital | 10000000.00 | Starting sandbox capital (₹1 Crore) |
| reset_day | Sunday | Auto-reset day |
| reset_time | 00:00 | Auto-reset time (IST) |
| order_check_interval | 5 | Seconds between order checks (1-30) |
| mtm_update_interval | 5 | Seconds between MTM updates (0-60) |
| nse_bse_square_off_time | 15:15 | NSE/BSE square-off time (IST) |
| cds_bcd_square_off_time | 16:45 | CDS/BCD square-off time (IST) |
| mcx_square_off_time | 23:30 | MCX square-off time (IST) |
| ncdex_square_off_time | 17:00 | NCDEX square-off time (IST) |
| equity_mis_leverage | 5 | Equity MIS leverage (1-50x) |
| equity_cnc_leverage | 1 | Equity CNC leverage (1-50x) |
| futures_leverage | 10 | Futures leverage (1-50x) |
| option_buy_leverage | 1 | Option buy leverage (1-50x) |
| option_sell_leverage | 1 | Option sell leverage (1-50x) |
| order_rate_limit | 10 | Orders per second (1-100) |
| api_rate_limit | 50 | API calls per second (1-1000) |
| smart_order_rate_limit | 2 | Smart orders per second (1-50) |
| smart_order_delay | 0.5 | Delay between smart orders (0.1-10s) |

## Relationships

```
sandbox_funds (1) ─────── (many) sandbox_orders
                │
                └─────── (many) sandbox_positions
                │
                └─────── (many) sandbox_holdings

sandbox_orders (1) ────── (many) sandbox_trades

sandbox_positions (many) ─ (1) sandbox_config (leverage settings)

sandbox_holdings (many) ── (1) sandbox_config (T+1 settlement)
```

## Common Queries

### Get All Open Orders for User

```python
from database.sandbox_db import SandboxOrders

orders = SandboxOrders.query.filter_by(
    user_id=user_id,
    order_status='open'
).order_by(SandboxOrders.order_timestamp.desc()).all()
```

### Get User Fund Details

```python
from database.sandbox_db import SandboxFunds

fund = SandboxFunds.query.filter_by(user_id=user_id).first()
```

### Get Open Positions

```python
from database.sandbox_db import SandboxPositions

positions = SandboxPositions.query.filter_by(
    user_id=user_id
).filter(
    SandboxPositions.quantity != 0
).all()
```

### Get All Trades for Symbol

```python
from database.sandbox_db import SandboxTrades

trades = SandboxTrades.query.filter_by(
    user_id=user_id,
    symbol='RELIANCE',
    exchange='NSE'
).order_by(SandboxTrades.trade_timestamp.desc()).all()
```

### Get Configuration Value

```python
from database.sandbox_db import get_config

leverage = get_config('equity_mis_leverage', default='5')
```

## Database Utilities

### Initialize Database

```python
from database.sandbox_db import init_db

init_db()  # Creates all tables and default config
```

### Get All Configurations

```python
from database.sandbox_db import get_all_configs

configs = get_all_configs()
# Returns: {config_key: {'value': ..., 'description': ...}}
```

### Update Configuration

```python
from database.sandbox_db import set_config

set_config('equity_mis_leverage', '8', 'Updated leverage')
```

## Migration

Run the comprehensive migration script:

```bash
# Using uv
uv run upgrade/migrate_sandbox.py

# Using Python
python upgrade/migrate_sandbox.py
```

The migration script:
- Creates all tables if missing
- Adds missing columns to existing tables
- Creates all indexes
- Inserts default configuration
- Is idempotent (safe to run multiple times)

## Database Maintenance

### Backup Database

```bash
# Create backup
cp db/sandbox.db db/sandbox_backup_$(date +%Y%m%d_%H%M%S).db
```

### Reset All Data (Keep Structure)

```python
from database.sandbox_db import db_session, SandboxOrders, SandboxTrades, SandboxPositions, SandboxHoldings, SandboxFunds

# Delete all data (keeps config)
db_session.query(SandboxOrders).delete()
db_session.query(SandboxTrades).delete()
db_session.query(SandboxPositions).delete()
db_session.query(SandboxHoldings).delete()
db_session.query(SandboxFunds).delete()
db_session.commit()
```

### Check Database Size

```bash
ls -lh db/sandbox.db
```

---

**Previous**: [Auto Square-Off](06_auto_squareoff.md) | **Next**: [Architecture](08_architecture.md)
