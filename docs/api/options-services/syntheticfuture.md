# SyntheticFuture

Calculate the synthetic futures price using ATM options (Put-Call Parity).

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/syntheticfuture
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/syntheticfuture
Custom Domain:  POST https://<your-custom-domain>/api/v1/syntheticfuture
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "underlying": "NIFTY",
  "exchange": "NSE_INDEX",
  "expiry_date": "25NOV25"
}
```

## Sample API Response

```json
{
  "status": "success",
  "underlying": "NIFTY",
  "underlying_ltp": 25910.05,
  "expiry": "25NOV25",
  "atm_strike": 25900.0,
  "synthetic_future_price": 25980.05
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| underlying | Underlying symbol (NIFTY, BANKNIFTY, SENSEX) | Mandatory | - |
| exchange | Exchange: NSE_INDEX, BSE_INDEX | Mandatory | - |
| expiry_date | Expiry date in DDMMMYY format | Mandatory | - |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| underlying | string | Underlying symbol |
| underlying_ltp | number | Current spot price |
| expiry | string | Expiry date |
| atm_strike | number | ATM strike used for calculation |
| synthetic_future_price | number | Calculated synthetic futures price |

## Formula

```
Synthetic Future Price = Strike Price + Call Premium - Put Premium
```

Where:
- Strike Price = ATM strike
- Call Premium = LTP of ATM Call
- Put Premium = LTP of ATM Put

## Understanding Synthetic Futures

### What is Basis?

```
Basis = Synthetic Future Price - Spot Price
```

| Basis | Interpretation |
|-------|----------------|
| Positive | Cost of carry (normal market) |
| Large positive | High demand for futures/options |
| Negative | Backwardation (rare) |

### Example Calculation

```
Spot Price (underlying_ltp): 25910.05
ATM Strike: 25900
ATM Call Premium: 500
ATM Put Premium: 420

Synthetic Future = 25900 + 500 - 420 = 25980
Basis = 25980 - 25910.05 = 69.95 points
```

## Notes

- Synthetic futures provide a **fair value reference** for actual futures
- Useful for **arbitrage detection** between futures and options
- The **basis** indicates the cost of carry
- Near expiry, synthetic future converges to spot price

## Use Cases

- **Arbitrage strategies**: Compare with actual futures price
- **Fair value calculation**: Determine if futures are overpriced/underpriced
- **Options pricing**: Use as underlying for options Greeks calculation

---

**Back to**: [API Documentation](../README.md)
