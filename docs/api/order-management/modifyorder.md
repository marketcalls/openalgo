# ModifyOrder

Modify an existing open order. You can change price, quantity, trigger price, and other parameters.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/modifyorder
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/modifyorder
Custom Domain:  POST https://<your-custom-domain>/api/v1/modifyorder
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "orderid": "250408001002736",
  "strategy": "Python",
  "symbol": "YESBANK",
  "action": "BUY",
  "exchange": "NSE",
  "pricetype": "LIMIT",
  "product": "CNC",
  "quantity": "1",
  "price": "16.5"
}
```

## Sample API Response

```json
{
  "orderid": "250408001002736",
  "status": "success"
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| orderid | Order ID to modify | Mandatory | - |
| strategy | Strategy identifier | Optional | - |
| symbol | Trading symbol | Mandatory | - |
| action | Order action: BUY or SELL | Mandatory | - |
| exchange | Exchange code: NSE, BSE, NFO, BFO, CDS, BCD, MCX | Mandatory | - |
| pricetype | Price type: MARKET, LIMIT, SL, SL-M | Mandatory | - |
| product | Product type: MIS, CNC, NRML | Mandatory | - |
| quantity | New order quantity | Mandatory | - |
| price | New order price | Mandatory | - |
| trigger_price | New trigger price (for SL orders) | Optional | 0 |
| disclosed_quantity | New disclosed quantity | Optional | 0 |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| orderid | string | Modified order ID |
| message | string | Error message (on failure) |
| mode | string | "live" or "analyze" |

## What Can Be Modified?

| Parameter | Modifiable | Notes |
|-----------|------------|-------|
| Quantity | Yes | Must be valid lot size for F&O |
| Price | Yes | For LIMIT/SL orders |
| Trigger Price | Yes | For SL/SL-M orders |
| Price Type | Varies | Depends on broker support |
| Product | No | Cannot change MIS to CNC etc. |
| Symbol | No | Cannot change symbol |
| Action | No | Cannot change BUY to SELL |

## Notes

- Only **open/pending orders** can be modified
- Completed, cancelled, or rejected orders cannot be modified
- Some brokers may have restrictions on modification frequency
- The order must be in a **modifiable state** (not in transit)
- If you need to change action (BUY/SELL), cancel and place a new order
- For F&O orders, ensure the modified quantity is a valid lot size

## Error Scenarios

| Error | Cause |
|-------|-------|
| Order not found | Invalid order ID |
| Order not modifiable | Order already executed/cancelled |
| Invalid price | Price out of circuit limits |
| Invalid quantity | Not a valid lot size for F&O |

---

**Back to**: [API Documentation](../README.md)
