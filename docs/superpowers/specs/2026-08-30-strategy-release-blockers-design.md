# Strategy Release-Blocker Repair Design

**Date:** 2026-08-30

**Baseline:** `b259267f480ca585f75e74483f003c9af3742e78`

**Status:** Awaiting written-spec review

## Objective

Remove the remaining `/strategy` release blockers found by the independent QA
re-audit:

- a retried signal-flip exit can settle or release the newly opened position
  instead of the outgoing position;
- a stop is finalised on broker acceptance, so an asynchronous rejection can
  leave a broker position unmanaged;
- Orderbook and Tradebook show local audit rows instead of broker truth;
- the strategy safety contracts are only partially documented; and
- the repository-wide backend suite accidentally collects a live SMTP
  diagnostic without an isolated settings database.

The target is zero open Critical or High strategy findings and a fully
collectable/runnable backend suite. Unrelated Medium findings remain tracked by
the QA register unless a changed contract requires their documentation to move
with this repair.

## Product and Runtime Constraints

- OpenAlgo is a single-user, single-broker-session trading platform.
- Entry intent must be durable before dispatch. An entry without durable intent
  is refused.
- An exit may still be dispatched during a database outage because getting flat
  wins over preserving its audit row.
- Exit claims are made under the run lock, but database and broker I/O remain
  outside the lock.
- Fills are correlated to the position instance they settle, not merely to a
  leg ID.
- A stopped run must be genuinely flat. Broker acceptance is not proof of a
  fill.
- Production runs under one eventlet Gunicorn worker. The change adds no thread,
  executor, asynchronous runtime, or blocking primitive.
- SQLite schema changes ship through an idempotent registered migration and are
  tested against a populated pre-change database copy.
- The broker book is authoritative for broker status, quantities, prices and
  fills. Local strategy rows remain authoritative for strategy-only context and
  audit history.

## Root Causes

### Replacement flip exits lose their owner

`state.claim_superseded_exit` marks the outgoing position with a temporary
sentinel. `signals._place` has no concept of an exit owner and always writes the
new order-row ID to the current live leg. A replacement fill therefore matches
the live position, while a replacement rejection cannot clear the outgoing
position's sentinel.

The same structural weakness affects restart recovery: order rows identify a
run and leg but not the position incarnation within that leg. During a flip,
one leg ID temporarily names the outgoing and newly opened positions.

### Stop completion is confused with exit acceptance

`engine.stop_run` calls `_finalise` as soon as every dispatch returns accepted.
Finalisation writes `stopped_at`, releases the strategy, unsubscribes market
data, and drops live state. If the broker later rejects or cancels an accepted
exit, `order_events` has nothing to release or retry and can only write a
critical event.

### Broker book endpoints are unused by two tabs

The backend and TypeScript client already expose broker-filtered Orderbook,
Tradebook and Positions endpoints. Positions uses them; Orderbook and Tradebook
continue to render `sm_strategy_order` rows. Those rows preserve useful
Run/Leg/Kind context but can disagree with the broker.

### A manual SMTP diagnostic is collected as a test

`test/test_email_functionality.py` is both a command-line diagnostic and a
pytest module. Its manual `main()` initializes the settings schema, but the
collected `test_smtp_connection()` does not. Pointing it at the shared test
database would also allow stale SMTP settings to trigger an external network
connection.

## Considered Approaches

### 1. Keep runs managed until exits fill, with durable position identity

This is the selected approach. Each position incarnation gets a durable opaque
reference shared by its entry and exits. A stop request is persisted separately
from final stop completion. Accepted exits leave the run active until fills make
it flat; rejections release the exact position claim for retry.

This changes stop semantics, but it makes the database, live state and broker
meaning agree and survives process restart.

### 2. Reopen a finalised run after a rejection

This preserves the existing immediate-success response, but creates an unsafe
interval with no subscription or risk evaluation. Reconstructing state after
the rejection can itself fail, and clients may already have acted on the
terminal frame. Rejected.

### 3. Finalise immediately and rely on periodic broker reconciliation

A broker reconciliation daemon would improve platform-wide truth, but it is a
new subsystem and cannot remove the period in which the position is unmanaged.
It also does not repair flip-fill ownership. Deferred as a separate product
capability, not used as this fix.

## Backend Design

### Durable position identity

Add a nullable `position_ref` string column to `sm_strategy_order` and an index
on `(run_id, leg_id, position_ref)`. New entry attempts generate a UUID-hex
reference before their durable row is written. The reference is copied into the
leg's live state and every exit row that closes that position.

The column remains nullable for legacy rows. Recovery retains its current
heuristic for legacy history but uses `position_ref` whenever present. The
migration adds the nullable column and index without inventing references for
old rows that cannot be correlated safely.

When a flip replaces a leg:

- the outgoing `position_ref`, entry row ID, side, size, entry price and current
  exit row ID move into `leg.superseded`;
- the new entry receives a different `position_ref`;
- a retry of the outgoing exit records the outgoing reference;
- the replacement row ID is bound to `superseded.exit_order_id` before broker
  dispatch; and
- no superseded operation writes `leg.exit_order_id` or `leg.exit_kind`.

`state.claim_superseded_exit` returns an opaque claim snapshot. A new
`state.bind_superseded_exit` atomically replaces only the expected temporary
claim with its durable row ID. `state.release_superseded_exit` continues to
release only an exact matching claim or row ID.

If an outgoing exit row cannot be written, the exit is still dispatched but its
claim remains armed. The module emits a critical reconciliation event and does
not allow a duplicate cover whose result it cannot correlate.

### Restart recovery for overlapping flip positions

Recovery groups new-format order history by `position_ref` inside each leg:

- the newest still-held position is installed as the live leg;
- one older still-held position is installed as `superseded`;
- filled/dead/working exits are applied to their own group; and
- more than two simultaneously held position groups is treated as a critical
  recovery error rather than silently dropping exposure.

Checkpoint state supplies volatile risk fields, but order rows decide position
identity and terminal disposition. A checkpoint containing `superseded` is
used as additional evidence, not the only evidence.

### Stop-request lifecycle

Add nullable `stop_requested_at` and `stop_requested_reason` columns to
`sm_strategy_run`. `stop_reason` continues to mean the final reason written when
the run actually stops.

`stop_run` performs this sequence:

1. Persist the stop request before dispatching exits.
2. Claim and dispatch exits without holding the run lock across I/O.
3. If a dispatch is refused or an entry is unfilled, leave the run active,
   subscribed and managed; return failure with retryable detail.
4. If exits are accepted but positions remain, return success with
   `stop_pending: true`; do not emit a terminal frame or release the strategy.
5. If synchronous fills already made the run flat, finalise immediately.

`engine.apply_fill` checks the persisted stop request after an exit fill. When
the run is flat, it finalises both batch and signal runs using the requested
reason. Without a stop request, existing signal-session behavior remains: a
flat signal run stays active for the next alert.

While a stop request is active:

- new signal entries are refused with a retry-neutral `run_stopping` result;
- exit signals and repeated stop requests remain allowed so rejected exits can
  be retried;
- risk evaluation remains subscribed for positions whose exit was refused; and
- recovery restores the open run and preserves the pending stop intent.

An asynchronously rejected or cancelled exit releases the claim belonging to
its `position_ref`, emits `run_stop_failed`, and explicitly says the run remains
open and managed. `run_stopped` is emitted only after flatness is confirmed.

### Event vocabulary

Add or standardize these meanings:

- `run_stop_requested`: stop intent persisted and exits are being attempted;
- `run_stop_failed`: at least one position remains held and managed after an
  exit refusal, rejection, cancellation or unfilled-entry refusal;
- `flip_outgoing_exit_rejected`: the outgoing side of a live flip remains held
  and is retryable; and
- `run_stopped`: the run is confirmed flat and finalised.

`_report_stranded_exit` remains only as a legacy/impossible-state guard. It must
not be used for a live flip rejection or claim that an active run already
closed.

## Frontend Design

Use the existing broker-book endpoints and polling hook for all three book
tabs. Add `runId` to the broker-book query key and request so cached latest-run
data cannot cross runs.

Orderbook and Tradebook use a two-part presentation:

1. **Broker-confirmed current/latest-run rows.** Broker status, quantity,
   action, product, price, average price, trade value and timestamp win. Matching
   local rows attach Run, Leg, Kind and rejection/audit context.
2. **Strategy audit records.** Local rows without a broker ID, and historical
   local rows absent from the broker's daily book, remain visible under an
   explicit non-broker label.

A successful empty broker response means there are no broker rows; it is not a
failure. If the endpoint fails, the tab shows a visible warning and falls back
to local audit rows without presenting them as broker-confirmed.

Positions keeps its current broker-first behavior. The local order query stays
because History, Live context, P&L context, rejected-before-submission rows and
fallbacks still require it.

## Email Test Design

Keep the command-line diagnostic, but separate its helper name from pytest's
test discovery. A real pytest test uses an autouse fixture that:

- binds `database.settings_db` to a `tmp_path` SQLite database with `NullPool`;
- resets `Base.query` and the scoped session;
- creates the settings schema and a default row;
- seeds only synthetic `.invalid` settings;
- replaces the network-capable SMTP validator with a canned result; and
- removes the scoped session and disposes the engine in cleanup.

The test asserts that the diagnostic reads the isolated settings and passes
them to the validator. It cannot inspect operator configuration or open a
network connection.

## API and Documentation Changes

Stop responses document `stop_pending` and distinguish accepted exits from
confirmed flatness. The strategy details/run payload exposes pending stop intent
where the existing serializers expose run fields.

Update the following single-source documents and their registered BDD/PRD
claims:

- `docs/api/strategy-services/stop.md`
- `docs/api/strategy-services/close_all.md`
- `docs/api/strategy-services/start.md`
- `docs/api/strategy-services/orders.md`
- `docs/api/strategy-services/events.md`
- `docs/api/strategy-services/README.md`
- `docs/prd/strategy-module-rms.md`
- `docs/prompt/strategy_rms_documentation.md`
- `docs/bdd/strategy_module_rms.feature`

The documentation must cover unfilled-entry refusal, durable acknowledgement
loss, position references, pending stops, broker-confirmed book authority and
the corrected event meanings. BDD source anchors are refreshed to lines that
actually establish each behavior.

## Migration and Compatibility

Create one idempotent strategy-module migration registered in
`upgrade/migrate_all.py` that adds:

- `sm_strategy_order.position_ref` plus its composite index;
- `sm_strategy_run.stop_requested_at`; and
- `sm_strategy_run.stop_requested_reason`.

Fresh databases receive the columns through ORM metadata. Existing rows retain
NULL and use legacy recovery behavior. The migration supports status reporting,
does not rewrite operator data, and is tested against a populated copy with the
three columns removed.

Existing clients that only inspect `ok` continue to work. `ok: true` after an
accepted stop means the request was accepted; `stop_pending: true` makes clear
that the run has not yet reached terminal flatness. A synchronous sandbox fill
normally returns `stop_pending: false`.

## Test Strategy

All production changes follow RED-GREEN TDD. Required regressions include:

- replacement flip exit binds only to `superseded`;
- replacement fill settles only the outgoing position and its P&L;
- replacement rejection and cancellation permit exactly one further retry;
- live flip rejection emits the flip-specific event, not a false closed-run
  event;
- stop acceptance followed by asynchronous rejection leaves the run open,
  subscribed and retryable;
- a stop finalises only after the final exit fill;
- signal entries are refused while a stop is pending;
- restart restores both live and superseded position references;
- migration status/apply/reapply works on a populated pre-change database;
- broker fields override contradictory local Orderbook/Tradebook fields while
  Run/Leg/Kind context survives;
- broker failure and empty-success states are visibly distinct;
- switching runs changes the broker-book cache key and request; and
- the SMTP test uses a temporary settings database and a mocked validator.

Verification includes targeted strategy tests, migration tests, the independent
residual probes, backend collection, the complete backend suite, targeted and
complete frontend tests, TypeScript/build, Biome, Ruff on changed Python files,
the eventlet invariant suites, the repository FD audit procedure, and a fresh
generation of the independent QA report and workbooks.

## Non-Goals

- A platform-wide continuous broker reconciliation daemon.
- Automatic liquidation outside the existing strategy order paths.
- Webhook audit/IP-allowlist UI work unrelated to the broker-book tabs.
- Rewriting historical NULL `position_ref` values using guesses.
- Closing unrelated Medium documentation findings except where their claims are
  directly changed by this design.

## Release Gates

The change is not complete until:

- the two previously failing residual probes pass and demonstrate RED against
  the old behavior;
- a delayed rejected stop exit remains managed and retryable;
- restart recovery preserves both sides of an unsettled flip;
- Orderbook and Tradebook identify broker-confirmed versus local-only data;
- the isolated email test and the full backend suite pass without network use;
- all changed docs agree with runtime behavior; and
- the refreshed QA audit reports zero open Critical or High findings for this
  scope.
