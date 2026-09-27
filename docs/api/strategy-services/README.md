# Strategy Module API

The `/strategy` module runs multi-leg options strategies with end-to-end risk management, plus a signal-driven mode for TradingView alerts. Two surfaces reach it from outside the browser:

- an API-key surface under `/api/v1/strategy/`, defined in `restx_api/strategy.py` and validated by `restx_api/strategy_schema.py`
- a public webhook at `/strategy/webhook/<token>`, whose validation pipeline is `services/strategy_module/webhook.py`

Building a strategy stays in the browser wizard at `/strategy`. The API-key surface is lifecycle plus reads only. Nothing on it can create a strategy, edit its configuration, enable live trading, rotate a webhook token, or delete anything.

## Endpoint Inventory

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/strategy/list` | [List strategies](./list.md) |
| POST | `/api/v1/strategy/status` | [One strategy and its current run](./status.md) |
| POST | `/api/v1/strategy/start` | [Start a run](./start.md) |
| POST | `/api/v1/strategy/stop` | [Stop the current run](./stop.md) |
| POST | `/api/v1/strategy/close_all` | [Close every leg](./close_all.md) |
| POST | `/api/v1/strategy/close_leg` | [Close one leg](./close_leg.md) |
| POST | `/api/v1/strategy/runs` | [Run history](./runs.md) |
| POST | `/api/v1/strategy/orders` | [Order history](./orders.md) |
| POST | `/api/v1/strategy/events` | [Risk-event audit trail](./events.md) |
| POST | `/strategy/webhook/<token>` | [Public webhook](./webhook.md) |

Every `/api/v1/strategy/` route is a POST with the identifier in the JSON body. External platforms such as TradingView, Excel and ChartInk cannot always choose a method or set a header, so there is no GET form and no path parameter.

The public webhook is **not** under `/api/v1` and takes no `apikey`. The URL token identifies the strategy.

## Seven Rules That Cost Money If You Get Them Wrong

1. **`mode` is required on `/start` and is never defaulted.** Omitting it is a 400, not a live order. The schema declares it `required=True` with no `load_default`, and no layer supplies a fallback.
2. **Live is opt-in per strategy.** A strategy is created sandbox-only. `mode: "live"` is refused with a 409 until the operator enables live trading on the strategy page.
3. **A strategy that is not yours returns 404, never 403.** The response is byte-identical to one for a strategy that does not exist, so the id space cannot be probed.
4. **No endpoint returns a webhook token.** Only its SHA-256 digest is stored. The plaintext is shown once, at creation and at rotation, in the browser.
5. **An accepted `/stop` is not necessarily flat.** A 200 response with
   `stop_pending: true` means the stop request is durable and its exits were
   accepted, but the run remains open, subscribed and managed until fills prove
   every owned position is flat. A 409 can also carry `stop_pending: true` when
   an unfilled entry or refused exit still needs management. Read that flag and
   the per-leg outcomes; never infer flatness from the HTTP status.
6. **`acknowledged: false` is not an order rejection.** The broker accepted the
   entry, but its broker id and status could not be written back after a retry.
   The durable pending intent and a structured critical `order_ack_unrecorded`
   event remain. The dispatch call immediately binds only the exact named row;
   a bounded shared open-run sweep retries and broker-polls it if needed.
   Conflicts keep the run open and reserved.
7. **Final P&L is written only after confirmed flatness.** Exact, priced order
   reference groups are authoritative, including an exact zero. If durable
   fills have no usable price and no checkpoint that witnessed the same owner
   shape and quantities, recovery retains the known portion and records a
   critical manual-reconciliation event instead of inventing a value.

## Authentication

Every `/api/v1/strategy/` request carries the OpenAlgo API key as `apikey` in the JSON body. The key resolves to the owning user, and every strategy read is scoped to that user.

```json
{
  "apikey": "<your_app_apikey>",
  "strategy_id": 7
}
```

An invalid or unknown key returns 403 with `Invalid openalgo apikey`. A missing key is a schema failure and returns 400.

## Response Envelope

Success:

```json
{
  "status": "success"
}
```

Error:

```json
{
  "status": "error",
  "message": "Strategy not found"
}
```

On a schema validation failure, `message` is an object keyed by field name rather than a string:

```json
{
  "status": "error",
  "message": {
    "mode": ["Missing data for required field."]
  }
}
```

## Status Codes

| Code | Meaning |
|---|---|
| 200 | Handled successfully |
| 400 | Schema validation failed, or the engine refused the request as badly configured |
| 403 | `Invalid openalgo apikey` |
| 404 | `Strategy not found`, whether it does not exist or belongs to somebody else |
| 409 | State conflict: not running, already running, or live trading not enabled |
| 429 | Flask-Limiter rejected the request |
| 500 | `An unexpected error occurred` |

409 rather than 400 is deliberate wherever the payload is fine and the state is not: the caller's fix is to change the strategy's state, not the request.

## Rate Limits

The `/api/v1/strategy/` routes use `API_RATE_LIMIT`, the same budget as the rest of the v1 surface. The module default when the variable is unset is `10 per second`; `.sample.env` ships `100 per second`. See [rate limiting](../rate-limiting.md).

The public webhook is limited by the route in front of the pipeline.
`rate_limited` is a member of the result vocabulary and answers 429. Because
that guard and the declared-size 413 run before the validation pipeline,
neither preflight refusal writes a durable webhook audit row.

## Vocabularies

Most of these tuples live in `database/strategy_module_db.py`. The four the request schemas validate against, `RUN_MODES`, `STRATEGY_STATUSES`, `EVENT_KINDS` and `EVENT_SEVERITIES`, are imported from there by `restx_api/strategy_schema.py`, so those four cannot drift apart from the store. Products, price types, quantity modes, universe tabs and leg segments are configuration vocabularies owned by `blueprints/strategy_module.py`, because the store has no opinion on a leg's shape: legs are a JSON column.

### Strategy kinds

`batch`, `signal`

A batch strategy is a multi-leg spread entered and exited as a unit, driven by `start` and `stop`. A signal strategy moves one leg at a time, driven by `long_entry`, `long_exit`, `short_entry` and `short_exit`. Each kind refuses the other's vocabulary.

### Universe tabs

`weekly_monthly`, `monthly_only`, `stocks_fno`, `mcx`

The instrument universe a strategy was built from. It is not decoration: it decides which segments a leg may use. A configuration saved without a tab has one derived from its own legs rather than defaulted, so a caller is never refused about a field it did not set.

### Leg segments

`options`, `futures`, `cash`

A batch leg's segment must be one its universe tab offers. **Cash is offered on `stocks_fno` only**: an index has no cash instrument of its own and an MCX commodity has no spot, so a cash leg on either tab names a symbol the master contract does not list. A signal leg takes `cash` or `futures` only; there is no `options` segment in signal mode, and an exact option contract is named as a symbol instead. A signal leg's segment and its exchange must agree, so cash on a derivative venue is refused rather than ignored.

### Directions

`both`, `long_only`, `short_only`

The signal-mode direction filter. Ignored for batch strategies.

### Run modes

`live`, `sandbox`

Exact and case-sensitive. `LIVE` is not `live`, and a near miss such as `paper` is refused rather than read as sandbox.

### Strategy statuses

`stopped`, `running`, `paused`, `errored`

### Trigger sources

`manual`, `webhook`, `scheduler`

A run started through this API records `manual`: an API-key start is a person asking for it right now.

### Stop reasons

`manual`, `scheduler`, `overall_sl`, `overall_target`, `lock_profit`, `eod`, `expiry`, `daily_loss_limit`, `tick_stale`, `recovery_failed`, `error`

### Order kinds

`entry`, `exit_sl`, `exit_target`, `exit_trail`, `exit_overall_sl`, `exit_overall_target`, `exit_lock_profit`, `exit_eod`, `exit_expiry`, `exit_daily_loss_limit`, `exit_close_all`, `exit_leg_manual`, `exit_recovery`, `exit_signal`

### Event kinds an operator must not ignore

The full list is in [`/events`](./events.md). These transitions are especially
important to an operator:

- **`run_stop_requested`** (`info`) - the request is durable and new signal
  entries are gated. It is not proof that the broker is flat; wait for
  `run_stopped` or inspect the pending outcomes.

- **`run_stop_failed`** (`critical`) - the broker refused the exit orders of a
  stop. The run is still open and **still holding those positions**. It is the
  one lifecycle event that means the opposite of what a stop usually means.
- **`order_ack_unrecorded`** (`critical`) - the broker accepted an order but
  its acknowledgement could not be written. Structured exact-row metadata is
  retained for immediate exact-row repair and the bounded shared open-run
  sweep. A missing or conflicting link never auto-finalises possible exposure.
- **`leg_expiry_fallback`** (`warn`) - the chain did not list the expiry rank
  the leg asked for, so a nearer one was used. A `next_week` leg trading the
  current week is a different trade from the one that was configured.
- **`flip_outgoing_exit_rejected`** (`critical`) - the outgoing side of a
  signal flip is still held. It remains an exact, managed owner and its exit is
  retryable; the replacement side does not erase it.

### Quantity modes

`lots`, `units`

`lots` multiplies the value by the contract's lot size from the master contract, so 5 lots of NIFTY is 5 x 65. The lot **count** is what is stored, so a strategy survives the exchange revising the lot size, as NIFTY did from 75 to 65. `units` is the number of shares or contracts outright. An unknown lot size in `lots` mode is an error, never a guess.

`qty_mode` is a **signal** leg field. A derivative venue defaults to `lots` and a cash venue to `units`; `units` may be set explicitly on a derivative, but `lots` on a cash venue is refused, because a cash instrument has no lot size to multiply by.

A **batch** leg has no `qty_mode` at all. Its `lots` count is multiplied by the master contract's lot size on every segment, cash included. A cash row's lot size is 1, so the count reads as a share count, but the multiplication is unconditional.

### Products

`CNC`, `NRML`, `MIS`

A strategy carries one product for every leg, and it is read as the **intent** rather than the literal: `MIS` is intraday everywhere, and anything else means carry the position, which is sent as `NRML` on a derivatives venue and `CNC` on cash. A basket mixing a cash leg and an option leg therefore works, and no leg is ever sent a product its venue refuses.

One combination is refused rather than translated: a **short** cash leg under a carrying product. Cash cannot be held short overnight, so anything that is not `MIS` would reach the venue as a naked short delivery. A batch leg with `position: "S"` on a cash segment is refused when the product is not `MIS`; a signal leg is refused at signal time instead, when the side actually being opened is known rather than the sides it accepts.

### Price types

`MARKET`

Only. Neither a strategy nor a leg carries a price, so a `LIMIT`, `SL` or `SL-M` entry would go out priced at zero. Exits are `MARKET` on every path regardless: a stop that cannot fill is not a stop.

### Order statuses

`pending`, `open`, `complete`, `cancelled`, `rejected`

### Event severities

`info`, `warn`, `critical`

### Event kinds

Lifecycle: `strategy_created`, `strategy_updated`, `webhook_token_rotated`, `live_enabled`, `live_disabled`, `webhook_locked`, `webhook_unlocked`, `run_started`, `run_paused`, `run_resumed`, `run_stop_requested`, `run_stopped`, `run_stop_failed`, `flip_outgoing_exit_rejected`, `close_all_manual`

Entry and exit: `leg_entry_placed`, `leg_entry_filled`, `leg_entry_rejected`, `leg_exit_placed`, `leg_exit_filled`, `leg_exit_rejected`, `leg_close_manual`, `leg_expiry_fallback`, `order_ack_unrecorded`

Per-leg risk: `leg_sl_hit`, `leg_target_hit`, `leg_trail_armed`, `leg_trail_advanced`

Strategy risk: `overall_sl_hit`, `overall_target_hit`, `lock_profit_armed`, `lock_profit_floor_advanced`, `lock_profit_triggered`, `trail_to_entry_activated`, `eod_squareoff`, `expiry_squareoff`

Tick source: `tick_source_switched_to_polling`, `tick_source_switched_to_ws`, `tick_source_stale`

Operational: `recovery_succeeded`, `recovery_failed`

### Webhook results

`ok`, `rejected_token`, `rejected_ip`, `rate_limited`, `rejected_dedupe`, `rejected_cooling_off`, `rejected_invalid_action`, `rejected_live_disabled`, `rejected_locked`, `rejected_payload`, `rejected_engine_error`

Each label's HTTP status and cause is documented on the [webhook page](./webhook.md).

## Timestamps

Timestamps are stored naive UTC and returned as ISO 8601 strings carrying an explicit `+00:00` offset, for example `2026-08-30T09:15:04.118332+00:00`. `entry_time` and `exit_time` on a strategy are wall-clock IST strings in `HH:MM` form.

Money fields are returned as JSON numbers, never as strings.

---

**Back to**: [API Documentation](../README.md)
