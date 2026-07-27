# CancelGTTOrder

Cancel an active GTT trigger by its `trigger_id`. Cancelling an OCO removes both legs atomically.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/cancelgttorder
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/cancelgttorder
Custom Domain:  POST https://<your-custom-domain>/api/v1/cancelgttorder
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "strategy": "My GTT Strategy",
  "trigger_id": "23132604291205"
}
```

## Sample cURL Request

```bash
curl -X POST http://127.0.0.1:5000/api/v1/cancelgttorder \
  -H 'Content-Type: application/json' \
  -d '{
  "apikey": "<your_app_apikey>",
  "strategy": "My GTT Strategy",
  "trigger_id": "23132604291205"
}'
```

## Sample API Response

```json
{
  "status": "success",
  "trigger_id": "23132604291205"
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|--------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| strategy | Strategy identifier (used in event logs) | Mandatory | - |
| trigger_id | Active trigger ID returned by `PlaceGTTOrder` | Mandatory | - |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | `"success"` or `"error"` |
| trigger_id | string | Cancelled trigger ID |
| message | string | Error message (on failure) |

## Notes

- Only **active** GTTs can be cancelled. Already-triggered, expired, or previously cancelled GTTs cannot be cancelled again.
- Cancelling an **OCO** removes both legs (stoploss + target) atomically — there is no per-leg cancel.
- Cancellation is broker-side; once acknowledged, the trigger is removed and won't appear in subsequent `GTTOrderBook` calls (the orderbook is filtered to active-only).
- **Idempotency**: cancelling an already-cancelled trigger returns the broker's native response, which may be either `success` or an error like "Trigger not found" depending on the broker.

## Error Scenarios

| Error | Cause |
|-------|-------|
| `trigger_id is required` (400) | Missing or empty `trigger_id` |
| `Invalid openalgo apikey` (403) | Bad / unrecognised API key |
| `GTT orders are not supported for broker 'X' yet` (501) | Broker doesn't ship a `gtt_api` module |
| `Sandbox GTT support not yet implemented` (501) | Analyzer mode is enabled |
| `Failed to cancel GTT` (4xx/5xx) | Broker rejected — usually because the trigger is no longer active |

## Related Endpoints

- [PlaceGTTOrder](./placegttorder.md) — Place a new GTT trigger
- [ModifyGTTOrder](./modifygttorder.md) — Modify an active GTT
- [GTTOrderBook](./gttorderbook.md) — List active GTT triggers

---

**Back to**: [API Documentation](../README.md)
