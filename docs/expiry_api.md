# Expiry API

The Expiry API allows you to retrieve expiry dates for F&O (Futures and Options) instruments for a given underlying symbol. This API helps you get all available expiry dates for futures or options contracts of a specific underlying asset.

## Endpoint

**Local Host**: `POST http://127.0.0.1:5000/api/v1/expiry`  
**Ngrok Domain**: `POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/expiry`  
**Custom Domain**: `POST https://<your-custom-domain>/api/v1/expiry`

## Request Format

### Headers
- `Content-Type: application/json`

### Body Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `apikey` | string | Yes | Your OpenAlgo API key for authentication |
| `symbol` | string | Yes | Underlying symbol (e.g., NIFTY, BANKNIFTY, RELIANCE) |
| `exchange` | string | Yes | Exchange code (NFO, BFO, MCX, CDS) |
| `instrumenttype` | string | Yes | Type of instrument - "futures" or "options" |

### Supported Exchanges and Instruments

| Exchange | Futures | Options | Examples |
|----------|---------|---------|----------|
| NFO | ✓ | ✓ | NIFTY, BANKNIFTY, RELIANCE |
| BFO | ✓ | ✓ | SENSEX, BANKEX |
| MCX | ✓ | ✓ | GOLD, SILVER, CRUDE |
| CDS | ✓ | ✓ | USDINR, EURINR |

## Request and Response Examples

### NIFTY Futures (NFO)

**Request:**
```json
{
    "apikey": "openalgo-api-key",
    "symbol": "NIFTY",
    "exchange": "NFO",
    "instrumenttype": "futures"
}
```

**Response:**
```json
{
    "data": [
        "31-JUL-25",
        "28-AUG-25",
        "25-SEP-25"
    ],
    "message": "Found 3 expiry dates for NIFTY futures in NFO",
    "status": "success"
}
```

### NIFTY Options (NFO)

**Request:**
```json
{
    "apikey": "openalgo-api-key",
    "symbol": "NIFTY",
    "exchange": "NFO",
    "instrumenttype": "options"
}
```

**Response:**
```json
{
    "data": [
        "10-JUL-25",
        "17-JUL-25",
        "24-JUL-25",
        "31-JUL-25",
        "07-AUG-25",
        "28-AUG-25",
        "25-SEP-25",
        "24-DEC-25",
        "26-MAR-26",
        "25-JUN-26",
        "31-DEC-26",
        "24-JUN-27",
        "30-DEC-27",
        "29-JUN-28",
        "28-DEC-28",
        "28-JUN-29",
        "27-DEC-29",
        "25-JUN-30"
    ],
    "message": "Found 18 expiry dates for NIFTY options in NFO",
    "status": "success"
}
```

### GOLD Futures (MCX)

**Request:**
```json
{
    "apikey": "openalgo-api-key",
    "symbol": "GOLD",
    "exchange": "MCX",
    "instrumenttype": "futures"
}
```

**Response:**
```json
{
    "data": [
        "05-AUG-25",
        "03-OCT-25",
        "05-DEC-25",
        "05-FEB-26",
        "02-APR-26",
        "05-JUN-26"
    ],
    "message": "Found 6 expiry dates for GOLD futures in MCX",
    "status": "success"
}
```

### USDINR Futures (CDS)

**Request:**
```json
{
    "apikey": "openalgo-api-key",
    "symbol": "USDINR",
    "exchange": "CDS",
    "instrumenttype": "futures"
}
```

**Response:**
```json
{
    "data": [
        "11-JUL-25",
        "18-JUL-25",
        "25-JUL-25",
        "29-JUL-25",
        "01-AUG-25",
        "08-AUG-25",
        "14-AUG-25",
        "22-AUG-25",
        "26-AUG-25",
        "29-AUG-25",
        "04-SEP-25",
        "12-SEP-25",
        "19-SEP-25",
        "26-SEP-25",
        "29-OCT-25",
        "26-NOV-25",
        "29-DEC-25",
        "28-JAN-26",
        "25-FEB-26",
        "27-MAR-26",
        "28-APR-26",
        "27-MAY-26",
        "26-JUN-26"
    ],
    "message": "Found 23 expiry dates for USDINR futures in CDS",
    "status": "success"
}
```

### Error Response

```json
{
    "status": "error",
    "message": "Invalid openalgo apikey"
}
```

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Response status: "success" or "error" |
| `message` | string | Descriptive message about the response |
| `data` | array | Array of expiry dates in DD-MMM-YY format, sorted chronologically |

## Example Usage

### Get NIFTY Options Expiry Dates

```bash
curl -X POST "http://127.0.0.1:5000/api/v1/expiry" \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "openalgo-api-key",
    "symbol": "NIFTY",
    "exchange": "NFO",
    "instrumenttype": "options"
  }'
```

### Get BANKNIFTY Futures Expiry Dates

```bash
curl -X POST "http://127.0.0.1:5000/api/v1/expiry" \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "openalgo-api-key",
    "symbol": "BANKNIFTY",
    "exchange": "NFO",
    "instrumenttype": "futures"
  }'
```

### Get MCX GOLD Futures Expiry Dates

```bash
curl -X POST "http://127.0.0.1:5000/api/v1/expiry" \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "openalgo-api-key",
    "symbol": "GOLD",
    "exchange": "MCX",
    "instrumenttype": "futures"
  }'
```

### Get CDS USDINR Futures Expiry Dates

```bash
curl -X POST "http://127.0.0.1:5000/api/v1/expiry" \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "openalgo-api-key",
    "symbol": "USDINR",
    "exchange": "CDS",
    "instrumenttype": "futures"
  }'
```

## Python Example

```python
import requests
import json

# API endpoint
url = "http://127.0.0.1:5000/api/v1/expiry"

# Request payload
payload = {
    "apikey": "openalgo-api-key",
    "symbol": "NIFTY",
    "exchange": "NFO",
    "instrumenttype": "options"
}

# Make the request
response = requests.post(url, json=payload)

# Parse the response
if response.status_code == 200:
    data = response.json()
    if data['status'] == 'success':
        print(f"Found {len(data['data'])} expiry dates:")
        for expiry in data['data']:
            print(f"  {expiry}")
    else:
        print(f"Error: {data['message']}")
else:
    print(f"HTTP Error: {response.status_code}")
```

## JavaScript Example

```javascript
const getExpiryDates = async () => {
    const url = "http://127.0.0.1:5000/api/v1/expiry";
    
    const payload = {
        apikey: "openalgo-api-key",
        symbol: "NIFTY",
        exchange: "NFO",
        instrumenttype: "options"
    };
    
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload)
        });
        
        const data = await response.json();
        
        if (data.status === 'success') {
            console.log(`Found ${data.data.length} expiry dates:`);
            data.data.forEach(expiry => {
                console.log(`  ${expiry}`);
            });
        } else {
            console.error(`Error: ${data.message}`);
        }
    } catch (error) {
        console.error('Request failed:', error);
    }
};

// Call the function
getExpiryDates();
```

## Error Codes

| HTTP Status | Error Type | Description |
|-------------|------------|-------------|
| 200 | Success | Request processed successfully |
| 400 | Bad Request | Invalid request parameters |
| 403 | Forbidden | Invalid API key |
| 500 | Server Error | Internal server error |

## Error Messages

| Message | Description |
|---------|-------------|
| "Invalid openalgo apikey" | The provided API key is invalid |
| "Symbol parameter is required and cannot be empty" | Symbol field is missing or empty |
| "Exchange parameter is required and cannot be empty" | Exchange field is missing or empty |
| "Instrumenttype parameter is required and cannot be empty" | Instrumenttype field is missing or empty |
| "Instrumenttype must be either 'futures' or 'options'" | Invalid instrumenttype value |
| "Exchange must be one of: NFO, BFO, MCX, CDS" | Invalid exchange value |
| "No expiry dates found for [symbol] [instrumenttype] in [exchange]" | No matching expiry dates found |

## Notes

- Expiry dates are returned in DD-MMM-YY format (e.g., "31-JUL-25")
- Dates are sorted chronologically from earliest to latest
- The API uses exact symbol matching to avoid confusion (e.g., "NIFTY" won't match "BANKNIFTY")
- Different exchanges use different instrument type codes internally but the API accepts standardized "futures" and "options" parameters
- Rate limiting is applied as per your OpenAlgo server configuration

## Rate Limits

This API endpoint is subject to rate limiting. The default rate limit is 10 requests per second per API key, but this may vary based on your OpenAlgo server configuration.

## Common Use Cases

1. **Options Strategy Planning**: Get all available expiry dates for options to plan multi-leg strategies
2. **Futures Trading**: Identify available futures contracts for different expiry months
3. **Calendar Spreads**: Find suitable expiry dates for calendar spread strategies
4. **Risk Management**: Understand contract availability for hedging purposes
5. **Market Making**: Get comprehensive expiry date information for market making activities

## Integration Tips

- Cache the expiry dates locally to reduce API calls
- Filter expiry dates based on your trading strategy requirements
- Consider time to expiry when selecting contracts
- Use the chronologically sorted expiry dates for time-based analysis
- Validate the symbol format according to OpenAlgo symbol conventions before making API calls