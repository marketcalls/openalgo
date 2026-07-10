# Sandbox Execution Engine PRD

## Purpose

The sandbox execution engine monitors open analyzer orders, matches them against current prices, and records fills, trades, position changes, and fund effects without sending orders to a broker.

## Engine Selection

`sandbox/execution_thread.py` owns lifecycle and selects one of two implementations:

| Mode | Implementation | Behavior |
|---|---|---|
| WebSocket | `sandbox/websocket_execution_engine.py` | Primary event-driven engine when the WebSocket proxy is reachable |
| Polling | `sandbox/execution_engine.py` | Quote-based fallback run by `ExecutionEngineThread` |

- `SANDBOX_ENGINE_TYPE` defaults to `websocket`.
- If the proxy is unavailable or WebSocket startup fails, the controller starts the polling engine.
- When startup falls back to polling, a five-second watcher upgrades to WebSocket after the proxy becomes healthy.
- The WebSocket engine treats data older than 30 seconds as stale and, when `SANDBOX_ENGINE_FALLBACK=true`, runs its polling fallback until data recovers.
- Start and stop operations are protected by a thread lock and keep only one primary engine active.

There is no `sandbox/polling_execution_engine.py`; polling behavior is implemented by `sandbox/execution_engine.py` and scheduled by `sandbox/execution_thread.py`.

## Matching Requirements

- Only open sandbox orders are candidates for execution.
- Market orders execute when a current quote is available.
- Buy limits match when market price is at or below the limit; sell limits match when it is at or above the limit.
- Buy stop orders trigger at or above trigger price; sell stop orders trigger at or below it.
- Stop-market orders fill at the available market price after trigger.
- Matching must be atomic enough to prevent duplicate fills when WebSocket and fallback checks overlap.
- Completed orders create trades and update positions, realized/unrealized effects, and blocked/released margin through the sandbox managers.
- Engine-generated order-filled, auto-square-off, and T+1 settlement events update the UI through the EventBus Socket.IO subscriber.

## Polling Requirements

- The polling interval comes from sandbox `order_check_interval`, default 5 seconds.
- Quotes are fetched in batches through multiquotes; unavailable symbols remain open for a later check.
- Processing respects the numeric prefix of `ORDER_RATE_LIMIT`, default 10 orders per second, with a one-second delay between batches.
- The engine must remove its scoped database session after background work.

## WebSocket Requirements

- Subscribe to symbols needed by open orders and remove completed orders from symbol indexes.
- Convert normalized tick data into the quote shape consumed by the common execution logic.
- Monitor feed freshness without blocking tick handling.
- Start or stop the polling fallback on stale/recovered data without filling one order twice.

## Lifecycle And Observability

- Enabling analyzer mode starts the configured engine; disabling it stops the engine and upgrade/fallback watchers.
- Shutdown waits for worker threads with bounded timeouts.
- Engine status reports current type, running state, configured type, and polling interval.
- Exceptions are logged without terminating the long-running monitor loop.

## Ownership And Coverage

| Area | Source |
|---|---|
| Selection, fallback, upgrade, lifecycle | `sandbox/execution_thread.py` |
| Polling matcher and account updates | `sandbox/execution_engine.py` |
| Tick subscriptions and stale-data fallback | `sandbox/websocket_execution_engine.py` |
| Sandbox persistence | `database/sandbox_db.py` |

See `docs/bdd/sandbox_analyzer.feature` and `docs/prd/sandbox-margin-system.md`.
