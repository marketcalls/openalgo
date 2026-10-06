"""
MACD Chart — Moving Average Convergence Divergence with histogram
"""
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dotenv import find_dotenv, load_dotenv
from openalgo import api, ta

script_dir = Path(__file__).resolve().parent
load_dotenv(find_dotenv(), override=False)

SYMBOL = "SBIN"
EXCHANGE = "NSE"
INTERVAL = "D"
FAST = 12
SLOW = 26
SIGNAL = 9

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
macd_line, signal_line, histogram = ta.macd(close, FAST, SLOW, SIGNAL)

x_labels = df.index.strftime("%Y-%m-%d")

fig = make_subplots(
    rows=2, cols=1, shared_xaxes=True,
    row_heights=[0.6, 0.4], vertical_spacing=0.03,
    subplot_titles=[f"{SYMBOL} Price", f"MACD({FAST},{SLOW},{SIGNAL})"],
)

# Price
fig.add_trace(go.Candlestick(
    x=x_labels, open=df["open"], high=df["high"], low=df["low"], close=close,
    name="Price", showlegend=False,
), row=1, col=1)

# MACD line
fig.add_trace(go.Scatter(
    x=x_labels, y=macd_line, mode="lines",
    name="MACD", line=dict(color="cyan", width=1.5),
), row=2, col=1)

# Signal line
fig.add_trace(go.Scatter(
    x=x_labels, y=signal_line, mode="lines",
    name="Signal", line=dict(color="orange", width=1.5),
), row=2, col=1)

# Histogram
colors = ["rgba(0,200,0,0.6)" if v >= 0 else "rgba(200,0,0,0.6)" for v in histogram]
fig.add_trace(go.Bar(
    x=x_labels, y=histogram, name="Histogram",
    marker_color=colors,
), row=2, col=1)

# Zero line
fig.add_hline(y=0, line_dash="solid", line_color="gray", opacity=0.3, row=2, col=1)

fig.update_layout(
    template="plotly_dark",
    title=f"{SYMBOL} — MACD({FAST},{SLOW},{SIGNAL})",
    xaxis_rangeslider_visible=False,
    height=700,
)
fig.update_xaxes(type="category", row=1, col=1)
fig.update_xaxes(type="category", row=2, col=1)
fig.update_yaxes(side="right")

fig.write_html(script_dir / f"{SYMBOL}_macd_chart.html")
fig.show()

# Explanation
current_macd = macd_line.iloc[-1]
current_signal = signal_line.iloc[-1]
current_hist = histogram.iloc[-1]
crossover = "bullish" if current_macd > current_signal else "bearish"
momentum = "increasing" if current_hist > histogram.iloc[-2] else "decreasing"

print(f"\n{SYMBOL} — MACD Analysis")
print(f"MACD Line: {current_macd:.4f}")
print(f"Signal Line: {current_signal:.4f}")
print(f"Histogram: {current_hist:.4f}")
print(f"Crossover: {crossover} (MACD {'>' if crossover == 'bullish' else '<'} Signal)")
print(f"Momentum: {momentum}")
