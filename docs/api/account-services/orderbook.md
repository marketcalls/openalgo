# OrderBook

Get all orders placed for the current trading day with statistics.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/orderbook
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/orderbook
Custom Domain:  POST https://<your-custom-domain>/api/v1/orderbook
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>"
}
```

## Sample API Response

```json
{
  "status": "success",
  "data": {
    "orders": [
      {
        "action": "BUY",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "orderid": "250408000989443",
        "product": "MIS",
        "quantity": "1",
        "price": 1186.0,
        "pricetype": "MARKET",
        "order_status": "complete",
        "trigger_price": 0.0,
        "timestamp": "08-Apr-2025 13:58:03"
      },
      {
        "action": "BUY",
        "symbol": "YESBANK",
        "exchange": "NSE",
        "orderid": "250408001002736",
        "product": "MIS",
        "quantity": "1",
        "price": 16.5,
        "pricetype": "LIMIT",
        "order_status": "cancelled",
        "trigger_price": 0.0,
        "timestamp": "08-Apr-2025 14:13:45"
      }
    ],
    "statistics": {
      "total_buy_orders": 2.0,
      "total_sell_orders": 0.0,
      "total_completed_orders": 1.0,
      "total_open_orders": 0.0,
      "total_rejected_orders": 0.0
    }
  }
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| data | object | Order book data |

### Data Object Fields

| Field | Type | Description |
|-------|------|-------------|
| orders | array | Array of order objects |
| statistics | object | Order statistics summary |

### Order Object Fields

| Field | Type | Description |
|-------|------|-------------|
| orderid | string | Unique order ID |
| symbol | string | Trading symbol |
| exchange | string | Exchange code |
| action | string | BUY or SELL |
| quantity | string | Order quantity |
| price | number | Order price |
| trigger_price | number | Trigger price for SL orders |
| pricetype | string | MARKET, LIMIT, SL, SL-M |
| product | string | MIS, CNC, NRML |
| order_status | string | Current order status |
| timestamp | string | Order placement time |

### Statistics Object Fields

| Field | Type | Description |
|-------|------|-------------|
| total_buy_orders | number | Total buy orders placed |
| total_sell_orders | number | Total sell orders placed |
| total_completed_orders | number | Orders fully executed |
| total_open_orders | number | Pending/open orders |
| total_rejected_orders | number | Rejected orders |

## Order Status Values

| Status | Description |
|--------|-------------|
| complete | Order fully executed |
| open | Order pending execution |
| pending | Trigger order waiting |
| rejected | Order rejected |
| cancelled | Order cancelled |

## Notes

- Returns **all orders for the current day**
- Includes completed, cancelled, and rejected orders
- **Statistics** provide a quick summary
- Use order IDs for modify/cancel operations

---

**Back to**: [API Documentation](../README.md)
