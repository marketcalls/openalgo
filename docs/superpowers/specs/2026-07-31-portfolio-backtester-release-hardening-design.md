# Portfolio Backtester Release Hardening Design

## Objective

Make `feature/portfolio-backtester` safe to review and merge by correcting
confirmed defects that can change reported results, break an authenticated
broker path, or leave the new API and frontend without meaningful regression
coverage. Validate the complete branch and commit the hardening locally without
pushing it.

## Scope

This hardening pass covers:

- investor-facing calculations and labels that currently disagree with the
  underlying simulation;
- authentication and broker-token propagation through all three portfolio
  endpoints;
- the broker-history cache boundary;
- Upstox holdings normalization;
- API, service, engine, broker-mapping, and focused frontend regression tests;
- validation gates for the changed Python and TypeScript surfaces.

The following stay documented as constraints or future work:

- dividend and total-return history;
- sector, market-cap, and index-constituent data;
- pre-2015 crisis coverage;
- broad decomposition of the 793-line service and 1,847-line page;
- portfolio persistence, multi-portfolio comparison, and risk-management
  features;
- live-broker certification, which requires credentials and an active broker
  session that the automated suite cannot provide.

## Confirmed Defects

### Health grading

Academic grade cutoffs make an ordinary four-holding portfolio an `F` even when
several measured pillars are healthy. Keep every pillar and its published
working, but use portfolio-health bands calibrated for a composite diagnostic:

- `A`: 80 or higher
- `B`: 65 through 79.9
- `C`: 50 through 64.9
- `D`: 35 through 49.9
- `F`: below 35

The frontend must derive positive or negative presentation from the grade rather
than retaining the old score-60 boundary.

### Cost reporting and tearsheet parity

The engine charges each rebalance at the portfolio value on that session, but
the service reconstructs the itemized total later as aggregate turnover times
initial capital. That reconstruction is wrong after the portfolio value changes
and can also misapply per-order caps.

The engine will accumulate each actual `CostSchedule.breakdown()` produced
during simulation and expose the totals on `BacktestResult`. The API will
serialize those totals directly. Cost drag remains the terminal return
difference between the charged and cost-free paths, so it continues to include
the opportunity cost of charges.

Tearsheet generation will accept the same cost configuration as the normal
backtest and feed the charged return series to `openstatz`. The frontend will
build one complete request for both actions. The default frontend delivery
brokerage will match the backend default of zero instead of silently adding
Rs 20 per order.

### Attribution reconciliation

The current attribution applies one average weight to every session and calls
the result the actual portfolio. That does not reproduce a drifting or
rebalanced portfolio, and it ignores costs.

Attribution will use:

- lagged realized weights for the gross daily portfolio path;
- the engine's net return path for the reported portfolio result;
- an equal-weight path for the selection baseline;
- a distinct cost effect so selection, allocation, and cost reconcile to the
  actual net excess return;
- engine item contributions for per-holding net contribution, with benchmark
  return allocated by target weight so per-holding excess contributions
  reconcile to total net excess.

The response will retain the existing selection and allocation fields and add a
cost-effect field. Copy will state that this is a data-supported decomposition,
not Brinson-Fachler.

### Robustness calculations

Walk-forward runs currently fall back to Rs 100,000 even when the caller chose
another initial capital. This changes the effect of flat per-order brokerage.
The selected initial capital will be propagated to every window.

Monte Carlo paths currently truncate any remainder shorter than the configured
block while annualizing over the original sample length. Bootstrap enough
blocks to cover the full sample, truncate the generated path to exactly the
original length, and include the last legal block start.

### Live holdings

A mixed portfolio with one known and one missing acquisition price is currently
treated as if the entire cost basis were known. The partial invested amount is
then subtracted from the full current value, overstating P&L. Total invested
value and percentage return will be unavailable unless every included holding
has a usable cost basis; broker-reported P&L remains available.

Non-finite broker numerics and blank symbols will be rejected during
normalization instead of contaminating weights and downstream metrics.

### Broker API path

The endpoints retrieve only `(auth_token, broker)` and then invoke history
through the internal-auth branch, dropping the feed token required by XTS-style
brokers. The endpoints will retrieve and propagate
`(auth_token, feed_token, broker)` through backtests, tearsheets, and live
holdings analysis.

Broker-sourced history will not use the process-wide price cache. Broker data
can change during the day and can differ by broker; the deterministic Historify
path retains the bounded LRU cache.

### Upstox mapping

The new Upstox mapping emits `last_price`, while the shared frontend contract
uses `ltp`. Emit `ltp` so the Holdings page receives the price. Preserve the
average-price and zero-division fix with an explicit regression test.

### Input validation

Per-charge overrides must be finite and non-negative. Invalid overrides should
produce a user-correctable 400 response, not negative transaction costs or a
500. Price matrices must reject non-finite or non-positive closes before
simulation.

### Dependency manifest parity

`requirements.txt` pins `openstatz==0.4.1`, but `pyproject.toml` and `uv.lock`
omit it. A clean `uv sync`, which is the repository-mandated setup path, leaves
the portfolio metrics dependency unavailable and causes seven portfolio tests
to fail at import time. Add the same exact pin to the project metadata and lock
file so clean installs and deployed environments contain the package the
feature imports.

## API and Data Flow

For an authenticated request:

1. Marshmallow validates the request shape and numeric bounds.
2. The API key is always verified.
3. Broker source requests load the auth token, feed token, and broker.
4. The service loads and validates one price matrix.
5. The engine runs once and records actual costs and item contributions.
6. Analytics, robustness, attribution, crisis, structure, health, and insights
   consume that result.
7. JSON cleaning converts non-finite analytical values to `null`.
8. Tearsheets consume the same request configuration and charged return series.

Failures caused by user input or unavailable data remain structured 4xx
responses. Unexpected failures are logged with tracebacks and return generic
500 messages.

## Frontend Coverage

Use the existing Vitest, jsdom, and Testing Library setup. Add focused tests for:

- complete request construction, including charge settings and source;
- identical cost configuration for analysis and tearsheet export;
- zero-brokerage defaults;
- health-grade presentation after recalibration;
- critical charge-control interaction and validation behavior;
- at least one portfolio chart/component empty-data or lifecycle path where a
  regression would otherwise reach production unnoticed.

The tests will favor extracted pure request/presentation helpers where that
reduces page-level mocking without changing user behavior.

## Backend Coverage

Add regression tests that fail against the current branch for:

- the new health boundaries and representative four-holding classification;
- exact accumulated cost breakdown after portfolio growth;
- tearsheet cost propagation;
- attribution reconciliation under drift, rebalancing, and costs;
- walk-forward initial-capital propagation;
- full-length Monte Carlo paths;
- partial holdings cost basis;
- feed-token propagation for all broker-source endpoint flows;
- API-key rejection on all endpoints;
- no process-wide cache reuse for broker-source prices;
- negative or non-finite charge and price inputs;
- Upstox `ltp`, average price, and zero-cost-basis behavior.
- a clean `uv sync` environment importing `openstatz==0.4.1`.

## Validation and Commit

Before the local commit:

- run targeted red-green tests for each fix;
- run the portfolio and newly added backend tests;
- run the complete frontend Vitest suite;
- run TypeScript build checking;
- run Ruff on the branch Python files and resolve branch-introduced findings;
- run Biome lint on the changed frontend files;
- run the production frontend build;
- inspect the final diff and staged file list;
- stage only source, tests, and approved documentation;
- create a conventional local commit and verify that no push occurred.

Generated `frontend/dist` changes and the untracked handover remain outside the
hardening commit.
