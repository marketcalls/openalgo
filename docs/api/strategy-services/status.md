# Strategy Status

One strategy: its full configuration including legs, and its current run if it has one.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/strategy/status
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/strategy/status
Custom Domain:  POST https://<your-custom-domain>/api/v1/strategy/status
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
curl -X POST http://127.0.0.1:5000/api/v1/strategy/status \
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
  "data": {
    "id": 7,
    "name": "NIFTY Short Straddle",
    "strategy_kind": "batch",
    "direction": "both",
    "universe_tab": "weekly_monthly",
    "underlying": "NIFTY",
    "underlying_exchange": "NSE_INDEX",
    "strategy_type": "intraday",
    "entry_time": "09:20",
    "exit_time": "15:10",
    "product": "NRML",
    "pricetype": "MARKET",
    "overall_sl_mtm": -5000.0,
    "overall_target_mtm": 8000.0,
    "lock_profit": null,
    "trail_sl_to_entry": false,
    "scheduler": null,
    "live_enabled": false,
    "webhook_locked": false,
    "webhook_ip_allowlist": null,
    "daily_loss_limit_inr": 10000.0,
    "status": "running",
    "current_run_id": 42,
    "created_at": "2026-08-24T04:11:52.104883+00:00",
    "updated_at": "2026-08-30T03:50:11.482913+00:00",
    "legs": [
      {
        "id": 1,
        "segment": "options",
        "position": "S",
        "lots": 1,
        "option_type": "CE",
        "strike_mode": "atm",
        "atm_offset": "ATM",
        "expiry": "weekly",
        "sl_pts": 30,
        "target_pts": 60,
        "trail": {"x": 10, "y": 5}
      },
      {
        "id": 2,
        "segment": "options",
        "position": "S",
        "lots": 1,
        "option_type": "PE",
        "strike_mode": "atm",
        "atm_offset": "ATM",
        "expiry": "weekly",
        "sl_pts": 30,
        "target_pts": 60,
        "trail": {"x": 10, "y": 5}
      }
    ]
  },
  "run": {
    "id": 42,
    "strategy_id": 7,
    "mode": "sandbox",
    "broker": "sandbox",
    "started_at": "2026-08-30T03:50:11.402118+00:00",
    "stopped_at": null,
    "stop_reason": null,
    "stop_requested_at": "2026-08-30T04:05:10.123456+00:00",
    "stop_requested_reason": "manual",
    "pnl_realized": 0.0,
    "pnl_peak": 0.0,
    "pnl_trough": 0.0,
    "trigger_source": "manual",
    "webhook_event_id": null,
    "resolved_expiries": {
      "1": "04-SEP-26",
      "2": "04-SEP-26"
    }
  }
}
```

## Sample API Response (Stopped Strategy)

```json
{
  "status": "success",
  "data": {
    "id": 7,
    "name": "NIFTY Short Straddle",
    "status": "stopped",
    "current_run_id": null,
    "legs": []
  },
  "run": null
}
```

The `data` object above is abridged for readability. A real response always carries every field listed below.

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| strategy_id | Strategy id, a positive integer | Mandatory | - |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| data | object | The strategy's full configuration, including `legs` |
| run | object or null | The current run, or `null` when the strategy is not running |

`data` carries the same fields as a [list](./list.md) row, with one omission and one addition. It does **not** carry `last_finalized_run`, which the list builds by joining each strategy's most recently finalised run; read the newest row from [`/runs`](./runs.md) instead. It adds:

| Field | Type | Description |
|-------|------|-------------|
| legs | array | The leg configuration as the wizard saved it |

Each leg carries `risk_unit`, `points` (the default) or `percent`, which governs that leg's `sl_pts`, `target_pts` and `trail` together. A percentage is measured against the leg's own entry price, so 2 on a short filled at 2500 is a stop at 2550. Every saved leg carries the field even when it was defaulted.

`run`:

| Field | Type | Description |
|-------|------|-------------|
| id | integer | Run id |
| strategy_id | integer | Owning strategy |
| mode | string | `live` or `sandbox`, fixed for the life of the run |
| broker | string | Broker the run is bound to, snapshotted at start. `sandbox` for a sandbox run |
| started_at | string | ISO 8601 UTC |
| stopped_at | string or null | ISO 8601 UTC, `null` while the run is open |
| stop_reason | string or null | One of the stop reasons, `null` while the run is open |
| stop_requested_at | string or null | ISO 8601 UTC set while a durable stop is pending; cleared after terminal finalization |
| stop_requested_reason | string or null | Reason for the pending stop. A populated value means new signal entries are gated and recovery will resume the stop |
| pnl_realized | number | Realized P&L written at confirmed-flat finalization; a critical recovery event says when only the known priced portion is authoritative |
| pnl_peak | number | Highest P&L the run reached |
| pnl_trough | number | Lowest P&L the run reached |
| trigger_source | string | `manual`, `webhook` or `scheduler` |
| webhook_event_id | integer or null | The `sm_webhook_event` row that caused this run, when a webhook started it |
| resolved_expiries | object or null | Leg id to the expiry resolved at start, as strings |

## Notes

- `run` is `null` whenever the strategy has no `current_run_id`, which is the normal state of a stopped strategy.
- While a run is open, `pnl_realized`, `pnl_peak` and `pnl_trough` are the values last written to the run row, not a live mark. The live figures come from the run's checkpoints.
- Once the strategy is stopped, the newest finalized row from [`/runs`](./runs.md)
  is authoritative for realized P&L, peak, trough, stop time and stop reason.
  A socket frame or checkpoint retained from before the stop must not override
  it; the stopped run has zero unrealized P&L.
- A populated `stop_requested_reason` means the stop is durable but not yet
  confirmed flat. The run remains current and managed; do not interpret a
  successful stop request as terminal until `stopped_at` is populated or `run`
  becomes `null`.
- Finalization uses exact order ownership and fill evidence. Unpriced exposure
  is never valued as zero merely because a broker numeric is missing. See
  [`/runs`](./runs.md) for recovery P&L authority rules.
- Expiries are resolved once at run start and held for the run, so a positional strategy does not roll to a new contract mid-run. `resolved_expiries` is that snapshot.
- The strategy's own `status` field and the presence of `run` are separate reads. Prefer `run` when you need to know whether anything is actually open.
- A strategy that is not yours returns 404 with `Strategy not found`, identical to one that does not exist.
- `data` never carries `webhook_token` or `webhook_token_hash`.

## Use Cases

- **Monitoring**: poll one strategy for its mode, broker and current run
- **Pre-flight**: confirm `live_enabled` before asking for a live start
- **Reconciliation**: read `resolved_expiries` to know exactly which contracts a run holds

---

**Back to**: [API Documentation](../README.md)
