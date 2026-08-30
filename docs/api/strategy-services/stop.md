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
| 409 | `This strategy is not running`, or the engine refused the stop, for example `Run is not active` |
| 429 | Rate limited |
| 500 | `An unexpected error occurred` |

## Notes

- **The caller never supplies a run id.** The run is resolved from the strategy's `current_run_id`. A caller-supplied run id would be a second thing to authorise, and getting it wrong would mean stopping a run that is not the live one.
- **409, not 400, when nothing is running.** The payload is fine; the state is not. The caller's fix is to start the strategy, not to correct the request.
- Exits go out at market. The symbol comes from each leg's own recorded state, never from re-resolving the configuration: an ATM offset resolved again hours later can name a different strike, and exiting a contract the run does not hold would open a new position instead of closing one.
- A leg that already has an exit on its way out is not sent a second one.
- `run_stopped` is not part of this response. A successful stop always ends the run; see [`/close_leg`](./close_leg.md) for the partial case.
- Finalising a run arms the [webhook](./webhook.md) cooling-off window, so an inbound `start` alert is refused for the next 30 seconds. That holds for every stop, not only the ones a webhook asked for, so a stale alert cannot re-enter the position that was just closed.
- The run's final `pnl_realized`, `pnl_peak` and `pnl_trough` are written on stop and readable from [`/runs`](./runs.md).

## Use Cases

- **End of session**: flatten a strategy from a script rather than the browser
- **Risk override**: stop a strategy from an external monitor that has seen something the engine has not
- **Deployment**: square off before restarting the platform

---

**Back to**: [API Documentation](../README.md)
