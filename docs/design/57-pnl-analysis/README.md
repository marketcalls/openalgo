# 57 - P&L Analysis

One page (`/pnl`, menu "P&L") for realized and unrealized P&L over any date range, with
a cumulative curve, a per-strategy breakdown, a calendar heat map and day / week / month /
scrip views. It mirrors the way broker consoles report P&L, so the numbers can be checked
against a console statement.

## Data model

Brokers expose only today's tradebook, so history is kept by OpenAlgo itself.

- `db/tradebook.db` (`TRADEBOOK_DATABASE_URL`) holds `tradebook_fills`, one row per fill, and
  `pnl_capture_runs`, an audit log of the capture job.
- Realized P&L is never stored. Every request replays the fills through `utils/pnl_fifo.py`,
  the way the intraday PnL Tracker derives its numbers.
- Fills enter the ledger two ways:
  - **Capture** (opt-in): with `PNL_CAPTURE_ENABLED=true`, `services/pnl_capture_service.py`
    stores the day's tradebook at 15:40 IST on trading days. Off by default.
  - **CSV import**: `POST /api/v1/pnl/import` backfills history from a Zerodha Console
    tradebook CSV or a Kotak transaction statement. Re-importing an overlapping file is a no-op.
- The dedup key is date + exchange family + the broker's trade id (Zerodha re-uses trade ids
  on later days); fills without a trade id fall back to a hash of their fields.
- A fill's strategy comes from the order tag in the strategy book (`database/strategy_book_db.py`)
  at write time, and can be set by hand per fill with `PATCH /api/v1/pnl/trades/<id>/strategy`.

## Matching rules

These follow Zerodha Console, so the page reproduces its figures:

- Equity buys and sells of the same symbol on the same day are matched first, at the day's
  average prices. What is left goes to delivery FIFO.
- NSE and BSE are one security for equity. F&O stays plain time-ordered FIFO.
- Product is not part of the match key: a CSV-imported buy has no product and must still meet
  its later sell.
- Open lots at the end of a range are valued at the close of the last trading day in it.
  Lots missing from the ledger (IPO, ESOP, bonus) are added as ordinary rows through CSV import.

## API (`/api/v1/pnl/*`, `apikey` required)

| Endpoint | Purpose |
|---|---|
| `GET /history` | Closed lots, daily realized P&L and live open positions for a range; filters `symbol`, `segment`, `strategy` |
| `GET /curve` | Daily realized and unrealized P&L per strategy (equity), `basis=actual_cost` or `range_start` |
| `GET /trades` | Raw fills for a range, no matching (backs the historical Trade Book) |
| `POST /import` | Backfill from a CSV (multipart `file`) |
| `GET /strategy-legs` | Current strategy-book legs |
| `PATCH /trades/<id>/strategy` | Tag one fill |

## Code map

- Backend: `database/pnl_db.py`, `utils/pnl_fifo.py`, `services/pnl_history_service.py`,
  `services/pnl_curve.py`, `services/pnl_capture_service.py`, `services/strategy_attribution.py`,
  `restx_api/pnl_history.py`, `utils/kotak_statement.py`, `utils/broker_timestamp.py`.
- Frontend: `pages/PnlAnalysis.tsx`, `components/pnl/*`, `components/reports/*`,
  `hooks/usePnlAnalysisData.ts`, `hooks/usePnlFilters.ts`, `lib/pnl*.ts`. The model code in
  `lib/` is pure TypeScript with unit tests.
- Trade Book: `pages/TradeBook.tsx` gains a historical view, grouping of fills by order, and
  tagging a whole order at once (`lib/tradeGroups.ts`).

## Known gaps

Corporate actions (splits, bonuses) are not adjusted for. Unrealized P&L is equity only on the
curve; F&O open positions come from the live position book.
