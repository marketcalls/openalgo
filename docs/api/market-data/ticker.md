# Ticker-Compatible History

Return broker historical candles in JSON or ticker-oriented plain text.

## Endpoint

```http
GET /api/v1/ticker/<string:symbol>
```

Example:

```bash
curl --get 'http://127.0.0.1:5000/api/v1/ticker/NSE:RELIANCE' \
  --data-urlencode 'apikey=<your_app_apikey>' \
  --data-urlencode 'interval=D' \
  --data-urlencode 'from=2026-07-01' \
  --data-urlencode 'to=2026-07-10' \
  --data-urlencode 'format=json'
```

## Query Parameters

| Parameter | Required | Description |
|---|---:|---|
| `apikey` | Yes | OpenAlgo API key |
| `interval` | No | History interval; defaults to `D` |
| `from` | Yes | Start date in `YYYY-MM-DD` |
| `to` | Yes | End date in `YYYY-MM-DD` |
| `format` | No | `json` or `txt`; defaults to `json` |

The path must contain one colon. If it does not, the implementation falls back to `NSE:RELIANCE`; callers should not rely on that fallback.

## JSON Response

```json
{
  "status": "success",
  "data": [
    {
      "timestamp": 1783296000,
      "open": 1510.5,
      "high": 1532.0,
      "low": 1504.1,
      "close": 1528.4,
      "volume": 6234100
    }
  ]
}
```

`format=txt` returns comma-separated plain-text rows. Daily rows are `Ticker,Date,Open,High,Low,Close,Volume`; intraday rows also include time after the date.

The handler restricts large date ranges according to interval before calling the broker. This endpoint always reads the broker API; use [`/history`](./history.md) with `source: "db"` for Historify data.

**Back to**: [API documentation](../README.md)
