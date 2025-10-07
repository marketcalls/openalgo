# OpenAlgo Sandbox Mode (API Analyzer)

## Overview

OpenAlgo Sandbox Mode, also known as **API Analyzer**, is a sophisticated simulation environment that enables traders and developers to test their trading strategies with realistic market conditions using simulated funds. This mode provides a risk-free environment to validate strategies, test algorithms, and understand market dynamics before deploying in live trading.

**Key Features:**
- ✅ Realistic order execution with live market data
- ✅ Simulated funds: ₹10,000,000 (1 Crore)
- ✅ Automatic fund reset every Sunday at midnight IST
- ✅ Support for all exchanges (NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCDEX)
- ✅ Leverage-based margin calculations
- ✅ Real-time MTM (Mark to Market) updates
- ✅ Automatic position square-off for MIS
- ✅ T+1 settlement for CNC holdings
- ✅ Complete order lifecycle management

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Fund Management](#fund-management)
3. [Leverage Rules](#leverage-rules)
4. [Order Execution](#order-execution)
5. [Position Management](#position-management)
6. [Holdings Management](#holdings-management)
7. [Auto Square-Off Timings](#auto-square-off-timings)
8. [Market Data Integration](#market-data-integration)
9. [Configuration](#configuration)
10. [Database Schema](#database-schema)
11. [API Response Format](#api-response-format)
12. [Edge Cases & Validations](#edge-cases--validations)

---

## Getting Started

### Enabling Sandbox Mode

Sandbox mode is controlled via the Analyzer Toggle API:

```python
# Enable Sandbox Mode
from services.analyzer_service import toggle_analyzer_mode

analyzer_data = {"mode": True}
success, response, status_code = toggle_analyzer_mode(
    analyzer_data=analyzer_data,
    api_key='your_api_key'
)

# Response:
{
  "status": "success",
  "data": {
    "mode": "analyze",
    "analyze_mode": True,
    "message": "Analyzer mode switched to analyze"
  }
}
```

### Checking Sandbox Status

```python
from services.analyzer_service import get_analyzer_status

success, response, status_code = get_analyzer_status(
    analyzer_data={},
    api_key='your_api_key'
)

# Response:
{
  "status": "success",
  "data": {
    "mode": "analyze",  # or "live"
    "analyze_mode": True
  }
}
```

---

## Fund Management

### Initial Capital

| Parameter | Value |
|-----------|-------|
| Starting Balance | ₹10,000,000 (1 Crore) |
| Reset Frequency | Every Sunday at 00:00 IST |
| Reset Trigger | Automatic |
| Manual Reset | Not allowed until Sunday |

### Fund Components

```json
{
  "status": "success",
  "data": {
    "availablecash": "9500000.00",      // Available for new trades
    "collateral": "250000.00",           // From holdings
    "m2mrealized": "25000.00",           // Realized P&L
    "m2munrealized": "-15000.00",        // Unrealized P&L
    "utiliseddebits": "500000.00"        // Margin utilized
  }
}
```

### Fund Calculation Logic

1. **Available Cash** = Starting Balance - Utilized Margin + Realized P&L
2. **Utilized Margin** = Sum of all margin blocked for open positions
3. **M2M Realized** = Cumulative realized profit/loss from closed positions
4. **M2M Unrealized** = Current floating P&L from open positions
5. **Collateral** = Value available from holdings (CNC positions)

### Sunday Reset Behavior

At **00:00 IST every Sunday**:
- Available cash reset to ₹10,000,000
- All M2M realized/unrealized reset to ₹0.00
- Utilized margin recalculated based on existing positions
- Collateral recalculated from holdings
- Order history archived (optional)

---

## Leverage Rules

Sandbox mode uses **simplified, standardized leverage** based on exchange and product type:

### Equity Exchanges (NSE, BSE)

| Product Type | Leverage | Margin Required | Example |
|--------------|----------|-----------------|---------|
| **MIS** (Intraday) | **5x** | 20% of trade value | Buy 100 shares @ ₹1000 = ₹20,000 margin |
| **CNC** (Delivery) | **1x** | 100% of trade value | Buy 100 shares @ ₹1000 = ₹100,000 margin |

### Derivatives - Futures (NFO, BFO, CDS, BCD, MCX)

| Product Type | Leverage | Margin Required | Example |
|--------------|----------|-----------------|---------|
| **MIS** (Intraday) | **10x** | 10% of contract value | 1 lot NIFTY FUT @ ₹25,000 × 50 = ₹125,000 margin |
| **NRML** (Carry Forward) | **10x** | 10% of contract value | 1 lot BANKNIFTY FUT @ ₹50,000 × 25 = ₹125,000 margin |

**Contract Value Calculation:**
```
Contract Value = LTP × Lot Size
Margin Required = Contract Value ÷ Leverage
```

### Derivatives - Options (NFO, BFO)

#### Buying Options (Long Call/Put)

| Product Type | Margin Required | Example |
|--------------|-----------------|---------|
| **MIS / NRML** | **Premium Amount** | Buy 1 lot NIFTY CE @ ₹100 × 50 = ₹5,000 |

**Calculation:**
```
Margin = Premium × Lot Size
```

#### Selling Options (Short Call/Put)

| Product Type | Margin Required | Example |
|--------------|-----------------|---------|
| **MIS / NRML** | **Equivalent Futures Margin** | Sell 1 lot NIFTY CE = Use NIFTY FUT margin |

**Calculation:**
```
For selling options, use the margin of equivalent futures contract
Example: Selling NIFTY23DEC2525000CE requires margin as if selling NIFTY23DEC25FUT
Margin = (Underlying Future LTP × Lot Size) ÷ 10
```

### Margin Blocking Examples

**Example 1: NSE Equity MIS**
```
Symbol: RELIANCE
Action: BUY
Quantity: 100
LTP: ₹1,200
Product: MIS

Trade Value = 100 × ₹1,200 = ₹120,000
Margin Required = ₹120,000 ÷ 5 = ₹24,000
```

**Example 2: NFO Futures**
```
Symbol: NIFTY15JAN2525000FUT
Action: BUY
Quantity: 1 lot
LTP: ₹25,150
Lot Size: 50
Product: MIS

Contract Value = ₹25,150 × 50 = ₹1,257,500
Margin Required = ₹1,257,500 ÷ 10 = ₹125,750
```

**Example 3: NFO Option Buying**
```
Symbol: NIFTY15JAN2525000CE
Action: BUY
Quantity: 1 lot
Premium: ₹150
Lot Size: 50
Product: MIS

Margin Required = ₹150 × 50 = ₹7,500
```

**Example 4: NFO Option Selling**
```
Symbol: NIFTY15JAN2525000CE
Action: SELL
Quantity: 1 lot
Premium: ₹150
Lot Size: 50
Underlying Future LTP: ₹25,150
Product: MIS

Margin Required = (₹25,150 × 50) ÷ 10 = ₹125,750
(Uses futures margin, not premium)
```

---

## Order Execution

### Order Types Supported

| Order Type | Description | Execution Logic |
|------------|-------------|-----------------|
| **MARKET** | Immediate execution | Executes at current LTP from quotes service |
| **LIMIT** | Price-specific order | Executes when LTP crosses limit price |
| **SL** (Stop Loss Limit) | Trigger + Limit price | Triggers at trigger_price, then becomes LIMIT order |
| **SL-M** (Stop Loss Market) | Trigger + Market execution | Triggers at trigger_price, executes immediately at LTP |

### Market Order Execution

**Immediate Execution:**
```
When: Order placed
Execution Price: Current LTP from quotes service
Status: Immediately moves to "complete"
Trade Entry: Created with average_price = LTP
```

**Example:**
```json
{
  "symbol": "RELIANCE",
  "action": "BUY",
  "exchange": "NSE",
  "price_type": "MARKET",
  "product": "MIS",
  "quantity": 100
}

Execution:
- Fetch LTP from quotes service: ₹1,200.50
- Execute order at: ₹1,200.50
- Total Value: 100 × ₹1,200.50 = ₹120,050
- Margin Blocked: ₹120,050 ÷ 5 = ₹24,010
- Order Status: "complete"
```

### Limit Order Execution

**BUY LIMIT Order:**
```
Trigger Condition: LTP <= Limit Price
Execution Price: Limit Price (or better)
Status: "open" → "complete" when triggered
```

**SELL LIMIT Order:**
```
Trigger Condition: LTP >= Limit Price
Execution Price: Limit Price (or better)
Status: "open" → "complete" when triggered
```

**Example:**
```json
{
  "symbol": "YESBANK",
  "action": "BUY",
  "exchange": "NSE",
  "price_type": "LIMIT",
  "product": "MIS",
  "quantity": 1000,
  "price": 16.50
}

Order Flow:
1. Order placed with status "open"
2. Background checker runs every 5 seconds
3. When LTP <= ₹16.50:
   - Order status → "complete"
   - Execution price: ₹16.50
   - Trade entry created
```

### Stop Loss Order Execution

**SL (Stop Loss Limit):**
```
Stage 1: Monitor trigger_price
  When: LTP crosses trigger_price
  Action: Convert to LIMIT order

Stage 2: Execute as LIMIT order
  When: LTP crosses limit price
  Action: Execute order
```

**SL-M (Stop Loss Market):**
```
Stage 1: Monitor trigger_price
  When: LTP crosses trigger_price
  Action: Execute immediately at current LTP
```

**Example SL Order:**
```json
{
  "symbol": "SBIN",
  "action": "SELL",
  "exchange": "NSE",
  "price_type": "SL",
  "product": "MIS",
  "quantity": 500,
  "price": 769.00,
  "trigger_price": 770.00
}

Execution Flow:
1. Order placed with status "open"
2. Waiting for LTP <= ₹770.00 (trigger)
3. When LTP touches ₹770.00:
   - Order becomes LIMIT order at ₹769.00
   - Now waiting for LTP <= ₹769.00
4. When LTP <= ₹769.00:
   - Execute at ₹769.00
   - Status: "complete"
```

### Order Checker Background Process

**Configuration:**
- Check Frequency: Every **5 seconds** (configurable)
- Scope: All pending orders with status "open"
- Data Source: Real-time quotes from `quotes_service.py`
- **Rate Limits**: Respects `.env` configured limits

**Rate Limit Compliance:**

From `.env` file:
```
API_RATE_LIMIT = "50 per second"
ORDER_RATE_LIMIT = "10 per second"
SMART_ORDER_RATE_LIMIT = "2 per second"
```

**Batch Processing Logic:**
```python
# Process orders in batches to respect rate limits
MAX_ORDERS_PER_BATCH = 10  # ORDER_RATE_LIMIT
BATCH_DELAY = 1.0          # 1 second between batches

def check_pending_orders():
    """Check pending orders with rate limit compliance"""
    pending_orders = get_all_pending_orders()

    # Split into batches of 10 orders
    for i in range(0, len(pending_orders), MAX_ORDERS_PER_BATCH):
        batch = pending_orders[i:i + MAX_ORDERS_PER_BATCH]

        # Process batch
        for order in batch:
            check_and_execute_order(order)

        # Wait 1 second before next batch
        if i + MAX_ORDERS_PER_BATCH < len(pending_orders):
            time.sleep(BATCH_DELAY)
```

**Process Flow:**
```python
Every 5 seconds:
1. Fetch all pending orders (status = "open")
2. Batch orders into groups of 10 (ORDER_RATE_LIMIT)
3. For each batch:
   a. Get unique symbols (avoid duplicate quote fetches)
   b. Fetch LTP for all symbols in batch (batch quotes request)
   c. Check trigger conditions for each order:
      - LIMIT: Check if LTP crosses limit price
      - SL: Check if LTP crosses trigger_price
      - SL-M: Check if LTP crosses trigger_price
   d. If condition met:
      - Update order status to "complete"
      - Create trade entry
      - Update position
      - Deduct/release margin
      - Update funds
   e. Wait 1 second before processing next batch
```

---

## Position Management

### Position States

| State | Description | Affected By |
|-------|-------------|-------------|
| **Open** | Active position with quantity ≠ 0 | Buy/Sell orders |
| **Closed** | Position squared off, quantity = 0 | Reverse trades |
| **Squared Off** | Auto-closed by system | Auto square-off |

### Position Calculation

**Net Quantity:**
```
Net Quantity = Buy Quantity - Sell Quantity

Examples:
- Buy 100, Sell 50 = Net: +50 (Long)
- Buy 50, Sell 100 = Net: -50 (Short)
- Buy 100, Sell 100 = Net: 0 (Closed)
```

**Average Price Calculation:**
```
Average Price = Total Trade Value ÷ Total Quantity

Example:
- Buy 100 @ ₹1000 = ₹100,000
- Buy 50 @ ₹1050 = ₹52,500
- Total: 150 shares @ ₹152,500
- Average: ₹152,500 ÷ 150 = ₹1,016.67
```

**P&L Calculation:**

**For Long Positions:**
```
Unrealized P&L = (Current LTP - Average Buy Price) × Quantity
Realized P&L = (Sell Price - Average Buy Price) × Quantity Sold
```

**For Short Positions:**
```
Unrealized P&L = (Average Sell Price - Current LTP) × Quantity
Realized P&L = (Average Sell Price - Buy Price) × Quantity Bought
```

### MTM (Mark to Market) Updates

**Update Frequency:**
- **User Refresh**: On-demand when user accesses positions/holdings
- **Auto-Refresh**: Every 5 seconds (if configured in sandbox settings)
- **Data Source**: Live LTP from quotes service

**Calculation Logic:**
```python
def calculate_mtm(position):
    """Calculate MTM for a position"""
    current_ltp = get_quotes(position.symbol, position.exchange)['ltp']

    if position.quantity > 0:  # Long position
        unrealized_pnl = (current_ltp - position.average_price) * position.quantity
    elif position.quantity < 0:  # Short position
        unrealized_pnl = (position.average_price - current_ltp) * abs(position.quantity)
    else:  # Closed position
        unrealized_pnl = 0

    return {
        'ltp': current_ltp,
        'unrealized_pnl': unrealized_pnl,
        'pnl_percent': (unrealized_pnl / (position.average_price * abs(position.quantity))) * 100
    }
```

### MIS Position Management

**Characteristics:**
- Intraday only (no carry forward)
- Higher leverage (5x equity, 10x derivatives)
- Auto square-off at specified time
- Squared off at **MARKET PRICE**

**Example:**
```
Position:
- Symbol: TATAMOTORS
- Action: BUY
- Quantity: 500
- Entry Price: ₹950
- Product: MIS
- Exchange: NSE

Square-Off Time: 3:15 PM IST
Square-Off Action: SELL 500 @ MARKET (e.g., ₹955)
Realized P&L: (₹955 - ₹950) × 500 = ₹2,500
```

### NRML Position Management

**Characteristics:**
- Carry forward allowed
- Lower leverage (10x for derivatives)
- No auto square-off
- Converted to holdings for equity

**Example:**
```
Position:
- Symbol: NIFTY15JAN2525000FUT
- Action: BUY
- Quantity: 1 lot (50 qty)
- Entry Price: ₹25,150
- Product: NRML
- Exchange: NFO

Carry Forward: Position remains open overnight
Daily MTM: P&L calculated at EOD
Settlement: At futures expiry
```

### CNC Position Management

**Characteristics:**
- Delivery-based (no leverage)
- Full payment required
- Moved to holdings after T+1 settlement
- No auto square-off

**T+1 Settlement Process:**
```
Day 0 (T): Order executed
- Status: In positions as "CNC"
- Funds: Blocked 100%

Day 1 (T+1): Settlement
- Status: Moved to holdings
- Available: Can be sold or held long-term
```

---

## Holdings Management

### Holdings Creation

**From CNC Positions:**
```
Timeline:
T+0: Buy 100 shares of RELIANCE @ ₹1,200 (CNC)
T+1: Position moves to holdings
     - Average Price: ₹1,200
     - Quantity: 100
     - Investment Value: ₹120,000
```

**Manual Entry (for testing):**
```json
{
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "quantity": 100,
  "average_price": 1200.00,
  "product": "CNC"
}
```

### Holdings P&L Calculation

**Current Value:**
```
Current Value = Current LTP × Quantity
Investment Value = Average Buy Price × Quantity
P&L = Current Value - Investment Value
P&L % = (P&L / Investment Value) × 100
```

**Example:**
```
Holding:
- Symbol: RELIANCE
- Quantity: 100
- Average Price: ₹1,200
- Current LTP: ₹1,250

Calculations:
- Investment Value: ₹1,200 × 100 = ₹120,000
- Current Value: ₹1,250 × 100 = ₹125,000
- P&L: ₹125,000 - ₹120,000 = ₹5,000
- P&L %: (₹5,000 / ₹120,000) × 100 = 4.17%
```

### Holdings Response Format

```json
{
  "status": "success",
  "data": {
    "holdings": [
      {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": 100,
        "average_price": 1200.00,
        "ltp": 1250.00,
        "pnl": 5000.00,
        "pnlpercent": 4.17
      }
    ],
    "statistics": {
      "totalholdingvalue": 125000.00,
      "totalinvvalue": 120000.00,
      "totalprofitandloss": 5000.00,
      "totalpnlpercentage": 4.17
    }
  }
}
```

### Holdings as Collateral

**Collateral Value:**
```
Collateral = Sum of (LTP × Quantity × Haircut Factor)

Haircut Factors (configurable):
- Large Cap Stocks: 80% (0.8)
- Mid Cap Stocks: 70% (0.7)
- Small Cap Stocks: 60% (0.6)
- Default: 75% (0.75)
```

**Example:**
```
Holding: RELIANCE (Large Cap)
- Quantity: 100
- LTP: ₹1,250
- Haircut: 80%

Collateral = ₹1,250 × 100 × 0.8 = ₹100,000
```

---

## Auto Square-Off Timings

### Exchange-Specific Timings (All in IST)

| Exchange | Product | Square-Off Time | Execution Type |
|----------|---------|-----------------|----------------|
| **NSE** | MIS | 3:15 PM | MARKET |
| **BSE** | MIS | 3:15 PM | MARKET |
| **NFO** | MIS | 3:15 PM | MARKET |
| **BFO** | MIS | 3:15 PM | MARKET |
| **CDS** | MIS | 4:45 PM | MARKET |
| **BCD** | MIS | 4:45 PM | MARKET |
| **MCX** | MIS | 11:30 PM | MARKET |
| **NCDEX** | MIS | 11:30 PM | MARKET |

### Square-Off Configuration

**Configurable in Sandbox Settings:**
```json
{
  "auto_square_off": {
    "enabled": true,
    "timings": {
      "NSE": "15:15:00",      // 3:15 PM
      "BSE": "15:15:00",      // 3:15 PM
      "NFO": "15:15:00",      // 3:15 PM
      "BFO": "15:15:00",      // 3:15 PM
      "CDS": "16:45:00",      // 4:45 PM
      "BCD": "16:45:00",      // 4:45 PM
      "MCX": "23:30:00",      // 11:30 PM
      "NCDEX": "23:30:00"     // 11:30 PM
    },
    "warning_minutes": 5      // Warn 5 minutes before square-off
  }
}
```

### Square-Off Process

**5 Minutes Before Square-Off:**
```
1. Alert user via notification/email
2. List all MIS positions to be squared off
3. Show current P&L for each position
```

**At Square-Off Time:**
```python
def auto_square_off(exchange, time):
    """Auto square-off MIS positions at EOD"""
    # Get all open MIS positions for exchange
    positions = get_open_mis_positions(exchange)

    for position in positions:
        # Fetch current market price
        ltp = get_quotes(position.symbol, exchange)['ltp']

        # Place reverse order at MARKET
        reverse_order = {
            'symbol': position.symbol,
            'action': 'SELL' if position.quantity > 0 else 'BUY',
            'quantity': abs(position.quantity),
            'price_type': 'MARKET',
            'product': 'MIS',
            'exchange': exchange
        }

        # Execute at LTP
        execute_order(reverse_order, execution_price=ltp)

        # Calculate realized P&L
        realized_pnl = calculate_pnl(position, ltp)

        # Update funds
        release_margin(position)
        update_realized_pnl(realized_pnl)
```

### Pending Order Cancellation

**End of Day (EOD) Cancellation:**
```
Timing: After square-off time + 30 minutes
Action: Cancel all pending orders (status = "open")
Reason: Market closed, orders cannot be executed
```

**Cancellation Logic:**
```python
def cancel_pending_orders_eod(exchange):
    """Cancel all pending orders at EOD"""
    cutoff_time = get_square_off_time(exchange) + timedelta(minutes=30)

    if current_time >= cutoff_time:
        # Get all pending orders
        pending_orders = get_orders(status='open', exchange=exchange)

        for order in pending_orders:
            # Update order status
            order.status = 'cancelled'
            order.remarks = 'Auto-cancelled at EOD'

            # Release blocked margin
            release_margin(order)
```

---

## Market Data Integration

### Real-Time Data Sources

All market data is fetched from **live broker feeds** via OpenAlgo services:

| Data Type | Service | Update Frequency | Usage |
|-----------|---------|------------------|-------|
| **LTP** | `quotes_service.py` | Every 5 seconds | Order execution, MTM |
| **Quotes** | `quotes_service.py` | On-demand | OHLC, Volume, Bid/Ask |
| **Depth** | `depth_service.py` | On-demand | Market depth analysis |
| **History** | `history_service.py` | On-demand | Historical charts |
| **Symbol Info** | `symbol_service.py` | On-demand | Lot size, tick size |

### Quotes Service Integration

**Usage for Order Execution:**
```python
from services.quotes_service import get_quotes

# Fetch current LTP
success, response, status_code = get_quotes(
    symbol="RELIANCE",
    exchange="NSE",
    auth_token=auth_token,
    broker=broker
)

# Response:
{
  "status": "success",
  "data": {
    "open": 1172.0,
    "high": 1196.6,
    "low": 1163.3,
    "ltp": 1187.75,      # Use for execution
    "ask": 1188.0,
    "bid": 1187.85,
    "prev_close": 1165.7,
    "volume": 14414545
  }
}

# Execute order at LTP
execution_price = response['data']['ltp']
```

### Symbol Service Integration

**Fetch Lot Size and Tick Size:**
```python
from services.symbol_service import get_symbol_info

success, response, status_code = get_symbol_info(
    symbol="NIFTY15JAN2525000FUT",
    exchange="NFO",
    auth_token=auth_token,
    broker=broker
)

# Response:
{
  "status": "success",
  "data": {
    "symbol": "NIFTY15JAN2525000FUT",
    "lotsize": 50,
    "tick_size": 0.05,
    "instrumenttype": "FUTIDX",
    "expiry": "15-JAN-25",
    "strike": -0.01
  }
}

# Use for calculations
lot_size = response['data']['lotsize']
tick_size = response['data']['tick_size']
contract_value = ltp * lot_size
```

### Background Data Updater

**Configuration:**
```json
{
  "data_updater": {
    "enabled": true,
    "check_interval": 5,        // seconds
    "update_on_refresh": true,
    "auto_update": false,       // User configurable
    "batch_size": 50,           // symbols per batch (API_RATE_LIMIT)
    "respect_rate_limits": true
  }
}
```

**Rate Limit Considerations:**

From `.env`:
```
API_RATE_LIMIT = "50 per second"
```

The updater fetches quotes for up to **50 symbols per second** to comply with API rate limits.

**Update Process:**
```python
Every 5 seconds (if enabled):
1. Get all active positions + open orders
2. Extract unique symbols
3. Split symbols into batches of 50 (API_RATE_LIMIT)
4. For each batch:
   a. Batch fetch LTP for all symbols
   b. Update position MTM
   c. Check pending order triggers
   d. Wait 1 second before next batch (if needed)
5. Update funds (M2M unrealized)
6. Emit SocketIO updates (if connected)
```

**Batch Quote Fetching:**
```python
def batch_fetch_quotes(symbols, exchange):
    """Fetch quotes for multiple symbols respecting rate limits"""
    results = {}

    # Process in batches of 50 (API_RATE_LIMIT)
    for i in range(0, len(symbols), 50):
        batch = symbols[i:i + 50]

        # Fetch quotes for batch
        for symbol in batch:
            success, response, _ = get_quotes(
                symbol=symbol,
                exchange=exchange,
                auth_token=auth_token,
                broker=broker
            )
            if success:
                results[symbol] = response['data']['ltp']

        # Wait 1 second before next batch
        if i + 50 < len(symbols):
            time.sleep(1.0)

    return results
```

---

## Configuration

### Sandbox Config Settings

**Location:** Sandbox Settings Page (`/sandbox/settings`)

**Configuration Options:**

```json
{
  "sandbox_config": {
    "funds": {
      "starting_balance": 10000000,
      "reset_day": "Sunday",
      "reset_time": "00:00:00"
    },
    "leverage": {
      "equity_mis": 5,
      "equity_cnc": 1,
      "futures_mis": 10,
      "futures_nrml": 10,
      "options_buy": "premium_only",
      "options_sell": "futures_margin"
    },
    "auto_square_off": {
      "enabled": true,
      "NSE_time": "15:15:00",
      "BSE_time": "15:15:00",
      "NFO_time": "15:15:00",
      "BFO_time": "15:15:00",
      "CDS_time": "16:45:00",
      "BCD_time": "16:45:00",
      "MCX_time": "23:30:00",
      "NCDEX_time": "23:30:00",
      "warning_minutes": 5
    },
    "order_checker": {
      "check_interval": 5,
      "enabled": true,
      "batch_size": 10,
      "respect_rate_limits": true
    },
    "mtm_update": {
      "on_refresh": true,
      "auto_update": false,
      "update_interval": 5,
      "batch_size": 50,
      "respect_rate_limits": true
    },
    "holdings": {
      "settlement_days": 1,
      "auto_convert_cnc": true,
      "collateral_haircut": 0.75
    },
    "rate_limits": {
      "order_rate_limit": 10,
      "smart_order_rate_limit": 2,
      "api_rate_limit": 50,
      "smart_order_delay": 0.5
    }
  }
}
```

**Rate Limit Configuration (from `.env`):**

These values are automatically loaded from the `.env` file:

```bash
# OpenAlgo Rate Limit Settings
LOGIN_RATE_LIMIT_MIN = "5 per minute"
LOGIN_RATE_LIMIT_HOUR = "25 per hour"
RESET_RATE_LIMIT = "15 per hour"
API_RATE_LIMIT = "50 per second"         # Max API calls per second
ORDER_RATE_LIMIT = "10 per second"       # Max orders per second
SMART_ORDER_RATE_LIMIT = "2 per second"  # Max smart orders per second
WEBHOOK_RATE_LIMIT = "100 per minute"
STRATEGY_RATE_LIMIT = "200 per minute"

# Smart Order Delay
SMART_ORDER_DELAY = '0.5'  # Seconds between multi-leg orders
```

**Rate Limit Compliance:**

All sandbox operations respect these rate limits:

1. **Order Placement**: Max 10 orders/second
2. **Smart Orders**: Max 2 smart orders/second with 0.5s delay
3. **API Calls**: Max 50 quote fetches/second
4. **Batch Processing**: Orders processed in batches to stay within limits

### User Interface

**Sandbox Settings Page:**
```
/sandbox/settings

Sections:
1. Fund Management
   - Starting Balance (read-only)
   - Next Reset Date
   - Manual Reset (disabled until Sunday)

2. Leverage Settings
   - Equity MIS Multiplier
   - Equity CNC Multiplier
   - Futures Multiplier
   - Options Margin Rules

3. Auto Square-Off
   - Enable/Disable
   - Exchange-wise Timings
   - Warning Minutes

4. Order Execution
   - Order Check Interval
   - Enable Background Checker

5. MTM Updates
   - Update on Page Refresh
   - Auto-Update Every 5 Seconds
```

---

## Database Schema

### Database File

**Location:** `openalgo/sandbox/sandbox.db`

All sandbox-related tables are stored in a **separate SQLite database** to isolate from live trading data.

### Table Definitions

#### 1. sandbox_orders

```sql
CREATE TABLE sandbox_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orderid VARCHAR(50) UNIQUE NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    strategy VARCHAR(100),
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    action VARCHAR(10) NOT NULL,
    quantity INTEGER NOT NULL,
    price DECIMAL(10, 2),
    trigger_price DECIMAL(10, 2),
    disclosed_quantity INTEGER,
    price_type VARCHAR(20) NOT NULL,
    product VARCHAR(20) NOT NULL,
    order_status VARCHAR(20) NOT NULL,
    average_price DECIMAL(10, 2),
    filled_quantity INTEGER DEFAULT 0,
    pending_quantity INTEGER,
    order_timestamp DATETIME NOT NULL,
    update_timestamp DATETIME,
    remarks TEXT,
    INDEX idx_user_status (user_id, order_status),
    INDEX idx_symbol_exchange (symbol, exchange),
    INDEX idx_orderid (orderid)
);
```

**Order Status Values:**
- `open` - Pending execution
- `complete` - Fully executed
- `cancelled` - Cancelled by user or system
- `rejected` - Rejected due to validation failure

#### 2. sandbox_trades

```sql
CREATE TABLE sandbox_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orderid VARCHAR(50) NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    action VARCHAR(10) NOT NULL,
    quantity INTEGER NOT NULL,
    average_price DECIMAL(10, 2) NOT NULL,
    trade_value DECIMAL(15, 2) NOT NULL,
    product VARCHAR(20) NOT NULL,
    trade_timestamp DATETIME NOT NULL,
    FOREIGN KEY (orderid) REFERENCES sandbox_orders(orderid),
    INDEX idx_user_trades (user_id, trade_timestamp),
    INDEX idx_orderid (orderid)
);
```

#### 3. sandbox_positions

```sql
CREATE TABLE sandbox_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    product VARCHAR(20) NOT NULL,
    quantity INTEGER NOT NULL,
    average_price DECIMAL(10, 2) NOT NULL,
    last_price DECIMAL(10, 2),
    pnl DECIMAL(15, 2),
    pnl_percent DECIMAL(10, 4),
    margin_used DECIMAL(15, 2),
    created_at DATETIME NOT NULL,
    updated_at DATETIME,
    UNIQUE (user_id, symbol, exchange, product),
    INDEX idx_user_positions (user_id),
    INDEX idx_symbol_exchange (symbol, exchange)
);
```

#### 4. sandbox_holdings

```sql
CREATE TABLE sandbox_holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    quantity INTEGER NOT NULL,
    average_price DECIMAL(10, 2) NOT NULL,
    last_price DECIMAL(10, 2),
    current_value DECIMAL(15, 2),
    investment_value DECIMAL(15, 2),
    pnl DECIMAL(15, 2),
    pnl_percent DECIMAL(10, 4),
    created_at DATETIME NOT NULL,
    updated_at DATETIME,
    UNIQUE (user_id, symbol, exchange),
    INDEX idx_user_holdings (user_id)
);
```

#### 5. sandbox_funds

```sql
CREATE TABLE sandbox_funds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR(50) UNIQUE NOT NULL,
    available_cash DECIMAL(15, 2) NOT NULL,
    utilized_margin DECIMAL(15, 2) NOT NULL,
    m2m_realized DECIMAL(15, 2) NOT NULL,
    m2m_unrealized DECIMAL(15, 2) NOT NULL,
    collateral DECIMAL(15, 2) NOT NULL,
    last_reset_date DATE NOT NULL,
    last_updated DATETIME NOT NULL,
    INDEX idx_user_funds (user_id)
);
```

#### 6. sandbox_config

```sql
CREATE TABLE sandbox_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR(50) UNIQUE NOT NULL,
    config_json TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME,
    INDEX idx_user_config (user_id)
);
```

**Config JSON Structure:**
```json
{
  "starting_balance": 10000000,
  "leverage_equity_mis": 5,
  "leverage_equity_cnc": 1,
  "leverage_futures": 10,
  "auto_square_off_enabled": true,
  "order_check_interval": 5,
  "mtm_auto_update": false
}
```

---

## API Response Format

### Common Response Structure

All sandbox responses include a **`mode`** field to distinguish from live trading:

```json
{
  "mode": "analyze",
  "status": "success",
  "data": { ... }
}
```

### PlaceOrder Response

```json
{
  "mode": "analyze",
  "status": "success",
  "orderid": "2510010001"
}
```

### OrderBook Response

```json
{
  "mode": "analyze",
  "status": "success",
  "data": {
    "orders": [
      {
        "action": "BUY",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "orderid": "2510010001",
        "product": "MIS",
        "quantity": "100",
        "price": 1200.0,
        "pricetype": "MARKET",
        "order_status": "complete",
        "trigger_price": 0.0,
        "average_price": 1187.75,
        "timestamp": "01-Oct-2025 10:30:45"
      }
    ],
    "statistics": {
      "total_buy_orders": 5.0,
      "total_sell_orders": 3.0,
      "total_completed_orders": 6.0,
      "total_open_orders": 2.0,
      "total_rejected_orders": 0.0
    }
  }
}
```

### PositionBook Response

```json
{
  "mode": "analyze",
  "status": "success",
  "data": [
    {
      "symbol": "RELIANCE",
      "exchange": "NSE",
      "product": "MIS",
      "quantity": "100",
      "average_price": "1187.75",
      "ltp": "1195.50",
      "pnl": "775.00",
      "pnl_percent": "0.65"
    }
  ]
}
```

### Funds Response

```json
{
  "mode": "analyze",
  "status": "success",
  "data": {
    "availablecash": "9500000.00",
    "collateral": "250000.00",
    "m2mrealized": "25000.00",
    "m2munrealized": "775.00",
    "utiliseddebits": "500000.00"
  }
}
```

---

## Edge Cases & Validations

### Order Validations

#### 1. Insufficient Funds

```python
# Check before order placement
required_margin = calculate_margin(order)
available_funds = get_available_funds(user_id)

if required_margin > available_funds:
    return {
        'mode': 'analyze',
        'status': 'error',
        'message': f'Insufficient funds. Required: ₹{required_margin}, Available: ₹{available_funds}'
    }
```

#### 2. Invalid Symbol

```python
# Validate symbol exists in database
from services.symbol_service import get_symbol_info

success, response, status_code = get_symbol_info(symbol, exchange)

if not success or status_code != 200:
    return {
        'mode': 'analyze',
        'status': 'error',
        'message': f'Invalid symbol: {symbol} not found in exchange {exchange}'
    }
```

#### 3. Negative Quantity

```python
if quantity <= 0:
    return {
        'mode': 'analyze',
        'status': 'error',
        'message': 'Quantity must be greater than 0'
    }
```

#### 4. Negative Price

```python
if price < 0 or trigger_price < 0:
    return {
        'mode': 'analyze',
        'status': 'error',
        'message': 'Price and trigger price cannot be negative'
    }
```

#### 5. Lot Size Validation (F&O)

```python
if exchange in ['NFO', 'BFO', 'CDS', 'BCD', 'MCX']:
    symbol_info = get_symbol_info(symbol, exchange)
    lot_size = symbol_info['data']['lotsize']

    if quantity % lot_size != 0:
        return {
            'mode': 'analyze',
            'status': 'error',
            'message': f'Quantity must be in multiples of lot size {lot_size}'
        }
```

### Position Edge Cases

#### 1. Over-Leveraged Position

```python
# Check total leverage exposure
total_exposure = sum(position.margin_used for position in positions)
max_allowed = available_cash * max_leverage_multiplier

if total_exposure > max_allowed:
    return {
        'mode': 'analyze',
        'status': 'error',
        'message': 'Maximum leverage limit exceeded'
    }
```

#### 2. Short Selling without Margin

```python
# For short selling, ensure margin is available
if action == 'SELL' and current_position.quantity >= 0:
    # This is a short sell
    required_margin = calculate_short_margin(symbol, quantity)
    if required_margin > available_funds:
        return {
            'mode': 'analyze',
            'status': 'error',
            'message': 'Insufficient margin for short selling'
        }
```

#### 3. Expired Contracts

```python
# Check if F&O contract is expired
from datetime import datetime

if 'FUT' in symbol or 'CE' in symbol or 'PE' in symbol:
    symbol_info = get_symbol_info(symbol, exchange)
    expiry_date = datetime.strptime(symbol_info['expiry'], '%d-%b-%y')

    if datetime.now() > expiry_date:
        return {
            'mode': 'analyze',
            'status': 'error',
            'message': f'Contract expired on {expiry_date.strftime("%d-%b-%Y")}'
        }
```

### Smart Order Edge Cases

#### 1. Position Size = 0

```python
# Close entire position
if position_size == 0:
    current_qty = get_position_quantity(symbol, exchange, product)
    if current_qty != 0:
        # Place reverse order to close
        reverse_action = 'SELL' if current_qty > 0 else 'BUY'
        quantity = abs(current_qty)
```

#### 2. Reducing Position

```python
# Current: Long 100, Target: Long 50
# Action: SELL 50
current_qty = 100
target_qty = 50
difference = current_qty - target_qty  # 50

if difference > 0:
    action = 'SELL'
    quantity = difference
```

#### 3. Reversing Position

```python
# Current: Long 100, Target: Short 50
# Action: SELL 150 (100 to close + 50 to reverse)
current_qty = 100
target_qty = -50
total_qty = abs(current_qty - target_qty)  # 150

action = 'SELL'
quantity = total_qty

# Respect smart order rate limit: 2 per second
# With 0.5 second delay between orders (SMART_ORDER_DELAY)
```

### Fund Management Edge Cases

#### 1. Negative Cash Balance

```python
# Prevent negative cash
if available_cash < 0:
    # Force close positions or reject new orders
    return {
        'mode': 'analyze',
        'status': 'error',
        'message': 'Negative cash balance. Please close some positions.'
    }
```

#### 2. Collateral Utilization

```python
# Check if collateral can cover margin
total_margin_required = calculate_total_margin()
available_cash_with_collateral = available_cash + collateral

if total_margin_required > available_cash_with_collateral:
    return {
        'mode': 'analyze',
        'status': 'error',
        'message': 'Insufficient funds including collateral'
    }
```

---

## Implementation Checklist

### Phase 1: Core Infrastructure
- [ ] Create `sandbox/` folder structure
- [ ] Setup `sandbox.db` database
- [ ] Create database tables (orders, trades, positions, holdings, funds, config)
- [ ] Implement fund initialization (₹1 Crore)
- [ ] Implement Sunday reset mechanism

### Phase 2: Order Management
- [ ] Implement `place_order` for sandbox mode
- [ ] Implement order validation (funds, symbol, quantity, price)
- [ ] Implement market order execution (immediate)
- [ ] Implement limit order execution (pending → complete)
- [ ] Implement SL and SL-M order execution
- [ ] Implement order checker (every 5 seconds)
- [ ] Implement `modify_order` for sandbox
- [ ] Implement `cancel_order` for sandbox
- [ ] Implement `cancel_all_orders` for sandbox

### Phase 3: Position Management
- [ ] Implement position creation/update
- [ ] Implement position P&L calculation
- [ ] Implement MTM updates (on-demand and auto)
- [ ] Implement margin calculation (equity, futures, options)
- [ ] Implement position response (mimic live)

### Phase 4: Holdings Management
- [ ] Implement CNC → Holdings conversion (T+1)
- [ ] Implement holdings P&L calculation
- [ ] Implement collateral calculation
- [ ] Implement holdings response (mimic live)

### Phase 5: Auto Square-Off
- [ ] Implement exchange-wise square-off timings
- [ ] Implement MIS position auto-close
- [ ] Implement EOD pending order cancellation
- [ ] Implement warning notifications (5 min before)

### Phase 6: Market Data Integration
- [ ] Integrate `quotes_service` for LTP
- [ ] Integrate `symbol_service` for lot size/tick size
- [ ] Implement background data updater
- [ ] Implement MTM auto-update (configurable)

### Phase 7: Advanced Orders
- [ ] Implement `place_smart_order` with position sizing
- [ ] Implement `basket_order` (multiple symbols)
- [ ] Implement `split_order` (large quantity split)

### Phase 8: Reporting & Analytics
- [ ] Implement `orderbook` response
- [ ] Implement `tradebook` response
- [ ] Implement `positionbook` response
- [ ] Implement `holdings` response
- [ ] Implement `funds` response
- [ ] Implement order/trade/position statistics

### Phase 9: Configuration UI
- [ ] Create sandbox settings page
- [ ] Implement leverage configuration
- [ ] Implement square-off timing configuration
- [ ] Implement order checker interval configuration
- [ ] Implement MTM update configuration

### Phase 10: Testing & Validation
- [ ] Test all order types (MARKET, LIMIT, SL, SL-M)
- [ ] Test all product types (MIS, CNC, NRML)
- [ ] Test leverage calculations
- [ ] Test margin validations
- [ ] Test auto square-off
- [ ] Test fund reset
- [ ] Test smart orders
- [ ] Test basket and split orders
- [ ] Test edge cases
- [ ] Load testing (multiple concurrent orders)

---

## Success Criteria

### Functional Requirements
✅ All order types execute correctly with live market data
✅ Margin calculations match specified leverage rules
✅ Positions update accurately with MTM
✅ Holdings created after T+1 settlement
✅ Auto square-off triggers at correct times
✅ Funds reset every Sunday at midnight
✅ All API responses mimic live broker format
✅ Sandbox database isolated from live data

### Non-Functional Requirements
✅ Order execution latency < 100ms
✅ Background checker completes cycle in < 5 seconds
✅ Database queries optimized with indexes
✅ Modular, maintainable code structure
✅ Comprehensive error handling
✅ Detailed logging for debugging

---

## Glossary

**Sandbox Mode**: Testing environment with simulated funds and orders
**Analyzer Mode**: Alternative name for Sandbox Mode (interchangeable)
**MIS (Margin Intraday Square-off)**: Intraday product with auto square-off
**CNC (Cash and Carry)**: Delivery-based equity product
**NRML (Normal)**: Carry-forward product for derivatives
**MTM (Mark to Market)**: Current profit/loss based on live prices
**LTP (Last Traded Price)**: Most recent traded price of a security
**T+1 Settlement**: Settlement one day after trade date
**Leverage**: Ability to trade with borrowed funds (margin)
**Collateral**: Holdings used as margin for trading
**Square-Off**: Closing an open position
**EOD (End of Day)**: Market closing time

---

## Support & Troubleshooting

### Common Issues

**Issue 1: Orders not executing**
- Check if order checker is enabled in config
- Verify LTP is crossing limit/trigger price
- Check if sufficient funds available

**Issue 2: Positions not updating MTM**
- Enable auto-update in sandbox settings
- Check if quotes service is returning valid LTP
- Refresh page manually

**Issue 3: Funds not resetting on Sunday**
- Verify system time is correct (IST)
- Check if reset cron job is running
- Manually trigger reset from settings

**Issue 4: Auto square-off not working**
- Verify exchange-wise timings in config
- Check if MIS positions exist
- Review logs for execution errors

---

**Version:** 1.0
**Last Updated:** October 2025
**Status:** Draft - Ready for Implementation

---

*This documentation provides a complete blueprint for building OpenAlgo Sandbox Mode. All specifications are based on real-world broker behavior and industry-standard practices.*
