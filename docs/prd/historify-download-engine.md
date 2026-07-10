# Historify Download Engine PRD

## Purpose

The download engine runs multi-symbol history jobs outside the request thread, persists per-symbol progress in DuckDB, and emits best-effort Socket.IO updates for the React Historify UI.

## Creation And Execution

`POST /historify/api/jobs` validates the logged-in session, resolves the user's OpenAlgo API key, and submits `create_and_start_job()` with:

- `job_type`: `custom`, `watchlist`, `option_chain`, or `futures_chain`.
- A non-empty array of `{symbol, exchange}` entries.
- `interval`, `start_date`, and `end_date`.
- Optional `config` and `incremental` behavior.

Jobs run on a shared `ThreadPoolExecutor`. `HISTORIFY_MAX_WORKERS` configures its size and defaults to 5.

## Persisted State

The job record stores status, counts, interval, date range, configuration, timestamps, and error details. Each job item stores symbol, exchange, status, record count, timestamps, and its own error.

Current job outcomes include `pending`, `running`, `paused`, `cancelled`, `completed`, `completed_with_errors`, and `failed`. Item outcomes include `pending`, `downloading`, `success`, `error`, and `skipped`.

## Worker Requirements

- Process only pending/downloading items so a checkpointed job can continue.
- Mark an item downloading before its broker request.
- Call the normalized history service and persist returned candles/catalog changes.
- Update job progress counters after every processed item.
- Keep one item's failure from terminating the remaining job.
- Finish as `completed` only with no item failures; otherwise use `completed_with_errors`.
- Clean in-memory running/pause state after completion, cancellation, or fatal error.

## Incremental Behavior

For an incremental job, inspect the stored first and last timestamps:

- Fetch an earlier missing range when requested start precedes stored data.
- Fetch a later missing range when requested end follows stored data.
- Skip an item when stored data already covers the requested range.
- For `1m`, allow the last stored day to be revisited so the intraday tail can be completed.

## Rate Protection

- Sleep a random `HISTORIFY_DELAY_MIN` to `HISTORIFY_DELAY_MAX` seconds between symbols; defaults are 1 to 3 seconds.
- After every 10 symbols processed in the current run, apply an additional random 5-to-10-second cooldown.
- The history service retains its own API rate behavior; these job delays protect longer broker request windows.

## Control Operations

| Method | Path | Rule |
|---|---|---|
| POST | `/historify/api/jobs/<job_id>/pause` | Only a running job can pause |
| POST | `/historify/api/jobs/<job_id>/resume` | Only a paused job can resume |
| POST | `/historify/api/jobs/<job_id>/cancel` | Running or paused jobs can cancel |
| POST | `/historify/api/jobs/<job_id>/retry` | Failed items reset to pending and are resubmitted |
| DELETE | `/historify/api/jobs/<job_id>` | A running job must be cancelled first |

Pause uses a `threading.Event`; cancellation is checked between items and while paused. Control transitions update DuckDB immediately and emit the corresponding Socket.IO event where implemented.

## Restart Recovery

The executor and pause/cancel signals are process-local. At startup, persisted running or paused jobs with no matching in-memory state are marked failed rather than silently appearing active. The user may then retry failed items.

## Ownership And Coverage

- Job service: `services/historify_service.py`
- Routes: `blueprints/historify.py`
- Persistence: `database/historify_db.py`
- Schedule-triggered jobs: `services/historify_scheduler_service.py`
- Acceptance coverage: `docs/bdd/historify_and_tools.feature`
