# OptionSymbol

Get the option symbol based on underlying, expiry, offset (ATM/ITM/OTM), and option type. This endpoint resolves the correct strike price automatically.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/optionsymbol
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/optionsymbol
Custom Domain:  POST https://<your-custom-domain>/api/v1/optionsymbol
```

## Sample API Request (ATM Option)

```json
{
  "apikey": "<your_app_apikey>",
  "underlying": "NIFTY",
  "exchange": "NSE_INDEX",
  "expiry_date": "30DEC25",
  "offset": "ATM",
  "option_type": "CE"
}
```

## Sample API Response (ATM Option)

```json
{
  "status": "success",
  "symbol": "NIFTY30DEC2525950CE",
  "exchange": "NFO",
  "lotsize": 65,
  "tick_size": 5,
  "freeze_qty": 1800,
  "underlying_ltp": 25966.4
}
```

## Sample API Request (ITM Option)

```json
{
  "apikey": "<your_app_apikey>",
  "underlying": "NIFTY",
  "exchange": "NSE_INDEX",
  "expiry_date": "30DEC25",
  "offset": "ITM3",
  "option_type": "PE"
}
```

## Sample API Response (ITM Option)

```json
{
  "status": "success",
  "symbol": "NIFTY30DEC2526100PE",
  "exchange": "NFO",
  "lotsize": 65,
  "tick_size": 5,
  "freeze_qty": 1800,
  "underlying_ltp": 25966.4
}
```

## Sample API Request (OTM Option)

```json
{
  "apikey": "<your_app_apikey>",
  "underlying": "NIFTY",
  "exchange": "NSE_INDEX",
  "expiry_date": "30DEC25",
  "offset": "OTM4",
  "option_type": "CE"
}
```

## Sample API Response (OTM Option)

```json
{
  "status": "success",
  "symbol": "NIFTY30DEC2526150CE",
  "exchange": "NFO",
  "lotsize": 65,
  "tick_size": 5,
  "freeze_qty": 1800,
  "underlying_ltp": 25966.4
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| underlying | Underlying symbol (NIFTY, BANKNIFTY, SENSEX) | Mandatory | - |
| exchange | Exchange: NSE_INDEX, BSE_INDEX | Mandatory | - |
| expiry_date | Expiry date in DDMMMYY format | Mandatory | - |
| offset | Strike offset: ATM, ITM1-ITM50, OTM1-OTM50 | Mandatory | - |
| option_type | Option type: CE or PE | Mandatory | - |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| symbol | string | Resolved option symbol |
| exchange | string | Options exchange (NFO/BFO) |
| lotsize | number | Lot size for the option |
| tick_size | number | Minimum price movement |
| freeze_qty | number | Maximum quantity per order |
| underlying_ltp | number | Current underlying price |

## Understanding Offset

| Offset | Description | CE Strike Direction | PE Strike Direction |
|--------|-------------|--------------------|--------------------|
| ATM | At-The-Money | Closest to LTP | Closest to LTP |
| ITM1-ITM50 | In-The-Money | Below LTP | Above LTP |
| OTM1-OTM50 | Out-of-The-Money | Above LTP | Below LTP |

## Lot Sizes

| Underlying | Lot Size |
|------------|----------|
| NIFTY | 65 |
| BANKNIFTY | 30 |
| SENSEX | 20 |

## Notes

- The offset is calculated based on actual **strike intervals** in the database
- **underlying_ltp** shows the current price used for ATM calculation
- Use this endpoint to **discover the symbol** before placing orders
- For placing orders directly with offset, use [OptionsOrder](../order-management/optionsorder.md)

---

**Back to**: [API Documentation](../README.md)
