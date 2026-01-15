# Multi Quotes

## Endpoint URL

This API Function fetches quotes for multiple symbols from the Broker in a single API call

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/multiquotes
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/multiquotes
Custom Domain:  POST https://<your-custom-domain>/api/v1/multiquotes
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "symbols": [
    {
      "symbol": "SBIN",
      "exchange": "NSE"
    },
    {
      "symbol": "NIFTY25NOV25FUT",
      "exchange": "NFO"
    },
    {
      "symbol": "INFY",
      "exchange": "BSE"
    }
  ]
}
```

## Sample API Response

```json
{
  "status": "success",
  "results": [
    {
      "symbol": "SBIN",
      "exchange": "NSE",
      "data": {
        "ask": 972.6,
        "bid": 0,
        "high": 980.6,
        "low": 971.05,
        "ltp": 972.6,
        "oi": 0,
        "open": 979.7,
        "prev_close": 981.55,
        "volume": 5377241
      }
    },
    {
      "symbol": "NIFTY25NOV25FUT",
      "exchange": "NFO",
      "data": {
        "ask": 26074.6,
        "bid": 26070.2,
        "high": 26195,
        "low": 26061.3,
        "ltp": 26074,
        "oi": 0,
        "open": 26136.3,
        "prev_close": 26220.8,
        "volume": 8618175
      }
    },
    {
      "symbol": "INFY",
      "exchange": "BSE",
      "data": {
        "ask": 0,
        "bid": 0,
        "high": 1551.5,
        "low": 1527.5,
        "ltp": 1544.6,
        "oi": 0,
        "open": 1530,
        "prev_close": 1536.75,
        "volume": 699948
      }
    }
  ]
}
```

## Request Fields

| Parameters | Description                      | Mandatory/Optional | Default Value |
| ---------- | -------------------------------- | ------------------ | ------------- |
| apikey     | App API key                      | Mandatory          | -             |
| symbols    | Array of symbol/exchange objects | Mandatory          | -             |

### Symbol Object Fields

| Parameters | Description    | Mandatory/Optional | Default Value |
| ---------- | -------------- | ------------------ | ------------- |
| symbol     | Trading symbol | Mandatory          | -             |
| exchange   | Exchange code  | Mandatory          | -             |

## Response Fields

| Field   | Type   | Description                                          |
| ------- | ------ | ---------------------------------------------------- |
| status  | string | Response status (success/error)                      |
| results | array  | Array of quote results for each requested symbol     |

### Result Object Fields

| Field    | Type   | Description                              |
| -------- | ------ | ---------------------------------------- |
| symbol   | string | Trading symbol                           |
| exchange | string | Exchange code                            |
| data     | object | Quote data object (see Quote Data Fields)|

### Quote Data Fields

| Field       | Type   | Description                  |
| ----------- | ------ | ---------------------------- |
| bid         | number | Best bid price               |
| ask         | number | Best ask price               |
| open        | number | Opening price                |
| high        | number | High price                   |
| low         | number | Low price                    |
| ltp         | number | Last traded price            |
| oi          | number | Open Interest                |
| prev\_close | number | Previous day's closing price |
| volume      | number | Total traded volume          |

## Important Notes

- **Batch Limit**: The maximum number of symbols per request depends on the broker's API limitations
  - **Fyers**: Automatically processes in batches of 50 symbols. You can send 500+ symbols and they will be processed automatically in multiple API calls
  - **Other brokers**: Check broker documentation for specific limits
- **Automatic Batching**: Fyers implementation includes intelligent batching
  - Requests with ≤50 symbols: Single API call
  - Requests with >50 symbols: Automatically split into batches of 50
  - 100ms delay between batches to prevent rate limiting
  - Example: 500 symbols = 10 batches processed automatically
- **Performance**: Multi quotes API is more efficient than making multiple individual quote requests
- **Broker Support**:
  - Fyers: Uses native multi-symbol API with automatic batching for any number of symbols
  - Other brokers: Automatically falls back to fetching quotes individually
- **Error Handling**: If individual symbols fail, the response will include error information for those specific symbols while still returning data for successful symbols
- **Rate Limiting**: Same rate limits apply as single quote API (default: 10 requests per second)

## Use Cases

1. **Portfolio Monitoring**: Fetch quotes for all holdings in a single request
2. **Watchlist Updates**: Get real-time quotes for watchlist symbols efficiently
3. **Multi-Asset Trading**: Monitor positions across different exchanges (NSE, BSE, NFO, etc.)
4. **Strategy Execution**: Get quotes for multiple instruments before executing complex strategies

## Example Usage Scenarios

### Fetching Portfolio Quotes
```json
{
  "apikey": "<your_app_apikey>",
  "symbols": [
    {"symbol": "SBIN", "exchange": "NSE"},
    {"symbol": "RELIANCE", "exchange": "NSE"},
    {"symbol": "TCS", "exchange": "NSE"},
    {"symbol": "INFY", "exchange": "BSE"}
  ]
}
```

### Monitoring Derivatives and Cash
```json
{
  "apikey": "<your_app_apikey>",
  "symbols": [
    {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
    {"symbol": "NIFTY25DEC24FUT", "exchange": "NFO"},
    {"symbol": "NIFTY25DEC2425000CE", "exchange": "NFO"},
    {"symbol": "NIFTY25DEC2425000PE", "exchange": "NFO"}
  ]
}
```

## Error Response

In case of an error, the API will return:

```json
{
  "status": "error",
  "message": "Error description"
}
```

### Common Error Scenarios

| Error Message                  | Cause                                    | Solution                                    |
| ------------------------------ | ---------------------------------------- | ------------------------------------------- |
| Invalid openalgo apikey        | Invalid or expired API key               | Check your API key                          |
| Validation error               | Missing required fields or invalid format| Verify request format                       |
| Failed to fetch multiquotes    | Broker API error                         | Check broker connectivity                   |
| Too many symbols               | Exceeded broker's limit                  | Split request into multiple calls per broker limit |
