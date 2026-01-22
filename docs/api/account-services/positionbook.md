# PositionBook

Get all current open positions for the trading day.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/positionbook
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/positionbook
Custom Domain:  POST https://<your-custom-domain>/api/v1/positionbook
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
      "symbol": "NHPC",
      "exchange": "NSE",
      "product": "MIS",
      "quantity": "-1",
      "average_price": "83.74",
      "ltp": "83.72",
      "pnl": "0.02"
    },
    {
      "symbol": "RELIANCE",
      "exchange": "NSE",
      "product": "MIS",
      "quantity": "0",
      "average_price": "0.0",
      "ltp": "1189.9",
      "pnl": "5.90"
    },
    {
      "symbol": "YESBANK",
      "exchange": "NSE",
      "product": "MIS",
      "quantity": "-104",
      "average_price": "17.2",
      "ltp": "17.31",
      "pnl": "-10.44"
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
| data | array | Array of position objects |

### Position Object Fields

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| exchange | string | Exchange code |
| product | string | MIS, CNC, NRML |
| quantity | string | Net position quantity |
| average_price | string | Average entry price |
| ltp | string | Last traded price |
| pnl | string | Profit/Loss |

## Understanding Position Quantity

| Quantity | Meaning |
|----------|---------|
| Positive (+ve) | Long position |
| Negative (-ve) | Short position |
| Zero (0) | Closed position (still shows today's P&L) |

## Notes

- Returns **all positions including closed ones** (quantity = 0)
- Closed positions show the **realized P&L** for the day
- **average_price** is the weighted average entry price
- **ltp** is the current market price
- **pnl** = (LTP - Average Price) × Quantity (for long), reverse for short
- For F&O positions, ensure lot size alignment

## Use Cases

- **Position monitoring**: Track all open positions
- **P&L tracking**: View real-time profit/loss
- **Risk management**: Monitor position sizes

## Related Endpoints

- [OpenPosition](../order-information/openposition.md) - Get position for specific symbol
- [ClosePosition](../order-management/closeposition.md) - Close all positions

---

**Back to**: [API Documentation](../README.md)
