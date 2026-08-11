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

## Fix Round 2

- Tick snapping now converts finite positive number strings (including
  scientific notation) into scaled `BigInt` coefficients before calculating
  the tick quotient. It applies exact decimal half-up rounding, then converts
  the exact tick multiple back to the numeric order payload.
- Literal payload regressions cover `101.3 / 2.5 → 102.5`,
  `0.15 / 0.1 → 0.2`, `1.005 / 0.01 → 1.01`, and
  `1.5e-7 / 1e-7 → 2e-7`; nonpositive prices remain non-submittable.
- RED/GREEN evidence: before the change, the new focused dialog test submitted
  `0.1` and `1` for the two decimal half cases. After the scaled-integer
  change, the focused suite passes (5 tests); lint, TypeScript, and the full
  frontend suite pass with 26 files and 393 tests. Production build also
  passes; generated `frontend/dist` output was restored afterward.

## Fix Round 3

- Tick normalization now returns an explicit invalid state when a finite
  source price would round to a non-finite numeric payload (or either input is
  invalid). It never falls back to the original, potentially off-tick value.
- Invalid LIMIT prices are retained in the dialog as an empty/error-marked row
  (`<symbol>: price is outside the supported tick range`) and disable Execute.
  A final submit-time normalization guard also marks a just-entered invalid
  value before omitting the basket request.
- RED/GREEN evidence: with `1.7e308` at tick `1e308`, the new dialog test
  initially found no invalid state and an enabled Execute button. It now shows
  the retained warning, disables execution, and confirms no basket request is
  sent. Prior exact decimal/scientific fixtures remain covered. Focused dialog
  tests pass (6); lint, TypeScript, full frontend (26 files, 394 tests), and
  production build pass; generated `frontend/dist` was restored afterward.
