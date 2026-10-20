# Strategy Close All

Record an operator's close-all request, persist the stop, exit every owned
position at market, and finalise only after confirmed flatness.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/strategy/close_all
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/strategy/close_all
Custom Domain:  POST https://<your-custom-domain>/api/v1/strategy/close_all
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "strategy_id": 7
}
```

## Sample cURL Request

```bash
curl -X POST http://127.0.0.1:5000/api/v1/strategy/close_all \
  -H 'Content-Type: application/json' \
  -d '{
  "apikey": "<your_app_apikey>",
  "strategy_id": 7
}'
```

## Sample API Response

```json
{
  "status": "success",
  "run_id": 42,
  "stop_pending": true,
  "exits": [
    {
      "leg_id": 1,
      "ok": true,
      "position_ref": "969bc536b1c14d15992f730c2c136d7a",
      "exit_owner": "live",
      "error": null
    },
    {
      "leg_id": 2,
      "ok": true,
      "position_ref": "80bb5fc9333f4922a582229f06a0fe45",
      "exit_owner": "live",
      "error": null
    }
  ]
}
```

## Sample API Response (Not Running)

```json
{
  "status": "error",
  "message": "This strategy is not running"
}
```

HTTP 409.

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| strategy_id | Strategy id, a positive integer | Mandatory | - |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| run_id | integer | The run the close-all request applies to |
| stop_pending | boolean | `true` while owned exposure still needs a fill, retry or reconciliation; `false` only after this call confirmed flatness |
| exits | array | Per-leg exit outcome |

Each object in `exits`:

| Field | Type | Description |
|-------|------|-------------|
| leg_id | integer | The leg's id within the strategy |
| ok | boolean | Whether the exit order was accepted |
| position_ref | string or null | Exact durable owner the exit targets |
| exit_owner | string | `live` or `superseded` for the outgoing side of a signal flip |
| symbol | string, optional | Held symbol, included when an unfilled entry is refused before dispatch |
| broker_order_id | string or null, optional | Broker id when available; `null` on an unfilled-entry refusal |
| error | string or null | Rejection reason when `ok` is false |

## Status Codes

| Code | Cause |
|---|---|
| 200 | The durable close-all was accepted. Read `stop_pending`; accepted working exits are not proof of flatness |
| 400 | Schema validation failed |
| 403 | `Invalid openalgo apikey` |
| 404 | `Strategy not found` |
| 409 | `This strategy is not running`, or the engine refused the stop |
| 429 | Rate limited |
| 500 | `An unexpected error occurred` |

## Notes

- **A close whose exits the broker refused leaves the run open.** Same rule as [`/stop`](./stop.md): the positions are still there, so finalising would stop evaluating their stops while they are held. Read the per-leg `ok` flags and retry rather than treating a 2xx envelope as flat.
- **Same stop mechanics as [`/stop`](./stop.md), different audit intent.** A
  `close_all_manual` event is written before the stop persistence and broker
  results. It proves an operator requested/attempted a close-all; it is not
  proof that the broker became flat. `run_stopped` is that terminal evidence.
  Its message is `Operator requested closure of all held legs`.
- The run id is resolved from the strategy, never supplied by the caller.
- Everything else, including pending-stop recovery, exact-owner exits and the
  409 behaviour, is identical to `/stop`.
- The `close_all_manual` event is visible through [`/events`](./events.md), and can be filtered with `"kind": "close_all_manual"`.

## Use Cases

- **Operator intent**: record that a human requested a flatten, then distinguish
  that request from the later confirmed-flat transition
- **Kill-switch scripting**: pair with the browser kill switch for an auditable manual flatten
- **Incident response**: close a strategy and be able to prove afterwards who did it and when

---

**Back to**: [API Documentation](../README.md)
