# Strategy Hub / Lean Trading Engine handoff

This file is intended for another AI agent continuing the work on the multi-strategy Python runner and OpenAlgo Strategy Hub.

## Current status

The implementation is complete and verified across three phases:

1. Phase 1: lean-trading-engine created in the separate worktree at `/Users/arifkhan/github/lean-strategies.worktrees/lean-trading-engine/`
2. Phase 2: strategy plugins wired for the sample strategies under `live-nifty-straddle/` and `live-nifty-weekly-momentum/`
3. Phase 3: OpenAlgo Strategy Hub added in this repo and verified locally

The repo in scope for this handoff is:

- OpenAlgo worktree: `/Users/arifkhan/github/openalgo.worktrees/simplified-python-strategy-module`
- Lean strategies worktree: `/Users/arifkhan/github/lean-strategies.worktrees/lean-trading-engine`

## What was implemented

### 1) OpenAlgo Strategy Hub

Implemented in this repo:

- [blueprints/strategy_zmq_listener.py](./blueprints/strategy_zmq_listener.py)
  - binds a ZMQ PULL socket on `STRATEGY_HUB_ZMQ_PORT` (default `6099`)
  - accepts incoming `ANNOUNCE`, `HEARTBEAT`, `METRICS`, `BYE`, and command frames from strategy runners
  - periodically scans a configured port range (`STRATEGY_ZMQ_BASE_PORT` to `+ STRATEGY_ZMQ_SCAN_RANGE`) to discover live strategies
  - tracks offline/stale strategies
  - relays registry changes via SocketIO using `strategy_hub_update`
  - supports command routing with ZMQ REQ + systemctl fallback

- [blueprints/strategy_hub_bp.py](./blueprints/strategy_hub_bp.py)
  - REST API for strategy discovery and control
  - route: `/strategy-hub`
  - API routes:
    - `GET /strategy-hub/api/strategies`
    - `POST /strategy-hub/api/strategies/<strategy_id>/start`
    - `POST /strategy-hub/api/strategies/<strategy_id>/stop`

- [app.py](./app.py)
  - registers the blueprint
  - starts the ZMQ listener at boot

- [.sample.env](./.sample.env)
  - added strategy hub settings:
    - `STRATEGY_HUB_ENABLED`
    - `STRATEGY_HUB_ZMQ_PORT`
    - `STRATEGY_ZMQ_BASE_PORT`
    - `STRATEGY_ZMQ_SCAN_RANGE`
    - `STRATEGY_HUB_POLL_INTERVAL_SECONDS`
    - `STRATEGY_HUB_STALE_SECONDS`

### 2) Frontend strategy dashboard

- [frontend/src/api/strategy-hub.ts](./frontend/src/api/strategy-hub.ts)
- [frontend/src/pages/strategy-hub/StrategyHubIndex.tsx](./frontend/src/pages/strategy-hub/StrategyHubIndex.tsx)
- [frontend/src/App.tsx](./frontend/src/App.tsx)
- [frontend/src/config/navigation.ts](./frontend/src/config/navigation.ts)
- [frontend/src/hooks/usePageTitle.ts](./frontend/src/hooks/usePageTitle.ts)

The UI is intentionally SocketIO-driven after initial load and does not auto-refresh via polling, per the design decision to avoid flickering cards and keep updates event-driven.

## Architecture decisions

### ZeroMQ pattern

The design uses:

- Strategy runner -> OpenAlgo hub: `PUSH`/`PULL` announce and heartbeat traffic
- Hub -> strategy runner: `REQ`/`REP` control messages

This avoids adding a long-polling or polling layer into the browser and allows the runner to announce on startup with minimal coordination.

### Eventlet / threading note

This is important:

- libzmq blocking `recv()` does not cooperate with eventlet greenlets
- strategy listener must run in a real OS thread, not eventlet green threads
- the in-memory strategy registry is protected with `threading.Lock`

This was an explicit design fix for reliability in the OpenAlgo app lifecycle.

### Control flow

`send_command()` does:

1. ZMQ REQ to the strategy's `REP` port with a timeout
2. fallback to `systemctl --user <action> <unit_name>` when the ZMQ route is unavailable

This allows both local service control and graceful failover.

## Lean trading engine worktree

Core engine modules live in the lean strategies repo under:

- `strategies/openalgo/lean_trading_engine/`

Important files:

- `strategies/openalgo/lean_trading_engine/zmq_publisher.py`
- `strategies/openalgo/lean_trading_engine/runner/NiftyMultiStrategyRunner.py`
- `strategies/openalgo/live-nifty-straddle/strategy.py`
- `strategies/openalgo/live-nifty-weekly-momentum/strategy.py`

The runner uses a plugin model; each strategy module announces itself to the hub and publishes its own metrics.

## Verification completed

The implementation was verified with a real dev server run and targeted smoke tests:

- app served locally on port `5000`
- WebSocket proxy remained on `8765`
- Strategy Hub ZMQ listener listened on `6099`
- `/strategy-hub` page route returned a valid response
- unauthenticated access returned `401` with `session_expired`
- ANNOUNCE / HEARTBEAT frames populated the registry
- BYE frames marked strategies offline
- command flow for stop/start worked in the smoke test

## Known environment caveats

### ngrok

The server log may show pre-existing ngrok startup errors in this environment. They are not part of the Strategy Hub feature and were not blocking the feature validation.

### AirPlay / port conflicts

On macOS, ControlCe/AirTunes can occupy local ports and cause confusion with `localhost` binding. For local testing, validate the app with the reported log output and the server ports rather than assuming a stale port is a feature problem.

### Flask-SocketIO dev server warning

When running locally in this environment, the app may emit:

- `Werkzeug appears to be used in a production deployment`
- `allow_unsafe_werkzeug=True` may be needed for a direct `socketio.run()` dev-server run

This is expected in an ad hoc dev environment; production mode still uses the platform's gunicorn/eventlet configuration.

## Important commands to continue work

From the OpenAlgo repo:

```bash
cd /Users/arifkhan/github/openalgo.worktrees/simplified-python-strategy-module
uv run python app.py
```

Or, if you need a fresh local startup after stale processes remain:

```bash
# kill stale app.py processes first if needed
lsof -ti:5000,8765,6099 | xargs kill -9
uv run python app.py
```

To inspect the strategy hub page locally:

- http://127.0.0.1:5000/strategy-hub

To inspect the API when authenticated:

- http://127.0.0.1:5000/strategy-hub/api/strategies

## Continuation status

The weekly momentum plugin has now been implemented in the Lean strategies
worktree. It uses a configurable spot lookback and momentum threshold, buys a
near-weekly ATM call or put, enforces one entry per day, exits on target/stop
or force-exit time, and persists its entry/history state. The isolated engine
test suite passes 15 tests.

The market adapter is still intentionally deployment-specific. No production
adapter was added because the deployed NIFTY data/broker API and its LEAN
subscription contract have not been identified. Keep live execution disabled
until that interface is supplied and paper-traded.

## Remaining work / next step recommendations

1. Push both branches when ready:
   - OpenAlgo: `feat/additive-python-strategy-module`
   - Lean strategies: `feature/lean-trading-engine`
2. Validate `/strategy-hub` in a browser with a real strategy runner or a local simulated publisher
3. Replace the placeholder `AdapterTemplate` in the market adapter with a real data source before live trading
4. Confirm each strategy's unit/service name, ZMQ port, and systemd integration in the actual deployment environment
5. Paper-trade the weekly momentum strategy with the production adapter before enabling live execution

## Quick summary for the next agent

The repo already contains the OpenAlgo-side strategy hub, the ZMQ discovery/control layer, and the frontend dashboard. The system is designed to discover external strategy runners over a configured ZMQ port range, build a live registry in memory, and expose it to the browser through SocketIO. The next agent should focus on real runner integration, service control, and the actual production strategy logic, not on the basic hub plumbing.
