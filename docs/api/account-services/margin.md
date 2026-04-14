# Margin

Calculate margin requirement for a basket of positions. Useful for pre-trade margin checks.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/margin
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/margin
Custom Domain:  POST https://<your-custom-domain>/api/v1/margin
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "positions": [
    {
      "symbol": "NIFTY25NOV2525000CE",
      "exchange": "NFO",
      "action": "BUY",
      "product": "NRML",
      "pricetype": "MARKET",
      "quantity": "65"
    },
    {
      "symbol": "NIFTY25NOV2525500CE",
      "exchange": "NFO",
      "action": "SELL",
      "product": "NRML",
      "pricetype": "MARKET",
      "quantity": "65"
    }
  ]
}
```

## Sample API Response

```json
{
  "status": "success",
  "data": {
    "total_margin_required": 91555.7625,
    "span_margin": 0.0,
    "exposure_margin": 91555.7625
  }
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| positions | Array of position objects (max 50) | Mandatory | - |

### Position Object Fields

| Field | Description | Mandatory/Optional | Default Value |
|-------|-------------|-------------------|---------------|
| symbol | Trading symbol | Mandatory | - |
| exchange | Exchange code: NSE, NFO, BFO, etc. | Mandatory | - |
| action | BUY or SELL | Mandatory | - |
| quantity | Position quantity | Mandatory | - |
| product | Product type: MIS, CNC, NRML | Mandatory | - |
| pricetype | Price type: MARKET, LIMIT | Mandatory | - |
| price | Order price (for LIMIT) | Optional | 0 |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| data | object | Margin calculation results |

### Data Object Fields

| Field | Type | Description |
|-------|------|-------------|
| total_margin_required | number | Total margin required for the basket |
| span_margin | number | SPAN margin component |
| exposure_margin | number | Exposure margin component |
| margin_benefit | number | Margin benefit from hedged positions |

## Notes

- Maximum **50 positions** per request
- Margin calculation includes **hedging benefits** for spread positions
- Actual margin may vary slightly due to real-time price changes
- Not all brokers support margin calculation API
- Use this for **pre-trade validation** to check if sufficient margin exists

## Use Cases

- **Pre-trade check**: Verify margin before placing orders
- **Strategy planning**: Calculate margin for option strategies
- **Risk management**: Understand margin exposure

## Example: Iron Condor Margin

```json
{
  "apikey": "<your_app_apikey>",
  "positions": [
    {"symbol": "NIFTY25NOV2526500CE", "exchange": "NFO", "action": "SELL", "quantity": "65", "product": "NRML", "pricetype": "MARKET"},
    {"symbol": "NIFTY25NOV2527000CE", "exchange": "NFO", "action": "BUY", "quantity": "65", "product": "NRML", "pricetype": "MARKET"},
    {"symbol": "NIFTY25NOV2525500PE", "exchange": "NFO", "action": "SELL", "quantity": "65", "product": "NRML", "pricetype": "MARKET"},
    {"symbol": "NIFTY25NOV2525000PE", "exchange": "NFO", "action": "BUY", "quantity": "65", "product": "NRML", "pricetype": "MARKET"}
  ]
}
```

---

**Back to**: [API Documentation](../README.md)
