# Strategy Close All

Exit every open leg at market and finalise the current run, recording that an operator closed everything.

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
  "exits": [
    {
      "leg_id": 1,
      "ok": true,
      "error": null
    },
    {
      "leg_id": 2,
      "ok": true,
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
| run_id | integer | The run that was closed |
| exits | array | Per-leg exit outcome |

Each object in `exits`:

| Field | Type | Description |
|-------|------|-------------|
| leg_id | integer | The leg's id within the strategy |
| ok | boolean | Whether the exit order was accepted |
| error | string or null | Rejection reason when `ok` is false |

## Status Codes

| Code | Cause |
|---|---|
| 200 | Exits were dispatched and the run was finalised |
| 400 | Schema validation failed |
| 403 | `Invalid openalgo apikey` |
| 404 | `Strategy not found` |
| 409 | `This strategy is not running`, or the engine refused the stop |
| 429 | Rate limited |
| 500 | `An unexpected error occurred` |

## Notes

- **A close whose exits the broker refused leaves the run open.** Same rule as [`/stop`](./stop.md): the positions are still there, so finalising would stop evaluating their stops while they are held. Read the per-leg `ok` flags and retry rather than treating a 2xx envelope as flat.
- **Same effect as [`/stop`](./stop.md), different audit trail.** Before the exits go out, a `close_all_manual` event is written with the message `Closed all legs from the API`. "The operator closed everything" reads differently from "the run was stopped" when reconstructing a session afterwards, which is why this is its own route rather than an alias.
- The run id is resolved from the strategy, never supplied by the caller.
- Everything else, including the exit mechanics and the 409 behaviour, is identical to `/stop`.
- The `close_all_manual` event is visible through [`/events`](./events.md), and can be filtered with `"kind": "close_all_manual"`.

## Use Cases

- **Operator intent**: record that a human flattened the book, not that a rule did
- **Kill-switch scripting**: pair with the browser kill switch for an auditable manual flatten
- **Incident response**: close a strategy and be able to prove afterwards who did it and when

---

**Back to**: [API Documentation](../README.md)
