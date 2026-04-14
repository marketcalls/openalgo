# OpenPosition

Get the current open position for a specific symbol. This endpoint returns the net quantity held for a symbol-exchange-product combination.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/openposition
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/openposition
Custom Domain:  POST https://<your-custom-domain>/api/v1/openposition
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "symbol": "YESBANK",
  "exchange": "NSE",
  "product": "MIS",
  "strategy": "Test Strategy"
}
```

## Sample API Response

```json
{
  "quantity": "-10",
  "status": "success"
}
```

## Sample API Response (No Position)

```json
{
  "quantity": "0",
  "status": "success"
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| symbol | Trading symbol | Mandatory | - |
| exchange | Exchange code: NSE, BSE, NFO, BFO, CDS, BCD, MCX | Mandatory | - |
| product | Product type: MIS, CNC, NRML | Mandatory | - |
| strategy | Strategy identifier | Optional | - |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| quantity | string | Net position quantity |

## Understanding Position Quantity

| Quantity Value | Meaning |
|----------------|---------|
| Positive (+ve) | Long position (bought more than sold) |
| Negative (-ve) | Short position (sold more than bought) |
| Zero (0) | No open position (flat) |

## Notes

- This endpoint is useful for **position-based strategies** to check current holdings
- Returns **0** if no position exists for the symbol-exchange-product combination
- The position is fetched from the position book and filtered by the specified criteria
- Use with [PlaceSmartOrder](../order-management/placesmartorder.md) for position-aware trading
- For F&O positions, ensure you specify the correct product type (MIS or NRML)

## Use Cases

- **Position verification**: Check if a position exists before placing orders
- **Smart order logic**: Calculate order quantity based on current position
- **Risk management**: Monitor position size

## Related Endpoints

- [PositionBook](../account-services/positionbook.md) - Get all positions
- [PlaceSmartOrder](../order-management/placesmartorder.md) - Position-aware orders

---

**Back to**: [API Documentation](../README.md)
