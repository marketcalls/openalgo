# Scrip Margin Calculator

## Endpoint URL

This API Function Calculates Margin Requirements and Leverage for a Single Symbol with Automatic Lot Size Detection

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/margin/scrip
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/margin/scrip
Custom Domain:  POST https://<your-custom-domain>/api/v1/margin/scrip
```

## Overview

The Scrip Margin API provides detailed margin and leverage calculations for individual trading symbols. It offers several advanced features:

- **Dynamic Leverage Calculation**: Automatically calculates leverage based on current LTP and margin requirements
- **Automatic Lot Size Detection**: For derivatives (NFO/BFO/CDS/MCX), automatically fetches and uses the correct lot size
- **Per-Unit Margin Breakdown**: Returns margin per share/contract for easy scaling calculations
- **Graceful LTP Handling**: If LTP is unavailable (pre-market hours, permissions), returns margin data with null leverage
- **Multi-Broker Support**: Works with 24+ broker integrations
- **Product-Aware**: Calculates different margin requirements for MIS, NRML, and CNC products

## Basic Usage

### Example 1: Derivatives with Auto Lot Size

```json
{
    "apikey": "your_app_apikey",
    "symbol": "NIFTY26DEC24FUT",
    "exchange": "NFO",
    "product": "MIS"
}
```

The API automatically fetches lot size (50 for NIFTY) and calculates margin accordingly.

### Example 2: Equity with Default Quantity

```json
{
    "apikey": "your_app_apikey",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "product": "MIS"
}
```

For equities, defaults to quantity=1, providing per-share margin information.

### Example 3: User-Provided Quantity Override

```json
{
    "apikey": "your_app_apikey",
    "symbol": "NIFTY26DEC24FUT",
    "exchange": "NFO",
    "product": "MIS",
    "quantity": 100
}
```

User can override automatic lot size detection by providing explicit quantity.

## Request Parameters

| Parameter | Type    | Required | Default  | Description                                           | Example              |
|-----------|---------|----------|----------|-------------------------------------------------------|----------------------|
| apikey    | String  | Yes      | -        | API Key for authentication                            | "your_api_key"       |
| symbol    | String  | Yes      | -        | Trading symbol                                        | "NIFTY26DEC24FUT"    |
| exchange  | String  | Yes      | -        | Exchange (NSE, BSE, NFO, BFO, CDS, MCX)               | "NFO"                |
| product   | String  | Yes      | -        | Product type (MIS, NRML, CNC)                         | "MIS"                |
| quantity  | Integer | No       | Auto/1   | Quantity (Auto for derivatives, 1 for equity)         | 50                   |
| action    | String  | No       | "BUY"    | Action (BUY/SELL)                                     | "BUY"                |
| pricetype | String  | No       | "MARKET" | Price type (MARKET, LIMIT, SL, SL-M)                  | "MARKET"             |
| price     | String  | No       | "0"      | Price (required for LIMIT orders)                     | "24500.00"           |

### Quantity Resolution Priority

The API uses the following priority order to determine quantity:

1. **User-Provided Quantity** (Highest Priority): If you explicitly provide `quantity`, it will be used regardless of symbol type
2. **Auto Lot Size for Derivatives**: For NFO/BFO/CDS/MCX exchanges, automatically fetches lot size from database
3. **Default to 1 for Equities**: For NSE/BSE exchanges, defaults to quantity=1 for per-share calculations

## Response Format

### Success Response (200) - With LTP Available

```json
{
    "status": "success",
    "data": {
        "symbol": "NIFTY26DEC24FUT",
        "exchange": "NFO",
        "product": "MIS",
        "ltp": 24500.0,
        "margin_per_unit": 2450.0,
        "leverage": 10.0,
        "margin_percent": 10.0,
        "quantity": 50,
        "lot_size": 50,
        "total_margin_required": 122500.0,
        "margin_breakdown": {
            "span_margin": 0,
            "exposure_margin": 122500.0,
            "option_premium": 0,
            "additional_margin": 0
        }
    }
}
```

### Success Response (200) - LTP Unavailable

```json
{
    "status": "success",
    "data": {
        "symbol": "NIFTY26DEC24FUT",
        "exchange": "NFO",
        "product": "MIS",
        "ltp": null,
        "margin_per_unit": 2450.0,
        "leverage": null,
        "margin_percent": null,
        "quantity": 50,
        "lot_size": 50,
        "total_margin_required": 122500.0,
        "ltp_warning": "LTP unavailable - leverage and margin % cannot be calculated",
        "margin_breakdown": {
            "span_margin": 0,
            "exposure_margin": 122500.0,
            "option_premium": 0,
            "additional_margin": 0
        }
    }
}
```

### Error Response (400) - Validation Error

```json
{
    "status": "error",
    "message": "{'symbol': ['Missing data for required field.']}"
}
```

### Error Response (403) - Authentication Error

```json
{
    "status": "error",
    "message": "Invalid API key"
}
```

### Error Response (500) - Server Error

```json
{
    "status": "error",
    "message": "Failed to calculate margin: Broker API timeout"
}
```

## Response Fields

| Field                   | Type    | Description                                                      | Always Present |
|-------------------------|---------|------------------------------------------------------------------|----------------|
| status                  | String  | Response status ("success" or "error")                           | Yes            |
| data                    | Object  | Margin data object (only on success)                             | On success     |
| message                 | String  | Error message (only on error)                                    | On error       |

### Data Object Fields

| Field                   | Type    | Description                                                      | Always Present |
|-------------------------|---------|------------------------------------------------------------------|----------------|
| symbol                  | String  | Trading symbol                                                   | Yes            |
| exchange                | String  | Exchange code                                                    | Yes            |
| product                 | String  | Product type                                                     | Yes            |
| ltp                     | Float   | Last Traded Price (null if unavailable)                          | Yes            |
| margin_per_unit         | Float   | Margin required per share/contract                               | Yes            |
| leverage                | Float   | Calculated leverage (LTP / Margin Per Unit), null if LTP unavailable | Yes       |
| margin_percent          | Float   | Margin as percentage of LTP, null if LTP unavailable             | Yes            |
| quantity                | Integer | Resolved quantity used for calculation                           | Yes            |
| lot_size                | Integer | Lot size from database (null for equities)                       | Yes            |
| total_margin_required   | Float   | Total margin for the resolved quantity                           | Yes            |
| margin_breakdown        | Object  | Detailed margin components (broker-specific)                     | Yes            |
| ltp_warning             | String  | Warning message when LTP is unavailable                          | Conditional    |

### Margin Breakdown Fields (Broker-Specific)

Different brokers provide different margin components. Common fields include:

| Field              | Description                                    | Availability      |
|--------------------|------------------------------------------------|-------------------|
| span_margin        | SPAN margin requirement                        | Most brokers      |
| exposure_margin    | Exposure margin requirement                    | Most brokers      |
| option_premium     | Premium for options (debit/credit)             | For options       |
| additional_margin  | Additional margin (VaR, ELM, etc.)             | Some brokers      |

## Supported Exchanges

| Exchange Code | Description                      |
|---------------|----------------------------------|
| NSE           | National Stock Exchange (Equity) |
| BSE           | Bombay Stock Exchange (Equity)   |
| NFO           | NSE Futures & Options            |
| BFO           | BSE Futures & Options            |
| CDS           | Currency Derivatives             |
| MCX           | Multi Commodity Exchange         |

## Supported Product Types

| Product | Description                        | Typical Leverage      |
|---------|------------------------------------|----------------------|
| MIS     | Margin Intraday Square-off         | High (5-20x)         |
| NRML    | Normal (F&O - Carry Forward)       | Lower (2-5x)         |
| CNC     | Cash and Carry (Delivery)          | No leverage (1x)     |

## Supported Price Types

| Price Type | Description                       |
|------------|-----------------------------------|
| MARKET     | Market order                      |
| LIMIT      | Limit order                       |
| SL         | Stop Loss Limit order             |
| SL-M       | Stop Loss Market order            |

## Supported Actions

| Action | Description |
|--------|-------------|
| BUY    | Buy order   |
| SELL   | Sell order  |

## Important Notes

### 1. Automatic Lot Size Detection

For derivatives (NFO, BFO, CDS, MCX):
- API automatically fetches lot size from the token database
- Example: NIFTY futures automatically uses lot size of 50
- If lot size not found, logs warning and defaults to quantity=1

For equities (NSE, BSE):
- Defaults to quantity=1 for per-share margin calculation
- Users can override by providing explicit quantity

### 2. Leverage Calculation Formula

```
Leverage = LTP / Margin Per Unit
```

Example:
- LTP = 24,500
- Margin Per Unit = 2,450
- Leverage = 24,500 / 2,450 = 10x

```
Margin Percentage = (Margin Per Unit / LTP) × 100
```

Example:
- Margin % = (2,450 / 24,500) × 100 = 10%

### 3. Graceful LTP Handling

The API handles LTP unavailability gracefully:
- **When LTP is unavailable**: Returns margin data with `leverage=null`, `margin_percent=null`, and includes `ltp_warning`
- **Common scenarios**: Pre-market hours, post-market hours, insufficient data permissions
- **Benefit**: You still get accurate margin requirements even without LTP

### 4. Multi-Broker Support

Supports 24+ broker integrations including:
- Angel One, Zerodha, Dhan, Kotak Neo
- Firstock, Fyers, IIFL, 5paisa
- Upstox, Alice Blue, Motilal Oswal, Shoonya (Finvasia)
- And many more

Each broker may return slightly different margin components in `margin_breakdown`.

### 5. Product Type Impact

Margin requirements vary significantly by product:
- **MIS (Intraday)**: Highest leverage, lowest margin (must square-off by EOD)
- **NRML (Carry Forward)**: Lower leverage, higher margin (can carry overnight)
- **CNC (Delivery)**: No leverage for equities (requires full amount)

### 6. Symbol Format

Use OpenAlgo standard symbol format:
- **Equity**: "SBIN", "RELIANCE", "TCS", "HDFCBANK"
- **Futures**: "NIFTY26DEC24FUT", "BANKNIFTY26DEC24FUT"
- **Options**: "NIFTY26DEC2426000CE", "BANKNIFTY26DEC2448000PE"
- **Format Pattern**:
  - Futures: `{SYMBOL}{DDMMMYY}FUT`
  - Options: `{SYMBOL}{DDMMMYY}{STRIKE}{CE/PE}`

### 7. Rate Limiting

- Default: 10 requests per second (configurable via `API_RATE_LIMIT` environment variable)
- If rate limit is exceeded, you will receive a 429 (Too Many Requests) response
- Implement exponential backoff in your client for production use

### 8. Latency Tracking

All requests are automatically tracked in the latency monitoring system:
- Logs to `latency.db` with `order_type='SCRIP_MARGIN'`
- Tracks: RTT, validation latency, response latency, overhead, total latency
- Useful for performance monitoring and optimization

## Example Use Cases

### Use Case 1: Check NIFTY Futures Leverage (Auto Lot Size)

**Request:**
```json
{
    "apikey": "your_app_apikey",
    "symbol": "NIFTY26DEC24FUT",
    "exchange": "NFO",
    "product": "MIS"
}
```

**What Happens:**
- API automatically fetches lot size = 50
- Fetches current LTP (e.g., 24,500)
- Calculates margin for 50 units
- Returns leverage and per-unit margin

**Use Case:** Quickly check how much leverage you get on NIFTY futures with MIS

### Use Case 2: Calculate Equity Margin (Per Share)

**Request:**
```json
{
    "apikey": "your_app_apikey",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "product": "MIS"
}
```

**What Happens:**
- Defaults to quantity = 1 (per share calculation)
- Returns margin required per share
- You can multiply by desired quantity

**Use Case:** Find out how much margin needed per share of RELIANCE, then scale to your desired quantity

### Use Case 3: Compare MIS vs NRML Leverage

**Request 1 (MIS):**
```json
{
    "apikey": "your_app_apikey",
    "symbol": "BANKNIFTY26DEC24FUT",
    "exchange": "NFO",
    "product": "MIS"
}
```

**Request 2 (NRML):**
```json
{
    "apikey": "your_app_apikey",
    "symbol": "BANKNIFTY26DEC24FUT",
    "exchange": "NFO",
    "product": "NRML"
}
```

**What Happens:**
- Both use same lot size (auto-fetched)
- MIS typically shows 2-3x higher leverage than NRML
- Compare `leverage` and `margin_per_unit` fields

**Use Case:** Decide between intraday (MIS) vs carry-forward (NRML) based on margin availability

### Use Case 4: Custom Quantity Calculation

**Request:**
```json
{
    "apikey": "your_app_apikey",
    "symbol": "NIFTY26DEC24FUT",
    "exchange": "NFO",
    "product": "MIS",
    "quantity": 150
}
```

**What Happens:**
- Overrides default lot size (50) with user quantity (150)
- Calculates margin for 150 units (3 lots)
- Returns total margin and per-unit margin

**Use Case:** Calculate margin for multiple lots at once

## Error Codes and Messages

| HTTP Code | Error Message                                          | Cause                                    | Solution                                  |
|-----------|--------------------------------------------------------|------------------------------------------|-------------------------------------------|
| 400       | "{'apikey': ['Missing data for required field.']}"     | Missing apikey parameter                 | Include "apikey" in request body          |
| 400       | "{'symbol': ['Missing data for required field.']}"     | Missing symbol parameter                 | Include "symbol" in request body          |
| 400       | "{'exchange': ['Missing data for required field.']}"   | Missing exchange parameter               | Include "exchange" in request body        |
| 400       | "{'product': ['Missing data for required field.']}"    | Missing product parameter                | Include "product" in request body         |
| 400       | "Invalid product type: {product}"                      | Unsupported product type                 | Use MIS, NRML, or CNC                     |
| 400       | "Quantity must be a positive integer"                  | Invalid quantity value                   | Provide positive integer for quantity     |
| 403       | "Invalid API key"                                      | Wrong or expired API key                 | Check API key in OpenAlgo dashboard       |
| 403       | "API key is required"                                  | Missing API key                          | Include valid API key in request          |
| 500       | "Failed to calculate margin: {error}"                  | Broker API error or timeout              | Retry request, check broker connectivity  |
| 500       | "An unexpected error occurred"                         | Internal server error                    | Check logs, contact support if persists   |
| 429       | "Too Many Requests"                                    | Rate limit exceeded                      | Implement rate limiting in your client    |

## Testing Tips

### 1. Use Liquid Symbols for Testing

**Index Futures** (High liquidity, reliable data):
- `NIFTY26DEC24FUT` (NFO, lot: 50)
- `BANKNIFTY26DEC24FUT` (NFO, lot: 35)
- `FINNIFTY26DEC24FUT` (NFO, lot: 40)

**Equities** (Large caps, always liquid):
- `RELIANCE` (NSE)
- `TCS` (NSE)
- `HDFCBANK` (NSE)
- `INFY` (NSE)

**Index Options** (High volume):
- `NIFTY26DEC2424500CE` (NFO, lot: 50)
- `BANKNIFTY26DEC2448000PE` (NFO, lot: 35)

### 2. Test Different Product Types

```json
// High leverage intraday
{"product": "MIS"}

// Lower leverage carry forward
{"product": "NRML"}

// No leverage delivery
{"product": "CNC"}
```

Compare `leverage` values across different products for the same symbol.

### 3. Test Quantity Override

```json
// Let API auto-fetch lot size
{
    "symbol": "NIFTY26DEC24FUT",
    "exchange": "NFO",
    "product": "MIS"
    // quantity not provided - will use 50
}

// Override with custom quantity
{
    "symbol": "NIFTY26DEC24FUT",
    "exchange": "NFO",
    "product": "MIS",
    "quantity": 100
    // will use 100 instead of 50
}
```

Verify that `quantity` in response matches your expectation.

### 4. Test Pre-Market Hours

Test during pre-market hours (before 9:15 AM IST) to verify graceful LTP handling:
- Response should have `ltp: null`
- Response should have `leverage: null`
- Response should include `ltp_warning` field
- Margin data should still be present and valid

### 5. Verify Calculations

Manually verify the calculations:
```
Check: Leverage = LTP / Margin Per Unit
Check: Total Margin = Margin Per Unit × Quantity
Check: Margin % = (Margin Per Unit / LTP) × 100
```

### 6. Test Error Handling

```json
// Test missing parameters
{}

// Test invalid exchange
{"exchange": "INVALID"}

// Test invalid symbol
{"symbol": "DOESNOTEXIST", "exchange": "NSE"}

// Test invalid API key
{"apikey": "invalid_key"}
```

Verify appropriate error messages are returned.

## Rate Limiting

- **Default**: 10 requests per second (configurable via `API_RATE_LIMIT` environment variable)
- **429 Response**: Returned when rate limit exceeded
- **Best Practice**: Implement exponential backoff and request queuing in production
- **Recommendation**: For high-frequency applications, increase `API_RATE_LIMIT` appropriately

Example rate limit configuration:
```bash
# In .env file
API_RATE_LIMIT=50 per second
```

## Comparison: Scrip Margin API vs Basket Margin API

| Feature                      | Scrip Margin API                       | Basket Margin API                      |
|------------------------------|----------------------------------------|----------------------------------------|
| **Endpoint**                 | `/api/v1/margin/scrip`                 | `/api/v1/margin`                       |
| **Purpose**                  | Single symbol analysis                 | Multiple positions (basket/strategy)   |
| **Max Positions**            | 1                                      | 50                                     |
| **Auto Lot Size**            | ✅ Yes                                 | ❌ No (manual quantity required)       |
| **Leverage Calculation**     | ✅ Yes (automatic)                     | ❌ No                                  |
| **Margin Per Unit**          | ✅ Yes                                 | ❌ No                                  |
| **LTP Included**             | ✅ Yes                                 | ❌ No                                  |
| **Margin Benefit**           | N/A (single position)                  | ✅ Yes (hedging benefit)               |
| **Use Case**                 | Quick symbol lookup, scaling decisions | Strategy margin, basket orders         |
| **Response Fields**          | 11+ fields (includes leverage, LTP)    | 4-6 fields (aggregated margin only)    |

### When to Use Each API

**Use Scrip Margin API when:**
- You want to analyze a single symbol
- You need leverage information
- You want automatic lot size detection
- You need per-unit margin for scaling decisions
- You're building a symbol search/analysis tool

**Use Basket Margin API when:**
- You're placing a basket order (multiple positions)
- You need margin benefit calculation for hedged strategies
- You're calculating margin for complex strategies (Iron Condor, Straddle, etc.)
- You need total margin for a complete strategy

## Security Notes

- Always use HTTPS in production
- Never share your API key publicly
- Store API keys securely (environment variables, secrets manager)
- Rotate API keys periodically
- Monitor API usage for anomalies
- Use rate limiting to prevent abuse
- Validate all user inputs before making API calls

## Performance Considerations

- **Latency**: Typical response time is 100-300ms (includes broker API call + LTP fetch)
- **Caching**: Consider caching lot sizes and symbol info locally for frequently used symbols
- **Batch Processing**: For analyzing multiple symbols, consider parallel requests (respect rate limits)
- **LTP Dependency**: If LTP fails, margin calculation still succeeds (graceful degradation)

## Support and Troubleshooting

For issues or questions:
1. Check the error message for specific guidance
2. Verify API key is valid and active
3. Ensure symbol format matches OpenAlgo standard
4. Check broker connectivity and permissions
5. Review application logs for detailed error traces
6. Consult OpenAlgo documentation and community forums

## API Changelog

**Version 1.0** (Initial Release)
- Dynamic leverage calculation
- Automatic lot size detection for derivatives
- Per-unit margin breakdown
- Graceful LTP unavailability handling
- Multi-broker support (24+ brokers)
- Comprehensive error handling
- Latency tracking integration
