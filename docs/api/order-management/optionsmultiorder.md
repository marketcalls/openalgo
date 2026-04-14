# OptionsMultiOrder

Place multiple option legs in a single request. Ideal for complex options strategies like Iron Condor, Strangles, Spreads, and more. BUY legs are executed before SELL legs for margin efficiency.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/optionsmultiorder
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/optionsmultiorder
Custom Domain:  POST https://<your-custom-domain>/api/v1/optionsmultiorder
```

## Sample API Request (Iron Condor - Same Expiry)

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "Iron Condor Test",
  "underlying": "NIFTY",
  "exchange": "NSE_INDEX",
  "expiry_date": "25NOV25",
  "legs": [
    {"offset": "OTM6", "option_type": "CE", "action": "BUY", "quantity": 65},
    {"offset": "OTM6", "option_type": "PE", "action": "BUY", "quantity": 65},
    {"offset": "OTM4", "option_type": "CE", "action": "SELL", "quantity": 65},
    {"offset": "OTM4", "option_type": "PE", "action": "SELL", "quantity": 65}
  ]
}
```

## Sample API Response (Iron Condor)

```json
{
  "status": "success",
  "underlying": "NIFTY",
  "underlying_ltp": 26050.45,
  "results": [
    {
      "action": "BUY",
      "leg": 1,
      "mode": "analyze",
      "offset": "OTM6",
      "option_type": "CE",
      "orderid": "25111996859688",
      "status": "success",
      "symbol": "NIFTY25NOV2526350CE"
    },
    {
      "action": "BUY",
      "leg": 2,
      "mode": "analyze",
      "offset": "OTM6",
      "option_type": "PE",
      "orderid": "25111996042210",
      "status": "success",
      "symbol": "NIFTY25NOV2525750PE"
    },
    {
      "action": "SELL",
      "leg": 3,
      "mode": "analyze",
      "offset": "OTM4",
      "option_type": "CE",
      "orderid": "25111922189638",
      "status": "success",
      "symbol": "NIFTY25NOV2526250CE"
    },
    {
      "action": "SELL",
      "leg": 4,
      "mode": "analyze",
      "offset": "OTM4",
      "option_type": "PE",
      "orderid": "25111919252668",
      "status": "success",
      "symbol": "NIFTY25NOV2525850PE"
    }
  ]
}
```

## Sample API Request (Diagonal Spread - Different Expiry)

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "Diagonal Spread Test",
  "underlying": "NIFTY",
  "exchange": "NSE_INDEX",
  "legs": [
    {"offset": "ITM2", "option_type": "CE", "action": "BUY", "quantity": 65, "expiry_date": "30DEC25"},
    {"offset": "OTM2", "option_type": "CE", "action": "SELL", "quantity": 65, "expiry_date": "25NOV25"}
  ]
}
```

## Sample API Response (Diagonal Spread)

```json
{
  "results": [
    {
      "action": "BUY",
      "leg": 1,
      "mode": "analyze",
      "offset": "ITM2",
      "option_type": "CE",
      "orderid": "25111933337854",
      "status": "success",
      "symbol": "NIFTY30DEC2525950CE"
    },
    {
      "action": "SELL",
      "leg": 2,
      "mode": "analyze",
      "offset": "OTM2",
      "option_type": "CE",
      "orderid": "25111957475473",
      "status": "success",
      "symbol": "NIFTY25NOV2526150CE"
    }
  ],
  "status": "success",
  "underlying": "NIFTY",
  "underlying_ltp": 26052.65
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| strategy | Strategy identifier | Optional | - |
| underlying | Underlying symbol (NIFTY, BANKNIFTY, etc.) | Mandatory | - |
| exchange | Exchange: NSE_INDEX, BSE_INDEX | Mandatory | - |
| expiry_date | Common expiry date (can be overridden per leg) | Optional | - |
| legs | Array of leg objects | Mandatory | - |

### Leg Object Fields

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| offset | Strike offset: ATM, ITM1-ITM50, OTM1-OTM50 | Mandatory | - |
| option_type | Option type: CE or PE | Mandatory | - |
| action | Order action: BUY or SELL | Mandatory | - |
| quantity | Order quantity | Mandatory | - |
| expiry_date | Leg-specific expiry (for diagonal spreads) | Optional | Uses common expiry |
| pricetype | Price type: MARKET, LIMIT | Optional | MARKET |
| product | Product type: MIS, NRML | Optional | NRML |
| splitsize | Split size for this leg | Optional | 0 |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| underlying | string | Underlying symbol |
| underlying_ltp | number | Last traded price of underlying |
| results | array | Array of leg results |

### Results Array Fields

| Field | Type | Description |
|-------|------|-------------|
| leg | number | Leg number (1, 2, 3...) |
| action | string | BUY or SELL |
| offset | string | Offset used |
| option_type | string | CE or PE |
| symbol | string | Resolved option symbol |
| orderid | string | Order ID from broker |
| status | string | "success" or "error" |
| mode | string | "live" or "analyze" |

## Supported Strategies

| Strategy | Legs | Description |
|----------|------|-------------|
| Iron Condor | 4 | OTM CE buy, OTM PE buy, closer OTM CE sell, closer OTM PE sell |
| Strangle | 2 | OTM CE, OTM PE (same expiry) |
| Straddle | 2 | ATM CE, ATM PE (same expiry) |
| Bull Call Spread | 2 | Buy lower strike CE, sell higher strike CE |
| Bear Put Spread | 2 | Buy higher strike PE, sell lower strike PE |
| Calendar Spread | 2 | Same strike, different expiry |
| Diagonal Spread | 2 | Different strike, different expiry |

## Notes

- **BUY legs are always executed first** for margin efficiency
- Each leg can have its own **expiry_date** for calendar/diagonal spreads
- If a leg fails, subsequent legs are still attempted
- The **underlying_ltp** is used for all legs to ensure consistent ATM calculation
- Maximum legs per request depends on broker limits

---

**Back to**: [API Documentation](../README.md)
