# 12 - Smart Orders

## Introduction

Smart Orders are position-aware orders that automatically calculate the correct action based on your current holdings. Instead of manually figuring out what to do, you tell OpenAlgo your target position, and it handles the rest.

## The Problem Smart Orders Solve

### Without Smart Orders

```
Current Position: 100 SBIN LONG
Your Strategy: "Go SHORT 100 shares"

Manual Calculation Required:
1. Sell 100 to close LONG
2. Sell 100 more to go SHORT
3. Total: SELL 200 shares

You must track position and calculate!
```

### With Smart Orders

```
Current Position: 100 SBIN LONG
Smart Order: "position_size = -100" (SHORT 100)

OpenAlgo Automatically:
1. Checks current position (100 LONG)
2. Calculates required action (SELL 200)
3. Executes single order

No manual calculation needed!
```

## How Smart Orders Work

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Smart Order Logic                                       │
│                                                                              │
│  Input: Target Position Size                                                │
│         +100 = Long 100 shares                                              │
│         -100 = Short 100 shares                                             │
│            0 = Flat (no position)                                           │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                                                                      │   │
│  │  Current Position    Target Position    Action                      │   │
│  │  ────────────────    ───────────────    ──────                      │   │
│  │       +100              +100            No action (already there)   │   │
│  │       +100              +200            BUY 100                     │   │
│  │       +100                 0            SELL 100                    │   │
│  │       +100              -100            SELL 200                    │   │
│  │       -100              +100            BUY 200                     │   │
│  │       -100                 0            BUY 100 (cover)             │   │
│  │         0               +100            BUY 100                     │   │
│  │         0               -100            SELL 100 (short)            │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Smart Order API

### Basic Request

```json
{
  "apikey": "your-api-key",
  "strategy": "MyStrategy",
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": "100",
  "position_size": "100",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

### Key Parameters

| Parameter | Description |
|-----------|-------------|
| action | BUY or SELL (direction hint) |
| quantity | Order quantity |
| position_size | Target position after execution |

### Position Size Values

| Value | Meaning |
|-------|---------|
| Positive | Long position (e.g., +100 = long 100) |
| Negative | Short position (e.g., -100 = short 100) |
| Zero | Flat (close all positions) |

## Real-World Examples

### Example 1: Going Long from Flat

```
Before: No position (0)
Smart Order: position_size = 100, action = BUY

Calculation:
  Target: +100
  Current: 0
  Difference: 100 - 0 = +100
  Action: BUY 100

Result: Now LONG 100 shares
```

### Example 2: Reversing Position

```
Before: LONG 100 shares (+100)
Smart Order: position_size = -100, action = SELL

Calculation:
  Target: -100
  Current: +100
  Difference: -100 - (+100) = -200
  Action: SELL 200

Result: Now SHORT 100 shares
```

### Example 3: Partial Exit

```
Before: LONG 200 shares (+200)
Smart Order: position_size = 50, action = SELL

Calculation:
  Target: +50
  Current: +200
  Difference: 50 - 200 = -150
  Action: SELL 150

Result: Now LONG 50 shares
```

### Example 4: Square Off (Close Position)

```
Before: SHORT 100 shares (-100)
Smart Order: position_size = 0, action = BUY

Calculation:
  Target: 0
  Current: -100
  Difference: 0 - (-100) = +100
  Action: BUY 100 (cover)

Result: Flat (no position)
```

## Smart Order Endpoint

### API Call

```
POST /api/v1/smartorder
Content-Type: application/json

{
  "apikey": "your-api-key",
  "strategy": "Reversal_System",
  "symbol": "NIFTY25JANFUT",
  "exchange": "NFO",
  "action": "SELL",
  "quantity": "50",
  "position_size": "-50",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

### Response

```json
{
  "status": "success",
  "orderid": "230125000012345",
  "action_taken": "SELL",
  "quantity_executed": "100"
}
```

## Python Example

```python
from openalgo import api

client = api(api_key="your-key", host="http://127.0.0.1:5000")

# Simple reversal system
def execute_signal(symbol, signal):
    """
    signal: 'LONG', 'SHORT', or 'FLAT'
    """

    if signal == 'LONG':
        position_size = 100
        action = 'BUY'
    elif signal == 'SHORT':
        position_size = -100
        action = 'SELL'
    else:  # FLAT
        position_size = 0
        action = 'SELL'  # Direction doesn't matter for flat

    response = client.place_smart_order(
        symbol=symbol,
        exchange='NSE',
        action=action,
        quantity=100,
        position_size=position_size,
        price_type='MARKET',
        product='MIS',
        strategy='SmartSystem'
    )

    return response

# Usage
execute_signal('SBIN', 'LONG')   # Goes long 100
execute_signal('SBIN', 'SHORT')  # Reverses to short 100
execute_signal('SBIN', 'FLAT')   # Closes position
```

## TradingView Integration

### Alert Message for Smart Order

```json
{
  "apikey": "your-api-key",
  "strategy": "TV_Smart",
  "symbol": "{{ticker}}",
  "exchange": "NSE",
  "action": "{{strategy.order.action}}",
  "quantity": "100",
  "position_size": "{{strategy.position_size}}",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

### Pine Script Example

```pine
//@version=5
strategy("Smart Order Example", overlay=true)

// Your strategy logic
longCondition = ta.crossover(ta.sma(close, 14), ta.sma(close, 28))
shortCondition = ta.crossunder(ta.sma(close, 14), ta.sma(close, 28))

// Enter positions
if (longCondition)
    strategy.entry("Long", strategy.long, qty=100)

if (shortCondition)
    strategy.entry("Short", strategy.short, qty=100)
```

## Smart Order vs Regular Order

| Aspect | Regular Order | Smart Order |
|--------|---------------|-------------|
| Position awareness | No | Yes |
| Manual calculation | Required | Automatic |
| Reversal handling | Multiple orders | Single order |
| Best for | Simple orders | Strategy systems |
| Complexity | Simple | Slightly complex |

## Use Cases

### 1. Trend Following Systems

```
Signal: LONG → position_size = +100
Signal: SHORT → position_size = -100
Signal: EXIT → position_size = 0
```

### 2. Mean Reversion

```
Oversold → position_size = +100
Overbought → position_size = -100
Normal → position_size = 0
```

### 3. Scaling In/Out

```
Initial entry → position_size = 100
Add to position → position_size = 200
Partial exit → position_size = 100
Full exit → position_size = 0
```

## Important Considerations

### 1. Strategy Name Matters

Position tracking is per strategy. Different strategies are tracked separately:

```
Strategy "A": position = +100
Strategy "B": position = -50

Smart order for Strategy "A" only considers "A"'s position
```

### 2. Product Type Consistency

Keep product type consistent within a strategy:
- Don't mix MIS and NRML in same strategy
- Position tracking may be affected

### 3. Symbol Matching

Ensure exact symbol match:
- "SBIN" and "SBIN-EQ" are different
- "NIFTY25JANFUT" is specific to that expiry

## Troubleshooting

### Issue: "Position not found"

**Cause**: No existing position for the symbol/strategy
**Solution**: This is normal for first order; it will create position

### Issue: "Unexpected quantity executed"

**Cause**: Existing position wasn't what you expected
**Solution**: Check current positions before sending smart order

### Issue: "Order not executed"

**Cause**: Already at target position
**Solution**: This is correct behavior - no action needed

---

**Previous**: [11 - Order Types Explained](../11-order-types/README.md)

**Next**: [13 - Basket Orders](../13-basket-orders/README.md)
