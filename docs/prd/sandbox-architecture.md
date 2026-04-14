# Sandbox Architecture

Detailed architecture documentation for the Sandbox (Analyzer Mode) paper trading system.

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           API LAYER                                          │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  /api/v1/placeorder  │  /api/v1/positions  │  /api/v1/orders           ││
│  │  /api/v1/closeposi   │  /api/v1/holdings   │  /api/v1/cancelorder      ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                              │ ANALYZER_MODE=True                            │
│                              ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                     sandbox_api.py Router                                ││
│  │         Routes to Sandbox managers instead of live broker                ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SANDBOX CORE                                         │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌─────────────┐  │
│  │ OrderManager  │  │PositionMgr   │  │ FundManager   │  │HoldingsMgr  │  │
│  │               │  │               │  │               │  │             │  │
│  │ • Validate    │  │ • Netting     │  │ • Margins     │  │ • T+1 Settl │  │
│  │ • Create      │  │ • MTM P&L     │  │ • Block/Free  │  │ • CNC→Hold  │  │
│  │ • Queue       │  │ • Close       │  │ • Credit/Debit│  │ • Sell Hold │  │
│  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘  └──────┬──────┘  │
│          │                  │                  │                  │         │
│          └──────────────────┼──────────────────┼──────────────────┘         │
│                             ▼                  ▼                             │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                       sandbox.db (SQLite)                                ││
│  │  sandbox_orders │ sandbox_positions │ sandbox_funds │ sandbox_holdings  ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      EXECUTION ENGINE                                        │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                WebSocket Execution Engine (Primary)                      ││
│  │  • Subscribes to real-time LTP via WebSocket proxy                      ││
│  │  • Immediate order matching on price updates                            ││
│  │  • Auto-fallback to polling if WebSocket unavailable                    ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                Polling Execution Engine (Fallback)                       ││
│  │  • Polls pending orders every 2 seconds                                 ││
│  │  • Fetches LTP from broker API                                          ││
│  │  • Matches orders sequentially                                          ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     SETTLEMENT & SQUARE-OFF                                  │
│  ┌─────────────────────────┐  ┌─────────────────────────┐                   │
│  │   Square-Off Manager    │  │    Settlement Jobs      │                   │
│  │   • MIS at 15:15 (NSE)  │  │    • T+1 at midnight    │                   │
│  │   • MIS at 23:30 (MCX)  │  │    • Expired F&O clean  │                   │
│  │   • Close at exchange   │  │    • Session boundary   │                   │
│  └─────────────────────────┘  └─────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Order Manager (`sandbox/order_manager.py`)

Handles all order operations with validation and margin checks.

**Key Methods:**

| Method | Description |
|--------|-------------|
| `place_order()` | Create and validate new order |
| `cancel_order()` | Cancel pending order |
| `modify_order()` | Modify pending order parameters |
| `get_order_book()` | Retrieve all orders |
| `get_trade_book()` | Get executed trades |

**Order States:**

```
PENDING → TRIGGER_PENDING → COMPLETE
    ↓           ↓
 CANCELLED   REJECTED
```

**Validation Flow:**

```python
def place_order(symbol, exchange, action, quantity, product, price_type, ...):
    # 1. Validate symbol exists
    if not validate_symbol(symbol, exchange):
        raise InvalidSymbolError()

    # 2. Calculate required margin
    margin = calculate_margin(symbol, quantity, product, action)

    # 3. Check CNC sell from holdings
    if product == 'CNC' and action == 'SELL':
        available = position_qty + holdings_qty
        if quantity > available:
            raise InsufficientHoldingsError()

    # 4. Block margin for BUY or margin requirement
    if action == 'BUY' or product in ['MIS', 'NRML']:
        fund_manager.block_margin(margin)

    # 5. Create order record
    order = SandboxOrders(...)

    # 6. For MARKET orders, execute immediately
    if price_type == 'MARKET':
        execute_order(order, current_ltp)

    return order.order_id
```

### 2. Position Manager (`sandbox/position_manager.py`)

Manages position tracking with netting and MTM calculations.

**Position Netting Logic:**

```
Case 1: Same Direction (Adding to position)
  Current: LONG 100 @ 500
  New BUY: 50 @ 510
  Result: LONG 150 @ avg((100*500 + 50*510)/150) = 503.33

Case 2: Opposite Direction (Partial close)
  Current: LONG 100 @ 500
  New SELL: 50 @ 520
  Result: LONG 50 @ 500, Realized P&L: 50*(520-500) = +1000

Case 3: Opposite Direction (Close and reverse)
  Current: LONG 100 @ 500
  New SELL: 150 @ 520
  Result: SHORT 50 @ 520
         Realized P&L (close): 100*(520-500) = +2000
```

**MTM Calculation:**

```python
def calculate_mtm(position, current_ltp):
    """Real-time MTM P&L calculation"""
    if position.quantity > 0:  # LONG
        unrealized_pnl = (current_ltp - position.average_price) * position.quantity
    else:  # SHORT
        unrealized_pnl = (position.average_price - current_ltp) * abs(position.quantity)

    return position.realized_pnl + unrealized_pnl
```

### 3. Fund Manager (`sandbox/fund_manager.py`)

Tracks virtual capital with margin blocking/release.

**Fund Structure:**

```python
class SandboxFunds:
    user_id: str
    available_balance: Decimal  # Default: 10,000,000 (1 Cr)
    used_margin: Decimal        # Blocked for open positions
    realized_pnl: Decimal       # Booked P&L from closed trades
```

**Margin Operations:**

| Operation | Effect |
|-----------|--------|
| `block_margin(amount)` | available - amount, used + amount |
| `release_margin(amount)` | available + amount, used - amount |
| `book_pnl(profit)` | available + profit, realized + profit |
| `book_pnl(loss)` | available - loss, realized - loss |

### 4. Holdings Manager (`sandbox/holdings_manager.py`)

Manages delivery holdings with T+1 settlement.

**Settlement Flow:**

```
Day T (Trading Day):
  09:15 - BUY CNC 100 SBIN @ 620
        → Creates CNC position (not holding yet)
        → Margin blocked: 62,000

Day T+1 (After Midnight):
  00:01 - T+1 Settlement Job runs
        → CNC position → Holdings conversion
        → Holdings record created
        → Margin transferred to holdings

Day T+1 (Trading Day):
  09:15 - Can now SELL from holdings
```

## Database Schema

### sandbox_orders

```sql
CREATE TABLE sandbox_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR NOT NULL,
    order_id VARCHAR UNIQUE NOT NULL,
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    action VARCHAR NOT NULL,        -- BUY, SELL
    quantity INTEGER NOT NULL,
    product VARCHAR NOT NULL,       -- MIS, CNC, NRML
    price_type VARCHAR NOT NULL,    -- MARKET, LIMIT, SL, SL-M
    price DECIMAL(18,2),
    trigger_price DECIMAL(18,2),
    filled_quantity INTEGER DEFAULT 0,
    average_price DECIMAL(18,2),
    status VARCHAR DEFAULT 'PENDING',
    status_message TEXT,
    order_timestamp DATETIME,
    exchange_timestamp DATETIME,
    strategy VARCHAR,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME
);
```

### sandbox_positions

```sql
CREATE TABLE sandbox_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    product VARCHAR NOT NULL,
    quantity INTEGER DEFAULT 0,
    average_price DECIMAL(18,2) DEFAULT 0,
    ltp DECIMAL(18,2),
    pnl DECIMAL(18,2) DEFAULT 0,
    realized_pnl DECIMAL(18,2) DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    UNIQUE(user_id, symbol, exchange, product)
);
```

### sandbox_holdings

```sql
CREATE TABLE sandbox_holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    quantity INTEGER NOT NULL,
    average_price DECIMAL(18,2) NOT NULL,
    ltp DECIMAL(18,2),
    pnl DECIMAL(18,2) DEFAULT 0,
    pnl_percent DECIMAL(8,2) DEFAULT 0,
    settlement_date DATE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    UNIQUE(user_id, symbol, exchange)
);
```

### sandbox_funds

```sql
CREATE TABLE sandbox_funds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR UNIQUE NOT NULL,
    available_balance DECIMAL(18,2) DEFAULT 10000000,
    used_margin DECIMAL(18,2) DEFAULT 0,
    realized_pnl DECIMAL(18,2) DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME
);
```

## API Integration

All standard OpenAlgo API endpoints work seamlessly when Analyzer Mode is enabled:

```python
# In analyzer mode, these automatically route to sandbox
client.placeorder(...)      # → sandbox/order_manager.place_order()
client.positions()          # → sandbox/position_manager.get_positions()
client.holdings()           # → sandbox/holdings_manager.get_holdings()
client.funds()              # → sandbox/fund_manager.get_funds()
```

## Related Documentation

| Document | Description |
|----------|-------------|
| [Sandbox PRD](./sandbox.md) | Main product requirements |
| [Execution Engine](./sandbox-execution-engine.md) | Order matching details |
| [Margin System](./sandbox-margin-system.md) | Margin calculation rules |
