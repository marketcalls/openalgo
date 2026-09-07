# OpenAlgo Strategy Module and Risk Engine Reference

## Purpose and scope

This document describes the `/strategy` module: multi-leg options strategies
with end-to-end risk management, and the signal-driven mode that reacts to
individual TradingView alerts.

It is deliberately separate from
[`services_documentation.md`](services_documentation.md), which covers the
platform's general service layer. Read that one for order placement, market
data and account services; read this one for anything under
`services/strategy_module/`, `database/strategy_module_db.py`,
`blueprints/strategy_module.py`, `restx_api/strategy.py` and `services/risk/`.

Scope of this file:

- the shared risk core and why it is shared
- the two strategy kinds and how they differ
- the data model
- every module's public surface, with exact signatures
- the lifecycle of a run, from start through ticks to square-off and recovery
- the invariants that must not be broken, and why each one exists
- what is deliberately not built yet

## Sources of truth

Code always wins over this document. When they disagree, the code is right and
this file is stale.

| Concern | File |
|---|---|
| Schema, store, vocabularies | `database/strategy_module_db.py` |
| Risk rules (shared) | `services/risk/` |
| Rule translation | `services/strategy_module/risk_adapter.py` |
| Run lifecycle, tick decisions | `services/strategy_module/engine.py` |
| Signal-mode protocol | `services/strategy_module/signals.py` |
| Live run state | `services/strategy_module/state.py` |
| Order placement | `services/strategy_module/order_dispatch.py` |
| Prices | `services/strategy_module/tick_feed.py` |
| Fills | `services/strategy_module/order_events.py` |
| Durability | `services/strategy_module/checkpoint.py`, `recovery.py` |
| Cron | `services/strategy_module/scheduler.py` |
| Public webhook | `services/strategy_module/webhook.py`, `webhook_bridge.py` |
| Broker-backed books | `services/strategy_module/views.py` |
| Contract resolution | `services/strategy_module/symbol_resolver.py` |
| Startup | `services/strategy_module/runtime.py` |
| Session API and validation | `blueprints/strategy_module.py` |
| API-key surface | `restx_api/strategy.py`, `restx_api/strategy_schema.py` |
| Public API reference | `docs/api/strategy-services/` |

Tests are the second source of truth, and several encode defects that were
deliberately not carried over. They are named in the code with a `PORTED
DEFECT` comment.

## Architecture

```
                     browser                TradingView / SDK / Excel
                        |                              |
        blueprints/strategy_module.py        restx_api/strategy.py
             (session cookie)                    (API key)
                        |                              |
                        +---------------+--------------+
                                        |
                         services/strategy_module/engine.py
                         services/strategy_module/signals.py
                                        |
        +----------------+--------------+--------------+----------------+
        |                |              |              |                |
   risk_adapter    order_dispatch   tick_feed    order_events      state
        |                |              |              |                |
   services/risk/   place_order /   websocket +    EventBus        in-process
   (SHARED)         sandbox         REST fallback  order.update    run state
                                        |
                              checkpoint.py / recovery.py
                                        |
                              database/strategy_module_db.py
```

The public webhook enters at `services/strategy_module/webhook.py`, which
validates and then hands off through `webhook_bridge.py` to the same engine.

## The shared risk core

`services/risk/` is the one place OpenAlgo decides whether a position has hit
its stop, taken its target, earned a tighter trailing stop, or whether a set of
positions has run past its combined limits.

**It performs no I/O of any kind.** No database, no broker, no market data, no
clock, no logging. Every input arrives as an argument and every decision leaves
as a return value. That is what lets the scalping terminal, Flow, this strategy
engine and a REST endpoint all sit on the same rules without a service layer in
between, and what makes the rules testable without a running platform.

```python
from services.risk import (
    PositionRisk, PositionDecision, evaluate_position,
    AggregateRisk, AggregateDecision, evaluate_aggregate,
    aggregate_pnl, trail_stops_to_entry,
    stop_from_points, target_from_points, Side, TrailMode, BreachReason,
)
```

The strategy module never calls these directly. `risk_adapter.py` translates in
both directions and is the only file that knows both vocabularies:

```
leg state  -> PositionRisk   -> evaluate_position  -> PositionDecision  -> leg state
run state  -> AggregateRisk  -> evaluate_aggregate -> AggregateDecision -> run state
```

Golden vectors in `test/risk/vectors.json` bind the Python core to the
TypeScript copy in `frontend/src/hooks/useTrailingSL.ts`. Add a case there
whenever a rule changes, so the two cannot drift.

`aggregate_pnl` counts a position's realized P&L whether or not it is currently
open. A signal leg re-entered after a completed round trip carries that round
trip's result and is open again; counting realized only while closed made the
figure vanish the moment the next entry was placed, so a daily loss limit reset
on every flat moment and could never be reached. A position that never closed
carries zero there, so nothing else changes.

### Points or percent

Each leg carries `risk_unit`, either `points` (the default) or `percent`, and it
governs `sl_pts`, `target_pts` and both halves of `trail` together. A leg with
no `risk_unit` is a points leg, which is every leg written before the field
existed, so nothing stored has to change and legs remain JSON with no migration.

One toggle covers all three on purpose: a leg whose stop is a percentage of
entry and whose target is an absolute distance is far more likely to be a
mistake than an intention.

**The conversion happens in `risk_adapter` and nowhere else.** `services/risk/`
speaks one language, points from entry, and translating into it is the adapter's
whole job. A second unit inside the core would mean two ways to express the same
stop and two places to get it wrong, which is the rule the module already
follows for every other decision: consumers translate, they do not decide.

A percentage is measured against the leg's own entry price, so 2% on a short
filled at 2500 is a stop at 2550 and a 4% target is 2400. Percentages are capped
at 100 in the validator, because 150% of entry below a long's entry price is not
a wider stop, it is a negative price.

**A percent leg with no confirmed fill gets no levels at all.** A percentage of
an entry of zero is not a stop at the entry price, it is a stop that cannot be
computed yet, and inventing one would put it on top of the entry and fire it on
the first tick. The leg has no confirmed position in that state anyway.

The field names keep saying `pts` in both the wire format and the database. They
are wrong for a percent leg and they are kept anyway, because renaming them
would break every stored strategy and every existing caller for a cosmetic gain.
The unit is displayed beside the number everywhere an operator reads it.

### risk_adapter public surface

```python
leg_to_position_risk(leg: dict) -> PositionRisk
evaluate_leg(leg: dict, last_price: Any) -> PositionDecision      # writes back into leg
apply_leg_decision(leg: dict, decision: PositionDecision) -> None
run_pnl(state: dict) -> tuple[float, float]                       # (realized, unrealized)
run_to_aggregate_risk(state: dict, strategy: dict) -> AggregateRisk
evaluate_run(state: dict, strategy: dict) -> AggregateDecision    # writes back into state
apply_run_decision(state: dict, decision: AggregateDecision) -> None
trail_open_legs_to_entry(state: dict, triggering_leg_id: Any) -> list[str]
```

Two mappings in here are easy to get wrong:

- **A trailing stop's gap is `trail_step`, not `trail_trigger`.** An X-only
  configuration (fixed-distance trail) passes X for both. Passing 0 disables
  trailing entirely, because the core requires a positive step before it will
  move a stop at all.
- **`overall_sl_mtm` is stored positive and applied as a negative threshold.**
  It passes through unchanged; the core takes it the same way.

### Combined MTM is an exit trigger, not an execution guarantee

The combined stop, target and lock-profit rules evaluate the run's rolling
latest-known LTP mark. A tick for one symbol updates the matching leg and the
engine immediately evaluates the basket using that new mark plus the most
recent marks already held for the other legs. Independent WebSocket ticks are
not a simultaneous, exchange-atomic basket snapshot.

Crossing `overall_sl_mtm` or `overall_target_mtm` therefore proves that the
marked basket crossed the configured threshold and that an exit was requested.
It does not guarantee the same realized P&L. The covering MARKET orders execute
against the available side of the book (a BUY at the ask and a SELL at the bid),
and the spread, price movement and sequential leg placements can move the final
fills away from the trigger mark. The durable run keeps both truths: `pnl_peak`
and `pnl_trough` describe the marked path, while `pnl_realized` comes from the
confirmed entry and exit fills.

For the reported Run 12, the durable evidence proves a `513.00` peak, an
`overall_target` stop and `117.00` realized after both exits filled. It does not
retain sufficiently granular per-leg tick-arrival evidence to prove that mixed-
age marks caused the difference. The rolling calculation makes that a possible
contributor, but not an established cause for that run.

## The daily loss limit

`daily_loss_limit_inr` is a limit on the **session**, not on a run.
`overall_sl_mtm` cannot express it: that one is reset every time a run opens,
which for a signal or scheduled strategy is several times a day, so a strategy
could lose its whole budget three times over and open a fourth run.

The session is the one that began at `SESSION_EXPIRY_TIME` (03:00 IST by
default), not at midnight, because that is when OpenAlgo revokes broker tokens
and ends its own day. `services/strategy_module/session.py` holds that boundary;
the engine and the signal path both need it and neither may import the other.

Runs that have finished since the boundary contribute the figure on their row,
and the live run contributes what it is marked at. Crossing the limit squares
off and stops with `stop_reason="daily_loss_limit"`. The banked half is cached
and invalidated by `finish_run` and `reconcile_run_pnl`, because the reader is
the per-tick risk evaluation and under `NullPool` an uncached read is a real
database connection per tick.

## The two strategy kinds

`sm_strategy.strategy_kind` is `batch` (default) or `signal`. They share every
table and all the machinery for state, orders, risk and recovery. What differs
is the protocol, the leg shape and the run lifecycle.

| | batch | signal |
|---|---|---|
| Trigger | `start` enters every leg, `stop` exits every leg | one alert moves one leg |
| Leg shape | segment, position, lots, option type, strike mode, offset, expiry | symbol, exchange, side, qty, segment, expiry |
| Options | relative option legs and spreads | an exact option contract may be named, but there is no `options` segment, expiry-rank or strike resolution; spreads stay in batch mode |
| Quantity | the configured count multiplied by the exact `SymToken` lot size, on every segment including cash. A cash row's lot size is 1, so the count is a share count, but the multiplication is unconditional and nothing asserts the 1 | derivatives accept `qty_mode=lots` (multiplied by the exact `SymToken` lot size) or `qty_mode=units` (absolute quantity on a whole-lot boundary); cash is units only and uses the exact quantity |
| Run | one per start-to-stop cycle | one per platform session, opened by the first signal |
| Webhook actions | `start`, `stop` | `long_entry`, `long_exit`, `short_entry`, `short_exit` |
| Legs at run start | all entered together | inactive until a signal opens one |
| Order kinds | `entry` plus the risk, scheduler and manual `exit_*` kinds | `entry` and `exit_signal` |

Each kind refuses the other's action vocabulary. `signals.actions_for(kind)`
returns the accepted set and the webhook validates against it.

### Signal mode semantics

Three outcomes, and the difference between them is the design:

| Outcome | Answer | Example |
|---|---|---|
| Acted | 200, an order was placed | `long_entry` on a flat leg |
| No-op | 200 with a note | `long_entry` on a leg already long |
| Refused | 4xx | `short_entry` on a `long_only` strategy |

The no-op notes are `already_long`, `already_short`, `no_matching_position`,
`outside_entry_window` and `outside_trading_window`.

A no-op is answered as a success on purpose. An alert engine repeats itself, and
reporting a repeat as a failure invites a retry; a retry on an order path is how
one alert becomes two positions. A refusal is different: it means the signal
contradicts how the strategy is configured, which the operator should see.

Other signal-mode rules:

- **The side a leg is held comes from the signal that opened it**, never from
  configuration. A leg's configured `side` says which signals it *accepts*.
- **An opposite entry squares first, then opens.** Reversing without closing
  leaves both positions on the book.
- **A leg returns to `configured` after an exit**, not `closed`, so the same
  symbol can be signalled again in the same platform session. Its realized P&L accumulates on
  the leg, and `run_pnl` counts realized from any leg that has it.
- **Signal actions skip the webhook dedupe and cooling-off windows.** They exist
  because a repeated `start` would open a second position; signal mode is
  already idempotent by meaning, and a 60 second window would suppress a genuine
  long, short, long sequence and leave the position backwards.

## Data model

Six tables, all `sm_` prefixed. The prefix matters: this codebase already has
`strategy_portfolio`, `strategy_book`, `strategy_order_tags`,
`strategy_pending_fills` and the `/python` strategy host, none of which are
related to each other or to this module.

| Table | Purpose |
|---|---|
| `sm_strategy` | config: legs (JSON), risk parameters, scheduler, webhook token hash |
| `sm_strategy_run` | one activation, including durable pending-stop timestamp/reason and terminal P&L |
| `sm_strategy_order` | every durable order intent, its exact `position_ref`, acknowledgement, fills and rejection context |
| `sm_strategy_checkpoint` | periodic runtime snapshot, for crash recovery |
| `sm_webhook_event` | every request admitted to the webhook pipeline, accepted or rejected; route preflight 429/declared-size 413 refusals are not stored |
| `sm_strategy_event` | risk-event audit trail |

Conventions:

- **Timestamps are naive UTC**, rendered with an explicit offset at the
  boundary. SQLite does not preserve a timezone on a `DateTime` column whatever
  you pass it, so storing aware values hands back naive ones on the next read.
- **Money is `Numeric(18, 2)`**, converted to float by the `*_to_dict` helpers
  so `Decimal` never reaches `jsonify`.
- **`ondelete="CASCADE"` is decorative.** SQLite enforces foreign keys only
  under `PRAGMA foreign_keys=ON`, which this project never sets.
  `delete_strategy` removes children explicitly. This is correctness, not
  tidiness: SQLite reuses rowids, so an orphaned audit trail re-attaches itself
  to whichever strategy is created next and inherits the id.
- **Checkpoints are pruned.** They are written every few seconds for a whole
  session in a worker that never restarts. Recovery only reads the newest row.

Vocabularies live as tuples in `strategy_module_db.py` rather than SQL CHECK
constraints, because SQLite cannot alter a CHECK in place: `STRATEGY_KINDS`,
`DIRECTIONS`, `STRATEGY_TYPES`, `RUN_MODES`, `STRATEGY_STATUSES`,
`TRIGGER_SOURCES`, `STOP_REASONS`, `ORDER_KINDS`, `ORDER_STATUSES`,
`EVENT_KINDS`, `EVENT_SEVERITIES`, `WEBHOOK_RESULTS`.

### Store surface

```python
# strategies
create_strategy(user_id, config) -> (payload_with_webhook_token, error)
list_strategies(user_id, status=None, q=None) -> list[dict]
get_strategy(strategy_id, user_id) -> SmStrategy | None      # owner scoped
get_strategy_unscoped(strategy_id) -> SmStrategy | None      # engine only
update_strategy(strategy_id, user_id, changes) -> (dict, error)
delete_strategy(strategy_id, user_id) -> (bool, error)
set_strategy_status(strategy_id, status, run_id=None) -> bool
claim_strategy_for_run(strategy_id) -> bool                  # atomic start guard
release_strategy(strategy_id) -> bool
rotate_webhook_token(strategy_id, user_id) -> (token, error)
set_live_enabled(strategy_id, user_id, enabled) -> (bool, error)
set_webhook_locked(strategy_id, user_id, locked) -> (bool, error)
get_strategy_by_webhook_token(token) -> SmStrategy | None
clear_strategy_module_cache() -> None

# runs, orders, events, checkpoints, webhook audit
create_run(...) / finish_run(...) / finish_run_and_release_strategy(...) / get_run(run_id) / list_runs(...) / list_open_runs()
request_run_stop(run_id, reason) / reconcile_run_pnl(run_id)
record_order(run_id, leg_id, kind, order) / update_order(...) / transition_order_terminal(...) / list_orders(run_id)
list_orders_for_strategy(strategy_id, run_id=None)
get_order_by_broker_id(broker_order_id)
record_event(...) / list_events(...)
write_checkpoint(run_id, snapshot) / latest_checkpoint(run_id)
list_checkpoints(run_id, limit=1000, strategy_id=None) / prune_checkpoints(run_id, keep=200)
record_webhook_event(...) / list_webhook_events(strategy_id, limit=200)
```

`claim_strategy_for_run` is a single conditional UPDATE, not a read then a
write. Three triggers can start the same strategy at once (UI, scheduler,
webhook) and a check-then-set lets two of them both see `stopped` and both place
a full set of entries. The original this was ported from uses
`SELECT ... FOR UPDATE`, which SQLite parses and does not honour, so that guard
would have been silently absent.

## Run state

`services/strategy_module/state.py` holds live run state as a plain in-process
dict. That is an upgrade over the Redis original, not a compromise: `-w 1` is
hardcoded in `start.sh` and `install/install.sh` with no variable to raise it,
so exactly one process can own a run, and the network hop bought only latency on
the hottest path. Durability lives in `sm_strategy_checkpoint` plus `recovery`.

The stored shape is identical to the checkpoint's `leg_state` JSON, so a
snapshot round-trips without translation.

```python
get_state_lock(run_id) -> threading.Lock
new_position_ref() -> str
run_state(run_id)                       # context manager, yields the live dict or None
init_run_state(run_id, strategy_id, legs) -> dict
add_leg(run_id, leg) -> dict | None     # signal mode: a leg appears when a signal opens it
get_run_state(run_id) -> dict | None    # deep copy, safe to read outside the lock
hydrate_run_state(run_id, state) -> None
clear_run_state(run_id) -> None         # drops the state AND its lock
active_run_ids() -> list[int]
open_legs(state) / legs_for_symbol(state, symbol, exchange) / subscribed_symbols(state)
snapshot_for_checkpoint(state) -> dict
favorable_peak_points(leg) -> float
mark_stopping(run_id) -> bool
claim_signal_entry(...) / finish_signal_entry(...) / release_signal_entry_claim(...) / reject_entry_intent(...)
claim_legs_for_exit(...) / claim_superseded_exit(...) / bind_live_exit(...) / bind_superseded_exit(...)
```

Two rules:

- **A leg must always carry a `position`.** `_new_leg_state` raises rather than
  defaulting. The original omits it on signal legs, and because the evaluator
  treats anything that is not `"B"` as a short, those legs were evaluated with
  an inverted sign and their stop fired on a favourable move.
- **A critical section holds in-memory bookkeeping only.** No database, no
  broker, no emit. A greenlet waiting on a lock cannot yield, so I/O inside one
  stalls the entire worker.

## Engine

```python
start_run(strategy_id, user_id, mode, trigger_source="manual",
          webhook_event_id=None) -> StartResult(ok, run_id, error, legs)
stop_run(run_id, user_id, reason="manual") -> dict
reconcile_pending_stop(run_id) -> dict | None
close_leg(run_id, leg_id, user_id) -> dict
apply_fill(run_id, leg_id, avg_price, is_entry,
           filled_qty=None, order_row_id=None,
           position_ref=None) -> bool       # True when the run went flat
process_tick(symbol, exchange, ltp) -> None
```

Load-bearing orderings:

- **Locks are released before orders are placed.** The tick path evaluates under
  the lock, collects what it decided, releases, then dispatches.
- **Entries go BUY before SELL.** A spread whose short leg is placed first can
  be refused for margin the account would have had once the long leg existed.
- **Every leg is resolved before anything is claimed.** A leg that cannot be
  resolved leaves no run row, no claimed strategy and no orders.
- **An exit uses the symbol the run holds**, read from its own state, never a
  re-resolved one. An ATM offset resolved again hours later names a different
  strike, and exiting that opens a new position rather than closing one.
- **The order row is written before the broker is called**, not from the
  dispatch result. The window between broker acceptance and the insert used to
  hold a real position that nothing recorded: invisible to the operator, to
  restart recovery and to every later exit, and unrecoverable if the process
  died there. The row goes in as `pending` with no broker id, and the broker id
  and status are written onto it once dispatch returns.
- **An entry that cannot be recorded is not placed; an exit that cannot be
  recorded is placed anyway.** Opposite decisions, on purpose. Refusing an
  entry costs one leg not opened. Refusing an exit costs a position that stays
  open with a database outage standing between it and every attempt to close
  it, so getting flat wins and the audit row is what is lost, loudly. The
  signal path applies the same two rules as the batch path.
- **The broker's acknowledgement is written back, and that write is checked.**
  `update_order` swallows its own failure and returns False. Ignoring it left
  the row `pending` with no broker order id, so no fill could ever be matched
  to it: the leg was never seeded and nothing evaluated a stop for a position
  that existed. The replay buffer cannot cover this, because the id it would
  match on is what was lost. Retried once, and if it still will not persist the
  exact row/run/leg, broker id and accepted/rejected facts go to the event log
  as structured `order_ack_unrecorded` metadata at critical severity. The
  dispatch call immediately binds only that row through an idempotent CAS. The
  existing shared scheduler rotates through bounded pages of ordinary open
  runs, retries interrupted repair, and broker-polls an accepted working order
  if the short-lived replay frame is gone. Recovery and pending-stop polling
  use the same repair. Missing or conflicting linkage remains open and
  reserved; it is never read as flat.
- **A leg whose entry has been accepted but not filled is never exited.** A leg
  is `open` from broker acceptance, so squaring off would send the configured
  size the other way against a position that may be nothing at all, and if that
  entry were then cancelled the square-off is itself a naked position in the
  reverse direction. `state.claim_legs_for_exit` refuses it and names it, in
  **one** hold of the run lock: claiming and classifying separately left a
  window in which an arriving fill made a leg appear in neither list, and the
  run then finalised with the position still open. The stop is reported as
  refused so the run stays open and managed, and it succeeds once the fill
  lands.
- **A rejected exit is undone wherever the rejection arrives.** The
  synchronous path releases the claim; a rejection or cancellation arriving
  later on the order stream does the same, so the leg stays exitable. An entry
  that dies asynchronously is marked rejected rather than left reading `open`,
  or the next square-off sends the full size against nothing. A pending stop
  stays open and managed; a terminal exit rejection/cancellation releases the
  exact owner claim, records `run_stop_failed` at critical severity, and can be
  retried.
- **A flip whose closing order is refused leaves both sides on the book.** The
  outgoing position is kept under `superseded`, and if its exit dies that
  record is cleared so the old side can be closed again: an exit signal naming
  a side the live leg does not hold is matched against it before being called
  a no-op. Both positions are real, and one leg id can only describe one of
  them.
- **A leg is closed by its fill arriving**, not by its exit being placed. A
  batch run or a run with a durable pending stop finalises after it is confirmed
  flat. A normal risk exit on a signal strategy does not end its session run; the
  next signal can reopen a leg in the same session and P&L history.
- **A leg is claimed for exit under the state lock**, by
  `state.claim_leg_exit`, which does the claim and the duplicate check in one
  hold. The marker is `exit_kind`, written before any dispatch, because
  `exit_order_id` is not written until the order comes back: testing that let
  two rules firing on one leg send a covering order each, and left the guard
  unarmed whenever the audit row could not be written. The batch path and the
  signal path use the same claim.
- **A rejected exit releases its claim**, so a failed attempt is not mistaken
  for a duplicate. Without that the leg is skipped for the rest of the session:
  its stop loss, its target, the square-off and the operator's Close button all
  pass over a position still held at the broker.
- **A stop whose exits were all refused does not close the run.** Finalising
  would release the strategy, drop the live state and unsubscribe the prices
  while the positions are still at the broker. It stays open, emits
  `run_stop_failed` at critical severity, and reports what was refused.
  `close_leg` likewise reports a refusal rather than answering ok.
- **A stop request is durable before any exit.** `request_run_stop` writes the
  timestamp and reason, then `mark_stopping` gates signal entry claims. Accepted
  working exits return `stop_pending: true`; the run stays current, subscribed
  and managed. Finalization happens only after exact owner quantities confirm
  flatness and atomically writes the run plus releases the strategy. Recovery
  resumes the persisted reason after a crash.
- **Trail-to-entry fires only on a stop-driven exit**, never on a manual close.
  That rule answers the market moving against the book; an operator closing a
  leg by hand is an override.

## Order dispatch

```python
build_order(*, symbol, exchange, action, quantity, product, strategy_name,
            pricetype="MARKET", price=0, trigger_price=0) -> dict
exit_action(position) -> str            # "B" -> SELL, "S" -> BUY; raises otherwise
resolve_live_auth(api_key) -> (auth_token, broker, error)
dispatch_order(*, mode, api_key, order) -> DispatchResult(ok, broker_order_id, response, error)
```

Five departures from how the rest of the product places orders:

- **Mode is per run, not global.** The analyzer setting is one platform-wide
  switch and `place_order` consults it, but two runs may disagree. This module
  branches on the run's own mode and calls each pipe directly, and a live run
  passes `force_live=True` to `place_order_with_auth` so the platform-wide
  toggle cannot divert it. Without that, an operator switching to analyze mode
  while a live run held real positions sent every exit to the sandbox, which
  reports success: the engine booked the exit, closed the leg and finalised the
  run, leaving a real position open with nothing evaluating its stop.
- **The product is translated to the venue.** A strategy carries one product for
  every leg. `build_order` reads it as the intent rather than the literal: MIS
  is intraday everywhere, anything else means carry, which is NRML on a
  derivatives venue and CNC on cash. A basket mixing a cash leg and an option
  leg therefore works, and no leg is ever sent a product its venue refuses. One
  combination is refused rather than translated: a short cash leg under a
  carrying product, because cash cannot be held short overnight and anything
  that is not MIS would reach the venue as a naked short delivery. A batch leg
  is refused at save; a signal leg at signal time, when the side being opened
  is known rather than the sides it accepts.
- **Entries are MARKET.** Neither the strategy nor a leg carries a price, so a
  LIMIT, SL or SL-M entry would go out priced at zero. Exits are MARKET on every
  path regardless: a stop that cannot fill is not a stop.
- **Action Center is bypassed.** `place_order` routes API-key orders into the
  semi-automatic approval queue when enabled. A stop-loss exit that waits for a
  human to approve it is not a stop loss, so dispatch calls
  `place_order_with_auth`, the same path without the queue.
- **Broker authorisation is resolved per order and never cached in run state.**
  Indian broker tokens expire daily around 3 AM IST and a run can be open across
  that boundary. When authorisation cannot be resolved, the order is refused and
  reported rather than attempted.

`exit_action` derives from the side the leg *actually holds*. The original reads
the configured side, which defaults to `"B"` for every leg including short ones,
so a rule-driven exit on a short placed another SELL and doubled the position.

## Tick feed

```python
feed = get_risk_tick_feed()             # module singleton
feed.set_on_price(cb)                   # cb(symbol, exchange, ltp) - drives risk evaluation
feed.set_notify(cb)                     # cb(TickSourceEvent) - source transitions, display only
feed.add_run_subscriptions(run_id, symbols) -> list[str]
feed.remove_run_subscriptions(run_id) -> list[str]
feed.get_ltp(symbol, exchange) -> float | None
feed.get_source(symbol, exchange) / feed.is_stale(...) / feed.degraded / feed.health()
feed.on_tick(payload)                   # producer entry point
feed.stop()
```

Subscriptions are refcounted per run. Per symbol the source runs a state
machine: `WS_LIVE` until no tick arrives for the stale threshold, then
`POLLING` over batched multi-quotes, back to `WS_LIVE` on the first websocket
tick, and `STALE` only when both sources have failed long enough that the price
should not be trusted. A 429 backs off 2, 5, 10, 30 seconds and marks the feed
degraded.

**Both the websocket and the REST fallback drive `set_on_price`.** A leg that
has fallen back to polling has to be risk-evaluated on polled prices too, or the
fallback would keep the price fresh on screen while protecting nothing.

Environment: `STRATEGY_TICK_STALE_THRESHOLD_SEC` (10),
`STRATEGY_TICK_STALE_FATAL_SEC` (60), `STRATEGY_TICK_POLL_INTERVAL_SEC` (2),
`STRATEGY_TICK_POLL_BATCH_MAX` (50).

### The threading boundary

This is the part of the module most likely to be broken by a well-meaning
change. Read the eventlet section of `CLAUDE.md` before touching it.

- The **producer** (`on_tick`) is treated as a real OS thread. It does one
  `frozenset` membership test and a `put_nowait` on a real queue from
  `utils/real_threading`, and takes no lock. A green lock touched from a real
  thread raises inside the hub and wedges that thread permanently.
- The **consumers** are green threads and never block on that real queue: they
  drain with `get_nowait` and sleep, because a greenlet blocking on a real
  primitive stalls the single worker.
- The state lock holds in-memory bookkeeping only. The subscribe call, the REST
  fetch, the price hook and even the transition log lines happen after release.

## Fills

`services/strategy_module/order_events.py` subscribes once to the in-process
EventBus topic `order.update`, which the platform already publishes for every
asynchronous status change, live or sandbox. Nothing polls `getOrderStatus`.

```python
start() -> bool                          # idempotent; called by runtime
```

- Deciding an update is not ours costs one indexed lookup on `broker_order_id`.
- **A fill is applied exactly once.** The same fill can arrive from a broker
  postback and from the order-update stream, and applying it twice would add the
  leg's realized profit to the run a second time. The order row's own status is
  the guard.
- **A rejection is final.** A late, out-of-order "complete" cannot resurrect it
  into a position the account never held.
- **A fill is applied only to the order the leg is waiting on.** Fills from
  the stream carry the order row id. A signal flip squares the held side and
  opens the other immediately, so until the closing order fills one leg id names
  two positions; the outgoing one is kept under `superseded` and settles from
  its own entry and size. Without that, the old long's exit fill closed the new
  short, which then vanished from `open_legs`: no stop evaluated, no square-off
  reaching it, and the broker still holding it.
- **A price must be strictly positive and finite**, checked with the same
  `services.risk.models.is_price` a tick has to satisfy. A truthiness test let
  the string `"0"` through, and several brokers send numerics as strings: the
  leg was then marked complete with an entry of 0.0, which `stop_from_points`
  refuses, so it had no stop while everything displayed it as managed.
- **The leg is resized to what actually filled.** A partial fill whose remainder
  was cancelled is ordinary on an illiquid strike, and exiting the size that was
  asked for rather than the size that traded reverses the position.
- **An exit on a leg whose entry never filled books nothing.** Deriving from an
  entry of zero booked the whole notional as realized, and that figure is what
  the combined stop, the combined target and the lock-profit floor are judged
  against.
- **A cancel is recorded as cancelled**, not as a rejection.
- **A terminal partial quantity is still exposure.** Positive `filled_qty`
  counts in every status, including cancellation and rejection; only a complete
  order may fall back to requested quantity when the broker omitted it. A stop
  stays pending until exact entry quantity minus exact exit fills is zero.
- **Missing price is not zero value.** A positive fill with no strictly positive
  finite average price still proves position quantity. Risk valuation remains
  unavailable until another durable witness supplies the price; recovery never
  turns that missing evidence into a fake zero.

## Durability

```python
# checkpoint.py
write_once(*, prune=None) -> int         # one pass; what tests drive
start() -> bool  /  stop() -> None  /  is_running() -> bool

# recovery.py
recover_all() -> dict[int, set[tuple[str, str]]]    # {run_id: symbols to resubscribe}
recover_run(run_id) -> RecoveredRun
normalise_order_status(raw) -> str
order_is_filled(raw) / order_is_dead(raw) / order_is_working(raw)
```

Recovery merges two sources with a deliberate precedence. Identity,
disposition and ownership come from **order rows grouped by exact
`position_ref`**. Volatile risk state (last price, effective stop and target,
trail flags, favourable extremes) comes from the checkpoint, because no order
row carries it. A leg's side is derived from its entry action, so a recovered
leg can never come back with a side it did not trade.

Two asymmetries matter:

- A **dead** order is never upgraded by a checkpoint. A rejection is a fact.
- A **working** order may be upgraded, because the checkpoint is written from
  the same fill the engine applies and the row can lag it.

Order status is normalised in exactly one place. An unrecognised status is
treated as *working*, because reading an unknown exit as dead would let a second
exit be placed, and a second exit opens the opposite position.

One leg can safely represent at most two held reference groups: the newest live
owner plus one outgoing `superseded` owner from a signal flip. If durable rows
prove more held owners, overlapping instruments or another ambiguous exposure,
the run is **not** installed in memory and is **not** finalised. It remains
database-open and reserves the strategy while a critical `recovery_failed`
event requests manual reconciliation. Closing it would falsely assert broker
flatness and permit a new run over unmanaged exposure. Ordinary malformed state
with no proven exposure is still finalised with `stop_reason="recovery_failed"`
so it cannot wedge startup.

A durable pending stop is recovered with its persisted reason. A flat rebuild
finishes it atomically; a held rebuild is hydrated in `stopping` state and its
exits are retried. New signal entries remain gated throughout.

Realized P&L follows evidence provenance. When every exact reference group has
priced entry and exit fills, the durable sum is authoritative even when it is
exactly zero. If one or more fills are unpriced, the checkpoint total is used
only when the checkpoint witnessed exactly the recovered live/superseded owner
shape and quantities. Otherwise recovery retains the known priced portion,
marks it non-authoritative internally and writes a critical
`recovery_succeeded` event requiring manual P&L reconciliation.

## Scheduler

APScheduler `BackgroundScheduler` on `Asia/Kolkata`.

```python
start(paused=False) -> BackgroundScheduler
shutdown() -> None  /  get_scheduler()
sync_all_jobs() -> dict         # rebuild every job from the database
sync_strategy_jobs(strategy_id) -> list[str]
remove_strategy_jobs(strategy_id) -> int
list_jobs() -> list[dict]
run_scheduled_start(strategy_id) / run_scheduled_stop(strategy_id)
```

Four traps present in the platform's other schedulers, avoided here:

1. **Timezone on every trigger**, not just the scheduler. Flow's and Historify's
   cron jobs carry none, so they run in server-local time.
2. **Job defaults set.** APScheduler's default `misfire_grace_time` is one
   second; `blueprints/python_strategy.py` inherits it, so a 09:15 job that
   slips silently vanishes. This module uses 60, with `coalesce` and
   `max_instances=1`.
3. **A module-level callable with args**, not a lambda, so jobs stay picklable.
4. **`remove_all_scoped_sessions()` in a `finally`.** A scheduler worker has no
   Flask app context, so `teardown_appcontext` never fires (issue #1738).

Nothing starts at import. The job store is in memory, so the database stays the
single source of truth, which only holds because every CRUD write calls
`sync_strategy_jobs`.

It also closes a hole in the original: there, the square-off job comes only from
`scheduler.auto_stop_time`, so an intraday strategy with `exit_time` set and
`auto_stop_time` blank was never squared off at all. Here `exit_time` installs
that job when no `auto_stop_time` is given, **and when the scheduler is switched
off entirely**, on weekdays. That last case is the default intraday
configuration, started by an alert and squared off by the clock, and it is the
one the fallback originally could not reach because it sat below the early
return for a scheduler that is not enabled.

## Public webhook

`POST /strategy/webhook/<token>`. The URL token identifies the strategy; there
is no body secret and no API key. It is stored only as a SHA-256 digest and
shown once at creation or rotation.

```python
handle_webhook(token, body=None, *, ip=None, user_agent=None, engine=None) -> WebhookOutcome
unknown_token_outcome(*, ip=None, user_agent=None, audit=True) -> WebhookOutcome
note_run_stopped(strategy_id) -> None    # arms the cooling-off window
ip_allowed(ip, allowlist) -> bool
reset_state() -> None
```

Five properties the token being the whole credential makes necessary:

- **The token is removed at every shipped logging boundary.** One shared path
  redactor covers standard and JSON application logs plus `logs.db`; every
  shipped nginx direct, Docker, multi-instance, update and change-domain
  template suppresses those paths from access logs. External senders and
  proxies remain the operator's boundary: apply the same control there and
  rotate any credential that may have been logged previously.
- **The token never reaches `logs.db`.** `utils/traffic_logger.py` masks the
  credential segment of `/strategy/webhook/`, `/flow/webhook/` and
  `/chartink/webhook/` paths. The traffic log keeps 30 days and is readable at
  `/traffic`, so a token logged verbatim there is a second, longer-lived copy of
  the credential.
- **The caller is `get_real_ip()`, not `remote_addr`.** Behind a reverse proxy,
  which is how most installs run, `remote_addr` is the proxy: the IP allowlist
  would be either useless or total, and the audit trail would name the proxy.
- **An oversized body is refused from `Content-Length`, before it is read or
  audited.** The cap inside the admitted pipeline is measured on bytes already
  in memory, and a refusal at that second cap is audited as `rejected_payload`.
- **The rate limiter is keyed on the token's digest.** Its in-memory storage
  empties the event list of an expired window but never removes the key, so a
  raw token there would persist for the life of the worker, one entry per token
  ever presented including every guess.
- **Audit rows for an unrecognised token are capped** at the newest 1000. They
  name no strategy, so nothing displays them and nothing deleted them: anyone
  who could reach the URL could grow the database without limit, invisibly. They
  are kept rather than dropped because a run of them is the first sign of
  somebody walking the token space.

The route applies its two rate limits and the declared `Content-Length` cap
before this function. A preflight 429 or 413 does not write `sm_webhook_event`.
For a request admitted to `handle_webhook`, the validation pipeline is in this
order and every terminal stage is audited:

| Stage | Result label | Status |
|---|---|---|
| Token resolves | `rejected_token` | 404 |
| Kill switch off | `rejected_locked` | 403 |
| IP in allowlist | `rejected_ip` | 403 |
| Payload parses and fits | `rejected_payload` | 400 |
| Action valid **for this kind** | `rejected_invalid_action` | 400 |
| Start names a mode | `rejected_invalid_action` | 400 |
| Live opt-in | `rejected_live_disabled` | 403 |
| Not a duplicate (batch only) | `rejected_dedupe` | 200, ok |
| Not cooling off (batch only) | `rejected_cooling_off` | 409 |
| Engine acted | `rejected_engine_error` | 500 |

An unknown token answers 404 **from the view**, not by falling through to the
app's handler. Unauthenticated 404s feed `Error404Tracker` and count toward an
IP ban, so a scanner walking the token space could otherwise get the owner's own
address banned. A malformed token is refused on shape before any lookup and is
indistinguishable from an unregistered one in body, status and timing.

`note_run_stopped` is called by the engine on **every** stop, not just
webhook-initiated ones. Without it a strategy stopped by its own risk rules, by
the scheduler or by the kill switch would accept a stale alert a second later
and re-enter the position it had just closed.

`webhook_bridge.py` adapts the handler (which holds a strategy row) to the
engine (which takes ids, because the UI and scheduler drive it too). It also
decides that a webhook `stop` applies to the strategy's current run, and that
stopping an already-flat strategy is a success rather than an error worth
retrying.

## Broker-backed books

```python
strategy_orderbook(strategy_id, api_key, run_id=None) -> dict
strategy_tradebook(strategy_id, api_key, run_id=None) -> dict
strategy_positions(strategy_id, api_key, run_id=None) -> dict
```

These call the platform's own global services and filter the response to this
strategy. On the Detail page the broker result is primary truth for the current
or latest run; recorded strategy order rows remain visible as an explicitly
labelled audit fallback. The hook requests a book only when a valid run exists
and its tab is active. A separate `queried` flag distinguishes “not requested”
from a successful empty broker book.

Broker numerics are nullable at normalization. Missing, empty, non-finite or
malformed quantity/price/P&L renders as unavailable; legitimate numeric zero is
preserved. The local fallback treats any positive `filled_qty` as fill proof in
any status, and permits requested-quantity fallback only for `complete`.
Positions preserve quantity and side when fill price is unavailable while
average price, realized and unrealized P&L stay unavailable.

The position fallback folds lifetime strategy orders so a residual owner from
an earlier run and lifetime realized P&L do not disappear merely because a new
run is current. Live leg marks are different: they are used only when the live
frame's `runId` equals the selected/current broker-book run. A stale prior-run
frame can therefore never value the current fallback.

Orderbook and tradebook reconcile a unique broker order id to local audit
context. Multiple broker trade rows are aggregated by filled quantity and
weighted price before comparison. Local-only, ambiguous and mismatched rows are
visible, and local rejection reasons stay visible alongside broker rows. A
broker error says the account book is unavailable and that the local audit may
lag; a missing run says the broker book was not requested, not that the broker
reported an empty book.

Sandbox runs read the sandbox books. Live reads pass `original_data=None`, the
internal-call form, so the platform-wide analyzer toggle cannot divert a live
run into the sandbox or a sandbox run into the real broker.

**Positions carry a weaker guarantee than the orderbook, and the code says so.**
A position row is per contract, so if the same contract is also held from a
manual order or another strategy, the row is shared and cannot be divided. A
strategy's reported P&L therefore comes from its own fills, never from these
rows.

## Contract resolution

```python
resolve_expiry_rank(underlying, exchange, instrument_type, rank, api_key=None) -> ExpiryResult
resolve_underlying_ltp(underlying, exchange, api_key=None) -> UnderlyingQuote
resolve_leg(leg, underlying, underlying_exchange, strategy_type=None, *,
            api_key=None, underlying_ltp=None) -> ResolvedLeg
derivatives_exchange(exchange) -> str
lot_size_for(symbol, exchange) -> int | None
quantity_is_whole_lots(quantity, symbol, exchange) -> (whole, lot_size)
resolve_quantity(value, qty_mode, symbol, exchange) -> (quantity, lot_size, error)
contract_exists(symbol, exchange) -> bool
```

`resolve_quantity` is what makes lots mode mean lots: 5 lots of NIFTY is
5 x 65 from the master contract, and the lot **count** is what is stored, so a
strategy survives an exchange revising the lot size. An unknown lot size in
lots mode is an error rather than a guess, because the quantity would otherwise
be fabricated.

`lot_size_for` matches on `name` first and falls back to the symbol, anchored:
the row must be the contract exactly or the base followed by the expiry day. An
unanchored prefix let `GOLD` match `GOLDM` and `GOLDPETAL`, so a base with no
contract of its own was handed a neighbour's lot size and the user's lot count
was multiplied by it.

`contract_exists` is what a **signal** leg is checked against, on every venue
including cash. A signal leg names its own instrument, so nothing resolves it
from an underlying and a rank: a futures leg configured as the base symbol went
to the broker verbatim with a quantity that looked entirely plausible, and a
misspelled equity on a cash venue went the same way, because a cash leg is not
resolved from an underlying either. It answers True when the master contract
has no rows for that venue at all, so a strategy is not blocked merely because
the contract has not been downloaded yet.

Delegates every piece of market knowledge it can to
`services/option_symbol_service.py`, including the rule that an MCX commodity
option has no spot and takes its nearest futures contract as the underlying.

Three things it refuses to guess:

- A **lotsize of zero or less** is a hard failure, never a silent 1.
- A **strike stays a float**. `VEDL25APR24292.5CE` is a real contract and
  `int()` would round it into a different one.
- The **monthly rank is read off the data** as the last expiry within its
  calendar month, not off a weekday. NFO moved monthlies from Thursday to
  Tuesday and MCX never had a weekday rule.

Failures are values carrying a machine-readable `code`, not exceptions, so the
engine can report which leg failed and why.

**Pass `underlying_ltp` when resolving a basket**, or two legs of one spread can
settle around different ATM strikes because the underlying moved between the two
quotes. `start_run` already does this.

## Startup

```python
from services.strategy_module.runtime import start_strategy_module, stop_strategy_module
```

One call from `app.py`. Nothing starts at import. The order closes a window at
each step:

1. **Order updates subscribe first**, so a fill arriving while recovery
   reconciles order rows is applied rather than falling between the two.
2. **Recovery**, before any price arrives.
3. **The risk hook is registered, then subscriptions**, so there is no window in
   which prices arrive and nothing judges them.
4. **Checkpointing**, once there is state worth snapshotting.
5. **The scheduler last**, because it can start new runs and must not do that
   until recovery has decided what is already running.

Every step is guarded independently. A platform that will not boot because its
strategy scheduler failed is worse than one that boots without it.

## HTTP surfaces

**Session API** (`blueprints/strategy_module.py`, `url_prefix="/strategy"`):
`/strategy/api/strategies` CRUD, lifecycle (`start`, `stop`, `close_all`,
`legs/<leg_id>/close`), `webhook/rotate`, `live`, `kill_switch`,
`unlock_webhook`, and the read-only views (`runs`, `orders`, `events`,
`webhook_events`, `checkpoints`, `orderbook`, `tradebook`, `positions`).

**API-key surface** (`restx_api/strategy.py`, nine POST routes under
`/api/v1/strategy/`): `list`, `status`, `start`, `stop`, `close_all`,
`close_leg`, `runs`, `orders`, `events`. Documented in
`docs/api/strategy-services/`.

Both enforce the same properties:

- **Configuration vocabularies are not all in the store.** `universe_tab`, a
  leg's `segment`, `product`, `pricetype` and `qty_mode` are validated in
  `blueprints/strategy_module.py`, because the store has no opinion on a leg's
  shape: legs are a JSON column. `UNIVERSE_TABS` and `TAB_SEGMENTS` are the
  pair that matters, because the tab decides which segments can resolve against
  the underlying, and cash resolves on `stocks_fno` only. A configuration that
  names no tab has one derived from its own legs rather than defaulted.
- **`strategy_kind` is settable at create and never updatable.** It sits
  outside `UPDATABLE_FIELDS`, and `update_strategy` refuses a request to change
  it by name rather than dropping it silently, which would have read as
  success. The two kinds do not share a leg shape, so a flip would leave every
  stored leg describing the other kind's contract in an opaque JSON column.
- `mode` is required on start and has no default anywhere in the chain.
- Live is opt-in per strategy.
- A strategy that is not yours answers **404, never 403**, identical to one that
  does not exist, so the id space cannot be probed.
- No response carries a webhook token.
- A PATCH re-validates the whole merged configuration, not just the changed
  fields, so a two-field invariant cannot be broken one request at a time.

## Live updates

A page watching one strategy joins the SocketIO room `strategy:{id}` through the
shared connection and is pushed six frame kinds: `strategy_snapshot`,
`strategy_delta`, `strategy_event`, `strategy_order_update`,
`strategy_run_update` and `strategy_terminal`. Deltas are throttled to 100ms;
one-off frames (a fill, a terminal) are exempt.

- **Ownership is checked on the join**, because the default namespace has no
  connect-time authentication. A strategy that is not yours and one that does
  not exist are refused identically.
- **Frames are ordered by `ts_ms`**, so a late delivery is dropped rather than
  winding the numbers backwards.
- **The 5s checkpoint poll remains as a fallback**, and its interval is gated on
  the socket actually *delivering*. Connected is not enough: a healthy-looking
  connection that delivers nothing is the failure being guarded against.
- The frontend must go through `useSocketContext()`, never `io(...)` directly:
  each Socket.IO connection holds an HTTP connection against the browser's
  per-host limit, shared across tabs.

## Defects deliberately not carried over

Each is pinned by a test that says so.

1. **Signal legs evaluated with an inverted sign.** The source never records a
   side on a signal leg, and its evaluator treats anything that is not `"B"` as
   a short, so those legs had their P&L, stop and target pointing the wrong way
   and the stop fired on a favourable move.
2. **A rule-driven exit on a short doubling the position.** The exit action came
   from configuration that defaults to `"B"`, so it placed another SELL.
3. **Run P&L summed from a stale per-leg field.** A leg whose `mtm` was never
   refreshed poisoned the total every strategy-level rule is judged against.
4. **Peak and trough persisted as zero** for any run closed by an overall stop,
   a target, a lock-profit floor, the scheduler or the kill switch.
5. **An intraday strategy with `exit_time` but no `auto_stop_time` never squared
   off**, because no job was ever installed for it.
6. **Checkpoints never pruned**, growing without bound in a worker that never
   restarts.
7. **Two disagreeing order-status normalisers.**
8. **A repeated exit alert reversing a signal position.** A leg stays open until
   its exit fill arrives, so the second alert found the position still held and
   sent a second closing order.
9. **A refused exit disarming its own leg permanently**, so its stop loss, its
   target and every square-off passed over a position still held.

## Not built yet

- **Resolving an expiry rank on a signal leg.** A signal leg must name the
  contract itself; a base symbol with an expiry rank is refused rather than
  resolved. The refusal is safe, but resolving would be the better answer.
- **A joined SocketIO room outliving the session that joined it.** Ownership is
  checked on the join and nothing re-checks it, so a socket connected before a
  logout keeps receiving that strategy's frames until it disconnects. Low, on a
  single-user deployment where the only owner is the person logging out.
- **`trigger_source` for API starts.** An API-key start records `manual`,
  because the store's vocabulary has no `api` value, so the audit trail cannot
  distinguish a browser start from an API one.
- **Account-level RMS caps** across strategies, and a Flow `riskGuard` node on
  the shared core.
- **Webhook audit and IP-allowlist controls on the strategy page.** The session
  API exposes webhook audit rows, but Detail does not fetch/render them. The
  wizard currently creates strategies with no allowlist and provides no editor;
  do not claim these operator surfaces exist until they are built.

## Related documents

- [`services_documentation.md`](services_documentation.md) - the general service layer
- [`order-constants.md`](order-constants.md) - exchange, product, price-type and action codes
- [`symbol-format.md`](symbol-format.md) - the symbol format every leg resolves to
- [`websockets-format.md`](websockets-format.md) - the tick and order-update protocols
- [`../api/strategy-services/`](../api/strategy-services/) - the public endpoint reference
