# History

Get historical OHLCV (Open, High, Low, Close, Volume) data for a symbol.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/history
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/history
Custom Domain:  POST https://<your-custom-domain>/api/v1/history
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "symbol": "SBIN",
  "exchange": "NSE",
  "interval": "5m",
  "start_date": "2025-04-01",
  "end_date": "2025-04-08"
}
```

## Sample API Response

```json
{
  "status": "success",
  "data": [
    {
      "timestamp": "2025-04-01 09:15:00+05:30",
      "open": 766.50,
      "high": 774.00,
      "low": 763.20,
      "close": 772.50,
      "volume": 318625
    },
    {
      "timestamp": "2025-04-01 09:20:00+05:30",
      "open": 772.45,
      "high": 774.95,
      "low": 772.10,
      "close": 773.20,
      "volume": 197189
    },
    {
      "timestamp": "2025-04-01 09:25:00+05:30",
      "open": 773.20,
      "high": 775.60,
      "low": 772.60,
      "close": 775.15,
      "volume": 227544
    }
  ]
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| symbol | Trading symbol | Mandatory | - |
| exchange | Exchange code: NSE, BSE, NFO, BFO, CDS, BCD, MCX | Mandatory | - |
| interval | Time interval (see below) | Mandatory | - |
| start_date | Start date (YYYY-MM-DD) | Mandatory | - |
| end_date | End date (YYYY-MM-DD) | Mandatory | - |

## Supported Intervals

| Interval | Description |
|----------|-------------|
| 1m | 1 minute |
| 3m | 3 minutes |
| 5m | 5 minutes |
| 10m | 10 minutes |
| 15m | 15 minutes |
| 30m | 30 minutes |
| 1h | 1 hour |
| D | Daily |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| data | array | Array of OHLCV candles |

### Data Array Fields

| Field | Type | Description |
|-------|------|-------------|
| timestamp | string | Candle timestamp (IST timezone) |
| open | number | Opening price |
| high | number | Highest price |
| low | number | Lowest price |
| close | number | Closing price |
| volume | number | Volume traded |

## Notes

- Historical data availability depends on broker
- Timestamps are in **IST (Indian Standard Time)**
- For intraday intervals, data is typically available for the last 30-90 days
- For daily data, longer history may be available
- Use [Intervals](./intervals.md) endpoint to check available intervals for your broker

## Example: Daily Data

```json
{
  "apikey": "<your_app_apikey>",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "interval": "D",
  "start_date": "2024-01-01",
  "end_date": "2025-01-01"
}
```

## Related Endpoints

- [Intervals](./intervals.md) - Get available time intervals

---

**Back to**: [API Documentation](../README.md)
