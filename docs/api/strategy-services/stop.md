# Strategy Stop

Exit every open leg at market and finalise the strategy's current run.

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
| run_id | integer | The run that was stopped |
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
- `run_stopped` is not part of this response. A successful stop always ends the run; see [`/close_leg`](./close_leg.md) for the partial case.
- Finalising a run arms the [webhook](./webhook.md) cooling-off window, so an inbound `start` alert is refused for the next 30 seconds. That holds for every stop, not only the ones a webhook asked for, so a stale alert cannot re-enter the position that was just closed.
- The run's `pnl_peak` and `pnl_trough` are written on stop. `pnl_realized` is written on stop and then **reconciled from the order rows when the exit fills arrive**, because a stop does not wait for them: read it from [`/runs`](./runs.md) after the fills, not in the same breath as the stop.

## Use Cases

- **End of session**: flatten a strategy from a script rather than the browser
- **Risk override**: stop a strategy from an external monitor that has seen something the engine has not
- **Deployment**: square off before restarting the platform

---

**Back to**: [API Documentation](../README.md)
