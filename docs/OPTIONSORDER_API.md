# Options Order

## Endpoint URL

This API Function Places Option Orders by Auto-Resolving Symbol based on Underlying and Offset

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/optionsorder
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/optionsorder
Custom Domain:  POST https://<your-custom-domain>/api/v1/optionsorder
```

## Sample API Request (Future as Underlying)

```json
{
    "apikey": "eb51c74ed08ffc821fd5da90b55b7560a3a9e48fd58df01063225ecd7b98c993",
    "strategy": "test_strategy",
    "underlying": "NIFTY28OCT25FUT",
    "exchange": "NFO",
    "strike_int": 50,
    "offset": "ITM2",
    "option_type": "CE",
    "action": "BUY",
    "quantity": 75,
    "pricetype": "MARKET",
    "product": "NRML"
}
```

###

## Sample API Response (Analyze Mode)

```json
{
    "status": "success",
    "orderid": "25102700000020",
    "symbol": "NIFTY28OCT2525850CE",
    "exchange": "NFO",
    "underlying": "NIFTY28OCT25FUT",
    "underlying_ltp": 25966.05,
    "offset": "ITM2",
    "option_type": "CE",
    "mode": "analyze"
}
```

###

## Sample API Request (Index Underlying with MARKET Order)

```json
{
    "apikey": "your_api_key",
    "strategy": "nifty_weekly",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "28NOV24",
    "strike_int": 50,
    "offset": "ATM",
    "option_type": "CE",
    "action": "BUY",
    "quantity": 75,
    "pricetype": "MARKET",
    "product": "MIS",
    "price": "0",
    "trigger_price": "0",
    "disclosed_quantity": "0"
}
```

###

## Sample API Response (Live Mode)

```json
{
    "status": "success",
    "orderid": "240123000001234",
    "symbol": "NIFTY28NOV2424000CE",
    "exchange": "NFO",
    "underlying": "NIFTY",
    "underlying_ltp": 23987.50,
    "offset": "ATM",
    "option_type": "CE"
}
```

###

## Sample API Request (LIMIT Order)

```json
{
    "apikey": "your_api_key",
    "strategy": "nifty_scalping",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "28NOV24",
    "strike_int": 50,
    "offset": "OTM1",
    "option_type": "CE",
    "action": "BUY",
    "quantity": 75,
    "pricetype": "LIMIT",
    "product": "MIS",
    "price": "50.0",
    "trigger_price": "0",
    "disclosed_quantity": "0"
}
```

###

## Sample API Request (Stop Loss Order)

```json
{
    "apikey": "your_api_key",
    "strategy": "protective_stop",
    "underlying": "BANKNIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "28NOV24",
    "strike_int": 100,
    "offset": "ATM",
    "option_type": "PE",
    "action": "SELL",
    "quantity": 30,
    "pricetype": "SL",
    "product": "MIS",
    "price": "100.0",
    "trigger_price": "105.0",
    "disclosed_quantity": "0"
}
```

###

## Parameter Description

| Parameters          | Description                                          | Mandatory/Optional | Default Value |
| ------------------- | ---------------------------------------------------- | ------------------ | ------------- |
| apikey              | App API key                                          | Mandatory          | -             |
| strategy            | Strategy name                                        | Mandatory          | -             |
| underlying          | Underlying symbol (NIFTY, BANKNIFTY, NIFTY28OCT25FUT) | Mandatory          | -             |
| exchange            | Exchange code (NSE_INDEX, NSE, NFO, BSE_INDEX, BSE, BFO) | Mandatory          | -             |
| expiry_date         | Expiry date in DDMMMYY format (e.g., 28OCT25)       | Optional*          | -             |
| strike_int          | Strike interval (50 for NIFTY, 100 for BANKNIFTY)   | Mandatory          | -             |
| offset              | Strike offset (ATM, ITM1-ITM50, OTM1-OTM50)         | Mandatory          | -             |
| option_type         | Option type (CE for Call, PE for Put)               | Mandatory          | -             |
| action              | Action (BUY/SELL)                                    | Mandatory          | -             |
| quantity            | Quantity (must be multiple of lot size)             | Mandatory          | -             |
| pricetype           | Price type (MARKET/LIMIT/SL/SL-M)                   | Optional           | MARKET        |
| product             | Product type (MIS/NRML)**                           | Optional           | MIS           |
| price               | Limit price                                          | Optional           | 0             |
| trigger_price       | Trigger price for SL orders                          | Optional           | 0             |
| disclosed_quantity  | Disclosed quantity                                   | Optional           | 0             |

*Note: expiry_date is optional if underlying includes expiry (e.g., NIFTY28OCT25FUT)
**Note: Options only support MIS and NRML products (CNC not supported)

###

## Response Parameters

| Parameter      | Description                                   | Type   |
| -------------- | --------------------------------------------- | ------ |
| status         | API response status (success/error)           | string |
| orderid        | Broker order ID (or SB-xxx for analyze mode) | string |
| symbol         | Resolved option symbol                        | string |
| exchange       | Exchange code where order is placed           | string |
| underlying     | Underlying symbol from request                | string |
| underlying_ltp | Last Traded Price of underlying               | number |
| offset         | Strike offset from request                    | string |
| option_type    | Option type (CE/PE)                           | string |
| mode           | Trading mode (analyze/live)***                | string |

***Note: mode field is only present in Analyze Mode responses

###

## Live Mode vs Analyze Mode

### Live Mode
- **When**: Analyze Mode toggle is OFF in OpenAlgo settings
- **Behavior**: Places real orders with connected broker
- **Order ID Format**: Broker's order ID (e.g., "240123000001234")
- **Response**: No "mode" field present

### Analyze Mode (Sandbox)
- **When**: Analyze Mode toggle is ON in OpenAlgo settings
- **Behavior**: Places virtual orders in sandbox environment
- **Order ID Format**: Sandbox ID with "SB-" prefix (e.g., "SB-1234567890")
- **Response**: Includes "mode": "analyze" field
- **Features**: Virtual capital, realistic execution, auto square-off

**Note**: Same API call works in both modes. The system automatically detects which mode is active.

###

## Product Types for Options

| Product | Description           | Margin      | Square-off    | Use Case              |
| ------- | --------------------- | ----------- | ------------- | --------------------- |
| MIS     | Margin Intraday       | Lower       | Auto (3:15 PM)| Intraday trading      |
| NRML    | Normal (Carry Forward)| Higher      | Manual        | Overnight positions   |

**Note**: CNC (Cash & Carry) is not supported for options trading.

###

## Examples for Different Strategies

### 1. Buy ATM Straddle

**Call Leg:**
```json
{
    "apikey": "your_api_key",
    "strategy": "straddle",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "28NOV24",
    "strike_int": 50,
    "offset": "ATM",
    "option_type": "CE",
    "action": "BUY",
    "quantity": 75,
    "pricetype": "MARKET",
    "product": "MIS"
}
```

**Put Leg:**
```json
{
    "apikey": "your_api_key",
    "strategy": "straddle",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "28NOV24",
    "strike_int": 50,
    "offset": "ATM",
    "option_type": "PE",
    "action": "BUY",
    "quantity": 75,
    "pricetype": "MARKET",
    "product": "MIS"
}
```

### 2. Iron Condor (4 Legs)

**Leg 1: Sell OTM1 Call**
```json
{
    "underlying": "NIFTY",
    "offset": "OTM1",
    "option_type": "CE",
    "action": "SELL",
    "quantity": 75
}
```

**Leg 2: Sell OTM1 Put**
```json
{
    "underlying": "NIFTY",
    "offset": "OTM1",
    "option_type": "PE",
    "action": "SELL",
    "quantity": 75
}
```

**Leg 3: Buy OTM3 Call**
```json
{
    "underlying": "NIFTY",
    "offset": "OTM3",
    "option_type": "CE",
    "action": "BUY",
    "quantity": 75
}
```

**Leg 4: Buy OTM3 Put**
```json
{
    "underlying": "NIFTY",
    "offset": "OTM3",
    "option_type": "PE",
    "action": "BUY",
    "quantity": 75
}
```

### 3. Covered Call (Equity + Short Call)

```json
{
    "apikey": "your_api_key",
    "strategy": "covered_call",
    "underlying": "RELIANCE",
    "exchange": "NSE",
    "expiry_date": "28NOV24",
    "strike_int": 10,
    "offset": "OTM2",
    "option_type": "CE",
    "action": "SELL",
    "quantity": 1000,
    "pricetype": "MARKET",
    "product": "NRML"
}
```

###

## Lot Size Reference

| Underlying  | Lot Size | Strike Interval | Exchange   |
| ----------- | -------- | --------------- | ---------- |
| NIFTY       | 25       | 50              | NSE_INDEX  |
| BANKNIFTY   | 15       | 100             | NSE_INDEX  |
| FINNIFTY    | 25       | 50              | NSE_INDEX  |
| MIDCPNIFTY  | 50       | 25              | NSE_INDEX  |
| SENSEX      | 10       | 100             | BSE_INDEX  |
| BANKEX      | 15       | 100             | BSE_INDEX  |

**Note**: For equity options, lot size varies. Check contract specifications.

###

## Error Response

```json
{
    "status": "error",
    "message": "Option symbol NIFTY28NOV2425500CE not found in NFO. Symbol may not exist or master contract needs update."
}
```

###

## Common Error Messages

| Error Message                              | Cause                                      | Solution                        |
| ------------------------------------------ | ------------------------------------------ | ------------------------------- |
| Invalid openalgo apikey                    | API key is incorrect or expired            | Check API key in settings       |
| Option symbol not found                    | Calculated strike doesn't exist            | Check strike_int and offset     |
| Quantity must be a positive integer        | Invalid quantity value                     | Provide valid quantity          |
| Insufficient funds                         | Not enough margin (Live mode)              | Add funds or reduce quantity    |
| Master contract needs update               | Symbol database is outdated                | Update master contract data     |

###

## Features

1. **Auto Symbol Resolution**: Automatically calculates ATM and resolves option symbol
2. **Dual Mode Support**: Works in both Live and Analyze (Sandbox) modes
3. **All Order Types**: Supports MARKET, LIMIT, SL, and SL-M orders
4. **Real-time LTP**: Uses current market price for ATM calculation
5. **Strategy Tracking**: Associates orders with strategy names for analytics
6. **Telegram Alerts**: Automatic notifications for order placement
7. **Error Handling**: Comprehensive error messages for debugging

###

## Rate Limiting

- **Limit**: 10 requests per second
- **Scope**: Per API endpoint
- **Response**: 429 status code if limit exceeded

###

## Best Practices

1. **Test in Analyze Mode First**: Enable Analyze Mode to test strategies without real money
2. **Verify Lot Size**: Ensure quantity is a multiple of lot size
3. **Check Strike Intervals**: Use correct strike_int for each underlying (50 for NIFTY, 100 for BANKNIFTY)
4. **Use Appropriate Product**: MIS for intraday, NRML for overnight
5. **Handle Errors**: Implement error handling for failed orders
6. **Monitor Margin**: Check available margin before placing orders
7. **Update Master Contracts**: Keep symbol database updated for accurate symbol resolution
