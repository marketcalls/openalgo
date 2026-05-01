# GTTOrderBook

List **active** GTT triggers for the authenticated user. Triggered, cancelled, expired, and rejected GTTs are filtered out at the broker layer — this endpoint only returns triggers that can still fire.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/gttorderbook
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/gttorderbook
Custom Domain:  POST https://<your-custom-domain>/api/v1/gttorderbook
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>"
}
```

## Sample cURL Request

```bash
curl -X POST http://127.0.0.1:5000/api/v1/gttorderbook \
  -H 'Content-Type: application/json' \
  -d '{
  "apikey": "<your_app_apikey>"
}'
```

## Sample API Response

```json
{
  "status": "success",
  "data": [
    {
      "trigger_id": "23132604291205",
      "trigger_type": "single",
      "status": "active",
      "symbol": "IDEA",
      "exchange": "NSE",
      "trigger_prices": [9.55],
      "last_price": 9.50,
      "legs": [
        {
          "action": "BUY",
          "quantity": 1,
          "price": 9.50,
          "pricetype": "LIMIT",
          "product": "CNC"
        }
      ],
      "created_at": "2026-04-29 12:18:42",
      "updated_at": "",
      "expires_at": ""
    },
    {
      "trigger_id": "23132604291213",
      "trigger_type": "two-leg",
      "status": "active",
      "symbol": "INFY",
      "exchange": "NSE",
      "trigger_prices": [1480, 1620],
      "last_price": 1550,
      "legs": [
        {
          "action": "SELL",
          "quantity": 5,
          "price": 1478,
          "pricetype": "LIMIT",
          "product": "CNC"
        },
        {
          "action": "SELL",
          "quantity": 5,
          "price": 1622,
          "pricetype": "LIMIT",
          "product": "CNC"
        }
      ],
      "created_at": "2026-04-29 12:25:11",
      "updated_at": "",
      "expires_at": ""
    }
  ]
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|--------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | `"success"` or `"error"` |
| data | array | List of active GTT entries (see below) |
| message | string | Error message (on failure) |

### GTT Entry

| Field | Type | Description |
|-------|------|-------------|
| trigger_id | string | Unique trigger ID assigned by the broker |
| trigger_type | string | `"single"` (one trigger) or `"two-leg"` (OCO) |
| status | string | Always `"active"` (this endpoint filters out non-active states) |
| symbol | string | Symbol in OpenAlgo format |
| exchange | string | Exchange code |
| trigger_prices | array of numbers | Trigger prices, sorted ascending. Single → `[trigger]`. OCO → `[stoploss_trigger, target_trigger]`. |
| last_price | number | LTP captured at place/last-modify time. `0` for brokers that don't expose it. |
| legs | array | Per-leg child order details (see below) |
| created_at | string | ISO/locale timestamp from broker |
| updated_at | string | Last-update timestamp (empty if never modified) |
| expires_at | string | Expiry timestamp (empty for brokers that don't expose an explicit expiry) |

### Leg Object

| Field | Type | Description |
|-------|------|-------------|
| action | string | `"BUY"` or `"SELL"` |
| quantity | integer | Order quantity |
| price | number | Child order limit price (`0` for MARKET-style legs) |
| pricetype | string | `"LIMIT"` or `"MARKET"` |
| product | string | `"CNC"` or `"NRML"` |

## Notes

- **Active-only filter** is applied at the broker mapper. Triggered, cancelled, expired, rejected, disabled, and deleted GTTs never appear in `data`.
- **Field semantics by trigger type**:
  - SINGLE → `trigger_prices` has one element; `legs` has one entry.
  - OCO → `trigger_prices` has two elements (sl first, tg second); `legs` has two entries in matching order.
- Some fields (`last_price`, `created_at`, `updated_at`, `expires_at`) depend on what the broker exposes — they may be `0` or empty for brokers that don't return them.

## Error Scenarios

| Error | Cause |
|-------|-------|
| `Invalid openalgo apikey` (403) | Bad / unrecognised API key |
| `GTT orders are not supported for broker 'X' yet` (501) | Broker doesn't ship a `gtt_api` module |
| `Sandbox GTT support not yet implemented` (501) | Analyzer mode is enabled |

## Related Endpoints

- [PlaceGTTOrder](./placegttorder.md) — Place a new GTT trigger
- [ModifyGTTOrder](./modifygttorder.md) — Modify an active GTT
- [CancelGTTOrder](./cancelgttorder.md) — Cancel an active GTT

---

**Back to**: [API Documentation](../README.md)
