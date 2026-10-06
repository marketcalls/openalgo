"""
Buy & Hold Portfolio Backtest - VectorBT + OpenAlgo
Strategy: Static allocation across ETFs (e.g., 60% NIFTYBEES + 40% GOLDBEES).
          One-time purchase on Day 1, hold forever.
Fees: Indian delivery equity model (0.111% + Rs 20/order).
Benchmark: NIFTY 50 Index via OpenAlgo (NSE_INDEX) + HDFC FD rate.
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
WEIGHTS = {"NIFTYBEES": 0.60, "GOLDBEES": 0.40}
EXCHANGE = "NSE"
INTERVAL = "D"
INIT_CASH = 10_00_000
FEES = 0.00111              # Indian delivery equity
FIXED_FEES = 20             # Rs 20 per order
FD_CAGR = 0.0645            # HDFC Bank FD rate 6.45%
BENCHMARK_SYMBOL = "NIFTY"
BENCHMARK_EXCHANGE = "NSE_INDEX"


def calc_cagr(start_val, end_val, years):
    """Calculate CAGR given start value, end value, and number of years."""
    if start_val <= 0 or end_val <= 0 or years <= 0:
        return 0.0
    return (end_val / start_val) ** (1 / years) - 1


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

# --- Build Price Panel ---
close_prices = pd.DataFrame({sym: dfs[sym]["close"] for sym in SYMBOLS}).dropna()
print(f"\nAligned data: {len(close_prices)} bars")

# --- Buy & Hold: One-time allocation on Day 1 ---
size_df = pd.DataFrame(np.nan, index=close_prices.index, columns=SYMBOLS)
size_df.iloc[0] = [WEIGHTS[sym] for sym in SYMBOLS]

pf = vbt.Portfolio.from_orders(
    close=close_prices, size=size_df, size_type="targetpercent",
    fees=FEES, fixed_fees=FIXED_FEES, init_cash=INIT_CASH,
    cash_sharing=True, call_seq="auto", group_by=True,
    freq="1D", min_size=1, size_granularity=1,
)

# --- Benchmark ---
print("\nFetching NIFTY 50 index data for benchmark...")
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
nifty_close = df_nifty["close"].reindex(close_prices.index).ffill().bfill()

pf_niftybees = vbt.Portfolio.from_holding(
    close_prices["NIFTYBEES"], init_cash=INIT_CASH, fees=FEES, freq="1D")
pf_goldbees = vbt.Portfolio.from_holding(
    close_prices["GOLDBEES"], init_cash=INIT_CASH, fees=FEES, freq="1D")

# --- Results ---
print("\n" + "=" * 60)
print(f"  Buy & Hold: {WEIGHTS['NIFTYBEES']*100:.0f}% NIFTYBEES + {WEIGHTS['GOLDBEES']*100:.0f}% GOLDBEES")
print("=" * 60)
print(pf.stats())

# --- CAGR Calculations ---
equity = pf.value()
n_days = (close_prices.index[-1] - close_prices.index[0]).days
n_years = n_days / 365.25

cagr_portfolio = calc_cagr(INIT_CASH, equity.iloc[-1], n_years)
cagr_nifty50 = calc_cagr(nifty_close.iloc[0], nifty_close.iloc[-1], n_years)
fd_final = INIT_CASH * (1 + FD_CAGR) ** n_years

# --- Strategy vs Benchmark ---
print("\n--- Strategy vs Benchmark ---")
comparison = pd.DataFrame({
    f"Portfolio ({WEIGHTS['NIFTYBEES']*100:.0f}/{WEIGHTS['GOLDBEES']*100:.0f})": [
        f"{pf.total_return() * 100:.2f}%",
        f"{cagr_portfolio * 100:.2f}%",
        f"{pf.sharpe_ratio():.2f}",
        f"{pf.sortino_ratio():.2f}",
        f"{pf.max_drawdown() * 100:.2f}%",
        f"Rs {equity.iloc[-1]:,.0f}",
    ],
    f"Benchmark ({BENCHMARK_SYMBOL})": [
        f"{(nifty_close.iloc[-1] / nifty_close.iloc[0] - 1) * 100:.2f}%",
        f"{cagr_nifty50 * 100:.2f}%",
        "-", "-", "-",
        "-",
    ],
    "NIFTYBEES B&H": [
        f"{pf_niftybees.total_return() * 100:.2f}%",
        "-",
        f"{pf_niftybees.sharpe_ratio():.2f}",
        f"{pf_niftybees.sortino_ratio():.2f}",
        f"{pf_niftybees.max_drawdown() * 100:.2f}%",
        f"Rs {pf_niftybees.value().iloc[-1]:,.0f}",
    ],
    "GOLDBEES B&H": [
        f"{pf_goldbees.total_return() * 100:.2f}%",
        "-",
        f"{pf_goldbees.sharpe_ratio():.2f}",
        f"{pf_goldbees.sortino_ratio():.2f}",
        f"{pf_goldbees.max_drawdown() * 100:.2f}%",
        f"Rs {pf_goldbees.value().iloc[-1]:,.0f}",
    ],
    f"HDFC FD ({FD_CAGR*100:.2f}%)": [
        f"{(fd_final / INIT_CASH - 1) * 100:.2f}%",
        f"{FD_CAGR * 100:.2f}%",
        "-", "-", "0.00%",
        f"Rs {fd_final:,.0f}",
    ],
}, index=["Total Return", "CAGR", "Sharpe Ratio", "Sortino Ratio",
          "Max Drawdown", "Final Value"])
print(comparison.to_string())

# --- Explain ---
print("\n--- Backtest Report Explanation ---")
print(f"* Total Return: Your portfolio made {pf.total_return() * 100:.2f}%")
print(f"  while NIFTY 50 made {(nifty_close.iloc[-1] / nifty_close.iloc[0] - 1) * 100:.2f}%")
alpha = pf.total_return() - (nifty_close.iloc[-1] / nifty_close.iloc[0] - 1)
if alpha > 0:
    print(f"  -> BEAT the market by {alpha * 100:.2f}%")
else:
    print(f"  -> UNDERPERFORMED by {abs(alpha) * 100:.2f}%")
print(f"* CAGR: {cagr_portfolio * 100:.2f}% annualized vs FD at {FD_CAGR * 100:.2f}%")
if cagr_portfolio > FD_CAGR:
    print(f"  -> BEAT the FD by {(cagr_portfolio - FD_CAGR) * 100:.2f}% per year")
else:
    print(f"  -> UNDERPERFORMED FD by {(FD_CAGR - cagr_portfolio) * 100:.2f}% per year")
print(f"* Max Drawdown: {pf.max_drawdown() * 100:.2f}% - the biggest drop from peak")
print(f"  -> On Rs {INIT_CASH:,} capital, the worst temporary loss = Rs {abs(pf.max_drawdown()) * INIT_CASH:,.0f}")
print(f"* This is a PASSIVE strategy - buy once and hold, no rebalancing needed")
print(f"* Gold (GOLDBEES) provides diversification when equity markets fall")

# --- Plot ---
cum_strat = equity / equity.iloc[0] - 1
cum_nifty = nifty_close / nifty_close.iloc[0] - 1
cum_niftybees = close_prices["NIFTYBEES"] / close_prices["NIFTYBEES"].iloc[0] - 1
cum_goldbees = close_prices["GOLDBEES"] / close_prices["GOLDBEES"].iloc[0] - 1
drawdown = equity / equity.cummax() - 1

fd_daily_rate = (1 + FD_CAGR) ** (1 / 365.25) - 1
fd_equity = pd.Series(
    INIT_CASH * (1 + fd_daily_rate) ** np.arange(len(close_prices)),
    index=close_prices.index,
)
cum_fd = fd_equity / fd_equity.iloc[0] - 1

fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                    row_heights=[0.65, 0.35], vertical_spacing=0.07)

fig.add_trace(go.Scatter(x=cum_strat.index, y=cum_strat * 100,
    name="Portfolio", line=dict(color="#00d4aa", width=2.5)), row=1, col=1)
fig.add_trace(go.Scatter(x=cum_nifty.index, y=cum_nifty * 100,
    name="NIFTY 50", line=dict(color="#ff6688", width=1.5, dash="dash")), row=1, col=1)
fig.add_trace(go.Scatter(x=cum_niftybees.index, y=cum_niftybees * 100,
    name="NIFTYBEES", line=dict(color="#4488ff", width=1, dash="dot")), row=1, col=1)
fig.add_trace(go.Scatter(x=cum_goldbees.index, y=cum_goldbees * 100,
    name="GOLDBEES", line=dict(color="#ffaa00", width=1, dash="dot")), row=1, col=1)
fig.add_trace(go.Scatter(x=cum_fd.index, y=cum_fd * 100,
    name=f"HDFC FD {FD_CAGR*100:.2f}%", line=dict(color="#888888", width=1.5, dash="dashdot")), row=1, col=1)
fig.add_trace(go.Scatter(x=drawdown.index, y=drawdown * 100,
    name="Drawdown", fill="tozeroy", line=dict(color="#ff4444", width=1)), row=2, col=1)

fig.update_yaxes(ticksuffix="%", side="right", row=1, col=1)
fig.update_yaxes(title_text="Drawdown %", ticksuffix="%", side="right", row=2, col=1)
fig.update_layout(template="plotly_dark",
    title=f"Buy & Hold: {WEIGHTS['NIFTYBEES']*100:.0f}% NIFTYBEES + {WEIGHTS['GOLDBEES']*100:.0f}% GOLDBEES vs Benchmarks",
    height=700)
fig.show()

# --- Export ---
orders_file = script_dir / "buy_hold_orders.csv"
pf.orders.records_readable.to_csv(orders_file, index=False)
print(f"\nOrders exported to {orders_file}")
