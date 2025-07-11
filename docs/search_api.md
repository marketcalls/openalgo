# Symbol Search API

The Symbol Search API allows you to search for trading symbols across different exchanges. This API is useful for finding specific instruments, including stocks, futures, and options contracts.

## Endpoint

```
POST /api/v1/search
```

## Request Headers

| Header | Required | Description |
|--------|----------|-------------|
| Content-Type | Yes | application/json |

## Request Body

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| apikey | string | Yes | Your OpenAlgo API key |
| query | string | Yes | Search query (symbol name, partial name, or option chain) |
| exchange | string | No | Exchange filter (NSE, BSE, NFO, MCX, etc.) |

## Response

### Success Response (200 OK)

```json
{
    "status": "success",
    "message": "Found X matching symbols",
    "data": [
        {
            "symbol": "string",
            "brsymbol": "string",
            "name": "string",
            "exchange": "string",
            "brexchange": "string",
            "token": "string",
            "expiry": "string",
            "strike": number,
            "lotsize": number,
            "instrumenttype": "string",
            "tick_size": number
        }
    ]
}
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | Status of the request (success/error) |
| message | string | Descriptive message about the result |
| data | array | Array of matching symbols |
| symbol | string | Trading symbol |
| brsymbol | string | Broker-specific symbol format |
| name | string | Company/instrument name |
| exchange | string | Exchange code |
| brexchange | string | Broker-specific exchange code |
| token | string | Unique instrument token |
| expiry | string | Expiry date (for derivatives) |
| strike | number | Strike price (for options) |
| lotsize | number | Lot size for the instrument |
| instrumenttype | string | Type of instrument (EQ, OPTIDX, etc.) |
| tick_size | number | Minimum price movement |

### Error Response

```json
{
    "status": "error",
    "message": "Error description"
}
```

## Error Codes

| Code | Description |
|------|-------------|
| 400 | Bad Request - Invalid parameters |
| 403 | Forbidden - Invalid API key |
| 500 | Internal Server Error |

## Examples

### Example 1: Search for Options Contracts

**Request:**
```bash
curl -X POST http://127.0.0.1:5000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "your_api_key_here",
    "query": "NIFTY 25000 JUL CE",
    "exchange": "NFO"
  }'
```

**Response:**
```json
{
  "data": [
    {
      "brexchange": "NFO",
      "brsymbol": "NIFTY17JUL2525000CE",
      "exchange": "NFO",
      "expiry": "17-JUL-25",
      "instrumenttype": "OPTIDX",
      "lotsize": 75,
      "name": "NIFTY",
      "strike": 25000,
      "symbol": "NIFTY17JUL2525000CE",
      "tick_size": 0.05,
      "token": "47275"
    },
    {
      "brexchange": "NFO",
      "brsymbol": "FINNIFTY31JUL2525000CE",
      "exchange": "NFO",
      "expiry": "31-JUL-25",
      "instrumenttype": "OPTIDX",
      "lotsize": 65,
      "name": "FINNIFTY",
      "strike": 25000,
      "symbol": "FINNIFTY31JUL2525000CE",
      "tick_size": 0.05,
      "token": "54763"
    },
    {
      "brexchange": "NFO",
      "brsymbol": "NIFTY31JUL2525000CE",
      "exchange": "NFO",
      "expiry": "31-JUL-25",
      "instrumenttype": "OPTIDX",
      "lotsize": 75,
      "name": "NIFTY",
      "strike": 25000,
      "symbol": "NIFTY31JUL2525000CE",
      "tick_size": 0.05,
      "token": "55799"
    },
    {
      "brexchange": "NFO",
      "brsymbol": "NIFTY03JUL2525000CE",
      "exchange": "NFO",
      "expiry": "03-JUL-25",
      "instrumenttype": "OPTIDX",
      "lotsize": 75,
      "name": "NIFTY",
      "strike": 25000,
      "symbol": "NIFTY03JUL2525000CE",
      "tick_size": 0.05,
      "token": "56699"
    },
    {
      "brexchange": "NFO",
      "brsymbol": "NIFTY10JUL2525000CE",
      "exchange": "NFO",
      "expiry": "10-JUL-25",
      "instrumenttype": "OPTIDX",
      "lotsize": 75,
      "name": "NIFTY",
      "strike": 25000,
      "symbol": "NIFTY10JUL2525000CE",
      "tick_size": 0.05,
      "token": "40015"
    },
    {
      "brexchange": "NFO",
      "brsymbol": "NIFTY24JUL2525000CE",
      "exchange": "NFO",
      "expiry": "24-JUL-25",
      "instrumenttype": "OPTIDX",
      "lotsize": 75,
      "name": "NIFTY",
      "strike": 25000,
      "symbol": "NIFTY24JUL2525000CE",
      "tick_size": 0.05,
      "token": "49487"
    }
  ],
  "message": "Found 6 matching symbols",
  "status": "success"
}
```

### Example 2: Search for Equity Symbols

**Request:**
```bash
curl -X POST http://127.0.0.1:5000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "your_api_key_here",
    "query": "TATA",
    "exchange": "NSE"
  }'
```

**Response:**
```json
{
  "data": [
    {
      "brexchange": "NSE",
      "brsymbol": "TATAINVEST-EQ",
      "exchange": "NSE",
      "expiry": "",
      "instrumenttype": "",
      "lotsize": 1,
      "name": "TATAINVEST",
      "strike": -0.01,
      "symbol": "TATAINVEST",
      "tick_size": 0.5,
      "token": "1621"
    },
    {
      "brexchange": "NSE",
      "brsymbol": "TATAELXSI-EQ",
      "exchange": "NSE",
      "expiry": "",
      "instrumenttype": "",
      "lotsize": 1,
      "name": "TATAELXSI",
      "strike": -0.01,
      "symbol": "TATAELXSI",
      "tick_size": 0.5,
      "token": "3411"
    },
    {
      "brexchange": "NSE",
      "brsymbol": "TATATECH-EQ",
      "exchange": "NSE",
      "expiry": "",
      "instrumenttype": "",
      "lotsize": 1,
      "name": "TATATECH",
      "strike": -0.01,
      "symbol": "TATATECH",
      "tick_size": 0.05,
      "token": "20293"
    },
    {
      "brexchange": "NSE",
      "brsymbol": "TATASTEEL-EQ",
      "exchange": "NSE",
      "expiry": "",
      "instrumenttype": "",
      "lotsize": 1,
      "name": "TATASTEEL",
      "strike": -0.01,
      "symbol": "TATASTEEL",
      "tick_size": 0.01,
      "token": "3499"
    },
    {
      "brexchange": "NSE",
      "brsymbol": "TATAGOLD-EQ",
      "exchange": "NSE",
      "expiry": "",
      "instrumenttype": "",
      "lotsize": 1,
      "name": "TATAGOLD",
      "strike": -0.01,
      "symbol": "TATAGOLD",
      "tick_size": 0.01,
      "token": "21401"
    },
    {
      "brexchange": "NSE",
      "brsymbol": "TATACHEM-EQ",
      "exchange": "NSE",
      "expiry": "",
      "instrumenttype": "",
      "lotsize": 1,
      "name": "TATACHEM",
      "strike": -0.01,
      "symbol": "TATACHEM",
      "tick_size": 0.05,
      "token": "3405"
    },
    {
      "brexchange": "NSE",
      "brsymbol": "TATACONSUM-EQ",
      "exchange": "NSE",
      "expiry": "",
      "instrumenttype": "",
      "lotsize": 1,
      "name": "TATACONSUM",
      "strike": -0.01,
      "symbol": "TATACONSUM",
      "tick_size": 0.1,
      "token": "3432"
    },
    {
      "brexchange": "NSE",
      "brsymbol": "TATAPOWER-EQ",
      "exchange": "NSE",
      "expiry": "",
      "instrumenttype": "",
      "lotsize": 1,
      "name": "TATAPOWER",
      "strike": -0.01,
      "symbol": "TATAPOWER",
      "tick_size": 0.05,
      "token": "3426"
    },
    {
      "brexchange": "NSE",
      "brsymbol": "TATACOMM-EQ",
      "exchange": "NSE",
      "expiry": "",
      "instrumenttype": "",
      "lotsize": 1,
      "name": "TATACOMM",
      "strike": -0.01,
      "symbol": "TATACOMM",
      "tick_size": 0.1,
      "token": "3721"
    },
    {
      "brexchange": "NSE",
      "brsymbol": "TATAMOTORS-EQ",
      "exchange": "NSE",
      "expiry": "",
      "instrumenttype": "",
      "lotsize": 1,
      "name": "TATAMOTORS",
      "strike": -0.01,
      "symbol": "TATAMOTORS",
      "tick_size": 0.05,
      "token": "3456"
    }
  ],
  "message": "Found 10 matching symbols",
  "status": "success"
}
```

### Example 3: Search Without Exchange Filter

**Request:**
```bash
curl -X POST http://127.0.0.1:5000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "your_api_key_here",
    "query": "RELIANCE"
  }'
```

This will return all symbols matching "RELIANCE" across all exchanges.

## Notes

1. The search is case-insensitive
2. Partial matches are supported
3. For options, you can search using various formats:
   - Symbol with strike and type: "NIFTY 25000 CE"
   - Symbol with expiry: "NIFTY JUL"
   - Complete option chain: "NIFTY 25000 JUL CE"
4. The exchange parameter is optional but recommended for faster and more accurate results
5. Empty or missing query parameter will return an error
6. The API uses the same search logic as the web interface at `/search/token`

## Rate Limiting

This endpoint is subject to the rate limit specified in your environment configuration (default: 10 requests per second).

## Common Use Cases

1. **Finding Option Contracts**: Search for specific strike prices and expiries
2. **Symbol Lookup**: Find the exact trading symbol for a company
3. **Token Retrieval**: Get the instrument token required for other API calls
4. **Lot Size Information**: Retrieve lot sizes for F&O instruments
5. **Exchange Validation**: Verify if a symbol is available on a specific exchange