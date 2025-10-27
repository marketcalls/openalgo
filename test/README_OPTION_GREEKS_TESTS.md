# Option Greeks API Tests

This folder contains test scripts for the Option Greeks API.

## Test Files

1. **test_option_greeks_api.py** - Tests the `/api/v1/optiongreeks` endpoint

## Prerequisites

1. **Install mibian Library** ⚠️ **REQUIRED**
   ```bash
   pip install mibian
   # or with uv
   uv pip install mibian
   ```

2. **OpenAlgo must be running**
   - Start OpenAlgo application
   - Ensure it's accessible at `http://127.0.0.1:5000`

3. **Markets Should Be Open**
   - Greeks require live prices for underlying and option
   - Best results during market hours (9:15 AM - 3:30 PM)
   - Pre-market/post-market may have stale data

4. **API Key**
   - Get your API key from OpenAlgo settings
   - Replace `"your_api_key_here"` in the test file

## How to Run Tests

### Option 1: From Test Directory

```bash
# Navigate to test directory
cd D:/openalgo-sandbox-test/openalgo/test

# Run Option Greeks API tests
python test_option_greeks_api.py
```

### Option 2: From Project Root

```bash
# Navigate to project root
cd D:/openalgo-sandbox-test/openalgo

# Run Option Greeks API tests
python test/test_option_greeks_api.py
```

### Option 3: Using uv

```bash
# From project root
cd D:/openalgo-sandbox-test/openalgo

# Run tests with uv
uv run python test/test_option_greeks_api.py
```

## Test Configuration

Edit the test file to configure:

```python
# Configuration section at the top of the file
BASE_URL = "http://127.0.0.1:5000"  # Change if using different host/port
API_KEY = "your_api_key_here"        # Replace with your actual API key
```

**IMPORTANT**: Update option symbols in tests to use current or future expiry dates!

## Test Coverage

### test_option_greeks_api.py

- Test 1: NIFTY Call Option Greeks (NFO)
- Test 2: BANKNIFTY Put Option Greeks (NFO)
- Test 3: Option Greeks with Custom Interest Rate
- Test 4: SENSEX Option Greeks (BFO)
- Test 5: Currency Option Greeks (CDS)
- Test 6: Commodity Option Greeks (MCX)
- Test 7: MCX Option with Custom Expiry Time (GOLD at 17:00)
- Test 8: Equity Option Greeks - RELIANCE (NFO)
- Test 9: Error - Invalid Symbol Format
- Test 10: Error - Expired Option
- Test 11: Compare Call vs Put Greeks (Same Strike)

## Expected Output

### Successful Response

```json
{
  "status": "success",
  "symbol": "NIFTY28NOV2424000CE",
  "exchange": "NFO",
  "underlying": "NIFTY",
  "strike": 24000,
  "option_type": "CE",
  "expiry_date": "28-Nov-2024",
  "days_to_expiry": 5.42,
  "spot_price": 24015.75,
  "option_price": 125.50,
  "interest_rate": 6.5,
  "implied_volatility": 15.25,
  "greeks": {
    "delta": 0.5234,
    "gamma": 0.000125,
    "theta": -12.5678,
    "vega": 18.7654,
    "rho": 0.001234
  }
}
```

### Error Response (mibian Not Installed)

```json
{
  "status": "error",
  "message": "Option Greeks calculation requires mibian library. Install with: pip install mibian"
}
```

### Error Response (Invalid Symbol)

```json
{
  "status": "error",
  "message": "Invalid option symbol format: NIFTY24000CE"
}
```

### Error Response (Expired Option)

```json
{
  "status": "error",
  "message": "Option has expired on 28-Oct-2024"
}
```

## Understanding Greeks Output

### Delta
- **Call Options**: 0 to 1 (typically 0.3 to 0.7 for near-ATM)
- **Put Options**: -1 to 0 (typically -0.7 to -0.3 for near-ATM)
- **Example**: Delta of 0.5 means option moves ₹0.50 for ₹1 move in underlying

### Gamma
- **Range**: 0 to ∞ (same for calls and puts)
- **Highest**: For ATM options near expiry
- **Example**: Gamma of 0.01 means delta increases by 0.01 for ₹1 move

### Theta
- **Always Negative**: For long options (time decay)
- **Accelerates**: As expiry approaches
- **Example**: Theta of -10 means losing ₹10 per day

### Vega
- **Always Positive**: For long options
- **Highest**: For ATM options with more time
- **Example**: Vega of 15 means ₹15 gain for 1% IV increase

### Rho
- **Call Options**: Positive (benefit from rate increase)
- **Put Options**: Negative (hurt by rate increase)
- **Less Important**: For short-term options

## Troubleshooting

### mibian Library Not Installed

```
ModuleNotFoundError: No module named 'mibian'
```

**Solution**:
```bash
pip install mibian
# or
uv pip install mibian
```

Verify installation:
```bash
python -c "import mibian; print('✓ mibian installed')"
```

### Invalid Symbol Format Error

```json
{
  "status": "error",
  "message": "Invalid option symbol format: NIFTY24000CE"
}
```

**Solution**:
- Symbol format must be: `SYMBOL[DD][MMM][YY][STRIKE][CE/PE]`
- ✅ Correct: `NIFTY28NOV2424000CE`
- ❌ Wrong: `NIFTY24000CE`, `NIFTY-28NOV24-24000-CE`

### Option Expired Error

```json
{
  "status": "error",
  "message": "Option has expired on 28-Oct-2024"
}
```

**Solution**:
- Update test file with current or future expiry dates
- Check contract expiry calendar
- Use current month or next month contracts

### Underlying Price Not Available

```json
{
  "status": "error",
  "message": "Failed to fetch underlying price: Symbol not found"
}
```

**Solution**:
1. Check if markets are open
2. Verify underlying symbol is correct
3. Ensure symbol exists in database
4. Check exchange mapping is correct

### Option Price Not Available

```json
{
  "status": "error",
  "message": "Option LTP not available"
}
```

**Solution**:
1. Markets might be closed
2. Option might not be actively traded
3. Symbol might be incorrect
4. Check if contract exists for that strike/expiry

### IV Calculation Failed

```json
{
  "status": "error",
  "message": "Failed to calculate Implied Volatility: ..."
}
```

**Possible Causes**:
1. **Deep ITM/OTM**: Option is too deep, Black-Scholes may not converge
2. **Zero Premium**: Option has no value
3. **Stale Prices**: Pre-market or post-market data

**Solution**:
- Use ATM or near-ATM options for testing
- Ensure markets are open
- Try different strikes

## Symbol Format Examples

### NFO (NSE Futures & Options)

```
NIFTY28NOV2424000CE       # NIFTY Call
BANKNIFTY28NOV2448000PE   # BANKNIFTY Put
RELIANCE28NOV241500CE     # Equity Option
```

**Expiry Time:** 3:30 PM (15:30 IST)

### BFO (BSE Futures & Options)

```
SENSEX28NOV2475000CE      # SENSEX Call
BANKEX28NOV2450000PE      # BANKEX Put
```

**Expiry Time:** 3:30 PM (15:30 IST)

### CDS (Currency Derivatives)

```
USDINR28NOV2483.50CE      # Note: Decimal strike
EURINR28DEC2490.00PE
```

**Expiry Time:** 12:30 PM (12:30 IST) - **Expires 3 hours earlier than NFO/BFO**

### MCX (Commodities)

```
GOLD28DEC2472000CE
SILVER28DEC2488000PE
CRUDEOIL28NOV246500CE
```

**Default Expiry Time:** 11:30 PM (23:30 IST) - **Expires 8 hours later than NFO/BFO**

**⚠️ Important**: Most MCX commodities expire at different times. Always specify `expiry_time` parameter:

| Commodity          | Expiry Time | Format   |
| ------------------ | ----------- | -------- |
| Gold, Silver, Copper | 5:00 PM   | "17:00"  |
| Natural Gas, Crude Oil | 7:00 PM | "19:00"  |

**Example with Custom Expiry Time**:
```json
{
    "apikey": "your_api_key",
    "symbol": "GOLD28DEC2472000CE",
    "exchange": "MCX",
    "expiry_time": "17:00"
}
```

## Understanding Expiry Times & DTE

Different exchanges have different expiry times, which affects **Days to Expiry (DTE)** and all Greeks calculations:

| Exchange | Expiry Time     | Impact on Expiry Day                 |
| -------- | --------------- | ------------------------------------ |
| NFO/BFO  | 3:30 PM (15:30) | Standard - Options expire afternoon  |
| CDS      | 12:30 PM (12:30)| Expires by lunch - Faster theta decay|
| MCX      | 11:30 PM (23:30)| Expires late night - More time value |

**Example on Expiry Day at 2:00 PM:**

```
CDS Option:   Expired 1.5 hours ago ❌
NFO Option:   Expires in 1.5 hours ⏱️  (Theta very high)
MCX Option:   Expires in 9.5 hours ⏱️  (Still has time value)
```

**Key Points:**
- DTE is calculated as: `(expiry_time - current_time) / 365 years`
- Accurate DTE is critical for IV and Greeks calculations
- On expiry day, CDS Greeks are most aggressive (highest theta)
- MCX has most time value remaining on expiry day

## Integration Examples

### Calculate Portfolio Delta

```python
import requests

def get_greeks(symbol, exchange):
    url = "http://127.0.0.1:5000/api/v1/optiongreeks"
    payload = {
        "apikey": "your_api_key",
        "symbol": symbol,
        "exchange": exchange
    }
    response = requests.post(url, json=payload)
    return response.json()

# Portfolio positions
positions = [
    {"symbol": "NIFTY28NOV2424000CE", "quantity": 75, "side": "long"},
    {"symbol": "NIFTY28NOV2424500CE", "quantity": 75, "side": "short"},
]

# Calculate net delta
net_delta = 0
for pos in positions:
    greeks = get_greeks(pos['symbol'], 'NFO')
    if greeks['status'] == 'success':
        delta = greeks['greeks']['delta']
        position_delta = delta * pos['quantity']
        if pos['side'] == 'short':
            position_delta *= -1
        net_delta += position_delta
        print(f"{pos['symbol']}: Delta = {delta:.4f}, Position Delta = {position_delta:.2f}")

print(f"\nNet Portfolio Delta: {net_delta:.2f}")
```

### Monitor Time Decay

```python
def monitor_theta(symbol, exchange):
    greeks = get_greeks(symbol, exchange)

    if greeks['status'] == 'success':
        theta = greeks['greeks']['theta']
        days_left = greeks['days_to_expiry']

        print(f"Symbol: {symbol}")
        print(f"Days to Expiry: {days_left:.2f}")
        print(f"Daily Theta: ₹{theta:.2f}")
        print(f"Weekly Theta: ₹{theta * 7:.2f}")

        if days_left < 5:
            print("⚠️  Warning: High theta decay - consider rolling position")

# Usage
monitor_theta("NIFTY28NOV2424000CE", "NFO")
```

### Find High Vega Options

```python
strikes = [23500, 23750, 24000, 24250, 24500]

print("Comparing Vega across strikes:")
for strike in strikes:
    symbol = f"NIFTY28NOV24{strike}CE"
    greeks = get_greeks(symbol, 'NFO')

    if greeks['status'] == 'success':
        vega = greeks['greeks']['vega']
        iv = greeks['implied_volatility']
        print(f"Strike {strike}: Vega = {vega:.2f}, IV = {iv:.2f}%")

# ATM typically has highest Vega - best for volatility plays
```

## Notes

- **mibian Required**: API will not work without mibian library installed
- **Live Prices**: Results depend on current market prices
- **Market Hours**: Best accuracy during market hours (9:15 AM - 3:30 PM)
- **Expiry Dates**: Always use current or future expiry dates
- **Symbol Format**: Must match exact pattern: `SYMBOL[DD][MMM][YY][STRIKE][CE/PE]`
- **Interest Rate**: Defaults to 6.5% per exchange, can be overridden
- **Deep Options**: Very deep ITM/OTM may have calculation issues
- **Currency Options**: Support decimal strikes (e.g., 83.50)

## Rate Limiting

- **Limit**: 30 requests per minute
- **Endpoint**: `/api/v1/optiongreeks`
- **Response**: 429 status code if exceeded
- **Recommendation**: Cache results for 30-60 seconds

## Performance Tips

1. **Cache Results**: Greeks don't change drastically every second
2. **Batch Requests**: Calculate all needed Greeks at once
3. **Rate Limit**: Space out requests if calculating many strikes
4. **Market Hours**: Best results during active trading hours

## Support

For issues or questions:
- Verify mibian installation first
- Check symbol format matches documented pattern
- Ensure markets are open for accurate prices
- Update expiry dates to current/future
- Review OpenAlgo logs for detailed errors
- Compare with broker Greeks to validate accuracy
