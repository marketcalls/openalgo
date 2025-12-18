# Market Timings

## Endpoint URL

This API retrieves market trading timings for a specific date across all Indian stock exchanges.

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/market/timings
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/market/timings
Custom Domain:  POST https://<your-custom-domain>/api/v1/market/timings
```

## Sample API Request

```json
{
    "apikey": "<your_app_apikey>",
    "date": "2025-04-30"
}
```

## Sample API Response (Normal Trading Day)

```json
{
    "status": "success",
    "data": [
        {"exchange": "NSE", "start_time": 1745984700000, "end_time": 1746007200000},
        {"exchange": "BSE", "start_time": 1745984700000, "end_time": 1746007200000},
        {"exchange": "NFO", "start_time": 1745984700000, "end_time": 1746007200000},
        {"exchange": "BFO", "start_time": 1745984700000, "end_time": 1746007200000},
        {"exchange": "MCX", "start_time": 1745983800000, "end_time": 1746037500000},
        {"exchange": "BCD", "start_time": 1745983800000, "end_time": 1746012600000},
        {"exchange": "CDS", "start_time": 1745983800000, "end_time": 1746012600000}
    ]
}
```

## Sample API Response (Holiday - Empty)

```json
{
    "status": "success",
    "data": []
}
```

## Sample API Response (Muhurat Trading - Special Session)

```json
{
    "status": "success",
    "data": [
        {"exchange": "NSE", "start_time": 1730469000000, "end_time": 1730473500000},
        {"exchange": "BSE", "start_time": 1730469000000, "end_time": 1730473500000},
        {"exchange": "NFO", "start_time": 1730469000000, "end_time": 1730473500000},
        {"exchange": "BFO", "start_time": 1730469000000, "end_time": 1730473500000},
        {"exchange": "CDS", "start_time": 1730469000000, "end_time": 1730473500000},
        {"exchange": "BCD", "start_time": 1730469000000, "end_time": 1730473500000},
        {"exchange": "MCX", "start_time": 1730469000000, "end_time": 1730491500000}
    ]
}
```

## Sample API Response (Partial Holiday - MCX Open)

```json
{
    "status": "success",
    "data": [
        {"exchange": "MCX", "start_time": 1741964400000, "end_time": 1742018100000}
    ]
}
```

## Request Fields

| Parameter | Description                       | Mandatory/Optional | Default Value |
| --------- | --------------------------------- | ------------------ | ------------- |
| apikey    | App API key for authentication    | Mandatory          | -             |
| date      | Date in YYYY-MM-DD format         | Mandatory          | -             |

## Response Fields

| Field      | Type    | Description                                    |
| ---------- | ------- | ---------------------------------------------- |
| status     | String  | Response status: "success" or "error"          |
| data       | Array   | List of exchange timing objects (empty if holiday) |

### Exchange Timing Object Fields

| Field      | Type    | Description                               |
| ---------- | ------- | ----------------------------------------- |
| exchange   | String  | Exchange code (NSE, BSE, NFO, etc.)       |
| start_time | Integer | Market open time (epoch milliseconds)     |
| end_time   | Integer | Market close time (epoch milliseconds)    |

## Default Market Timings (IST)

| Exchange      | Start Time | End Time | Description                    |
| ------------- | ---------- | -------- | ------------------------------ |
| NSE           | 09:15      | 15:30    | National Stock Exchange        |
| BSE           | 09:15      | 15:30    | Bombay Stock Exchange          |
| NFO           | 09:15      | 15:30    | NSE Futures & Options          |
| BFO           | 09:15      | 15:30    | BSE Futures & Options          |
| CDS           | 09:00      | 17:00    | Currency Derivatives           |
| BCD           | 09:00      | 17:00    | BSE Currency Derivatives       |
| MCX           | 09:00      | 23:55    | Multi Commodity Exchange       |

## Response Scenarios

| Scenario                   | Response                                      |
| -------------------------- | --------------------------------------------- |
| Normal trading day         | All 7 exchanges with default timings          |
| Weekend (Sat/Sun)          | Empty array `[]`                              |
| Full holiday               | Empty array `[]`                              |
| Partial holiday            | Only open exchanges (e.g., MCX evening)       |
| Muhurat Trading (Diwali)   | All exchanges with special session timings    |
| Settlement holiday         | All 7 exchanges with normal timings           |

## Example Usage

### Get Timings for a Normal Day

```bash
curl -X POST "http://127.0.0.1:5000/api/v1/market/timings" \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "your-api-key",
    "date": "2025-04-30"
  }'
```

### Check if Market is Open on a Holiday

```bash
curl -X POST "http://127.0.0.1:5000/api/v1/market/timings" \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "your-api-key",
    "date": "2025-12-25"
  }'
```

### Check Muhurat Trading Timings

```bash
curl -X POST "http://127.0.0.1:5000/api/v1/market/timings" \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "your-api-key",
    "date": "2025-11-01"
  }'
```

## Python Example

```python
import requests
from datetime import datetime, timezone, timedelta

# IST timezone
IST = timezone(timedelta(hours=5, minutes=30))

# API endpoint
url = "http://127.0.0.1:5000/api/v1/market/timings"

# Request payload
payload = {
    "apikey": "your-api-key",
    "date": "2025-04-30"
}

# Make the request
response = requests.post(url, json=payload)

# Parse the response
if response.status_code == 200:
    data = response.json()
    if data['status'] == 'success':
        if not data['data']:
            print("Market is closed (holiday/weekend)")
        else:
            print(f"Market timings for {payload['date']}:")
            for timing in data['data']:
                start = datetime.fromtimestamp(timing['start_time']/1000, IST)
                end = datetime.fromtimestamp(timing['end_time']/1000, IST)
                print(f"  {timing['exchange']}: {start.strftime('%H:%M')} - {end.strftime('%H:%M')}")
    else:
        print(f"Error: {data['message']}")
else:
    print(f"HTTP Error: {response.status_code}")
```

## JavaScript Example

```javascript
const getMarketTimings = async (date) => {
    const url = "http://127.0.0.1:5000/api/v1/market/timings";

    const payload = {
        apikey: "your-api-key",
        date: date
    };

    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (data.status === 'success') {
            if (data.data.length === 0) {
                console.log("Market is closed (holiday/weekend)");
            } else {
                console.log(`Market timings for ${date}:`);
                data.data.forEach(timing => {
                    const start = new Date(timing.start_time);
                    const end = new Date(timing.end_time);
                    console.log(`  ${timing.exchange}: ${start.toLocaleTimeString('en-IN')} - ${end.toLocaleTimeString('en-IN')}`);
                });
            }
        } else {
            console.error(`Error: ${data.message}`);
        }
    } catch (error) {
        console.error('Request failed:', error);
    }
};

// Usage
getMarketTimings("2025-04-30");
```

## Error Response

```json
{
    "status": "error",
    "message": "Invalid date format. Use YYYY-MM-DD"
}
```

## Error Codes

| HTTP Status | Error Type    | Description                    |
| ----------- | ------------- | ------------------------------ |
| 200         | Success       | Request processed successfully |
| 400         | Bad Request   | Invalid date format            |
| 403         | Forbidden     | Invalid API key                |
| 500         | Server Error  | Internal server error          |

## Error Messages

| Message                                           | Description                    |
| ------------------------------------------------- | ------------------------------ |
| "Invalid date format. Use YYYY-MM-DD"             | Date not in correct format     |
| "Date must be between 2020-01-01 and 2050-12-31"  | Date out of supported range    |

## Notes

- Timestamps are in epoch milliseconds
- Empty `data` array indicates market is closed (holiday or weekend)
- MCX has extended evening hours (09:00-23:55) on normal trading days
- On equity holidays, MCX often has evening-only sessions
- Muhurat Trading is a special ~1 hour session on Diwali
- Settlement holidays return normal timings (trading is open)
- Data is cached for 1 hour for performance

## Common Use Cases

1. **Pre-market Checks**: Verify if market is open before placing orders
2. **Scheduling Trades**: Plan order execution based on market hours
3. **MCX Evening Trading**: Check if MCX evening session is available
4. **Muhurat Trading**: Get special session timings on Diwali
5. **Holiday Detection**: Determine if a date is a market holiday

## Rate Limits

This API endpoint is subject to rate limiting. The default rate limit is 10 requests per second per API key.
