# Strategy Runs

Every activation of a strategy, newest first.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/strategy/runs
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/strategy/runs
Custom Domain:  POST https://<your-custom-domain>/api/v1/strategy/runs
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
curl -X POST http://127.0.0.1:5000/api/v1/strategy/runs \
  -H 'Content-Type: application/json' \
  -d '{
  "apikey": "<your_app_apikey>",
  "strategy_id": 7,
  "limit": 10
}'
```

## Sample API Response

```json
{
  "status": "success",
  "data": [
    {
      "id": 42,
      "strategy_id": 7,
      "mode": "sandbox",
      "broker": "sandbox",
      "started_at": "2026-08-30T03:50:11.402118+00:00",
      "stopped_at": "2026-08-30T09:40:02.771905+00:00",
      "stop_reason": "eod",
      "stop_requested_at": null,
      "stop_requested_reason": null,
      "pnl_realized": 3140.5,
      "pnl_peak": 4880.0,
      "pnl_trough": -1220.25,
      "trigger_source": "manual",
      "webhook_event_id": null,
      "resolved_expiries": {
        "1": "04-SEP-26",
        "2": "04-SEP-26"
      }
    },
    {
      "id": 39,
      "strategy_id": 7,
      "mode": "live",
      "broker": "zerodha",
      "started_at": "2026-08-29T03:50:04.118332+00:00",
      "stopped_at": "2026-08-29T06:12:44.900410+00:00",
      "stop_reason": "overall_sl",
      "stop_requested_at": null,
      "stop_requested_reason": null,
      "pnl_realized": -5024.0,
      "pnl_peak": 910.0,
      "pnl_trough": -5180.0,
      "trigger_source": "webhook",
      "webhook_event_id": 811,
      "resolved_expiries": {
        "1": "04-SEP-26",
        "2": "04-SEP-26"
      }
    }
  ]
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| strategy_id | Strategy id, a positive integer | Mandatory | - |
| limit | How many runs to return, 1 to 500 | Optional | 100 |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| data | array | Run objects, newest first by start time |

Each object in `data`:

| Field | Type | Description |
|-------|------|-------------|
| id | integer | Run id, usable as the `run_id` filter on [`/orders`](./orders.md) and [`/events`](./events.md) |
| strategy_id | integer | Owning strategy |
| mode | string | `live` or `sandbox`, fixed for the life of the run |
| broker | string | Broker the run was bound to, snapshotted at start. `sandbox` for a sandbox run |
| started_at | string | ISO 8601 UTC |
| stopped_at | string or null | ISO 8601 UTC, `null` while the run is still open |
| stop_reason | string or null | Why the run ended |
| stop_requested_at | string or null | ISO 8601 UTC set while a durable stop is pending; cleared when the terminal transition succeeds |
| stop_requested_reason | string or null | Pending stop reason. While populated, new signal entries are refused and recovery resumes the stop |
| pnl_realized | number | Realized P&L written at confirmed-flat finalization. Recovery can retain only the known priced portion and emit a critical manual-reconciliation event when valuation evidence is incomplete |
| pnl_peak | number | Highest P&L the run reached |
| pnl_trough | number | Lowest P&L the run reached |
| trigger_source | string | `manual`, `webhook` or `scheduler` |
| webhook_event_id | integer or null | The inbound webhook that caused this run, when one did |
| resolved_expiries | object or null | Leg id to the expiry resolved at start, keyed by string |

### Stop reasons

`manual`, `scheduler`, `overall_sl`, `overall_target`, `lock_profit`, `eod`, `expiry`, `daily_loss_limit`, `tick_stale`, `recovery_failed`, `error`

## Notes

- Rows are ordered by start time, **newest first**.
- **`limit` is bounded rather than clamped.** A value below 1 or above 500 is a 400, so a caller learns the value was refused. The lower bound is not cosmetic: SQLite reads a negative `LIMIT` as "no limit", so an unbounded field would let `limit: -1` serialize every run the strategy has ever had.
- The run at the top of the list is the current one only while `stopped_at` is `null`. Compare against `current_run_id` from [`/status`](./status.md) if you need certainty.
- `stop_requested_at` and `stop_requested_reason` distinguish a durable pending
  stop from an ordinary running run. The run remains current, subscribed and
  managed until exact owner quantities prove it is flat. Terminal finalization
  atomically writes `stopped_at`/`stop_reason`, releases the strategy and clears
  both request fields.
- `pnl_peak` and `pnl_trough` are authoritative only once the run has stopped. While a run is open, the in-process state and its checkpoints are the authority, not these columns.
- **An overall threshold triggers an exit; it does not promise the realized
  result.** Aggregate risk is evaluated after each one-symbol tick from the
  basket's rolling latest-known LTP marks, not a guaranteed simultaneous basket
  snapshot. MARKET exits fill at the available bid/ask, and spread, movement or
  sequential leg placement can make `pnl_realized` differ from the threshold
  and from `pnl_peak`/`pnl_trough`. A run triggered by the combined target keeps
  `stop_reason: "overall_target"` even when its final realized P&L is below that
  target.
- **Final P&L follows evidence, not timing.** Exact priced `position_ref` groups
  override a stale checkpoint, including an exact zero. If durable fills prove
  exposure but have no usable price, a checkpoint total is used only when its
  owner shape and quantities exactly match what recovery rebuilt. Otherwise the
  known priced portion is retained and a critical `recovery_succeeded` event
  calls for manual P&L reconciliation.
- A signal-mode strategy has one run per platform session rather than one per
  entry/exit round trip: the first signal after the configured session boundary
  opens it and the scheduled square-off closes it.

## Use Cases

- **Performance review**: pull the last N runs and their realized P&L
- **Post-mortem**: find which runs ended on `overall_sl` or `daily_loss_limit`
- **Drill-down**: take a `run_id` from here into [`/orders`](./orders.md) or [`/events`](./events.md)

---

**Back to**: [API Documentation](../README.md)
