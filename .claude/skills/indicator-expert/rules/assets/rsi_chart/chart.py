"""
RSI Chart — Relative Strength Index with overbought/oversold zones
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
RSI_PERIOD = 14

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
rsi = ta.rsi(close, RSI_PERIOD)

x_labels = df.index.strftime("%Y-%m-%d")

fig = make_subplots(
    rows=2, cols=1, shared_xaxes=True,
    row_heights=[0.65, 0.35], vertical_spacing=0.03,
    subplot_titles=[f"{SYMBOL} Price", f"RSI({RSI_PERIOD})"],
)

# Price
fig.add_trace(go.Candlestick(
    x=x_labels, open=df["open"], high=df["high"], low=df["low"], close=close,
    name="Price", showlegend=False,
), row=1, col=1)

# RSI
fig.add_trace(go.Scatter(
    x=x_labels, y=rsi, mode="lines",
    name=f"RSI({RSI_PERIOD})", line=dict(color="yellow", width=1.5),
), row=2, col=1)

# Overbought/Oversold zones
fig.add_hline(y=70, line_dash="dash", line_color="red", opacity=0.7, row=2, col=1)
fig.add_hline(y=30, line_dash="dash", line_color="green", opacity=0.7, row=2, col=1)
fig.add_hline(y=50, line_dash="dot", line_color="gray", opacity=0.3, row=2, col=1)

# Color zones
fig.add_hrect(y0=70, y1=100, fillcolor="red", opacity=0.05, row=2, col=1)
fig.add_hrect(y0=0, y1=30, fillcolor="green", opacity=0.05, row=2, col=1)

fig.update_layout(
    template="plotly_dark",
    title=f"{SYMBOL} — RSI({RSI_PERIOD}) Analysis",
    xaxis_rangeslider_visible=False,
    height=700,
)
fig.update_xaxes(type="category", row=1, col=1)
fig.update_xaxes(type="category", row=2, col=1)
fig.update_yaxes(range=[0, 100], row=2, col=1)
fig.update_yaxes(side="right")

fig.write_html(script_dir / f"{SYMBOL}_rsi_chart.html")
fig.show()

# Explanation
current_rsi = rsi.iloc[-1]
if current_rsi > 70:
    zone = "OVERBOUGHT (>70) — Price may be stretched, potential pullback"
elif current_rsi < 30:
    zone = "OVERSOLD (<30) — Price may be undervalued, potential bounce"
elif current_rsi > 50:
    zone = "Bullish zone (50-70) — Momentum favors buyers"
else:
    zone = "Bearish zone (30-50) — Momentum favors sellers"

print(f"\n{SYMBOL} — RSI({RSI_PERIOD}) Analysis")
print(f"Current RSI: {current_rsi:.2f}")
print(f"Zone: {zone}")
