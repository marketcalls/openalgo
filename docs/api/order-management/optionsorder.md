# OptionsOrder

Place an options order by specifying offset (ATM/ITM/OTM) instead of exact strike price. The API automatically resolves the correct option symbol based on the current underlying price.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/optionsorder
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/optionsorder
Custom Domain:  POST https://<your-custom-domain>/api/v1/optionsorder
```

## Sample API Request (ATM Option)

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "python",
  "underlying": "NIFTY",
  "exchange": "NSE_INDEX",
  "expiry_date": "28OCT25",
  "offset": "ATM",
  "option_type": "CE",
  "action": "BUY",
  "quantity": "65",
  "pricetype": "MARKET",
  "product": "NRML",
  "splitsize": "0"
}
```

## Sample API Response (ATM Option)

```json
{
  "exchange": "NFO",
  "offset": "ATM",
  "option_type": "CE",
  "orderid": "25102800000006",
  "status": "success",
  "symbol": "NIFTY28OCT2525950CE",
  "underlying": "NIFTY28OCT25FUT",
  "underlying_ltp": 25966.05
}
```

## Sample API Request (ITM Option)

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "python",
  "underlying": "NIFTY",
  "exchange": "NSE_INDEX",
  "expiry_date": "28OCT25",
  "offset": "ITM4",
  "option_type": "PE",
  "action": "BUY",
  "quantity": "65",
  "pricetype": "MARKET",
  "product": "NRML",
  "splitsize": "0"
}
```

## Sample API Response (ITM Option)

```json
{
  "exchange": "NFO",
  "offset": "ITM4",
  "option_type": "PE",
  "orderid": "25102800000007",
  "status": "success",
  "symbol": "NIFTY28OCT2526150PE",
  "underlying": "NIFTY28OCT25FUT",
  "underlying_ltp": 25966.05
}
```

## Sample API Request (OTM Option)

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "python",
  "underlying": "NIFTY",
  "exchange": "NSE_INDEX",
  "expiry_date": "28OCT25",
  "offset": "OTM5",
  "option_type": "CE",
  "action": "BUY",
  "quantity": "65",
  "pricetype": "MARKET",
  "product": "NRML",
  "splitsize": "0"
}
```

## Offset Values

| Offset | Description |
|--------|-------------|
| ATM | At-The-Money (strike closest to current price) |
| ITM1 to ITM50 | In-The-Money (1-50 strikes away) |
| OTM1 to OTM50 | Out-of-The-Money (1-50 strikes away) |

### Understanding ITM/OTM for CE and PE

| Option Type | ITM Direction | OTM Direction |
|-------------|---------------|---------------|
| CE (Call) | Lower strikes | Higher strikes |
| PE (Put) | Higher strikes | Lower strikes |

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| strategy | Strategy identifier | Optional | - |
| underlying | Underlying symbol (NIFTY, BANKNIFTY, etc.) | Mandatory | - |
| exchange | Exchange: NSE_INDEX, BSE_INDEX, NFO, BFO | Mandatory | - |
| expiry_date | Expiry date in DDMMMYY format (e.g., 28OCT25) | Mandatory | - |
| offset | Strike offset: ATM, ITM1-ITM50, OTM1-OTM50 | Mandatory | - |
| option_type | Option type: CE or PE | Mandatory | - |
| action | Order action: BUY or SELL | Mandatory | - |
| quantity | Order quantity | Mandatory | - |
| pricetype | Price type: MARKET, LIMIT, SL, SL-M | Mandatory | - |
| product | Product type: MIS or NRML | Mandatory | - |
| splitsize | Split order into chunks (0 = no split) | Optional | 0 |
| price | Limit price (for LIMIT orders) | Optional | 0 |
| trigger_price | Trigger price (for SL orders) | Optional | 0 |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| orderid | string | Unique order ID from broker |
| symbol | string | Resolved option symbol |
| exchange | string | Exchange where order was placed (NFO/BFO) |
| offset | string | Offset used for resolution |
| option_type | string | CE or PE |
| underlying | string | Underlying futures symbol used for price reference |
| underlying_ltp | number | Last traded price of underlying |
| mode | string | "live" or "analyze" |

## Notes

- The **underlying** is used to fetch the current price for ATM calculation
- For **NSE_INDEX** or **BSE_INDEX** exchange, the order is placed on NFO/BFO respectively
- The **expiry_date** must be in DDMMMYY format (e.g., 28OCT25, 25NOV25)
- Use **splitsize** to break large orders into smaller chunks (max 100 orders per split)
- The API uses the synthetic futures price or spot price to determine ATM strike

---

**Back to**: [API Documentation](../README.md)
