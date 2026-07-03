---
type: API Endpoint
title: BasketOrder
description: Place multiple orders simultaneously as a basket
resource: https://github.com/marketcalls/openalgo/blob/main/docs/api/order-management/basketorder.md
tags:
- order
- basket
- portfolio
- trading
timestamp: '2026-07-03T00:00:00+00:00'
---

# BasketOrder

Place multiple orders simultaneously in a single API call. Ideal for portfolio rebalancing, multi-stock strategies, or executing correlated trades.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/basketorder
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/basketorder
Custom Domain:  POST https://<your-custom-domain>/api/v1/basketorder
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "Python",
  "orders": [
    {
      "symbol": "BHEL",
      "exchange": "NSE",
      "action": "BUY",
      "quantity": "1",
      "pricetype": "MARKET",
      "product": "MIS"
    },
    {
      "symbol": "ZOMATO",
      "exchange": "NSE",
      "action": "SELL",
      "quantity": "1",
      "pricetype": "MARKET",
      "product": "MIS"
    },
    {
      "symbol": "RELIANCE",
      "exchange": "NSE",
      "action": "BUY",
      "quantity": "1",
      "pricetype": "LIMIT",
      "product": "MIS",
      "price": "1180"
    }
  ]
}
```

## Sample cURL Request

```bash
curl -X POST http://127.0.0.1:5000/api/v1/basketorder \
  -H 'Content-Type: application/json' \
  -d '{
  "apikey": "<your_app_apikey>",
  "strategy": "Python",
  "orders": [
    {
      "symbol": "BHEL",
      "exchange": "NSE",
      "action": "BUY",
      "quantity": "1",
      "pricetype": "MARKET",
      "product": "MIS"
    },
    {
      "symbol": "ZOMATO",
      "exchange": "NSE",
      "action": "SELL",
      "quantity": "1",
      "pricetype": "MARKET",
      "product": "MIS"
    },
    {
      "symbol": "RELIANCE",
      "exchange": "NSE",
      "action": "BUY",
      "quantity": "1",
      "pricetype": "LIMIT",
      "product": "MIS",
      "price": "1180"
    }
  ]
}'
```

## Sample API Response

```json
{
  "status": "success",
  "results": [
    {
      "symbol": "BHEL",
      "status": "success",
      "orderid": "250408000999544"
    },
    {
      "symbol": "ZOMATO",
      "status": "success",
      "orderid": "250408000997545"
    },
    {
      "symbol": "RELIANCE",
      "status": "success",
      "orderid": "250408000997546"
    }
  ]
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| strategy | Strategy identifier | Optional | - |
| orders | Array of order objects | Mandatory | - |

### Order Object Fields

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| symbol | Trading symbol | Mandatory | - |
| exchange | Exchange code: NSE, BSE, NFO, BFO, CDS, BCD, MCX | Mandatory | - |
| action | Order action: BUY or SELL | Mandatory | - |
| quantity | Order quantity | Mandatory | - |
| pricetype | Price type: MARKET, LIMIT, SL, SL-M | Mandatory | - |
| product | Product type: MIS, CNC, NRML | Mandatory | - |
| price | Order price (for LIMIT orders) | Optional | 0 |
| trigger_price | Trigger price (for SL orders) | Optional | 0 |

See [order code constants](../../sdk/order-constants.md) for valid `exchange`, `action`, `pricetype`, and `product` values, and the [symbol format](../../sdk/symbol-format.md) reference for the `symbol` convention.

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" if at least one order succeeded |
| results | array | Array of individual order results |

### Results Array Fields

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| status | string | "success" or "error" |
| orderid | string | Order ID from broker (on success) |
| message | string | Error message (on failure) |

## Notes

- Orders are executed **concurrently** using a thread pool for faster execution
- If some orders fail, others still execute (partial success possible)
- Each order in the basket is independent
- Maximum orders per basket depends on broker limits
- Use for:
  - **Portfolio rebalancing**: Buy/sell multiple stocks together
  - **Pair trading**: Simultaneous long/short positions
  - **Index tracking**: Replicating index constituents

## Example Use Cases

### Portfolio Rebalancing
```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "Rebalance",
  "orders": [
    {"symbol": "TCS", "exchange": "NSE", "action": "BUY", "quantity": "5", "pricetype": "MARKET", "product": "CNC"},
    {"symbol": "INFY", "exchange": "NSE", "action": "BUY", "quantity": "10", "pricetype": "MARKET", "product": "CNC"},
    {"symbol": "WIPRO", "exchange": "NSE", "action": "SELL", "quantity": "8", "pricetype": "MARKET", "product": "CNC"}
  ]
}
```

### Pair Trading
```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "PairTrade",
  "orders": [
    {"symbol": "SBIN", "exchange": "NSE", "action": "BUY", "quantity": "100", "pricetype": "MARKET", "product": "MIS"},
    {"symbol": "BANKBARODA", "exchange": "NSE", "action": "SELL", "quantity": "200", "pricetype": "MARKET", "product": "MIS"}
  ]
}
```

# Citations
- Official docs: https://docs.openalgo.in
- Source: https://github.com/marketcalls/openalgo/blob/main/docs/api/order-management/basketorder.md
