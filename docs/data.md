# Market Data API

## Workflow

The recommended workflow for using the Market Data API:

1. Get supported intervals for your broker using the intervals API
2. Use the exact interval strings returned by the intervals API
3. Make requests to other endpoints as needed

## Intervals

Get supported intervals for the broker. Use this endpoint first to get the list of valid intervals for historical data requests.

```http
POST /api/v1/intervals
```

### Request Body

| Parameter | Type   | Required | Description           |
|-----------|--------|----------|-----------------------|
| apikey    | string | Yes      | Your OpenAlgo API key |

### Response

```javascript
{
    "status": "success",
    "data": {
        "seconds": ["5s", "10s", "15s", "30s", "45s"],
        "minutes": ["1m", "2m", "3m", "5m", "10m", "15m", "20m", "30m"],
        "hours": ["1h", "2h", "4h"],
        "days": ["D"],
        "weeks": ["W"],
        "months": ["M"]
    }
}
```

### Response Fields

| Field    | Type   | Description                                |
|----------|--------|--------------------------------------------|
| seconds  | array  | List of supported second-based intervals   |
| minutes  | array  | List of supported minute-based intervals   |
| hours    | array  | List of supported hour-based intervals     |
| days     | array  | List of supported daily intervals         |
| weeks    | array  | List of supported weekly intervals        |
| months   | array  | List of supported monthly intervals       |

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

Get historical data for a symbol. Use intervals from the intervals API response.

```http
POST /api/v1/history
```

### Request Body

| Parameter  | Type   | Required | Description                                |
|------------|--------|----------|--------------------------------------------|
| apikey     | string | Yes      | Your OpenAlgo API key                      |
| symbol     | string | Yes      | Trading symbol (e.g., SBIN)               |
| exchange   | string | Yes      | Exchange name (e.g., NSE)                 |
| interval   | string | Yes      | Timeframe interval (from intervals API)    |
| start_date | string | Yes      | Start date (YYYY-MM-DD)                   |
| end_date   | string | Yes      | End date (YYYY-MM-DD)                     |

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

## Python Example

```python
import requests

def get_supported_intervals(api_key):
    """Get supported intervals for the broker"""
    response = requests.post(
        "https://api.openalgo.in/api/v1/intervals",
        json={"apikey": api_key}
    )
    return response.json()

def get_historical_data(api_key, symbol, exchange, interval, start_date, end_date):
    """Get historical data using interval from intervals API"""
    response = requests.post(
        "https://api.openalgo.in/api/v1/history",
        json={
            "apikey": api_key,
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "start_date": start_date,
            "end_date": end_date
        }
    )
    return response.json()

# Example usage
api_key = "your_api_key"

# First, get supported intervals
intervals = get_supported_intervals(api_key)
print("Supported intervals:", intervals['data'])

# Use interval from the response
history = get_historical_data(
    api_key=api_key,
    symbol="SBIN",
    exchange="NSE",
    interval="D",  # From intervals response
    start_date="2024-01-01",
    end_date="2024-01-31"
)
print("Historical data:", history['data'])
```

### Notes

1. Always check supported intervals first using the intervals API
2. Use exact interval strings from intervals API response
3. All timestamps are in Unix epoch format
4. Prices and quantities are returned as numbers
5. Market depth always returns exactly 5 entries for both bids and asks
6. Empty market depth entries are filled with zeros
7. Date format for history API: YYYY-MM-DD
8. Rate limit: 10 requests per second
