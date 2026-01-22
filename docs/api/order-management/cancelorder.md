# CancelOrder

Cancel a specific open order by its order ID.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/cancelorder
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/cancelorder
Custom Domain:  POST https://<your-custom-domain>/api/v1/cancelorder
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "orderid": "250408001002736",
  "strategy": "Python"
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
| orderid | Order ID to cancel | Mandatory | - |
| strategy | Strategy identifier | Optional | - |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| orderid | string | Cancelled order ID |
| message | string | Error message (on failure) |
| mode | string | "live" or "analyze" |

## Notes

- Only **open/pending orders** can be cancelled
- Completed orders cannot be cancelled
- Orders that are being processed (in transit) may not be cancellable
- If the order is already cancelled, the API returns success
- For AMO (After Market Orders), cancellation rules may differ

## Error Scenarios

| Error | Cause |
|-------|-------|
| Order not found | Invalid order ID |
| Order not cancellable | Order already executed |
| Order in transit | Order being processed at exchange |

## Related Endpoints

- [CancelAllOrder](./cancelallorder.md) - Cancel all open orders at once

---

**Back to**: [API Documentation](../README.md)
