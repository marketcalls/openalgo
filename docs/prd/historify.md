# Historify PRD

## Purpose

Historify downloads normalized broker history into a local DuckDB store for charts, REST history with `source=db`, research, and exports. It also owns a watchlist, data catalog, asynchronous jobs, symbol metadata, and recurring schedules.

## Product Surface

- The React page is served at `/historify` when `frontend/dist` is available.
- Session-authenticated JSON and file routes are under `/historify/api`.
- Historify is not a Flask-RESTX `/api/v1` namespace.
- The complete 50 method/path pairs are listed in `historify-api-reference.md`.

## Functional Requirements

### Watchlist And Discovery

- Add, remove, bulk-add, and bulk-remove symbol/exchange watchlist entries.
- Validate symbols through current contract/master data before persistence.
- Discover supported exchanges, API intervals, Historify intervals, F&O underlyings, expiries, futures, and options.
- Store and enrich symbol metadata used by catalog and export views.

### Download And Jobs

- Download one symbol or the complete watchlist for a date range and interval.
- Create asynchronous custom, watchlist, option-chain, or futures-chain jobs.
- Support incremental jobs that fetch only missing ranges before or after stored data.
- Persist job and item status, progress counts, downloaded records, timestamps, and errors.
- Allow valid pause, resume, cancel, retry, and delete transitions.
- Emit Socket.IO progress, paused, cancelled, and completion updates as best-effort UI notifications.

### Storage And Query

- Store normalized OHLCV plus open interest where available.
- Keep `1m` and `D` as primary download/storage intervals and derive supported higher intervals from stored data.
- Upsert candles without duplicating the same symbol, exchange, interval, and timestamp.
- Maintain a data catalog and statistics for stored ranges.
- Serve chart data by symbol, exchange, interval, and optional date range.

### Export And Import

- Export filtered data as CSV, TXT, ZIP, or Parquet.
- Preview matching record count and estimated size before export.
- Aggregate computed intervals during supported export flows.
- Stream only server-generated temporary files and remove them after download.
- Import validated CSV or Parquet uploads and provide sample files for both formats.

### Scheduling

- Create interval or daily schedules using the Historify watchlist as the symbol source.
- Support enable, disable, pause, resume, update, delete, and manual trigger operations.
- Persist execution history and expose the scheduler's next run time.

## Operational Requirements

- Downloads require the logged-in user's OpenAlgo API key and normalized history service.
- Broker history failures and no-data responses must remain visible per job item.
- DuckDB operations must use the database module's lock/retry behavior.
- Active jobs left without in-memory state after restart are marked failed so they can be retried.
- Historical availability varies by broker and requested interval/date range.

## Data Ownership

`database/historify_db.py` owns DuckDB tables for market data, watchlist, catalog, jobs/items, metadata, schedules, executions, and indexes. `services/historify_service.py` owns downloads/jobs and `services/historify_scheduler_service.py` owns recurring execution.

The environment name is currently inconsistent: `.sample.env` and system-permissions code use `HISTORIFY_DATABASE_URL`, while the database implementation reads `HISTORIFY_DATABASE_PATH`. This remains an explicit conflict until code is standardized.

## Related Documentation

- `historify-api-reference.md`
- `historify-data-model.md`
- `historify-download-engine.md`
- `docs/bdd/historify_and_tools.feature`
