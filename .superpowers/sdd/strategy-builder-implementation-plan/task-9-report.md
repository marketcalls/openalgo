# Task 9 report — Greeks and broker-aware currency units

## Implemented

- Position Greeks now always apply `sideSign * lots * leg.lotSize`, independent
  of whether values are displayed as plain decimals or with a currency symbol.
- Active futures add their signed contract quantity to delta and contribute
  zero gamma, theta, and vega.
- Delta is labelled in underlying units and gamma in delta units per price
  point. Theta and vega are labelled as position-currency sensitivities per day
  and per 1% IV respectively; delta and gamma never receive currency symbols.
- Strategy Builder memoizes the existing shared
  `makeFormatCurrency(user?.broker)` helper and injects it into Greeks,
  positions, live P&L, and payoff-chart presentation.
- Removed the private INR formatters from `PositionsPanel` and `PnLTab`.
  Entry/current/exit prices, realized and live P&L, metrics, margin,
  breakevens, and chart hover values now use the injected formatter.
- Payoff hover data carries broker-formatted underlying and P&L strings, while
  Plotly's numeric axes retain the exact numeric data and stable scenario
  behavior. The y-axis title no longer hard-codes a rupee unit.

## Independent source validation

- The pre-change `GreeksTab` used `sign * quantity` only when the rupee toggle
  was selected; decimal mode used sign alone. This reproduced the two-lot
  quantity loss directly in component output.
- The pre-change aggregation skipped every non-option leg, so futures could
  not contribute delta.
- `services/option_greeks_service.py` documents the backend Greek convention:
  theta is daily theta and vega is per 1% volatility change. This supports the
  dimensional labels used by the table.
- `frontend/src/lib/utils.ts` already defines broker-aware currency behavior:
  broker `deltaexchange` uses USD/en-US and all other brokers use INR/en-IN.
  No additional currency formatter was created.
- The pre-change positions, live P&L, and payoff components contained private
  or inline INR/`en-IN` formatting. The retained task components and Strategy
  Builder page contain no hard-coded rupee/`en-IN` presentation.

## TDD evidence

- Initial RED: four component suites produced 8 expected failures. The failures
  exposed missing quantity scaling/test IDs, absent futures delta, ambiguous
  labels, private INR rendering in positions and live P&L, and hard-coded chart
  hover/y-axis currency.
- Hand-derived option fixture: `BUY * 2 lots * 100 lot size * 0.5 delta = 100`;
  theta is `2 * 100 * -3 = -600`, gamma is `2 * 100 * 0.02 = 4`, and vega is
  `2 * 100 * 5 = 1,000`.
- Hand-derived futures fixture: `BUY 2 * 50 - SELL 1 * 25 = +75` delta, with
  zero gamma/theta/vega.
- Page-wiring RED: while the page was deliberately held to the INR formatter,
  the real Delta Exchange positions output failed to find `$125.00`. Restoring
  `makeFormatCurrency(user?.broker)` made the regression pass.
- Label RED: the stronger position-currency theta/vega assertions failed until
  the dimensional basis was made explicit.
- Focused GREEN: the Greeks, positions, live-P&L, payoff-chart, and page suites
  pass 40 tests.

## Verification

- Full frontend: 29 files, 419 tests passed.
- `npm run lint` passed across 387 source files.
- `npx tsc -b --pretty false` passed.
- `npm run build` passed.
- Generated `frontend/dist` was restored to HEAD and ignored build-only assets
  were removed afterward.
- `git diff --check` passed before report creation.

## Concerns

- None within Task 9 scope. Live/scenario separation and P&L arithmetic were
  left unchanged; only their currency presentation was injected.
