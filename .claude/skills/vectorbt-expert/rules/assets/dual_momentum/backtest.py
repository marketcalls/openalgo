"""
Dual Momentum (ETF Rotation) Backtest - VectorBT + OpenAlgo
Strategy: Quarterly momentum rotation between NIFTYBEES and GOLDBEES.
          Buys previous quarter's outperformer for the next quarter.
Fees: Indian delivery equity model (0.111% + Rs 20/order).
Benchmark: NIFTY 50 Index via OpenAlgo (NSE_INDEX).
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import vectorbt as vbt
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dotenv import find_dotenv, load_dotenv
from openalgo import api

# --- Config ---
script_dir = Path(__file__).resolve().parent
load_dotenv(find_dotenv(), override=False)

SYMBOLS = ["NIFTYBEES", "GOLDBEES"]
EXCHANGE = "NSE"
INTERVAL = "D"
INIT_CASH = 10_00_000
FEES = 0.00111              # Indian delivery equity
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
start_date = "2018-01-01"

print(f"Fetching data for {SYMBOLS} ({EXCHANGE}) from {start_date} to {end_date}")

dfs = {}
for sym in SYMBOLS:
    df = client.history(
        symbol=sym, exchange=EXCHANGE, interval=INTERVAL,
        start_date=start_date, end_date=end_date.strftime("%Y-%m-%d"),
    )
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
    else:
        df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    if df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    dfs[sym] = df
    print(f"  {sym}: {len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}")

# --- Build Panel ---
close_prices = pd.DataFrame({sym: dfs[sym]["close"] for sym in SYMBOLS}).dropna()
open_prices = pd.DataFrame({sym: dfs[sym]["open"] for sym in SYMBOLS})
open_prices = open_prices.reindex(close_prices.index).ffill().bfill()

# --- Quarterly Returns & Winner Selection ---
quarterly_close = close_prices.resample("QE").last().dropna(how="all")
quarterly_returns = quarterly_close.pct_change()

# Winner shifted by 1 quarter (use PREVIOUS quarter's winner)
winner = quarterly_returns.idxmax(axis=1)
winner_shifted = winner.shift(1).dropna()

# --- Build Daily Allocation Weights ---
alloc_daily = pd.Series(index=close_prices.index, dtype="object")
for dt, sym in winner_shifted.items():
    next_idx_pos = close_prices.index.searchsorted(dt, side="right")
    if next_idx_pos < len(close_prices.index):
        alloc_daily.loc[close_prices.index[next_idx_pos]] = sym

alloc_daily = alloc_daily.ffill()
alloc_daily = alloc_daily.loc[alloc_daily.first_valid_index():]

weights = pd.DataFrame(index=alloc_daily.index, columns=SYMBOLS, dtype=float)
weights["NIFTYBEES"] = np.where(alloc_daily == "NIFTYBEES", ALLOCATION, 0.0)
weights["GOLDBEES"] = np.where(alloc_daily == "GOLDBEES", ALLOCATION, 0.0)

switch_mask = alloc_daily.ne(alloc_daily.shift(1))
switch_mask.iloc[0] = True
target_on_switch = weights.where(switch_mask, np.nan)

# --- Backtest ---
price_df = open_prices.loc[alloc_daily.index]

pf = vbt.Portfolio.from_orders(
    close=price_df, size=target_on_switch, size_type="targetpercent",
    fees=FEES, fixed_fees=FIXED_FEES, init_cash=INIT_CASH,
    cash_sharing=True, call_seq="auto", group_by=True,
    freq="1D", min_size=1, size_granularity=1,
)

# --- Benchmark ---
df_nifty = client.history(
    symbol=BENCHMARK_SYMBOL, exchange=BENCHMARK_EXCHANGE, interval=INTERVAL,
    start_date=start_date, end_date=end_date.strftime("%Y-%m-%d"),
)
if "timestamp" in df_nifty.columns:
    df_nifty["timestamp"] = pd.to_datetime(df_nifty["timestamp"])
    df_nifty = df_nifty.set_index("timestamp")
else:
    df_nifty.index = pd.to_datetime(df_nifty.index)
df_nifty = df_nifty.sort_index()
if df_nifty.index.tz is not None:
    df_nifty.index = df_nifty.index.tz_convert(None)
nifty_close = df_nifty["close"].reindex(alloc_daily.index).ffill().bfill()
pf_bench = vbt.Portfolio.from_holding(nifty_close, init_cash=INIT_CASH, fees=FEES, freq="1D")

pf_bench_bees = vbt.Portfolio.from_holding(
    close_prices.loc[alloc_daily.index, "NIFTYBEES"], init_cash=INIT_CASH, fees=FEES, freq="1D")
pf_bench_gold = vbt.Portfolio.from_holding(
    close_prices.loc[alloc_daily.index, "GOLDBEES"], init_cash=INIT_CASH, fees=FEES, freq="1D")

# --- Results ---
print("\n" + "=" * 60)
print("  Dual Momentum - NIFTYBEES vs GOLDBEES (Quarterly Rebalance)")
print("=" * 60)
print(pf.stats())

print("\n--- Strategy vs Benchmark ---")
comparison = pd.DataFrame({
    "Dual Momentum": [
        f"{pf.total_return() * 100:.2f}%", f"{pf.sharpe_ratio():.2f}",
        f"{pf.sortino_ratio():.2f}", f"{pf.max_drawdown() * 100:.2f}%",
    ],
    f"Benchmark ({BENCHMARK_SYMBOL})": [
        f"{pf_bench.total_return() * 100:.2f}%", f"{pf_bench.sharpe_ratio():.2f}",
        f"{pf_bench.sortino_ratio():.2f}", f"{pf_bench.max_drawdown() * 100:.2f}%",
    ],
    "NIFTYBEES B&H": [
        f"{pf_bench_bees.total_return() * 100:.2f}%", f"{pf_bench_bees.sharpe_ratio():.2f}",
        f"{pf_bench_bees.sortino_ratio():.2f}", f"{pf_bench_bees.max_drawdown() * 100:.2f}%",
    ],
    "GOLDBEES B&H": [
        f"{pf_bench_gold.total_return() * 100:.2f}%", f"{pf_bench_gold.sharpe_ratio():.2f}",
        f"{pf_bench_gold.sortino_ratio():.2f}", f"{pf_bench_gold.max_drawdown() * 100:.2f}%",
    ],
}, index=["Total Return", "Sharpe Ratio", "Sortino Ratio", "Max Drawdown"])
print(comparison.to_string())

# --- Explain ---
print("\n--- Backtest Report Explanation ---")
print(f"* Total Return: Your strategy made {pf.total_return() * 100:.2f}%")
print(f"  while NIFTY 50 made {pf_bench.total_return() * 100:.2f}%")
alpha = pf.total_return() - pf_bench.total_return()
if alpha > 0:
    print(f"  -> BEAT the market by {alpha * 100:.2f}%")
else:
    print(f"  -> UNDERPERFORMED by {abs(alpha) * 100:.2f}%")
print(f"* The strategy rotates quarterly into whichever ETF performed better last quarter")
print(f"* This captures momentum - assets that did well recently tend to continue")
print(f"* Max Drawdown: {pf.max_drawdown() * 100:.2f}% - the biggest drop from peak")
print(f"  -> On Rs {INIT_CASH:,} capital, the worst temporary loss = Rs {abs(pf.max_drawdown()) * INIT_CASH:,.0f}")
print(f"* Rebalances: {switch_mask.sum()} times over the period")

# --- Plot ---
equity = pf.value()
cum_strat = equity / equity.iloc[0] - 1
cum_nifty = nifty_close / nifty_close.iloc[0] - 1
drawdown = equity / equity.cummax() - 1

fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                    row_heights=[0.65, 0.35], vertical_spacing=0.07)
fig.add_trace(go.Scatter(x=cum_strat.index, y=cum_strat * 100,
    name="Dual Momentum", line=dict(color="#00d4aa", width=2.5)), row=1, col=1)
fig.add_trace(go.Scatter(x=cum_nifty.index, y=cum_nifty * 100,
    name="NIFTY 50", line=dict(color="#ff6688", width=1.5, dash="dash")), row=1, col=1)
fig.add_trace(go.Scatter(x=drawdown.index, y=drawdown * 100,
    name="Drawdown", fill="tozeroy", line=dict(color="#ff4444", width=1)), row=2, col=1)

fig.update_yaxes(ticksuffix="%", side="right", row=1, col=1)
fig.update_yaxes(title_text="Drawdown %", ticksuffix="%", side="right", row=2, col=1)
fig.update_layout(template="plotly_dark",
    title="Dual Momentum vs NIFTY 50", height=700)
fig.show()

# --- Export ---
rebalance_log = pd.DataFrame({
    "date": alloc_daily.index[switch_mask],
    "buy_etf": alloc_daily[switch_mask].values,
})
rebalance_log.to_csv(script_dir / "dual_momentum_rebalance_log.csv", index=False)
pf.orders.records_readable.to_csv(script_dir / "dual_momentum_orders.csv", index=False)
print(f"\nExported rebalance log and orders to {script_dir}")
