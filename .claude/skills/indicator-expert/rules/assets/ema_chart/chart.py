"""
EMA Chart — Exponential Moving Average overlay on candlestick
"""
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dotenv import find_dotenv, load_dotenv
from openalgo import api, ta

script_dir = Path(__file__).resolve().parent
load_dotenv(find_dotenv(), override=False)

SYMBOL = "SBIN"
EXCHANGE = "NSE"
INTERVAL = "D"
EMA_FAST = 10
EMA_SLOW = 20
EMA_LONG = 50

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

# Compute EMAs
ema_fast = ta.ema(close, EMA_FAST)
ema_slow = ta.ema(close, EMA_SLOW)
ema_long = ta.ema(close, EMA_LONG)

# Crossover signals
buy_signals = ta.crossover(ema_fast, ema_slow)
sell_signals = ta.crossunder(ema_fast, ema_slow)

x_labels = df.index.strftime("%Y-%m-%d")

fig = go.Figure()

fig.add_trace(go.Candlestick(
    x=x_labels, open=df["open"], high=df["high"], low=df["low"], close=close,
    name="Price",
))

fig.add_trace(go.Scatter(
    x=x_labels, y=ema_fast, mode="lines",
    name=f"EMA({EMA_FAST})", line=dict(color="cyan", width=1.5),
))
fig.add_trace(go.Scatter(
    x=x_labels, y=ema_slow, mode="lines",
    name=f"EMA({EMA_SLOW})", line=dict(color="orange", width=1.5),
))
fig.add_trace(go.Scatter(
    x=x_labels, y=ema_long, mode="lines",
    name=f"EMA({EMA_LONG})", line=dict(color="magenta", width=1, dash="dash"),
))

# Buy signals
buy_idx = [x_labels[i] for i in range(len(buy_signals)) if buy_signals[i]]
buy_prices = [close.iloc[i] for i in range(len(buy_signals)) if buy_signals[i]]
fig.add_trace(go.Scatter(
    x=buy_idx, y=buy_prices, mode="markers", name="Buy",
    marker=dict(symbol="triangle-up", size=12, color="lime"),
))

# Sell signals
sell_idx = [x_labels[i] for i in range(len(sell_signals)) if sell_signals[i]]
sell_prices = [close.iloc[i] for i in range(len(sell_signals)) if sell_signals[i]]
fig.add_trace(go.Scatter(
    x=sell_idx, y=sell_prices, mode="markers", name="Sell",
    marker=dict(symbol="triangle-down", size=12, color="red"),
))

fig.update_layout(
    template="plotly_dark",
    title=f"{SYMBOL} — EMA({EMA_FAST}/{EMA_SLOW}/{EMA_LONG})",
    xaxis_rangeslider_visible=False,
    xaxis_type="category",
    height=600,
)
fig.update_yaxes(side="right")

fig.write_html(script_dir / f"{SYMBOL}_ema_chart.html")
fig.show()

# Explanation
current_fast = ema_fast.iloc[-1]
current_slow = ema_slow.iloc[-1]
current_price = close.iloc[-1]
trend = "bullish" if current_fast > current_slow else "bearish"
above_long = "above" if current_price > ema_long.iloc[-1] else "below"

print(f"\n{SYMBOL} — EMA Analysis")
print(f"Price: {current_price:.2f}")
print(f"EMA({EMA_FAST}): {current_fast:.2f}")
print(f"EMA({EMA_SLOW}): {current_slow:.2f}")
print(f"EMA({EMA_LONG}): {ema_long.iloc[-1]:.2f}")
print(f"Short-term trend: {trend} (EMA {EMA_FAST} {'>' if trend == 'bullish' else '<'} EMA {EMA_SLOW})")
print(f"Long-term position: Price {above_long} EMA({EMA_LONG})")
