"""
Bollinger Bands Chart — with squeeze detection and %B subplot
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
BB_PERIOD = 20
BB_STD = 2.0

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
upper, middle, lower = ta.bbands(close, BB_PERIOD, BB_STD)
bb_pct = ta.bb_percent(close, BB_PERIOD, BB_STD)
bb_width = ta.bb_width(close, BB_PERIOD, BB_STD)

x_labels = df.index.strftime("%Y-%m-%d")

fig = make_subplots(
    rows=3, cols=1, shared_xaxes=True,
    row_heights=[0.55, 0.22, 0.23], vertical_spacing=0.03,
    subplot_titles=[
        f"{SYMBOL} Price + Bollinger Bands({BB_PERIOD}, {BB_STD})",
        f"Bollinger %B",
        f"Bollinger Width (Squeeze Detection)",
    ],
)

# Candlestick + Bands
fig.add_trace(go.Scatter(
    x=x_labels, y=upper, mode="lines", name="Upper BB",
    line=dict(color="rgba(100,149,237,0.6)", width=1),
), row=1, col=1)
fig.add_trace(go.Scatter(
    x=x_labels, y=lower, mode="lines", name="Lower BB",
    line=dict(color="rgba(100,149,237,0.6)", width=1),
    fill="tonexty", fillcolor="rgba(100,149,237,0.08)",
), row=1, col=1)
fig.add_trace(go.Scatter(
    x=x_labels, y=middle, mode="lines", name=f"SMA({BB_PERIOD})",
    line=dict(color="cornflowerblue", width=1, dash="dash"),
), row=1, col=1)
fig.add_trace(go.Candlestick(
    x=x_labels, open=df["open"], high=df["high"], low=df["low"], close=close,
    name="Price",
), row=1, col=1)

# %B
fig.add_trace(go.Scatter(
    x=x_labels, y=bb_pct, mode="lines",
    name="%B", line=dict(color="yellow", width=1.5),
), row=2, col=1)
fig.add_hline(y=1.0, line_dash="dash", line_color="red", opacity=0.5, row=2, col=1)
fig.add_hline(y=0.0, line_dash="dash", line_color="green", opacity=0.5, row=2, col=1)
fig.add_hline(y=0.5, line_dash="dot", line_color="gray", opacity=0.3, row=2, col=1)

# Width (squeeze)
fig.add_trace(go.Scatter(
    x=x_labels, y=bb_width, mode="lines",
    name="BB Width", line=dict(color="cyan", width=1.5),
), row=3, col=1)

fig.update_layout(
    template="plotly_dark",
    title=f"{SYMBOL} — Bollinger Bands Analysis",
    xaxis_rangeslider_visible=False,
    height=900,
)
for r in range(1, 4):
    fig.update_xaxes(type="category", row=r, col=1)
    fig.update_yaxes(side="right", row=r, col=1)

fig.write_html(script_dir / f"{SYMBOL}_bollinger_chart.html")
fig.show()

# Explanation
current_pct = bb_pct.iloc[-1]
current_width = bb_width.iloc[-1]
min_width = pd.Series(bb_width).rolling(20).min().iloc[-1]

if current_pct > 1:
    position = "ABOVE upper band — overbought / breakout"
elif current_pct < 0:
    position = "BELOW lower band — oversold / breakdown"
elif current_pct > 0.8:
    position = "Near upper band — approaching resistance"
elif current_pct < 0.2:
    position = "Near lower band — approaching support"
else:
    position = "Inside bands — range-bound"

squeeze = "YES — volatility squeeze" if current_width <= min_width * 1.05 else "No"

print(f"\n{SYMBOL} — Bollinger Bands({BB_PERIOD}, {BB_STD}) Analysis")
print(f"Upper: {upper.iloc[-1]:.2f} | Middle: {middle.iloc[-1]:.2f} | Lower: {lower.iloc[-1]:.2f}")
print(f"%B: {current_pct:.4f}")
print(f"Position: {position}")
print(f"Band Width: {current_width:.4f}")
print(f"Squeeze: {squeeze}")
