# Intervals

Get available time intervals for historical data from the current broker.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/intervals
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/intervals
Custom Domain:  POST https://<your-custom-domain>/api/v1/intervals
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
    "months": [],
    "weeks": [],
    "days": ["D"],
    "hours": ["1h"],
    "minutes": ["1m", "3m", "5m", "10m", "15m", "30m"],
    "seconds": []
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
| data | object | Available intervals by category |

### Data Object Fields

| Field | Type | Description |
|-------|------|-------------|
| months | array | Monthly intervals (e.g., "M") |
| weeks | array | Weekly intervals (e.g., "W") |
| days | array | Daily intervals (e.g., "D") |
| hours | array | Hourly intervals (e.g., "1h", "2h") |
| minutes | array | Minute intervals (e.g., "1m", "5m", "15m") |
| seconds | array | Second intervals (e.g., "1s") |

## Common Interval Values

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
| W | Weekly |
| M | Monthly |

## Notes

- Available intervals **vary by broker**
- Always check available intervals before requesting [History](./history.md)
- Some brokers may not support all interval types
- The response shows only intervals supported by your connected broker

---

**Back to**: [API Documentation](../README.md)
