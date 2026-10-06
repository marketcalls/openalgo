---
name: strategy-compare
description: Compare multiple strategies or directions (long vs short vs both) on the same symbol. Generates side-by-side stats table.
argument-hint: "[symbol] [strategies...]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

Create a strategy comparison script.

## Arguments

Parse `$ARGUMENTS` as: symbol followed by strategy names

- `$0` = symbol (e.g., SBIN, RELIANCE, NIFTY)
- Remaining args = strategies to compare (e.g., ema-crossover rsi donchian)

If only a symbol is given with no strategies, compare: ema-crossover, rsi, donchian, supertrend.
If "long-vs-short" is one of the strategies, compare longonly vs shortonly vs both for the first real strategy.

## Instructions

1. Read the vectorbt-expert skill rules for reference patterns
2. Create `backtesting/strategy_comparison/` directory if it doesn't exist (on-demand)
3. Create a `.py` file in `backtesting/strategy_comparison/` named `{symbol}_strategy_comparison.py`
3. The script must:
   - Fetch data once via OpenAlgo
   - If user provides a DuckDB path, load data directly via `duckdb.connect(path, read_only=True)`. See vectorbt-expert `rules/duckdb-data.md`.
   - If `openalgo.ta` is not importable (standalone DuckDB), use inline `exrem()` fallback.
   - **Use OpenAlgo ta for ALL indicators by default** (never VectorBT built-in). Only switch to TA-Lib if the user explicitly says "talib"/"TA-Lib"
   - **Always use OpenAlgo ta** for specialty indicators (Supertrend, Donchian, etc.) - no TA-Lib equivalent exists
   - Clean signals with `ta.exrem()` (always `.fillna(False)` before exrem)
   - Run each strategy on the same data
   - **Indian delivery fees**: `fees=0.00111, fixed_fees=20` for delivery equity
   - Collect key metrics from each into a side-by-side DataFrame
   - **Include NIFTY benchmark** in the comparison table (via OpenAlgo `NSE_INDEX`)
   - **Print Strategy vs Benchmark comparison table**: Total Return, Sharpe, Sortino, Max DD, Win Rate, Trades, Profit Factor
   - **Explain results** in plain language - which strategy performed best and why
   - Plot overlaid equity curves for all strategies using Plotly (`template="plotly_dark"`)
   - Save comparison to CSV
4. Never use icons/emojis in code or logger output

## Example Usage

`/strategy-compare RELIANCE ema-crossover rsi donchian`
`/strategy-compare SBIN long-vs-short ema-crossover`
