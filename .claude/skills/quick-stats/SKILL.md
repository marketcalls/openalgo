---
name: quick-stats
description: Quickly fetch data and print key backtest stats for a symbol with a default EMA crossover strategy. No file creation needed - runs inline in a notebook cell or prints to console.
argument-hint: "[symbol] [exchange] [interval]"
allowed-tools: Read, Bash, Glob, Grep
---

Generate a quick inline backtest and print stats. Do NOT create a file - output code directly for the user to run or execute in a notebook.

## Arguments

- `$0` = symbol (e.g., SBIN, RELIANCE). Default: SBIN
- `$1` = exchange. Default: NSE
- `$2` = interval. Default: D

## Instructions

Generate a single code block the user can paste into a Jupyter cell or run as a script. The code must:

1. Fetch data from OpenAlgo (or DuckDB if user provides a DB path, or yfinance as fallback)
2. **Use OpenAlgo ta** for EMA 10/20 crossover by default (never VectorBT built-in); only use TA-Lib if the user explicitly says "talib"/"TA-Lib"
3. Clean signals with `ta.exrem()` (always `.fillna(False)` before exrem)
4. Use **Indian delivery fees**: `fees=0.00111, fixed_fees=20`
5. Fetch **NIFTY benchmark** via OpenAlgo (`symbol="NIFTY", exchange="NSE_INDEX"`)
6. Print a compact results summary:

```
Symbol: SBIN | Exchange: NSE | Interval: D
Strategy: EMA 10/20 Crossover
Period: 2023-01-01 to 2026-02-27
Fees: Delivery Equity (0.111% + Rs 20/order)
-------------------------------------------
Total Return:    45.23%
Sharpe Ratio:    1.45
Sortino Ratio:   2.01
Max Drawdown:   -12.34%
Win Rate:        42.5%
Profit Factor:   1.67
Total Trades:    28
-------------------------------------------
Benchmark (NIFTY): 32.10%
Alpha:           +13.13%
```

7. **Explain** key metrics in plain language for normal traders
8. Show equity curve plot using Plotly (`template="plotly_dark"`)

## Example Usage

`/quick-stats RELIANCE`
`/quick-stats HDFCBANK NSE 1h`
