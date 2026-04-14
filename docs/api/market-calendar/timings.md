# Timings

Get market trading timings for a specific date across all exchanges.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/timings
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/timings
Custom Domain:  POST https://<your-custom-domain>/api/v1/timings
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "date": "2025-12-19"
}
```

## Sample API Response

```json
{
  "status": "success",
  "data": [
    {
      "exchange": "NSE",
      "start_time": 1766115900000,
      "end_time": 1766138400000
    },
    {
      "exchange": "BSE",
      "start_time": 1766115900000,
      "end_time": 1766138400000
    },
    {
      "exchange": "NFO",
      "start_time": 1766115900000,
      "end_time": 1766138400000
    },
    {
      "exchange": "BFO",
      "start_time": 1766115900000,
      "end_time": 1766138400000
    },
    {
      "exchange": "CDS",
      "start_time": 1766115000000,
      "end_time": 1766143800000
    },
    {
      "exchange": "BCD",
      "start_time": 1766115000000,
      "end_time": 1766143800000
    },
    {
      "exchange": "MCX",
      "start_time": 1766115000000,
      "end_time": 1766168700000
    }
  ]
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| date | Date in YYYY-MM-DD format | Mandatory | - |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| data | array | Array of timing objects |

### Timing Object Fields

| Field | Type | Description |
|-------|------|-------------|
| exchange | string | Exchange code |
| start_time | number | Market open time (epoch milliseconds) |
| end_time | number | Market close time (epoch milliseconds) |

## Standard Trading Hours (IST)

| Exchange | Open | Close |
|----------|------|-------|
| NSE | 09:15 | 15:30 |
| BSE | 09:15 | 15:30 |
| NFO | 09:15 | 15:30 |
| BFO | 09:15 | 15:30 |
| CDS | 09:00 | 17:00 |
| BCD | 09:00 | 17:00 |
| MCX | 09:00 | 23:30 |

## Notes

- Date must be between **2020-01-01 and 2050-12-31**
- Times are returned as **epoch milliseconds**
- Returns **empty array** for weekends and full holidays
- For **special sessions** (e.g., Muhurat trading), returns only the special session timings
- MCX has extended trading hours into the night

## Converting Epoch to Readable Time

**JavaScript:**
```javascript
const date = new Date(1766115900000);
console.log(date.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }));
// Output: "19/12/2025, 9:15:00 am"
```

**Python:**
```python
from datetime import datetime
import pytz

ist = pytz.timezone('Asia/Kolkata')
dt = datetime.fromtimestamp(1766115900000/1000, ist)
print(dt.strftime('%Y-%m-%d %H:%M:%S %Z'))
# Output: 2025-12-19 09:15:00 IST
```

---

**Back to**: [API Documentation](../README.md)
