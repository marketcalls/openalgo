# Sandbox Mode - Design Document

## Executive Summary

OpenAlgo Sandbox Mode (API Analyzer) provides a complete simulated trading environment where users can test strategies, validate trading logic, and practice order execution using real-time market data without risking real capital. This document outlines the design, architecture, and implementation of the Sandbox Mode system.

## Problem Statement

Traders and algorithmic trading developers need a safe, realistic environment to:

1. **Test Trading Strategies**: Validate strategy logic before deploying with real capital
2. **Learn Trading Mechanics**: Understand order types, margin requirements, and position management
3. **Debug Algorithms**: Identify and fix issues in trading algorithms
4. **Simulate Real Conditions**: Experience realistic market behavior and order execution
5. **Risk-Free Practice**: Build confidence without financial risk

## Solution Overview

Sandbox Mode provides a complete isolated trading environment with:

- **Simulated Capital**: ₹1 Crore (10 million) starting balance
- **Real Market Data**: Live prices from broker feeds
- **Realistic Execution**: Orders execute at actual market prices (LTP)
- **Complete Isolation**: Separate database and processing threads
- **Accurate Margin System**: Leverage-based calculations matching real trading
- **Auto Square-Off**: Exchange-specific automatic position closure

## Architecture Principles

### 1. Isolation

Complete separation between sandbox and live trading:

```
Live Trading Infrastructure          Sandbox Infrastructure
─────────────────────────           ─────────────────────────
database/auth_db.py                  database/sandbox_db.py
├── Users                            ├── SandboxOrders
├── ApiKeys                          ├── SandboxTrades
└── BrokerAccounts                   ├── SandboxPositions
                                     ├── SandboxHoldings
services/order_service.py            ├── SandboxFunds
services/position_service.py         └── SandboxConfig

broker/*/api.py                      sandbox/*.py
                                     ├── order_manager.py
                                     ├── position_manager.py
                                     ├── execution_engine.py
                                     ├── squareoff_manager.py
                                     └── fund_manager.py
```

**Benefits**:
- No risk of sandbox orders reaching live brokers
- Independent testing without affecting live data
- Clean data separation for analysis
- Parallel operation of live and sandbox modes

### 2. Realism

Sandbox mimics real trading behavior:

**Order Execution**:
- MARKET orders execute immediately at LTP
- LIMIT orders execute when LTP crosses limit price
- SL/SL-M orders trigger and execute at LTP
- No artificial slippage or delays

**Margin System**:
- Leverage-based margin blocking
- Exchange-specific leverage rules
- Instrument type-specific calculations
- Margin release on cancellation/closure

**Market Data**:
- Real-time LTP from broker feeds
- Actual lot sizes and tick sizes
- Live OHLCV data for analysis
- No simulated or delayed data

### 3. Scalability

Designed to handle multiple users and high order volumes:

**Thread Architecture**:
```python
Main Flask App (Main Thread)
├── Handles HTTP requests
├── Routes and blueprints
└── WebSocket connections

Execution Thread (Background)
├── Checks pending orders every 5 seconds
├── Executes when conditions met
└── Updates positions and funds

Squareoff Thread (Scheduled)
├── APScheduler with cron jobs
├── Exchange-specific times (IST)
├── Cancels pending MIS orders
└── Closes MIS positions
```

**Performance Optimizations**:
- Batch processing of orders (10 per second limit)
- Database connection pooling
- Indexed queries for fast lookups
- Scoped sessions for thread safety

### 4. Maintainability

Clean, modular code structure:

**Service Layer Pattern**:
```
Blueprint (sandboxblueprint) → Service (sandbox_service.py) → Core Module (order_manager.py)
     ↓                              ↓                              ↓
  HTTP Request                 Business Logic              Database Operations
```

**Separation of Concerns**:
- **Blueprints**: HTTP routing and request handling
- **Services**: Business logic and orchestration
- **Core Modules**: Specific functionality (orders, positions, funds)
- **Database**: Data models and persistence

## Component Design

### 1. Analyzer Service

**File**: `services/analyzer_service.py`
**Purpose**: Central control for toggling sandbox mode

**Key Responsibilities**:
- Enable/disable sandbox mode
- Start/stop background threads
- Return analyzer status
- Log mode transitions

**API**:
```python
def toggle_analyzer_mode(
    analyzer_data: Dict[str, Any],
    api_key: Optional[str] = None,
    auth_token: Optional[str] = None,
    broker: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Toggle analyzer mode on/off

    Args:
        analyzer_data: {'mode': True/False}
        api_key: OpenAlgo API key

    Returns:
        (success, response, status_code)
    """
```

**Mode Transition Logic**:
```python
if new_mode:  # Enabling analyzer mode
    1. Set analyze_mode flag in database
    2. Start execution thread
    3. Start squareoff scheduler
    4. Return success with mode='analyze'
else:  # Disabling analyzer mode
    1. Clear analyze_mode flag
    2. Stop execution thread
    3. Stop squareoff scheduler
    4. Return success with mode='live'
```

### 2. Order Manager

**File**: `sandbox/order_manager.py`
**Purpose**: Handle order placement, validation, and lifecycle

**Core Functions**:

#### place_order()
```python
def place_order(order_data, user_id):
    """Place sandbox order

    Steps:
    1. Validate order data (symbol, quantity, price)
    2. Get current LTP
    3. Calculate margin required
    4. Check available funds
    5. Block margin
    6. Create order record
    7. Execute if MARKET, else set status='open'
    8. Return orderid
    """
```

#### Margin Blocking Strategy
```python
def should_block_margin(action, product, symbol, exchange):
    """
    Decision tree for margin blocking:

    BUY orders:
    ├── Always block margin
    └── Amount = trade_value / leverage

    SELL orders:
    ├── Options (CE/PE):
    │   └── Block margin (short option)
    ├── Futures (FUT):
    │   └── Block margin (short future)
    └── Equity (MIS/NRML):
        └── Block margin (short selling)
    """
```

#### Price Selection for Margin
```python
def get_margin_price(order_data, ltp):
    """
    Price used for margin calculation:

    MARKET → Current LTP
    LIMIT  → Order's limit price
    SL     → Order's trigger price
    SL-M   → Order's trigger price
    """
```

**Key Features**:
- Instrument type detection via symbol suffix
- Order-specific price for margin calculation
- Comprehensive validation
- Margin release on cancellation

### 3. Execution Engine

**File**: `sandbox/execution_engine.py`
**Purpose**: Background execution of pending orders

**Architecture**:
```python
Thread Loop (every 5 seconds):
1. Query all pending orders (status='open')
2. Group by symbol for batch quote fetching
3. For each order:
   a. Get current LTP
   b. Check if execution condition met:
      - LIMIT: LTP crosses limit price
      - SL: LTP crosses trigger price
      - SL-M: LTP crosses trigger price
   c. If yes, execute at LTP
   d. Create trade entry
   e. Update position
   f. Release/adjust margin
4. Sleep until next cycle
```

**Execution Logic**:
```python
def check_execution_condition(order, ltp):
    """
    LIMIT BUY:  Execute when LTP <= order.price
    LIMIT SELL: Execute when LTP >= order.price

    SL BUY:     Trigger when LTP >= trigger_price
    SL SELL:    Trigger when LTP <= trigger_price

    SL-M BUY:   Same as SL
    SL-M SELL:  Same as SL

    All execute at LTP for realistic fills
    """
```

**Rate Limiting**:
- Max 10 orders per second (ORDER_RATE_LIMIT)
- Batch processing with 1-second delays
- Respects API rate limits (50 calls/second)

### 4. Squareoff Scheduler

**File**: `sandbox/squareoff_thread.py`
**Purpose**: Auto square-off MIS positions at EOD

**Implementation**: APScheduler with cron jobs

**Scheduler Configuration**:
```python
scheduler = BackgroundScheduler(
    timezone=pytz.timezone('Asia/Kolkata'),  # IST
    daemon=True,
    job_defaults={
        'coalesce': True,        # Combine missed runs
        'max_instances': 1,      # One job at a time
        'misfire_grace_time': 300  # 5 min grace
    }
)
```

**Job Schedule**:
```python
Exchange Groups and Times (IST):
├── NSE_BSE (NSE, BSE, NFO, BFO)
│   └── 15:15 (3:15 PM)
├── CDS_BCD (CDS, BCD)
│   └── 16:45 (4:45 PM)
├── MCX
│   └── 23:30 (11:30 PM)
└── NCDEX
    └── 17:00 (5:00 PM)
```

**Squareoff Process**:
```python
def squareoff_exchange_group(exchange_group):
    """
    Step 1: Cancel all pending MIS orders
    ├── Query open orders (status='open', product='MIS')
    ├── Release blocked margin
    └── Set status='cancelled'

    Step 2: Close all MIS positions
    ├── Query positions (product='MIS', qty!=0)
    ├── Get current LTP
    ├── Create reverse order (BUY if short, SELL if long)
    ├── Execute at MARKET (LTP)
    ├── Calculate realized P&L
    └── Update funds
    """
```

**Dynamic Reload**:
```python
def reload_squareoff_schedule():
    """
    Reload without restarting app:
    1. Remove all existing jobs
    2. Read updated times from sandbox_config
    3. Create new cron jobs
    4. No downtime or app restart needed
    """
```

### 5. Position Manager

**File**: `sandbox/position_manager.py`
**Purpose**: Manage positions, calculate P&L, and generate tradebook

**Position Update Logic**:
```python
def update_position(trade, user_id):
    """
    Position Update Algorithm:

    1. Find existing position (user_id, symbol, exchange, product)

    2. Calculate new quantity:
       - BUY: current_qty + trade_qty
       - SELL: current_qty - trade_qty

    3. Calculate average price:
       - If increasing position:
         avg_price = (old_qty * old_price + trade_qty * trade_price) / new_qty
       - If reducing/reversing:
         Keep old avg_price

    4. Update position record

    5. If quantity becomes 0:
       - Calculate realized P&L
       - Update funds
       - Keep position record for history
    """
```

**P&L Calculation**:
```python
def calculate_pnl(position, ltp):
    """
    Long Position (qty > 0):
    ├── Unrealized P&L = (LTP - avg_price) * qty
    └── P&L % = (Unrealized P&L / investment) * 100

    Short Position (qty < 0):
    ├── Unrealized P&L = (avg_price - LTP) * abs(qty)
    └── P&L % = (Unrealized P&L / investment) * 100

    Closed Position (qty = 0):
    └── Unrealized P&L = 0
    """
```

**Tradebook Formatting**:
```python
def format_tradebook(trades):
    """
    Format for display:
    ├── Round price to 2 decimals
    ├── Round trade_value to 2 decimals
    ├── Format timestamp to 'DD-MMM-YYYY HH:MM:SS'
    └── Include all trade details
    """
```

### 6. Fund Manager

**File**: `sandbox/fund_manager.py`
**Purpose**: Margin calculations and fund management

**Leverage Rules**:
```python
Exchange/Instrument Leverage Matrix:

NSE/BSE Equity:
├── MIS: 5x (configurable: equity_mis_leverage)
├── CNC: 1x (configurable: equity_cnc_leverage)
└── NRML: 1x

NFO/BFO/CDS/BCD/MCX/NCDEX:
├── Futures: 10x (configurable: futures_leverage)
├── Options BUY: 1x (full premium required)
└── Options SELL: 10x (futures margin)
```

**Margin Calculation**:
```python
def calculate_margin(order_data, ltp):
    """
    Margin Calculation:

    Options BUY:
    ├── margin = premium * lot_size * quantity
    └── (Full premium required)

    Options SELL:
    ├── margin = (underlying_ltp * lot_size * quantity) / leverage
    └── (Use futures margin)

    Futures:
    ├── margin = (ltp * lot_size * quantity) / leverage
    └── (Contract value / leverage)

    Equity:
    ├── margin = (price * quantity) / leverage
    └── (Trade value / leverage)
    """
```

**Fund Components**:
```python
class SandboxFunds:
    total_capital = 10000000.00        # Starting balance
    available_balance = calculated      # Total - used_margin
    used_margin = sum(position margins) # Blocked for positions
    realized_pnl = cumulative          # From closed positions
    unrealized_pnl = current           # From open positions
    total_pnl = realized + unrealized  # Total P&L
```

## Database Design

### Schema Overview

**Location**: `db/sandbox.db` (SQLite)

**Configuration**: `SANDBOX_DATABASE_URL` in `.env`

### Table: sandbox_orders

```sql
CREATE TABLE sandbox_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orderid VARCHAR(50) UNIQUE NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    strategy VARCHAR(100),
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    action VARCHAR(10) NOT NULL CHECK(action IN ('BUY', 'SELL')),
    quantity INTEGER NOT NULL,
    price DECIMAL(10, 2),
    trigger_price DECIMAL(10, 2),
    price_type VARCHAR(20) NOT NULL CHECK(price_type IN ('MARKET', 'LIMIT', 'SL', 'SL-M')),
    product VARCHAR(20) NOT NULL CHECK(product IN ('CNC', 'NRML', 'MIS')),
    order_status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK(order_status IN ('open', 'complete', 'cancelled', 'rejected')),
    average_price DECIMAL(10, 2),
    filled_quantity INTEGER DEFAULT 0,
    pending_quantity INTEGER NOT NULL,
    rejection_reason TEXT,
    margin_blocked DECIMAL(10, 2) DEFAULT 0.00,
    order_timestamp DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    update_timestamp DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),

    INDEX idx_orderid (orderid),
    INDEX idx_user_id (user_id),
    INDEX idx_symbol (symbol),
    INDEX idx_exchange (exchange),
    INDEX idx_order_status (order_status),
    INDEX idx_user_status (user_id, order_status),
    INDEX idx_symbol_exchange (symbol, exchange)
);
```

**Key Points**:
- `margin_blocked`: Tracks margin blocked for this order
- `order_status`: Lifecycle tracking (open → complete/cancelled/rejected)
- Indexes for fast query performance

### Table: sandbox_trades

```sql
CREATE TABLE sandbox_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tradeid VARCHAR(50) UNIQUE NOT NULL,
    orderid VARCHAR(50) NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    action VARCHAR(10) NOT NULL,
    quantity INTEGER NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    product VARCHAR(20) NOT NULL,
    strategy VARCHAR(100),
    trade_timestamp DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),

    INDEX idx_tradeid (tradeid),
    INDEX idx_trade_orderid (orderid),
    INDEX idx_trade_user (user_id),
    INDEX idx_user_symbol_trade (user_id, symbol)
);
```

**Purpose**: Immutable record of all executed trades

### Table: sandbox_positions

```sql
CREATE TABLE sandbox_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    product VARCHAR(20) NOT NULL,
    quantity INTEGER NOT NULL,
    average_price DECIMAL(10, 2) NOT NULL,
    ltp DECIMAL(10, 2),
    pnl DECIMAL(10, 2) DEFAULT 0.00,
    pnl_percent DECIMAL(10, 4) DEFAULT 0.00,
    created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),

    UNIQUE(user_id, symbol, exchange, product),
    INDEX idx_position_user (user_id),
    INDEX idx_user_symbol (user_id, symbol),
    INDEX idx_user_product (user_id, product)
);
```

**Key Points**:
- Unique constraint prevents duplicate positions
- `quantity`: Can be positive (long), negative (short), or zero (closed)
- `pnl`: Updated on MTM refresh

### Table: sandbox_holdings

```sql
CREATE TABLE sandbox_holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    quantity INTEGER NOT NULL,
    average_price DECIMAL(10, 2) NOT NULL,
    ltp DECIMAL(10, 2),
    pnl DECIMAL(10, 2) DEFAULT 0.00,
    pnl_percent DECIMAL(10, 4) DEFAULT 0.00,
    settlement_date DATE NOT NULL,
    created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),

    UNIQUE(user_id, symbol, exchange),
    INDEX idx_holding_user (user_id)
);
```

**Purpose**: T+1 settled positions from CNC orders

### Table: sandbox_funds

```sql
CREATE TABLE sandbox_funds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR(50) UNIQUE NOT NULL,
    total_capital DECIMAL(15, 2) DEFAULT 10000000.00,
    available_balance DECIMAL(15, 2) DEFAULT 10000000.00,
    used_margin DECIMAL(15, 2) DEFAULT 0.00,
    realized_pnl DECIMAL(15, 2) DEFAULT 0.00,
    unrealized_pnl DECIMAL(15, 2) DEFAULT 0.00,
    total_pnl DECIMAL(15, 2) DEFAULT 0.00,
    last_reset_date DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    reset_count INTEGER DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),

    INDEX idx_funds_user (user_id)
);
```

**Fund Relationships**:
```
available_balance = total_capital - used_margin + realized_pnl
total_pnl = realized_pnl + unrealized_pnl
```

### Table: sandbox_config

```sql
CREATE TABLE sandbox_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_key VARCHAR(100) UNIQUE NOT NULL,
    config_value TEXT NOT NULL,
    description TEXT,
    updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),

    INDEX idx_config_key (config_key)
);
```

**Configuration Entries** (18 total):
```
1. starting_capital: 10000000.00
2. reset_day: Sunday
3. reset_time: 00:00
4. order_check_interval: 5
5. mtm_update_interval: 5
6. nse_bse_square_off_time: 15:15
7. cds_bcd_square_off_time: 16:45
8. mcx_square_off_time: 23:30
9. ncdex_square_off_time: 17:00
10. equity_mis_leverage: 5
11. equity_cnc_leverage: 1
12. futures_leverage: 10
13. option_buy_leverage: 1
14. option_sell_leverage: 10
15. order_rate_limit: 10
16. api_rate_limit: 50
17. smart_order_rate_limit: 2
18. smart_order_delay: 0.5
```

## Integration Architecture

### 1. Market Data Integration

```python
Integration Point: services/quotes_service.py

Purpose: Real-time LTP for order execution and MTM

Flow:
1. Sandbox calls get_quotes(symbol, exchange, auth_token, broker)
2. Quote service routes to appropriate broker API
3. Returns real-time LTP, OHLC, volume
4. Sandbox uses LTP for execution and calculations
```

### 2. Symbol Service Integration

```python
Integration Point: services/symbol_service.py

Purpose: Instrument details (lot size, tick size)

Flow:
1. Sandbox calls get_symbol_info(symbol, exchange, auth_token, broker)
2. Symbol service fetches from master contract
3. Returns lot size, instrument type, expiry
4. Sandbox uses for margin calculations
```

### 3. Web UI Integration

```python
Integration Point: blueprints/sandbox.py

Routes:
├── /sandbox/ - Configuration page
├── /sandbox/update - Update config settings
├── /sandbox/reset - Reset funds and data
├── /sandbox/reload-squareoff - Reload schedule
└── /sandbox/squareoff-status - Get scheduler status

Auto-reload Feature:
When square-off time updated:
1. Config saved to database
2. Endpoint auto-calls reload_squareoff_schedule()
3. Scheduler reloads without restart
4. New times effective immediately
```

## Migration System

### Migration File

**File**: `upgrade/migrate_sandbox.py`

**Purpose**: Comprehensive setup of sandbox database

**Features**:
- Creates all 6 sandbox tables
- Adds missing columns to existing tables
- Creates all indexes
- Inserts default config entries
- Status checking with statistics
- Automatic backup before migration

**Usage**:
```bash
# Apply migration
cd openalgo
uv run upgrade/migrate_sandbox.py

# Or using Python directly
python upgrade/migrate_sandbox.py
```

**Idempotency**:
```python
def create_all_tables(conn):
    """All CREATE TABLE use IF NOT EXISTS"""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS sandbox_orders (...)
    """))

def insert_default_config(conn):
    """Check before inserting"""
    result = conn.execute(text(
        "SELECT 1 FROM sandbox_config WHERE config_key = :key"
    ), {'key': key})

    if not result.fetchone():
        # Insert only if doesn't exist
        conn.execute(text("""
            INSERT INTO sandbox_config (config_key, config_value, description)
            VALUES (:key, :value, :description)
        """))
```

## Configuration Management

### Environment Variables

```bash
# .env file
VERSION=1.0.4
SANDBOX_DATABASE_URL=sqlite:///db/sandbox.db

# Rate Limits
API_RATE_LIMIT=50 per second
ORDER_RATE_LIMIT=10 per second
SMART_ORDER_RATE_LIMIT=2 per second
SMART_ORDER_DELAY=0.5
```

### Runtime Configuration

Stored in `sandbox_config` table, accessed via:

```python
from database.sandbox_db import get_config, set_config

# Get config
value = get_config('equity_mis_leverage', default=5)

# Set config
set_config('equity_mis_leverage', '5')

# Triggers auto-reload for square-off times
if key.endswith('square_off_time'):
    reload_squareoff_schedule()
```

## Security Considerations

### 1. Data Isolation

- Separate database file (`db/sandbox.db`)
- No shared tables with live trading
- User_id scoping on all queries
- No broker API calls for order execution

### 2. Rate Limiting

- Order placement: 10 per second
- Smart orders: 2 per second
- API calls: 50 per second
- Enforced at service layer

### 3. Validation

- Symbol existence validation
- Quantity and price validation
- Sufficient funds check
- Product and exchange validation

## Performance Characteristics

### Response Times

| Operation | Target | Actual |
|-----------|--------|--------|
| Place Order | < 100ms | ~50ms |
| Get Positions | < 200ms | ~120ms |
| Execution Check | < 5s | ~3s |
| Square-off | < 30s | ~15s |

### Scalability

- Supports 100+ concurrent users
- Handles 1000+ orders per user
- Background thread processes 10 orders/second
- Database connection pooling (10-20 connections)

## Testing Strategy

### Unit Tests

```python
# Test order placement
def test_place_order():
    order_data = {...}
    success, response, code = place_order(order_data, user_id)
    assert success
    assert 'orderid' in response

# Test margin calculation
def test_calculate_margin():
    margin = calculate_margin(order_data, ltp=1200)
    assert margin == expected_margin

# Test position update
def test_update_position():
    update_position(trade_data, user_id)
    position = get_position(user_id, symbol, exchange)
    assert position.quantity == expected_qty
```

### Integration Tests

```python
# Test full order flow
def test_order_execution_flow():
    # 1. Enable sandbox mode
    toggle_analyzer_mode({'mode': True}, api_key)

    # 2. Place LIMIT order
    order_response = place_order({
        'symbol': 'RELIANCE',
        'price_type': 'LIMIT',
        'price': 1200,
        ...
    })

    # 3. Wait for execution
    time.sleep(6)  # Wait for execution thread

    # 4. Check order status
    order = get_order(order_response['orderid'])
    assert order.order_status == 'complete'

    # 5. Verify position created
    positions = get_positions(user_id)
    assert len(positions) > 0

    # 6. Verify funds deducted
    funds = get_funds(user_id)
    assert funds.used_margin > 0
```

## Deployment Checklist

### Pre-Deployment

- [ ] Run migration: `upgrade/migrate_sandbox.py`
- [ ] Verify database created: `db/sandbox.db`
- [ ] Check config entries in `sandbox_config` table
- [ ] Update `.env`: Set `SANDBOX_DATABASE_URL`
- [ ] Test analyzer toggle: Enable/disable works
- [ ] Verify threads start: Execution and squareoff running

### Post-Deployment

- [ ] Monitor thread health
- [ ] Check log files for errors
- [ ] Verify order execution (place test LIMIT order)
- [ ] Test square-off (set time to near future)
- [ ] Validate margin calculations
- [ ] Check fund reset (Sunday midnight)

## Monitoring and Maintenance

### Health Checks

```python
def check_system_health():
    """System health indicators"""
    return {
        'execution_thread': is_execution_running(),
        'squareoff_scheduler': is_squareoff_running(),
        'database_connection': test_db_connection(),
        'pending_orders_count': get_pending_orders_count(),
        'active_positions_count': get_active_positions_count(),
        'last_execution_check': get_last_execution_time()
    }
```

### Log Monitoring

```bash
# Watch sandbox logs
tail -f logs/sandbox.log

# Look for errors
grep ERROR logs/sandbox.log

# Monitor execution thread
grep "Execution thread" logs/sandbox.log

# Monitor squareoff
grep "Square-off" logs/sandbox.log
```

### Metrics to Track

1. **Order Metrics**:
   - Orders placed per hour
   - Execution success rate
   - Average execution time
   - Rejection rate and reasons

2. **Position Metrics**:
   - Open positions count
   - Average P&L per position
   - Square-off success rate

3. **System Metrics**:
   - Thread uptime
   - Database query performance
   - API rate limit compliance

## Future Enhancements

### Short Term (Next Release)

1. **Enhanced MTM**: Auto-update every 5 seconds (configurable)
2. **Basket Orders**: Multiple orders in single API call
3. **Split Orders**: Large quantity split into smaller orders
4. **Order Modifications**: Modify price/quantity of pending orders

### Medium Term

1. **Advanced Analytics**: P&L charts, strategy performance
2. **Risk Management**: Max position size, daily loss limits
3. **Backtesting Integration**: Historical simulation
4. **Strategy Templates**: Pre-built strategies to test

### Long Term

1. **Machine Learning**: Predict strategy performance
2. **Social Features**: Share strategies, leaderboards
3. **Mobile App**: Sandbox on mobile devices
4. **Advanced Orders**: OCO, Bracket, Cover orders

## Conclusion

The Sandbox Mode provides a complete, isolated, and realistic trading environment for testing strategies without financial risk. The architecture is designed for:

- **Safety**: Complete isolation from live trading
- **Realism**: Real market data and accurate execution
- **Performance**: Efficient thread management and batch processing
- **Maintainability**: Clean code structure and comprehensive logging
- **Scalability**: Supports multiple users and high order volumes

This design enables traders to confidently test and refine their strategies before deploying them with real capital.

---

**Document Version**: 1.0.4
**Last Updated**: October 2025
**Status**: Production Ready
