# Holidays

Get market holidays for a specific year including special trading sessions.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/holidays
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/holidays
Custom Domain:  POST https://<your-custom-domain>/api/v1/holidays
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "year": 2026
}
```

## Sample API Response

```json
{
  "status": "success",
  "year": 2026,
  "timezone": "Asia/Kolkata",
  "data": [
    {
      "date": "2026-01-26",
      "description": "Republic Day",
      "holiday_type": "TRADING_HOLIDAY",
      "closed_exchanges": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"],
      "open_exchanges": []
    },
    {
      "date": "2026-02-19",
      "description": "Chhatrapati Shivaji Maharaj Jayanti",
      "holiday_type": "SETTLEMENT_HOLIDAY",
      "closed_exchanges": [],
      "open_exchanges": []
    },
    {
      "date": "2026-03-10",
      "description": "Holi",
      "holiday_type": "TRADING_HOLIDAY",
      "closed_exchanges": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
      "open_exchanges": [
        {
          "exchange": "MCX",
          "start_time": 1741624200000,
          "end_time": 1741677900000
        }
      ]
    },
    {
      "date": "2026-08-15",
      "description": "Independence Day",
      "holiday_type": "TRADING_HOLIDAY",
      "closed_exchanges": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"],
      "open_exchanges": []
    }
  ]
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| year | Year to get holidays for (2020-2050) | Optional | Current year |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| year | number | Year for which holidays are returned |
| timezone | string | Timezone (Asia/Kolkata) |
| data | array | Array of holiday objects |

### Holiday Object Fields

| Field | Type | Description |
|-------|------|-------------|
| date | string | Holiday date (YYYY-MM-DD) |
| description | string | Holiday name/reason |
| holiday_type | string | Type of holiday |
| closed_exchanges | array | Exchanges fully closed |
| open_exchanges | array | Exchanges with special sessions |

### Open Exchanges Object Fields

| Field | Type | Description |
|-------|------|-------------|
| exchange | string | Exchange code |
| start_time | number | Session start (epoch milliseconds) |
| end_time | number | Session end (epoch milliseconds) |

## Holiday Types

| Type | Description |
|------|-------------|
| TRADING_HOLIDAY | Full market closure |
| SETTLEMENT_HOLIDAY | Settlement closed, trading may be open |
| SPECIAL_SESSION | Modified trading hours (e.g., Muhurat) |

## Notes

- Year must be between **2020 and 2050**
- **closed_exchanges** lists exchanges that are completely closed
- **open_exchanges** lists exchanges with special/partial sessions
- Times are in **epoch milliseconds**
- MCX often has evening sessions on NSE/BSE holidays

## Use Cases

- **Calendar planning**: Know trading days in advance
- **Strategy scheduling**: Adjust strategies for holidays
- **Risk management**: Plan for reduced liquidity days

---

**Back to**: [API Documentation](../README.md)
