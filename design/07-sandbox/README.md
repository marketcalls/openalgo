# 07 - Sandbox Architecture (Paper Trading)

## Overview

OpenAlgo's Sandbox/Analyzer mode provides a complete paper trading environment with ₹1 Crore virtual capital, realistic margin calculations, and auto square-off functionality. It runs completely isolated from live trading with its own database.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Sandbox Architecture                                   │
└──────────────────────────────────────────────────────────────────────────────┘

                              API Request
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         Mode Router                                           │
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  if analyzer_mode:                                                       │ │
│  │      → Route to Sandbox Services                                         │ │
│  │  else:                                                                   │ │
│  │      → Route to Live Broker Services                                     │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
                    │                               │
           Analyzer Mode                        Live Mode
                    │                               │
                    ▼                               ▼
┌───────────────────────────────┐    ┌───────────────────────────────┐
│      Sandbox Services          │    │      Live Broker Services      │
│                               │    │                               │
│  ┌─────────────────────────┐  │    │  ┌─────────────────────────┐  │
│  │    Order Manager        │  │    │  │   Broker Order API      │  │
│  │    (Virtual Orders)     │  │    │  │   (Real Orders)         │  │
│  └─────────────────────────┘  │    │  └─────────────────────────┘  │
│                               │    │                               │
│  ┌─────────────────────────┐  │    │                               │
│  │    Fund Manager         │  │    │                               │
│  │    (₹1 Cr Virtual)      │  │    │                               │
│  └─────────────────────────┘  │    │                               │
│                               │    │                               │
│  ┌─────────────────────────┐  │    │                               │
│  │    Execution Engine     │  │    │                               │
│  │    (Monitors Pending)   │  │    │                               │
│  └─────────────────────────┘  │    │                               │
│                               │    │                               │
│  ┌─────────────────────────┐  │    │                               │
│  │    Position Manager     │  │    │                               │
│  │    (Track P&L)          │  │    │                               │
│  └─────────────────────────┘  │    │                               │
│                               │    │                               │
│  ┌─────────────────────────┐  │    │                               │
│  │    Squareoff Manager    │  │    │                               │
│  │    (Auto close at EOD)  │  │    │                               │
│  └─────────────────────────┘  │    │                               │
└───────────────────────────────┘    └───────────────────────────────┘
                │
                ▼
┌───────────────────────────────┐
│       sandbox.db              │
│  (Isolated Database)          │
│                               │
│  • sandbox_orders             │
│  • sandbox_trades             │
│  • sandbox_positions          │
│  • sandbox_holdings           │
│  • sandbox_funds              │
│  • sandbox_config             │
└───────────────────────────────┘
```

## Core Components

### 1. Fund Manager

**Location:** `sandbox/fund_manager.py`

Manages virtual capital with realistic margin calculations.

```python
class FundManager:
    """Manages virtual funds for sandbox mode"""

    _lock = threading.Lock()  # Thread-safe operations

    def __init__(self, user_id):
        self.user_id = user_id
        self.starting_capital = Decimal(get_config('starting_capital', '10000000.00'))

    def initialize_funds(self):
        """Initialize ₹1 Crore starting capital for new user"""
        funds = SandboxFunds(
            user_id=self.user_id,
            total_capital=self.starting_capital,      # ₹1,00,00,000
            available_balance=self.starting_capital,
            used_margin=Decimal('0.00'),
            realized_pnl=Decimal('0.00'),
            unrealized_pnl=Decimal('0.00')
        )
```

**Capital Configuration:**
```python
# sandbox_config table
starting_capital = '10000000.00'  # ₹1 Crore
reset_day = 'Sunday'              # Weekly reset day
reset_time = '00:00'              # Reset time (IST)
```

### 2. Execution Engine

**Location:** `sandbox/execution_engine.py`

Monitors pending orders and executes based on real market data.

```python
class ExecutionEngine:
    """Executes pending orders based on market data"""

    def __init__(self):
        self.order_rate_limit = 10  # 10 orders/second
        self.api_rate_limit = 50    # 50 API calls/second
        self.batch_delay = 1.0      # 1 second between batches

    def check_and_execute_pending_orders(self):
        """Main execution loop - checks pending orders every 5 seconds"""
        # 1. Get all pending orders
        pending_orders = SandboxOrders.query.filter_by(order_status='open').all()

        # 2. Group by symbol for efficient quote fetching
        orders_by_symbol = {}
        for order in pending_orders:
            key = (order.symbol, order.exchange)
            orders_by_symbol.setdefault(key, []).append(order)

        # 3. Batch fetch quotes (multiquotes API)
        quote_cache = self._fetch_quotes_batch(symbols_list)

        # 4. Process orders respecting rate limits
        for order in pending_orders:
            quote = quote_cache.get((order.symbol, order.exchange))
            if quote:
                self._process_order(order, quote)
```

**Order Execution Logic:**
```
┌─────────────────────────────────────────────────────────────────┐
│                    Order Execution Flow                          │
└─────────────────────────────────────────────────────────────────┘

                    Pending Order
                         │
                         ▼
              ┌──────────────────────┐
              │   Fetch Live Quote   │
              │   (Multiquotes API)  │
              └──────────┬───────────┘
                         │
           ┌─────────────┴─────────────┐
           │                           │
           ▼                           ▼
    ┌─────────────┐            ┌─────────────┐
    │   MARKET    │            │    LIMIT    │
    │   Order     │            │   SL/SL-M   │
    └──────┬──────┘            └──────┬──────┘
           │                          │
           │ Execute                  │ Check Price
           │ immediately              │ Condition
           ▼                          ▼
    ┌─────────────┐         ┌──────────────────┐
    │ Create Trade│         │ LIMIT: LTP ≤ Px  │
    │ at LTP      │         │ SL: LTP ≥ Trigger│
    └─────────────┘         └────────┬─────────┘
                                     │ Condition Met
                                     ▼
                              ┌─────────────┐
                              │ Create Trade│
                              │ at LTP      │
                              └─────────────┘
```

### 3. Position Manager

**Location:** `sandbox/position_manager.py`

Tracks open positions with real-time P&L updates.

```python
class PositionManager:
    """Manages positions and P&L calculations"""

    def update_position(self, trade):
        """Update position after trade execution"""
        # Get or create position
        position = get_or_create_position(trade)

        if same_direction(position, trade):
            # Add to position (average up/down)
            new_qty = position.quantity + trade.quantity
            new_avg = (position.avg_price * position.quantity +
                      trade.price * trade.quantity) / new_qty
        else:
            # Reduce position (book profit/loss)
            if trade.quantity >= abs(position.quantity):
                # Close or flip position
                realized_pnl = calculate_pnl(position, trade)
                position.accumulated_realized_pnl += realized_pnl
```

### 4. Squareoff Manager

**Location:** `sandbox/squareoff_manager.py`

Automatically closes intraday positions at market close.

```python
class SquareoffManager:
    """Auto square-off at exchange timings"""

    SQUAREOFF_TIMES = {
        'NSE': '15:15',   # 3:15 PM
        'NFO': '15:25',   # 3:25 PM
        'MCX': '23:25',   # 11:25 PM
        'CDS': '17:00',   # 5:00 PM
    }

    def squareoff_intraday_positions(self):
        """Close all MIS positions at EOD"""
        # Get all MIS positions
        positions = SandboxPositions.query.filter(
            SandboxPositions.product == 'MIS',
            SandboxPositions.quantity != 0
        ).all()

        for position in positions:
            self._close_position(position)
```

## Database Schema

**Location:** `database/sandbox_db.py`

### Tables

```sql
-- Virtual Orders
CREATE TABLE sandbox_orders (
    id INTEGER PRIMARY KEY,
    orderid TEXT UNIQUE NOT NULL,
    user_id TEXT NOT NULL,
    strategy TEXT,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    action TEXT NOT NULL,           -- BUY, SELL
    quantity INTEGER NOT NULL,
    price DECIMAL(10,2),            -- Null for MARKET
    trigger_price DECIMAL(10,2),    -- For SL orders
    price_type TEXT NOT NULL,       -- MARKET, LIMIT, SL, SL-M
    product TEXT NOT NULL,          -- CNC, NRML, MIS
    order_status TEXT DEFAULT 'open', -- open, complete, cancelled, rejected
    average_price DECIMAL(10,2),
    filled_quantity INTEGER DEFAULT 0,
    pending_quantity INTEGER NOT NULL,
    margin_blocked DECIMAL(10,2),
    order_timestamp DATETIME,
    update_timestamp DATETIME
);

-- Executed Trades
CREATE TABLE sandbox_trades (
    id INTEGER PRIMARY KEY,
    tradeid TEXT UNIQUE NOT NULL,
    orderid TEXT NOT NULL,
    user_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    action TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    product TEXT NOT NULL,
    strategy TEXT,
    trade_timestamp DATETIME
);

-- Open Positions
CREATE TABLE sandbox_positions (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    product TEXT NOT NULL,
    quantity INTEGER NOT NULL,      -- Can be negative (short)
    average_price DECIMAL(10,2) NOT NULL,
    ltp DECIMAL(10,2),
    pnl DECIMAL(10,2) DEFAULT 0,
    pnl_percent DECIMAL(10,4) DEFAULT 0,
    accumulated_realized_pnl DECIMAL(10,2) DEFAULT 0,
    margin_blocked DECIMAL(15,2) DEFAULT 0,
    UNIQUE(user_id, symbol, exchange, product)
);

-- Holdings (T+1 settled)
CREATE TABLE sandbox_holdings (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    average_price DECIMAL(10,2) NOT NULL,
    ltp DECIMAL(10,2),
    pnl DECIMAL(10,2) DEFAULT 0,
    UNIQUE(user_id, symbol, exchange)
);

-- Virtual Funds
CREATE TABLE sandbox_funds (
    id INTEGER PRIMARY KEY,
    user_id TEXT UNIQUE NOT NULL,
    total_capital DECIMAL(15,2),
    available_balance DECIMAL(15,2),
    used_margin DECIMAL(15,2),
    realized_pnl DECIMAL(15,2),
    unrealized_pnl DECIMAL(15,2),
    last_reset_date DATETIME,
    reset_count INTEGER DEFAULT 0
);
```

## Margin Calculation

### Leverage by Product Type

| Product | Equity Leverage | F&O Leverage |
|---------|-----------------|--------------|
| CNC | 1x (100%) | N/A |
| MIS | 5x (20%) | 2x (50%) |
| NRML | 1x (100%) | 1x (100%) |

```python
def calculate_margin(symbol, exchange, price, quantity, product):
    """Calculate margin required for an order"""

    if product == 'CNC':
        # Full payment for delivery
        margin = price * quantity

    elif product == 'MIS':
        # Intraday leverage
        if is_option(symbol, exchange):
            margin = price * quantity * 0.5  # 50% for options
        elif is_future(symbol, exchange):
            margin = price * quantity * 0.5  # 50% for futures
        else:
            margin = price * quantity * 0.2  # 20% for equity

    elif product == 'NRML':
        # Carry forward (full margin)
        margin = price * quantity

    return margin
```

## Order Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Sandbox Order Flow                            │
└─────────────────────────────────────────────────────────────────┘

1. Place Order Request
        │
        ▼
┌─────────────────┐
│ Validate Order  │
│ (symbol, qty,   │
│  price type)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Check Available │
│ Margin          │
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
Sufficient  Insufficient
    │         │
    ▼         ▼
┌────────┐  ┌────────┐
│ Block  │  │ Reject │
│ Margin │  │ Order  │
└───┬────┘  └────────┘
    │
    ▼
┌─────────────────┐
│ Create Order    │
│ status='open'   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│ Execution Engine (Background - 5 sec)   │
│                                         │
│  1. Fetch live quotes                   │
│  2. Check price conditions              │
│  3. Execute if conditions met           │
│  4. Create trade                        │
│  5. Update position                     │
│  6. Update margin                       │
└─────────────────────────────────────────┘
```

## Auto-Reset Feature

Virtual capital resets weekly (configurable):

```python
# Configuration
reset_day = 'Sunday'
reset_time = '00:00'

def reset_user_funds():
    """Reset all users to starting capital"""
    SandboxFunds.query.update({
        'total_capital': starting_capital,
        'available_balance': starting_capital,
        'used_margin': Decimal('0.00'),
        'realized_pnl': Decimal('0.00'),
        'unrealized_pnl': Decimal('0.00'),
        'reset_count': SandboxFunds.reset_count + 1
    })

    # Clear all positions and holdings
    SandboxPositions.query.delete()
    SandboxHoldings.query.delete()
```

## Configuration

### Environment Variables

```bash
# Sandbox Database
SANDBOX_DATABASE_URL=sqlite:///db/sandbox.db

# Starting Capital (in INR)
SANDBOX_STARTING_CAPITAL=10000000

# Execution Engine
ORDER_RATE_LIMIT=10 per second
API_RATE_LIMIT=50 per second
```

### Sandbox Config Table

| Key | Default | Description |
|-----|---------|-------------|
| `starting_capital` | 10000000 | Virtual capital (₹1 Cr) |
| `reset_day` | Sunday | Weekly reset day |
| `reset_time` | 00:00 | Reset time (IST) |
| `auto_squareoff` | true | Enable auto square-off |

## Enabling Analyzer Mode

### Toggle via API

```python
# POST /auth/analyzer-toggle
{
    "enable": true  # or false
}
```

### Session State

```python
session['analyzer_mode'] = True

# All subsequent API calls routed to sandbox
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `sandbox/execution_engine.py` | Order execution background job |
| `sandbox/fund_manager.py` | Virtual capital management |
| `sandbox/position_manager.py` | Position tracking |
| `sandbox/squareoff_manager.py` | Auto square-off at EOD |
| `sandbox/order_manager.py` | Order CRUD operations |
| `sandbox/holdings_manager.py` | T+1 settlement logic |
| `database/sandbox_db.py` | Database models |
| `sandbox/catch_up_processor.py` | Settlement catch-up |
