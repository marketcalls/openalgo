"""
Walk-Forward Analysis Template - VectorBT + OpenAlgo
Optimizes EMA parameters on in-sample, validates on out-of-sample, rolls forward.
Indicators: OpenAlgo ta (default indicator library; swap to TA-Lib only if requested).
Fees: Indian delivery equity model (0.111% + Rs 20/order).
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import vectorbt as vbt
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from tqdm import tqdm
from dotenv import find_dotenv, load_dotenv
from openalgo import api, ta

# --- Config ---
script_dir = Path(__file__).resolve().parent
load_dotenv(find_dotenv(), override=False)

SYMBOL = "SBIN"
EXCHANGE = "NSE"
INTERVAL = "D"
INIT_CASH = 1_000_000
FEES = 0.00111              # Indian delivery equity
FIXED_FEES = 20
ALLOCATION = 0.75

# Walk-forward parameters
TRAIN_DAYS = 252 * 2        # 2 years training (in-sample)
TEST_DAYS = 63              # 3 months testing (out-of-sample)
STEP_DAYS = 63              # Roll forward by 1 quarter

# EMA optimization grid
FAST_RANGE = range(5, 25)   # Fast EMA: 5 to 24
SLOW_RANGE = range(20, 50)  # Slow EMA: 20 to 49

# --- Fetch Data ---
client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host=os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"),
)

end_date = datetime.now().date()
start_date = end_date - timedelta(days=365 * 5)  # 5 years for walk-forward

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
print(f"Data loaded: {len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}")


def run_ema_backtest(close_slice, fast_period, slow_period):
    """Run a single EMA crossover backtest on a data slice."""
    ema_f = ta.ema(close_slice, fast_period)
    ema_s = ta.ema(close_slice, slow_period)

    buy_raw = (ema_f > ema_s) & (ema_f.shift(1) <= ema_s.shift(1))
    sell_raw = (ema_f < ema_s) & (ema_f.shift(1) >= ema_s.shift(1))

    entries = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
    exits = ta.exrem(sell_raw.fillna(False), buy_raw.fillna(False))

    pf = vbt.Portfolio.from_signals(
        close_slice, entries, exits,
        init_cash=INIT_CASH, size=ALLOCATION, size_type="percent",
        fees=FEES, fixed_fees=FIXED_FEES, direction="longonly",
        min_size=1, size_granularity=1, freq="1D",
    )
    return pf


# --- Walk-Forward Analysis ---
print(f"\nRunning walk-forward analysis...")
print(f"  Training window: {TRAIN_DAYS} bars ({TRAIN_DAYS // 252:.1f} years)")
print(f"  Testing window: {TEST_DAYS} bars (~{TEST_DAYS // 21:.0f} months)")
print(f"  Step size: {STEP_DAYS} bars (~{STEP_DAYS // 21:.0f} months)")

oos_results = []

# Count total windows for progress bar
total_windows = 0
s = 0
while s + TRAIN_DAYS + TEST_DAYS <= len(close):
    total_windows += 1
    s += STEP_DAYS

start = 0
for window_num in tqdm(range(total_windows), desc="Walk-Forward Windows"):
    train_slice = close.iloc[start:start + TRAIN_DAYS]
    test_slice = close.iloc[start + TRAIN_DAYS:start + TRAIN_DAYS + TEST_DAYS]

    # --- Optimize on Training Data ---
    best_sharpe = -np.inf
    best_fast, best_slow = 10, 20
    best_is_return = 0

    for fast in FAST_RANGE:
        for slow in SLOW_RANGE:
            if fast >= slow:
                continue
            pf_train = run_ema_backtest(train_slice, fast, slow)
            sharpe = pf_train.sharpe_ratio()
            if not np.isnan(sharpe) and sharpe > best_sharpe:
                best_sharpe = sharpe
                best_fast = fast
                best_slow = slow
                best_is_return = pf_train.total_return()

    # Skip window if no valid parameters found (all NaN sharpe)
    if best_sharpe == -np.inf:
        print(f"  Window {window_num + 1}: No valid parameters found, skipping")
        start += STEP_DAYS
        continue

    # --- Validate on Test Data ---
    pf_test = run_ema_backtest(test_slice, best_fast, best_slow)

    oos_results.append({
        'window': window_num + 1,
        'train_start': train_slice.index[0].strftime('%Y-%m-%d'),
        'train_end': train_slice.index[-1].strftime('%Y-%m-%d'),
        'test_start': test_slice.index[0].strftime('%Y-%m-%d'),
        'test_end': test_slice.index[-1].strftime('%Y-%m-%d'),
        'best_fast': best_fast,
        'best_slow': best_slow,
        'is_return': best_is_return,
        'is_sharpe': best_sharpe,
        'oos_return': pf_test.total_return(),
        'oos_sharpe': pf_test.sharpe_ratio(),
        'oos_max_dd': pf_test.max_drawdown(),
        'oos_trades': pf_test.trades.count(),
    })

    start += STEP_DAYS

results_df = pd.DataFrame(oos_results)

# --- Walk-Forward Report ---
print("\n" + "=" * 80)
print("  WALK-FORWARD ANALYSIS REPORT")
print("=" * 80)
print(results_df[['window', 'test_start', 'test_end', 'best_fast', 'best_slow',
                   'is_return', 'oos_return', 'oos_sharpe']].to_string(index=False,
    float_format=lambda x: f"{x:.2%}" if abs(x) < 10 else f"{x:.2f}"))

# --- Summary Statistics ---
print("\n--- Walk-Forward Summary ---")
avg_oos_return = results_df['oos_return'].mean()
oos_win_rate = (results_df['oos_return'] > 0).mean()
avg_is_return = results_df['is_return'].mean()
wfe = avg_oos_return / avg_is_return if avg_is_return != 0 else 0

print(f"Total windows: {len(results_df)}")
print(f"Avg In-Sample Return: {avg_is_return:.2%}")
print(f"Avg Out-of-Sample Return: {avg_oos_return:.2%}")
print(f"OOS Win Rate: {oos_win_rate:.0%} of windows profitable")
print(f"Walk-Forward Efficiency (WFE): {wfe:.2%}")
print(f"  -> WFE > 50% is acceptable, > 70% is good")

# --- Explain for Traders ---
print("\n--- What This Means ---")
if oos_win_rate >= 0.7 and wfe > 0.5:
    print("ROBUST: Strategy consistently profitable on unseen data.")
    print("  The parameters found during training continue to work on new data.")
elif oos_win_rate >= 0.5:
    print("MODERATE: Strategy shows some edge on unseen data but inconsistent.")
    print("  Consider additional filters or a different strategy.")
else:
    print("WEAK: Strategy fails on unseen data. Likely overfit to training period.")
    print("  Do NOT trade this strategy live without significant changes.")

print(f"\nParameter stability: Fast EMA ranged {results_df['best_fast'].min()}-{results_df['best_fast'].max()}, "
      f"Slow EMA ranged {results_df['best_slow'].min()}-{results_df['best_slow'].max()}")
param_stable = (results_df['best_fast'].std() < 5) and (results_df['best_slow'].std() < 5)
if param_stable:
    print("  -> Parameters are STABLE across windows (good sign)")
else:
    print("  -> Parameters VARY widely across windows (strategy may be fragile)")

# --- Plot ---
fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                    row_heights=[0.6, 0.4], vertical_spacing=0.1,
                    subplot_titles=["OOS Return per Window", "Cumulative OOS Return"])

colors = ['#00d4aa' if r > 0 else '#ff4444' for r in results_df['oos_return']]
fig.add_trace(go.Bar(
    x=results_df['window'], y=results_df['oos_return'] * 100,
    marker_color=colors, name="OOS Return %",
), row=1, col=1)

cum_oos = (1 + results_df['oos_return']).cumprod() - 1
fig.add_trace(go.Scatter(
    x=results_df['window'], y=cum_oos * 100,
    name="Cumulative OOS Return %", line=dict(color="#00d4aa", width=2),
), row=2, col=1)

fig.update_layout(template="plotly_dark", title="Walk-Forward Analysis Results",
                  height=600, showlegend=True)
fig.update_yaxes(title_text="Return %", ticksuffix="%", side="right", row=1, col=1)
fig.update_yaxes(title_text="Cumulative %", ticksuffix="%", side="right", row=2, col=1)
fig.update_xaxes(title_text="Window #", row=2, col=1)
fig.show()

# --- Export ---
results_file = script_dir / f"{SYMBOL}_walk_forward_results.csv"
results_df.to_csv(results_file, index=False)
print(f"\nResults exported to {results_file}")
