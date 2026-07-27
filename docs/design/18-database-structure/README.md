# 18 - Database Structure

## Store Inventory

OpenAlgo uses local persistence split by workload. Defaults come from `.sample.env`.

| Store | Configuration | Default | Responsibility |
|---|---|---|---|
| Main | `DATABASE_URL` | `sqlite:///db/openalgo.db` | Users, auth, API keys, settings, strategies, Flow, calendar, messaging config, chart prefs, Action Center, scalping |
| Traffic | `LOGS_DATABASE_URL` | `sqlite:///db/logs.db` | HTTP traffic, 404 activity, IP bans/security data |
| Latency | `LATENCY_DATABASE_URL` | `sqlite:///db/latency.db` | API/broker timing telemetry |
| Health | `HEALTH_DATABASE_URL` | `sqlite:///db/health.db` | FD, memory, DB, WebSocket, thread metrics |
| Sandbox | `SANDBOX_DATABASE_URL` | `sqlite:///db/sandbox.db` | Simulated orders, trades, positions, holdings, funds, config, GTT tables |
| Historify | implementation path setting | `db/historify.duckdb` | Candles, catalog, watchlist, jobs, metadata, schedules |

The sample environment currently names `HISTORIFY_DATABASE_URL`, while `database/historify_db.py` reads `HISTORIFY_DATABASE_PATH`. This is a known configuration naming conflict, not a documentation alias; see `docs/prd/CONFLICTS.md`.

## Engine Policy

`database/engine_factory.py` creates SQLite engines with `NullPool`. Each scoped session gets a short-lived connection instead of retaining file descriptors across long-running worker lifetimes. `check_same_thread=False` allows scoped use across the app's thread model, but callers still must not share a SQLAlchemy session concurrently.

`app.py` registers teardown removal for the scoped sessions used by database modules. Adding a new scoped session requires adding it to the teardown inventory or using a context-managed pattern that closes it reliably.

## Main Database Domains

| Module | Main tables/concern |
|---|---|
| `auth_db.py`, `user_db.py` | Broker auth, API keys, active sessions, login audit, local user |
| `settings_db.py`, `leverage_db.py` | Analyzer and application settings |
| `strategy_db.py`, `chartink_db.py`, `flow_db.py` | Automation definitions and executions |
| `action_center_db.py` | Pending semi-auto requests and approval outcome |
| `market_calendar_db.py`, `qty_freeze_db.py` | Exchange calendar and freeze quantities |
| `telegram_db.py`, `whatsapp_db.py` | Bot configuration, linked users, notification state |
| `oauth_db.py` | Remote MCP clients, tokens, audit/control state |
| `chart_prefs_db.py`, `strategy_portfolio_db.py` | Workspace and portfolio state |
| `scalping_db.py` | Mode-separated tracked legs and stop/trailing-stop configuration |

## Sandbox Database

Sandbox initialization is self-healing: startup must ensure every required table exists even if a prior initialization was partial. The presence of sandbox GTT tables does not mean REST analyzer GTT is implemented; those service calls currently return 501.

The sandbox managers own execution, order state, position netting, holdings/T+1 behavior, funds/margin, square-off, and settlement. No live broker order call belongs in this database layer.

## Historify DuckDB

Historify is columnar rather than SQLAlchemy/SQLite. It stores:

- `market_data` and indexes for OHLCV/OI queries.
- `watchlist` and `data_catalog`.
- Download job and job-item state.
- Symbol metadata.
- Schedules and schedule executions.

The history REST service reads it only when `source="db"`; default history remains broker API data.

## Time And Secrets

- Persist timezone-aware values where the model supports them; user-facing market/session behavior is generally IST.
- Never log or copy decrypted API keys, broker tokens, TOTP secrets, bot tokens, or OAuth credentials.
- Encryption helpers are module-specific because not every store derives Fernet keys identically.

## Schema Changes

Most modules use idempotent `create_all` plus targeted startup migrations for compatible column/index additions. There is no general Alembic migration layer. A schema change must therefore be safe on an existing file, safe after partial initialization, and tested against both a fresh and pre-existing database.

## Backups

Back up all six configured stores before an upgrade. Copying only `openalgo.db` omits traffic/security history, latency/health telemetry, sandbox state, and local historical candles.
