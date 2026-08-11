# Task 8 report — coherent scenarios, PoP, and payoff chart

## Implemented

- Added a single `ScenarioState { spot, iv, daysElapsed, valuationTime }` in
  `strategyMath`. Strategy Builder derives it from the live spot, selected spot
  and IV shifts, the fractional-day horizon, and the corrected server clock.
- The same state now drives the payoff domain, current curve, shifted marker,
  expected-move bands, PoP distribution, summary P&L, curve label, and hover
  change basis. The streaming tab remains explicitly labelled `Live P&L` and
  does not receive scenario state.
- Replaced arithmetic expected-move bands with zero-rate lognormal quantiles:
  `spot * exp(-0.5 * sigma^2 * T +/- n * sigma * sqrt(T))`. The range and chart
  share the `lognormalPriceBand` helper, while PoP uses the identical lognormal
  convention.
- `probabilityOfProfit` now returns `number | null`; valid zero renders as
  `0.00%`, while missing samples, spot, IV, or horizon render unavailable.
- Payoff curves use selected-horizon labels such as `T+6h`, and multi-expiry
  strategies label the terminal curve `At First Expiry`. Both curves expose
  the same underlying/change/P&L hover fields with two-decimal precision.
- Plotly layout now has stable `uirevision: 'strategy-payoff'`.
- The time simulator exposes exact fractional remaining time. A sub-day expiry
  uses an hourly control and cannot show an unreachable `+1d`; the selected day
  fraction is passed unchanged into scenario valuation.

## Independent source validation

- `origin/main` passed shifted spot only to the Total P&L calculation, while
  payoff range, chart marker/bands, and PoP retained live spot and IV.
- `origin/main` calculated chart bands as arithmetic `spot +/- n * spot *
  sigma * sqrt(T)`, while PoP used a lognormal CDF.
- `origin/main` returned `0` for both unavailable and finite-zero PoP, and the
  positions panel rendered values only when `probOfProfit > 0`.
- `origin/main` hard-coded the dashed trace as `T+0`, omitted matching hover
  fields, and did not set Plotly `uirevision`.
- `origin/main` forced the simulator maximum to at least one day with
  `Math.max(1, Math.floor(maxDays))`, reproducing the sub-day `+1d` defect.
- The audit's near-expiry collision statement is not browser/pixel proven.
  This task removes the source-level positive-time floor at a zero horizon, but
  adds no speculative label suppression and does not claim the collision fixed.

## TDD evidence

- RED: the four requested suites produced 10 expected failures. They exposed
  the missing lognormal helper/range, nullable PoP contract, shifted chart
  marker and bands, stable zoom, dynamic `T+6h` label, symmetric hover fields,
  finite-zero PoP display, and sub-day control.
- Expected lognormal values were hand-derived literals: for spot `110`, IV
  `30%`, and `T=0.25`, one-sigma boundaries are `93.6187202159` and
  `126.3720540374`; two-sigma boundaries are `80.5783792325` and
  `146.8233797046`.
- GREEN: the four focused suites pass 29 tests. The integrated math/chart/
  positions/simulator/page/Live-P&L run passes 57 tests.

## Review fix round

- Normalized expiry identities to UTC calendar dates, so a leg carrying an
  authoritative timestamp and a legacy expiry string for the same event does
  not incorrectly trigger the multi-expiry label.
- Persisted contraction of the selected horizon when the nearest active expiry
  shortens, preventing a stale longer selection from resurfacing if that leg is
  later removed.
- Hardened lognormal bands and PoP against non-finite inputs and samples; those
  cases now use the unavailable contract instead of leaking `NaN`.
- RED regressions first reproduced the stale `+4d` selection and the mixed
  expiry/non-finite failures. GREEN passed the 57-test integrated run.

## Verification

- Full frontend: 28 files, 404 tests passed.
- `npm run lint` passed across 386 source files.
- `npx tsc -b --pretty false` passed.
- `npm run build` passed; generated `frontend/dist` was restored to HEAD and
  ignored build-only assets were removed afterward.
- `git diff --check` passed for the retained source/test/report changes.

## Verification target

- Reproduce near-expiry sigma/spot annotation spacing in real desktop and
  mobile browsers before choosing a pixel threshold or suppression policy.

## Fix Round 1

- RED: the 0.02-day and 0.23-day simulator regressions exposed non-integral
  native range partitions of `0.48` and `5.52`. Finite `1e308` IV/horizon and
  spot fixtures also reproduced `NaN`/`Infinity` bands, a contaminated payoff
  range, and `NaN` PoP. The focused RED run had 6 expected failures.
- Sub-day simulators now expose a native integer-index range and map each index
  to an equal positive time increment no larger than one hour. The terminal
  integer maps back to the exact `maxDays`; day mode retains its quarter-day
  step.
- Lognormal bands and PoP now validate sigma, square-root time, variance,
  sigma-time, drift, spread/exponents, price bounds, CDF ratios/log returns,
  z-scores, probability masses, accumulation, and the final result. Any
  non-finite derived value uses the existing unavailable/omitted-band contract.
- Pre-commit review reproduced a browser-specific step mismatch that DOM
  `change` alone did not expose: installed Chrome's End key stopped the decimal
  0.23-day range at `0.191666666666667`, while the integer range reached its
  terminal index `6`. It also found `spot * 1.1` could overflow independently
  of the omitted lognormal band.
- Second RED: three integer-range assertions and one finite extreme-spot range
  assertion failed. The payoff baseline now saturates an overflowed upper
  candidate at `Number.MAX_VALUE`, keeping the range finite.
- GREEN: simulator tests pass 4/4 and math tests pass 28/28. The requested
  math/simulator/page/chart/positions integration passes 64/64, including the
  representation-independent stale-horizon regression.
- Full verification: 28 files and 412 tests passed; lint passed across 386
  source files; standalone TypeScript and the production build passed.
  Generated `frontend/dist` was restored to HEAD and ignored build assets were
  removed afterward.
