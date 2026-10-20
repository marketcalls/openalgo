# Strategy Events

The risk-event audit trail for a strategy, newest first.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/strategy/events
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/strategy/events
Custom Domain:  POST https://<your-custom-domain>/api/v1/strategy/events
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
curl -X POST http://127.0.0.1:5000/api/v1/strategy/events \
  -H 'Content-Type: application/json' \
  -d '{
  "apikey": "<your_app_apikey>",
  "strategy_id": 7,
  "run_id": 42,
  "severity": "warn",
  "limit": 100
}'
```

## Sample API Response

```json
{
  "status": "success",
  "data": [
    {
      "id": 2041,
      "run_id": 42,
      "strategy_id": 7,
      "ts": "2026-08-30T06:21:40.104112+00:00",
      "kind": "leg_sl_hit",
      "severity": "warn",
      "leg_id": 1,
      "message": "stop loss hit: last price 172.8 is at or above the stop 172.35 on a short position",
      "payload": null
    },
    {
      "id": 2038,
      "run_id": 42,
      "strategy_id": 7,
      "ts": "2026-08-30T03:50:11.702884+00:00",
      "kind": "leg_entry_placed",
      "severity": "info",
      "leg_id": 1,
      "message": "Entry SELL 75 NIFTY04SEP2624500CE placed",
      "payload": null
    },
    {
      "id": 2037,
      "run_id": 42,
      "strategy_id": 7,
      "ts": "2026-08-30T03:50:11.480221+00:00",
      "kind": "run_started",
      "severity": "info",
      "leg_id": null,
      "message": "Run started in sandbox mode (manual)",
      "payload": null
    }
  ]
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| strategy_id | Strategy id, a positive integer | Mandatory | - |
| run_id | Narrow the result to one run, a positive integer | Optional | null (every run) |
| kind | Filter by event kind. Must be a member of the event-kind vocabulary | Optional | null (no filter) |
| severity | `info`, `warn` or `critical` | Optional | null (no filter) |
| limit | How many events to return, 1 to 1000 | Optional | 500 |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| data | array | Event objects, newest first by timestamp |

Each object in `data`:

| Field | Type | Description |
|-------|------|-------------|
| id | integer | Event row id |
| run_id | integer or null | Run the event belongs to. `null` for configuration-layer events such as `strategy_created` |
| strategy_id | integer | Owning strategy |
| ts | string | ISO 8601 UTC |
| kind | string | What happened |
| severity | string | `info`, `warn` or `critical` |
| leg_id | integer or null | Leg the event concerns, when it concerns one |
| message | string | Human-readable description |
| payload | object or null | Structured detail. `null` on most events |

### Event kinds

Lifecycle: `strategy_created`, `strategy_updated`, `webhook_token_rotated`, `live_enabled`, `live_disabled`, `webhook_locked`, `webhook_unlocked`, `run_started`, `run_paused`, `run_resumed`, `run_stop_requested`, `run_stopped`, `run_stop_failed`, `flip_outgoing_exit_rejected`, `close_all_manual`

`run_stop_requested` says the stop intent is durable and new signal entries are
gated; it is not proof of flatness. `run_stopped` is the terminal transition
after the engine has confirmed that no owned position remains. `run_stop_failed`
is critical whenever a pending stop could not make progress, including an
unfilled entry, a refused order, or an asynchronous rejection/cancellation. The
run remains open and managed for a retry.

`flip_outgoing_exit_rejected` is critical. It means the old side of a signal
flip is still held under its exact `position_ref`, remains managed, and can be
targeted by another exit even though the replacement side is also live.

Entry and exit: `leg_entry_placed`, `leg_entry_filled`, `leg_entry_rejected`, `leg_exit_placed`, `leg_exit_filled`, `leg_exit_rejected`, `leg_close_manual`, `leg_expiry_fallback`, `order_ack_unrecorded`

Manual close events describe accepted intent only. `close_all_manual` uses
`Operator requested closure of all held legs`, and `leg_close_manual` uses
`Operator requested closure of leg <leg_id>`. Completed wording is reserved
for the later fill-confirmed `run_stopped` transition.

`leg_expiry_fallback` is written at `warn` severity, before the entry goes out, when the chain did not list the expiry rank the leg asked for and a nearer one was used. A `next_week` leg trading the current week is a different trade from the one that was configured, so it is said out loud rather than inferred from the symbol afterwards.

`order_ack_unrecorded` is critical. The acknowledgement write failed twice.
Its structured `payload` carries versioned exact `order_id`, `run_id`, `leg_id`,
`broker_order_id`, `accepted`, `status` and `reject_reason` facts. The dispatch
call immediately uses those facts to bind only the named pending row. The
shared five-second scheduler job also rotates through a bounded page of every
ordinary open run, replays a held frame, and broker-polls an accepted working
order when no frame remains. Recovery and pending-stop polling use the same
idempotent repair. Later terminal facts are preserved; missing or conflicting
linkage leaves the run open and reserved rather than asserting flatness.
Rejected acknowledgements are repaired to `rejected` without creating
exposure.

Per-leg risk: `leg_sl_hit`, `leg_target_hit`, `leg_trail_armed`, `leg_trail_advanced`

Strategy risk: `overall_sl_hit`, `overall_target_hit`, `lock_profit_armed`, `lock_profit_floor_advanced`, `lock_profit_triggered`, `trail_to_entry_activated`, `eod_squareoff`, `expiry_squareoff`

For a synchronous combined-target exit, lifecycle order is meaningful:
`overall_target_hit` records the marked breach, every accepted
`leg_exit_placed` records dispatch, and only the later `run_stopped` event proves
all exact owners filled flat. Terminal finalization preserves
`stop_reason="overall_target"`; a synchronous fill cannot publish
`run_stopped` ahead of the accepted placement that made the basket flat.

Tick source: `tick_source_switched_to_polling`, `tick_source_switched_to_ws`, `tick_source_stale`

Operational: `recovery_succeeded`, `recovery_failed`

Operational severity carries meaning. `recovery_failed` can mean an ordinary
malformed run with no proven exposure was finalised, or that proven exposure
could not fit the live-plus-superseded state and was deliberately left database
open and reserved for manual reconciliation. A `recovery_succeeded` event can
also be critical when a run was recovered with only the known portion of P&L
because one or more fills were unpriced and no matching checkpoint witnessed
the same owners and quantities.

## Notes

- Rows are ordered by timestamp, **newest first**.
- **The trail is append-only.** Nothing updates or deletes an event row, so what you read is what the engine wrote at the time.
- **`limit` is bounded rather than clamped.** A value below 1 or above 1000 is a 400, so a caller learns the value was refused. SQLite reads a negative `LIMIT` as "no limit", so an unbounded field would let `limit: -1` serialize every event the strategy has ever recorded. The engine writes an event per risk transition per leg, which can be a whole platform session's worth.
- **An out-of-vocabulary `kind` or `severity` is a 400**, not an empty list. Send a value from the lists above.
- **A `run_id` belonging to another strategy matches nothing.** The query is scoped to this strategy before the run filter is applied.
- Configuration-layer events share the table with runtime ones and carry `run_id: null`. Filtering by `run_id` therefore excludes them.
- The `close_all_manual` event written by [`/close_all`](./close_all.md) records the request before broker exits settle; use `run_stopped` as confirmed-flat evidence.
- `payload` is free-form JSON and is `null` on most events, `run_started` included. A scheduled **live** start that was refused because live trading is not enabled writes a `live_disabled` event carrying `{"trigger_source": "scheduler", "mode": "live"}`; `order_ack_unrecorded` carries the exact reconciliation fields documented above. Do not assume one shape across kinds.

## Use Cases

- **Post-mortem**: read every `critical` event on a run that ended badly
- **Alerting**: poll for `severity: "critical"` and forward to an external monitor
- **Rule verification**: confirm that `lock_profit_armed` and `lock_profit_floor_advanced` fired where they should have

---

**Back to**: [API Documentation](../README.md)
