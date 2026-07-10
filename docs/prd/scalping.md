# Scalping Terminal PRD

## Purpose

The scalping terminal provides fast F&O discovery and order actions while keeping validation and risk-reducing exits on the server. The page is session-authenticated and obtains the user's OpenAlgo API key server-side for normalized trading calls.

## HTTP Surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/scalping/api/underlyings` | Compact underlying list |
| GET | `/scalping/api/history` | Chart history |
| GET | `/scalping/api/all_underlyings` | Exchange-aware underlying discovery |
| GET | `/scalping/api/expiry` | Expiry discovery |
| GET | `/scalping/api/strikes` | ATM-centered option strikes |
| GET | `/scalping/api/search` | Instrument search |
| GET | `/scalping/api/futures` | Futures discovery |
| POST | `/scalping/api/order` | Validated order entry |
| POST | `/scalping/api/close_leg` | Reduce one tracked leg |
| POST | `/scalping/api/close_all` | Reduce all tracked legs |
| POST | `/scalping/api/cancel_all` | Cancel pending orders |
| GET, DELETE | `/scalping/api/tracked` | Read or clear tracked instruments |
| GET, POST, DELETE | `/scalping/api/sl` | Read, persist, or remove stop state |

## Execution And Risk Requirements

- Exchange, product, action, quantity, lot multiple, and request shape are validated server-side.
- Manual order entry is capped at 20 lots and 100000 units.
- Exit direction is derived from current exposure, and an exit must not increase that exposure.
- Stop, target, and trailing state is keyed by symbol, exchange, product, and live/analyzer mode.
- Malformed or non-reducible stop state is rejected.
- A singleton server risk monitor continues after the browser leaves, evaluates incoming ticks, and submits freeze-safe risk-reducing exits on a breach.
- Charts are opt-in. The browser persists the chart toggle and 1m, 5m, or 15m interval preference.

## Ownership And Coverage

Implementation is in `blueprints/scalping.py`, `database/scalping_db.py`, `services/scalping_risk_monitor_service.py`, and `frontend/src/pages/Scalping.tsx`. Acceptance coverage is in `docs/bdd/scalping_and_tools.feature`.
