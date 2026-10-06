"""
Multi-Indicator Chart — Candlestick + EMA + RSI + MACD + Volume
Complete technical analysis in one view
"""
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
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
volume = df["volume"]

# Compute all indicators
ema_20 = ta.ema(close, 20)
ema_50 = ta.ema(close, 50)
rsi = ta.rsi(close, 14)
macd_line, signal_line, histogram = ta.macd(close, 12, 26, 9)

x_labels = df.index.strftime("%Y-%m-%d")

fig = make_subplots(
    rows=4, cols=1, shared_xaxes=True,
    row_heights=[0.4, 0.2, 0.2, 0.2],
    vertical_spacing=0.025,
    subplot_titles=[
        f"{SYMBOL} Price + EMA(20/50)",
        "RSI(14)",
        "MACD(12,26,9)",
        "Volume",
    ],
)

# Row 1: Candlestick + EMA
fig.add_trace(go.Candlestick(
    x=x_labels, open=df["open"], high=high, low=low, close=close,
    name="Price", showlegend=False,
), row=1, col=1)
fig.add_trace(go.Scatter(
    x=x_labels, y=ema_20, mode="lines",
    name="EMA(20)", line=dict(color="cyan", width=1.5),
), row=1, col=1)
fig.add_trace(go.Scatter(
    x=x_labels, y=ema_50, mode="lines",
    name="EMA(50)", line=dict(color="orange", width=1.5),
), row=1, col=1)

# Row 2: RSI
fig.add_trace(go.Scatter(
    x=x_labels, y=rsi, mode="lines",
    name="RSI(14)", line=dict(color="yellow", width=1.5),
), row=2, col=1)
fig.add_hline(y=70, line_dash="dash", line_color="red", opacity=0.5, row=2, col=1)
fig.add_hline(y=30, line_dash="dash", line_color="green", opacity=0.5, row=2, col=1)
fig.update_yaxes(range=[0, 100], row=2, col=1)

# Row 3: MACD
fig.add_trace(go.Scatter(
    x=x_labels, y=macd_line, mode="lines",
    name="MACD", line=dict(color="cyan", width=1),
), row=3, col=1)
fig.add_trace(go.Scatter(
    x=x_labels, y=signal_line, mode="lines",
    name="Signal", line=dict(color="orange", width=1),
), row=3, col=1)
hist_colors = ["rgba(0,200,0,0.6)" if v >= 0 else "rgba(200,0,0,0.6)" for v in histogram]
fig.add_trace(go.Bar(
    x=x_labels, y=histogram, name="Histogram",
    marker_color=hist_colors,
), row=3, col=1)
fig.add_hline(y=0, line_color="gray", opacity=0.3, row=3, col=1)

# Row 4: Volume
vol_colors = ["green" if c >= o else "red" for c, o in zip(close, df["open"])]
fig.add_trace(go.Bar(
    x=x_labels, y=volume, name="Volume",
    marker_color=vol_colors, opacity=0.5,
), row=4, col=1)

fig.update_layout(
    template="plotly_dark",
    title=f"{SYMBOL} — Complete Technical Analysis",
    xaxis_rangeslider_visible=False,
    height=1000,
    showlegend=True,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)
for r in range(1, 5):
    fig.update_xaxes(type="category", row=r, col=1)
    fig.update_yaxes(side="right", row=r, col=1)

fig.write_html(script_dir / f"{SYMBOL}_multi_indicator_chart.html")
fig.show()

# Summary
print(f"\n{SYMBOL} — Technical Analysis Summary")
print(f"{'='*50}")
print(f"Price: {close.iloc[-1]:.2f}")
print(f"EMA(20): {ema_20.iloc[-1]:.2f} {'(above)' if close.iloc[-1] > ema_20.iloc[-1] else '(below)'}")
print(f"EMA(50): {ema_50.iloc[-1]:.2f} {'(above)' if close.iloc[-1] > ema_50.iloc[-1] else '(below)'}")
print(f"RSI(14): {rsi.iloc[-1]:.2f}")
print(f"MACD: {macd_line.iloc[-1]:.4f} | Signal: {signal_line.iloc[-1]:.4f}")
print(f"Volume: {volume.iloc[-1]:,.0f}")

# Overall bias
bullish_count = 0
if close.iloc[-1] > ema_20.iloc[-1]: bullish_count += 1
if close.iloc[-1] > ema_50.iloc[-1]: bullish_count += 1
if ema_20.iloc[-1] > ema_50.iloc[-1]: bullish_count += 1
if rsi.iloc[-1] > 50: bullish_count += 1
if macd_line.iloc[-1] > signal_line.iloc[-1]: bullish_count += 1

print(f"\nOverall Bias: {bullish_count}/5 bullish conditions met")
if bullish_count >= 4:
    print("Assessment: STRONGLY BULLISH")
elif bullish_count >= 3:
    print("Assessment: MODERATELY BULLISH")
elif bullish_count == 2:
    print("Assessment: NEUTRAL / MIXED")
elif bullish_count == 1:
    print("Assessment: MODERATELY BEARISH")
else:
    print("Assessment: STRONGLY BEARISH")
