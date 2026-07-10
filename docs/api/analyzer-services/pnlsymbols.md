# Sandbox P&L By Symbol

Return today's realized and unrealized P&L for open sandbox positions. This endpoint is available only while analyzer mode is enabled.

## Endpoint

```http
POST /api/v1/pnl/symbols
```

```bash
curl -X POST 'http://127.0.0.1:5000/api/v1/pnl/symbols' \
  -H 'Content-Type: application/json' \
  -d '{"apikey":"<your_app_apikey>"}'
```

## Response

```json
{
  "status": "success",
  "data": [
    {
      "symbol": "RELIANCE",
      "exchange": "NSE",
      "product": "MIS",
      "quantity": 10,
      "pnl": 125.5,
      "unrealized_pnl": 100.0,
      "today_realized_pnl": 25.5,
      "total_pnl_today": 125.5
    }
  ],
  "total_pnl": 125.5,
  "total_unrealized_pnl": 100.0,
  "total_today_realized_pnl": 25.5,
  "total_pnl_today": 125.5,
  "mode": "analyze"
}
```

A request made in live mode returns HTTP 400. An invalid API key returns HTTP 403.

**Back to**: [API documentation](../README.md)
