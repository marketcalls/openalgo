# Strategy Close Leg

Exit one leg of the current run at market. The run continues with the rest.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/strategy/close_leg
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/strategy/close_leg
Custom Domain:  POST https://<your-custom-domain>/api/v1/strategy/close_leg
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>",
  "strategy_id": 7,
  "leg_id": 2
}
```

## Sample cURL Request

```bash
curl -X POST http://127.0.0.1:5000/api/v1/strategy/close_leg \
  -H 'Content-Type: application/json' \
  -d '{
  "apikey": "<your_app_apikey>",
  "strategy_id": 7,
  "leg_id": 2
}'
```

## Sample API Response

```json
{
  "status": "success",
  "run_id": 42,
  "leg_id": 2,
  "run_stopped": false,
  "exits": [
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

## Sample API Response (Last Open Leg)

```json
{
  "status": "success",
  "run_id": 42,
  "leg_id": 2,
  "run_stopped": true,
  "exits": [
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

## Sample API Response (Leg Not Open)

```json
{
  "status": "error",
  "message": "That leg is not open"
}
```

HTTP 409.

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| strategy_id | Strategy id, a positive integer | Mandatory | - |
| leg_id | The leg's id within the strategy, a positive integer | Mandatory | - |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| run_id | integer | The run the leg belongs to |
| leg_id | integer | The leg that was closed, echoed back |
| run_stopped | boolean | `true` only when this call observed the last owner already fill and terminal finalization succeeded. An accepted asynchronous exit normally returns `false` |
| exits | array | Exit outcome for the leg |

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
| 200 | The exit was dispatched |
| 400 | Schema validation failed, including a missing `leg_id` |
| 403 | `Invalid openalgo apikey` |
| 404 | `Strategy not found` |
| 409 | `This strategy is not running`, the engine refused the close (for example `Run is not active` or a leg that is not open), or the broker refused the exit order and the leg is still held |
| 429 | Rate limited |
| 500 | `An unexpected error occurred` |

## Notes

- **Leg ids are the ids the wizard assigned within the strategy**, the same values that appear in `legs[].id` on [`/status`](./status.md). They are not order ids and not run ids.
- **The run is resolved from the strategy**, so the caller never supplies a run id.
- `run_stopped` reports what this call could prove. Dispatch is not closure: a
  live broker normally acknowledges before its fill, so the last accepted exit
  returns `false` and its fill performs terminal finalization later. A sandbox
  market order can fill synchronously and return `true` in the same call.
- This endpoint deliberately has no whole-run pending-stop field. It closes one
  exact owner without creating a durable whole-run stop request.
- The accepted-dispatch audit event says `Operator requested closure of leg
  <leg_id>`. It does not say the leg closed; only the later confirmed fill can
  support completed wording or a terminal `run_stopped` event.
- **A refused exit is reported as a failure, not as a close.** A non-empty `exits` array is not success on its own; the per-leg `ok` flags carry whether the broker took the order. Telling an operator a leg has closed while the position is still on the book is worse than telling them nothing.
- **A refused exit stays retryable.** The leg is not marked as having an exit in flight, so its stop loss, its target and the scheduler's square-off can all still reach it.
- **Closing a leg by hand does not trigger trail-to-entry.** That rule answers the market moving against the book; an operator closing a leg is an override, and treating it as a signal would tighten every other leg's stop without being asked.
- A `leg_id` that names no open leg is a 409, not a 404. The strategy was found; the leg is simply not in a state that can be closed.
- The exit uses the symbol recorded in the run's own state, not a fresh resolution of the configuration.

## Use Cases

- **Legging out**: close the losing side of a spread and let the winner run
- **Manual repair**: remove one leg whose contract has become illiquid without flattening the strategy
- **Risk trimming**: reduce exposure without giving up the position entirely

---

**Back to**: [API Documentation](../README.md)
