"""
Realistic Transaction Cost Analysis Template - VectorBT + OpenAlgo
Compares strategy performance across different cost models:
  1. Zero fees (unrealistic upper bound)
  2. Simplified flat fee
  3. Indian delivery equity (realistic)
  4. Indian intraday equity
  5. Indian F&O futures
Shows the real impact of transaction costs on strategy profitability.
Indicators: OpenAlgo ta (default indicator library; swap to TA-Lib only if requested).
Benchmark: NIFTY 50 Index via OpenAlgo (NSE_INDEX).
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import vectorbt as vbt
import plotly.graph_objects as go
from dotenv import find_dotenv, load_dotenv
from openalgo import api, ta

# --- Config ---
script_dir = Path(__file__).resolve().parent
load_dotenv(find_dotenv(), override=False)

SYMBOL = "SBIN"
EXCHANGE = "NSE"
INTERVAL = "D"
FAST_EMA = 10
SLOW_EMA = 20
INIT_CASH = 1_000_000
ALLOCATION = 0.75
BENCHMARK_SYMBOL = "NIFTY"
BENCHMARK_EXCHANGE = "NSE_INDEX"

# --- Indian Market Fee Models ---
FEE_MODELS = {
    "Zero Fees (Unrealistic)": {
        "fees": 0, "fixed_fees": 0, "slippage": 0,
    },
    "Simplified 0.1%": {
        "fees": 0.001, "fixed_fees": 0, "slippage": 0,
    },
    "Delivery Equity": {
        "fees": 0.00111,       # 0.111% (STT 0.1% both + statutory)
        "fixed_fees": 20,      # Rs 20 per order
        "slippage": 0.0005,    # 0.05% slippage
    },
    "Intraday Equity": {
        "fees": 0.000225,      # 0.0225% (STT 0.025% sell + statutory)
        "fixed_fees": 20,      # Rs 20 per order
        "slippage": 0.0005,
    },
    "F&O Futures": {
        "fees": 0.00018,       # 0.018% (STT 0.02% sell + statutory)
        "fixed_fees": 20,
        "slippage": 0.0002,    # Lower slippage for liquid futures
    },
}

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

# --- Generate Signals (OpenAlgo ta EMA) ---
ema_fast = ta.ema(close, FAST_EMA)
ema_slow = ta.ema(close, SLOW_EMA)

buy_raw = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
sell_raw = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))

entries = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
exits = ta.exrem(sell_raw.fillna(False), buy_raw.fillna(False))

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

# --- Run Backtest for Each Fee Model ---
results = {}
portfolios = {}

for model_name, params in FEE_MODELS.items():
    pf = vbt.Portfolio.from_signals(
        close, entries, exits,
        init_cash=INIT_CASH,
        size=ALLOCATION,
        size_type="percent",
        fees=params["fees"],
        fixed_fees=params["fixed_fees"],
        slippage=params.get("slippage", 0),
        direction="longonly",
        min_size=1,
        size_granularity=1,
        freq="1D",
    )
    portfolios[model_name] = pf
    results[model_name] = {
        "Total Return": f"{pf.total_return() * 100:.2f}%",
        "Sharpe Ratio": f"{pf.sharpe_ratio():.2f}",
        "Max Drawdown": f"{pf.max_drawdown() * 100:.2f}%",
        "Win Rate": f"{pf.trades.win_rate() * 100:.1f}%",
        "Total Trades": str(pf.trades.count()),
        "Profit Factor": f"{pf.trades.profit_factor():.2f}",
        "Total Fees Paid": f"Rs {pf.orders.records['fees'].sum():,.0f}",
    }

# Add benchmark
pf_bench = vbt.Portfolio.from_holding(bench_close, init_cash=INIT_CASH, freq="1D")
results[f"Benchmark ({BENCHMARK_SYMBOL})"] = {
    "Total Return": f"{pf_bench.total_return() * 100:.2f}%",
    "Sharpe Ratio": f"{pf_bench.sharpe_ratio():.2f}",
    "Max Drawdown": f"{pf_bench.max_drawdown() * 100:.2f}%",
    "Win Rate": "-",
    "Total Trades": "-",
    "Profit Factor": "-",
    "Total Fees Paid": "-",
}

# --- Print Results ---
print("\n" + "=" * 80)
print(f"  Transaction Cost Impact Analysis - EMA {FAST_EMA}/{SLOW_EMA} on {SYMBOL}")
print("=" * 80)
results_df = pd.DataFrame(results)
print(results_df.to_string())

# --- Explain for Traders ---
zero_return = portfolios["Zero Fees (Unrealistic)"].total_return()
delivery_return = portfolios["Delivery Equity"].total_return()
cost_drag = zero_return - delivery_return

print("\n--- What This Means for You ---")
print(f"* With zero fees, this strategy returns {zero_return * 100:.2f}%")
print(f"* With realistic delivery fees, it returns {delivery_return * 100:.2f}%")
print(f"* Transaction costs eat {cost_drag * 100:.2f}% of your returns")
print(f"  -> That is Rs {cost_drag * INIT_CASH:,.0f} lost to fees on Rs {INIT_CASH:,} capital")

if delivery_return > 0:
    print(f"\n* Strategy is STILL PROFITABLE after realistic costs")
else:
    print(f"\n* Strategy becomes UNPROFITABLE with realistic costs!")
    print(f"  -> The edge is not large enough to overcome transaction costs")
    print(f"  -> Consider: fewer trades, higher timeframe, or a different strategy")

# --- Plot: Equity Curves for All Fee Models ---
fig = go.Figure()
for model_name, pf in portfolios.items():
    equity = pf.value()
    cum_ret = equity / equity.iloc[0] - 1
    fig.add_trace(go.Scatter(
        x=cum_ret.index, y=cum_ret * 100,
        name=model_name, mode='lines',
    ))

# Add benchmark
bench_cum = bench_close / bench_close.iloc[0] - 1
fig.add_trace(go.Scatter(
    x=bench_cum.index, y=bench_cum * 100,
    name=f"Benchmark ({BENCHMARK_SYMBOL})", mode='lines',
    line=dict(dash='dash', color='gray'),
))

fig.update_layout(
    template="plotly_dark",
    title=f"Impact of Transaction Costs - EMA {FAST_EMA}/{SLOW_EMA} on {SYMBOL}",
    xaxis_title="Date",
    yaxis_title="Cumulative Return (%)",
    yaxis=dict(ticksuffix="%"),
    height=600,
    legend=dict(x=0.01, y=0.99),
)
fig.update_yaxes(side="right")
fig.show()

# --- Export ---
export_file = script_dir / f"{SYMBOL}_cost_analysis.csv"
results_df.to_csv(export_file)
print(f"\nResults exported to {export_file}")
