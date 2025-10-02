# Position Management in Sandbox Mode

## Overview

The sandbox position management system tracks open and closed positions, calculates real-time P&L with intraday accumulation, and handles position netting logic realistically.

## Key Features

1. **Real-time Position Tracking**: Live quantity and average price updates
2. **Intraday P&L Accumulation**: Tracks total P&L across multiple trades on same symbol
3. **Position Netting**: Proper addition, reduction, and reversal logic
4. **MTM Updates**: Live price updates every 5 seconds (configurable)
5. **Margin Management**: Dynamic margin blocking and release
6. **Holdings Support**: T+1 settlement for CNC positions

## Position States

### Open Position (quantity != 0)
- Has active long (+) or short (-) quantity
- Shows unrealized P&L based on current LTP
- Margin is blocked
- MTM updated every 5 seconds

### Closed Position (quantity = 0)
- Position was closed during the day
- Shows accumulated realized P&L
- No margin blocked
- MTM updates skipped (P&L is final)

## Intraday P&L Accumulation

**New in v1.1.0**: Positions now track accumulated P&L across multiple trades.

### Example Scenario

```python
# Morning: Trade 1
BUY 100 RELIANCE @ 2890
SELL 100 RELIANCE @ 2895
→ Realized P&L: ₹500
→ Position: qty=0, accumulated_realized_pnl=₹500

# Afternoon: Trade 2
BUY 100 RELIANCE @ 2900
SELL 100 RELIANCE @ 2898
→ Realized P&L: -₹200
→ Position: qty=0, accumulated_realized_pnl=₹300

# Position Display shows: P&L = ₹300 (total for the day)
```

**Database**: `accumulated_realized_pnl` column in `sandbox_positions` table

**Implementation**: `sandbox/execution_engine.py` (lines 358-365)

## P&L Calculations

### Unrealized P&L (Open Positions)

```python
# Long Position
pnl = (LTP - Average Price) × Quantity

# Short Position
pnl = (Average Price - LTP) × |Quantity|
```

### Realized P&L (Closed Quantity)

```python
# Long Position Closed
pnl = (Sell Price - Buy Price) × Quantity

# Short Position Closed
pnl = (Sell Price - Buy Price) × Quantity
```

### Display P&L

```python
# For Open Positions:
display_pnl = accumulated_realized_pnl + current_unrealized_pnl

# For Closed Positions:
display_pnl = accumulated_realized_pnl
```

## Position Netting Logic

**File**: `sandbox/execution_engine.py` (lines 262-428)

### Case 1: New Position

```python
# No existing position
BUY 100 @ 2890
→ Position: +100 @ 2890
```

### Case 2: Adding to Position (Same Direction)

```python
# Existing: +100 @ 2890
BUY 50 @ 2900
→ Total Value: (100×2890) + (50×2900) = 434,000
→ Total Qty: 150
→ New Avg: 434,000 ÷ 150 = 2893.33
→ Position: +150 @ 2893.33
```

### Case 3: Reducing Position (Opposite Direction)

```python
# Existing: +100 @ 2890
SELL 40 @ 2900
→ Realized P&L: (2900-2890) × 40 = ₹400
→ Position: +60 @ 2890 (avg unchanged)
→ Margin released for 40 shares
```

### Case 4: Closing Position

```python
# Existing: +100 @ 2890
SELL 100 @ 2900
→ Realized P&L: (2900-2890) × 100 = ₹1,000
→ Position: qty=0, accumulated_pnl=₹1,000
→ Full margin released
```

### Case 5: Reversing Position

```python
# Existing: +100 @ 2890
SELL 150 @ 2900
→ Realized P&L: (2900-2890) × 100 = ₹1,000 (for closed 100)
→ New Position: -50 @ 2900 (reversed to short)
→ Margin: Released for 100, blocked for 50 short
```

### Case 6: Reopening Closed Position

```python
# Previous: qty=0, accumulated_pnl=₹1,000
BUY 50 @ 2910
→ Position: +50 @ 2910
→ Unrealized P&L: 0 (new position)
→ Accumulated P&L: ₹1,000 (preserved)
→ Display P&L: ₹1,000 (accumulated only)
```

## Get Positions API

### Request

```python
import requests

payload = {"apikey": "your_api_key"}
response = requests.post(
    "http://127.0.0.1:5000/api/v1/positionbook",
    json=payload
)
```

### Response

```json
{
    "status": "success",
    "data": [
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 100,
            "average_price": 2890.50,
            "ltp": 2895.75,
            "pnl": 525.00,
            "pnl_percent": 0.1816
        },
        {
            "symbol": "SBIN",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 0,
            "average_price": 590.00,
            "ltp": 595.00,
            "pnl": 300.00,
            "pnl_percent": 0.0000
        }
    ],
    "mode": "analyze"
}
```

**Note**: Closed positions (qty=0) show accumulated realized P&L.

## Close Position API

### Close Specific Position

```python
payload = {
    "apikey": "your_api_key",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "product": "MIS"
}

response = requests.post(
    "http://127.0.0.1:5000/api/v1/closeposition",
    json=payload
)
```

### Close All Positions

```python
# Omit symbol/exchange to close all
payload = {"apikey": "your_api_key"}

response = requests.post(
    "http://127.0.0.1:5000/api/v1/closeposition",
    json=payload
)
```

### Closure Logic

**File**: `sandbox/position_manager.py` (lines 334-387)

1. Check if position exists and quantity != 0
2. Determine reverse action (BUY for short, SELL for long)
3. Create MARKET order with reverse action
4. Execute immediately (market order)
5. Update position to qty=0
6. Calculate and add realized P&L to accumulated P&L

## Holdings (CNC Product)

### T+1 Settlement Process

**File**: `sandbox/position_manager.py` (lines 463-558, 584-674)

CNC positions automatically convert to holdings at midnight (00:00 IST):

```python
# Day 1 (10:00 AM): BUY 50 TCS in CNC
→ Creates position in sandbox_positions

# Day 1 (00:00 Midnight): Settlement scheduler runs
→ Moves position to sandbox_holdings
→ Clears position quantity to 0
→ Preserves realized P&L

# Settlement runs as APScheduler background task
# File: sandbox/squareoff_thread.py (lines 99-122)
```

### Catch-up Settlement (Missed Settlements)

**File**: `sandbox/position_manager.py` (lines 622-674)

When the app is stopped (e.g., for maintenance or system downtime), the midnight settlement job won't run. To handle this, a catch-up settlement mechanism automatically runs:

**Trigger Points**:
1. **App Startup**: When app starts with analyzer mode already enabled (app.py:347-353)
2. **Mode Toggle**: When user enables analyzer mode (analyzer_service.py:107-113)

**Logic**:
```python
# Example: User placed CNC order on Day 1, stopped app, restarted on Day 5

def catchup_missed_settlements():
    """Settle CNC positions that should have been settled while app was stopped"""

    # Find all CNC positions older than 1 day
    cutoff_time = datetime.now() - timedelta(days=1)

    old_positions = [
        p for p in SandboxPositions.query.filter_by(product='CNC').all()
        if p.quantity != 0 and p.created_at < cutoff_time
    ]

    # Automatically settle them to holdings
    for position in old_positions:
        process_session_settlement(position)

    # Result: Old CNC positions appear in /holdings, not /positions
```

**Use Case Example**:

| Timeline | Event | Result |
|----------|-------|--------|
| **Day 1, 10:00 AM** | BUY 100 RELIANCE CNC @ 2500 | Position created |
| **Day 1, 11:00 PM** | User stops app & logs out | App offline |
| **Day 2-5** | App remains stopped | Midnight settlement doesn't run |
| **Day 6, 9:00 AM** | User restarts app | Catch-up settlement runs |
| **Day 6, 9:00 AM** | Catch-up detects 5-day-old CNC position | Automatically settles to holdings |
| **Day 6, 9:01 AM** | User views /holdings | Position shows in holdings ✓ |

This ensures **holdings are always accurate** even after extended downtime.

### Get Holdings API

```python
payload = {"apikey": "your_api_key"}
response = requests.post(
    "http://127.0.0.1:5000/api/v1/holdings",
    json=payload
)
```

### Holdings Response

```json
{
    "status": "success",
    "data": {
        "holdings": [
            {
                "symbol": "TCS",
                "exchange": "NSE",
                "quantity": 50,
                "average_price": 3480.00,
                "ltp": 3520.00,
                "pnl": 2000.00,
                "pnl_percent": 1.1494,
                "current_value": 176000.00,
                "settlement_date": "2025-10-01"
            }
        ],
        "statistics": {
            "totalholdingvalue": 176000.00,
            "totalinvvalue": 174000.00,
            "totalprofitandloss": 2000.00,
            "totalpnlpercentage": 1.1494
        }
    },
    "mode": "analyze"
}
```

## Summary

Position management in sandbox mode provides:

- **Accurate Tracking**: Real-time quantity, average price, and LTP
- **Intraday P&L**: Accumulated across multiple trades on same symbol
- **Realistic Netting**: Proper addition, reduction, and reversal logic
- **Live MTM**: Updates every 5 seconds using broker API quotes
- **Margin Integration**: Dynamic blocking and release based on position changes
- **Holdings Support**: T+1 settlement for long-term CNC positions

---

**Previous**: [Margin System](04_margin_system.md) | **Next**: [Auto Square-Off](06_auto_squareoff.md)
