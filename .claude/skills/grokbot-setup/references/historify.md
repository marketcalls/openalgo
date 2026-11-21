# Historify: bulk watchlist, daily downloads, backfill and verification

Historify stores OHLCV in DuckDB at `db/historify.duckdb` inside the OpenAlgo
repo. The UI and endpoints live under `/historify` and `/historify/api/...`;
those endpoints need a logged-in web session, not the API key. Everything below
was proven on the box with a ~700-symbol daily watchlist (NIFTY 500 stocks, NSE
indices, BSE indices, global indices).

## 1. Build and upload a bulk watchlist

Historify has a bulk watchlist box that takes one `SYMBOL,EXCHANGE` per line.
Build a CSV in that exact shape (no header):

```
RELIANCE,NSE
NIFTY,NSE_INDEX
SENSEX,BSE_INDEX
```

- Stock lists: download the index constituents CSV (for example NIFTY 500) from
  niftyindices.com and map each symbol to `NSE`. Drop placeholder rows such as
  `DUMMY*` symbols.
- Index lists: take the `NSE_INDEX`, `BSE_INDEX` and `GLOBAL_INDEX` symbols from
  the master contract (the `symtoken` table), not from memory.
- Upload either by pasting into the Historify bulk-add box, or with a script
  that runs inside the repo (`os.chdir(repo)`, load the repo `.env`) and calls
  `services.historify_service.bulk_add_to_watchlist(symbols)`, the same function
  behind `POST /historify/api/watchlist/bulk`. Print `added`, `skipped` and
  `failed`, then count the watchlist by exchange.

## 2. Daily (1D) data only, 10-year backfill

- Ask the user which interval they want. For analysis watchlists, daily `D` is
  usually enough; intraday for hundreds of symbols is slow and heavy.
- Backfill: start one Historify download job for the watchlist with interval `D`
  and a start date 10 years back. Broker history APIs are rate limited, so a
  ~700-symbol, 10-year job takes a while; report progress from the job status or
  the `data_catalog` table rather than guessing.
- Some symbols never return data (discontinued indices, indices the broker does
  not serve, source data that stopped). After the backfill, list symbols with no
  rows or with a last date far behind, show them to the user, and remove them
  from the watchlist only with the user's approval. Keep a small exclude list in
  your scripts so they do not come back on the next import.

## 3. Incremental daily download (built-in scheduler)

Use Historify's own scheduler rather than a cron or routine:

- Create a daily schedule at **18:00 IST**, interval `D`, with a short lookback
  (7 days covers holidays and missed runs).
- The schedule is stored in the app's database and survives app restarts. It
  only runs while the app is running, and a run may start a few minutes late.
- Broker data must be available at run time, so the broker session must be live
  (Indian brokers: the 8:00 AM IST login covers the 18:00 run).

## 4. Reading DuckDB safely

The running app holds the DuckDB file. For ad hoc analysis copy it first and
read the copy:

```bash
cp db/historify.duckdb /tmp/historify.duckdb
```

```python
import duckdb
con = duckdb.connect("/tmp/historify.duckdb", read_only=True)
con.execute("SELECT symbol, exchange, last_timestamp, record_count "
            "FROM data_catalog WHERE interval = 'D'").fetchall()
```

For scripts that must read the live file, open `read_only=True` and retry on
`duckdb.IOException` with a short backoff while the app is writing. Never open
it read-write while the app runs. Timestamps are epoch seconds; convert to
Asia/Kolkata before taking the date.

## 5. Verify script pattern

Write a `verify.py` that exits `0` when everything is current, `1` when some
symbols are stale or missing, `2` on error, and supports `--json`:

- Reference latest trading day per group from the live REST API
  (`POST /api/v1/history`, interval `D`, last ~12 days): NIFTY (`NSE_INDEX`) for
  NSE stocks and NSE indices, SENSEX (`BSE_INDEX`) for BSE indices, and each
  global index's own latest candle (different holidays).
- Compare with `data_catalog.last_timestamp` per symbol; list ok, stale and
  missing per group.
- Fall back to the newest stored date in the group if the API is unreachable.

## 6. Daily verification routine

Create a routine shortly after the scheduled run (for example 18:30 IST on
trading days) that runs the verify script and reports one line: counts per group
and any stale or missing symbols. If stale, trigger an incremental download for
just those symbols and re-verify once. Do not log in to the broker from this
routine; the 8:00 AM login is the only broker login.
