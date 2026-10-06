---
name: backtest
description: Quick backtest a strategy on a symbol. Creates a complete .py script with data fetch, signals, backtest, stats, and plots.
argument-hint: "[strategy] [symbol] [exchange] [interval]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

Create a complete VectorBT backtest script for the user.

## Arguments

Parse `$ARGUMENTS` as: strategy symbol exchange interval

- `$0` = strategy name (e.g., ema-crossover, rsi, donchian, supertrend, macd, sda2, momentum)
- `$1` = symbol (e.g., SBIN, RELIANCE, NIFTY). Default: SBIN
- `$2` = exchange (e.g., NSE, NFO). Default: NSE
- `$3` = interval (e.g., D, 1h, 5m). Default: D

If no arguments, ask the user which strategy they want.

## Instructions

1. Read the vectorbt-expert skill rules for reference patterns
2. Create `backtesting/{strategy_name}/` directory if it doesn't exist (on-demand)
3. Create a `.py` file in `backtesting/{strategy_name}/` named `{symbol}_{strategy}_backtest.py`
4. Use the matching template from `rules/assets/{strategy}/backtest.py` as the starting point
5. The script must:
   - Load `.env` from the project root using `find_dotenv()` (walks up from script dir automatically)
   - Fetch data via `client.history()` from OpenAlgo
   - If user provides a DuckDB path, load data directly via `duckdb.connect(path, read_only=True)` instead of OpenAlgo API. Auto-detect format: Historify (`market_data` table, epoch timestamps) vs custom (`ohlcv` table, date+time). See vectorbt-expert `rules/duckdb-data.md`.
   - If `openalgo.ta` is not importable (standalone DuckDB), use inline `exrem()` fallback.
   - **Use OpenAlgo ta for ALL indicators by default** (EMA, SMA, RSI, MACD, BBands, ATR, ADX, STDDEV, MOM, and 90+ more) - `from openalgo import ta`
   - **Only use TA-Lib if the user explicitly says "talib"/"TA-Lib"** in their request; specialty indicators (Supertrend, Donchian, Ichimoku, HMA, KAMA, ALMA, ZLEMA, VWMA) always come from OpenAlgo ta regardless, since TA-Lib has no equivalent
   - Use `ta.exrem()` to clean duplicate signals (always `.fillna(False)` before exrem)
   - Run `vbt.Portfolio.from_signals()` with `min_size=1, size_granularity=1`
   - **Indian delivery fees**: `fees=0.00111, fixed_fees=20` for delivery equity
   - Fetch NIFTY benchmark via OpenAlgo (`symbol="NIFTY", exchange="NSE_INDEX"`)
   - Print full `pf.stats()`
   - **Print Strategy vs Benchmark comparison table** (Total Return, Sharpe, Sortino, Max DD, Win Rate, Trades, Profit Factor)
   - **Explain the backtest report** in plain language for normal traders
   - Generate the OpenStatz interactive dashboard tearsheet via `ostz.dashboard(...)` if `openstatz` is available - a self-contained offline HTML file, no server needed (always use OpenStatz, never QuantStats; never the legacy `ostz.reports.html` static report). **Set `strategy_returns.name` (e.g. `"EMA 20/50 Crossover - SBIN"`) and `benchmark.name` before calling `dashboard()`** - that name, not the `title=` argument, is what the tearsheet shows as the strategy header/column/legend (see the openstatz-tearsheet rule)
   - Plot equity curve + drawdown using Plotly (`template="plotly_dark"`)
   - Export trades to CSV
5. Never use icons/emojis in code or logger output
6. For futures symbols (NIFTY, BANKNIFTY), use lot-size-aware sizing:
   - NIFTY: `min_size=65, size_granularity=65` (effective 31 Dec 2025)
   - BANKNIFTY: `min_size=30, size_granularity=30`
   - Use `fees=0.00018, fixed_fees=20` for F&O futures

## Available Strategies

| Strategy | Keyword | Template |
|----------|---------|----------|
| EMA Crossover | `ema-crossover` | `assets/ema_crossover/backtest.py` |
| RSI | `rsi` | `assets/rsi/backtest.py` |
| Donchian Channel | `donchian` | `assets/donchian/backtest.py` |
| Supertrend | `supertrend` | `assets/supertrend/backtest.py` |
| MACD Breakout | `macd` | `assets/macd/backtest.py` |
| SDA2 | `sda2` | `assets/sda2/backtest.py` |
| Momentum | `momentum` | `assets/momentum/backtest.py` |
| Dual Momentum | `dual-momentum` | `assets/dual_momentum/backtest.py` |
| Buy & Hold | `buy-hold` | `assets/buy_hold/backtest.py` |
| RSI Accumulation | `rsi-accumulation` | `assets/rsi_accumulation/backtest.py` |

## Benchmark Rules

- Default: NIFTY 50 via OpenAlgo (`symbol="NIFTY", exchange="NSE_INDEX"`)
- If user specifies a different benchmark, use that instead
- For yfinance: use `^NSEI` for India, `^GSPC` (S&P 500) for US markets
- Always compare: Total Return, Sharpe, Sortino, Max Drawdown

## Example Usage

`/backtest ema-crossover RELIANCE NSE D`
`/backtest rsi SBIN`
`/backtest supertrend NIFTY NFO 5m`
