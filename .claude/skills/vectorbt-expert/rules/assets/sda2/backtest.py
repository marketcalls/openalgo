"""
SDA2 Trend Following Backtest - VectorBT + OpenAlgo
Strategy: WMA-based channel with STDDEV and ATR bands.
Indicators: OpenAlgo ta WMA, STDDEV, ATR (default indicator library).
Fees: Indian delivery equity model (0.111% + Rs 20/order).
Benchmark: NIFTY 50 Index via OpenAlgo (NSE_INDEX).
"""

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
FEES = 0.00111
FIXED_FEES = 20
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
high = df["high"]
low = df["low"]
open_price = df["open"]

# --- Strategy: SDA2 Trend Following (OpenAlgo ta) ---
base = ((high + low) / 2.0) + (open_price - close)
derived = ta.wma(base, 3)

sd7 = ta.stdev(derived, 7)
atr2 = ta.atr(high, low, close, period=2)

upper = derived + sd7 + (atr2 / 1.5)
lower = derived - sd7 - (atr2 / 1.0)

buy_raw = (close > upper) & (close.shift(1) <= upper.shift(1))
sell_raw = (lower > close) & (lower.shift(1) <= close.shift(1))

entries = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
exits = ta.exrem(sell_raw.fillna(False), entries)

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
print("\n" + "=" * 60)
print(f"  SDA2 Trend Following - {SYMBOL} ({EXCHANGE})")
print("=" * 60)
print(pf.stats())

print("\n--- Strategy vs Benchmark ---")
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

print("\n--- Backtest Report Explanation ---")
print(f"* Total Return: Your strategy made {pf.total_return() * 100:.2f}% "
      f"while NIFTY 50 made {pf_bench.total_return() * 100:.2f}%")
alpha = pf.total_return() - pf_bench.total_return()
if alpha > 0:
    print(f"  -> BEAT the market by {alpha * 100:.2f}%")
else:
    print(f"  -> UNDERPERFORMED the market by {abs(alpha) * 100:.2f}%")
print(f"* Sharpe Ratio: {pf.sharpe_ratio():.2f} (return per unit of risk, >1 decent, >2 excellent)")
print(f"* Max Drawdown: {pf.max_drawdown() * 100:.2f}%")
print(f"  -> If you invested Rs {INIT_CASH:,}, the biggest temporary loss = Rs {abs(pf.max_drawdown()) * INIT_CASH:,.0f}")
print(f"* Win Rate: {pf.trades.win_rate() * 100:.1f}% - SDA2 is trend-following, expect 35-45%")
print(f"* Profit Factor: {pf.trades.profit_factor():.2f} - for every Rs 1 lost, you made Rs {pf.trades.profit_factor():.2f}")

fig = pf.plot(
    subplots=["value", "underwater", "cum_returns"],
    template="plotly_dark",
    title=f"SDA2 Trend Following - {SYMBOL} ({EXCHANGE} {INTERVAL})",
)
fig.show()

trades_file = script_dir / f"{SYMBOL}_sda2_trades.csv"
pf.positions.records_readable.to_csv(trades_file, index=False)
print(f"\nTrades exported to {trades_file}")
