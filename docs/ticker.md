# Stock Ticker Aggregates API

## Overview
The Stock Ticker Aggregates API provides historical price data for stocks in customizable time windows. It allows you to fetch OHLCV (Open, High, Low, Close, Volume) data for any stock with flexible interval options.

## Endpoint
```
GET http://127.0.0.1:5000/api/v1/ticker/{exchange}:{symbol}
```

## Parameters

### Path Parameters
- `exchange:symbol` (required): Combined exchange and symbol (e.g., NSE:RELIANCE). Defaults to NSE:RELIANCE if not provided.

### Query Parameters
- `interval` (optional): The time interval for the data. Default: D
  Supported intervals:
  - Seconds: 5s, 10s, 15s, 30s, 45s
  - Minutes: 1m, 2m, 3m, 5m, 10m, 15m, 20m, 30m
  - Hours: 1h, 2h, 4h
  - Days: D
  - Weeks: W
  - Months: M
- `from` (required): The start date in YYYY-MM-DD format or millisecond timestamp
- `to` (required): The end date in YYYY-MM-DD format or millisecond timestamp
- `adjusted` (optional): Whether to adjust for splits. Default: true
  - true: Results are adjusted for splits
  - false: Results are NOT adjusted for splits
- `sort` (optional): Sort results by timestamp. Default: asc
  - asc: Results sorted in ascending order (oldest first)
  - desc: Results sorted in descending order (newest first)

### Authentication
API key must be provided either:
- In the request header as `X-API-KEY`
- As a query parameter `apikey`

**Note**: The API key must be obtained from your OpenAlgo instance dashboard under the API Key section.

### AmiBroker Integration
For AmiBroker users, use this exact URL template format to fetch historical quotes:
```
http://127.0.0.1:5000/api/v1/ticker/{symbol}?apikey={api_key}&interval={interval_extra}&from={from_ymd}&to={to_ymd}&format=txt
```

Example:
```
http://127.0.0.1:5000/api/v1/ticker/NSE:ICICIBANK?apikey=your_api_key_here&interval=1m&from=2025-06-04&to=2025-07-04&format=txt
```

## Example Request
```
GET http://127.0.0.1:5000/api/v1/ticker/NSE:RELIANCE?apikey=your_api_key_here&interval=D&from=2023-01-09&to=2023-02-10&adjusted=true&sort=asc
```

## Response Format
```json
{
    "status": "success",
    "data": [
        {
            "timestamp": "2023-01-09, 05:00:00",
            "open": 60.25,
            "high": 61.40,
            "low": 59.80,
            "close": 60.95,
            "volume": 12345678
        },
        // ... more data points
    ]
}
```

## Error Responses
- 400: Bad Request - Invalid parameters
- 403: Forbidden - Invalid API key
- 404: Not Found - Broker module not found
- 500: Internal Server Error - Unexpected error

## Example Usage
For example, to get 5-minute bars for RELIANCE stock from NSE:
```
GET http://127.0.0.1:5000/api/v1/ticker/NSE:RELIANCE?apikey=your_api_key_here&interval=5m&from=2023-01-09&to=2023-02-10
```

This will return 5-minute OHLCV bars for RELIANCE between January 9, 2023, and February 10, 2023.

## Ticker API Documentation

The Ticker API provides historical stock data in both daily and intraday formats. The API supports both JSON and plain text responses.

## Endpoint

```
GET /api/v1/ticker/{exchange}:{symbol}
```

## Parameters

| Parameter | Type   | Required | Description                                      | Example     |
|-----------|--------|----------|--------------------------------------------------|-------------|
| symbol    | string | Yes      | Stock symbol with exchange (e.g., NSE:RELIANCE)    | NSE:RELIANCE  |
| interval  | string | No       | Time interval (D, 1m, 5m, 1h, etc.). Default: D  | 5m          |
| from      | string | No       | Start date in YYYY-MM-DD format                  | 2024-12-01  |
| to        | string | No       | End date in YYYY-MM-DD format                    | 2024-12-31  |
| apikey    | string | Yes      | API Key for authentication                       | your_api_key|
| format    | string | No       | Response format (json/txt). Default: json        | txt         |

## Response Formats

### Plain Text Format (format=txt)

#### Daily Data (interval=D)
Format: `Ticker,Date_YMD,Open,High,Low,Close,Volume`

Example:
```
NSE:RELIANCE,2024-12-02,2815.9,2857.7,2804.45,2825.5,3517068
NSE:RELIANCE,2024-12-03,2797.7,2823.35,2790.0,2798.5,3007864
```

#### Intraday Data (interval=1m, 5m, etc.)
Format: `Ticker,Date_YMD,Time,Open,High,Low,Close,Volume`

Example:
```
NSE:ICICIBANK,2025-06-04,09:15:00,1437.4,1440.1,1433.0,1433.6,345598
NSE:ICICIBANK,2025-06-04,09:16:00,1434.0,1436.3,1432.5,1434.2,83225
NSE:ICICIBANK,2025-06-04,09:17:00,1434.4,1434.8,1432.9,1433.8,26743
NSE:ICICIBANK,2025-06-04,09:18:00,1433.8,1434.8,1433.2,1433.4,22281
NSE:ICICIBANK,2025-06-04,09:19:00,1433.3,1433.3,1430.3,1431.0,35529
NSE:ICICIBANK,2025-06-04,09:20:00,1430.6,1431.9,1430.1,1431.0,31222
NSE:ICICIBANK,2025-06-04,09:21:00,1431.0,1432.0,1430.9,1431.8,25495
NSE:ICICIBANK,2025-06-04,09:22:00,1431.8,1432.3,1431.4,1432.3,9631
NSE:ICICIBANK,2025-06-04,09:23:00,1432.3,1432.3,1431.4,1431.8,15877
NSE:ICICIBANK,2025-06-04,09:24:00,1431.5,1431.7,1430.6,1431.2,12727
NSE:ICICIBANK,2025-06-04,09:25:00,1431.2,1431.5,1431.0,1431.3,20720
NSE:ICICIBANK,2025-06-04,09:26:00,1431.5,1432.2,1431.3,1432.2,10217
```

### JSON Format (format=json)

```json
{
    "status": "success",
    "data": [
        {
            "timestamp": 1701432600,
            "open": 2815.9,
            "high": 2857.7,
            "low": 2804.45,
            "close": 2825.5,
            "volume": 3517068
        },
        ...
    ]
}
```

## Error Responses

### Plain Text Format
Error messages are returned as plain text with appropriate HTTP status codes.

Example:
```
Invalid openalgo apikey
```

### JSON Format
```json
{
    "status": "error",
    "message": "Invalid openalgo apikey"
}
```

## HTTP Status Codes

| Code | Description                                           |
|------|-------------------------------------------------------|
| 200  | Successful request                                     |
| 400  | Bad request (invalid parameters)                       |
| 403  | Invalid API key                                        |
| 404  | Broker module not found                                |
| 500  | Internal server error                                  |

## Rate Limiting

The API is rate-limited to 10 requests per second by default. This can be configured using the `API_RATE_LIMIT` environment variable.

## Date Range Restrictions

To prevent large queries that could hit broker rate limits, the API automatically restricts date ranges:

- **Daily/Weekly/Monthly intervals (D, W, M)**: Maximum 10 years from end date
- **Intraday intervals (1m, 5m, 1h, etc.)**: Maximum 30 days from end date

If a request exceeds these limits, the start date will be automatically adjusted. For example:
- Original request: `http://127.0.0.1:5000/api/v1/ticker/NSE:ICICIBANK?apikey=your_api_key_here&interval=1m&from=2000-06-01&to=2025-07-04&format=txt`
- Adjusted to: `from=2025-06-04&to=2025-07-04&interval=1m` (30 days for 1-minute data)

## Notes

1. All timestamps in the responses are in Indian Standard Time (IST)
2. Volume is always returned as an integer
3. If no symbol is provided, defaults to "NSE:RELIANCE"
4. If no exchange is specified in the symbol, defaults to "NSE"
5. The API supports both formats:
   - `NSE:RELIANCE` (preferred)
   - `RELIANCE` (defaults to NSE)
