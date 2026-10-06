---
name: optimize
description: Optimize strategy parameters using VectorBT. Tests parameter combinations and generates heatmaps.
argument-hint: "[strategy] [symbol] [exchange] [interval]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

Create a parameter optimization script for a VectorBT strategy.

## Arguments

Parse `$ARGUMENTS` as: strategy symbol exchange interval

- `$0` = strategy name (e.g., ema-crossover, rsi, donchian). Default: ema-crossover
- `$1` = symbol (e.g., SBIN, RELIANCE, NIFTY). Default: SBIN
- `$2` = exchange (e.g., NSE, NFO). Default: NSE
- `$3` = interval (e.g., D, 1h, 5m). Default: D

If no arguments, ask the user which strategy to optimize.

## Instructions

1. Read the vectorbt-expert skill rules for reference patterns
2. Create `backtesting/{strategy_name}/` directory if it doesn't exist (on-demand)
3. Create a `.py` file in `backtesting/{strategy_name}/` named `{symbol}_{strategy}_optimize.py`
4. The script must:
   - Load `.env` from project root using `find_dotenv()` and fetch data via OpenAlgo `client.history()`
   - If user provides a DuckDB path, load data directly via `duckdb.connect(path, read_only=True)`. See vectorbt-expert `rules/duckdb-data.md`.
   - If `openalgo.ta` is not importable (standalone DuckDB), use inline `exrem()` fallback.
   - **Use OpenAlgo ta for ALL indicators by default** (never VectorBT built-in). Only switch to TA-Lib if the user explicitly says "talib"/"TA-Lib"
   - **Always use OpenAlgo ta** for specialty indicators (Supertrend, Donchian, etc.) - no TA-Lib equivalent exists
   - Use `ta.exrem()` to clean signals (always `.fillna(False)` before exrem)
   - Define sensible parameter ranges for the chosen strategy
   - Use loop-based optimization to collect multiple metrics per combo
   - Track: total_return, sharpe_ratio, max_drawdown, trade_count for each combination
   - Use `tqdm` for progress bars
   - **Indian delivery fees**: `fees=0.00111, fixed_fees=20` for delivery equity
   - Find best parameters by total return AND by Sharpe ratio
   - Print top 10 results for both criteria
   - Generate Plotly heatmap of total return across parameter grid (`template="plotly_dark"`)
   - Generate Plotly heatmap of Sharpe ratio across parameter grid
   - **Fetch NIFTY benchmark** and compare best parameters vs benchmark
   - **Print Strategy vs Benchmark comparison table**
   - **Explain results** in plain language for normal traders
   - Save results to CSV
4. Never use icons/emojis in code or logger output
5. For futures symbols, use lot-size-aware sizing:
   - NIFTY: `min_size=65, size_granularity=65`
   - BANKNIFTY: `min_size=30, size_granularity=30`

## Default Parameter Ranges

| Strategy | Parameter 1 | Parameter 2 |
|----------|------------|-------------|
| ema-crossover | fast EMA: 5-50 | slow EMA: 10-60 |
| rsi | window: 5-30 | oversold: 20-40 |
| donchian | period: 5-50 | - |
| supertrend | period: 5-30 | multiplier: 1.0-5.0 |

## Example Usage

`/optimize ema-crossover RELIANCE NSE D`
`/optimize rsi SBIN`
