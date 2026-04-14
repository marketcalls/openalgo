# AnalyzerStatus

Get the current status of the analyzer (sandbox) mode.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/analyzerstatus
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/analyzerstatus
Custom Domain:  POST https://<your-custom-domain>/api/v1/analyzerstatus
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>"
}
```

## Sample API Response (Analyzer Mode ON)

```json
{
  "status": "success",
  "data": {
    "analyze_mode": true,
    "mode": "analyze",
    "total_logs": 2
  }
}
```

## Sample API Response (Live Mode)

```json
{
  "status": "success",
  "data": {
    "analyze_mode": false,
    "mode": "live",
    "total_logs": 0
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
| data | object | Analyzer status data |

### Data Object Fields

| Field | Type | Description |
|-------|------|-------------|
| analyze_mode | boolean | true if analyzer mode is active |
| mode | string | "analyze" or "live" |
| total_logs | number | Number of orders logged in analyzer mode |

## What is Analyzer Mode?

Analyzer mode (sandbox mode) allows you to test your trading strategies without placing real orders:

| Feature | Live Mode | Analyzer Mode |
|---------|-----------|---------------|
| Orders sent to broker | Yes | No |
| Real money at risk | Yes | No |
| Order IDs | Real broker IDs | Simulated IDs |
| Response format | Same | Same (with mode: "analyze") |
| Uses sandbox capital | No | Yes (₹1 Crore) |

## Notes

- Check analyzer status before placing important orders
- **total_logs** shows how many simulated orders have been placed
- Use [AnalyzerToggle](./analyzertoggle.md) to switch between modes
- Analyzer mode is ideal for:
  - Strategy testing
  - API integration testing
  - Demo purposes

---

**Back to**: [API Documentation](../README.md)
