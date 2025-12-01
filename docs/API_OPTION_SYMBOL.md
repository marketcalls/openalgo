# Option Symbol API Documentation

## Overview

The **Option Symbol API** (`/api/v1/optionsymbol`) helps you fetch option contract symbols dynamically based on the underlying asset, expiry date, and strike price offset from ATM (At-The-Money).

This API is useful for:
- **Automated option trading strategies** that need to select strikes relative to ATM
- **Option chain analysis** by fetching multiple strikes programmatically
- **Strategy builders** that require dynamic strike selection based on market conditions

## Endpoint

```
POST /api/v1/optionsymbol
```

## Request Parameters

| Parameter | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `apikey` | string | Yes | OpenAlgo API key for authentication | `"abc123xyz"` |
| `strategy` | string | Yes | Strategy name for tracking | `"iron_condor"` |
| `underlying` | string | Yes | Underlying symbol (can include expiry) | `"NIFTY"` or `"NIFTY28NOV24FUT"` |
| `exchange` | string | Yes | Exchange code | `"NSE_INDEX"`, `"NSE"`, `"NFO"`, `"BSE_INDEX"`, `"BSE"`, `"BFO"` |
| `expiry_date` | string | No | Expiry date in DDMMMYY format | `"28NOV24"`, `"31JAN25"` |
| `strike_int` | integer | Yes | Strike price interval | `50` (NIFTY), `100` (BANKNIFTY), `10` (Equity) |
| `offset` | string | Yes | Strike offset from ATM | `"ATM"`, `"ITM1"` to `"ITM50"`, `"OTM1"` to `"OTM50"` |
| `option_type` | string | Yes | Option type | `"CE"` (Call) or `"PE"` (Put) |

### Parameter Details

#### `underlying`
Can be provided in two formats:
1. **Base symbol only**: `"NIFTY"`, `"BANKNIFTY"`, `"RELIANCE"`
   - Requires `expiry_date` parameter
2. **Symbol with embedded expiry**: `"NIFTY28NOV24FUT"`, `"RELIANCE31JAN25FUT"`
   - Expiry is automatically extracted, `expiry_date` parameter is optional

#### `exchange`
Maps to option exchange automatically:
- `NSE` or `NSE_INDEX` → Options on `NFO`
- `BSE` or `BSE_INDEX` → Options on `BFO`
- `MCX` → Options on `MCX`
- `CDS` → Options on `CDS`

#### `strike_int`
Strike price interval varies by underlying:
- **NIFTY**: 50
- **BANKNIFTY**: 100
- **FINNIFTY**: 50
- **MIDCPNIFTY**: 25
- **Equity options**: 2.5, 5, 10 (varies by price)

**Note**: This parameter is **required** as strike intervals differ across symbols.

#### `offset`
Offset from ATM strike:
- **ATM**: At-The-Money strike
- **ITM1-ITM50**: In-The-Money strikes (1 to 50 strikes away)
- **OTM1-OTM50**: Out-of-The-Money strikes (1 to 50 strikes away)

**Logic**:
- For **Call (CE)**:
  - ITM = Lower strikes (ATM - N × strike_int)
  - OTM = Higher strikes (ATM + N × strike_int)
- For **Put (PE)**:
  - ITM = Higher strikes (ATM + N × strike_int)
  - OTM = Lower strikes (ATM - N × strike_int)

## How It Works

1. **Parse Underlying**: Extracts base symbol and expiry date
2. **Fetch LTP**: Gets Last Traded Price of underlying from broker API
3. **Calculate ATM**: Rounds LTP to nearest strike interval
   - Formula: `ATM = round(LTP / strike_int) × strike_int`
4. **Calculate Target Strike**: Applies offset to ATM
5. **Construct Symbol**: Creates option symbol in OpenAlgo format
6. **Query Database**: Finds symbol in master contract database
7. **Return Details**: Returns full option contract details

## Response Format

### Success Response (200)

```json
{
  "status": "success",
  "symbol": "NIFTY28NOV2424000CE",
  "exchange": "NFO",
  "lotsize": 25,
  "tick_size": 0.05,
  "underlying_ltp": 23987.50
}
```

### Error Response (400) - Validation Error

```json
{
  "status": "error",
  "message": "Validation error",
  "errors": {
    "offset": ["Offset must be ATM, ITM1-ITM50, or OTM1-OTM50"]
  }
}
```

### Error Response (400) - Missing Expiry

```json
{
  "status": "error",
  "message": "Expiry date required. Provide via expiry_date parameter or embed in underlying (e.g., NIFTY28OCT25FUT)."
}
```

### Error Response (403) - Invalid API Key

```json
{
  "status": "error",
  "message": "Invalid openalgo apikey"
}
```

### Error Response (404) - Symbol Not Found

```json
{
  "status": "error",
  "message": "Option symbol NIFTY28NOV2425500CE not found in NFO. Symbol may not exist or master contract needs update."
}
```

### Error Response (500) - LTP Fetch Failed

```json
{
  "status": "error",
  "message": "Failed to fetch LTP for NIFTY. Insufficient permissions"
}
```

### Error Response (500) - LTP Not Available

```json
{
  "status": "error",
  "message": "Could not determine LTP for NIFTY."
}
```

## Examples

### Example 1: NIFTY ATM Call Option

**Request:**
```bash
curl -X POST http://127.0.0.1:5000/api/v1/optionsymbol \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "your_api_key",
    "strategy": "nifty_weekly",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "28NOV24",
    "strike_int": 50,
    "offset": "ATM",
    "option_type": "CE"
  }'
```

**Scenario:**
- Current NIFTY LTP: 23,987.50
- ATM Strike: 24,000 (rounded to nearest 50)
- Target Strike: 24,000 (ATM)
- Result: `NIFTY28NOV2424000CE`

### Example 2: NIFTY ITM2 Put Option

**Request:**
```json
{
  "apikey": "your_api_key",
  "strategy": "nifty_weekly",
  "underlying": "NIFTY",
  "exchange": "NSE_INDEX",
  "expiry_date": "28NOV24",
  "strike_int": 50,
  "offset": "ITM2",
  "option_type": "PE"
}
```

**Scenario:**
- Current NIFTY LTP: 23,987.50
- ATM Strike: 24,000
- Target Strike: 24,100 (ATM + 2 × 50) [For PE, ITM = Higher]
- Result: `NIFTY28NOV2424100PE`

### Example 3: BANKNIFTY OTM3 Call Option

**Request:**
```json
{
  "apikey": "your_api_key",
  "strategy": "bank_nifty_strategy",
  "underlying": "BANKNIFTY",
  "exchange": "NSE_INDEX",
  "expiry_date": "28NOV24",
  "strike_int": 100,
  "offset": "OTM3",
  "option_type": "CE"
}
```

**Scenario:**
- Current BANKNIFTY LTP: 51,287.50
- ATM Strike: 51,300 (rounded to nearest 100)
- Target Strike: 51,600 (ATM + 3 × 100) [For CE, OTM = Higher]
- Result: `BANKNIFTY28NOV2451600CE`

### Example 4: Underlying with Embedded Expiry

**Request:**
```json
{
  "apikey": "your_api_key",
  "strategy": "futures_options",
  "underlying": "NIFTY28NOV24FUT",
  "exchange": "NFO",
  "strike_int": 50,
  "offset": "ITM5",
  "option_type": "CE"
}
```

**Scenario:**
- Underlying: `NIFTY28NOV24FUT`
- Extracted Base: `NIFTY`
- Extracted Expiry: `28NOV24`
- No `expiry_date` parameter needed
- LTP fetched from NIFTY index (not future)
- Result: Appropriate option symbol based on NIFTY spot price

### Example 5: Equity Option (RELIANCE)

**Request:**
```json
{
  "apikey": "your_api_key",
  "strategy": "equity_options",
  "underlying": "RELIANCE",
  "exchange": "NSE",
  "expiry_date": "28NOV24",
  "strike_int": 10,
  "offset": "OTM2",
  "option_type": "PE"
}
```

**Scenario:**
- Current RELIANCE LTP: 2,847.50
- ATM Strike: 2,850 (rounded to nearest 10)
- Target Strike: 2,830 (ATM - 2 × 10) [For PE, OTM = Lower]
- Result: `RELIANCE28NOV242830PE`

## Strike Offset Reference Table

For NIFTY with LTP = 23,987.50, strike_int = 50, ATM = 24,000:

| Offset | CE Strike | PE Strike | CE Moneyness | PE Moneyness |
|--------|-----------|-----------|--------------|--------------|
| ITM5   | 23,750    | 24,250    | Deep ITM     | Deep ITM     |
| ITM3   | 23,850    | 24,150    | ITM          | ITM          |
| ITM1   | 23,950    | 24,050    | Slightly ITM | Slightly ITM |
| ATM    | 24,000    | 24,000    | ATM          | ATM          |
| OTM1   | 24,050    | 23,950    | Slightly OTM | Slightly OTM |
| OTM3   | 24,150    | 23,850    | OTM          | OTM          |
| OTM5   | 24,250    | 23,750    | Deep OTM     | Deep OTM     |

## Common Use Cases

### 1. Iron Condor Strategy

Fetch 4 option symbols for an iron condor:

```python
import requests

def get_iron_condor_options(api_key, underlying, expiry, strike_int):
    """
    Iron Condor: Sell OTM1 Call, Sell OTM1 Put, Buy OTM3 Call, Buy OTM3 Put
    """
    base_payload = {
        "apikey": api_key,
        "strategy": "iron_condor",
        "underlying": underlying,
        "exchange": "NSE_INDEX",
        "expiry_date": expiry,
        "strike_int": strike_int
    }

    options = []

    # Sell OTM1 Call
    payload = {**base_payload, "offset": "OTM1", "option_type": "CE"}
    response = requests.post("http://127.0.0.1:5000/api/v1/optionsymbol", json=payload)
    options.append(("SELL", response.json()["data"]["symbol"]))

    # Sell OTM1 Put
    payload = {**base_payload, "offset": "OTM1", "option_type": "PE"}
    response = requests.post("http://127.0.0.1:5000/api/v1/optionsymbol", json=payload)
    options.append(("SELL", response.json()["data"]["symbol"]))

    # Buy OTM3 Call
    payload = {**base_payload, "offset": "OTM3", "option_type": "CE"}
    response = requests.post("http://127.0.0.1:5000/api/v1/optionsymbol", json=payload)
    options.append(("BUY", response.json()["data"]["symbol"]))

    # Buy OTM3 Put
    payload = {**base_payload, "offset": "OTM3", "option_type": "PE"}
    response = requests.post("http://127.0.0.1:5000/api/v1/optionsymbol", json=payload)
    options.append(("BUY", response.json()["data"]["symbol"]))

    return options

# Usage
options = get_iron_condor_options("your_api_key", "NIFTY", "28NOV24", 50)
for action, symbol in options:
    print(f"{action:4s} {symbol}")
```

### 2. Straddle Strategy (ATM Call + ATM Put)

```python
def get_straddle_options(api_key, underlying, expiry, strike_int):
    """
    Straddle: Buy/Sell ATM Call + ATM Put
    """
    base_payload = {
        "apikey": api_key,
        "strategy": "straddle",
        "underlying": underlying,
        "exchange": "NSE_INDEX",
        "expiry_date": expiry,
        "strike_int": strike_int,
        "offset": "ATM"
    }

    # ATM Call
    payload_ce = {**base_payload, "option_type": "CE"}
    call_response = requests.post("http://127.0.0.1:5000/api/v1/optionsymbol", json=payload_ce)

    # ATM Put
    payload_pe = {**base_payload, "option_type": "PE"}
    put_response = requests.post("http://127.0.0.1:5000/api/v1/optionsymbol", json=payload_pe)

    return [
        call_response.json()["data"]["symbol"],
        put_response.json()["data"]["symbol"]
    ]
```

### 3. Covered Call (ITM or OTM)

```python
def get_covered_call_option(api_key, underlying, expiry, strike_int, offset="OTM2"):
    """
    Covered Call: Sell OTM Call against long stock position
    """
    payload = {
        "apikey": api_key,
        "strategy": "covered_call",
        "underlying": underlying,
        "exchange": "NSE",
        "expiry_date": expiry,
        "strike_int": strike_int,
        "offset": offset,
        "option_type": "CE"
    }

    response = requests.post("http://127.0.0.1:5000/api/v1/optionsymbol", json=payload)
    return response.json()["data"]["symbol"]
```

## Error Codes

| Status Code | Description |
|-------------|-------------|
| 200 | Success - Option symbol found |
| 400 | Validation error - Invalid parameters |
| 403 | Authentication error - Invalid API key |
| 404 | Symbol not found - Option doesn't exist in database |
| 500 | Server error - Internal processing error |

## Important Notes

1. **Master Contract Data**: The API queries the master contract database. Ensure your broker's master contract data is updated.

2. **Strike Availability**: Not all strikes may be available for all expiries. The API will return 404 if the calculated strike doesn't exist.

3. **LTP Source**:
   - For index options (NIFTY, BANKNIFTY), LTP is fetched from index exchange (NSE_INDEX)
   - For equity options, LTP is fetched from equity exchange (NSE/BSE)
   - For options on futures, LTP is still fetched from underlying spot, not from futures

4. **Strike Calculation**: ATM is calculated by rounding LTP to the nearest strike interval:
   ```
   ATM = round(LTP / strike_int) × strike_int
   ```

5. **Rate Limiting**: The endpoint is rate-limited to 10 requests per second (configurable via `API_RATE_LIMIT` environment variable)

## Related Endpoints

- `/api/v1/quotes` - Get real-time quotes for symbols
- `/api/v1/expiry` - Get available expiry dates for F&O instruments
- `/api/v1/search` - Search for symbols in master contract database

## Support

For issues or questions:
- Check master contract data is updated
- Verify the underlying symbol format
- Ensure expiry date exists for the instrument
- Review API logs for detailed error messages

---

**Version**: 1.0
**Last Updated**: October 2025
