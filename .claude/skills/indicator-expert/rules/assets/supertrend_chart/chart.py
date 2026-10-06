"""
Supertrend Chart — Direction-colored trend overlay on candlestick
"""
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dotenv import find_dotenv, load_dotenv
from openalgo import api, ta

script_dir = Path(__file__).resolve().parent
load_dotenv(find_dotenv(), override=False)

SYMBOL = "SBIN"
EXCHANGE = "NSE"
INTERVAL = "D"
ST_PERIOD = 10
ST_MULTIPLIER = 3.0

client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host=os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"),
)

end_date = datetime.now().date()
start_date = end_date - timedelta(days=365)

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

st, direction = ta.supertrend(high, low, close, ST_PERIOD, ST_MULTIPLIER)

# Split into uptrend and downtrend segments
st_series = pd.Series(st, index=df.index)
direction_series = pd.Series(direction, index=df.index)
st_up = st_series.where(direction_series == -1)
st_down = st_series.where(direction_series == 1)

# Direction change signals
buy_signals = (direction_series == -1) & (direction_series.shift(1) == 1)
sell_signals = (direction_series == 1) & (direction_series.shift(1) == -1)

x_labels = df.index.strftime("%Y-%m-%d")

fig = go.Figure()

fig.add_trace(go.Candlestick(
    x=x_labels, open=df["open"], high=high, low=low, close=close,
    name="Price",
))

fig.add_trace(go.Scatter(
    x=x_labels, y=st_up, mode="lines",
    name="Supertrend (Up)", line=dict(color="lime", width=2),
))
fig.add_trace(go.Scatter(
    x=x_labels, y=st_down, mode="lines",
    name="Supertrend (Down)", line=dict(color="red", width=2),
))

# Buy signals
buy_idx = [x_labels[i] for i in range(len(buy_signals)) if buy_signals.iloc[i]]
buy_prices = [low.iloc[i] * 0.99 for i in range(len(buy_signals)) if buy_signals.iloc[i]]
fig.add_trace(go.Scatter(
    x=buy_idx, y=buy_prices, mode="markers", name="Buy Signal",
    marker=dict(symbol="triangle-up", size=14, color="lime"),
))

# Sell signals
sell_idx = [x_labels[i] for i in range(len(sell_signals)) if sell_signals.iloc[i]]
sell_prices = [high.iloc[i] * 1.01 for i in range(len(sell_signals)) if sell_signals.iloc[i]]
fig.add_trace(go.Scatter(
    x=sell_idx, y=sell_prices, mode="markers", name="Sell Signal",
    marker=dict(symbol="triangle-down", size=14, color="red"),
))

fig.update_layout(
    template="plotly_dark",
    title=f"{SYMBOL} — Supertrend({ST_PERIOD}, {ST_MULTIPLIER})",
    xaxis_rangeslider_visible=False,
    xaxis_type="category",
    height=600,
)
fig.update_yaxes(side="right")

fig.write_html(script_dir / f"{SYMBOL}_supertrend_chart.html")
fig.show()

# Explanation
current_dir = direction_series.iloc[-1]
current_st = st_series.iloc[-1]
trend = "UPTREND (bullish)" if current_dir == -1 else "DOWNTREND (bearish)"

print(f"\n{SYMBOL} — Supertrend({ST_PERIOD}, {ST_MULTIPLIER}) Analysis")
print(f"Current Price: {close.iloc[-1]:.2f}")
print(f"Supertrend Level: {current_st:.2f}")
print(f"Direction: {trend}")
if current_dir == -1:
    print(f"Support at: {current_st:.2f} (stop-loss reference)")
else:
    print(f"Resistance at: {current_st:.2f} (stop-loss reference)")
