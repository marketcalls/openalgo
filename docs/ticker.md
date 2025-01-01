# Stock Ticker Aggregates API

## Overview
The Stock Ticker Aggregates API provides historical price data for stocks in customizable time windows. It allows you to fetch OHLCV (Open, High, Low, Close, Volume) data for any stock with flexible interval options.

## Endpoint
```
GET http://127.0.0.1:5000/api/v1/ticker/{exchange}:{symbol}
```

## Parameters

### Path Parameters
- `exchange:symbol` (required): Combined exchange and symbol (e.g., NSE:ZOMATO). Defaults to NSE:ZOMATO if not provided.

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

## Example Request
```
GET http://127.0.0.1:5000/api/v1/ticker/NSE:ZOMATO?interval=D&from=2023-01-09&to=2023-02-10&adjusted=true&sort=asc
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
For example, to get 5-minute bars for ZOMATO stock from NSE:
```
GET http://127.0.0.1:5000/api/v1/ticker/NSE:ZOMATO?interval=5m&from=2023-01-09&to=2023-02-10
```

This will return 5-minute OHLCV bars for ZOMATO between January 9, 2023, and February 10, 2023.

## Ticker API Documentation

The Ticker API provides historical stock data in both daily and intraday formats. The API supports both JSON and plain text responses.

## Endpoint

```
GET /api/v1/ticker/{exchange}:{symbol}
```

## Parameters

| Parameter | Type   | Required | Description                                      | Example     |
|-----------|--------|----------|--------------------------------------------------|-------------|
| symbol    | string | Yes      | Stock symbol with exchange (e.g., NSE:ZOMATO)    | NSE:ZOMATO  |
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
NSE:ZOMATO,2024-12-02,281.9,285.7,280.45,282.5,35170688
NSE:ZOMATO,2024-12-03,279.7,282.35,279.0,279.85,30078648
```

#### Intraday Data (interval=1m, 5m, etc.)
Format: `Ticker,Date_YMD,Time,Open,High,Low,Close,Volume`

Example:
```
NSE:ZOMATO,2024-12-02,09:15:00,281.5,281.95,280.45,281.05,529484
NSE:ZOMATO,2024-12-02,09:16:00,281.0,281.4,280.65,280.95,391523
```

### JSON Format (format=json)

```json
{
    "status": "success",
    "data": [
        {
            "timestamp": 1701432600,
            "open": 281.9,
            "high": 285.7,
            "low": 280.45,
            "close": 282.5,
            "volume": 35170688
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

## Notes

1. All timestamps in the responses are in Indian Standard Time (IST)
2. Volume is always returned as an integer
3. If no symbol is provided, defaults to "NSE:ZOMATO"
4. If no exchange is specified in the symbol, defaults to "NSE"
5. The API supports both formats:
   - `NSE:ZOMATO` (preferred)
   - `ZOMATO` (defaults to NSE)
