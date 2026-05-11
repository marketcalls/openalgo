# BracketOrder

Place a native bracket order with automatic target and stop-loss placement. Bracket orders provide a way to place an entry order along with two exit orders (target and stop-loss) in an OCO (One-Cancels-Other) fashion.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/bracketorder
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/bracketorder
Custom Domain:  POST https://<your-custom-domain>/api/v1/bracketorder
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "Python",
  "symbol": "SBIN",
  "action": "BUY",
  "exchange": "NSE",
  "product": "MIS",
  "quantity": 1,
  "price_type": "MARKET",
  "target_type": "points",
  "target_value": 5,
  "sl_type": "points",
  "sl_value": 3
}
```

## Sample cURL Request

```bash
curl -X POST http://127.0.0.1:5000/api/v1/bracketorder \
  -H 'Content-Type: application/json' \
  -d '{
  "apikey": "<your_app_apikey>",
  "strategy": "Python",
  "symbol": "SBIN",
  "action": "BUY",
  "exchange": "NSE",
  "product": "MIS",
  "quantity": 1,
  "price_type": "MARKET",
  "target_type": "points",
  "target_value": 5,
  "sl_type": "points",
  "sl_value": 3
}'
```

## Request Body Fields

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| strategy | Strategy identifier | Optional | "Python" |
| symbol | Trading symbol | Mandatory | - |
| action | Order action: BUY or SELL | Mandatory | - |
| exchange | Exchange code: NSE, BSE, NFO, MCX, CRYPTO etc. | Mandatory | - |
| product | Product type: MIS, CNC, NRML | Mandatory | - |
| quantity | Order quantity | Mandatory | - |
| price_type | Price type: MARKET or LIMIT | Mandatory | - |
| price | Entry price (required for LIMIT orders) | Optional | 0 |
| target_type | Type of target: points, percentage, absolute | Mandatory | - |
| target_value | Value of target based on target_type | Mandatory | - |
| sl_type | Type of stop-loss: points, percentage, absolute | Mandatory | - |
| sl_value | Value of stop-loss based on sl_type | Mandatory | - |

## Status and Management Endpoints

### Get Bracket Order Status
**URL**: `GET /api/v1/bracketorder/status?bo_id=<bo_id>&apikey=<apikey>`

### Cancel Bracket Order
**URL**: `DELETE /api/v1/bracketorder?bo_id=<bo_id>&apikey=<apikey>`

## Lifecycle Logic

1. **Entry Placement**: Places the initial entry order (MARKET or LIMIT).
2. **Fill Monitoring**: Background manager monitors the entry order for execution.
3. **Exit Leg Placement**: Once filled, it automatically calculates and places:
   - A **LIMIT** order for the Target.
   - An **SL-M** order for the Stop-Loss.
4. **OCO (One-Cancels-Other)**:
   - If Target hits: Stop-Loss order is automatically cancelled.
   - If Stop-Loss hits: Target order is automatically cancelled.
5. **Auto-Cancel**: If the entry order is not filled within 2 hours (default), it is automatically cancelled.

## Notes
- Works in both **Sandbox (Analyze Mode)** and **Live Mode**.
- Polling interval is configurable via `BO_POLL_INTERVAL_SECONDS` in `.env` (default: 3s).
- Native Bracket Orders are simulated internally by OpenAlgo to provide support across all brokers, even those that don't natively support BO/CO.

---

**Back to**: [API Documentation](../README.md)
