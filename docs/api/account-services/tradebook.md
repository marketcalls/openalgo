# TradeBook

Get all executed trades for the current trading day.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/tradebook
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/tradebook
Custom Domain:  POST https://<your-custom-domain>/api/v1/tradebook
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
  "data": [
    {
      "action": "BUY",
      "symbol": "RELIANCE",
      "exchange": "NSE",
      "orderid": "250408000989443",
      "product": "MIS",
      "quantity": 0.0,
      "average_price": 1180.1,
      "timestamp": "13:58:03",
      "trade_value": 1180.1
    },
    {
      "action": "SELL",
      "symbol": "NHPC",
      "exchange": "NSE",
      "orderid": "250408001086129",
      "product": "MIS",
      "quantity": 0.0,
      "average_price": 83.74,
      "timestamp": "14:28:49",
      "trade_value": 83.74
    }
  ]
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
| data | array | Array of trade objects |

### Trade Object Fields

| Field | Type | Description |
|-------|------|-------------|
| orderid | string | Order ID that generated this trade |
| symbol | string | Trading symbol |
| exchange | string | Exchange code |
| action | string | BUY or SELL |
| quantity | number | Traded quantity |
| average_price | number | Execution price |
| product | string | MIS, CNC, NRML |
| timestamp | string | Trade execution time |
| trade_value | number | Total trade value (quantity × price) |

## Notes

- Contains only **executed trades** (not pending orders)
- A single order may have **multiple trades** (partial fills)
- **trade_value** is the monetary value of the trade
- Use for trade reconciliation and P&L calculation
- Trades are sorted by execution time

## Difference: OrderBook vs TradeBook

| Aspect | OrderBook | TradeBook |
|--------|-----------|-----------|
| Contains | All orders (including pending) | Only executed trades |
| Multiple entries | One per order | One per fill (partial fills) |
| Shows | Order status | Execution details |

---

**Back to**: [API Documentation](../README.md)
