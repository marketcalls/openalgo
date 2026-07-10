# Historify Data Model

## Store And Connection Model

Historify uses one DuckDB file, default `db/historify.duckdb`, through short-lived context-managed connections. Connection creation retries transient file-lock failures up to three times with increasing delay and always closes the connection.

`database/historify_db.py` reads `HISTORIFY_DATABASE_PATH`. `.sample.env` and system-permissions code use `HISTORIFY_DATABASE_URL`; the naming mismatch is unresolved.

## Tables

### `market_data`

Normalized candles keyed by `(symbol, exchange, interval, timestamp)`.

| Column group | Fields |
|---|---|
| Identity | `symbol`, `exchange`, `interval`, Unix `timestamp` |
| Candle | `open`, `high`, `low`, `close`, `volume`, `oi` |
| Audit | `created_at` |

The composite primary key prevents duplicate candles for the same contract and interval. Open interest defaults to zero when a source omits it.

### `watchlist`

Tracks unique `(symbol, exchange)` entries with optional `display_name` and `added_at`. `id` is an integer primary key managed by database helpers.

### `data_catalog`

Tracks one row per `(symbol, exchange, interval)` with first/last timestamps, record count, and last download time. Catalog rows are maintained alongside candle writes and deletions.

### `download_jobs`

Stores string job ID, type, status, symbol counts, interval/date range, serialized configuration, lifecycle timestamps, and job-level error text.

### `job_items`

Stores each job's symbol/exchange, item status, downloaded record count, error text, and lifecycle timestamps. `job_id` is the owning string job identifier.

### `symbol_metadata`

Keyed by `(symbol, exchange)` and stores name, expiry, strike, lot size, instrument type, tick size, and last-updated time.

### `historify_schedules`

Stores schedule name/description, interval-or-daily configuration, watchlist source, data interval, lookback, enabled/paused/status state, APScheduler ID, run timestamps, and success/failure counters.

### `historify_schedule_executions`

Stores schedule ID, linked download job, status, lifecycle timestamps, symbol and record counts, and error text for each scheduled run.

## Indexes

The schema creates indexes for:

- `market_data(timestamp)`
- `market_data(exchange, timestamp)`
- `market_data(interval, timestamp)`
- `job_items(job_id)`
- `download_jobs(status)`
- `historify_schedules(is_enabled, is_paused)`
- `historify_schedule_executions(schedule_id)`

The candle primary key is the principal lookup constraint for symbol/exchange/interval range queries.

## Data Requirements

- Candle timestamps are stored as Unix integers; API layers convert as required by their contracts.
- Writes must upsert or otherwise preserve the composite-key uniqueness guarantee.
- Catalog range/count metadata must be recalculated or updated after insert and delete operations.
- Computed intervals are derived from stored candles and are not required to have separate physical rows.
- Job and schedule state transitions must be persisted before emitting best-effort UI notifications.
- Export files are temporary artifacts and are not part of DuckDB ownership.

## Ownership And Coverage

Schema and data operations are in `database/historify_db.py`. Route/service contracts are in `historify-api-reference.md`, `historify-download-engine.md`, and `docs/bdd/historify_and_tools.feature`.
