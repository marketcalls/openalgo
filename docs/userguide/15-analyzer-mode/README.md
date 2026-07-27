# 15 - Analyzer Mode (Sandbox Testing)

## Introduction

Analyzer Mode is OpenAlgo's sandbox testing environment. It lets you test strategies with real market data but sandbox capital (₹1 Crore), ensuring you never risk real money while learning or validating strategies.

## What is Analyzer Mode?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Analyzer Mode                                        │
│                                                                              │
│  REAL                           SIMULATED                                   │
│  ────                           ─────────                                   │
│  • Market prices               • Order execution                            │
│  • Market data                 • Position tracking                          │
│  • Market hours                • P&L calculation                            │
│                                • Account balance                            │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                                                                      │   │
│  │  You get ₹1,00,00,000 (1 Crore) sandbox capital                     │   │
│  │  Trade freely, learn safely                                         │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Why Use Analyzer Mode?

### 1. Learn Without Risk

- New to OpenAlgo? Learn the interface
- New to trading? Understand order flow
- Test features before going live

### 2. Validate Strategies

- Test TradingView alerts
- Verify Amibroker integration
- Debug Python strategies

### 3. Practice Order Types

- Understand market vs limit orders
- Test stop-loss execution
- Try smart orders and baskets

### 4. Compliance Testing

- Verify strategy behavior
- Document trading logic
- Train team members

## Enabling Analyzer Mode

### Method 1: Web Interface

1. Login to OpenAlgo
2. Navigate to **Analyzer** page
3. Click **Enable Analyzer Mode**
4. Confirm the action

### Method 2: Keyboard Shortcut

Press `Ctrl + Shift + A` (when available)

### Visual Indicator

When Analyzer Mode is ON, you'll see:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ⚠️ ANALYZER MODE ACTIVE                                                    │
│                                                                              │
│  All orders are simulated. No real trades will be executed.                │
│  Sandbox Balance: ₹1,00,00,000                                             │
│                                                                              │
│  Theme changes to PURPLE to remind you                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Analyzer Mode Features

### Sandbox Account

| Feature | Value |
|---------|-------|
| Starting Capital | ₹1,00,00,000 |
| Margin Available | Based on product type |
| Reset Option | Reset to starting capital |

### Realistic Simulation

| Aspect | How It Works |
|--------|--------------|
| Prices | Real market prices |
| Execution | Instant for market orders |
| Slippage | Minimal (idealized) |
| Margin | Realistic requirements |
| Auto Square-off | At exchange timings |

### Separate Database

- Analyzer data is isolated
- Real trading data unaffected
- Can run side-by-side

## Using Analyzer Mode

### Placing Orders

Orders work exactly the same as live trading:

```json
{
  "apikey": "your-api-key",
  "strategy": "TestStrategy",
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": "100",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

The only difference: Orders go to sandbox, not your broker.

### Viewing Positions

Analyzer positions appear in a separate view:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Sandbox Positions                                 [Sandbox Mode Active]    │
├─────────────────────────────────────────────────────────────────────────────┤
│  Symbol  │ Qty   │ Avg Price │  LTP   │   P&L   │ Product                  │
│──────────│───────│───────────│────────│─────────│──────────────────────────│
│  SBIN    │ +100  │ ₹625.00   │ ₹630.00│ +₹500   │ MIS                      │
│  NIFTY   │ +50   │ ₹21500    │ ₹21550 │ +₹2500  │ NRML                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Checking P&L

View sandbox P&L on the Sandbox P&L page:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Sandbox P&L                                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Starting Capital:     ₹1,00,00,000                                        │
│  Current Value:        ₹1,02,50,000                                        │
│  Total P&L:            +₹2,50,000 (+2.5%)                                  │
│                                                                              │
│  Today's P&L:          +₹15,000                                            │
│  Realized:             +₹10,000                                            │
│  Unrealized:           +₹5,000                                             │
│                                                                              │
│  Total Trades:         45                                                   │
│  Winning Trades:       28 (62%)                                            │
│  Losing Trades:        17 (38%)                                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Testing TradingView Integration

### Step 1: Enable Analyzer Mode

Turn on Analyzer Mode in OpenAlgo.

### Step 2: Configure TradingView Alert

Use your regular webhook URL - same as production.

### Step 3: Trigger Alert

When alert triggers:
- Order appears in Sandbox Order Book
- Position created in Sandbox Positions
- No real money touched

### Step 4: Verify Execution

Check:
- Order received correctly
- Symbol mapped properly
- Quantity and action correct

## Testing Python Strategies

```python
from openalgo import api

# Connect (same as production)
client = api(api_key="your-key", host="http://127.0.0.1:5000")

# When Analyzer Mode is ON, this goes to sandbox
response = client.place_order(
    symbol="SBIN",
    exchange="NSE",
    action="BUY",
    quantity=100,
    price_type="MARKET",
    product="MIS",
    strategy="TestStrategy"
)

# Check sandbox positions
positions = client.get_positions()
print(positions)
```

## Margin System

Analyzer Mode simulates realistic margins:

### Equity (MIS)

| Segment | Margin |
|---------|--------|
| Large Cap | 5× leverage |
| Mid Cap | 4× leverage |
| Small Cap | 3× leverage |

### F&O (NRML)

| Product | Margin |
|---------|--------|
| Futures | SPAN + Exposure |
| Options Buy | Premium |
| Options Sell | SPAN margin |

### Example

```
Available: ₹1,00,00,000
Buy NIFTY Future: Requires ~₹1,50,000 margin
Remaining: ₹98,50,000
```

## Auto Square-Off

Sandbox simulates auto square-off:

| Segment | Time |
|---------|------|
| Equity MIS | 3:15 PM |
| F&O MIS | 3:25 PM |

Positions are marked closed at these times.

## Resetting Sandbox Account

If you want to start fresh:

1. Go to **Analyzer** page
2. Click **Reset Sandbox Account**
3. Confirm action
4. Capital restored to ₹1 Crore
5. All positions and history cleared

## Best Practices

### Before Going Live

1. ✅ Test all order types (market, limit, SL)
2. ✅ Verify webhook integration
3. ✅ Test smart orders
4. ✅ Verify position tracking
5. ✅ Check P&L calculations
6. ✅ Test error scenarios

### Strategy Validation

1. Run strategy for minimum 1 week in sandbox
2. Compare sandbox results with backtest
3. Check for execution issues
4. Monitor for unexpected behavior
5. Document any differences

### Transitioning to Live

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Sandbox to Live Checklist                                │
│                                                                              │
│  □ Strategy tested for sufficient time                                      │
│  □ Results match expectations                                               │
│  □ All integrations verified                                                │
│  □ Error handling tested                                                    │
│  □ Risk parameters set                                                      │
│  □ Start with small quantities                                              │
│  □ Monitor first few live trades closely                                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Disabling Analyzer Mode

When ready for live trading:

1. Go to **Analyzer** page
2. Click **Disable Analyzer Mode**
3. Confirm you understand orders will be real
4. Theme returns to normal

**Warning**: After disabling, ALL orders go to your real broker!

## Capabilities

What Analyzer Mode **CAN** do:

| Capability | Description |
|------------|-------------|
| Real market prices | Uses live market data for realistic pricing |
| Full order flow | BUY, SELL, market orders, limit orders work |
| Position tracking | Tracks open/closed positions accurately |
| P&L calculation | Real-time profit/loss based on market prices |
| Margin simulation | Realistic margin requirements enforced |
| Auto square-off | Simulates exchange timings |
| Multiple strategies | Test multiple strategies simultaneously |
| Webhook testing | TradingView, ChartInk, Amibroker webhooks work |
| API testing | Full API functionality in sandbox |
| Smart orders | Position-aware orders work correctly |
| Basket orders | Multi-symbol orders supported |

## Limitations

What Analyzer Mode **CANNOT** do:

| Limitation | Description |
|------------|-------------|
| Market depth | Order book depth not simulated |
| Slippage | Minimal; real trading may have higher slippage |
| Partial fills | All orders fill completely (no partial fills) |
| Order rejection | Limited rejection scenarios simulated |
| Corporate actions | Dividends, splits, bonuses not applied |
| Auction prices | Opening/closing auction not simulated |
| Circuit limits | Price circuit breakers not enforced |
| Broker-specific rules | Broker margin/position limits not exact |
| Real broker connectivity | No actual broker API calls made |

### Key Differences from Live Trading

1. **Execution**: Sandbox orders execute instantly at market price; real orders may take time and have slippage
2. **Liquidity**: Sandbox assumes unlimited liquidity; real markets may not fill large orders
3. **Timing**: Sandbox doesn't simulate network latency or broker delays
4. **Rejection**: Real brokers may reject orders for various reasons not simulated

## Analyzer Mode Logs

View sandbox-specific logs:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Analyzer Logs                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  10:30:15 │ BUY  │ SBIN    │ 100 │ ₹625.00 │ Executed                      │
│  10:45:22 │ BUY  │ INFY    │ 50  │ ₹1500   │ Executed                      │
│  11:00:05 │ SELL │ SBIN    │ 100 │ ₹630.00 │ Executed │ P&L: +₹500        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

**Previous**: [14 - Positions & Holdings](../14-positions-holdings/README.md)

**Next**: [16 - TradingView Integration](../16-tradingview-integration/README.md)
