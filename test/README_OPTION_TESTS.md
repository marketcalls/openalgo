# Option Symbol and Options Order API Tests

This folder contains test scripts for the Option Symbol and Options Order APIs.

## Test Files

1. **test_option_symbol_api.py** - Tests the `/api/v1/optionsymbol` endpoint
2. **test_options_order_api.py** - Tests the `/api/v1/optionsorder` endpoint

## Prerequisites

1. **OpenAlgo must be running**
   - Start OpenAlgo application
   - Ensure it's accessible at `http://127.0.0.1:5000`

2. **API Key**
   - Get your API key from OpenAlgo settings
   - Replace `"your_api_key_here"` in the test files with your actual API key

## How to Run Tests

### Option 1: From Test Directory

```bash
# Navigate to test directory
cd D:/openalgo-sandbox-test/openalgo/test

# Run Option Symbol API tests
python test_option_symbol_api.py

# Run Options Order API tests
python test_options_order_api.py
```

### Option 2: From Project Root

```bash
# Navigate to project root
cd D:/openalgo-sandbox-test/openalgo

# Run Option Symbol API tests
python test/test_option_symbol_api.py

# Run Options Order API tests
python test/test_options_order_api.py
```

### Option 3: Using uv

```bash
# From project root
cd D:/openalgo-sandbox-test/openalgo

# Run tests with uv
uv run python test/test_option_symbol_api.py
uv run python test/test_options_order_api.py
```

## Test Configuration

Edit the test files to configure:

```python
# Configuration section at the top of each file
BASE_URL = "http://127.0.0.1:5000"  # Change if using different host/port
API_KEY = "your_api_key_here"        # Replace with your actual API key
```

## Test Modes

### Testing with Analyze Mode (Sandbox)

1. Enable **Analyze Mode** in OpenAlgo settings
2. Run the tests
3. Orders will be placed in sandbox (virtual trading)
4. Check sandbox dashboard for results
5. Response will include `"mode": "analyze"`

### Testing with Live Mode

1. Disable **Analyze Mode** in OpenAlgo settings
2. Run the tests
3. **⚠️ WARNING**: Orders will be placed with real broker
4. Ensure you want to place real orders before testing
5. Response will NOT include mode field

## Test Coverage

### test_option_symbol_api.py

- Test 1: NIFTY Index Option Symbol
- Test 2: NIFTY Future with Embedded Expiry
- Test 3: BANKNIFTY Option Symbol
- Test 4: Equity Option Symbol (RELIANCE)
- Test 5: Validation Error Test
- Test 6: Multiple Offsets Test

### test_options_order_api.py

- Test 1: Buy NIFTY ATM Call (MIS)
- Test 2: Sell BANKNIFTY ITM2 Put (NRML)
- Test 3: Buy Option using Future with Embedded Expiry
- Test 4: LIMIT Order
- Test 5: Stop Loss (SL) Order
- Test 6: Iron Condor Strategy (4 Legs)
- Test 7: Validation Error Test

## Expected Output

### Successful Response (Option Symbol)

```json
{
  "status": "success",
  "symbol": "NIFTY28OCT2525850CE",
  "exchange": "NFO",
  "lotsize": 75,
  "tick_size": 0.05,
  "underlying_ltp": 25966.05
}
```

### Successful Response (Options Order - Analyze Mode)

```json
{
  "status": "success",
  "orderid": "SB-1234567890",
  "symbol": "NIFTY28OCT2525850CE",
  "exchange": "NFO",
  "underlying": "NIFTY",
  "underlying_ltp": 25966.05,
  "offset": "ITM2",
  "option_type": "CE",
  "mode": "analyze"
}
```

### Successful Response (Options Order - Live Mode)

```json
{
  "status": "success",
  "orderid": "240123000001234",
  "symbol": "NIFTY28OCT2525850CE",
  "exchange": "NFO",
  "underlying": "NIFTY",
  "underlying_ltp": 25966.05,
  "offset": "ITM2",
  "option_type": "CE"
}
```

### Error Response

```json
{
  "status": "error",
  "message": "Option symbol NIFTY28NOV2425500CE not found in NFO. Symbol may not exist or master contract needs update."
}
```

## Troubleshooting

### Connection Refused Error

```
ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
```

**Solution**: Make sure OpenAlgo is running at `http://127.0.0.1:5000`

### Invalid API Key Error

```json
{
  "status": "error",
  "message": "Invalid openalgo apikey"
}
```

**Solution**: Replace API key in test file with your actual API key from OpenAlgo settings

### Module Import Errors

```
ModuleNotFoundError: No module named 'requests'
```

**Solution**: Install required packages:
```bash
pip install requests
# or
uv pip install requests
```

### Symbol Not Found Error

```json
{
  "status": "error",
  "message": "Option symbol not found in NFO"
}
```

**Solution**:
- Check if expiry date is valid
- Ensure master contract data is updated
- Verify the strike exists for the given expiry

## Notes

- Tests use MARKET orders by default (no real cost impact in sandbox)
- Lot sizes: NIFTY=25, BANKNIFTY=15, adjust quantity accordingly
- Strike intervals: NIFTY=50, BANKNIFTY=100
- Always test in Analyze Mode first before going live
- Update expiry dates in test files to use current/future dates

## Support

For issues or questions:
- Check OpenAlgo logs for detailed error messages
- Verify API endpoint is accessible
- Ensure master contract data is up to date
- Review API documentation in `docs/` folder
