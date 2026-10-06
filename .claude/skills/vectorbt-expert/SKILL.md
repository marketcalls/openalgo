---
name: vectorbt-expert
description: VectorBT backtesting expert. Use when user asks to backtest strategies, create entry/exit signals, analyze portfolio performance, optimize parameters, fetch historical data, use VectorBT/vectorbt, compare strategies, position sizing, equity curves, drawdown charts, or trade analysis. Also triggers for openalgo.ta helpers (exrem, crossover, crossunder, flip, donchian, supertrend).
user-invocable: false
---

# VectorBT Backtesting Expert Skill

## Environment

- Python with vectorbt, pandas, numpy, plotly
- Data sources: OpenAlgo (Indian markets), DuckDB (direct database), yfinance (US/Global), CCXT (Crypto), custom providers
- DuckDB support: supports both custom DuckDB and OpenAlgo Historify format
- API keys loaded from single root `.env` via `python-dotenv` + `find_dotenv()` — never hardcode keys
- Technical indicators: **OpenAlgo ta** (DEFAULT - `from openalgo import ta`, 100+ indicators covering trend/momentum/volatility/volume/oscillators/statistical/hybrid). Use **TA-Lib** only if the user explicitly asks for TA-Lib/talib. NEVER use VectorBT built-in indicators either way.
- Specialty indicators (no TA-Lib equivalent, always `openalgo.ta`): Supertrend, Donchian, Ichimoku, HMA, KAMA, ALMA, ZLEMA, VWMA
- Signal cleaning: `openalgo.ta` for exrem, crossover, crossunder, flip (always, regardless of indicator library)
- Fee model: Indian market standard (STT + statutory charges + Rs 20/order)
- Benchmark: NIFTY 50 via OpenAlgo (`NSE_INDEX`) by default
- Charts: Plotly with `template="plotly_dark"`
- Environment variables loaded from single `.env` at project root via `find_dotenv()` (walks up from script dir)
- Scripts go in `backtesting/{strategy_name}/` directories (created on-demand, not pre-created)
- Never use icons/emojis in code or logger output

## Critical Rules

1. **Default to OpenAlgo ta** (`from openalgo import ta`) for ALL technical indicators (EMA, SMA, RSI, MACD, BBANDS, ATR, ADX, STDDEV, MOM, and 90+ more). **Only use TA-Lib if the user explicitly requests "talib"/"TA-Lib"** in their prompt. NEVER use `vbt.MA.run()`, `vbt.RSI.run()`, or any VectorBT built-in indicator with either library.
2. **Always use OpenAlgo ta** for indicators not in TA-Lib at all: Supertrend, Donchian, Ichimoku, HMA, KAMA, ALMA, ZLEMA, VWMA - these have no TA-Lib equivalent, so they're openalgo.ta even in a TA-Lib-opt-in script.
3. **Use OpenAlgo ta** for signal utilities: `ta.exrem()`, `ta.crossover()`, `ta.crossunder()`, `ta.flip()`. If `openalgo.ta` is not importable (standalone DuckDB), use inline `exrem()` fallback. See [duckdb-data](rules/duckdb-data.md).
4. **Always clean signals** with `ta.exrem()` after generating raw buy/sell signals. Always `.fillna(False)` before exrem.
5. **Market-specific fees**: India ([indian-market-costs](rules/indian-market-costs.md)), US ([us-market-costs](rules/us-market-costs.md)), Crypto ([crypto-market-costs](rules/crypto-market-costs.md)). Auto-select based on user's market.
6. **Default benchmarks**: India=NIFTY via OpenAlgo, US=S&P 500 (`^GSPC`), Crypto=Bitcoin (`BTC-USD`). See [data-fetching](rules/data-fetching.md) Market Selection Guide.
7. **Always produce** a Strategy vs Benchmark comparison table after every backtest.
8. **Always explain** the backtest report in plain language so even normal traders understand risk and strength.
9. **Plotly candlestick charts** must use `xaxis type="category"` to avoid weekend gaps.
10. **Whole shares**: Always set `min_size=1, size_granularity=1` for equities.
11. **DuckDB data loading**: When user provides a DuckDB path, load data directly using `duckdb.connect()` with `read_only=True`. Auto-detect format: OpenAlgo Historify (table `market_data`, epoch timestamps) vs custom (table `ohlcv`, date+time columns). See [duckdb-data](rules/duckdb-data.md).

## Modular Rule Files

Detailed reference for each topic is in `rules/`:

| Rule File | Topic |
|-----------|-------|
| [data-fetching](rules/data-fetching.md) | OpenAlgo (India), yfinance (US), CCXT (Crypto), custom providers, .env setup |
| [simulation-modes](rules/simulation-modes.md) | from_signals, from_orders, from_holding, direction types |
| [position-sizing](rules/position-sizing.md) | Amount/Value/Percent/TargetPercent sizing |
| [indicators-signals](rules/indicators-signals.md) | OpenAlgo ta indicator reference (default), TA-Lib opt-in, signal generation |
| [openalgo-ta-helpers](rules/openalgo-ta-helpers.md) | Complete OpenAlgo ta catalog (100+ indicators): exrem, crossover, Supertrend, Donchian, Ichimoku, MAs |
| [stop-loss-take-profit](rules/stop-loss-take-profit.md) | Fixed SL, TP, trailing stop |
| [parameter-optimization](rules/parameter-optimization.md) | Broadcasting and loop-based optimization |
| [performance-analysis](rules/performance-analysis.md) | Stats, metrics, benchmark comparison, CAGR |
| [plotting](rules/plotting.md) | Candlestick (category x-axis), VectorBT plots, custom Plotly |
| [indian-market-costs](rules/indian-market-costs.md) | Indian market fee model by segment |
| [us-market-costs](rules/us-market-costs.md) | US market fee model (stocks, options, futures) |
| [crypto-market-costs](rules/crypto-market-costs.md) | Crypto fee model (spot, USDT-M, COIN-M futures) |
| [futures-backtesting](rules/futures-backtesting.md) | Lot sizes (SEBI revised Dec 2025), value sizing |
| [long-short-trading](rules/long-short-trading.md) | Simultaneous long/short, direction comparison |
| [duckdb-data](rules/duckdb-data.md) | DuckDB direct loading, Historify format, auto-detect, resampling, multi-symbol |
| [csv-data-resampling](rules/csv-data-resampling.md) | Loading CSV, resampling with Indian market alignment |
| [walk-forward](rules/walk-forward.md) | Walk-forward analysis, WFE ratio |
| [robustness-testing](rules/robustness-testing.md) | Monte Carlo, noise test, parameter sensitivity, delay test |
| [pitfalls](rules/pitfalls.md) | Common mistakes and checklist before going live |
| [strategy-catalog](rules/strategy-catalog.md) | Strategy reference with code snippets |
| [openstatz-tearsheet](rules/openstatz-tearsheet.md) | OpenStatz interactive offline dashboard, metrics, Monte Carlo (replaces QuantStats) |

## Strategy Templates (in rules/assets/)

Production-ready scripts with realistic fees, NIFTY benchmark, comparison table, and plain-language report:

| Template | Path | Description |
|----------|------|-------------|
| EMA Crossover | `assets/ema_crossover/backtest.py` | EMA 10/20 crossover |
| RSI | `assets/rsi/backtest.py` | RSI(14) oversold/overbought |
| Donchian | `assets/donchian/backtest.py` | Donchian channel breakout |
| Supertrend | `assets/supertrend/backtest.py` | Supertrend with intraday sessions |
| MACD | `assets/macd/backtest.py` | MACD signal-candle breakout |
| SDA2 | `assets/sda2/backtest.py` | SDA2 trend following |
| Momentum | `assets/momentum/backtest.py` | Double momentum (MOM + MOM-of-MOM) |
| Dual Momentum | `assets/dual_momentum/backtest.py` | Quarterly ETF rotation |
| Buy & Hold | `assets/buy_hold/backtest.py` | Static multi-asset allocation |
| RSI Accumulation | `assets/rsi_accumulation/backtest.py` | Weekly RSI slab-wise accumulation |
| Walk-Forward | `assets/walk_forward/template.py` | Walk-forward analysis template |
| Realistic Costs | `assets/realistic_costs/template.py` | Transaction cost impact comparison |

## Quick Template: Standard Backtest Script

```python
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import vectorbt as vbt
from dotenv import find_dotenv, load_dotenv
from openalgo import api, ta

# --- Config ---
script_dir = Path(__file__).resolve().parent
load_dotenv(find_dotenv(), override=False)

SYMBOL = "SBIN"
EXCHANGE = "NSE"
INTERVAL = "D"
INIT_CASH = 1_000_000
FEES = 0.00111              # Indian delivery equity (STT + statutory)
FIXED_FEES = 20             # Rs 20 per order
ALLOCATION = 0.75
BENCHMARK_SYMBOL = "NIFTY"
BENCHMARK_EXCHANGE = "NSE_INDEX"

# --- Fetch Data ---
client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host=os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"),
)

end_date = datetime.now().date()
start_date = end_date - timedelta(days=365 * 3)

df = client.history(
    symbol=SYMBOL, exchange=EXCHANGE, interval=INTERVAL,
    start_date=start_date.strftime("%Y-%m-%d"),
    end_date=end_date.strftime("%Y-%m-%d"),
)
if "timestamp" in df.columns:
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp")
else:
    df.index = pd.to_datetime(df.index)
df = df.sort_index()
if df.index.tz is not None:
    df.index = df.index.tz_convert(None)

close = df["close"]

# --- Strategy: EMA Crossover (OpenAlgo ta - default indicator library) ---
ema_fast = ta.ema(close, 10)
ema_slow = ta.ema(close, 20)

buy_raw = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
sell_raw = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))

entries = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
exits = ta.exrem(sell_raw.fillna(False), buy_raw.fillna(False))

# --- Backtest ---
pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    init_cash=INIT_CASH, size=ALLOCATION, size_type="percent",
    fees=FEES, fixed_fees=FIXED_FEES, direction="longonly",
    min_size=1, size_granularity=1, freq="1D",
)

# --- Benchmark ---
df_bench = client.history(
    symbol=BENCHMARK_SYMBOL, exchange=BENCHMARK_EXCHANGE, interval=INTERVAL,
    start_date=start_date.strftime("%Y-%m-%d"),
    end_date=end_date.strftime("%Y-%m-%d"),
)
if "timestamp" in df_bench.columns:
    df_bench["timestamp"] = pd.to_datetime(df_bench["timestamp"])
    df_bench = df_bench.set_index("timestamp")
else:
    df_bench.index = pd.to_datetime(df_bench.index)
df_bench = df_bench.sort_index()
if df_bench.index.tz is not None:
    df_bench.index = df_bench.index.tz_convert(None)
bench_close = df_bench["close"].reindex(close.index).ffill().bfill()
pf_bench = vbt.Portfolio.from_holding(bench_close, init_cash=INIT_CASH, fees=FEES, freq="1D")

# --- Results ---
print(pf.stats())

# --- Strategy vs Benchmark ---
comparison = pd.DataFrame({
    "Strategy": [
        f"{pf.total_return() * 100:.2f}%", f"{pf.sharpe_ratio():.2f}",
        f"{pf.sortino_ratio():.2f}", f"{pf.max_drawdown() * 100:.2f}%",
        f"{pf.trades.win_rate() * 100:.1f}%", f"{pf.trades.count()}",
        f"{pf.trades.profit_factor():.2f}",
    ],
    f"Benchmark ({BENCHMARK_SYMBOL})": [
        f"{pf_bench.total_return() * 100:.2f}%", f"{pf_bench.sharpe_ratio():.2f}",
        f"{pf_bench.sortino_ratio():.2f}", f"{pf_bench.max_drawdown() * 100:.2f}%",
        "-", "-", "-",
    ],
}, index=["Total Return", "Sharpe Ratio", "Sortino Ratio", "Max Drawdown",
          "Win Rate", "Total Trades", "Profit Factor"])
print(comparison.to_string())

# --- Explain ---
print(f"* Total Return: {pf.total_return() * 100:.2f}% vs NIFTY {pf_bench.total_return() * 100:.2f}%")
print(f"* Max Drawdown: {pf.max_drawdown() * 100:.2f}%")
print(f"  -> On Rs {INIT_CASH:,}, worst temporary loss = Rs {abs(pf.max_drawdown()) * INIT_CASH:,.0f}")

# --- Plot ---
fig = pf.plot(subplots=['value', 'underwater', 'cum_returns'], template="plotly_dark")
fig.show()

# --- Export ---
pf.positions.records_readable.to_csv(script_dir / f"{SYMBOL}_trades.csv", index=False)
```

## Quick Template: DuckDB Backtest Script

```python
import datetime as dt
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import vectorbt as vbt

try:
    # Default: OpenAlgo ta for both indicators and signal cleaning
    from openalgo import ta
    exrem = ta.exrem
    ema = ta.ema
except ImportError:
    # Fallback ONLY when the openalgo package itself is not installed
    # (standalone DuckDB with no OpenAlgo). Use TA-Lib for indicators
    # and this inline exrem() replacement for signal cleaning.
    import talib as tl

    def ema(data, period):
        return pd.Series(tl.EMA(data.values, timeperiod=period), index=data.index)

    def exrem(signal1, signal2):
        result = signal1.copy()
        active = False
        for i in range(len(signal1)):
            if active:
                result.iloc[i] = False
            if signal1.iloc[i] and not active:
                active = True
            if signal2.iloc[i]:
                active = False
        return result

# --- Config ---
SYMBOL = "SBIN"
DB_PATH = r"path/to/market_data.duckdb"
INIT_CASH = 1_000_000
FEES = 0.000225              # Intraday equity
FIXED_FEES = 20

# --- Load from DuckDB ---
con = duckdb.connect(DB_PATH, read_only=True)
df = con.execute("""
    SELECT date, time, open, high, low, close, volume
    FROM ohlcv WHERE symbol = ? ORDER BY date, time
""", [SYMBOL]).fetchdf()
con.close()

df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str))
df = df.set_index("datetime").sort_index()
df = df.drop(columns=["date", "time"])

# --- Resample to 5min ---
df_5m = df.resample("5min", origin="start_day", offset="9h15min",
                     label="right", closed="right").agg({
    "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
}).dropna()
close = df_5m["close"]

# --- Strategy + Backtest (same as OpenAlgo template, but use the ema()/exrem() resolved above) ---
```

If the user explicitly asks for TA-Lib, skip the `try/except` above and `import talib as tl` directly instead - the exrem fallback is only for when `openalgo` itself is unavailable.
