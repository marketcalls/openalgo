# 13 - Basket Orders

## Introduction

Basket Orders allow you to submit multiple independent orders with a single API call. This is essential for strategies that require executing trades across multiple symbols at once.

## What is a Basket Order?

A basket order bundles multiple individual orders into one request:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Basket Order Structure                                │
│                                                                              │
│  Single API Request                                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                                                                      │   │
│  │  Order 1: BUY 100 SBIN                                              │   │
│  │  Order 2: BUY 50 INFY                                               │   │
│  │  Order 3: SELL 25 TCS                                               │   │
│  │  Order 4: BUY 200 HDFC                                              │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                               │
│                              ▼                                               │
│                    All orders sent to broker                                │
│                              │                                               │
│                              ▼                                               │
│                   Individual order responses                                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Use Cases

### 1. Index Replication

Buy all Nifty 50 constituents proportionally:

```
Basket:
- BUY 100 RELIANCE
- BUY 50 TCS
- BUY 75 HDFC
- BUY 200 INFY
... (all 50 stocks)
```

### 2. Sector Rotation

Rotate into banking sector:

```
Basket:
- SELL 100 RELIANCE (exit energy)
- SELL 50 TCS (exit IT)
- BUY 100 HDFCBANK (enter banking)
- BUY 100 ICICIBANK (enter banking)
```

### 3. Pair Trading

Long-short pair execution:

```
Basket:
- BUY 100 SBIN (long)
- SELL 100 BANKBARODA (short)
```

### 4. Options Strategies

Multi-leg option strategies:

```
Iron Condor Basket:
- SELL 1 NIFTY 21500 CE
- BUY 1 NIFTY 21600 CE
- SELL 1 NIFTY 21000 PE
- BUY 1 NIFTY 20900 PE
```

## Basket Order API

### Endpoint

```
POST /api/v1/basketorder
```

### Request Format

```json
{
  "apikey": "your-api-key",
  "strategy": "BasketStrategy",
  "orders": [
    {
      "symbol": "SBIN",
      "exchange": "NSE",
      "action": "BUY",
      "quantity": "100",
      "pricetype": "MARKET",
      "product": "MIS"
    },
    {
      "symbol": "INFY",
      "exchange": "NSE",
      "action": "BUY",
      "quantity": "50",
      "pricetype": "MARKET",
      "product": "MIS"
    },
    {
      "symbol": "TCS",
      "exchange": "NSE",
      "action": "SELL",
      "quantity": "25",
      "pricetype": "MARKET",
      "product": "MIS"
    }
  ]
}
```

### Response

```json
{
  "status": "success",
  "results": [
    {
      "symbol": "SBIN",
      "status": "success",
      "orderid": "230125000012345"
    },
    {
      "symbol": "INFY",
      "status": "success",
      "orderid": "230125000012346"
    },
    {
      "symbol": "TCS",
      "status": "success",
      "orderid": "230125000012347"
    }
  ]
}
```

## Python Example

```python
from openalgo import api

client = api(api_key="your-key", host="http://127.0.0.1:5000")

# Define basket
basket = [
    {
        "symbol": "SBIN",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 100,
        "pricetype": "MARKET",
        "product": "MIS"
    },
    {
        "symbol": "INFY",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 50,
        "pricetype": "MARKET",
        "product": "MIS"
    },
    {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 25,
        "pricetype": "MARKET",
        "product": "MIS"
    }
]

# Place basket order
response = client.basketorder(
    orders=basket,
    strategy="PortfolioRebalance"
)

# Check results
for result in response['results']:
    print(f"{result['symbol']}: {result['status']}")
```

## Order Types in Baskets

### Market Orders (Recommended)

```json
{
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": "100",
  "pricetype": "MARKET",
  "product": "MIS"
}
```

### Limit Orders

```json
{
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": "100",
  "pricetype": "LIMIT",
  "price": "620",
  "product": "MIS"
}
```

### Mixed Order Types

A basket can mix MARKET and LIMIT legs. Every leg still needs its own symbol, exchange, action, quantity and product; LIMIT also needs a price. Use the complete [BasketOrder request](../../api/order-management/basketorder.md) and review each result separately.

## Basket Execution Behavior

### Batched Submission

Live orders are submitted in concurrent batches of ten, with BUY orders before SELL orders and a one-second delay between batches. Broker acceptance, fills and their timing remain independent per leg.

### Partial Success

Some orders may succeed while others fail:

```json
{
  "results": [
    {"symbol": "SBIN", "status": "success", "orderid": "123"},
    {"symbol": "INFY", "status": "error", "message": "Insufficient margin"},
    {"symbol": "TCS", "status": "success", "orderid": "124"}
  ]
}
```

### No Atomicity

Important: Basket orders are NOT atomic!
- Each order is independent
- One failure doesn't cancel others
- You must handle partial fills

## Handling Partial Outcomes

Inspect every entry in `results`; the top-level `status` does not prove that every leg was accepted or filled. A basket is not atomic and does not roll back earlier legs when a later leg fails.

If a request times out or a leg has no confirmed outcome, reconcile the broker's order book, trade book and positions before sending any replacement. Do not retry a whole basket or select retries only by symbol: an accepted order may already exist, and two legs can use the same symbol.

Only send a corrected or replacement leg after confirming what happened to that specific order. In Semi-Auto, a response with `pending_order_id` means the basket is queued in [Action Center](../22-action-center/README.md), not executed.

## Limits and Execution

Live baskets process BUY orders before SELL orders, in concurrent batches of ten with a one-second delay between batches. This is not a promise of simultaneous fills or a broker rate-limit allowance. Account entitlement, margin, order-rate limits and each instrument's freeze quantity still apply.

- Rehearse in Analyzer mode and review each leg's symbol, product and quantity.
- Market orders can slip, be rejected or remain unfilled; no order type guarantees execution.
- For an option contract, quantity is units, not the number of lots. Look up its current lot size.
- Read the [BasketOrder API reference](../../api/order-management/basketorder.md) for the request/response contract and current routing behavior.

## Options Strategy Baskets

### Bull Call Spread

```json
{
  "apikey": "your-key",
  "strategy": "BullCallSpread",
  "orders": [
    {
      "symbol": "NIFTY30JAN2521500CE",
      "exchange": "NFO",
      "action": "BUY",
      "quantity": "50",
      "pricetype": "MARKET",
      "product": "NRML"
    },
    {
      "symbol": "NIFTY30JAN2521600CE",
      "exchange": "NFO",
      "action": "SELL",
      "quantity": "50",
      "pricetype": "MARKET",
      "product": "NRML"
    }
  ]
}
```

### Iron Condor

An iron condor has separate short/long call and short/long put legs. Search the actual contracts for the intended expiry, choose the current lot size and include every required field per leg. The [Strategy Builder](../31-tools/README.md#1-strategy-builder-strategybuilder) can prepare and review those legs before basket submission.

## Basket vs Individual Orders

| Aspect | Basket | Individual |
|--------|--------|------------|
| API calls | 1 | Multiple |
| Speed | Faster | Slower |
| Complexity | Higher | Lower |
| Error handling | Complex | Simple |
| Best for | Multi-symbol strategies | Single symbol |

---

**Previous**: [12 - Smart Orders](../12-smart-orders/README.md)

**Next**: [14 - Positions & Holdings](../14-positions-holdings/README.md)
