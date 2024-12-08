# Market Data API

## Quotes

Get real-time quotes for a symbol.

```http
POST /api/v1/quotes
```

### Request Body

| Parameter | Type   | Required | Description                                |
|-----------|--------|----------|--------------------------------------------|
| apikey    | string | Yes      | Your OpenAlgo API key                      |
| symbol    | string | Yes      | Trading symbol (e.g., SBIN)               |
| exchange  | string | Yes      | Exchange name (e.g., NSE)                 |

### Response

```javascript
{
    "status": "success",
    "data": {
        "bid": 426.85,
        "ask": 426.90,
        "open": 430.50,
        "high": 433.65,
        "low": 423.60,
        "ltp": 426.90,
        "prev_close": 425.20,
        "volume": 38977242
    }
}
```

### Response Fields

| Field      | Type   | Description                    |
|------------|--------|--------------------------------|
| bid        | number | Best bid price                 |
| ask        | number | Best ask price                 |
| open       | number | Opening price                  |
| high       | number | High price                     |
| low        | number | Low price                      |
| ltp        | number | Last traded price              |
| prev_close | number | Previous day's closing price   |
| volume     | number | Total traded volume            |

## History

Get historical data for a symbol.

```http
POST /api/v1/history
```

### Request Body

| Parameter  | Type   | Required | Description                                |
|------------|--------|----------|--------------------------------------------|
| apikey     | string | Yes      | Your OpenAlgo API key                      |
| symbol     | string | Yes      | Trading symbol (e.g., SBIN)               |
| exchange   | string | Yes      | Exchange name (e.g., NSE)                 |
| interval   | string | Yes      | Timeframe interval (see supported values)  |
| start_date | string | Yes      | Start date (YYYY-MM-DD)                   |
| end_date   | string | Yes      | End date (YYYY-MM-DD)                     |

### Supported Intervals

| Category | Values                                  |
|----------|----------------------------------------|
| Seconds  | 5s, 10s, 15s, 30s, 45s                 |
| Minutes  | 1m, 2m, 3m, 5m, 10m, 15m, 20m, 30m     |
| Hours    | 1h, 2h, 4h                             |
| Higher   | D (Daily), W (Weekly), M (Monthly)      |

### Response

```javascript
{
    "status": "success",
    "data": [
        {
            "timestamp": 1621814400,
            "open": 417.0,
            "high": 419.2,
            "low": 405.3,
            "close": 412.05,
            "volume": 142964052
        }
    ]
}
```

### Response Fields

| Field     | Type   | Description                    |
|-----------|--------|--------------------------------|
| timestamp | number | Unix epoch timestamp           |
| open      | number | Opening price                  |
| high      | number | High price                     |
| low       | number | Low price                      |
| close     | number | Closing price                  |
| volume    | number | Trading volume                 |

## Market Depth

Get market depth information for a symbol.

```http
POST /api/v1/depth
```

### Request Body

| Parameter | Type   | Required | Description                                |
|-----------|--------|----------|--------------------------------------------|
| apikey    | string | Yes      | Your OpenAlgo API key                      |
| symbol    | string | Yes      | Trading symbol (e.g., SBIN)               |
| exchange  | string | Yes      | Exchange name (e.g., NSE)                 |

### Response

```javascript
{
    "status": "success",
    "data": {
        "asks": [
            {
                "price": 1311.55,
                "quantity": 5187
            },
            {
                "price": 0,
                "quantity": 0
            },
            {
                "price": 0,
                "quantity": 0
            },
            {
                "price": 0,
                "quantity": 0
            },
            {
                "price": 0,
                "quantity": 0
            }
        ],
        "bids": [
            {
                "price": 0,
                "quantity": 0
            },
            {
                "price": 0,
                "quantity": 0
            },
            {
                "price": 0,
                "quantity": 0
            },
            {
                "price": 0,
                "quantity": 0
            },
            {
                "price": 0,
                "quantity": 0
            }
        ],
        "totalbuyqty": 0,
        "totalsellqty": 5187,
        "high": 1323.9,
        "low": 1310.0,
        "ltp": 1311.55,
        "ltq": 100,
        "open": 1323.9,
        "prev_close": 1311.55,
        "volume": 9037514,
        "oi": 0
    }
}
```

### Response Fields

| Field        | Type   | Description                    |
|--------------|--------|--------------------------------|
| asks         | array  | List of 5 best ask prices      |
| bids         | array  | List of 5 best bid prices      |
| totalbuyqty  | number | Total buy quantity             |
| totalsellqty | number | Total sell quantity            |
| high         | number | Day's high price               |
| low          | number | Day's low price                |
| ltp          | number | Last traded price              |
| ltq          | number | Last traded quantity           |
| open         | number | Opening price                  |
| prev_close   | number | Previous day's closing price   |
| volume       | number | Total traded volume            |
| oi           | number | Open interest                  |

### Error Response

```javascript
{
    "status": "error",
    "message": "Error description"
}
```

### Common Errors

| Error                    | Description                                      |
|-------------------------|--------------------------------------------------|
| Invalid API key         | The provided API key is invalid or expired       |
| Invalid symbol          | The trading symbol is not found                  |
| Invalid exchange        | The exchange name is not supported               |
| Unsupported timeframe   | The interval value is not supported             |
| Rate limit exceeded     | Too many requests in a short time period        |

### Notes

1. All timestamps are in Unix epoch format
2. Prices and quantities are returned as numbers
3. Market depth always returns exactly 5 entries for both bids and asks
4. Empty market depth entries are filled with zeros
5. Timeframe parameters are case-insensitive (e.g., "D" or "d" for daily)
6. Date format for history API: YYYY-MM-DD
7. Rate limit: 10 requests per second
