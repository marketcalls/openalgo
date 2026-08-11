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
