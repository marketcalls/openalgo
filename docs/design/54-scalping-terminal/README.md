# 54 - Scalping Terminal And Risk Monitor

## Purpose

`/scalping` is a session-authenticated trading workspace for fast equity, futures, and options execution. It combines contract discovery, order/position views, WebSocket ticks, optional live charts, tracked legs, and persisted server-side stop/target/trailing-stop management.

## Components

| Component | Responsibility |
|---|---|
| `blueprints/scalping.py` | Session APIs for discovery, history, execution, exits, tracked legs, stops |
| `database/scalping_db.py` | Mode-separated stop state and tracked symbols |
| `services/scalping_risk_monitor_service.py` | Long-lived tick evaluation and reducing exits |
| `frontend/src/pages/Scalping.tsx` | Terminal interaction and state composition |
| `frontend/src/api/scalping.ts` | Typed blueprint client |
| `frontend/src/components/scalping/ScalpChart.tsx` | Candles and volume |
| `frontend/src/components/scalping/SetSLDialog.tsx` | Stop/target/trailing configuration |

## Session APIs

The blueprint provides underlyings, all-underlying search, expiry, strikes, futures, symbol search, history, order, close-leg, close-all, cancel-all, tracked-symbol GET/DELETE, and stop GET/POST/DELETE resources under `/scalping/api`.

These are browser session APIs, not public `/api/v1` API-key endpoints. They resolve the current user's OpenAlgo API key internally.

## Instruments And Execution

Supported execution exchanges are `NSE`, `BSE`, `NFO`, `BFO`, `MCX`, and `CDS`. Derivatives allow `MIS`/`NRML`; equities allow `MIS`/`CNC`. Index underlyings map to their quote and F&O exchanges, while MCX/CDS option chains can use the current-month future as reference.

Server-side safety rails include:

- `BUY` or `SELL` only.
- Maximum 20 lots per manual request.
- Absolute maximum 100,000 units.
- Derivative quantity must respect the contract lot size.
- Exit routes derive the opposite action from the actual position and cannot increase exposure.
- Order strategy is stamped as `Scalping`.

Analyzer/live mode is read from the global application setting and used to segregate tracking and stop rows.

## Market Data And Books

The page uses the shared browser market-data manager for ticks and Socket.IO order events for throttled order/trade/position refresh. Stale ticks can fall back to multi-quotes. Client filtering keeps displayed book entries scoped to the current day when timestamps are parseable.

History supports `1m`, `5m`, and `15m` with lookbacks of 1, 3, and 9 trading days. Returned chart times are shifted for Lightweight Charts' UTC rendering so displayed bars align with IST. Indices can legitimately have zero volume.

Charts are off by default because three live charts create additional subscriptions and history reconciliation. The charts toggle and timeframe are stored in browser local storage.

## Persisted Stops

A stop row is keyed by symbol, exchange, product, and mode. It stores side, quantity, entry/stop/target values, trailing settings, current trailed stop, and runtime state. POST validates finite/non-negative inputs and verifies that a reducing exit can be placed before persistence.

The browser configures and displays this state, but it is not the risk engine.

## Server Risk Monitor

The singleton monitor starts with application environment setup and owns an internal WebSocket client. It synchronizes active rows, subscribes/unsubscribes symbols, evaluates each tick, persists trailed-stop advances with rate limiting, and submits whole-lot, freeze-safe reducing exits on stop or target breach.

This design keeps protection active when the browser navigates away or closes. The monitor rechecks live position state before execution as a backstop. `stop()` disconnects and is registered for process exit cleanup.

## Failure Boundaries

- Saving/deleting stop state notifies the monitor but a notification hiccup does not fail the persistence request.
- Feed unavailability is logged and retried through synchronization rather than corrupting stop state.
- Invalid/string broker numerics are normalized before position calculations.
- Broker history gaps do not stop live chart tick formation.
- The monitor only reduces exposure; it is not a general strategy entry engine.

## Tests

`test/test_scalping_risk_monitor.py` covers trailing-stop evaluation and monitor behavior. Frontend tests cover scalping price, row, tick, and trailing-stop helpers. Changes to execution rails require both server validation and UI regression coverage.
