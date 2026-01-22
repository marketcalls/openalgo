# 13 - Basket Orders

## Introduction

Basket Orders allow you to place multiple orders simultaneously with a single API call. This is essential for strategies that require executing trades across multiple symbols at once.

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
  ],
  "total_orders": 3,
  "successful": 3,
  "failed": 0
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
response = client.place_basket_order(
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

You can mix order types in a basket:

```json
{
  "orders": [
    {
      "symbol": "SBIN",
      "pricetype": "MARKET",
      ...
    },
    {
      "symbol": "INFY",
      "pricetype": "LIMIT",
      "price": "1500",
      ...
    }
  ]
}
```

## Basket Execution Behavior

### Parallel Execution

Orders are sent to broker in parallel:

```
Time 0ms:  All orders submitted
Time 50ms: SBIN executed
Time 55ms: INFY executed
Time 60ms: TCS executed
```

### Partial Success

Some orders may succeed while others fail:

```json
{
  "results": [
    {"symbol": "SBIN", "status": "success", "orderid": "123"},
    {"symbol": "INFY", "status": "error", "message": "Insufficient margin"},
    {"symbol": "TCS", "status": "success", "orderid": "124"}
  ],
  "successful": 2,
  "failed": 1
}
```

### No Atomicity

Important: Basket orders are NOT atomic!
- Each order is independent
- One failure doesn't cancel others
- You must handle partial fills

## Handling Partial Failures

```python
response = client.place_basket_order(orders=basket, strategy="MyStrategy")

# Check for failures
failed_orders = [r for r in response['results'] if r['status'] == 'error']

if failed_orders:
    print("Failed orders:")
    for order in failed_orders:
        print(f"  {order['symbol']}: {order['message']}")

    # Retry or handle as needed
    # ...
```

## Limits and Best Practices

### Order Limits

| Limit Type | Typical Value |
|------------|---------------|
| Max orders per basket | 50 |
| Max orders per second | 10 |
| Max daily orders | Broker dependent |

### Best Practices

1. **Keep baskets manageable**: 10-20 orders ideal
2. **Use market orders** for guaranteed execution
3. **Handle partial failures** in your code
4. **Test in Analyzer mode** first
5. **Monitor execution** in order book

### Error Handling Example

```python
def execute_basket_with_retry(basket, max_retries=3):
    response = client.place_basket_order(orders=basket, strategy="MyStrategy")

    failed = [r for r in response['results'] if r['status'] == 'error']

    retries = 0
    while failed and retries < max_retries:
        # Extract failed orders
        failed_symbols = [f['symbol'] for f in failed]
        retry_basket = [o for o in basket if o['symbol'] in failed_symbols]

        # Wait and retry
        time.sleep(1)
        response = client.place_basket_order(orders=retry_basket, strategy="MyStrategy")

        failed = [r for r in response['results'] if r['status'] == 'error']
        retries += 1

    return response
```

## Options Strategy Baskets

### Bull Call Spread

```json
{
  "apikey": "your-key",
  "strategy": "BullCallSpread",
  "orders": [
    {
      "symbol": "NIFTY25JAN21500CE",
      "exchange": "NFO",
      "action": "BUY",
      "quantity": "50",
      "pricetype": "MARKET",
      "product": "NRML"
    },
    {
      "symbol": "NIFTY25JAN21600CE",
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

```json
{
  "strategy": "IronCondor",
  "orders": [
    {"symbol": "NIFTY25JAN21500CE", "action": "SELL", ...},
    {"symbol": "NIFTY25JAN21600CE", "action": "BUY", ...},
    {"symbol": "NIFTY25JAN21000PE", "action": "SELL", ...},
    {"symbol": "NIFTY25JAN20900PE", "action": "BUY", ...}
  ]
}
```

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
