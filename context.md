# OpenAlgo fork - AI agent context

This file lets a new AI agent pick up where the previous session stopped
instead of starting from scratch. It is updated at the end of every task.

## Repository map

- Upstream: https://github.com/marketcalls/openalgo (remote `origin`)
- This fork's push remote: https://github.com/Narasimha722/openalgo_opensource
- Local branch: `main`. Current HEAD is `255f9099d` (merge of upstream's 43
  commits onto the local feature commit `ad1e96d21`).

## What this fork adds on top of upstream (feature: Intraday Position Calculator)

The charting terminal's Buy/Sell (One-Click off) opens a Position Calculator
dialog before placing an order. It auto-sizes the quantity from the user's
available capital and the symbol's intraday leverage multiplier, and adds
trade-type and risk controls.

Feature files (all local, verified working):

- `database/intraday_leverage_db.py` - Intraday Leverage DB (1,579 NSE stocks,
  1x/2x/4x/5x multipliers), init + lookup functions.
- `blueprints/intraday_leverage.py` - REST API exposing the multiplier lookup.
- `upgrade/migrate_intraday_leverage.py` - migration + seeds from the Excel
  sheet; registered in `upgrade/migrate_all.py`.
- `frontend/src/components/trading/PositionCalculator.tsx` - the dialog. New
  props/contract in the current head:
  - `onConfirm(outcome: PositionCalculatorOutcome)`
  - Buy/Sell toggle (top-right), Intraday/Overnight/GTT segmented control,
    hidden max-quantity formula, Stop Loss / Target Price / Trailing Stop Loss
    fields, GTT switch.
- `frontend/src/api/intradayLeverage.ts` - API client.
- `frontend/src/components/trading/ChartPane.tsx` - wiring: `onOrderRequest`
  opens the calculator; `handleCalcConfirm` writes qty/product into the
  terminal and calls `terminal.confirmOrder(action, type, opts)`.
- `frontend/src/pages/Holdings.tsx`, `frontend/src/pages/OptionChain.tsx` -
  same calculator, then open PlaceOrderDialog with outcome qty/action.
- `frontend/src/lib/trading/terminal.ts` - `confirmOrder(side, type, opts?)`
  and `_executeOrder(side, type, opts?)`. Risk params route through a SINGLE
  REST `POST /api/v1/placeorder`; otherwise the SocketIO feed path is used.
- `restx_api/schemas.py` - `OrderSchema` extended with `stoploss`, `target`,
  `trailing_stoploss` (float, optional) and `gtt` (bool, default false).
- `services/place_order_service.py` - the four risk keys are popped from
  `order_data` only in the LIVE broker branch (5 adapters forward the whole
  dict and would reject the unknown `gtt` key); sandbox path keeps them as
  metadata and logs preserve them via `original_data`.

## Order flow after the merge (this is the part a fresh agent must know)

Upstream (43 commits merged) redesigned the chart order path with a
One-Click armed/disarmed ticket system (`onOrderTicket` + `PlaceOrderDialog`
+ `buildOrderTicket`/`placeTicket`). Conflict resolution integrated both:

- `placeFromMenu(side, type)` -> always calls `_executeOrder(side, type)`.
  Guards run there, not in the caller.
- `_executeOrder(side, type, opts?)`:
  1. Guards: replay lock, symbol/trade present, quote-only, freeze limit,
     stop-on-wrong-side-of-LTP.
  2. `!opts && !this.armed` (menu click while One-Click is OFF):
     - `cb.onOrderRequest` set -> open the Position Calculator and return.
     - else `cb.onOrderTicket` set -> open the classic PlaceOrderDialog
       ticket and return.
     - else -> toast 'One-Click is off' and return.
  3. Otherwise (armed, or calculator confirm): double-fire cooldown, then
     place. `opts` present (calculator confirm) -> risk params sent via REST
     placeorder; else the normal `trade.place` feed path.
- `confirmOrder(side, type, opts?)` is what the calculator calls; it always
  places (opts present, never bounces to the ticket).
- `ChartPane` registers BOTH `onOrderRequest` (calculator) and
  `onOrderTicket` (ticket); the calculator wins when One-Click is off.
  Armed One-Click clicks still place instantly (upstream behaviour kept).

## Verified state

- Backend schema loads stoploss/target/trailing_stoploss/gtt correctly.
- Frontend `tsc -b` clean; `npx vitest run src/lib/trading/terminal.test.ts`
  -> 53 passed. `npm run build` clean; `PositionCalculator-*.js` chunk
  contains Intraday/Overnight/GTT/Risk Management.
- `frontend/dist` is freshly rebuilt for this merged head and tracks the
  feature; do not restore it (unlike the previous rule: this fork pushes it
  because there is no CI `commit-dist` job here; app.py serves it).

## Not yet done / open items

- Live-broker runtime verification of the calculator (both analyze/sandbox
  and live mode) - user tests.
- Optional: a future broker adapter could opt back in to consume
  stoploss/target/trailing_stoploss on a plain base order (currently only
  sandbox records them; live brokers place a single-leg order).
- GTT is currently a flag + Overnight product only; full
  `/place_gtt_order` trigger-leg placement is deferred (broker-specific).

## Task list history

1. Position calculator UX: Buy/Sell toggle, Intraday/Overnight/GTT, hidden
   formula, SL/TP/Trailing fields - DONE.
2. Backend risk-param schema + live strip / sandbox passthrough - DONE.
3. Merge 43 upstream commits (agent module, chart ticket redesign, shoonya /
   kotak fixes) - DONE.
4. Rebuild dist, create this file, push to Narasimha722/openalgo_opensource -
   DONE (this task).

Next task will be described in the next session.