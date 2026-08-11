# Task 7 report — closed-leg execution and per-leg metadata

## Implemented

- Added `StrategyLeg.contractValid` and the shared `isLegExecutable` predicate.
  An executable leg is active, not closed according to Task 6's `isLegClosed`
  (including `exitPrice: 0`), and has validated canonical tick metadata.
- Canonical option, future, template, manual, and edit resolution paths set and
  propagate `contractValid: true`.
- Saved legs begin with `contractValid: false`. After the restored identity has
  a current chain, a generation- and identity-guarded rehydration pass resolves
  every active open saved leg. It adopts canonical symbol/exchange/expiry/lot/
  tick/live metadata only for the same leg selection and preserves entry price.
  Pending or failed resolutions remain non-executable.
- The live dialog is `frontend/src/components/trading/ExecuteBasketDialog.tsx`.
  It now contains only executable rows, defaults inclusion only for those rows,
  uses exact `lots * lotSize`, and tick-normalizes with the leg's own `tickSize`
  without page-level lot or `0.05` tick fallbacks.
- The Positions action is disabled without any executable leg.

## Validation evidence

- `origin/main` establishes numeric `BasketOrderItem.quantity`/`price`; tests
  therefore assert the API's real numeric payload shape while preserving the
  documented uppercase `BUY`/`SELL`, `NRML`, and `LIMIT` constants from
  `docs/prompt/order-constants.md`.
- RED: the new dialog test exposed `STALE_SYMBOL` being displayed despite no
  canonical validation; the saved-leg page test exposed that a completed
  canonical restore still left Execute disabled.
- GREEN: dialog tests verify closed and stale omissions plus mixed `50`/`25`
  quantities and `10.05`/`101` tick-normalized prices. Page tests verify
  pending/failed saved rehydration is blocked and successful rehydration enables
  execution while preserving a `₹100.00` entry price.

## Commands run

- Focused: 63 tests across dialog, page, manual/edit, and strategy math suites.
- Full frontend: 26 files, 388 tests passed.
- `npm run lint`, `npx tsc -b`, and `npm run build` passed.
- Build output in `frontend/dist` was restored afterward.

## Fix Round 1

- Dialog rows now reconcile by exact contract identity while open. Surviving
  rows retain user inclusion, lots, price, product, and price type through live
  metadata updates; rows that become ineligible disappear and newly executable
  contracts start with defaults. Broker-owned lot/tick metadata still refreshes.
- Tick normalization now handles fractional ticks above one and exponent-form
  ticks. Regression payloads cover `2.5` (`101.3 → 102.5`) and `1e-7`
  (`1.5e-7 → 2e-7`).
- Saved-leg rehydration uses `Promise.allSettled`, allowing independently
  resolved contracts to become executable when another leg rejects. The
  attempt set is keyed by request identity and leg selection, so unchanged
  failed far contracts are not retried on live-chain updates. Changing identity
  or selection, or explicitly refreshing contracts, opens a retry boundary.
- RED/GREEN evidence: dialog tests initially showed reset rows and invalid tick
  payloads; page tests initially showed batch cancellation/unhandled rejection
  and repeated failed far resolution. Focused dialog/page tests now pass; full
  frontend verification reports 26 files and 392 tests passing, plus lint and
  TypeScript checks.
