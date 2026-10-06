"""
MACD Signal-Candle Breakout Backtest - VectorBT + OpenAlgo
Strategy: MACD zero-line defines bull/bear regimes. Entry on breakout of signal candle.
Indicators: OpenAlgo ta MACD (default indicator library) + openalgo.ta signal helpers.
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
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
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

print(f"Fetching {SYMBOL} ({EXCHANGE}) {INTERVAL} data from {start_date} to {end_date}")

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
print(f"Data loaded: {len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}")

# --- Strategy: MACD Signal-Candle Breakout (OpenAlgo ta) ---
macd_series, macd_signal_line, macd_hist = ta.macd(
    close, fast_period=MACD_FAST, slow_period=MACD_SLOW, signal_period=MACD_SIGNAL
)
zero = pd.Series(0.0, index=close.index)

# MACD zero-line flips define regimes
bull_flip = ta.crossover(macd_series, zero)
bear_flip = ta.crossunder(macd_series, zero)

bull_regime = ta.flip(bull_flip, bear_flip)
bear_regime = ta.flip(bear_flip, bull_flip)

# Signal candle levels (capture and carry forward)
sig_high = high.where(bull_flip).ffill()
sig_low = low.where(bear_flip).ffill()

# Entries: price breaks signal candle level during matching regime
long_entry_raw = (ta.crossover(high, sig_high) & bull_regime).fillna(False)

# Only first entry per regime; exit on bear regime flip
entries = ta.exrem(long_entry_raw, bear_flip.fillna(False))
exits = ta.exrem(bear_flip.fillna(False), long_entry_raw)

print(f"Signals - Entries: {entries.sum()}, Exits: {exits.sum()}")

# --- Backtest ---
pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    init_cash=INIT_CASH,
    size=ALLOCATION,
    size_type="percent",
    fees=FEES,
    fixed_fees=FIXED_FEES,
    direction="longonly",
    min_size=1,
    size_granularity=1,
    freq="1D",
)

# --- Benchmark: NIFTY 50 ---
print(f"\nFetching benchmark: {BENCHMARK_SYMBOL} ({BENCHMARK_EXCHANGE})")
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
print(f"  MACD Signal-Candle Breakout - {SYMBOL} ({EXCHANGE})")
print("=" * 60)
print(pf.stats())

# --- Strategy vs Benchmark Metrics ---
print("\n--- Strategy vs Benchmark ---")
comparison = pd.DataFrame({
    "Strategy": [
        f"{pf.total_return() * 100:.2f}%",
        f"{pf.sharpe_ratio():.2f}",
        f"{pf.sortino_ratio():.2f}",
        f"{pf.max_drawdown() * 100:.2f}%",
        f"{pf.trades.win_rate() * 100:.1f}%",
        f"{pf.trades.count()}",
        f"{pf.trades.profit_factor():.2f}",
    ],
    f"Benchmark ({BENCHMARK_SYMBOL})": [
        f"{pf_bench.total_return() * 100:.2f}%",
        f"{pf_bench.sharpe_ratio():.2f}",
        f"{pf_bench.sortino_ratio():.2f}",
        f"{pf_bench.max_drawdown() * 100:.2f}%",
        "-", "-", "-",
    ],
}, index=["Total Return", "Sharpe Ratio", "Sortino Ratio", "Max Drawdown",
          "Win Rate", "Total Trades", "Profit Factor"])
print(comparison.to_string())

# --- Explain Backtest Report ---
print("\n--- Backtest Report Explanation ---")
print(f"* Total Return: Your strategy made {pf.total_return() * 100:.2f}% "
      f"while NIFTY 50 made {pf_bench.total_return() * 100:.2f}%")
alpha = pf.total_return() - pf_bench.total_return()
if alpha > 0:
    print(f"  -> Your strategy BEAT the market by {alpha * 100:.2f}% (positive alpha)")
else:
    print(f"  -> Your strategy UNDERPERFORMED the market by {abs(alpha) * 100:.2f}%")
print(f"* Sharpe Ratio: {pf.sharpe_ratio():.2f}")
print(f"  -> This measures return per unit of risk. Think of it as 'bang for your buck'.")
print(f"     Below 1 = not enough return for the risk taken")
print(f"     1-2 = decent, 2+ = very good")
print(f"* Max Drawdown: {pf.max_drawdown() * 100:.2f}%")
print(f"  -> The biggest drop from peak. If you invested 10L, you would have temporarily")
print(f"     lost up to Rs {abs(pf.max_drawdown()) * INIT_CASH:,.0f} before recovering.")
print(f"* Win Rate: {pf.trades.win_rate() * 100:.1f}% of trades were profitable")
print(f"* Profit Factor: {pf.trades.profit_factor():.2f}")
print(f"  -> For every Rs 1 lost, you made Rs {pf.trades.profit_factor():.2f} in profits.")

# --- Plot ---
fig = pf.plot(
    subplots=["value", "underwater", "cum_returns"],
    template="plotly_dark",
    title=f"MACD Signal-Candle Breakout - {SYMBOL} ({EXCHANGE} {INTERVAL})",
)
fig.show()

# --- Export ---
trades_file = script_dir / f"{SYMBOL}_macd_trades.csv"
pf.positions.records_readable.to_csv(trades_file, index=False)
print(f"\nTrades exported to {trades_file}")
