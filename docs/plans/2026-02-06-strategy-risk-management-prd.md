# Strategy Risk Management & Position Tracking — PRD

**Date**: 2026-02-06
**Status**: Draft
**Scope**: Webhook + Chartink Strategies (V1)

---

## 1. Problem Statement

Currently, OpenAlgo strategies (Webhook and Chartink) have no local order/position tracking — everything is delegated to broker APIs. There is no strategy-level stoploss, target, or trailing stop. A trader running multiple strategies on the same symbol has no way to manage or view positions per strategy. All exits rely on `placesmartorder(position_size=0)` which closes ALL positions for a symbol across the entire account, not just the strategy's position.

### What's Missing

- Strategy-level order tracking (no link between a Strategy and its Orders)
- Strategy-level position tracking (no per-strategy position state)
- Strategy-level PnL calculation (no per-strategy profit tracking)
- Stoploss / Target / Trailing Stop automation
- Local order/trade/position database for live trading
- Persistence across application restarts
- Strategy-isolated position close (without affecting other strategies)

---

## 2. Goals

1. **Strategy-level risk management**: Configurable stoploss, target, and trailing stop at both strategy and symbol level
2. **Strategy-level position tracking**: Track positions, orders, and trades per strategy in local database
3. **Live PnL updates**: Real-time unrealized PnL via centralized feed handler (WebSocket push + REST polling fallback)
4. **Strategy-isolated exits**: Close individual or all positions for a strategy without affecting other strategies or manual positions
5. **Persistence**: All state survives application restarts
6. **Unified dashboard**: Single page to view, manage, and control all strategy positions

---

## 3. Scope

### In Scope (V1)

- Webhook strategies (`blueprints/strategy.py`)
- Chartink strategies (`blueprints/chartink.py`)
- Strategy-level defaults with symbol-level overrides for SL/target/trailing stop/breakeven
- Percentage and Points as value modes
- Simple trailing stop (trail from peak price, only moves in favorable direction)
- Breakeven: move SL to entry when profit threshold hit (equity, single option, per-leg)
- Always MARKET exit orders on trigger
- Automatic order tracking (orders placed via webhooks)
- Manual position close (individual + all strategy positions + position group)
- Futures order mapping: single futures contract (current_month, next_month) with auto-split
- Options order mapping: single option (ATM/ITM/OTM) and multi-leg (presets + custom)
- Mixed futures + options legs in multi-leg mode (covered calls, protective puts, etc.)
- Relative expiry resolution (current_week, next_week, current_month, next_month)
- Per-leg and Combined P&L risk modes for multi-leg orders
- Product type validation (CNC/MIS for equity, NRML/MIS for F&O)
- Freeze quantity auto-split via SplitOrder service (configured in /admin)
- Tick size rounding for all computed prices (from symbol service)
- Lot size validation (from symbol service, never hardcoded)
- Strategy Dashboard page with activate/deactivate controls
- Strategy-level orderbook, tradebook, positions in drawer views
- Real-time order status tracking on every entry/exit (SocketIO push)
- Exit status badges showing how each exit happened (SL/TGT/TSL/BE-SL/C-SL/C-TGT/C-TSL/Manual)
- Live SL, Target, TSL prices updating in real-time in UI
- Strategy-level PnL shown in real-time (per-leg, combined, strategy aggregate)
- Daily PnL snapshots
- Toast notifications + Telegram alerts for risk events
- MIS auto square-off at configurable time (default 15:15 IST)
- Underlying search selector with typeahead for F&O symbol mapping
- Master contract download prerequisite check (same as /python strategies)
- Restart recovery with broker position reconciliation
- SQLite concurrency safeguards (WAL mode, batched writes, position locks)
- Webhook deduplication (reject identical signals within configurable window)
- Position state machine (active/exiting/pending_entry) for race condition prevention
- All timestamps displayed in IST

### Out of Scope (Future)

- Python strategies (isolated subprocess model)
- Flow workflows (separate execution engine)
- Step trailing stop
- Absolute price mode for SL/target
- LIMIT exit orders
- Manual order association (retroactive linking)
- Strategy-level margin tracking
- Calendar spreads / diagonal spreads (different expiry per leg — multi-leg uses common expiry in V1)

---

## 4. Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| SL/target scope | Strategy defaults + symbol overrides | DRY configuration — set once, override where needed |
| Value modes | Percentage (%) + Points | Absolute prices don't work as strategy defaults across different symbols |
| Trailing stop model | Simple trail from peak | Covers 90% of use cases; step trailing adds complexity for V2 |
| Breakeven | Per-leg only (not combined) | Breakeven is meaningful per individual position, not across aggregated P&L |
| Exit execution | Pluggable strategy pattern, MARKET default | Designed for future execution types (mid order, order chasing, etc.) |
| Order tracking | Automatic only | Webhook orders are reliably tagged; manual association adds complexity |
| Exit mechanism | `placeorder` with tracked qty | `placesmartorder(position_size=0)` exits ALL positions — unsafe for multi-strategy |
| PnL granularity | Trade-level + daily snapshots | Enables equity curves and drawdown analysis with minimal storage |
| Market data engine | Reuse sandbox dual-engine | WebSocket CRITICAL priority + REST polling fallback — production-proven |
| Fill price source | `average_price` from OrderStatus | Actual execution price, not order price |
| OrderStatus polling | 1 req/sec (rate limit respected) | Single background thread, LIFO queue for priority |
| Options mapping | Order mode per symbol mapping | Same webhook signal can map to equity, single option, or multi-leg |
| Expiry resolution | Relative (current_week, etc.) | Self-maintaining — no manual update after each expiry |
| Multi-leg presets | Presets + custom | Presets cover 80% cases; custom for power users |
| Multi-leg risk | Per-leg + Combined (user choice) | Different strategies need different risk approaches |
| Freeze qty | Auto-split via SplitOrder | Centrally configured in /admin; transparent to user |
| Tick size | From symbol service | All computed prices rounded to valid tick; ensures order acceptance |
| Lot size | From symbol service | NEVER hardcoded; exchanges revise periodically |
| Position re-entry | New row per entry (no UNIQUE constraint) | Preserves trade history; no manual deletion needed for re-entry |
| Position state | State machine (active/exiting/pending_entry) | Prevents race conditions between concurrent entries and exits |
| SQLite concurrency | WAL mode + busy_timeout + batched writes | Handles multi-thread writes safely; production should consider PostgreSQL |
| Combined group | StrategyPositionGroup table | Stores combined_peak_pnl, group_status; defers triggers until all legs fill |
| Poller queue | Priority queue (exits before entries) | Exit confirmation is time-critical; entry can wait |
| MIS square-off | Configurable per strategy (default 15:15 IST) | Matches broker auto-square-off window; prevents forced broker exits |
| Webhook dedup | Time-window deduplication (5s default) | Prevents double-orders from signal source retries |
| Futures support | `futures` order mode + futures legs in multi_leg | Enables hedging strategies (covered calls, protective puts) |
| Product types | CNC/MIS for equity; NRML/MIS for F&O | Enforced at config + order time; exchange-mandated rules |

---

## 5. Database Schema

All tables stored in `db/openalgo.db` for persistence across restarts.

### 5.1 Strategy Table Additions (Existing)

Extend `Strategy` and `ChartinkStrategy` tables:

```
default_stoploss_type      VARCHAR(10)   -- 'percentage', 'points', or NULL (disabled)
default_stoploss_value     FLOAT         -- e.g., 2.0 for 2% or 50 for 50 points
default_target_type        VARCHAR(10)
default_target_value       FLOAT
default_trailstop_type     VARCHAR(10)
default_trailstop_value    FLOAT
default_breakeven_type     VARCHAR(10)   -- 'percentage', 'points', or NULL (disabled)
default_breakeven_threshold FLOAT
risk_monitoring            VARCHAR(10)   DEFAULT 'active'  -- 'active' or 'paused'
auto_squareoff_time        VARCHAR(5)    DEFAULT '15:15'   -- IST, for MIS positions (HH:MM format)
```

**Auto Square-Off Time**: Configurable per strategy. Default is `15:15` IST (15 minutes before NSE market close). Only applies to MIS (intraday) positions. CNC and NRML positions are not auto-squared-off. All times in the system are displayed in IST.

### 5.2 Symbol Mapping Additions (Existing)

Extend `StrategySymbolMapping` and `ChartinkSymbolMapping` tables:

```
-- Order Mode
order_mode          VARCHAR(15) DEFAULT 'equity'  -- 'equity', 'futures', 'single_option', 'multi_leg'

-- Options Configuration (for single_option and multi_leg modes)
underlying          VARCHAR(50)           -- e.g., 'NIFTY', 'BANKNIFTY'
underlying_exchange VARCHAR(15)           -- e.g., 'NSE_INDEX', 'BSE_INDEX'
expiry_type         VARCHAR(15)           -- 'current_week', 'next_week', 'current_month', 'next_month'

-- Single Option fields
offset              VARCHAR(10)           -- 'ATM', 'ITM1'-'ITM40', 'OTM1'-'OTM40'
option_type         VARCHAR(2)            -- 'CE' or 'PE'

-- Multi-Leg Configuration
risk_mode           VARCHAR(10)           -- 'per_leg' or 'combined'
preset              VARCHAR(20)           -- 'straddle', 'strangle', 'iron_condor', 'bull_call_spread', 'bear_put_spread', 'custom'
legs_config         JSON                  -- array of leg objects (see Section 7.3)
combined_stoploss_type    VARCHAR(10)
combined_stoploss_value   FLOAT
combined_target_type      VARCHAR(10)
combined_target_value     FLOAT
combined_trailstop_type   VARCHAR(10)
combined_trailstop_value  FLOAT

-- Risk Parameters (equity mode or single_option per-leg; nullable = use strategy default)
stoploss_type       VARCHAR(10)
stoploss_value      FLOAT
target_type         VARCHAR(10)
target_value        FLOAT
trailstop_type      VARCHAR(10)
trailstop_value     FLOAT

-- Breakeven (equity, single_option, per-leg mode)
breakeven_type      VARCHAR(10)           -- 'percentage' or 'points', NULL = disabled
breakeven_threshold FLOAT
```

**Legs Config JSON Structure** (for multi_leg mode — supports both options and futures legs):
```json
[
    {
        "leg_type": "option",
        "offset": "OTM4",
        "option_type": "CE",
        "action": "SELL",
        "quantity": 75,
        "product_type": "NRML",
        "stoploss_type": "percentage",
        "stoploss_value": 30,
        "target_type": "percentage",
        "target_value": 50,
        "trailstop_type": "points",
        "trailstop_value": 10,
        "breakeven_type": "percentage",
        "breakeven_threshold": 20
    },
    {
        "leg_type": "futures",
        "expiry_type": "current_month",
        "action": "BUY",
        "quantity": 75,
        "product_type": "NRML",
        "stoploss_type": "percentage",
        "stoploss_value": 2,
        "target_type": "percentage",
        "target_value": 5,
        "trailstop_type": null,
        "trailstop_value": null,
        "breakeven_type": null,
        "breakeven_threshold": null
    }
]
```

**Leg Types**:
- `option`: Requires `offset`, `option_type` (CE/PE). Resolved to option symbol at trigger time.
- `futures`: Requires `expiry_type` (current_month/next_month). Resolved to futures symbol at trigger time. No `offset` or `option_type`.

**Product Type Rules** (enforced at configuration time and order placement):

| Instrument Type | Allowed Product Types | Default |
|----------------|----------------------|---------|
| Equity (NSE/BSE) | CNC, MIS | MIS |
| Futures (NFO/BFO/MCX/CDS) | NRML, MIS | NRML |
| Options (NFO/BFO/MCX/CDS) | NRML, MIS | NRML |

- **MIS** (Intraday): Auto square-off at configured time (default 15:15 IST, user-configurable per strategy)
- **CNC** (Cash & Carry): Delivery-based, no auto square-off
- **NRML** (Normal): Carry forward, no auto square-off (but subject to exchange expiry)

### 5.3 StrategyOrder (New)

Tracks every order placed by a strategy.

```sql
CREATE TABLE strategy_order (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id       INTEGER NOT NULL,
    strategy_type     VARCHAR(10) NOT NULL,   -- 'webhook' or 'chartink'
    user_id           VARCHAR(255) NOT NULL,
    orderid           VARCHAR(50) NOT NULL,   -- broker order ID
    symbol            VARCHAR(50) NOT NULL,
    exchange          VARCHAR(10) NOT NULL,
    action            VARCHAR(4) NOT NULL,    -- BUY or SELL
    quantity          INTEGER NOT NULL,
    product_type      VARCHAR(10) NOT NULL,   -- MIS, CNC, NRML
    price_type        VARCHAR(10) NOT NULL,   -- MARKET, LIMIT, SL, SL-M
    price             FLOAT DEFAULT 0,
    trigger_price     FLOAT DEFAULT 0,
    order_status      VARCHAR(20) NOT NULL,   -- pending, open, complete, rejected, cancelled
    average_price     FLOAT DEFAULT 0,        -- from OrderStatus (fill price)
    filled_quantity   INTEGER DEFAULT 0,
    is_entry          BOOLEAN DEFAULT TRUE,
    exit_reason       VARCHAR(20),            -- NULL for entries; stoploss/target/trailstop/manual/squareoff
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 5.4 StrategyPosition (New)

Each entry creates a new row. Active positions queried via `WHERE quantity > 0`. No UNIQUE constraint — this allows re-entry after exit without requiring manual deletion of closed rows, and preserves full trade history.

```sql
CREATE TABLE strategy_position (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id           INTEGER NOT NULL,
    strategy_type         VARCHAR(10) NOT NULL,
    user_id               VARCHAR(255) NOT NULL,
    symbol                VARCHAR(50) NOT NULL,
    exchange              VARCHAR(10) NOT NULL,
    product_type          VARCHAR(10) NOT NULL,
    action                VARCHAR(4) NOT NULL,   -- BUY (long) or SELL (short)
    quantity              INTEGER NOT NULL,       -- always positive; direction from action
    intended_quantity     INTEGER NOT NULL,       -- original intended qty (for partial fill detection)
    average_entry_price   FLOAT NOT NULL,         -- weighted average from fills
    ltp                   FLOAT DEFAULT 0,        -- last traded price (live updated)
    unrealized_pnl        FLOAT DEFAULT 0,
    unrealized_pnl_pct    FLOAT DEFAULT 0,
    peak_price            FLOAT DEFAULT 0,        -- highest (long) or lowest (short) since entry
    position_state        VARCHAR(15) DEFAULT 'active',  -- 'active', 'exiting', 'pending_entry'
    stoploss_type         VARCHAR(10),            -- resolved effective value
    stoploss_value        FLOAT,
    stoploss_price        FLOAT,                  -- computed from average_entry_price
    target_type           VARCHAR(10),
    target_value          FLOAT,
    target_price          FLOAT,
    trailstop_type        VARCHAR(10),
    trailstop_value       FLOAT,
    trailstop_price       FLOAT,                  -- moves with peak_price
    breakeven_type        VARCHAR(10),             -- 'percentage' or 'points', NULL = disabled
    breakeven_threshold   FLOAT,
    breakeven_activated   BOOLEAN DEFAULT FALSE,   -- one-time flag
    tick_size             FLOAT DEFAULT 0.05,      -- from symbol service, for price rounding
    position_group_id     VARCHAR(36),             -- UUID, links legs in combined P&L mode (NULL for equity/per_leg)
    risk_mode             VARCHAR(10),             -- 'per_leg' or 'combined' (NULL for equity/futures)
    realized_pnl          FLOAT DEFAULT 0,         -- accumulated from partial exits
    exit_reason           VARCHAR(20),             -- NULL while open; stoploss/target/trailstop/breakeven_sl/manual/squareoff
    exit_detail           VARCHAR(30),             -- granular: leg_sl/leg_target/leg_tsl/combined_sl/combined_target/combined_tsl/breakeven_sl/manual
    exit_price            FLOAT,                   -- average exit fill price
    closed_at             DATETIME,                -- timestamp when quantity reached 0
    created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Composite index for fast active position lookups (replaces UNIQUE constraint)
CREATE INDEX idx_strategy_position_active
    ON strategy_position(strategy_id, strategy_type, symbol, exchange, product_type)
    WHERE quantity > 0;
```

**Position State Machine**:
```
pending_entry → active → exiting → closed (quantity=0)
                  │                    │
                  └─── re-entry ───────┘ (new row created)
```

- `pending_entry`: Entry order placed, awaiting fill. Webhook handler rejects new signals for this symbol.
- `active`: Position filled, risk engine monitoring. Triggers can fire.
- `exiting`: Exit order placed, awaiting fill. Webhook handler rejects new entries. Risk engine skips trigger checks.
- `closed`: `quantity = 0`, `closed_at` set. Row is historical. New entry creates a NEW row.

**Partial Fill Detection**: If `quantity < intended_quantity`, the UI shows a warning badge "1800/3600 filled" and a `strategy_partial_fill_warning` SocketIO event + Telegram alert is emitted.

### 5.5 StrategyTrade (New)

Every filled trade for audit trail and PnL calculation.

```sql
CREATE TABLE strategy_trade (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id       INTEGER NOT NULL,
    strategy_type     VARCHAR(10) NOT NULL,
    user_id           VARCHAR(255) NOT NULL,
    orderid           VARCHAR(50) NOT NULL,
    symbol            VARCHAR(50) NOT NULL,
    exchange          VARCHAR(10) NOT NULL,
    action            VARCHAR(4) NOT NULL,
    quantity          INTEGER NOT NULL,
    price             FLOAT NOT NULL,          -- average_price from OrderStatus
    trade_type        VARCHAR(5) NOT NULL,     -- 'entry' or 'exit'
    exit_reason       VARCHAR(20),             -- NULL for entries
    pnl               FLOAT DEFAULT 0,         -- per-trade realized PnL (exit trades only)
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 5.6 StrategyDailyPnL (New)

End-of-day snapshots for analytics.

```sql
CREATE TABLE strategy_daily_pnl (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id           INTEGER NOT NULL,
    strategy_type         VARCHAR(10) NOT NULL,
    user_id               VARCHAR(255) NOT NULL,
    date                  DATE NOT NULL,
    realized_pnl          FLOAT DEFAULT 0,
    unrealized_pnl        FLOAT DEFAULT 0,
    total_pnl             FLOAT DEFAULT 0,
    total_trades          INTEGER DEFAULT 0,
    winning_trades        INTEGER DEFAULT 0,
    losing_trades         INTEGER DEFAULT 0,
    gross_profit          FLOAT DEFAULT 0,         -- sum of PnL from winning trades
    gross_loss            FLOAT DEFAULT 0,         -- sum of PnL from losing trades (stored as positive)
    max_trade_profit      FLOAT DEFAULT 0,         -- best single trade PnL of the day
    max_trade_loss        FLOAT DEFAULT 0,         -- worst single trade PnL of the day (stored as positive)
    cumulative_pnl        FLOAT DEFAULT 0,         -- running total from strategy inception
    peak_cumulative_pnl   FLOAT DEFAULT 0,         -- highest cumulative PnL reached
    drawdown              FLOAT DEFAULT 0,         -- current drawdown from peak (₹)
    drawdown_pct          FLOAT DEFAULT 0,         -- current drawdown from peak (%)
    max_drawdown          FLOAT DEFAULT 0,         -- max drawdown seen up to this date (₹)
    max_drawdown_pct      FLOAT DEFAULT 0,         -- max drawdown seen up to this date (%)
    created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(strategy_id, strategy_type, date)
);
```

### 5.7 StrategyPositionGroup (New)

Group-level state for combined P&L mode. Tracks combined peak PnL, group fill status, and shared state across legs.

```sql
CREATE TABLE strategy_position_group (
    id                    VARCHAR(36) PRIMARY KEY,  -- UUID (same as position_group_id in StrategyPosition)
    strategy_id           INTEGER NOT NULL,
    strategy_type         VARCHAR(10) NOT NULL,
    user_id               VARCHAR(255) NOT NULL,
    symbol_mapping_id     INTEGER NOT NULL,         -- reference to the symbol mapping that created this group
    expected_legs         INTEGER NOT NULL,          -- total legs expected (from legs_config)
    filled_legs           INTEGER DEFAULT 0,         -- legs with complete fills
    group_status          VARCHAR(15) DEFAULT 'filling', -- 'filling', 'active', 'exiting', 'closed', 'failed_exit'
    combined_peak_pnl     FLOAT DEFAULT 0,           -- highest combined PnL reached (for trailing stop)
    combined_pnl          FLOAT DEFAULT 0,           -- current combined unrealized PnL
    created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Group Status Machine**:
```
filling → active → exiting → closed
                      │
                      └→ failed_exit (partial exit rejected — needs manual intervention)
```

- `filling`: Not all legs have filled yet. Combined trigger checks are DEFERRED until all legs fill.
- `active`: All legs filled. Combined SL/target/trail checks are active.
- `exiting`: Combined trigger fired, exit orders placed for all legs.
- `closed`: All legs exited successfully.
- `failed_exit`: One or more leg exit orders were rejected. CRITICAL alert to user. "Retry Exit" button shown in UI.

---

## 6. Risk Parameter Resolution

When processing an order for a symbol, resolve effective risk parameters:

```python
def _resolve(override, default):
    """Return override if explicitly set (not None), else fall back to default.
    IMPORTANT: Uses 'is not None' instead of 'or' because 0.0 is a valid
    deliberate value (e.g., disable SL for this symbol). Python 'or' treats
    0.0 as falsy and would incorrectly fall through to the default.
    """
    return override if override is not None else default

def resolve_risk_params(strategy, symbol_mapping):
    """Symbol override takes priority over strategy default."""
    return {
        'stoploss_type':       _resolve(symbol_mapping.stoploss_type,       strategy.default_stoploss_type),
        'stoploss_value':      _resolve(symbol_mapping.stoploss_value,      strategy.default_stoploss_value),
        'target_type':         _resolve(symbol_mapping.target_type,         strategy.default_target_type),
        'target_value':        _resolve(symbol_mapping.target_value,        strategy.default_target_value),
        'trailstop_type':      _resolve(symbol_mapping.trailstop_type,      strategy.default_trailstop_type),
        'trailstop_value':     _resolve(symbol_mapping.trailstop_value,     strategy.default_trailstop_value),
        'breakeven_type':      _resolve(symbol_mapping.breakeven_type,      strategy.default_breakeven_type),
        'breakeven_threshold': _resolve(symbol_mapping.breakeven_threshold, strategy.default_breakeven_threshold),
    }
```

### Price Computation from average_price

**Long position (action = BUY):**

```
stoploss_price  = average_price × (1 - stoploss_value / 100)     [percentage]
                = average_price - stoploss_value                   [points]
target_price    = average_price × (1 + target_value / 100)        [percentage]
                = average_price + target_value                     [points]
trailstop_price = peak_price × (1 - trailstop_value / 100)       [percentage]
                = peak_price - trailstop_value                     [points]
```

**Short position (action = SELL):**

```
stoploss_price  = average_price × (1 + stoploss_value / 100)     [percentage]
                = average_price + stoploss_value                   [points]
target_price    = average_price × (1 - target_value / 100)        [percentage]
                = average_price - target_value                     [points]
trailstop_price = trough_price × (1 + trailstop_value / 100)     [percentage]
                = trough_price + trailstop_value                   [points]
```

---

## 7. Options Order Mapping

### 7.1 Order Modes

Each symbol mapping has an `order_mode` that determines how webhook signals are translated to orders:

| Order Mode | Description | Service Used |
|-----------|-------------|--------------|
| `equity` | Direct equity order | `placeorder` |
| `futures` | Single futures contract (current/next month) | `placeorder` + `SplitOrder` if qty > freeze_qty |
| `single_option` | Single options leg | `OptionsOrder` + `SplitOrder` if qty > freeze_qty |
| `multi_leg` | Multi-leg strategy (options + futures mixed) | `OptionsMultiOrder` + `SplitOrder` per leg if needed |

### 7.2 Symbol Mapping — Futures Configuration

```
order_mode:         'futures'
underlying:         'NIFTY'                    -- underlying symbol
underlying_exchange:'NSE_INDEX'                -- underlying exchange (for LTP)
expiry_type:        'current_month'            -- 'current_month' or 'next_month'
quantity:           75                         -- total quantity (will auto-split if > freeze_qty)
product_type:       'NRML'                     -- NRML or MIS only
```

**On webhook BUY signal**: Resolve the futures symbol (e.g., `NIFTY28FEB25FUT`) from underlying + expiry_type at trigger time, then place order via `placeorder` (auto-split if needed).
**On webhook SELL signal**: Sell/close the position using tracked quantity via `placeorder`.

**Futures symbol resolution**:
```python
def resolve_futures_symbol(underlying, exchange, expiry_type):
    """Resolve futures symbol from underlying + relative expiry."""
    expiry_date = resolve_expiry(underlying, exchange, expiry_type, api_key, instrumenttype='futures')
    return f"{underlying}{expiry_date}FUT"  # e.g., NIFTY28FEB25FUT
```

### 7.3 Symbol Mapping — Single Option Configuration

```
order_mode:         'single_option'
underlying:         'NIFTY'                    -- underlying symbol
underlying_exchange:'NSE_INDEX'                -- underlying exchange
expiry_type:        'current_week'             -- relative: current_week/next_week/current_month/next_month
offset:             'ATM'                      -- ATM, ITM1-ITM40, OTM1-OTM40
option_type:        'CE'                       -- CE or PE
quantity:           75                         -- total quantity (will auto-split if > freeze_qty)
product_type:       'NRML'                     -- MIS or NRML
```

**On webhook BUY signal**: Buy the resolved option (e.g., NIFTY28FEB2625000CE)
**On webhook SELL signal**: Sell/close the position using tracked quantity via `placeorder`

### 7.4 Symbol Mapping — Multi-Leg Configuration

```
order_mode:         'multi_leg'
underlying:         'NIFTY'
underlying_exchange:'NSE_INDEX'
expiry_type:        'current_week'
risk_mode:          'per_leg' | 'combined'     -- user choice
preset:             'iron_condor' | 'straddle' | 'strangle' | 'bull_call_spread' | 'bear_put_spread' | 'custom'
legs: [
    {
        leg_type:     'option',     -- 'option' or 'futures'
        offset:       'OTM4',
        option_type:  'CE',
        action:       'SELL',
        quantity:     75,
        product_type: 'NRML',
        -- Per-leg risk (used in per_leg mode, or always for breakeven):
        stoploss_type:     'percentage',
        stoploss_value:    30,
        target_type:       'percentage',
        target_value:      50,
        trailstop_type:    'points',
        trailstop_value:   10,
        breakeven_type:    'percentage',    -- percentage or points
        breakeven_threshold: 20             -- move SL to entry when +20% profit
    },
    {
        offset:       'OTM4',
        option_type:  'PE',
        action:       'SELL',
        quantity:     75,
        ...per-leg risk params...
    },
    {
        offset:       'OTM6',
        option_type:  'CE',
        action:       'BUY',
        quantity:     75,
        ...per-leg risk params...
    },
    {
        offset:       'OTM6',
        option_type:  'PE',
        action:       'BUY',
        quantity:     75,
        ...per-leg risk params...
    }
]
-- Combined risk (used in combined mode only):
combined_stoploss_type:     'points',
combined_stoploss_value:    5000,          -- exit all legs when combined loss > ₹5000
combined_target_type:       'points',
combined_target_value:      8000,          -- exit all legs when combined profit > ₹8000
combined_trailstop_type:    'percentage',
combined_trailstop_value:   20             -- trail from peak combined profit
```

### 7.5 Preset Templates

When user selects a preset, the legs are auto-populated:

| Preset | Legs Auto-Generated |
|--------|-------------------|
| **Straddle** | SELL ATM CE + SELL ATM PE |
| **Strangle** | SELL OTM2 CE + SELL OTM2 PE (width configurable) |
| **Iron Condor** | SELL OTM4 CE + SELL OTM4 PE + BUY OTM6 CE + BUY OTM6 PE (widths configurable) |
| **Bull Call Spread** | BUY ATM CE + SELL OTM2 CE |
| **Bear Put Spread** | BUY ATM PE + SELL OTM2 PE |
| **Custom** | User adds 1-6 legs manually (mix of options + futures) |

Preset selection pre-fills the leg form. User can modify any field after selection.

**Mixed Futures + Options Example** (Covered Call):
```
Preset: custom
Legs:
  Leg 1: { leg_type: "futures", expiry_type: "current_month", action: "BUY", quantity: 75, product_type: "NRML" }
  Leg 2: { leg_type: "option", offset: "OTM2", option_type: "CE", action: "SELL", quantity: 75, product_type: "NRML" }
```

This enables strategies that combine futures hedging with options premium collection (covered calls, protective puts, synthetic positions).

### 7.6 Risk Modes for Multi-Leg

#### Per-Leg Mode (`risk_mode = 'per_leg'`)
- Each leg tracked as an independent `StrategyPosition`
- Each leg has its own SL, target, trailing stop, breakeven threshold
- Each leg triggers and exits independently
- No `position_group_id` needed

#### Combined P&L Mode (`risk_mode = 'combined'`)
- All legs linked via `position_group_id` in `StrategyPosition`
- Combined SL/target defined on aggregate unrealized P&L across all legs
- When combined SL or target triggers → ALL legs in the group exit together via `placeorder` per leg
- Combined trailing stop trails from peak combined profit
- Individual leg breakeven NOT available in combined mode
- Individual leg SL/target/trail NOT active in combined mode (only combined triggers)

### 7.7 Breakeven — Move SL to Entry

Available for: Equity positions, single option positions, and individual legs in per-leg mode.
NOT available for: Combined P&L mode.

```
Configuration:
    breakeven_type:      'percentage' | 'points'
    breakeven_threshold: float         -- trigger threshold

Behavior:
    Long position — entry at ₹800, SL at ₹784:
        If breakeven_type = 'percentage', breakeven_threshold = 1.5:
            When LTP >= 800 × 1.015 = ₹812 → move SL to ₹800 (entry price)
        If breakeven_type = 'points', breakeven_threshold = 12:
            When LTP >= 800 + 12 = ₹812 → move SL to ₹800 (entry price)

    Short position — entry at ₹800, SL at ₹816:
        When LTP <= threshold below entry → move SL to ₹800 (entry price)

    Once breakeven is activated:
        - stoploss_price is set to average_entry_price
        - breakeven_activated = TRUE (flag in StrategyPosition)
        - Trailing stop continues to operate independently from peak_price
        - Effective stop = max(stoploss_price, trailstop_price) for longs
                         = min(stoploss_price, trailstop_price) for shorts
        - This ensures the tighter (more protective) stop always applies
        - Breakeven is a one-time move; once activated it doesn't revert
```

**Breakeven + Trail Interaction**: After breakeven moves SL to entry price, the trailing stop may still be below entry if the trail value is wide. The effective stop is always the most protective (closest to LTP):
- Long: `effective_stop = max(stoploss_price, trailstop_price)`
- Short: `effective_stop = min(stoploss_price, trailstop_price)`

The trigger check uses this effective stop. The `exit_detail` is attributed to whichever stop was tighter at trigger time.

### 7.8 Tick Size Handling

All computed SL/target/trailing stop/breakeven prices MUST be rounded to the instrument's tick size.

```python
def round_to_tick(price, tick_size):
    """Round price to nearest valid tick."""
    return round(round(price / tick_size) * tick_size, 10)

# Example: tick_size = 0.05
# SL computed as 784.03 → rounded to 784.05
# Target computed as 840.07 → rounded to 840.05
```

**Tick size source**: Fetched from Symbol service (`get_symbol()`) which returns `tick_size` field.
**Lot size source**: Fetched from Symbol service (`get_symbol()`) which returns `lotsize` field.
Both cached per symbol to avoid repeated API calls.

**Lot size enforcement**: For options, quantity must be a multiple of lot size. The UI validates this at configuration time, and the backend rejects non-multiples.

```python
symbol_info = get_symbol(symbol, exchange, api_key)
tick_size = symbol_info['data']['tick_size']    # from symbol service
lot_size = symbol_info['data']['lotsize']       # from symbol service (NEVER hardcoded)
freeze_qty = get_freeze_qty_from_admin(symbol)  # from /admin config
```

**No hardcoding**: Lot sizes change periodically (exchange revisions). Always fetch dynamically from the symbol service which reads from the broker's master contract database.

### 7.9 Freeze Quantity & Auto-Split

Freeze quantity is the maximum order size allowed by the exchange in a single order.

**Source**: Centrally configured in `/admin` section.

**Behavior**:
```
Order quantity = 3600, freeze_qty = 1800:
  → Auto-split into 2 orders of 1800 each
  → Uses SplitOrder service
  → Each split order gets its own orderid
  → All split orders tracked as StrategyOrder rows
  → All linked to the same StrategyPosition

Order quantity = 2000, freeze_qty = 1800:
  → Split into: 1800 + 200
  → 2 StrategyOrder rows, same StrategyPosition
```

**Exit auto-split**: When closing a position with qty > freeze_qty, the exit is also auto-split.

```
Position: NIFTY CE, qty = 3600, freeze_qty = 1800
  → Close All: 2 exit orders of 1800 each via SplitOrder
  → Both orders tracked with same exit_reason
```

### 7.10 Relative Expiry Resolution

Resolved at webhook trigger time (not at mapping configuration time):

```python
def resolve_expiry(underlying, exchange, expiry_type, api_key, instrumenttype='options'):
    """Resolve relative expiry to actual expiry date."""
    success, response, _ = get_expiry_dates(
        symbol=underlying,
        exchange=exchange_to_fno(exchange),  # NSE_INDEX → NFO
        instrumenttype=instrumenttype,       # 'options' or 'futures'
        api_key=api_key
    )

    expiry_dates = response['data']  # Sorted ascending
    today = datetime.now(IST).date()

    if expiry_type == 'current_week':
        return first expiry >= today
    elif expiry_type == 'next_week':
        return second expiry >= today
    elif expiry_type == 'current_month':
        return last expiry in current month
    elif expiry_type == 'next_month':
        return last expiry in next month
```

---

## 8. Exit Execution Mechanism (Pluggable)

### 8.1 Design Pattern — Strategy Pattern

Exit execution is implemented as a pluggable strategy pattern, allowing new execution types to be added without modifying the risk engine core.

```python
class ExitExecutionStrategy:
    """Base class for exit execution strategies."""
    def execute(self, position, exit_reason, api_key) -> list[str]:
        """Execute exit for a position. Returns list of orderids."""
        raise NotImplementedError

class MarketExecution(ExitExecutionStrategy):
    """V1 default: immediate MARKET order."""
    def execute(self, position, exit_reason, api_key):
        # Auto-split if qty > freeze_qty
        # Place placeorder(price_type=MARKET)
        # Return orderids

# Future execution types (not in V1):
# class MidOrderExecution(ExitExecutionStrategy):
#     """Place at mid-price (bid+ask)/2, chase if not filled."""
#
# class OrderChasingExecution(ExitExecutionStrategy):
#     """Place limit at best price, re-price every N seconds, fallback to MARKET."""
#
# class TWAPExecution(ExitExecutionStrategy):
#     """Time-weighted split across N intervals."""
```

### 8.2 Configuration

The execution type is stored per strategy (with symbol-level override possible):

**Strategy table addition:**
```
default_exit_execution    VARCHAR(20) DEFAULT 'market'  -- 'market' (V1 only; future: 'mid', 'chase', 'twap')
```

**Symbol mapping addition:**
```
exit_execution            VARCHAR(20)                   -- NULL = use strategy default
```

**Multi-leg combined mode**: All legs in a group use the same execution type.

### 8.3 V1 Behavior

V1 implements only `MarketExecution`. The `exit_execution` field defaults to `'market'` and the UI shows it as a read-only field with a note: "Additional execution types coming soon."

The risk engine calls the execution strategy via the pluggable interface:

```python
def place_exit_order(position, exit_reason):
    strategy = get_execution_strategy(position.exit_execution or 'market')
    orderids = strategy.execute(position, exit_reason, api_key)
    for oid in orderids:
        save_strategy_order(oid, is_entry=False, exit_reason=exit_reason)
        queue_to_poller(oid)
```

This ensures the risk engine never directly calls `placeorder` — it always goes through the execution strategy, making future execution types a drop-in addition.

---

## 9. Order Lifecycle

### 9.1 Entry Order Flow

```
Webhook signal arrives (POST /strategy/webhook/<webhook_id>)
  │
  ├─ Validate: strategy active, trading hours, symbol mapping
  │
  ├─ Place order via placeorder API (NOT placesmartorder)
  │   → Returns orderid
  │
  ├─ Save to StrategyOrder table (order_status: 'pending', is_entry: true)
  │
  └─ Queue orderid to OrderStatus poller
```

### 9.2 OrderStatus Poller (1 req/sec rate limit)

```
Background thread (single, persistent):
  While running:
    │
    ├─ Dequeue next orderid
    │
    ├─ Call OrderStatus service → get order_status, average_price
    │
    ├─ If "complete":
    │   ├─ Update StrategyOrder (average_price, filled_quantity, status)
    │   ├─ Create StrategyTrade (trade_type: 'entry')
    │   ├─ Create/update StrategyPosition:
    │   │   ├─ Set average_entry_price = average_price (or weighted avg for adds)
    │   │   ├─ Set peak_price = average_price (initial)
    │   │   ├─ Compute stoploss_price, target_price, trailstop_price
    │   │   └─ Set quantity
    │   ├─ Subscribe symbol to MarketDataService (CRITICAL priority)
    │   ├─ Emit SocketIO: strategy_position_opened
    │   └─ Send Telegram alert
    │
    ├─ If "rejected" or "cancelled":
    │   └─ Update StrategyOrder status, no position change
    │
    ├─ If "open":
    │   └─ Re-queue (back of queue)
    │
    └─ Sleep 1 second
```

### 9.3 Exit Order Flow (SL/Target/Trail Trigger)

```
MarketDataService LTP update (CRITICAL priority callback):
  │
  ├─ Check is_trade_management_safe()
  │   └─ If unsafe: skip (log warning, emit strategy_risk_paused)
  │
  ├─ Update position: ltp, unrealized_pnl, peak_price
  │
  ├─ If trailing stop configured:
  │   └─ Recalculate trailstop_price from peak_price
  │
  ├─ Check triggers (long example):
  │   ├─ LTP <= stoploss_price   → exit_reason = 'stoploss'
  │   ├─ LTP >= target_price     → exit_reason = 'target'
  │   └─ LTP <= trailstop_price  → exit_reason = 'trailstop'
  │
  └─ If triggered:
      ├─ Set StrategyPosition.exit_reason + exit_detail (e.g., 'stoploss' / 'leg_sl')
      ├─ Emit SocketIO: strategy_exit_triggered (with trigger_price, ltp_at_trigger, badge)
      ├─ Place exit via ExitExecutionStrategy (placeorder with auto-split)
      ├─ Save to StrategyOrder (is_entry: false, exit_reason, order_status: 'pending')
      ├─ Emit SocketIO: strategy_order_placed
      ├─ Queue orderid to OrderStatus poller
      └─ Send Telegram alert
```

### 9.4 Exit Order Completion

```
OrderStatus poller picks up exit orderid:
  │
  ├─ If "complete":
  │   ├─ Update StrategyOrder (average_price, filled_quantity, status='complete')
  │   ├─ Emit SocketIO: strategy_order_filled (with fill price, quantity)
  │   ├─ Calculate trade PnL:
  │   │   Long: pnl = (exit_price - entry_price) × quantity
  │   │   Short: pnl = (entry_price - exit_price) × quantity
  │   ├─ Create StrategyTrade (trade_type: 'exit', pnl)
  │   ├─ Update StrategyPosition:
  │   │   ├─ quantity = 0 (full exit)
  │   │   ├─ realized_pnl += trade pnl
  │   │   ├─ exit_price = average_price from fill
  │   │   ├─ closed_at = now
  │   │   └─ Clear SL/target/trail prices
  │   ├─ Unsubscribe symbol from MarketDataService
  │   ├─ Emit SocketIO: strategy_position_closed (with exit_reason, exit_detail, pnl, badge)
  │   └─ Send Telegram alert with PnL
  │
  └─ If "rejected":
      ├─ Update StrategyOrder (status='rejected')
      ├─ Emit SocketIO: strategy_order_rejected (with orderid, symbol, reason)
      ├─ Clear exit_reason on StrategyPosition (position stays open)
      ├─ Re-subscribe to MarketDataService if previously unsubscribed
      └─ Position remains open (trader must handle manually — "Failed" badge in UI)
```

### 9.5 Manual Position Close

```
User clicks [Close] on individual position:
  │
  ├─ Confirmation dialog: "Close 100 SBIN @ Market?"
  │
  └─ Same as exit order flow above, with exit_reason = 'manual'

User clicks [Close All Positions] for a strategy:
  │
  ├─ Confirmation dialog: "Close all N positions for Strategy Name?"
  │
  └─ For each position where quantity > 0:
      └─ Place exit placeorder, exit_reason = 'manual'
```

### 9.6 Position Deletion Protection

- Position with `quantity > 0`: Delete button disabled, tooltip: "Close position before deleting"
- Position with `quantity = 0`: Delete button enabled, removes record from DB
- Strategy deletion: If ANY position has `quantity > 0`, block with warning: "Close all positions before deleting this strategy"

---

## 10. Risk Engine Architecture

### 10.1 Dual-Engine Pattern (Reuse from Sandbox)

```
┌──────────────────────────────────────────────────────┐
│              StrategyRiskEngine (Singleton)           │
│                                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │ PRIMARY: WebSocket Execution Engine              │ │
│  │ • CRITICAL priority MarketDataService subscriber │ │
│  │ • Event-driven callback on every LTP update      │ │
│  │ • Sub-second latency                             │ │
│  │ • Health monitor thread (checks every 5s)        │ │
│  │ • Stale threshold: 30 seconds                    │ │
│  └──────────┬──────────────────────────────────────┘ │
│             │ auto-fallback if WebSocket stale        │
│  ┌──────────▼──────────────────────────────────────┐ │
│  │ FALLBACK: REST Polling Engine                    │ │
│  │ • MultiQuotes API (batch fetch, 1 req/sec)       │ │
│  │ • Configurable interval (default 5 seconds)      │ │
│  │ • Auto-upgrade when WebSocket recovers           │ │
│  └─────────────────────────────────────────────────┘ │
│                                                       │
│  Startup:                                             │
│  1. Check WebSocket proxy health (port 8765)          │
│  2. If healthy → start WebSocket engine               │
│  3. If unhealthy → start polling + auto-upgrade watch │
└──────────────────────────────────────────────────────┘
```

### 10.2 On Each LTP Update

```python
def on_ltp_update(symbol, exchange, ltp):
    # 1. Safety check
    is_safe, reason = market_data_service.is_trade_management_safe()
    if not is_safe:
        emit_risk_paused(reason)
        return

    # 2. Find all active strategy positions for this symbol
    positions = get_active_positions(symbol, exchange)

    for position in positions:
        # 3. Skip if position is not in 'active' state (exiting, pending_entry)
        if position.position_state != 'active':
            continue

        # 4. Update LTP and PnL
        position.ltp = ltp
        position.unrealized_pnl = calculate_pnl(position, ltp)

        # 5. Update peak price
        if position.action == 'BUY' and ltp > position.peak_price:
            position.peak_price = ltp
        elif position.action == 'SELL' and ltp < position.peak_price:
            position.peak_price = ltp

        # 6. Check breakeven threshold (one-time move)
        if position.breakeven_type and not position.breakeven_activated:
            if breakeven_threshold_hit(position, ltp):
                position.stoploss_price = round_to_tick(position.average_entry_price, position.tick_size)
                position.breakeven_activated = True

        # 7. Recalculate trailing stop from peak
        if position.trailstop_type:
            position.trailstop_price = round_to_tick(compute_trail(position), position.tick_size)

        # 8. Compute effective stop (considers breakeven + trail interaction)
        effective_stop = compute_effective_stop(position)  # max(sl, tsl) for longs

        # 9. Check triggers (per-leg / equity / single_option / futures)
        if position.risk_mode != 'combined':
            triggered, reason = check_triggers(position, ltp, effective_stop)
            if triggered:
                with PositionLockManager.get_lock(position.strategy_id, position.symbol, ...):
                    position.position_state = 'exiting'
                    place_exit_order(position, reason)

        # 8. Persist to DB (batched)
        save_position(position)

    # 10. Check combined P&L triggers (after all legs updated)
    for group in get_active_position_groups():
        # Skip groups that are still filling (not all legs have filled yet)
        if group.group_status != 'active':
            continue

        legs = get_positions_by_group(group.id)
        combined_pnl = sum(leg.unrealized_pnl for leg in legs)

        # Update combined peak PnL on the group record
        if combined_pnl > group.combined_peak_pnl:
            group.combined_peak_pnl = combined_pnl
        group.combined_pnl = combined_pnl

        mapping = get_mapping_for_group(group.id)

        # Combined SL check
        if mapping.combined_stoploss_type and combined_pnl <= -abs(compute_combined_threshold(mapping, 'sl')):
            group.group_status = 'exiting'
            close_all_legs(group, legs, exit_reason='stoploss')

        # Combined target check
        elif mapping.combined_target_type and combined_pnl >= compute_combined_threshold(mapping, 'target'):
            group.group_status = 'exiting'
            close_all_legs(group, legs, exit_reason='target')

        # Combined trailing stop check
        elif mapping.combined_trailstop_type:
            trail_threshold = compute_combined_trail(mapping, group.combined_peak_pnl)
            if combined_pnl <= trail_threshold:
                group.group_status = 'exiting'
                close_all_legs(group, legs, exit_reason='trailstop')
```

### 10.3 Activate / Deactivate

| State | Behavior |
|-------|----------|
| **Active** | Risk engine monitors positions. SL/target/trailing triggers fire. New webhook orders are tracked. |
| **Paused** | Webhook orders still execute (strategy `is_active` unchanged), but SL/target/trailing monitoring is paused. Positions remain in DB. Useful during volatile periods when trader wants manual control. |

- **Activate**: Subscribes all open positions to MarketDataService, resumes monitoring
- **Deactivate**: Unsubscribes from MarketDataService, stops trigger checking. Confirmation dialog required.

### 10.4 Master Contract Prerequisite

Similar to `/python` strategies, the risk engine and webhook order placement MUST NOT proceed without a downloaded master contract. This is critical because symbol resolution, tick size, lot size, and option strike mapping all depend on the master contract database.

```
Before any order placement or risk engine start:
  │
  ├─ Check: Is master contract downloaded for the broker?
  │   └─ Uses existing master contract check (same as /python strategies)
  │
  ├─ If NOT downloaded:
  │   ├─ Risk engine: Refuse to start, log warning
  │   ├─ Webhook orders: Return error response, do NOT place order
  │   ├─ UI: Show warning banner on Strategy Dashboard: "Master contract not downloaded. Download from Broker → Settings."
  │   └─ SocketIO emit: strategy_master_contract_missing
  │
  └─ If downloaded:
      └─ Proceed normally
```

This check runs:
1. On application startup (before risk engine initialization)
2. On every webhook signal (before order placement)
3. On risk engine activate (before subscribing to market data)

### 10.5 Restart Recovery

```
Application starts (app.py):
  │
  ├─ Check master contract downloaded → if not, skip risk engine init with warning
  │
  ├─ Initialize StrategyRiskEngine singleton
  │
  ├─ Query DB: StrategyPositions WHERE quantity > 0
  │             AND strategy.risk_monitoring = 'active'
  │
  ├─ Query DB: StrategyOrders WHERE order_status = 'pending'
  │
  ├─ Re-queue pending orders to OrderStatus poller (exit orders at HIGH priority)
  │
  ├─ **Broker reconciliation** (safety check):
  │   ├─ Fetch broker PositionBook via API
  │   ├─ For each local open position, compare qty with broker-side net qty
  │   ├─ If divergence detected: flag position as 'needs_review', emit warning
  │   └─ Log: "Reconciliation: N positions matched, M need review"
  │
  ├─ Subscribe all open position symbols to MarketDataService
  │   └─ Fetch current LTP immediately for peak_price initialization
  │
  ├─ Resume risk monitoring
  │
  └─ Log: "Recovered N positions across M strategies"
```

**Recovery safety**: During recovery, use broker's fill timestamp (from OrderStatus response) for `closed_at`, not `datetime.now()`. Mark recovered orders with `recovered=True` flag for audit trail.

---

## 11. Real-Time Status Tracking & Order Status Updates

### 11.1 Order Status Lifecycle

Every order (entry AND exit) goes through status updates that are persisted to `StrategyOrder` and pushed in real-time via SocketIO:

```
Order placed → order_status = 'pending'     → emit: strategy_order_placed
  │
  ├─ Poller returns 'open'     → order_status = 'open'        → emit: strategy_order_updated
  ├─ Poller returns 'complete' → order_status = 'complete'     → emit: strategy_order_filled
  ├─ Poller returns 'rejected' → order_status = 'rejected'     → emit: strategy_order_rejected
  └─ Poller returns 'cancelled'→ order_status = 'cancelled'    → emit: strategy_order_cancelled
```

**Every status change** triggers:
1. DB update to `StrategyOrder.order_status` and `StrategyOrder.updated_at`
2. SocketIO emit with full order payload (orderid, symbol, status, average_price, exit_reason)
3. Toast notification (if `strategyRisk` category enabled)

### 11.2 Exit Status Classification

When a position is closed, both `exit_reason` and `exit_detail` are set on the `StrategyPosition` record to clearly track HOW the exit happened:

| Trigger | `exit_reason` | `exit_detail` | UI Badge |
|---------|--------------|---------------|----------|
| Per-leg stoploss hit | `stoploss` | `leg_sl` | SL (red) |
| Per-leg target hit | `target` | `leg_target` | TGT (green) |
| Per-leg trailing stop hit | `trailstop` | `leg_tsl` | TSL (amber) |
| Breakeven SL hit (SL moved to entry, then triggered) | `stoploss` | `breakeven_sl` | BE-SL (blue) |
| Combined P&L stoploss | `stoploss` | `combined_sl` | C-SL (red) |
| Combined P&L target | `target` | `combined_target` | C-TGT (green) |
| Combined P&L trailing stop | `trailstop` | `combined_tsl` | C-TSL (amber) |
| Manual close (individual) | `manual` | `manual` | Manual (gray) |
| Manual close all | `manual` | `manual_all` | Manual (gray) |
| Webhook squareoff signal | `squareoff` | `squareoff` | SQ-OFF (gray) |

The `exit_detail` provides granularity to distinguish per-leg vs combined triggers, and breakeven-SL vs regular SL.

### 11.3 Real-Time Risk Values — SocketIO Push

On every LTP update from the market data feed, the risk engine emits updated position state to the frontend via SocketIO:

```
SocketIO event: strategy_position_update
Payload: {
    "strategy_id": 1,
    "strategy_type": "webhook",
    "position_id": 42,
    "symbol": "SBIN",
    "exchange": "NSE",
    "ltp": 812.50,
    "unrealized_pnl": 1250.00,
    "unrealized_pnl_pct": 1.56,
    "peak_price": 815.00,
    "stoploss_price": 784.00,       -- current effective SL (may have moved via breakeven/trail)
    "target_price": 840.00,         -- current target
    "trailstop_price": 795.50,      -- current trailing stop (moves with peak)
    "breakeven_activated": false,
    "risk_status": "monitoring"     -- monitoring | triggered | closed | paused
}
```

For combined P&L groups, an additional event is emitted:

```
SocketIO event: strategy_group_update
Payload: {
    "strategy_id": 1,
    "position_group_id": "uuid-xxx",
    "combined_pnl": -2500.00,
    "combined_peak_pnl": 1200.00,
    "combined_sl_price": -5000.00,    -- threshold value
    "combined_target_price": 8000.00,
    "combined_tsl_price": -3200.00,   -- trailing from peak
    "legs": [
        {"position_id": 42, "symbol": "NIFTY..CE", "pnl": -1500},
        {"position_id": 43, "symbol": "NIFTY..PE", "pnl": -1000}
    ],
    "risk_status": "monitoring"
}
```

**Emit frequency**: On every LTP tick for subscribed symbols (CRITICAL priority — sub-second via WebSocket, ~5s via REST fallback).

### 11.4 Strategy-Level PnL — Real-Time Aggregation

Strategy-level PnL is computed and pushed as an aggregate on every position update:

```
SocketIO event: strategy_pnl_update
Payload: {
    "strategy_id": 1,
    "strategy_type": "webhook",
    "total_unrealized_pnl": 4250.00,
    "total_realized_pnl": 1500.00,
    "total_pnl": 5750.00,
    "open_positions": 3,
    "closed_positions_today": 5,
    "winning_exits_today": 3,
    "losing_exits_today": 2,
    "win_rate": 63.3,
    "profit_factor": 2.68,
    "current_drawdown": -800.00,
    "max_drawdown": -3200.00
}
```

The frontend dashboard subscribes to these events and updates all values without REST polling — fully push-based.

### 11.5 Exit Event — Real-Time Notification

When a trigger fires and an exit order is placed, an immediate SocketIO event is emitted BEFORE waiting for the order to fill:

```
SocketIO event: strategy_exit_triggered
Payload: {
    "strategy_id": 1,
    "position_id": 42,
    "symbol": "SBIN",
    "exit_reason": "stoploss",
    "exit_detail": "leg_sl",
    "trigger_price": 784.00,        -- the SL/TGT/TSL price that was hit
    "ltp_at_trigger": 783.50,       -- actual LTP when trigger fired
    "exit_orderid": "24020600001",
    "quantity": 100,
    "badge": "SL"                   -- UI badge text
}
```

This gives the user immediate visual feedback that a trigger fired, even before the exit order fills. The position row in the UI shows a "Exiting..." spinner until the fill confirmation arrives.

### 11.6 Order Status Updates in StrategyOrder Table

The `StrategyOrder` table is updated at every stage:

| Event | Fields Updated |
|-------|---------------|
| Order placed | `order_status='pending'`, `created_at` |
| Poller: open | `order_status='open'`, `updated_at` |
| Poller: complete | `order_status='complete'`, `average_price`, `filled_quantity`, `updated_at` |
| Poller: rejected | `order_status='rejected'`, `updated_at` |
| Poller: cancelled | `order_status='cancelled'`, `updated_at` |

For exit orders, `exit_reason` is set at creation time (when the trigger fires), so the order always carries the reason it was placed.

---

## 12. Frontend — Strategy Dashboard

### 12.1 Page: `/strategy/dashboard`

Single unified page for managing all strategy positions.

### 12.2 Layout

```
┌────────────────────────────────────────────────────────────┐
│  Strategy Positions                           [Export CSV]  │
│                                                             │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌────────────┐ │
│  │ Active: 3  │ │ Paused: 1 │ │ Open: 8   │ │ Total P&L  │ │
│  │ strategies │ │ strategies│ │ positions │ │ +₹4,250 ▲  │ │
│  └───────────┘ └───────────┘ └───────────┘ └────────────┘ │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Nifty Momentum              ● ACTIVE  [Deactivate]  │  │
│  │ P&L: +₹1,150  │  2 positions  │  4 trades today     │  │
│  │──────────────────────────────────────────────────────│  │
│  │ Symbol  Qty   Avg      LTP      P&L     SL   TGT TS │  │
│  │ SBIN    +100  800.00   812.50   +1,250  784  840 792 │  │
│  │                                          [Close ✕]   │  │
│  │ INFY    +50   1520.00  1498.00  -1,100  1490 1596 —  │  │
│  │                                          [Close ✕]   │  │
│  │──────────────────────────────────────────────────────│  │
│  │ [Close All Positions]  [Orders 8] [Trades 4] [P&L]  │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Chartink Scanner            ○ PAUSED   [Activate]    │  │
│  │ P&L: ₹0  │  0 positions  │  0 trades today          │  │
│  │──────────────────────────────────────────────────────│  │
│  │ No open positions. Risk monitoring paused.           │  │
│  │──────────────────────────────────────────────────────│  │
│  │ [Orders 12]  [Trades 8]  [P&L]                      │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

### 12.3 Strategy Card Elements

| Element | Description |
|---------|-------------|
| Strategy name | Display name of the strategy |
| Status indicator | Green dot = Active, Amber dot = Paused |
| **[Activate] / [Deactivate]** | Toggle risk monitoring on/off (confirmation dialog) |
| Strategy summary | Total P&L (live), position count, trade count today, win rate, profit factor |
| Position table | Symbol, Qty (+/-), Avg, LTP (live), P&L (live), SL, TGT, TS |
| **[Close ✕]** per position | Close individual position at MARKET. Confirmation dialog. |
| **[Close All Positions]** | Close all strategy positions at MARKET. Confirmation dialog. |
| **[Orders N]** | Opens drawer with strategy orderbook (same format as global /orderbook) |
| **[Trades N]** | Opens drawer with strategy tradebook (same format as global /tradebook) |
| **[P&L]** | Opens drawer with daily PnL chart + summary stats |

### 12.4 Position Table Columns

| Column | Source | Format |
|--------|--------|--------|
| Symbol | `StrategyPosition.symbol` | font-medium |
| Qty | `StrategyPosition.quantity` | +N (green) / -N (red) |
| Avg | `StrategyPosition.average_entry_price` | font-mono, INR format |
| LTP | Live via `strategy_position_update` SocketIO | font-mono, INR format, live-updating |
| P&L | Live via `strategy_position_update` SocketIO | green/red with arrow, live-updating |
| SL | Live via `strategy_position_update` SocketIO | red text, updates on breakeven/trail move |
| TGT | Live via `strategy_position_update` SocketIO | green text |
| TSL | Live via `strategy_position_update` SocketIO | amber text, updates on peak move; `—` if none |
| BE | `breakeven_activated` | blue "BE" badge when active; `—` if not configured |
| Status | `exit_detail` / position state | see Status column below |
| Action | Close button | enabled only if qty > 0; "Exiting..." spinner during exit |

**Status Column Values** (color-coded badges):

| State | Badge | Color |
|-------|-------|-------|
| Position open, monitoring active | `Monitoring` | blue |
| Position open, monitoring paused | `Paused` | amber |
| Exit order placed, awaiting fill | `Exiting...` | amber, animated |
| Exited via per-leg stoploss | `SL` | red |
| Exited via per-leg target | `TGT` | green |
| Exited via per-leg trailing stop | `TSL` | amber |
| Exited via breakeven SL | `BE-SL` | blue |
| Exited via combined SL | `C-SL` | red |
| Exited via combined target | `C-TGT` | green |
| Exited via combined TSL | `C-TSL` | amber |
| Exited manually | `Manual` | gray |
| Exited via webhook squareoff | `SQ-OFF` | gray |
| Exit order rejected | `Failed` | red, pulsing |

### 12.5 Symbol Mapping — Order Mode Configuration UI

When configuring a symbol mapping, the UI adapts based on the selected `order_mode`:

**Underlying Search Selector** (for `futures`, `single_option`, `multi_leg` modes):
```
┌────────────────────────────────────────────────────┐
│  Order Mode: [Equity ▼] [Futures] [Single Option] [Multi-Leg]  │
│                                                     │
│  Underlying:  [🔍 Search underlying... ]           │
│               ┌─────────────────────────┐          │
│               │ NIFTY                    │          │
│               │ BANKNIFTY                │          │
│               │ FINNIFTY                 │          │
│               │ MIDCPNIFTY               │          │
│               │ SENSEX                   │          │
│               │ SBIN                     │          │
│               │ RELIANCE                 │          │
│               └─────────────────────────┘          │
│                                                     │
│  Exchange:    [NFO ▼]    -- auto-set from underlying│
│  Expiry:      [Current Month ▼]                     │
│  Product:     [NRML ▼]  [MIS]                       │
│  Quantity:    [75]       -- validated against lot size│
│                                                     │
│  Auto Square-Off: [15:15] IST  -- MIS only          │
└────────────────────────────────────────────────────┘
```

**Search behavior**: Typeahead search across master contract symbols. Filters by instrument type based on context:
- For `futures` mode: Shows symbols with futures contracts (NIFTY, BANKNIFTY, stock futures, etc.)
- For `single_option` / `multi_leg` mode: Shows symbols with options contracts
- For `equity` mode: Direct symbol entry (no underlying search needed)

**Product type dropdown**: Dynamically filtered based on instrument type:
- Equity selected → shows CNC, MIS
- Futures/Options selected → shows NRML, MIS

**Auto Square-Off Time**: Shown only when product_type = MIS. Default 15:15 IST. User can adjust via time picker. All times displayed in IST.

### 12.6 Drawer Views

**Orders Drawer**: Same table format as global OrderBook page.
- Columns: Symbol, Exchange, Action, Qty, Price, Trigger, Type, Product, Order ID, Status, Time, Exit Reason
- Stats cards: Buy/Sell/Completed/Open/Rejected
- Data source: `StrategyOrder` table (local DB, no broker API call)

**Trades Drawer**: Same table format as global TradeBook page.
- Columns: Symbol, Exchange, Product, Action, Qty, Price, Trade Value, Order ID, Time, Trade Type, Exit Reason, P&L
- Data source: `StrategyTrade` table (local DB, no broker API call)

**P&L Drawer**: Daily PnL analytics + strategy risk metrics.
- Equity curve chart (daily cumulative_pnl over time)
- Drawdown chart (daily drawdown overlaid below equity curve)
- Risk metrics panel (see Section 12.7)
- Data source: `StrategyDailyPnL` + `StrategyTrade` tables

### 12.7 Strategy Risk Metrics

Computed from `StrategyTrade` (trade-level) and `StrategyDailyPnL` (daily snapshots). Displayed in the P&L drawer and on the strategy card summary.

#### 12.7.1 Metrics — Definitions & Computation

| Metric | Formula | Source | Update Frequency |
|--------|---------|--------|-----------------|
| **Total P&L** | realized + unrealized | Positions + trades | Real-time (SocketIO) |
| **Realized P&L** | Sum of all closed trade PnL | `StrategyTrade` | On each exit fill |
| **Unrealized P&L** | Sum of open position PnL | `StrategyPosition` | Real-time (SocketIO) |
| **Win Rate** | winning_trades / total_trades × 100 | `StrategyTrade` | On each exit fill |
| **Total Trades** | Count of exit trades | `StrategyTrade` | On each exit fill |
| **Average Win** | gross_profit / winning_trades | `StrategyTrade` | On each exit fill |
| **Average Loss** | gross_loss / losing_trades | `StrategyTrade` | On each exit fill |
| **Risk-Reward Ratio** | average_win / average_loss | Derived | On each exit fill |
| **Profit Factor** | gross_profit / gross_loss | `StrategyTrade` | On each exit fill |
| **Expectancy** | (win_rate × avg_win) − (loss_rate × avg_loss) | Derived | On each exit fill |
| **Best Trade** | Max single trade PnL | `StrategyTrade` | On each exit fill |
| **Worst Trade** | Min single trade PnL | `StrategyTrade` | On each exit fill |
| **Max Consecutive Wins** | Longest winning streak | `StrategyTrade` (ordered by time) | On each exit fill |
| **Max Consecutive Losses** | Longest losing streak | `StrategyTrade` (ordered by time) | On each exit fill |
| **Max Drawdown** | Largest peak-to-trough decline in cumulative PnL | `StrategyDailyPnL` | Daily snapshot + real-time intraday |
| **Max Drawdown %** | max_drawdown / peak_cumulative_pnl × 100 | `StrategyDailyPnL` | Daily snapshot + real-time intraday |
| **Current Drawdown** | peak_cumulative_pnl − current_cumulative_pnl | `StrategyDailyPnL` + live | Real-time |
| **Best Day** | Max daily total_pnl | `StrategyDailyPnL` | Daily snapshot |
| **Worst Day** | Min daily total_pnl | `StrategyDailyPnL` | Daily snapshot |
| **Average Daily P&L** | Sum of daily total_pnl / trading_days | `StrategyDailyPnL` | Daily snapshot |
| **Days Active** | Count of rows in StrategyDailyPnL | `StrategyDailyPnL` | Daily snapshot |

#### 12.7.2 Exit Breakdown — By Trigger Type

Aggregated from `StrategyTrade.exit_reason` for all closed trades:

| Exit Type | Count | Total P&L | Avg P&L |
|-----------|-------|-----------|---------|
| Stoploss | 12 | −₹8,400 | −₹700 |
| Target | 18 | +₹22,500 | +₹1,250 |
| Trailing Stop | 5 | +₹4,100 | +₹820 |
| Breakeven SL | 3 | −₹45 | −₹15 |
| Manual | 2 | +₹600 | +₹300 |

This table helps traders evaluate which exit mechanisms are performing well and which need parameter tuning.

#### 12.7.3 P&L Drawer Layout

```
┌────────────────────────────────────────────────────┐
│  P&L Analytics — Nifty Momentum                    │
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │           Equity Curve (line chart)            │  │
│  │  ₹ ─────────/\──────/\──/\────────────        │  │
│  │           Drawdown (area chart, below)         │  │
│  │    ──────────\/ ──────\/──\/──────────         │  │
│  └──────────────────────────────────────────────┘  │
│                                                     │
│  ┌─────────────┐ ┌─────────────┐ ┌──────────────┐ │
│  │ Total P&L    │ │ Win Rate     │ │ Profit Factor│ │
│  │ +₹18,755     │ │ 63.3%        │ │ 2.68         │ │
│  └─────────────┘ └─────────────┘ └──────────────┘ │
│  ┌─────────────┐ ┌─────────────┐ ┌──────────────┐ │
│  │ Max Drawdown │ │ Risk:Reward  │ │ Expectancy   │ │
│  │ −₹3,200(4.2%)│ │ 1:1.79       │ │ +₹485/trade  │ │
│  └─────────────┘ └─────────────┘ └──────────────┘ │
│                                                     │
│  Trade Statistics                                   │
│  ┌──────────────────────────────────────────────┐  │
│  │ Total Trades: 30   │  Wins: 19  │  Losses: 11│  │
│  │ Avg Win: +₹1,184   │  Avg Loss: −₹764        │  │
│  │ Best Trade: +₹3,200 │  Worst: −₹1,800        │  │
│  │ Max Consec Wins: 5  │  Max Consec Losses: 3   │  │
│  │ Best Day: +₹4,200   │  Worst Day: −₹2,100    │  │
│  │ Days Active: 14     │  Avg Daily: +₹1,340     │  │
│  └──────────────────────────────────────────────┘  │
│                                                     │
│  Exit Breakdown                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │ Type       │ Count │ Total P&L  │ Avg P&L    │  │
│  │ Target     │    18 │ +₹22,500   │ +₹1,250    │  │
│  │ Trail Stop │     5 │ +₹4,100    │ +₹820      │  │
│  │ Stoploss   │    12 │ −₹8,400    │ −₹700      │  │
│  │ Breakeven  │     3 │ −₹45       │ −₹15       │  │
│  │ Manual     │     2 │ +₹600      │ +₹300      │  │
│  └──────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────┘
```

### 12.8 Live Data

#### Backend → Risk Engine (Market Data Feed)

The risk engine uses the **shared centralized WebSocket handler** (MarketDataService) which operates in dual mode:

- **During market hours**: WebSocket push via unified proxy (port 8765) — CRITICAL priority subscriber, sub-second LTP updates
- **After market hours**: Automatic fallback to REST polling (MultiQuotes batch fetch) — configurable interval

This is the same shared handler used by the sandbox, flow price monitor, and other consumers. The risk engine subscribes as a CRITICAL priority consumer and receives LTP callbacks which drive all trigger checks, PnL calculations, and risk metric updates.

#### Risk Engine → Frontend (SocketIO Push)

All live data on the dashboard is **fully push-based** via Flask-SocketIO — no REST polling from frontend:

- **Position LTP, P&L, SL, TGT, TSL**: Updated via `strategy_position_update` SocketIO event (Section 11.3)
- **Combined group P&L**: Updated via `strategy_group_update` SocketIO event
- **Strategy summary P&L + risk metrics**: Updated via `strategy_pnl_update` SocketIO event (Section 11.4)
- **Dashboard summary cards**: Aggregated client-side from strategy PnL updates
- **Exit events**: Immediate via `strategy_exit_triggered` event; position shows "Exiting..." until fill
- **Order status changes**: Via `strategy_order_filled` / `strategy_order_rejected` events
- **Risk status badges**: Transition in real-time (Monitoring → Exiting... → SL/TGT/TSL badge)
- **Initial load**: REST API `GET /strategy/api/dashboard` provides snapshot; SocketIO takes over for live updates

#### Data Flow

```
Broker WebSocket → Unified Proxy (8765) → ZeroMQ Bus (5555)
                                               │
                                    MarketDataService (shared)
                                     │                    │
                          ┌──────────┘                    └──────────┐
                          │                                          │
                   StrategyRiskEngine                     Other consumers
                   (CRITICAL priority)                    (sandbox, flow, etc.)
                          │
              ┌───────────┼───────────┐
              │           │           │
         Trigger      Update     Compute
         checks     positions   risk metrics
              │           │           │
              └───────────┼───────────┘
                          │
                   Flask-SocketIO
                          │
              ┌───────────┼───────────┐
              │           │           │
         position_    pnl_       exit_
         update      update    triggered
              │           │           │
              └───────────┼───────────┘
                          │
                    React Frontend
                    (Dashboard UI)
```

### 12.9 Position Deletion Protection

| State | Delete Button | Behavior |
|-------|--------------|----------|
| `quantity > 0` | Disabled | Tooltip: "Close position before deleting" |
| `quantity = 0` | Enabled | Removes record from DB |
| Strategy has any open position | Strategy delete blocked | Warning: "Close all positions before deleting this strategy" |

---

## 13. Notifications

### 13.1 New Toast Category

Add `strategyRisk` to the alert store categories:

| Category Key | Label | Description | Group |
|-------------|-------|-------------|-------|
| `strategyRisk` | Strategy Risk | Stoploss, target, trailing stop trigger notifications | Real-time Socket.IO Events |

Configured in Profile → Alerts tab alongside existing categories.

### 13.2 SocketIO Events

**Toast/notification events** (user-facing alerts):

| Event | When | Toast Style | Audio |
|-------|------|-------------|-------|
| `strategy_position_opened` | New position from fill | info | Yes |
| `strategy_exit_triggered` | Any SL/target/trail/breakeven trigger fires | error/success/warning (by type) | Yes |
| `strategy_position_closed` | Position fully exited (fill confirmed) | success/error (by P&L) | Yes |
| `strategy_order_rejected` | Exit order rejected by broker | error (red) | Yes |
| `strategy_risk_paused` | Data stale / connection lost | warning | Yes |
| `strategy_risk_resumed` | Connection recovered | info | No |

**Data update events** (silent, for live UI updates — no toast):

| Event | When | Payload |
|-------|------|---------|
| `strategy_position_update` | Every LTP tick | Position LTP, P&L, SL, TGT, TSL, peak, BE status |
| `strategy_group_update` | Every LTP tick (combined mode) | Combined P&L, legs breakdown, combined thresholds |
| `strategy_pnl_update` | Every LTP tick | Strategy aggregate PnL, open/closed counts |
| `strategy_order_placed` | Order placed | Order details, pending status |
| `strategy_order_filled` | Order fill confirmed | Fill price, quantity, updated position |
| `strategy_order_cancelled` | Order cancelled | Order details |

### 13.3 Telegram Alerts

Strategy risk events map to existing Telegram notification preferences:

| Telegram Toggle | Strategy Risk Events |
|----------------|---------------------|
| `order_notifications` | Exit orders from SL/target/trail triggers |
| `trade_notifications` | Entry/exit trade fills |
| `pnl_notifications` | Position closed with P&L |

No new Telegram toggles required.

---

## 14. Backend Services (New)

### 14.1 StrategyRiskEngine (`services/strategy_risk_engine.py`)

Singleton service. Reuses sandbox dual-engine pattern.

**Responsibilities:**
- Subscribe to MarketDataService (CRITICAL priority)
- Monitor all active strategy positions (per-leg + combined groups)
- Check SL/target/trailing stop/breakeven triggers on each LTP update
- Delegate exit to ExitExecutionStrategy (pluggable)
- Emit real-time SocketIO events on every LTP update (position updates, group updates, PnL)
- Emit exit trigger events immediately when SL/target/trail fires
- Track and emit order status changes (pending → open → complete/rejected/cancelled)
- Set exit_reason + exit_detail on StrategyPosition when trigger fires
- Check master contract prerequisite before startup
- Auto-fallback to REST polling if WebSocket stale
- Auto-upgrade back to WebSocket when recovered

### 14.2 StrategyPositionTracker (`services/strategy_position_tracker.py`)

**Responsibilities:**
- Create/update StrategyPosition on order fills
- Compute SL/target/trailing stop/breakeven prices from average_price
- Round all computed prices to tick_size
- Calculate weighted average entry price on position adds
- Track realized PnL on exits
- Handle partial exits (reduce quantity, accumulate realized PnL)
- Manage position groups (combined P&L mode)

### 14.3 OrderStatusPoller (`services/strategy_order_poller.py`)

**Responsibilities:**
- Single background thread, 1 req/sec rate limit
- Priority queue: exit orders (SL/target/trail triggers) polled before entry orders. Within same priority, FIFO.
- Poll OrderStatus service for each orderid
- Update StrategyOrder status on every poll (pending → open → complete/rejected/cancelled)
- Emit SocketIO event on every status transition (strategy_order_placed/filled/rejected/cancelled)
- Route completions to StrategyPositionTracker
- On restart: reload pending orders from DB
- Use broker fill timestamp (not `datetime.now()`) for `closed_at` during recovery fills

### 14.4 StrategyPnLService (`services/strategy_pnl_service.py`)

**Responsibilities:**
- Calculate unrealized PnL from positions + LTP
- Calculate realized PnL from trade history
- Generate daily PnL snapshots (APScheduler job at 15:35 IST)
- Aggregate PnL across all positions in a strategy
- Compute strategy risk metrics: win rate, avg win/loss, profit factor, expectancy, risk-reward ratio
- Track max drawdown (cumulative peak-to-trough) across daily snapshots
- Track intraday drawdown in real-time (updated on each exit fill)
- Compute exit breakdown by trigger type (stoploss/target/trailstop/breakeven/manual counts + PnL)
- Compute streak metrics (max consecutive wins/losses) from ordered trade history
- Compute best/worst trade, best/worst day, average daily PnL

### 14.5 StrategyOptionsResolver (`services/strategy_options_resolver.py`)

**Responsibilities:**
- Resolve relative expiry to actual expiry date (via expiry service)
- Resolve strike from offset + underlying LTP (via OptionsOrder service)
- Fetch and cache tick_size + lot_size per symbol (via symbol service)
- Fetch freeze_qty from admin config
- Validate quantity is multiple of lot_size
- Determine if auto-split needed (qty > freeze_qty)

### 14.6 StrategyExitExecutor (`services/strategy_exit_executor.py`)

**Responsibilities:**
- Pluggable strategy pattern for exit execution
- V1: `MarketExecution` — immediate MARKET order via placeorder
- Auto-split via SplitOrder if qty > freeze_qty
- Returns list of orderids for tracking
- Future extensibility: mid order, order chasing, TWAP (no code changes to risk engine needed)

---

## 15. Backend API Endpoints (New)

### 15.1 Strategy Risk Configuration

```
PUT /strategy/api/strategy/<id>/risk
Body: {
    "default_stoploss_type": "percentage",
    "default_stoploss_value": 2.0,
    "default_target_type": "percentage",
    "default_target_value": 5.0,
    "default_trailstop_type": "points",
    "default_trailstop_value": 50
}
```

```
PUT /strategy/api/strategy/<id>/symbol/<mapping_id>/risk
Body: {
    "stoploss_type": "points",
    "stoploss_value": 10,
    "target_type": null,       # use strategy default
    "target_value": null,
    "trailstop_type": null,
    "trailstop_value": null
}
```

### 15.2 Risk Monitoring Control

```
POST /strategy/api/strategy/<id>/risk/activate
POST /strategy/api/strategy/<id>/risk/deactivate
```

### 15.3 Strategy Dashboard Data

```
GET /strategy/api/dashboard
Response: {
    "strategies": [
        {
            "id": 1,
            "name": "Nifty Momentum",
            "strategy_type": "webhook",
            "risk_monitoring": "active",
            "positions": [...],
            "total_pnl": 1150.00,
            "trade_count_today": 4,
            "order_count": 8,
            "win_rate": 63.3,
            "profit_factor": 2.68,
            "max_drawdown": -3200.00
        }
    ],
    "summary": {
        "active_strategies": 3,
        "paused_strategies": 1,
        "open_positions": 8,
        "total_pnl": 4250.00
    }
}
```

### 15.4 Strategy Positions

```
GET /strategy/api/strategy/<id>/positions
Response: {
    "positions": [
        {
            "id": 1,
            "symbol": "SBIN",
            "exchange": "NSE",
            "product_type": "MIS",
            "action": "BUY",
            "quantity": 100,
            "average_entry_price": 800.00,
            "ltp": 812.50,
            "unrealized_pnl": 1250.00,
            "unrealized_pnl_pct": 1.56,
            "stoploss_price": 784.00,
            "target_price": 840.00,
            "trailstop_price": 792.00,
            "peak_price": 815.00,
            "breakeven_activated": false,
            "realized_pnl": 0,
            "exit_reason": null,
            "exit_detail": null,
            "exit_price": null,
            "risk_status": "monitoring"
        }
    ]
}
```

### 15.5 Manual Position Close

```
POST /strategy/api/strategy/<id>/position/<position_id>/close
POST /strategy/api/strategy/<id>/positions/close-all
```

### 15.6 Strategy Orders & Trades

```
GET /strategy/api/strategy/<id>/orders
GET /strategy/api/strategy/<id>/trades
```

### 15.7 Strategy P&L & Risk Metrics

```
GET /strategy/api/strategy/<id>/pnl
Response: {
    "pnl": {
        "total_pnl": 18755.00,
        "realized_pnl": 17500.00,
        "unrealized_pnl": 1255.00
    },
    "risk_metrics": {
        "total_trades": 30,
        "winning_trades": 19,
        "losing_trades": 11,
        "win_rate": 63.3,
        "average_win": 1184.21,
        "average_loss": -763.64,
        "risk_reward_ratio": 1.55,
        "profit_factor": 2.68,
        "expectancy": 485.45,
        "best_trade": 3200.00,
        "worst_trade": -1800.00,
        "max_consecutive_wins": 5,
        "max_consecutive_losses": 3,
        "max_drawdown": -3200.00,
        "max_drawdown_pct": -4.2,
        "current_drawdown": -800.00,
        "current_drawdown_pct": -1.1,
        "best_day": 4200.00,
        "worst_day": -2100.00,
        "average_daily_pnl": 1339.64,
        "days_active": 14
    },
    "exit_breakdown": [
        {"exit_reason": "target", "count": 18, "total_pnl": 22500.00, "avg_pnl": 1250.00},
        {"exit_reason": "trailstop", "count": 5, "total_pnl": 4100.00, "avg_pnl": 820.00},
        {"exit_reason": "stoploss", "count": 12, "total_pnl": -8400.00, "avg_pnl": -700.00},
        {"exit_reason": "breakeven_sl", "count": 3, "total_pnl": -45.00, "avg_pnl": -15.00},
        {"exit_reason": "manual", "count": 2, "total_pnl": 600.00, "avg_pnl": 300.00}
    ],
    "daily_pnl": [
        {"date": "2026-02-01", "total_pnl": 1200.00, "cumulative_pnl": 1200.00, "drawdown": 0},
        {"date": "2026-02-02", "total_pnl": -800.00, "cumulative_pnl": 400.00, "drawdown": -800.00},
        ...
    ]
}
```

### 15.8 Position Deletion

```
DELETE /strategy/api/strategy/<id>/position/<position_id>
Response (if quantity > 0): { "status": "error", "message": "Close position before deleting" }
Response (if quantity == 0): { "status": "success", "message": "Position record deleted" }
```

---

## 16. Webhook Handler Changes

### 16.1 Strategy Webhook (`blueprints/strategy.py`)

Current flow:
```
Webhook → validate → build order payload → queue to order_queue → POST /api/v1/placeorder
```

New flow:
```
Webhook → dedup check → validate → position state check → build order payload
  │
  ├─ Dedup: Reject if identical signal within 5s window (Section 17.6)
  │
  ├─ Position state check:
  │   ├─ If existing position with position_state = 'exiting': REJECT ("Exit in progress")
  │   ├─ If existing position with position_state = 'pending_entry': REJECT ("Entry pending")
  │   └─ Otherwise: proceed
  │
  ├─ Queue to order_queue → POST /api/v1/placeorder
  │                                │
  │                                ▼
  │                       Get orderid from response
  │                                │
  │                                ▼
  │                       Save StrategyOrder (pending)
  │                       Set position_state = 'pending_entry' (new entry)
  │                                │
  │                                ▼
  │                       Queue to OrderStatus poller (entry = LOW priority, exit = HIGH priority)
  │
  └─ On fill: PositionTracker creates/updates StrategyPosition, sets position_state = 'active'
```

**Key changes**:
1. The order processor MUST capture the `orderid` from the API response (current code discards it)
2. Position state guards prevent race conditions between entries and exits
3. Webhook deduplication prevents double-orders from signal source retries

### 16.2 Futures & Options Order Mapping (New)

When a symbol mapping is configured with `order_mode = 'futures'`, `'single_option'`, or `'multi_leg'`:

**Futures mode**:
```
Webhook signal: {"symbol": "NIFTY", "action": "BUY"}
  │
  ├─ Lookup symbol mapping → order_mode = 'futures'
  │
  ├─ Resolve futures symbol:
  │   ├─ Resolve relative expiry (current_month/next_month) via expiry service
  │   ├─ Build futures symbol: NIFTY28FEB25FUT
  │   ├─ Get tick_size + lot_size from symbol service
  │   ├─ Get freeze_qty from admin config → auto-split if qty > freeze_qty
  │   └─ Validate product_type is NRML or MIS (not CNC)
  │
  ├─ Place via placeorder (auto-split if needed)
  │
  ├─ Save StrategyOrder(s) → queue to OrderStatus poller
  │
  └─ On fill: create StrategyPosition with resolved futures symbol
```

**Single option mode**:
```
Webhook signal: {"symbol": "NIFTY", "action": "BUY"}
  │
  ├─ Lookup symbol mapping → order_mode = 'single_option'
  │
  ├─ Resolve option symbol:
  │   ├─ Fetch underlying LTP via quotes service
  │   ├─ Resolve relative expiry (current_week/next_week/current_month/next_month)
  │   │   → Uses expiry service to get actual expiry date
  │   ├─ Resolve strike from offset (ATM, ITM3, OTM2, etc.)
  │   │   → Uses OptionsOrder service internally
  │   ├─ Get tick_size from symbol service → round SL/target/trail prices
  │   └─ Get freeze_qty from admin config → auto-split if qty > freeze_qty
  │
  ├─ If qty <= freeze_qty:
  │   └─ Place via OptionsOrder service (single call)
  │
  ├─ If qty > freeze_qty:
  │   └─ Place via SplitOrder service (auto-chunks at freeze_qty)
  │
  ├─ Save StrategyOrder(s) → queue to OrderStatus poller
  │
  └─ On fill: create StrategyPosition with resolved option symbol
```

For multi-leg:

```
Webhook signal: {"symbol": "NIFTY", "action": "BUY"}
  │
  ├─ Lookup symbol mapping → order_mode = 'multi_leg'
  │
  ├─ For each leg in mapping configuration:
  │   ├─ Resolve option symbol (offset + option_type + relative expiry)
  │   ├─ Get tick_size per leg symbol
  │   ├─ Get freeze_qty per leg symbol
  │   └─ Auto-split if needed
  │
  ├─ Determine risk_mode:
  │   ├─ 'per_leg': Each leg tracked as independent StrategyPosition
  │   └─ 'combined': All legs linked via position_group_id
  │
  ├─ Place via OptionsMultiOrder service (BUY legs first for margin efficiency)
  │
  ├─ Save StrategyOrder per leg → queue each to OrderStatus poller
  │
  └─ On fills: create StrategyPosition per leg (with position_group_id if combined)
```

### 16.3 Squareoff Handling

Current: `placesmartorder(position_size=0)` → exits ALL positions for symbol.

New: Query `StrategyPosition` for this strategy's tracked quantity → `placeorder(action=reverse, quantity=tracked_qty)` → exits only this strategy's position.

### 16.4 Chartink Webhook (`blueprints/chartink.py`)

Same changes as strategy webhook — identical pattern.

---

## 17. Concurrency, Data Integrity & Performance

### 17.1 SQLite Concurrency Safeguards

The risk engine, OrderStatusPoller, Flask request threads (webhooks, dashboard API, manual close), and APScheduler all write to `db/openalgo.db` concurrently. SQLite requires explicit configuration for safe multi-threaded access.

**Required PRAGMA settings** (set on engine creation in `database/strategy_position_db.py`):

```python
from sqlalchemy import event

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")       # Allow concurrent reads + single writer
    cursor.execute("PRAGMA busy_timeout=5000")       # Wait 5s instead of failing on lock
    cursor.execute("PRAGMA synchronous=NORMAL")      # Good balance of safety + performance
    cursor.execute("PRAGMA wal_autocheckpoint=1000") # Auto-checkpoint every 1000 pages
    cursor.close()
```

**Why WAL mode**: Default SQLite (`DELETE` journal mode) uses exclusive file-level locks — only ONE writer at a time, all others get `SQLITE_BUSY` immediately. WAL (Write-Ahead Logging) allows concurrent readers alongside a single writer. Combined with `busy_timeout=5000`, other writers queue and wait up to 5 seconds instead of failing.

### 17.2 Batched Position Updates (Reduce Write Frequency)

The risk engine receives sub-second LTP ticks for 50+ positions. Writing to DB on every tick would produce 50+ writes/sec, overwhelming SQLite.

**Solution**: Buffer position updates in memory, flush to DB at a throttled rate:

```python
class PositionUpdateBuffer:
    """Buffer in-memory position updates, flush to DB every N seconds."""
    FLUSH_INTERVAL = 1.0  # seconds

    def update(self, position_id, ltp, unrealized_pnl, peak_price, trailstop_price):
        """Store in-memory; latest update wins."""
        self._buffer[position_id] = {...}

    def flush(self):
        """Batch-write all buffered updates to DB in a single transaction."""
        with db_session() as session:
            for position_id, data in self._buffer.items():
                session.query(StrategyPosition).filter_by(id=position_id).update(data)
            session.commit()
        self._buffer.clear()
```

- **Trigger checks**: Run in-memory using buffered values (no DB read needed)
- **DB writes**: Batched flush every 1 second (reduces 50+ writes/sec to ~1 write/sec)
- **SocketIO emits**: Driven from in-memory state, not DB reads

### 17.3 Position-Level Locking (Thread Safety)

Multiple threads may attempt to modify the same `StrategyPosition` concurrently (risk engine callback, poller fill handler, webhook new entry). A per-position lock prevents data corruption:

```python
import threading
from collections import defaultdict

class PositionLockManager:
    """Per-position threading lock to serialize mutations."""
    _locks = defaultdict(threading.Lock)

    @classmethod
    def get_lock(cls, strategy_id, symbol, exchange, product_type):
        key = (strategy_id, symbol, exchange, product_type)
        return cls._locks[key]
```

**Usage**: Any code modifying a `StrategyPosition` row MUST hold the position lock:
- Risk engine: Before placing exit order (set `position_state='exiting'`)
- Poller: Before updating position on fill (set quantity, realized_pnl)
- Webhook: Before creating new entry (check `position_state`, set `position_state='pending_entry'`)

### 17.4 Session Cleanup in Background Threads

All background threads using `scoped_session` MUST call `db_session.remove()` after each unit of work:

```python
# In OrderStatusPoller loop:
try:
    process_next_order()
finally:
    db_session.remove()

# In risk engine flush:
try:
    buffer.flush()
finally:
    db_session.remove()
```

### 17.5 SocketIO Throttling

With 50+ positions, emitting per-position SocketIO events on every LTP tick can produce 65+ emits/second, causing UI jank and thread contention.

**Solution**: Aggregate and throttle SocketIO emits:

```
Risk Engine (per LTP tick):
  1. Update in-memory position state (fast)
  2. Check triggers (fast)
  3. Buffer position updates → PositionUpdateBuffer

Emit Thread (separate, runs every 200-500ms):
  1. Collect all changed positions since last emit
  2. Emit ONE batched event per strategy: strategy_positions_batch_update
  3. Emit ONE strategy_pnl_update per strategy
  4. Emit strategy_group_update per combined group (if changed)
```

**Frontend**: React components use `requestAnimationFrame` to batch incoming SocketIO state updates, preventing unnecessary re-renders.

**SocketIO rooms**: Emit to strategy-specific rooms (`strategy_{id}`) so only subscribed clients receive events.

### 17.6 Webhook Deduplication

TradingView and other signal sources may send duplicate webhooks (network retries, duplicate alerts). The system rejects duplicate signals within a configurable window:

```python
def is_duplicate_webhook(strategy_id, symbol, action, window_seconds=5):
    """Reject if identical signal received within window."""
    key = f"{strategy_id}:{symbol}:{action}"
    now = time.time()
    if key in _recent_signals and (now - _recent_signals[key]) < window_seconds:
        return True
    _recent_signals[key] = now
    return False
```

Window default: 5 seconds. Configurable per strategy if needed.

### 17.7 MIS Auto Square-Off

For positions with `product_type = 'MIS'`, an automatic square-off is triggered at the configured time (default 15:15 IST):

```
APScheduler job (runs every minute during market hours):
  │
  ├─ Check current time (IST)
  │
  ├─ For each strategy with open MIS positions:
  │   ├─ If current_time >= strategy.auto_squareoff_time:
  │   │   ├─ Place exit orders for all MIS positions
  │   │   ├─ exit_reason = 'squareoff', exit_detail = 'auto_squareoff_mis'
  │   │   └─ Emit SocketIO: strategy_auto_squareoff
  │   └─ If current_time < auto_squareoff_time: skip
  │
  └─ CNC and NRML positions: Not affected
```

---

## 18. Configuration

### 18.1 Environment Variables (New)

```env
# Strategy Risk Engine
STRATEGY_RISK_ENGINE_TYPE=websocket          # 'websocket' or 'polling'
STRATEGY_RISK_ENGINE_FALLBACK=true           # Enable auto-fallback
STRATEGY_ORDER_POLL_INTERVAL=1               # OrderStatus poll interval (seconds)
STRATEGY_RISK_STALE_THRESHOLD=30             # Seconds before data considered stale
STRATEGY_PNL_SNAPSHOT_TIME=15:35             # Daily PnL snapshot time (IST)
STRATEGY_DEFAULT_SQUAREOFF_TIME=15:15        # Default MIS auto square-off time (IST)
STRATEGY_WEBHOOK_DEDUP_WINDOW=5              # Webhook deduplication window (seconds)
STRATEGY_POSITION_UPDATE_INTERVAL=1.0        # Batched DB flush interval (seconds)
STRATEGY_SOCKETIO_THROTTLE_MS=300            # SocketIO emit throttle (milliseconds)
```

### 18.2 Defaults

All risk parameters are optional. A strategy with no SL/target/trailing configured simply tracks positions and PnL without automated exits.

---

## 19. Database Migration

Migration follows the existing OpenAlgo pattern: standalone idempotent scripts in `upgrade/`, registered in `migrate_all.py`, run via `uv run upgrade/migrate_all.py`.

### 19.1 New Migration Script: `upgrade/migrate_strategy_risk.py`

Follows the same conventions as `migrate_sandbox.py`:

```python
#!/usr/bin/env python
"""
Strategy Risk Management Migration Script for OpenAlgo

Creates new tables for strategy-level risk management, position tracking,
and order tracking. Adds risk columns to existing Strategy/ChartinkStrategy
and SymbolMapping tables.

Usage:
    cd upgrade
    uv run migrate_strategy_risk.py           # Apply migration
    uv run migrate_strategy_risk.py --status  # Check status

Migration: strategy_risk_management
"""

MIGRATION_NAME = "strategy_risk_management"
MIGRATION_VERSION = "001"
```

**Functions to implement** (following existing pattern):

```python
def upgrade():
    """Apply complete strategy risk setup."""
    engine = get_main_db_engine()         # db/openalgo.db
    with engine.connect() as conn:
        set_sqlite_pragmas(conn)          # WAL mode, busy_timeout
        create_new_tables(conn)           # strategy_order, strategy_position, etc.
        create_indexes(conn)              # Performance indexes
        add_risk_columns_to_strategy(conn)
        add_risk_columns_to_chartink(conn)
        add_mapping_columns_to_strategy_symbol_mapping(conn)
        add_mapping_columns_to_chartink_symbol_mapping(conn)

def status():
    """Check if migration is applied."""

def rollback():
    """Reverse migration (drop new tables, columns cannot be dropped in SQLite)."""
```

### 19.2 New Tables (CREATE TABLE IF NOT EXISTS)

All in `db/openalgo.db`:

- `strategy_order` (Section 5.3) — order tracking per strategy
- `strategy_position` (Section 5.4) — live + historical positions, partial index on active
- `strategy_trade` (Section 5.5) — filled trade audit trail
- `strategy_daily_pnl` (Section 5.6) — end-of-day snapshots
- `strategy_position_group` (Section 5.7) — combined P&L group state

### 19.3 Columns Added to Existing Tables (PRAGMA table_info check)

Each column is checked via `PRAGMA table_info(table_name)` before `ALTER TABLE ADD COLUMN` (same pattern as `migrate_sandbox.py`).

**Strategy + ChartinkStrategy** (11 columns each):
```
default_stoploss_type, default_stoploss_value, default_target_type,
default_target_value, default_trailstop_type, default_trailstop_value,
default_breakeven_type, default_breakeven_threshold, risk_monitoring (DEFAULT 'active'),
auto_squareoff_time (DEFAULT '15:15'), default_exit_execution (DEFAULT 'market')
```

**ChartinkStrategy only** (fix pre-existing schema gap):
```
trading_mode VARCHAR(10)  -- Strategy has this, ChartinkStrategy doesn't
```

**StrategySymbolMapping + ChartinkSymbolMapping** (23 columns each):
```
order_mode (DEFAULT 'equity'), underlying, underlying_exchange, expiry_type,
offset, option_type, risk_mode, preset, legs_config (TEXT/JSON),
combined_stoploss_type, combined_stoploss_value, combined_target_type,
combined_target_value, combined_trailstop_type, combined_trailstop_value,
stoploss_type, stoploss_value, target_type, target_value,
trailstop_type, trailstop_value, breakeven_type, breakeven_threshold,
exit_execution
```

### 19.4 SQLite PRAGMA Setup

The migration also sets WAL mode and busy_timeout on the main database (Section 17.1):

```python
def set_sqlite_pragmas(conn):
    """Configure SQLite for concurrent access."""
    conn.execute(text("PRAGMA journal_mode=WAL"))
    conn.execute(text("PRAGMA busy_timeout=5000"))
    conn.execute(text("PRAGMA synchronous=NORMAL"))
    conn.execute(text("PRAGMA wal_autocheckpoint=1000"))
```

### 19.5 Registration in `migrate_all.py`

Add to the `MIGRATIONS` list:

```python
MIGRATIONS = [
    # ... existing migrations ...
    ("migrate_strategy_risk.py", "Strategy Risk Management & Position Tracking"),
]
```

### 19.6 Migration Notes

- **Idempotent**: Safe to run multiple times (`CREATE TABLE IF NOT EXISTS`, `PRAGMA table_info` checks)
- **Non-destructive**: New columns are nullable; existing data untouched
- **Backward compatible**: Strategies without risk columns continue to work (NULL = not configured)
- **No data migration**: All new columns have sensible defaults or are nullable
- **Run via**: `uv run upgrade/migrate_all.py` (includes all migrations) or `uv run upgrade/migrate_strategy_risk.py` (standalone)

---

## 20. Implementation Phases

### Phase 1: Database & Core Tracking
- New database tables (StrategyOrder, StrategyPosition, StrategyTrade, StrategyDailyPnL)
- Extend Strategy/ChartinkStrategy tables with risk columns + breakeven
- Extend SymbolMapping tables with override columns + order_mode + options config
- OrderStatusPoller service
- StrategyPositionTracker service
- Webhook handler integration (save orders, queue for polling)
- Tick size caching from symbol service

### Phase 2: Risk Engine & Real-Time Status
- StrategyRiskEngine (WebSocket primary + polling fallback)
- SL/target/trailing stop trigger logic with tick size rounding
- Trailing stop price recalculation
- Breakeven threshold detection and SL move
- Per-leg mode monitoring
- Combined P&L mode monitoring (position groups)
- Exit order placement via placeorder (with auto-split for freeze qty)
- Real-time SocketIO events: position updates, group updates, PnL updates, exit triggers
- Order status tracking on every entry/exit with SocketIO emit per status change
- Exit status classification (exit_reason + exit_detail on StrategyPosition)
- Activate/deactivate controls
- Master contract download prerequisite check
- Restart recovery

### Phase 3: Futures & Options Order Mapping
- Symbol mapping UI: order mode selector (equity / futures / single option / multi-leg)
- Underlying search selector with typeahead (searches master contract)
- Futures configuration: underlying, expiry_type (current_month/next_month), product_type
- Single option configuration: underlying, expiry_type, offset, option_type
- Multi-leg configuration: preset templates + custom legs (options + futures mixed)
- Product type validation (CNC/MIS for equity, NRML/MIS for F&O)
- Per-leg risk params editor
- Combined risk params editor
- Relative expiry resolution at webhook trigger time
- Integration with OptionsOrder and OptionsMultiOrder services
- Freeze quantity auto-split via SplitOrder service
- Breakeven configuration UI
- Auto square-off time picker for MIS positions (default 15:15 IST)

### Phase 4: Frontend Dashboard
- Strategy Dashboard page (`/strategy/dashboard`)
- Strategy cards with position tables (equity + options legs)
- Position group display (combined legs shown together)
- Live P&L via SocketIO push events (per-leg + combined + strategy aggregate)
- Live risk values (SL, TGT, TSL) updating in real-time via SocketIO
- Exit status badges (SL/TGT/TSL/BE-SL/C-SL/C-TGT/C-TSL/Manual/SQ-OFF)
- "Exiting..." spinner state during exit order lifecycle
- Close individual / Close all / Close group actions
- Activate / Deactivate toggle
- Orders, Trades, P&L drawer views

### Phase 5: Notifications & Polish
- New `strategyRisk` toast category
- SocketIO events for all risk triggers
- Telegram alert integration
- Daily PnL snapshot scheduler
- Position deletion protection
- Profile → Alerts configuration

---

## 21. Key Constraints & Safety

| Constraint | Handling |
|-----------|---------|
| OrderStatus rate limit (1 req/sec) | Single poller thread, 1 second sleep between calls; priority queue (exits first) |
| OrderBook/TradeBook/PositionBook rate limit (1 req/sec) | Never used — all data from local DB tables |
| WebSocket stale data | `is_trade_management_safe()` check before every trigger |
| App restart | DB persistence + recovery sequence + broker reconciliation on startup |
| Multi-strategy same symbol | Each strategy has isolated positions; exits use `placeorder` with tracked qty |
| Rejected exit order | Position remains open, warning emitted, trader must handle manually. Combined mode: `failed_exit` group status with "Retry Exit" button |
| Partial fills | Update position quantity proportionally; `intended_quantity` tracks original intent; warning badge if partial |
| Market closed | Risk engine only monitors during market hours |
| Position deletion | Blocked while quantity > 0 |
| Strategy deletion | Blocked if any position has quantity > 0 |
| Freeze quantity | Auto-split via SplitOrder service; configured centrally in /admin |
| Tick size | All computed prices rounded via `round_to_tick()`; fetched from symbol service |
| Lot size | Always fetched from symbol service; NEVER hardcoded; validated at order time |
| Options/futures expiry | Resolved at webhook trigger time (relative expiry); stale expiry dates rejected |
| Combined P&L exit | ALL legs exit together; deferred until all legs fill (`group_status = 'active'`) |
| Combined P&L partial exit failure | Group marked `failed_exit`; CRITICAL alert; "Retry Exit" button for failed legs |
| Breakeven + trail interaction | Effective stop = max(SL, TSL) for longs, min(SL, TSL) for shorts — tighter stop wins |
| Master contract not downloaded | Risk engine refuses to start; webhook orders blocked; UI shows warning banner |
| SQLite concurrency | WAL mode + busy_timeout=5000 + batched writes + per-position locks (Section 17) |
| Webhook deduplication | Reject identical signals within configurable window (default 5s) |
| Position state guard | `position_state` prevents race conditions: exiting position rejects new entries |
| MIS auto square-off | Configurable per strategy (default 15:15 IST); only MIS positions affected |
| Product type validation | CNC/MIS for equity; NRML/MIS for futures & options; enforced at config + order time |
| All timestamps | Displayed in IST (Indian Standard Time) throughout the system |

---

## 22. Files to Create / Modify

### New Files
| File | Purpose |
|------|---------|
| `upgrade/migrate_strategy_risk.py` | Database migration script (idempotent, registered in migrate_all.py) |
| `services/strategy_risk_engine.py` | Dual-engine risk monitoring (per-leg + combined P&L) |
| `services/strategy_position_tracker.py` | Position tracking, breakeven, and PnL |
| `services/strategy_order_poller.py` | OrderStatus polling (1 req/sec) |
| `services/strategy_pnl_service.py` | PnL calculation and daily snapshots |
| `services/strategy_options_resolver.py` | Resolve relative expiry, strike offset, fetch tick_size/lot_size/freeze_qty |
| `services/strategy_exit_executor.py` | Pluggable exit execution strategies (MarketExecution in V1; future: mid, chase, TWAP) |
| `database/strategy_position_db.py` | New table models (StrategyOrder, StrategyPosition, StrategyTrade, StrategyDailyPnL, StrategyPositionGroup) |
| `frontend/src/pages/StrategyDashboard.tsx` | Dashboard page |
| `frontend/src/api/strategy-dashboard.ts` | API layer |
| `frontend/src/types/strategy-dashboard.ts` | TypeScript types |
| `frontend/src/components/strategy-dashboard/` | Dashboard components (StrategyCard, PositionTable, PositionGroupTable, OrdersDrawer, TradesDrawer, PnLDrawer) |
| `frontend/src/components/strategy/FuturesOptionsLegEditor.tsx` | UI for configuring futures / single option / multi-leg with preset templates |
| `frontend/src/components/strategy/UnderlyingSearch.tsx` | Typeahead search for underlying symbol selection |
| `frontend/src/components/strategy/RiskParamsEditor.tsx` | Reusable SL/target/trail/breakeven configuration form |

### Modified Files
| File | Change |
|------|--------|
| `upgrade/migrate_all.py` | Register `migrate_strategy_risk.py` in MIGRATIONS list |
| `database/strategy_db.py` | Add risk + breakeven + options columns to Strategy + StrategySymbolMapping models |
| `database/chartink_db.py` | Add risk + breakeven + options columns to ChartinkStrategy + ChartinkSymbolMapping models + add `trading_mode` |
| `blueprints/strategy.py` | Integrate order tracking, options/futures routing, squareoff change, auto-split, dedup, position state checks |
| `blueprints/chartink.py` | Same as strategy.py |
| `app.py` | Initialize StrategyRiskEngine on startup + restart recovery + broker reconciliation |
| `frontend/src/stores/alertStore.ts` | Add `strategyRisk` category |
| `frontend/src/pages/Profile.tsx` | Add strategyRisk to alert categories config |
| `frontend/src/hooks/useSocket.ts` | Handle new strategy risk SocketIO events |
| `frontend/src/router.tsx` | Add `/strategy/dashboard` route |
| `frontend/src/pages/strategy/` | Add options mapping UI to symbol configuration pages |
