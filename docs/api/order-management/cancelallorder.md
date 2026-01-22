# CancelAllOrder

Cancel all open orders and trigger pending orders in a single request.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/cancelallorder
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/cancelallorder
Custom Domain:  POST https://<your-custom-domain>/api/v1/cancelallorder
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
  "status": "success",
  "message": "Canceled 5 orders. Failed to cancel 0 orders.",
  "canceled_orders": [
    "250408001042620",
    "250408001042667",
    "250408001042642",
    "250408001043015",
    "250408001043386"
  ],
  "failed_cancellations": []
}
```

## Sample API Response (Partial Success)

```json
{
  "status": "success",
  "message": "Canceled 3 orders. Failed to cancel 2 orders.",
  "canceled_orders": [
    "250408001042620",
    "250408001042667",
    "250408001042642"
  ],
  "failed_cancellations": [
    {
      "orderid": "250408001043015",
      "reason": "Order in transit"
    },
    {
      "orderid": "250408001043386",
      "reason": "Order already executed"
    }
  ]
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
| message | string | Summary of cancellation results |
| canceled_orders | array | List of successfully cancelled order IDs |
| failed_cancellations | array | List of orders that failed to cancel |
| mode | string | "live" or "analyze" |

### Failed Cancellations Array Fields

| Field | Type | Description |
|-------|------|-------------|
| orderid | string | Order ID that failed to cancel |
| reason | string | Reason for failure |

## Notes

- Cancels **all open orders** including:
  - Open limit orders
  - Pending trigger orders (SL, SL-M)
  - AMO orders (if supported by broker)
- Orders that are **already executed** or **in transit** cannot be cancelled
- The API returns success even if some orders fail to cancel
- Use **strategy** parameter to track which strategy initiated the cancellation
- This is a **bulk operation** - use with caution in production

## Use Cases

- **Emergency exit**: Cancel all pending orders when market moves unexpectedly
- **End of day cleanup**: Cancel unfilled orders before market close
- **Strategy reset**: Clear all pending orders before starting fresh

---

**Back to**: [API Documentation](../README.md)
