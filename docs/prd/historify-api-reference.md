# Historify API Reference

## Scope And Authentication

Historify is a session-authenticated Flask blueprint with `url_prefix="/historify"`. Its JSON and file routes therefore begin with `/historify/api`; they are not RESTX `/api/v1` endpoints and do not use the `/api/v1/historify` prefix from older documentation.

All routes below require a valid OpenAlgo app session. Download and job creation also require an OpenAlgo API key for the logged-in user because they call normalized history services.

## Complete Route Inventory

### Watchlist And Download

| Method | Path | Purpose |
|---|---|---|
| GET | `/historify/api/watchlist` | List watchlist entries |
| POST | `/historify/api/watchlist` | Add one `{symbol, exchange, display_name?}` entry |
| DELETE | `/historify/api/watchlist` | Remove one `{symbol, exchange}` entry |
| POST | `/historify/api/watchlist/bulk` | Add a `symbols` array |
| POST | `/historify/api/watchlist/bulk/delete` | Remove a `symbols` array |
| POST | `/historify/api/download` | Download one symbol, interval, and date range |
| POST | `/historify/api/download/watchlist` | Download all watchlist symbols for an interval/date range |

### Data, Catalog, And Export

| Method | Path | Purpose |
|---|---|---|
| GET | `/historify/api/data` | Query OHLCV by symbol, exchange, interval, and optional dates |
| GET | `/historify/api/catalog` | List stored datasets |
| GET | `/historify/api/symbol-info` | Report interval/data availability for a symbol |
| POST | `/historify/api/export` | Create a single-symbol CSV export |
| GET | `/historify/api/export/download` | Stream the session's single export and remove the temporary file |
| POST | `/historify/api/export/preview` | Estimate matching records and export size |
| POST | `/historify/api/export/bulk` | Create CSV, TXT, ZIP, or Parquet output |
| GET | `/historify/api/export/bulk/download` | Stream the session's bulk export and remove the temporary file |
| GET | `/historify/api/catalog/grouped` | Return catalog entries grouped for the UI |
| GET | `/historify/api/catalog/metadata` | Return catalog metadata |
| POST | `/historify/api/metadata/enrich` | Enrich and persist metadata for supplied symbols |

Bulk export accepts optional `symbols`, `interval` or `intervals`, `start_date`, `end_date`, `split_by`, `format`, and Parquet `compression`. Supported compression values are `zstd`, `snappy`, `gzip`, and `none`. Multiple intervals, and computed intervals requested as CSV/TXT, are emitted as ZIP files.

### Discovery, Maintenance, And Upload

| Method | Path | Purpose |
|---|---|---|
| GET | `/historify/api/intervals` | Return intervals available from the OpenAlgo API |
| GET | `/historify/api/historify-intervals` | Return intervals supported by local Historify storage/aggregation |
| GET | `/historify/api/exchanges` | Return supported exchanges |
| GET | `/historify/api/stats` | Return database statistics |
| DELETE | `/historify/api/delete` | Delete one symbol/exchange/interval dataset |
| POST | `/historify/api/delete/bulk` | Delete multiple selected datasets |
| POST | `/historify/api/upload` | Import an uploaded CSV or Parquet file |
| GET | `/historify/api/sample/<format_type>` | Download a CSV or Parquet sample file |

Uploaded files are validated by format and parsed through Historify import logic. File paths are server-generated; callers do not supply arbitrary download paths.

### F&O Contract Discovery

| Method | Path | Purpose |
|---|---|---|
| GET | `/historify/api/fno/underlyings` | List F&O underlyings, optionally by exchange |
| GET | `/historify/api/fno/expiries` | List expiries by underlying, exchange, and optional instrument type |
| GET | `/historify/api/fno/chain` | Query a filtered futures/options chain |
| GET | `/historify/api/fno/futures` | List futures contracts for an underlying |
| GET | `/historify/api/fno/options` | List option symbols with expiry and strike filters |

`underlying` is required for expiry and chain-specific routes. Chain filters include `exchange`, `expiry`, `instrumenttype`, `strike_min`, `strike_max`, and a bounded result `limit` where supported.

### Download Jobs

| Method | Path | Purpose |
|---|---|---|
| GET | `/historify/api/jobs` | List jobs with optional status and limit filters |
| POST | `/historify/api/jobs` | Create and start a job for a symbol list |
| GET | `/historify/api/jobs/<job_id>` | Read one job |
| DELETE | `/historify/api/jobs/<job_id>` | Delete one job |
| POST | `/historify/api/jobs/<job_id>/cancel` | Cancel a job |
| POST | `/historify/api/jobs/<job_id>/pause` | Pause a job |
| POST | `/historify/api/jobs/<job_id>/resume` | Resume a job |
| POST | `/historify/api/jobs/<job_id>/retry` | Retry a failed/cancelled job |

Job creation accepts `job_type`, `symbols`, `interval`, `start_date`, `end_date`, optional `config`, and `incremental`. Job transitions are validated by the service; a request cannot force an arbitrary persisted status.

### Schedules

| Method | Path | Purpose |
|---|---|---|
| GET | `/historify/api/schedules` | List schedules with next-run data |
| POST | `/historify/api/schedules` | Create an interval or daily schedule |
| GET | `/historify/api/schedules/<schedule_id>` | Read one schedule |
| PUT | `/historify/api/schedules/<schedule_id>` | Update a schedule |
| DELETE | `/historify/api/schedules/<schedule_id>` | Delete a schedule |
| POST | `/historify/api/schedules/<schedule_id>/enable` | Enable a schedule |
| POST | `/historify/api/schedules/<schedule_id>/disable` | Disable a schedule |
| POST | `/historify/api/schedules/<schedule_id>/pause` | Pause a schedule |
| POST | `/historify/api/schedules/<schedule_id>/resume` | Resume a schedule |
| POST | `/historify/api/schedules/<schedule_id>/trigger` | Trigger execution now |
| GET | `/historify/api/schedules/<schedule_id>/executions` | List execution history, maximum 100 rows per request |

Schedules use the watchlist as their symbol source. `schedule_type` is `interval` or `daily`; stored data interval is currently `1m` or `D`. Interval schedules accept minutes/hours, daily schedules accept `HH:MM`, and `lookback_days` must be between 1 and 365.

## Response And Error Contract

JSON handlers generally return `{status: "success", ...}` or `{status: "error", message: ...}` with an appropriate HTTP status. Validation failures use 400, absent records/files use 404, and unexpected service failures use 500. File download routes return streamed file responses and delete their server-side temporary files after transfer.

Historify does not expose a separate WebSocket event API. Job and schedule status are read from the HTTP routes above; live market data continues to use the main WebSocket proxy.

## Data And Configuration Notes

- Local candles, catalog entries, jobs, metadata, schedules, and execution history are stored in Historify DuckDB.
- RESTX history with `source=db` reads the same local store through Historify database services.
- `.sample.env` and `blueprints/system_permissions.py` use `HISTORIFY_DATABASE_URL`, while `database/historify_db.py` uses `HISTORIFY_DATABASE_PATH`. This naming conflict remains open and neither name should be presented as universally authoritative.

## Ownership And Coverage

Routes are implemented in `blueprints/historify.py`; business logic is in `services/historify_service.py` and `services/historify_scheduler_service.py`; persistence is in `database/historify_db.py`. See `docs/bdd/historify_and_tools.feature`, `docs/prd/historify.md`, and `docs/prd/historify-data-model.md`.
