# Portfolio Backtester Release Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct release-blocking portfolio calculation, broker integration, validation, and frontend coverage gaps, then validate and commit the branch locally without pushing.

**Architecture:** Keep the existing portfolio module boundaries. Make the engine the source of truth for realized paths and charges, make services serialize rather than reconstruct those results, and use small pure frontend helpers so analysis and export share one request contract. Add boundary tests at the engine, service, API, broker-mapping, and frontend levels.

**Tech Stack:** Python 3.14, pandas, NumPy, Flask-RESTX, Marshmallow, pytest, React 19, TypeScript 7, Vitest, Testing Library, Ruff, Biome, Vite.

## Global Constraints

- Work only in `D:\testing\openalgo-portfolio-hardening` on `feature/portfolio-backtester`.
- Preserve the other checkout's Zerodha edits, generated `frontend/dist` changes, stash, and handover.
- Use `uv` for every Python environment and command.
- Apply strict red-green TDD for every behavior change.
- Do not add sector, market-cap, index constituent, dividend, or pre-2015 data.
- Do not broadly split the portfolio service or pages in this pass.
- Do not push.

---

### Task 1: Clean-install dependency and test bootstrap

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `test/conftest.py`
- Modify: `docs/superpowers/specs/2026-07-31-portfolio-backtester-release-hardening-design.md`

**Interfaces:**
- Consumes: the exact `openstatz==0.4.1` pin already present in `requirements.txt`.
- Produces: a clean `uv sync` environment in which portfolio tests collect without a real `.env`.

- [ ] **Step 1: Preserve the failing clean-install evidence**

Run:

```powershell
$env:API_KEY_PEPPER='0000000000000000000000000000000000000000000000000000000000000000'
$env:DATABASE_URL='sqlite:///db/openalgo.db'
$env:APP_KEY='test-only-app-key'
uv run pytest test/test_portfolio_engine.py -q
```

Expected: 7 failures with `ModuleNotFoundError: No module named 'openstatz'`.

- [ ] **Step 2: Add deterministic test environment defaults**

Create `test/conftest.py`:

```python
"""Safe environment defaults for tests collected outside an installation."""

import os

os.environ.setdefault("API_KEY_PEPPER", "0" * 64)
os.environ.setdefault("DATABASE_URL", "sqlite:///db/openalgo-test.db")
os.environ.setdefault("APP_KEY", "test-only-app-key")
```

- [ ] **Step 3: Synchronize the project manifest**

Run:

```powershell
uv add "openstatz==0.4.1"
```

Confirm `pyproject.toml` and `uv.lock` contain the exact pin and no unrelated dependency update.

- [ ] **Step 4: Verify the baseline**

Run:

```powershell
uv run pytest test/test_portfolio_engine.py -q
```

Expected: `106 passed`.

- [ ] **Step 5: Commit**

```powershell
git add pyproject.toml uv.lock test/conftest.py docs/superpowers/specs/2026-07-31-portfolio-backtester-release-hardening-design.md
git commit -m "fix(portfolio): make clean installs reproducible"
```

### Task 2: Health, holdings, and Upstox contracts

**Files:**
- Modify: `portfolio/health.py`
- Modify: `portfolio/holdings.py`
- Modify: `broker/upstox/mapping/order_data.py`
- Modify: `test/test_portfolio_engine.py`
- Create: `test/test_upstox_holdings_mapping.py`

**Interfaces:**
- Produces: `grade_for(score)` with bands A/80, B/65, C/50, D/35, F/0.
- Produces: `holdings_summary()` with `has_cost_basis=False` unless every holding has a positive average price.
- Produces: Upstox holdings rows with the standard `ltp` key.

- [ ] **Step 1: Write failing health and partial-basis tests**

Add literal boundary assertions:

```python
@pytest.mark.parametrize(
    ("score", "grade"),
    [(80, "A"), (79.9, "B"), (65, "B"), (64.9, "C"),
     (50, "C"), (49.9, "D"), (35, "D"), (34.9, "F")],
)
def test_investor_health_grade_boundaries(score, grade):
    assert grade_for(score) == grade

def test_partial_cost_basis_never_fabricates_total_return():
    summary = holdings_summary([
        Holding("KNOWN", "NSE", 2, 100, 120, 40),
        Holding("UNKNOWN", "NSE", 1, 0, 200, 25),
    ])
    assert summary["invested"] is None
    assert summary["pnl"] == 65
    assert summary["pnl_pct"] is None
    assert summary["has_cost_basis"] is False
```

Add a parser test proving blank symbols and `nan` prices are dropped.

- [ ] **Step 2: Run the tests and verify RED**

Run the exact new node IDs. Expected failures: old grade letters, fabricated mixed-basis total, and invalid rows retained.

- [ ] **Step 3: Implement minimal health and holdings fixes**

Change `GRADES`, require a nonblank symbol, and use `math.isfinite` for parsed numerics. Define `has_cost_basis = all(h.average_price > 0 for h in holdings)` and publish aggregate invested/percentage only when true.

- [ ] **Step 4: Write and run the failing Upstox contract test**

Call the real `transform_holdings_data()` with a complete Upstox-shaped row and assert the literal normalized object contains:

```python
{
    "symbol": "INFY",
    "exchange": "NSE",
    "quantity": 2,
    "product": "D",
    "average_price": 100.0,
    "ltp": 120.0,
    "pnl": 40.0,
    "pnlpercent": 20.0,
}
```

Add a zero-average row and assert it does not divide by zero.

- [ ] **Step 5: Implement the Upstox key fix and verify GREEN**

Emit `ltp`, not `last_price`. Run the new Upstox tests and affected portfolio tests.

- [ ] **Step 6: Commit**

```powershell
git add portfolio/health.py portfolio/holdings.py broker/upstox/mapping/order_data.py test/test_portfolio_engine.py test/test_upstox_holdings_mapping.py
git commit -m "fix(portfolio): correct health and holdings contracts"
```

### Task 3: Price and charge validation plus cache isolation

**Files:**
- Modify: `portfolio/costs.py`
- Modify: `portfolio/data.py`
- Modify: `portfolio/engine.py`
- Modify: `restx_api/portfolio.py`
- Modify: `test/test_portfolio_engine.py`
- Create: `test/test_portfolio_service.py`

**Interfaces:**
- Produces: finite, non-negative `Charge` and `CostSchedule` values.
- Produces: `load_prices(..., source="api")` with no process-wide cache reuse.
- Produces: simulation rejection for non-finite or non-positive closes.

- [ ] **Step 1: Write validation tests and verify RED**

Add tests proving:

```python
with pytest.raises(ValueError, match="non-negative"):
    Charge("bad", "Bad", "turnover", rate=-0.01)

with pytest.raises(ValueError, match="positive finite"):
    run_backtest(matrix({"A": [100.0, 0.0]}), {"A": 100})
```

Add `load_prices` tests with a fake `get_history` returning different closes on two identical broker-source calls; assert two calls occur and the second result changes. Add a matching Historify-source cache test asserting one load.

- [ ] **Step 2: Implement dataclass and matrix guards**

Add `__post_init__` validation for charge basis/rate/flat/cap and schedule tax/slippage. Validate engine closes before division and validate assembled matrices before remembering them.

- [ ] **Step 3: Restrict caching to Historify**

Only read and write `_cache` when `source == "db"`. Do not put broker tokens into cache keys or retain them in memory.

- [ ] **Step 4: Harden the API charge schema**

Make nested override floats reject negative and non-finite values. Confirm invalid overrides return a structured 400 through a service/API boundary test.

- [ ] **Step 5: Verify GREEN and commit**

Run affected tests, then:

```powershell
git add portfolio/costs.py portfolio/data.py portfolio/engine.py restx_api/portfolio.py test/test_portfolio_engine.py test/test_portfolio_service.py
git commit -m "fix(portfolio): validate inputs and isolate broker history"
```

### Task 4: Engine cost truth and robustness calculations

**Files:**
- Modify: `portfolio/engine.py`
- Modify: `portfolio/walkforward.py`
- Modify: `services/portfolio_service.py`
- Modify: `test/test_portfolio_engine.py`
- Modify: `test/test_portfolio_service.py`

**Interfaces:**
- Produces: `BacktestResult.cost_breakdown: dict[str, float]`.
- Produces: `walk_forward(..., initial_capital: float)`.
- Produces: Monte Carlo paths with exactly the input return count.

- [ ] **Step 1: Write the failing realized-cost test**

Use a growing two-asset matrix and a schedule with a flat order charge plus value-based tax. Hand-calculate the charge at each rebalance value and assert `result.cost_breakdown["total"]` equals their sum, not `turnover * initial_capital`.

- [ ] **Step 2: Implement realized breakdown accumulation**

At each rebalance call the real schedule's `breakdown()` once, charge its `total`, and accumulate every line including orders. For flat-bps costs accumulate an actual total. Store the aggregate on `BacktestResult`.

- [ ] **Step 3: Write the failing walk-forward capital test**

Use a flat-per-order schedule where Rs 1,000 and Rs 1,000,000 produce visibly different relative costs. Assert the window result matches a direct backtest with the requested capital.

- [ ] **Step 4: Propagate `initial_capital` and verify GREEN**

Add the parameter to `walk_forward`, pass it into every `run_backtest`, and pass the service request capital into `walk_forward`.

- [ ] **Step 5: Write the failing full-length Monte Carlo test**

Add a private helper with the exact signature
`def _bootstrap_path(values: np.ndarray, block: int, rng: np.random.Generator) -> np.ndarray`.
Use 45 returns with block 20 and a deterministic fake RNG to assert the helper
returns exactly 45 observations and requests start indices with an exclusive
upper bound of `n - block + 1`, making the last legal start reachable. The
production change that must fail this test is returning only
`floor(45/20)*20 == 40` observations.

- [ ] **Step 6: Implement full-length block sampling**

Use `ceil(n / block)` blocks, sample starts from `[0, n - block]` inclusively, concatenate, and slice `[:n]`. Annualize over that same `n`.

- [ ] **Step 7: Serialize actual costs**

Replace service reconstruction with `result.cost_breakdown`. Map the schedule's generic `tax` line to the API's existing `gst` field for the Indian equity response so the frontend never receives `undefined`.

- [ ] **Step 8: Verify GREEN and commit**

```powershell
git add portfolio/engine.py portfolio/walkforward.py services/portfolio_service.py test/test_portfolio_engine.py test/test_portfolio_service.py
git commit -m "fix(portfolio): report realized costs and robust paths"
```

### Task 5: Attribution that reconciles to the real backtest

**Files:**
- Modify: `portfolio/attribution.py`
- Modify: `services/portfolio_service.py`
- Modify: `frontend/src/api/portfolio.ts`
- Modify: `frontend/src/pages/PortfolioBacktester.tsx`
- Modify: `test/test_portfolio_engine.py`

**Interfaces:**
- Consumes: holding returns, realized weight path, target weights, net portfolio returns, benchmark returns, and engine item contributions.
- Produces: `selection_effect + allocation_effect + cost_effect == excess_return`.

- [ ] **Step 1: Write failing dynamic reconciliation tests**

Build a two-asset matrix that drifts, rebalances, and pays nonzero costs. Assert:

```python
assert out["portfolio_return"] == pytest.approx(result.total_return)
assert (
    out["selection_effect"] + out["allocation_effect"] + out["cost_effect"]
) == pytest.approx(out["excess_return"])
assert sum(row["contribution"] for row in out["holdings"]) == pytest.approx(
    out["excess_return"]
)
```

The current average-weight implementation must fail the first assertion.

- [ ] **Step 2: Implement dynamic gross, net, and cost paths**

Compute gross daily portfolio returns from lagged realized weights. Compute the net total from the engine return series, selection from the equal-weight path, allocation from gross minus equal, and cost from net minus gross.

- [ ] **Step 3: Reconcile holding excess contributions**

Use engine net item contributions and subtract target-weighted benchmark total. Reject or mark unavailable when the required periods do not align rather than presenting an approximate value as exact.

- [ ] **Step 4: Update response types and copy**

Add `cost_effect` to the TypeScript interface and show it as a separate attribution row. Keep the explicit non-Brinson explanation.

- [ ] **Step 5: Verify GREEN and commit**

```powershell
git add portfolio/attribution.py services/portfolio_service.py frontend/src/api/portfolio.ts frontend/src/pages/PortfolioBacktester.tsx test/test_portfolio_engine.py
git commit -m "fix(portfolio): reconcile attribution to net results"
```

### Task 6: Broker feed-token and endpoint security coverage

**Files:**
- Modify: `restx_api/portfolio.py`
- Modify: `services/portfolio_service.py`
- Create: `test/test_portfolio_api.py`
- Modify: `test/test_portfolio_service.py`

**Interfaces:**
- Consumes: `get_auth_token_broker(api_key, include_feed_token=True)`.
- Produces: feed-token propagation through backtest, tearsheet, and holdings history.

- [ ] **Step 1: Build a real Flask-RESTX test app**

Register the real portfolio namespace on a minimal Flask app with rate limiting disabled. Mock only credential storage, broker I/O, and report generation; keep schema, routing, authentication branches, and response serialization real.

- [ ] **Step 2: Write and verify failing auth tests**

For each endpoint, post a complete request with an invalid key and assert 403 plus the public error message. This protects the previously fixed Historify auth bypass.

- [ ] **Step 3: Write and verify failing feed-token tests**

Return `("auth", "feed", "xts-broker")` from the credential boundary. Capture the arguments received by each real service entry point and assert the full token tuple reaches broker-history loading.

- [ ] **Step 4: Implement propagation**

Retrieve three values with `include_feed_token=True`; add `feed_token` to `analyse_live_holdings`; pass it to `run_portfolio_backtest`. Keep holdings retrieval on its existing auth-token contract.

- [ ] **Step 5: Verify generic 500 behavior**

Raise a sentinel exception inside each service boundary and assert no exception text appears in the response.

- [ ] **Step 6: Commit**

```powershell
git add restx_api/portfolio.py services/portfolio_service.py test/test_portfolio_api.py test/test_portfolio_service.py
git commit -m "fix(portfolio): preserve broker auth across API paths"
```

### Task 7: Tearsheet parity and frontend regression coverage

**Files:**
- Modify: `services/portfolio_service.py`
- Modify: `restx_api/portfolio.py`
- Create: `frontend/src/lib/portfolioRequest.ts`
- Create: `frontend/src/lib/portfolioRequest.test.ts`
- Modify: `frontend/src/components/portfolio/ChargeControls.tsx`
- Create: `frontend/src/components/portfolio/ChargeControls.test.tsx`
- Create: `frontend/src/components/portfolio/MonthlyReturnsHeatmap.test.tsx`
- Modify: `frontend/src/pages/PortfolioBacktester.tsx`
- Modify: `frontend/src/pages/PortfolioAnalyzer.tsx`
- Modify: `test/test_portfolio_service.py`
- Modify: `test/test_portfolio_api.py`

**Interfaces:**
- Produces: one `buildPortfolioRequest(form)` helper used by analysis and export.
- Produces: tearsheet service arguments identical to normal backtest cost arguments.
- Produces: frontend health tone derived from grade.

- [ ] **Step 1: Write a failing tearsheet parity test**

Patch only `openstatz.reports.html` and price loading. Pass nondefault charges, GST, slippage, and capital through the endpoint and assert the returns given to the renderer match a direct charged `run_backtest`.

- [ ] **Step 2: Factor backend cost construction**

Create one private service helper that builds `Costs | CostSchedule` from the request fields. Use it in normal backtests and tearsheets. Extend `generate_tearsheet` and its endpoint call with the complete cost configuration.

- [ ] **Step 3: Write the failing frontend request test**

Hand-assert the complete literal request generated from two holdings and nondefault charges. It must include `charges`, `gst_rate`, `slippage`, source, benchmark exchange, dates, and rebalance rule. Assert the default produces zero flat brokerage.

- [ ] **Step 4: Implement the shared request helper**

Move `ChargeState` and `DEFAULT_CHARGES` to `portfolioRequest.ts`. Make both Analyze and Tearsheet call the same helper. Keep the component importing the shared type and defaults.

- [ ] **Step 5: Add focused component tests**

Add a real `ChargeControls` interaction test that changes the exchange and observes the transaction-rate field update. Add a heatmap test with positive, negative, and null literal cells to catch fraction/percent regressions.

- [ ] **Step 6: Correct health presentation**

Add a small pure `healthGradeTone()` helper with tests proving A/B/C are not rendered as failures and D/F are. Use it in Analyzer and Backtester grade presentation.

- [ ] **Step 7: Verify GREEN and commit**

Run targeted backend and frontend tests, then:

```powershell
git add services/portfolio_service.py restx_api/portfolio.py frontend/src/lib/portfolioRequest.ts frontend/src/lib/portfolioRequest.test.ts frontend/src/components/portfolio/ChargeControls.tsx frontend/src/components/portfolio/ChargeControls.test.tsx frontend/src/components/portfolio/MonthlyReturnsHeatmap.test.tsx frontend/src/pages/PortfolioBacktester.tsx frontend/src/pages/PortfolioAnalyzer.tsx test/test_portfolio_service.py test/test_portfolio_api.py
git commit -m "fix(portfolio): keep exports and UI on one contract"
```

### Task 8: Branch hygiene, security review, and final validation

**Files:**
- Modify branch-introduced Python/TypeScript files only as required by gates.
- Modify: `PORTFOLIO_HANDOVER.md` only if it exists in the isolated worktree and is explicitly selected for the final commit; otherwise leave it outside.

**Interfaces:**
- Produces: evidence-backed validation and a local-only commit history.

- [ ] **Step 1: Resolve branch-introduced static findings**

Fix the undefined `PriceMatrix` annotation import, unused exception bindings,
portfolio import order, explicit `zip(..., strict=True)`, and the unnecessary
`height` React effect dependency. Do not churn unrelated pre-existing files.

- [ ] **Step 2: Run targeted security review**

Trace API-key, symbol, date, charge, HTML, and broker-token inputs through the
real validation and output boundaries. Report only high-confidence exploitable
issues; record needs-verification items separately.

- [ ] **Step 3: Run full backend validation**

```powershell
uv run pytest test/test_portfolio_engine.py test/test_portfolio_service.py test/test_portfolio_api.py test/test_upstox_holdings_mapping.py -q
$files = git diff --name-only main...HEAD -- '*.py'
uv run ruff check $files
uv run python -m py_compile $files
```

Expected: all tests pass, Ruff exits 0 for branch files, compilation exits 0.

- [ ] **Step 4: Run full frontend validation**

```powershell
Set-Location frontend
npm run test:run -- --reporter=dot
npx tsc -b --pretty false
$files = git -C .. diff --name-only main...HEAD -- 'frontend/src/*.ts' 'frontend/src/*.tsx' 'frontend/src/**/*.ts' 'frontend/src/**/*.tsx' | ForEach-Object { $_ -replace '^frontend/', '' }
npx biome lint --max-diagnostics=200 $files
npm run build
```

Expected: all Vitest files pass, TypeScript exits 0, Biome has no errors, Vite
build exits 0.

- [ ] **Step 5: Verify generated artifacts remain uncommitted**

Run:

```powershell
git status --short
git diff --check
git log --oneline main..HEAD
```

Confirm `frontend/dist` is absent from the staged/source diff in the isolated
worktree.

- [ ] **Step 6: Final requirement audit**

Re-read the design and map every confirmed defect to a passing regression test
or explicit documented constraint. If evidence is missing, continue work.

- [ ] **Step 7: Commit any final hygiene-only changes**

```powershell
git add portfolio/__init__.py portfolio/data.py portfolio/engine.py portfolio/walkforward.py restx_api/__init__.py restx_api/portfolio.py services/portfolio_service.py test/test_portfolio_engine.py frontend/src/components/portfolio/PortfolioLineChart.tsx
git diff --cached --check
git diff --cached
git commit -m "chore(portfolio): satisfy release validation gates"
```

- [ ] **Step 8: Confirm local-only outcome**

Run:

```powershell
git status --short
git branch --show-current
git log --oneline --decorate -12
git remote -v
```

Do not run `git push`. Report the isolated worktree path, commits, test counts,
remaining data constraints, and the accidental documentation commit still
present on `fix/zerodha-rate-limit` in the other checkout.
