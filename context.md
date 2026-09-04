# OpenAlgo fork - AI agent context

This file lets a new AI agent pick up where the previous session stopped
instead of starting from scratch. It is updated at the end of every task.

## Repository map

- Upstream: https://github.com/marketcalls/openalgo (remote `origin`)
- This fork's push remote: https://github.com/Narasimha722/openalgo_opensource
- Local branch: `main`. Prior HEAD was `fc1088865` (feature commit
  `ae8dd9dbe` + fork CI dist merge `c9fd8c5f6` + local dist rebuild
  `fc1088865`), before the TASK 6 commit lands.

## TASK 6 - calculator redesign + brokerage fees - IN PROGRESS (this session)

Ready for commit: backend estimator, API, tests, frontend client, calculator
redesign, order-book Charges column - all verified. Not yet pushed.

- **`data/broker_charges_comparison.csv`** (new): copy of the user's tariff
  sheet (`D:\Personal\broker_charges_comparison.csv`) + a Groww section
  appended (flat Rs 20/order, delivery Rs 0, STT/SEBI/stamp/txn mirroring
  Zerodha, delivery DP Rs 15 incl GST). Source had Fyers/Zerodha/Dhan only.
- **`services/brokerage_charges.py`** (new): pure estimator, no Flask. Reads
  the CSV once (lru_cache), resolves the segment from
  exchange/product/symbol/instrumenttype (`Equity Delivery`, `Equity Intraday`,
  `Futures`, `Options`; Dhan "Futures (Equity F&O)"/"Options (Equity F&O)"
  aliased), merges global rows ("All Equity Segments" GST/SEBI/IPFT and
  "DP Charges"/"Demat Account" DP) into every segment, returns per-component
  amounts + total + notes. Supported: `fyers, zerodha, dhan, groww`.
  Three parser defects fixed mid-task and pinned by tests: equity symbols
  ending in "CE"/"PE" (RELIANCE, BAJFINANCE) resolving to Options; STT
  "0.1% on buy and sell" parsing as sell-only; global-segment rows never
  loading. DP buy-row clash (Groww, Fyers) resolved by keeping the sell row.
- **`blueprints/brokerage_charges.py`** (new): `POST /brokerage-charges/api/estimate`
  and `/api/estimate/batch` (`{orders:[...]}`), both `@check_session_validity`,
  broker from session, 403 outside the supported four. Registered in `app.py`.
- **`frontend/src/api/brokerage.ts`** (new): `estimate` / `estimateBatch` via
  `webClient` (auto-CSRF). Exports `BROKERAGE_BROKERS` set for UI gating.
- **`PositionCalculator.tsx`** redesigned: header = symbol + live price beside
  it + exchange/product badges + Buy/Sell toggle; Trade Type tiles directly
  below; "Price" section (Market/Limit tiles + limit input + validation hint);
  Capital section; Quantity card with Leverage `Nx` as just the number, lot
  size, input + Max + max-qty readout, and a Brokerage chip that pops open the
  estimate breakdown. Risk Management is gone - replaced by an "Add Stop Loss /
  Target Price" expander (SL / Target / Trailing SL). Bid/ask display removed.
  Dialog widened to `sm:max-w-lg` with inner scroll. Brokerage chip hidden
  unless `authStore.user.broker` is in the supported set; estimate debounced
  400 ms, valued at LTP (Market) or the limit price (Limit).
- **`OrderBook.tsx`**: new "Charges" column (header + cell) only for supported
  brokers and `!isCrypto`; one batch call estimates every priced row
  (`price>0 && quantity>0`); cell shows the total with a hover tooltip
  (segment + per-component breakdown); unpriced rows stay blank.
- Verification done: `pytest test/test_brokerage_charges.py` 19/19 passed
  (locked vectors: Zerodha intraday BUY 100@500 = 21.07, delivery SELL =
  67.21 incl STT 50 + DP 15.34, Fyers options SELL 1 lot @200 lot75 = 54.00,
  Groww delivery SELL = 66.87 with DP 15, Dhan intraday BUY = 111.23, Zerodha
  Futures BUY 1 lot @48000 lot35 = 95.46); `ruff check` clean;
  `tsc -b` clean; `vitest terminal.test.ts` 53/53; biome lint clean;
  `npm run build` clean (new chunk `brokerage-*.js` contains
  `brokerage-charges/api`).
- Docs updated: `Documentation.md` (Task 6 section) + this file.

## TASK 5 - calculator leverage gate + Market/Limit + 3D UI - DONE

All plan items from the previous section are implemented, verified and
committed. Implementation summary (what changed vs the plan):

- `PositionCalculator.tsx`: `effectiveLeverage = tradeType === 'INTRADAY' ?
  leverage : 1`. Sizing basis is the LIMIT price when a Limit order is chosen
  with a valid price, else live LTP. `maxQuantity = floor(capital *
  effectiveLeverage / priceBasis)`. Outcome now carries `orderType` and
  `price?`. New 3D dark-glass styling (raised/inset `Tile` component, gradient
  glow cards, gradient CTAs) - pure Tailwind CSS, no new deps. Limit price
  must be beyond the market (buy below LTP, sell above LTP) or confirm is
  blocked with an explanation; the "scheduled order" semantics the user asked
  for.
- `terminal.ts`: `confirmOrder`/`_executeOrder` opts gain `price?: number`;
  `_executeOrder` prices LIMIT orders from `opts.price` instead of snapping
  to the chart context price.
- `ChartPane.tsx`: `handleCalcConfirm` passes `outcome.orderType` (was
  `calcParams.type`) and `outcome.price` into `confirmOrder`.
- Verified: `tsc -b` clean; `vitest terminal.test.ts` 53/53; biome lint
  clean; `npm run build` clean; rebuilt `PositionCalculator-*.js` chunk
  contains Market/Limit/"not applicable"/"cash value".
- Docs updated: `Documentation.md` (outcome/order-type/quantity/layout
  sections, terminal LIMIT-price note, change summary) and this file.

Existing plan section below is kept for reference history.

Goals (user requirements, verbatim intent):

1. Leverage must apply ONLY to INTRADAY. For OVERNIGHT and GTT the multiplier
   is not applicable: capital/price only (SBI at Rs 100, capital Rs 100 ->
   exactly 1 share). Current code fetches the intraday multiplier and uses it
   for every trade type - GATE IT.
2. New order-type selector in the calculator: MARKET vs LIMIT.
   - MARKET = execute now at current market price (leverage applies for
     Intraday, not for Overnight/GTT).
   - LIMIT = schedule at a chosen price; executes when the market reaches it
     (e.g. buy SBI only when it comes down to 80). Same leverage rules.
3. Rebuild the calculator UI as a "3D UI" (depth/raised-inset controls,
   glass gradients, glow). Keep every existing prop/outcome contract and the
   wiring below intact unless the plan says otherwise.

Design decisions:

- Effective multiplier = tradeType === 'INTRADAY' ? apiMultiplier : 1.
- Order price basis for sizing: LIMIT + valid price use the limit price;
  MARKET uses live LTP (currentPrice).
- maxQuantity = floor(capital * effectiveMultiplier / priceBasis). Clamp/
  reset user quantity when tradeType or orderType changes so it never exceeds
  the new max.
- Outcome gains `orderType: 'MARKET' | 'LIMIT'` and `price?: number` (limit
  price; required when LIMIT). Product/stoploss/target/trailingStoploss/gtt
  unchanged.
- Terminal: `confirmOrder`/`_executeOrder` opts gain `price?: number`;
  `_executeOrder` uses it for LIMIT px instead of snapping to ctx price.
  Both the REST risk path and the feed path already send px as `price`, so a
  LIMIT order with a user price flows through unchanged.
- ChartPane `handleCalcConfirm` passes `outcome.orderType` as the order type
  and `outcome.price` through opts (currently it forwards calcParams.type,
  which is always MARKET - change this).

Files to change: `frontend/src/components/trading/PositionCalculator.tsx`,
`frontend/src/lib/trading/terminal.ts`, `frontend/src/components/trading/
ChartPane.tsx`, `Documentation.md`, `context.md`.

Verification: `npx tsc -b`, `npx vitest run src/lib/trading/terminal.test.ts`,
`npm run build` (re-verify PositionCalculator chunk), then rebuild/commit
frontend/dist and update Documentation.md + this file.

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
  feature. Note: the fork's CI runs a `chore: auto-build frontend dist [skip ci]`
  job that pushes its own rebuild; when a push is rejected, merge fork/main
  (taking their dist), rebuild locally, `git add -A -- frontend/dist` +
  `git add -f -- frontend/dist`, commit, push (`origin` has no such job).

## Not yet done / open items

- User's own idea backlog lives in `task.txt` (repo root) - crypto calculator,
  per-stock news section, vertical candle-drag on the chart, scanners. Ask the
  user which to pick up next rather than guessing.
- Brokers outside Fyers/Zerodha/Dhan/Groww get no brokerage estimate (tariff
  sheet only covers those four). Treatment for trades on other brokers:
  hidden chip / blank column - intentional, per the user's list.
- Live-broker runtime verification of the calculator + Charges column (both
  analyze/sandbox and live mode) - user tests.
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
5. Calculator leverage gating + Market/Limit order type + 3D UI redesign -
   DONE (this task; summary at top of file).
6. Calculator redesign (stock+LTP header, Price section, Capital/Qty split,
   leverage as a number, Add SL/TP expander) + brokerage fees in calculator and
   order book (Fyers/Zerodha/Dhan/Groww) - IN PROGRESS: implemented and
   verified; commit + push pending. Summary at top of file.