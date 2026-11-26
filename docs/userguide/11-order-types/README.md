# 11 - Order Types Explained

## Introduction

Understanding order types is essential for effective trading. Each order type has specific use cases, advantages, and limitations.

## GTT Triggers

GTT is a persistent trigger workflow, separate from the MARKET/LIMIT/SL/SL-M price types below. Place single or OCO triggers, then inspect active triggers and triggered/cancelled history in the Orderbook's **GTT** tab. Analyzer supports simulated GTT triggers against live prices; live availability depends on the broker plugin. See [PlaceGTTOrder](../../api/order-management/placegttorder.md), [GTTOrderBook](../../api/order-management/gttorderbook.md), [ModifyGTTOrder](../../api/order-management/modifygttorder.md) and [CancelGTTOrder](../../api/order-management/cancelgttorder.md).

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

Requests execution at the available market price. Liquidity, broker/exchange acceptance and price protection can still prevent or delay a fill.

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
| Requests execution at available market prices | No price control or guaranteed fill |
| Simple to use | May get worse price |
| Fast | Slippage in volatile markets |

### OpenAlgo API

```json
{
  "apikey": "your-key",
  "strategy": "OrderTypeExample",
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
Result: Order executes at ₹620

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
  "strategy": "OrderTypeExample",
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
  "strategy": "OrderTypeExample",
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
2. Once triggered, becomes a market order (subject to liquidity, price protection and broker/exchange acceptance)

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
| Execution | Limit (may not fill) | Market (liquidity/acceptance dependent) |
| Price control | Yes | No |
| Gap protection | Poor (may not fill) | No limit-price control; a fill is not guaranteed |
| Complexity | Two prices needed | One trigger price |
| Best for | Normal markets | Gap protection |

### OpenAlgo API

```json
{
  "apikey": "your-key",
  "strategy": "OrderTypeExample",
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

## Validity and Broker Support

The unified PlaceOrder request does not offer a general validity selector. Do not add `IOC` or `GTC` fields assuming every adapter supports them. Broker plugins map supported price/product types to their own request formats; check the broker's current instrument and order-type restrictions. GTT is the separate trigger workflow linked above.

## Common Order Mistakes

### Mistake 1: SL Order Triggered Immediately

**Problem**: SL buy at trigger ₹615 when price is already ₹620
**Why**: The market is already above the buy trigger
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
                  ├── YES → Prefer a market order after trigger?
                  │         ├── YES → SL-M
                  │         └── NO → SL
                  └── NO → Reconsider requirements
```

---

**Previous**: [10 - Placing Your First Order](../10-placing-first-order/README.md)

**Next**: [12 - Smart Orders](../12-smart-orders/README.md)
