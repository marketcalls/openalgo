# Option Chain

## Endpoint URL

This API Function Fetches Option Chain Data with Real-time Quotes for All Strikes

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/optionchain
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/optionchain
Custom Domain:  POST https://<your-custom-domain>/api/v1/optionchain
```

## Sample API Request (Full Chain)

```json
{
    "apikey": "your_api_key",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "30DEC25"
}
```

###

## Sample API Response (Full Chain)

```json
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 24250.50,
    "expiry_date": "30DEC25",
    "atm_strike": 24250.0,
    "chain": [
        {
            "strike": 24000.0,
            "ce": {
                "symbol": "NIFTY30DEC2524000CE",
                "label": "ITM5",
                "ltp": 320.50,
                "bid": 319.75,
                "ask": 321.25,
                "open": 310.00,
                "high": 325.00,
                "low": 305.00,
                "prev_close": 315.00,
                "volume": 125000,
                "oi": 5000000,
                "lotsize": 25,
                "tick_size": 0.05
            },
            "pe": {
                "symbol": "NIFTY30DEC2524000PE",
                "label": "OTM5",
                "ltp": 85.25,
                "bid": 84.50,
                "ask": 86.00,
                "open": 90.00,
                "high": 95.00,
                "low": 82.00,
                "prev_close": 88.00,
                "volume": 98000,
                "oi": 4200000,
                "lotsize": 25,
                "tick_size": 0.05
            }
        },
        {
            "strike": 24250.0,
            "ce": {
                "symbol": "NIFTY30DEC2524250CE",
                "label": "ATM",
                "ltp": 185.50,
                "bid": 184.75,
                "ask": 186.25,
                "open": 180.00,
                "high": 195.00,
                "low": 175.00,
                "prev_close": 182.00,
                "volume": 250000,
                "oi": 8500000,
                "lotsize": 25,
                "tick_size": 0.05
            },
            "pe": {
                "symbol": "NIFTY30DEC2524250PE",
                "label": "ATM",
                "ltp": 180.25,
                "bid": 179.50,
                "ask": 181.00,
                "open": 175.00,
                "high": 190.00,
                "low": 170.00,
                "prev_close": 178.00,
                "volume": 245000,
                "oi": 8200000,
                "lotsize": 25,
                "tick_size": 0.05
            }
        },
        {
            "strike": 24500.0,
            "ce": {
                "symbol": "NIFTY30DEC2524500CE",
                "label": "OTM5",
                "ltp": 78.50,
                "bid": 77.75,
                "ask": 79.25,
                "open": 82.00,
                "high": 88.00,
                "low": 75.00,
                "prev_close": 80.00,
                "volume": 110000,
                "oi": 4800000,
                "lotsize": 25,
                "tick_size": 0.05
            },
            "pe": {
                "symbol": "NIFTY30DEC2524500PE",
                "label": "ITM5",
                "ltp": 328.75,
                "bid": 327.50,
                "ask": 330.00,
                "open": 320.00,
                "high": 335.00,
                "low": 315.00,
                "prev_close": 322.00,
                "volume": 95000,
                "oi": 3900000,
                "lotsize": 25,
                "tick_size": 0.05
            }
        }
    ]
}
```

###

## Sample API Request (10 Strikes Around ATM)

```json
{
    "apikey": "your_api_key",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "30DEC25",
    "strike_count": 10
}
```

This returns 10 strikes above ATM + 10 strikes below ATM + ATM = 21 total strikes.

###

## Sample API Request (Future as Underlying)

```json
{
    "apikey": "your_api_key",
    "underlying": "NIFTY30DEC25FUT",
    "exchange": "NFO"
}
```

**Note**: When using a future as underlying, expiry_date is extracted from the future symbol.

###

## Sample API Request (Stock Options)

```json
{
    "apikey": "your_api_key",
    "underlying": "RELIANCE",
    "exchange": "NSE",
    "expiry_date": "30DEC25",
    "strike_count": 10
}
```

###

## Parameter Description

| Parameter     | Description                                              | Mandatory/Optional | Default Value |
| ------------- | -------------------------------------------------------- | ------------------ | ------------- |
| apikey        | App API key                                              | Mandatory          | -             |
| underlying    | Underlying symbol (NIFTY, BANKNIFTY, RELIANCE, etc.)    | Mandatory          | -             |
| exchange      | Exchange code (NSE_INDEX, NSE, NFO, BSE_INDEX, BSE, BFO)| Mandatory          | -             |
| expiry_date   | Expiry date in DDMMMYY format (e.g., 30DEC25)           | Mandatory*         | -             |
| strike_count  | Number of strikes above and below ATM (1-100)           | Optional           | All strikes   |

*Note: expiry_date is optional if underlying includes expiry (e.g., NIFTY30DEC25FUT)

###

## Response Parameters

| Parameter      | Description                              | Type   |
| -------------- | ---------------------------------------- | ------ |
| status         | API response status (success/error)      | string |
| underlying     | Base underlying symbol                   | string |
| underlying_ltp | Last Traded Price of underlying          | number |
| expiry_date    | Expiry date in DDMMMYY format           | string |
| atm_strike     | At-The-Money strike price               | number |
| chain          | Array of strike data with CE and PE     | array  |

###

## Chain Item Structure

Each item in the `chain` array contains:

| Field  | Description                          | Type   |
| ------ | ------------------------------------ | ------ |
| strike | Strike price                         | number |
| ce     | Call option data (null if not found) | object |
| pe     | Put option data (null if not found)  | object |

###

## CE/PE Data Structure

| Field      | Description                           | Type   |
| ---------- | ------------------------------------- | ------ |
| symbol     | Option symbol (e.g., NIFTY30DEC2524000CE) | string |
| label      | Strike label (ATM, ITM1, OTM1, etc.) | string |
| ltp        | Last Traded Price                    | number |
| bid        | Best bid price                       | number |
| ask        | Best ask price                       | number |
| open       | Day's open price                     | number |
| high       | Day's high price                     | number |
| low        | Day's low price                      | number |
| prev_close | Previous day's close price           | number |
| volume     | Traded volume                        | number |
| oi         | Open Interest                        | number |
| lotsize    | Lot size for the option              | number |
| tick_size  | Minimum price movement               | number |

###

## Strike Labels

Strike labels indicate the position relative to ATM and are **different for CE and PE**:

| Strike Position | CE Label | PE Label | Description                    |
| --------------- | -------- | -------- | ------------------------------ |
| At ATM          | ATM      | ATM      | At-The-Money strike            |
| 1 below ATM     | ITM1     | OTM1     | CE is In-The-Money, PE is Out  |
| 2 below ATM     | ITM2     | OTM2     | CE is In-The-Money, PE is Out  |
| 1 above ATM     | OTM1     | ITM1     | CE is Out-The-Money, PE is In  |
| 2 above ATM     | OTM2     | ITM2     | CE is Out-The-Money, PE is In  |

**Label Logic:**
- Strikes **below** ATM: CE is ITM, PE is OTM
- Strikes **above** ATM: CE is OTM, PE is ITM
- **ATM** strike: Both CE and PE are labeled as ATM

###

## Exchange Mapping

| Underlying Exchange | Options Exchange | Examples                    |
| ------------------- | ---------------- | --------------------------- |
| NSE_INDEX           | NFO              | NIFTY, BANKNIFTY, FINNIFTY  |
| BSE_INDEX           | BFO              | SENSEX, BANKEX              |
| NSE                 | NFO              | RELIANCE, TCS, INFY         |
| BSE                 | BFO              | Stock options on BSE        |

###

## Error Response

```json
{
    "status": "error",
    "message": "No strikes found for NIFTY expiring 30DEC25. Please check expiry date or update master contract."
}
```

###

## Common Error Messages

| Error Message                                     | Cause                                | Solution                          |
| ------------------------------------------------- | ------------------------------------ | --------------------------------- |
| Invalid openalgo apikey                           | API key is incorrect or expired      | Check API key in settings         |
| No strikes found for {symbol}                     | Expiry doesn't exist in database     | Check expiry date format          |
| Failed to fetch LTP for {symbol}                  | Underlying quote not available       | Check underlying symbol/exchange  |
| Failed to determine ATM strike                    | No valid strikes near current price  | Check if market is open           |
| Expiry date is required                           | Missing expiry for non-future        | Provide expiry_date parameter     |
| Master contract needs update                      | Symbol database is outdated          | Update master contract data       |

###

## Use Cases

### 1. Fetch Full Option Chain for Analysis

```json
{
    "apikey": "your_api_key",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "30DEC25"
}
```

Use this to get all available strikes for comprehensive analysis.

### 2. Fetch 10 Strikes Around ATM

```json
{
    "apikey": "your_api_key",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "30DEC25",
    "strike_count": 10
}
```

Returns 10 strikes above and 10 strikes below ATM (21 total including ATM).

### 3. Find ATM Strike and Premium

Use the response to identify:
- ATM strike from `atm_strike` field
- ATM CE and PE premiums from chain items where `label` is "ATM"

### 4. Calculate Put-Call Ratio (PCR)

Sum OI from all PE options and divide by sum of OI from all CE options:
```
PCR = Sum(PE OI) / Sum(CE OI)
```

### 5. Identify Max Pain

Strike with maximum combined OI for CE and PE indicates potential max pain level.

###

## Index Reference

| Index       | Exchange   | Strike Interval | Lot Size |
| ----------- | ---------- | --------------- | -------- |
| NIFTY       | NSE_INDEX  | 50              | 25       |
| BANKNIFTY   | NSE_INDEX  | 100             | 15       |
| FINNIFTY    | NSE_INDEX  | 50              | 25       |
| MIDCPNIFTY  | NSE_INDEX  | 25              | 50       |
| SENSEX      | BSE_INDEX  | 100             | 10       |
| BANKEX      | BSE_INDEX  | 100             | 15       |

###

## Features

1. **Full Chain Support**: Returns entire option chain when strike_count is not provided
2. **Separate CE/PE Labels**: Each option has its own ITM/OTM/ATM label
3. **Real-time Quotes**: Fetches live LTP, bid, ask, volume, and OI for all strikes
4. **Future as Underlying**: Supports using futures for ATM calculation
5. **Stock Options**: Works for both index and stock options
6. **Comprehensive Data**: Includes lotsize and tick_size for each option

###

## Rate Limiting

- **Limit**: 10 requests per second
- **Scope**: Per API endpoint
- **Response**: 429 status code if limit exceeded

###

## Best Practices

1. **Use strike_count for Performance**: Limit strikes when full chain is not needed
2. **Cache Results**: Option chain data can be cached for short periods (5-10 seconds)
3. **Handle Null Values**: CE or PE can be null if symbol doesn't exist
4. **Check Market Hours**: Quotes may be stale outside market hours
5. **Update Master Contracts**: Ensure symbol database is current for accurate results
6. **Use Correct Expiry Format**: Always use DDMMMYY format (e.g., 30DEC25)

###

## Integration Examples

### Python Example

```python
import requests

url = "http://127.0.0.1:5000/api/v1/optionchain"
payload = {
    "apikey": "your_api_key",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "30DEC25",
    "strike_count": 10
}

response = requests.post(url, json=payload)
data = response.json()

if data["status"] == "success":
    print(f"ATM Strike: {data['atm_strike']}")
    print(f"Underlying LTP: {data['underlying_ltp']}")

    for item in data["chain"]:
        ce = item.get("ce", {})
        pe = item.get("pe", {})
        print(f"Strike: {item['strike']} | CE: {ce.get('ltp', '-')} ({ce.get('label', '-')}) | PE: {pe.get('ltp', '-')} ({pe.get('label', '-')})")
```

### JavaScript Example

```javascript
const fetchOptionChain = async () => {
    const response = await fetch('http://127.0.0.1:5000/api/v1/optionchain', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            apikey: 'your_api_key',
            underlying: 'NIFTY',
            exchange: 'NSE_INDEX',
            expiry_date: '30DEC25',
            strike_count: 10
        })
    });

    const data = await response.json();

    if (data.status === 'success') {
        console.log(`ATM Strike: ${data.atm_strike}`);
        data.chain.forEach(item => {
            console.log(`Strike: ${item.strike}, CE: ${item.ce?.ltp}, PE: ${item.pe?.ltp}`);
        });
    }
};
```
