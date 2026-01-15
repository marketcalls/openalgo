# Market Holidays

## Endpoint URL

This API retrieves market holidays for Indian stock exchanges for a specific year.

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/market/holidays
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/market/holidays
Custom Domain:  POST https://<your-custom-domain>/api/v1/market/holidays
```

## Sample API Request

```json
{
    "apikey": "<your_app_apikey>",
    "year": 2025
}
```

## Sample API Response

```json
{
    "status": "success",
    "year": 2025,
    "timezone": "Asia/Kolkata",
    "data": [
        {
            "date": "2025-02-26",
            "description": "Maha Shivaratri",
            "holiday_type": "TRADING_HOLIDAY",
            "closed_exchanges": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
            "open_exchanges": [
                {
                    "exchange": "MCX",
                    "start_time": 1740549000000,
                    "end_time": 1740602700000
                }
            ]
        },
        {
            "date": "2025-04-18",
            "description": "Good Friday",
            "holiday_type": "TRADING_HOLIDAY",
            "closed_exchanges": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"],
            "open_exchanges": []
        },
        {
            "date": "2025-11-01",
            "description": "Diwali Laxmi Pujan (Muhurat Trading)",
            "holiday_type": "SPECIAL_SESSION",
            "closed_exchanges": [],
            "open_exchanges": [
                {"exchange": "NSE", "start_time": 1730469000000, "end_time": 1730473500000},
                {"exchange": "BSE", "start_time": 1730469000000, "end_time": 1730473500000},
                {"exchange": "NFO", "start_time": 1730469000000, "end_time": 1730473500000},
                {"exchange": "BFO", "start_time": 1730469000000, "end_time": 1730473500000},
                {"exchange": "CDS", "start_time": 1730469000000, "end_time": 1730473500000},
                {"exchange": "BCD", "start_time": 1730469000000, "end_time": 1730473500000},
                {"exchange": "MCX", "start_time": 1730469000000, "end_time": 1730491500000}
            ]
        }
    ]
}
```

## Request Fields

| Parameter | Description                                         | Mandatory/Optional | Default Value |
| --------- | --------------------------------------------------- | ------------------ | ------------- |
| apikey    | App API key for authentication                      | Mandatory          | -             |
| year      | Year to get holidays for (2020-2050)                | Optional           | Current year  |

## Response Fields

| Field             | Type    | Description                                                |
| ----------------- | ------- | ---------------------------------------------------------- |
| status            | String  | Response status: "success" or "error"                      |
| year              | Integer | Year for which holidays are returned                       |
| timezone          | String  | Timezone of the timestamps (Asia/Kolkata)                  |
| data              | Array   | List of holiday objects                                    |

### Holiday Object Fields

| Field             | Type    | Description                                                |
| ----------------- | ------- | ---------------------------------------------------------- |
| date              | String  | Holiday date in YYYY-MM-DD format                          |
| description       | String  | Name/description of the holiday                            |
| holiday_type      | String  | Type of holiday (see Holiday Types below)                  |
| closed_exchanges  | Array   | List of exchanges closed on this day                       |
| open_exchanges    | Array   | List of exchanges with special timings                     |

### Open Exchange Object Fields

| Field      | Type    | Description                               |
| ---------- | ------- | ----------------------------------------- |
| exchange   | String  | Exchange code (NSE, BSE, NFO, etc.)       |
| start_time | Integer | Market open time (epoch milliseconds)     |
| end_time   | Integer | Market close time (epoch milliseconds)    |

## Holiday Types

| Type               | Description                                                      |
| ------------------ | ---------------------------------------------------------------- |
| TRADING_HOLIDAY    | Full trading holiday (market closed)                             |
| SETTLEMENT_HOLIDAY | Settlement operations closed, trading is open with normal hours  |
| SPECIAL_SESSION    | Special trading session (e.g., Muhurat Trading on Diwali)        |

## Supported Exchanges

| Exchange | Description                        |
| -------- | ---------------------------------- |
| NSE      | National Stock Exchange            |
| BSE      | Bombay Stock Exchange              |
| NFO      | NSE Futures & Options              |
| BFO      | BSE Futures & Options              |
| MCX      | Multi Commodity Exchange           |
| CDS      | Currency Derivatives Segment       |
| BCD      | BSE Currency Derivatives           |

## Example Usage

### Get 2025 Holidays

```bash
curl -X POST "http://127.0.0.1:5000/api/v1/market/holidays" \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "your-api-key",
    "year": 2025
  }'
```

### Get Current Year Holidays

```bash
curl -X POST "http://127.0.0.1:5000/api/v1/market/holidays" \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "your-api-key"
  }'
```

## Python Example

```python
import requests
from datetime import datetime

# API endpoint
url = "http://127.0.0.1:5000/api/v1/market/holidays"

# Request payload
payload = {
    "apikey": "your-api-key",
    "year": 2025
}

# Make the request
response = requests.post(url, json=payload)

# Parse the response
if response.status_code == 200:
    data = response.json()
    if data['status'] == 'success':
        print(f"Holidays for {data['year']}:")
        for holiday in data['data']:
            print(f"  {holiday['date']}: {holiday['description']} ({holiday['holiday_type']})")
            if holiday['closed_exchanges']:
                print(f"    Closed: {', '.join(holiday['closed_exchanges'])}")
            if holiday['open_exchanges']:
                for ex in holiday['open_exchanges']:
                    start = datetime.fromtimestamp(ex['start_time']/1000)
                    end = datetime.fromtimestamp(ex['end_time']/1000)
                    print(f"    {ex['exchange']}: {start.strftime('%H:%M')} - {end.strftime('%H:%M')}")
    else:
        print(f"Error: {data['message']}")
else:
    print(f"HTTP Error: {response.status_code}")
```

## Error Response

```json
{
    "status": "error",
    "message": "Year must be between 2020 and 2050"
}
```

## Error Codes

| HTTP Status | Error Type    | Description                    |
| ----------- | ------------- | ------------------------------ |
| 200         | Success       | Request processed successfully |
| 400         | Bad Request   | Invalid request parameters     |
| 403         | Forbidden     | Invalid API key                |
| 500         | Server Error  | Internal server error          |

## Notes

- Timestamps are in epoch milliseconds (multiply by 1000 for JavaScript Date)
- MCX often has evening sessions on equity market holidays
- Muhurat Trading is a special 1-hour session on Diwali evening
- Settlement holidays have normal trading hours but settlement is closed
- Holiday data is pre-seeded for 2025 and 2026
- Data is cached for 1 hour for performance

## Rate Limits

This API endpoint is subject to rate limiting. The default rate limit is 10 requests per second per API key.
