# Option Symbol

## Endpoint URL

This API Function Returns Option Symbol Details based on Underlying and Offset

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/optionsymbol
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/optionsymbol
Custom Domain:  POST https://<your-custom-domain>/api/v1/optionsymbol
```

## Sample API Request (Index Underlying)

```json
{
    "apikey": "eb51c74ed08ffc821fd5da90b55b7560a3a9e48fd58df01063225ecd7b98c993",
    "strategy": "test_strategy",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "28OCT25",
    "strike_int": 50,
    "offset": "ITM2",
    "option_type": "CE"
}
```

###

## Sample API Response

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

###

## Sample API Request (Future as Underlying)

```json
{
    "apikey": "eb51c74ed08ffc821fd5da90b55b7560a3a9e48fd58df01063225ecd7b98c993",
    "strategy": "test_strategy",
    "underlying": "NIFTY28OCT25FUT",
    "exchange": "NFO",
    "strike_int": 50,
    "offset": "ITM2",
    "option_type": "CE"
}
```

###

## Sample API Response

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

###

## Parameter Description

| Parameters   | Description                                          | Mandatory/Optional | Default Value |
| ------------ | ---------------------------------------------------- | ------------------ | ------------- |
| apikey       | App API key                                          | Mandatory          | -             |
| strategy     | Strategy name                                        | Mandatory          | -             |
| underlying   | Underlying symbol (NIFTY, BANKNIFTY, NIFTY28OCT25FUT) | Mandatory          | -             |
| exchange     | Exchange code (NSE_INDEX, NSE, NFO, BSE_INDEX, BSE, BFO) | Mandatory          | -             |
| expiry_date  | Expiry date in DDMMMYY format (e.g., 28OCT25)       | Optional*          | -             |
| strike_int   | Strike interval (50 for NIFTY, 100 for BANKNIFTY)   | Mandatory          | -             |
| offset       | Strike offset (ATM, ITM1-ITM50, OTM1-OTM50)         | Mandatory          | -             |
| option_type  | Option type (CE for Call, PE for Put)               | Mandatory          | -             |

*Note: expiry_date is optional if underlying includes expiry (e.g., NIFTY28OCT25FUT)

###

## Response Parameters

| Parameter      | Description                                   | Type   |
| -------------- | --------------------------------------------- | ------ |
| status         | API response status (success/error)           | string |
| symbol         | Resolved option symbol                        | string |
| exchange       | Exchange code where option is listed          | string |
| lotsize        | Lot size of the option contract              | number |
| tick_size      | Minimum price movement                        | number |
| underlying_ltp | Last Traded Price of underlying               | number |

###

## Examples for Different Underlyings

### NIFTY (Strike Interval: 50)

```json
{
    "apikey": "your_api_key",
    "strategy": "nifty_weekly",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "28NOV24",
    "strike_int": 50,
    "offset": "ATM",
    "option_type": "CE"
}
```

### BANKNIFTY (Strike Interval: 100)

```json
{
    "apikey": "your_api_key",
    "strategy": "banknifty_options",
    "underlying": "BANKNIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "28NOV24",
    "strike_int": 100,
    "offset": "OTM2",
    "option_type": "PE"
}
```

### RELIANCE Equity (Strike Interval: 10)

```json
{
    "apikey": "your_api_key",
    "strategy": "equity_options",
    "underlying": "RELIANCE",
    "exchange": "NSE",
    "expiry_date": "28NOV24",
    "strike_int": 10,
    "offset": "ITM1",
    "option_type": "CE"
}
```

###

## Offset Examples

For underlying LTP = 25966.05, strike_int = 50, ATM = 26000:

| Offset | Option Type | Strike  | Description       |
| ------ | ----------- | ------- | ----------------- |
| ATM    | CE          | 26000   | At-The-Money      |
| ATM    | PE          | 26000   | At-The-Money      |
| ITM1   | CE          | 25950   | In-The-Money -1   |
| ITM2   | CE          | 25900   | In-The-Money -2   |
| ITM1   | PE          | 26050   | In-The-Money +1   |
| ITM2   | PE          | 26100   | In-The-Money +2   |
| OTM1   | CE          | 26050   | Out-of-The-Money +1 |
| OTM2   | CE          | 26100   | Out-of-The-Money +2 |
| OTM1   | PE          | 25950   | Out-of-The-Money -1 |
| OTM2   | PE          | 25900   | Out-of-The-Money -2 |

###

## Error Response

```json
{
    "status": "error",
    "message": "Option symbol NIFTY28OCT2527000CE not found in NFO. Symbol may not exist or master contract needs update."
}
```

###

## Use Cases

1. **Get ATM Option**: Use `"offset": "ATM"` to get the current At-The-Money strike
2. **Get OTM for Premium Collection**: Use `"offset": "OTM2"` or higher for selling OTM options
3. **Get ITM for Directional Trades**: Use `"offset": "ITM1"` or `"ITM2"` for higher delta trades
4. **Build Iron Condor**: Fetch OTM1 and OTM3 strikes for both CE and PE
5. **Verify Symbol Before Order**: Check if option exists in master contract database
