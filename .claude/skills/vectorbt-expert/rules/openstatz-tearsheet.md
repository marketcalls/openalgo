---
name: openstatz-tearsheet
description: OpenStatz tearsheet integration - modern interactive offline dashboard, metrics, Monte Carlo for portfolio analytics. OpenStatz replaces QuantStats project-wide.
metadata:
  tags: openstatz, quantstats, tearsheet, dashboard, report, metrics, monte-carlo, analytics, risk
---

# OpenStatz Tearsheet Integration

**OpenStatz is the required tearsheet library for this project - never use QuantStats.** OpenStatz is a modern, actively-maintained rebuild of QuantStats. Its metrics carry an enforced numerical-parity contract (`rtol=1e-9`) against QuantStats, but its tearsheet is a completely different, modern product: `ostz.dashboard(...)` renders the same interactive React dashboard that `openstatz serve` serves (live lightweight-charts, bespoke SVG stat panels) into a single self-contained offline `.html` file. Always generate the dashboard tearsheet after every backtest.

**Always use `ostz.dashboard(...)` for the tearsheet - never the legacy `ostz.reports.html/full/basic/plots(...)` static matplotlib reports.** Those reproduce the old QuantStats look and are deliberately excluded from this project.

## The dashboard runs standalone - no server required

`ostz.dashboard(...)` does **not** need `openstatz serve`, the `[app]` FastAPI extra, or any network access. It computes the analysis with pure pandas/numpy and inlines the pre-built web UI plus the data into one offline file. The published wheel bundles that built UI, so it works on a plain `pip install openstatz`. Open the resulting `.html` in any browser - no localhost, no server.

## Installation

```bash
pip install openstatz --upgrade
```

## Import Alias: Use `ostz`, Not `os`

OpenStatz's own docs suggest `import openstatz as os`, but every backtest script in this project already does `import os` for `os.getenv()` (API keys) and path handling. **Always alias it as `ostz`** to avoid shadowing the stdlib `os` module:

```python
import openstatz as ostz
```

(The QuantStats-compatible alias `qs` also works if you are porting old code, but prefer `ostz` in new scripts for clarity.)

## Basic Usage with VectorBT

After running a VectorBT backtest, extract returns and generate the dashboard tearsheet:

```python
import openstatz as ostz

# Extract daily returns from VectorBT portfolio
strategy_returns = pf.returns()

# If returns have timezone, remove it
if strategy_returns.index.tz is not None:
    strategy_returns.index = strategy_returns.index.tz_convert(None)

# IMPORTANT: name the series - this is what the tearsheet displays as the
# strategy header, metrics column, and chart legend. Without it the dashboard
# shows "Strategy" (or the price-column name like "close"). The title= argument
# below only sets the browser-tab <title>, NOT the on-page strategy name.
strategy_returns.name = "EMA Crossover"          # your strategy's name

# dashboard() needs the benchmark as a RETURNS SERIES, not a ticker string.
# (Unlike the removed reports.html, it does not download tickers for you.)
benchmark = ostz.providers.download_returns("^NSEI")          # NIFTY 50
benchmark = benchmark.reindex(strategy_returns.index).fillna(0)
benchmark.name = "NIFTY 50"                       # names the benchmark column too

# Generate the modern interactive offline tearsheet
ostz.dashboard(
    strategy_returns,
    benchmark=benchmark,
    output="tearsheet.html",
    title="EMA Crossover Tearsheet",   # browser tab only - not the on-page name
    open_browser=True,                 # set False in headless/automated runs
)
print("Tearsheet saved to tearsheet.html")
```

**`title=` names the browser tab; `.name` names the strategy inside the sheet.** The
on-page `<h1>` header, the metrics-table column, and the chart legends all come from
the pandas Series' `.name` attribute (it defaults to `"Strategy"` when unset). Always
set `strategy_returns.name` (and `benchmark.name`) before calling `dashboard()`.

## Benchmark Options

`dashboard()` requires the benchmark as a `pd.Series` of returns. Fetch it once, align it to the strategy index, then pass the Series:

```python
# Indian Market - NIFTY 50
benchmark = ostz.providers.download_returns("^NSEI")

# US Market - S&P 500
benchmark = ostz.providers.download_returns("SPY")

# Custom benchmark from OpenAlgo (convert close prices to returns first)
benchmark = bench_close.pct_change().dropna()

# In every case, align to the strategy index (and name it) before passing:
benchmark = benchmark.reindex(strategy_returns.index).fillna(0)
benchmark.name = "NIFTY 50"
ostz.dashboard(strategy_returns, benchmark=benchmark, output="tearsheet.html")
```

Running without a benchmark is also fine - just omit it (still name the strategy):

```python
strategy_returns.name = "EMA Crossover"
ostz.dashboard(strategy_returns, output="tearsheet.html", title="EMA Crossover Tearsheet")
```

## Console Metrics (numbers only, no UI)

For a plain-text metrics table in the console (e.g. logging a summary), use `reports.metrics`. This prints numbers only - it does not open a UI or produce the old static report:

```python
ostz.reports.metrics(returns, mode="full")       # Full metrics table to console
ostz.reports.metrics(returns, mode="basic")      # Basic metrics table to console
```

## Key Metrics (ostz.stats)

Individual metric values as raw numbers - use these to build the plain-language report or a comparison table:

```python
import openstatz as ostz

returns = pf.returns()

# Performance
ostz.stats.cagr(returns)                          # CAGR
ostz.stats.sharpe(returns)                        # Sharpe Ratio
ostz.stats.sortino(returns)                       # Sortino Ratio
ostz.stats.adjusted_sortino(returns)              # Adjusted Sortino
ostz.stats.calmar(returns)                        # Calmar Ratio

# Risk
ostz.stats.max_drawdown(returns)                  # Max Drawdown
ostz.stats.volatility(returns)                    # Annualized Volatility
ostz.stats.value_at_risk(returns)                 # VaR (95%)
ostz.stats.conditional_value_at_risk(returns)     # CVaR / Expected Shortfall
ostz.stats.ulcer_index(returns)                   # Ulcer Index

# Trade Analysis (period-based)
ostz.stats.win_rate(returns)                      # Win Rate (% positive days)
ostz.stats.profit_factor(returns)                 # Profit Factor
ostz.stats.payoff_ratio(returns)                  # Payoff Ratio
ostz.stats.consecutive_wins(returns)              # Max Consecutive Wins
ostz.stats.consecutive_losses(returns)            # Max Consecutive Losses

# Other
ostz.stats.best(returns)                          # Best day/period
ostz.stats.worst(returns)                         # Worst day/period
ostz.stats.avg_win(returns)                       # Average winning day
ostz.stats.avg_loss(returns)                      # Average losing day
ostz.stats.kelly_criterion(returns)               # Kelly Criterion
ostz.stats.risk_of_ruin(returns)                  # Risk of Ruin
ostz.stats.information_ratio(returns, benchmark)  # Information Ratio
ostz.stats.gain_to_pain_ratio(returns)            # Gain to Pain Ratio
ostz.stats.tail_ratio(returns)                    # Tail Ratio
ostz.stats.outlier_win_ratio(returns)             # Outlier Win Ratio
ostz.stats.outlier_loss_ratio(returns)            # Outlier Loss Ratio
```

All of these charts are already rendered interactively inside the `ostz.dashboard(...)` tearsheet (cumulative returns, drawdowns, rolling Sharpe/Sortino/volatility/beta, monthly heatmap, distribution). There is no separate matplotlib plotting step in this project.

## Monte Carlo Simulations

Monte Carlo probabilities as numbers (bust / goal), for the plain-language report:

```python
import openstatz as ostz

returns = pf.returns()

mc = ostz.stats.montecarlo(returns, sims=1000, bust=-0.20, goal=0.50)

print(f"Bust probability (>20% loss): {mc.bust_probability:.1%}")
print(f"Goal probability (>50% gain): {mc.goal_probability:.1%}")
```

## Complete Backtest Integration Template

Add this block at the end of every backtest script:

```python
# --- OpenStatz Tearsheet (modern interactive offline dashboard) ---
try:
    import openstatz as ostz

    strategy_returns = pf.returns()
    if strategy_returns.index.tz is not None:
        strategy_returns.index = strategy_returns.index.tz_convert(None)

    # Name the series so the tearsheet header/column/legend show the strategy
    # name, not "Strategy" or the price-column name. STRATEGY_NAME is a
    # descriptive label you set for the run, e.g. "EMA 20/50 Crossover".
    strategy_returns.name = f"{STRATEGY_NAME} - {SYMBOL}"

    # dashboard() needs the benchmark as a returns Series (not a ticker string)
    benchmark = ostz.providers.download_returns("^NSEI")
    benchmark = benchmark.reindex(strategy_returns.index).fillna(0)
    benchmark.name = "NIFTY 50"

    tearsheet_file = script_dir / f"{SYMBOL}_tearsheet.html"
    ostz.dashboard(
        strategy_returns,
        benchmark=benchmark,
        output=str(tearsheet_file),
        title=f"{STRATEGY_NAME} - {SYMBOL}",   # browser tab only
        open_browser=True,   # opens the tearsheet in the browser after each run
    )
    print(f"\nOpenStatz tearsheet saved to {tearsheet_file}")

    # Quick Monte Carlo (numbers for the plain-language report)
    mc = ostz.stats.montecarlo(strategy_returns, sims=1000, bust=-0.10, goal=0.30)
    print(f"Monte Carlo (1000 sims): Bust prob={mc.bust_probability:.1%}, Goal prob={mc.goal_probability:.1%}")

except ImportError:
    print("\nOpenStatz not installed. Run: pip install openstatz")
    print("Skipping tearsheet generation.")
```

## Important Notes

- The tearsheet is always `ostz.dashboard(...)` - a self-contained offline HTML file with the interactive dashboard. It needs no `openstatz serve`, no `[app]` extra, and no network.
- **Set `strategy_returns.name` (and `benchmark.name`) before calling `dashboard()`.** That name is what the tearsheet displays as the strategy header (`<h1>`), the metrics-table column, and the chart legends. It defaults to `"Strategy"` when unset, and `pf.returns()` often inherits the price-column name (e.g. `"close"`), so an unnamed series shows the wrong label. The `title=` argument only rewrites the browser-tab `<title>` - it does **not** change any on-page label.
- `dashboard()` needs the benchmark as a `pd.Series` of returns. It does **not** accept a ticker string - fetch it with `ostz.providers.download_returns("^NSEI")` and reindex to the strategy index first.
- Do not use the legacy `ostz.reports.html/full/basic/plots(...)` or the `ostz.plots.*` matplotlib gallery in this project - they reproduce the old QuantStats static look. Use the dashboard for visuals, `ostz.stats.*` / `ostz.reports.metrics()` for raw numbers.
- OpenStatz analyzes **return series** (daily returns), not discrete trade data.
- Win Rate in OpenStatz = percentage of **days** with positive returns (not trade-level). For trade-level metrics, use VectorBT's `pf.trades.win_rate()` and `pf.trades.profit_factor()`. Both are valid - they measure different things.
- Always remove timezone from the returns index before passing to OpenStatz.
- For Indian market benchmark use `^NSEI` (NIFTY 50 on Yahoo Finance); for US market use `SPY` (S&P 500 ETF).
- Never alias the import as `os` in a backtest script - it shadows the stdlib `os` module already used for `os.getenv()`.
- If porting an existing QuantStats script instead of writing a new one, `openstatz.compat.install_quantstats_shim()` followed by `import quantstats as qs` lets old `qs.*` code run unchanged against the OpenStatz engine - but new scripts should call `openstatz` directly and use `ostz.dashboard(...)` for the tearsheet.
