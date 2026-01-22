# ClosePosition

Close all open positions across all exchanges in a single request. This is a square-off operation that places counter orders for all open positions.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/closeposition
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/closeposition
Custom Domain:  POST https://<your-custom-domain>/api/v1/closeposition
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "Python"
}
```

## Sample API Response

```json
{
  "message": "All Open Positions Squared Off",
  "status": "success"
}
```

## Sample API Response (No Positions)

```json
{
  "message": "No open positions to close",
  "status": "success"
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| strategy | Strategy identifier | Optional | - |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| message | string | Result message |
| mode | string | "live" or "analyze" |

## How It Works

1. Fetches all open positions from position book
2. For each position with non-zero quantity:
   - Long position (+ve quantity) → Places SELL order
   - Short position (-ve quantity) → Places BUY order
3. All closing orders are placed as **MARKET** orders
4. Uses the **same product type** as the original position (MIS/NRML)

## Positions Closed

| Exchange | Product Types Closed |
|----------|---------------------|
| NSE | MIS, CNC |
| BSE | MIS, CNC |
| NFO | MIS, NRML |
| BFO | MIS, NRML |
| CDS | MIS, NRML |
| BCD | MIS, NRML |
| MCX | MIS, NRML |

## Notes

- This is a **destructive operation** - all positions will be squared off
- Closing orders are placed as **MARKET orders** for immediate execution
- CNC (delivery) positions are also closed if they have intraday quantity
- Use with caution - there is no confirmation prompt
- The operation affects **all positions** across all exchanges
- For selective closing, use individual orders instead

## Use Cases

- **Emergency exit**: Square off all positions during market crash
- **End of day**: Close all intraday positions before market close
- **Risk management**: Flatten all positions when risk limits are breached

## Related Endpoints

- [CancelAllOrder](./cancelallorder.md) - Cancel all open orders
- [PositionBook](../account-services/positionbook.md) - View current positions

---

**Back to**: [API Documentation](../README.md)
