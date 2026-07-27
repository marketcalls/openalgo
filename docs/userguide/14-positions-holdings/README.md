# 14 - Positions & Holdings

## Introduction

Understanding the difference between positions and holdings is fundamental to trading. This guide explains both concepts and how to manage them in OpenAlgo.

## Positions vs Holdings

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                   Positions vs Holdings                                      │
│                                                                              │
│  POSITIONS                              HOLDINGS                            │
│  ──────────                             ────────                            │
│                                                                              │
│  • Intraday trades (MIS)               • Delivery trades (CNC)              │
│  • F&O positions (NRML)                • Stocks in your demat               │
│  • Active today                        • Long-term investments              │
│  • Must close or convert               • No expiry (equity)                 │
│  • Mark-to-market P&L                  • Dividend eligible                  │
│                                                                              │
│  Example:                               Example:                            │
│  Bought SBIN MIS today                 Bought SBIN CNC last month           │
│  → Shows in Positions                  → Shows in Holdings                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Understanding Positions

### What is a Position?

A position is an open trade that hasn't been closed yet:
- Intraday equity trades (MIS product)
- Futures and Options trades (NRML product)
- Any trade that's "open" for the day

### Position Data Fields

| Field | Description |
|-------|-------------|
| Symbol | Trading symbol (e.g., SBIN) |
| Exchange | NSE, NFO, MCX, etc. |
| Product | MIS, NRML |
| Quantity | Number of shares/lots (+ for long, - for short) |
| Average Price | Your entry price |
| LTP | Last Traded Price |
| P&L | Unrealized profit/loss |
| Day's Change | Change since market open |

### Position Example

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Your Positions                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  Symbol  │ Qty   │ Avg Price │  LTP   │   P&L   │ Product │ Exchange       │
│──────────│───────│───────────│────────│─────────│─────────│────────────────│
│  SBIN    │ +100  │ ₹625.00   │ ₹630.00│ +₹500   │ MIS     │ NSE            │
│  RELIANCE│ -50   │ ₹2450.00  │ ₹2440  │ +₹500   │ MIS     │ NSE            │
│  NIFTY   │ +50   │ ₹150.00   │ ₹165.00│ +₹750   │ NRML    │ NFO            │
└─────────────────────────────────────────────────────────────────────────────┘

Total Unrealized P&L: +₹1,750
```

### Reading Position Quantity

| Quantity | Meaning |
|----------|---------|
| +100 | Long 100 shares (bought) |
| -100 | Short 100 shares (sold) |
| 0 | No position (flat) |

## Understanding Holdings

### What are Holdings?

Holdings are stocks you own in your demat account:
- Purchased using CNC (delivery) product
- Settled after T+1 day
- No expiry
- Eligible for dividends and corporate actions

### Holdings Data Fields

| Field | Description |
|-------|-------------|
| Symbol | Stock symbol |
| Quantity | Number of shares owned |
| Average Price | Your average cost |
| LTP | Current market price |
| Current Value | Qty × LTP |
| P&L | Total profit/loss |
| P&L % | Percentage return |

### Holdings Example

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Your Holdings                                        Total: ₹5,25,000      │
├─────────────────────────────────────────────────────────────────────────────┤
│  Symbol  │ Qty  │ Avg Price │  LTP    │ Value    │  P&L    │ P&L %         │
│──────────│──────│───────────│─────────│──────────│─────────│───────────────│
│  HDFC    │ 100  │ ₹1500     │ ₹1650   │ ₹1,65,000│+₹15,000 │ +10.0%        │
│  ICICI   │ 200  │ ₹950      │ ₹1020   │ ₹2,04,000│+₹14,000 │ +7.4%         │
│  INFY    │ 50   │ ₹1400     │ ₹1560   │ ₹78,000  │+₹8,000  │ +11.4%        │
│  TCS     │ 25   │ ₹3200     │ ₹3120   │ ₹78,000  │-₹2,000  │ -2.5%         │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Viewing in OpenAlgo

### Positions Page

Navigate to **Positions** in sidebar:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Positions                                        [Refresh] [Close All]    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Filters: [All Products ▾]  [All Exchanges ▾]                               │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  SBIN    NSE    +100    MIS                                        │    │
│  │  Avg: ₹625.00    LTP: ₹630.00    P&L: +₹500        [Exit]         │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  Total P&L: +₹1,750                                                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Holdings Page

Navigate to **Holdings** in sidebar:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Holdings                                         [Refresh] [Download]     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Portfolio Value: ₹5,25,000                                                 │
│  Total Investment: ₹4,75,000                                                │
│  Total P&L: +₹50,000 (+10.5%)                                              │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  HDFC Bank                                                         │    │
│  │  100 shares @ ₹1500 avg                                           │    │
│  │  Current: ₹1,65,000    P&L: +₹15,000 (+10%)        [Sell]         │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Position Operations

### Closing a Position

**Method 1: UI Button**
1. Go to Positions page
2. Find the position
3. Click **Exit** button
4. Order placed at market price

**Method 2: API**
```json
{
  "apikey": "your-key",
  "strategy": "ManualExit",
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "SELL",
  "quantity": "100",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

### Closing All Positions

**Method 1: UI**
1. Go to Positions page
2. Click **Close All** button
3. Confirm action
4. All positions squared off

**Method 2: API**
```
POST /api/v1/closeallpositions
{
  "apikey": "your-key",
  "strategy": "SquareOff"
}
```

### Modifying Position Size

```python
# Increase position
client.place_order(
    symbol="SBIN",
    action="BUY",
    quantity=50,  # Add 50 more
    ...
)

# Decrease position
client.place_order(
    symbol="SBIN",
    action="SELL",
    quantity=30,  # Reduce by 30
    ...
)
```

## API Endpoints

### Get Positions

```
POST /api/v1/positions
{
  "apikey": "your-key"
}
```

**Response:**
```json
{
  "status": "success",
  "data": [
    {
      "symbol": "SBIN",
      "exchange": "NSE",
      "product": "MIS",
      "quantity": 100,
      "average_price": 625.00,
      "ltp": 630.00,
      "pnl": 500.00
    }
  ]
}
```

### Get Holdings

```
POST /api/v1/holdings
{
  "apikey": "your-key"
}
```

**Response:**
```json
{
  "status": "success",
  "data": [
    {
      "symbol": "HDFC",
      "exchange": "NSE",
      "quantity": 100,
      "average_price": 1500.00,
      "ltp": 1650.00,
      "pnl": 15000.00,
      "pnl_percent": 10.0
    }
  ]
}
```

### Get Open Position (Specific)

```
POST /api/v1/openposition
{
  "apikey": "your-key",
  "strategy": "MyStrategy",
  "symbol": "SBIN",
  "exchange": "NSE",
  "product": "MIS"
}
```

## P&L Calculations

### Position P&L (Unrealized)

```
For LONG positions:
P&L = (LTP - Average Price) × Quantity

For SHORT positions:
P&L = (Average Price - LTP) × Quantity

Example (Long 100 SBIN):
Average: ₹625, LTP: ₹630
P&L = (630 - 625) × 100 = +₹500
```

### Holdings P&L

```
P&L = (Current Price - Average Cost) × Quantity

P&L % = ((Current Price - Average Cost) / Average Cost) × 100

Example (100 HDFC):
Average: ₹1500, Current: ₹1650
P&L = (1650 - 1500) × 100 = +₹15,000
P&L % = ((1650 - 1500) / 1500) × 100 = +10%
```

## Auto Square-Off (MIS)

MIS positions are automatically squared off:

| Segment | Auto Square-Off Time |
|---------|---------------------|
| Equity | 3:15 PM |
| F&O | 3:25 PM |
| Currency | 4:55 PM |
| Commodity | 11:30 PM |

**Tip**: Close positions yourself before auto square-off for better prices.

## Converting Positions

### MIS to NRML/CNC

Convert intraday to overnight:
- Must be done before square-off time
- Additional margin required
- Check broker-specific rules

### Product Conversion API

```
POST /api/v1/convertposition
{
  "apikey": "your-key",
  "symbol": "SBIN",
  "exchange": "NSE",
  "quantity": "100",
  "from_product": "MIS",
  "to_product": "CNC"
}
```

## Best Practices

### Position Management

1. **Set stop-losses** for all positions
2. **Monitor margin** to avoid forced liquidation
3. **Close before auto square-off** when possible
4. **Review positions** at start and end of day

### Holdings Management

1. **Diversify** across sectors
2. **Review periodically** (quarterly)
3. **Rebalance** when needed
4. **Track corporate actions** (dividends, splits)

---

**Previous**: [13 - Basket Orders](../13-basket-orders/README.md)

**Next**: [15 - Analyzer Mode (Sandbox Testing)](../15-analyzer-mode/README.md)
