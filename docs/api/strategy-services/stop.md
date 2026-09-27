# Strategy Stop

Persist a stop request, exit every owned position at market, and finalise the
current run only after fills confirm it is flat.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/strategy/stop
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/strategy/stop
Custom Domain:  POST https://<your-custom-domain>/api/v1/strategy/stop
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
curl -X POST http://127.0.0.1:5000/api/v1/strategy/stop \
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
| run_id | integer | The run the stop applies to. It remains current while `stop_pending` is true |
| stop_pending | boolean | `true` while owned exposure still needs a fill, retry or reconciliation; `false` only when this call confirmed flatness and won terminal finalization |
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
| 200 | The durable stop was accepted. `stop_pending: true` means exit fills are still outstanding; `false` means this call confirmed flatness and finalized |
| 400 | Schema validation failed |
| 403 | `Invalid openalgo apikey` |
| 404 | `Strategy not found` |
| 409 | `This strategy is not running`, the engine refused the stop (for example `Run is not active`), or the broker refused the exit orders and the run is still holding the positions |
| 429 | Rate limited |
| 500 | `An unexpected error occurred` |

## Notes

- **The caller never supplies a run id.** The run is resolved from the strategy's `current_run_id`. A caller-supplied run id would be a second thing to authorise, and getting it wrong would mean stopping a run that is not the live one.
- **409, not 400, when nothing is running.** The payload is fine; the state is not. The caller's fix is to start the strategy, not to correct the request.
- Exits go out at market. The symbol comes from each leg's own recorded state, never from re-resolving the configuration: an ATM offset resolved again hours later can name a different strike, and exiting a contract the run does not hold would open a new position instead of closing one.
- A leg that already has an exit on its way out is not sent a second one. The claim and the duplicate check happen in one hold of the run's lock, so two rules firing on the same leg cannot each send a covering order.
- **A leg whose entry has been accepted but not filled is not exited, and the stop is reported as refused.** There is no confirmed quantity to close, and sending the configured size the other way would be a naked position if that entry later cancels. The run stays open and managed; retry once the fill lands.
- **A stop whose exit orders were all refused does not close the run.** The positions are still at the broker, so finalising would release the strategy and stop evaluating their stops while they are open. The response reports which legs were refused and the run stays live and managed; retry the stop.
- A refused exit leaves the leg exitable rather than marking it as having an exit in flight, so a later stop, a stop loss, a target or the scheduler's square-off can still reach it.
- The stop request is written before API-key lookup or broker dispatch. If that
  write fails, the response has `stop_pending: false`, no exit is sent and the
  request can be retried. Once it succeeds, new signal entries are gated and a
  restart resumes the same reason.
- A 200 with `stop_pending: true` means accepted exits are working. The run
  stays current, subscribed and managed. A terminal fill retries the pending
  stop and only confirmed flatness emits `run_stopped`; a terminal rejection or
  cancellation emits `run_stop_failed` and leaves the exact owner retryable.
- `run_stopped` is an event, not a field in this response. Use `stop_pending`
  here and the run's `stopped_at`/pending-stop fields in [`/runs`](./runs.md).
- Confirmed-flat finalization arms the [webhook](./webhook.md) cooling-off
  window. An accepted pending stop does not claim that the position is gone.
- Final P&L is written from exact owner/fill evidence. Unpriced exposure is
  reported as unavailable or retained as a known portion with a critical
  manual-reconciliation event; it is never silently valued as zero.

## Use Cases

- **End of session**: flatten a strategy from a script rather than the browser
- **Risk override**: stop a strategy from an external monitor that has seen something the engine has not
- **Deployment**: square off before restarting the platform

---

**Back to**: [API Documentation](../README.md)
