# 11 - Order Types Explained

## Introduction

Understanding order types is essential for effective trading. Each order type has specific use cases, advantages, and limitations.

## Order Types Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Order Types Hierarchy                               │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        MARKET ORDER                                  │   │
│  │           Execute immediately at best available price                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        LIMIT ORDER                                   │   │
│  │           Execute only at specified price or better                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      STOP-LOSS ORDER (SL)                           │   │
│  │       Triggers limit order when price reaches stop price            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                   STOP-LOSS MARKET ORDER (SL-M)                     │   │
│  │       Triggers market order when price reaches stop price           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Market Order (MARKET)

### What It Does

Executes immediately at the current best available price.

### Example

```
Stock: SBIN
Current Price: ₹625.50
You place: MARKET BUY 100 shares

Result: You get 100 shares at approximately ₹625.50
(Actual price may vary slightly based on market)
```

### When to Use

| Use When | Don't Use When |
|----------|----------------|
| Need immediate execution | Price precision matters |
| Trading liquid stocks | Stock is thinly traded |
| News-based trading | Large order size |
| Exiting positions quickly | Volatile market conditions |

### Pros and Cons

| Pros | Cons |
|------|------|
| Guaranteed execution | No price control |
| Simple to use | May get worse price |
| Fast | Slippage in volatile markets |

### OpenAlgo API

```json
{
  "apikey": "your-key",
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": "100",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

## Limit Order (LIMIT)

### What It Does

Executes only at your specified price or better.
- BUY LIMIT: Executes at your price or lower
- SELL LIMIT: Executes at your price or higher

### Example

```
Stock: SBIN
Current Price: ₹625
You place: LIMIT BUY 100 at ₹620

Scenario 1: Price drops to ₹620
Result: Order executes at ₹620 ✓

Scenario 2: Price stays above ₹620
Result: Order remains pending

Scenario 3: Price drops to ₹615
Result: Order executes at ₹620 (or better at ₹615)
```

### When to Use

| Use When | Don't Use When |
|----------|----------------|
| Want specific price | Need immediate execution |
| Buying dips | Fast-moving markets |
| Selling rallies | May miss opportunity |
| Large orders | News-based trading |

### Pros and Cons

| Pros | Cons |
|------|------|
| Price control | May not execute |
| No slippage | Order may expire |
| Better average price | Requires price monitoring |

### OpenAlgo API

```json
{
  "apikey": "your-key",
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": "100",
  "pricetype": "LIMIT",
  "price": "620",
  "product": "MIS"
}
```

## Stop-Loss Order (SL)

### What It Does

Combines a trigger price and a limit price:
1. Order stays dormant until trigger price is reached
2. Once triggered, becomes a limit order

### Example

```
You own: SBIN at ₹625
Current Price: ₹625
You place: SL SELL at Trigger ₹615, Limit ₹614

Price Movement:
₹625 → ₹620 → ₹617 → ₹615 (TRIGGERED!)
                       ↓
           Limit sell order at ₹614 placed
                       ↓
           Executes at ₹614 or better
```

### When to Use

| Use When | Risk |
|----------|------|
| Protecting profits | May not execute if price gaps |
| Limiting losses | Requires two prices |
| Position management | Can be triggered by volatility |

### Trigger vs Limit Price

```
BUY Stop-Loss (for short positions):
  Trigger Price: Price that activates the order (higher)
  Limit Price: Maximum price you'll pay (equal or higher)

SELL Stop-Loss (for long positions):
  Trigger Price: Price that activates the order (lower)
  Limit Price: Minimum price you'll accept (equal or lower)
```

### OpenAlgo API

```json
{
  "apikey": "your-key",
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "SELL",
  "quantity": "100",
  "pricetype": "SL",
  "price": "614",
  "trigger_price": "615",
  "product": "MIS"
}
```

## Stop-Loss Market Order (SL-M)

### What It Does

Triggers a market order when trigger price is reached:
1. Order stays dormant until trigger price hit
2. Once triggered, becomes a market order (guaranteed execution)

### Example

```
You own: SBIN at ₹625
Current Price: ₹625
You place: SL-M SELL at Trigger ₹615

Price Movement:
₹625 → ₹620 → ₹617 → ₹615 (TRIGGERED!)
                       ↓
           Market sell order placed
                       ↓
           Executes immediately at market price
           (Could be ₹614, ₹613, or ₹616)
```

### When to Use

| Use When | Risk |
|----------|------|
| Must exit no matter what | Slippage in volatile markets |
| Gap down protection | May get worse price |
| Simpler than SL | No price control after trigger |

### SL vs SL-M Comparison

| Aspect | SL | SL-M |
|--------|----|----|
| Execution | Limit (may not fill) | Market (always fills) |
| Price control | Yes | No |
| Gap protection | Poor (may not fill) | Better (will fill) |
| Complexity | Two prices needed | One trigger price |
| Best for | Normal markets | Gap protection |

### OpenAlgo API

```json
{
  "apikey": "your-key",
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "SELL",
  "quantity": "100",
  "pricetype": "SL-M",
  "trigger_price": "615",
  "product": "MIS"
}
```

## Price Type Reference

| Price Type | Parameters Needed | Use Case |
|------------|-------------------|----------|
| MARKET | None | Immediate execution |
| LIMIT | price | Specific price entry/exit |
| SL | price, trigger_price | Stop-loss with limit |
| SL-M | trigger_price | Stop-loss with market |

## Product Types

### MIS (Margin Intraday Square-off)

- For intraday trading
- Auto-closes before market end
- Higher leverage available
- Lower margin required

### CNC (Cash and Carry)

- For delivery trading
- No auto square-off
- Stocks go to demat
- Full amount required

### NRML (Normal)

- For F&O overnight positions
- No auto square-off (within expiry)
- Standard margin applies

## Validity Types

Most brokers support:

| Validity | Meaning |
|----------|---------|
| DAY | Valid for today only |
| IOC | Immediate or Cancel (execute now or cancel) |
| GTC | Good Till Cancelled (until manually cancelled) |

**Note**: OpenAlgo typically uses DAY validity.

## Common Order Mistakes

### Mistake 1: SL Order Triggered Immediately

**Problem**: SL buy at trigger ₹625 when price is ₹620
**Why**: Trigger price is below current price (already triggered!)
**Fix**: For SL BUY, trigger must be ABOVE current price

### Mistake 2: Limit Order Not Executing

**Problem**: BUY LIMIT at ₹600 when price is ₹625
**Why**: Price never reached your limit
**Fix**: Set realistic limit prices or use market orders

### Mistake 3: Wrong Product Type

**Problem**: CNC order for options
**Why**: Options can't be delivered
**Fix**: Use MIS or NRML for F&O

## Quick Decision Guide

```
Need immediate execution?
├── YES → MARKET
└── NO → Want specific price?
         ├── YES → LIMIT
         └── NO → Setting stop-loss?
                  ├── YES → Need guaranteed execution?
                  │         ├── YES → SL-M
                  │         └── NO → SL
                  └── NO → Reconsider requirements
```

---

**Previous**: [10 - Placing Your First Order](../10-placing-first-order/README.md)

**Next**: [12 - Smart Orders](../12-smart-orders/README.md)
