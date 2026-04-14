# Expiry

Get available expiry dates for a futures or options symbol.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/expiry
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/expiry
Custom Domain:  POST https://<your-custom-domain>/api/v1/expiry
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "symbol": "NIFTY",
  "exchange": "NFO",
  "instrumenttype": "options"
}
```

## Sample API Response

```json
{
  "status": "success",
  "message": "Found 18 expiry dates for NIFTY options in NFO",
  "data": [
    "10-JUL-25",
    "17-JUL-25",
    "24-JUL-25",
    "31-JUL-25",
    "07-AUG-25",
    "28-AUG-25",
    "25-SEP-25",
    "24-DEC-25",
    "26-MAR-26",
    "25-JUN-26",
    "31-DEC-26",
    "24-JUN-27",
    "30-DEC-27",
    "29-JUN-28",
    "28-DEC-28",
    "28-JUN-29",
    "27-DEC-29",
    "25-JUN-30"
  ]
}
```

## Sample API Request (Futures)

```json
{
  "apikey": "<your_app_apikey>",
  "symbol": "NIFTY",
  "exchange": "NFO",
  "instrumenttype": "futures"
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| symbol | Underlying symbol (e.g., NIFTY, BANKNIFTY) | Mandatory | - |
| exchange | Exchange code: NFO, BFO, CDS, BCD, MCX | Mandatory | - |
| instrumenttype | Instrument type: "options" or "futures" | Mandatory | - |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| message | string | Summary of results |
| data | array | Array of expiry dates in DD-MMM-YY format |

## Notes

- Expiry dates are sorted in **ascending order** (nearest first)
- Weekly expiries are included for index options (NIFTY, BANKNIFTY)
- Monthly expiries extend further into the future
- Use this data to populate expiry dropdowns in your application
- Format is **DD-MMM-YY** (e.g., 10-JUL-25)

## Use Cases

- **Options trading**: Get available expiries for option selection
- **Futures trading**: Find current and far-month futures
- **Strategy building**: Select appropriate expiry for strategy

---

**Back to**: [API Documentation](../README.md)
