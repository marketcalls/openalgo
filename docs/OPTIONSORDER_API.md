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
    "apikey": "<your_app_apikey>",
    "strategy": "test_strategy",
    "underlying": "NIFTY30DEC25FUT",
    "exchange": "NFO",
    "expiry_date": "30DEC25",
    "offset": "ITM2",
    "option_type": "CE",
    "action": "BUY",
    "quantity": 75,
    "pricetype": "MARKET",
    "product": "NRML",
    "splitsize": 0
}
```

###

## Sample API Response (Analyze Mode)

```json
{
    "status": "success",
    "orderid": "25102700000020",
    "symbol": "NIFTY30DEC2525850CE",
    "exchange": "NFO",
    "underlying": "NIFTY30DEC25FUT",
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
    "apikey": "<your_app_apikey>",
    "strategy": "nifty_weekly",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "30DEC25",
    "offset": "ATM",
    "option_type": "CE",
    "action": "BUY",
    "quantity": 75,
    "pricetype": "MARKET",
    "product": "MIS",
    "splitsize": 0
}
```

###

## Sample API Response (Live Mode)

```json
{
    "status": "success",
    "orderid": "240123000001234",
    "symbol": "NIFTY30DEC2524000CE",
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
    "apikey": "<your_app_apikey>",
    "strategy": "nifty_scalping",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "30DEC25",
    "offset": "OTM1",
    "option_type": "CE",
    "action": "BUY",
    "quantity": 75,
    "pricetype": "LIMIT",
    "product": "MIS",
    "price": "50.0",
    "splitsize": 0
}
```

###

## Sample API Request (Stop Loss Order)

```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "protective_stop",
    "underlying": "BANKNIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "30DEC25",
    "offset": "ATM",
    "option_type": "PE",
    "action": "SELL",
    "quantity": 30,
    "pricetype": "SL",
    "product": "MIS",
    "price": "100.0",
    "trigger_price": "105.0",
    "splitsize": 0
}
```

###

## Parameter Description

| Parameters          | Description                                          | Mandatory/Optional | Default Value |
| ------------------- | ---------------------------------------------------- | ------------------ | ------------- |
| apikey              | App API key                                          | Mandatory          | -             |
| strategy            | Strategy name                                        | Mandatory          | -             |
| underlying          | Underlying symbol (NIFTY, BANKNIFTY, NIFTY30DEC25FUT) | Mandatory          | -             |
| exchange            | Exchange code (NSE_INDEX, NSE, NFO, BSE_INDEX, BSE, BFO) | Mandatory          | -             |
| expiry_date         | Expiry date in DDMMMYY format (e.g., 30DEC25)       | Mandatory          | -             |
| offset              | Strike offset (ATM, ITM1-ITM50, OTM1-OTM50)         | Mandatory          | -             |
| option_type         | Option type (CE for Call, PE for Put)               | Mandatory          | -             |
| action              | Action (BUY/SELL)                                    | Mandatory          | -             |
| quantity            | Quantity (must be multiple of lot size)             | Mandatory          | -             |
| splitsize           | Auto-split order into chunks of this size (0=no split) | Optional        | 0             |
| pricetype           | Price type (MARKET/LIMIT/SL/SL-M)                   | Optional           | MARKET        |
| product             | Product type (MIS/NRML)**                           | Optional           | MIS           |
| price               | Limit price                                          | Optional           | 0             |
| trigger_price       | Trigger price for SL orders                          | Optional           | 0             |
| disclosed_quantity  | Disclosed quantity                                   | Optional           | 0             |

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
    "apikey": "<your_app_apikey>",
    "strategy": "straddle",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "30DEC25",
    "offset": "ATM",
    "option_type": "CE",
    "action": "BUY",
    "quantity": 75,
    "pricetype": "MARKET",
    "product": "MIS",
    "splitsize": 0
}
```

**Put Leg:**
```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "straddle",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "30DEC25",
    "offset": "ATM",
    "option_type": "PE",
    "action": "BUY",
    "quantity": 75,
    "pricetype": "MARKET",
    "product": "MIS",
    "splitsize": 0
}
```

### 2. Covered Call (Equity + Short Call)

```json
{
    "apikey": "<your_app_apikey>",
    "strategy": "covered_call",
    "underlying": "RELIANCE",
    "exchange": "NSE",
    "expiry_date": "30DEC25",
    "offset": "OTM2",
    "option_type": "CE",
    "action": "SELL",
    "quantity": 1000,
    "pricetype": "MARKET",
    "product": "NRML",
    "splitsize": 0
}
```

###

## Error Response

```json
{
    "status": "error",
    "message": "Option symbol NIFTY30DEC2525500CE not found in NFO. Symbol may not exist or master contract needs update."
}
```

###

## Common Error Messages

| Error Message                              | Cause                                      | Solution                        |
| ------------------------------------------ | ------------------------------------------ | ------------------------------- |
| Invalid openalgo apikey                    | API key is incorrect or expired            | Check API key in settings       |
| Option symbol not found                    | Calculated strike doesn't exist            | Check offset and expiry_date    |
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
3. **Verify Offset**: Ensure offset value is valid (ATM, ITM1-ITM50, OTM1-OTM50)
4. **Use Appropriate Product**: MIS for intraday, NRML for overnight
5. **Handle Errors**: Implement error handling for failed orders
6. **Monitor Margin**: Check available margin before placing orders
7. **Update Master Contracts**: Keep symbol database updated for accurate symbol resolution
