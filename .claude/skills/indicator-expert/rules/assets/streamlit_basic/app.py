"""
Single-Symbol Streamlit Dashboard — Technical Indicator Analysis
Run: streamlit run app.py
Open: http://localhost:8501
"""
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from dotenv import find_dotenv, load_dotenv
from openalgo import api, ta

load_dotenv(find_dotenv(), override=False)

st.set_page_config(page_title="OpenAlgo Indicators", layout="wide")

client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host=os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"),
)

INTERVAL_DAYS = {"1m": 2, "5m": 7, "15m": 30, "1h": 90, "D": 365}


def fetch_data(symbol, exchange, interval):
    days = INTERVAL_DAYS.get(interval, 365)
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)
    df = client.history(
        symbol=symbol, exchange=exchange, interval=interval,
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
    return df


# --- Sidebar ---
st.sidebar.title("Settings")
symbol = st.sidebar.text_input("Symbol", value="SBIN")
exchange = st.sidebar.selectbox("Exchange", ["NSE", "BSE", "NFO", "NSE_INDEX"])
interval = st.sidebar.selectbox("Interval", ["1m", "5m", "15m", "1h", "D"], index=4)

overlays = st.sidebar.multiselect(
    "Overlay Indicators",
    ["EMA(20)", "EMA(50)", "Bollinger Bands", "Supertrend"],
    default=["EMA(20)"],
)
subplots = st.sidebar.multiselect(
    "Subplot Indicators",
    ["RSI", "MACD", "Volume", "Stochastic", "ADX", "OBV"],
    default=["RSI", "Volume"],
)

auto_refresh = st.sidebar.checkbox("Auto-refresh", value=False)
refresh_sec = st.sidebar.slider("Refresh interval (sec)", 5, 60, 30,
                                disabled=not auto_refresh)

# --- Fetch Data ---
try:
    df = fetch_data(symbol, exchange, interval)
except Exception as e:
    st.error(f"Error fetching data: {e}")
    st.stop()

close = df["close"]
high = df["high"]
low = df["low"]
volume = df["volume"]
fmt = "%H:%M" if interval in ("1m", "5m", "15m") else "%Y-%m-%d"
x_labels = df.index.strftime(fmt)

# --- Stats Metrics ---
st.title(f"{symbol} Technical Analysis")

try:
    quote = client.quotes(symbol=symbol, exchange=exchange)
    d = quote.get("data", {})
    ltp = d.get("ltp", close.iloc[-1])
    prev = d.get("prev_close", close.iloc[-2] if len(close) > 1 else ltp)
    change = ltp - prev
    change_pct = (change / prev) * 100 if prev else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("LTP", f"{ltp:,.2f}", f"{change:+.2f}")
    c2.metric("Change %", f"{change_pct:+.2f}%")
    c3.metric("Volume", f"{d.get('volume', int(volume.iloc[-1])):,}")
    c4.metric("RSI(14)", f"{ta.rsi(close, 14).iloc[-1]:.1f}")
    ema20_val = ta.ema(close, 20).iloc[-1]
    c5.metric("EMA(20)", f"{ema20_val:,.2f}",
              f"{'Above' if ltp > ema20_val else 'Below'}")
except Exception:
    pass

# --- Build Chart ---
n_rows = 1 + len(subplots)
row_heights = [0.5] + [0.5 / len(subplots)] * len(subplots) if subplots else [1.0]

fig = make_subplots(
    rows=n_rows, cols=1, shared_xaxes=True,
    row_heights=row_heights, vertical_spacing=0.03,
)

# Row 1: Candlestick + overlays
fig.add_trace(go.Candlestick(
    x=x_labels, open=df["open"], high=high, low=low, close=close,
    name="Price", showlegend=False,
), row=1, col=1)

if "EMA(20)" in overlays:
    fig.add_trace(go.Scatter(x=x_labels, y=ta.ema(close, 20),
                             name="EMA(20)", line=dict(color="cyan", width=1)),
                  row=1, col=1)
if "EMA(50)" in overlays:
    fig.add_trace(go.Scatter(x=x_labels, y=ta.ema(close, 50),
                             name="EMA(50)", line=dict(color="orange", width=1)),
                  row=1, col=1)
if "Bollinger Bands" in overlays:
    upper, mid, lower = ta.bbands(close, 20, 2.0)
    fig.add_trace(go.Scatter(x=x_labels, y=upper, name="BB Upper",
                             line=dict(color="gray", dash="dash")), row=1, col=1)
    fig.add_trace(go.Scatter(x=x_labels, y=lower, name="BB Lower",
                             line=dict(color="gray", dash="dash"),
                             fill="tonexty", fillcolor="rgba(128,128,128,0.1)"),
                  row=1, col=1)
if "Supertrend" in overlays:
    st_line, st_dir = ta.supertrend(high, low, close, 10, 3.0)
    st_dir_s = pd.Series(st_dir, index=df.index)
    colors = ["green" if d == -1 else "red" for d in st_dir]
    for j in range(len(x_labels)):
        if j == 0:
            continue
        fig.add_trace(go.Scatter(
            x=[x_labels[j - 1], x_labels[j]],
            y=[st_line[j - 1], st_line[j]],
            mode="lines", showlegend=False,
            line=dict(color=colors[j], width=2),
        ), row=1, col=1)

# Dynamic subplots
for i, sp in enumerate(subplots, start=2):
    if sp == "RSI":
        rsi = ta.rsi(close, 14)
        fig.add_trace(go.Scatter(x=x_labels, y=rsi, name="RSI(14)",
                                 line=dict(color="yellow", width=1)), row=i, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=i, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=i, col=1)
    elif sp == "MACD":
        m, s, h = ta.macd(close, 12, 26, 9)
        fig.add_trace(go.Scatter(x=x_labels, y=m, name="MACD",
                                 line=dict(color="cyan")), row=i, col=1)
        fig.add_trace(go.Scatter(x=x_labels, y=s, name="Signal",
                                 line=dict(color="orange")), row=i, col=1)
        colors_h = ["green" if v >= 0 else "red" for v in h]
        fig.add_trace(go.Bar(x=x_labels, y=h, name="Hist",
                             marker_color=colors_h, opacity=0.6), row=i, col=1)
    elif sp == "Volume":
        vc = ["green" if c >= o else "red" for c, o in zip(close, df["open"])]
        fig.add_trace(go.Bar(x=x_labels, y=volume, name="Volume",
                             marker_color=vc, opacity=0.5), row=i, col=1)
    elif sp == "Stochastic":
        k, d = ta.stochastic(high, low, close, k_period=14, smooth_k=3, d_period=3)
        fig.add_trace(go.Scatter(x=x_labels, y=k, name="%K",
                                 line=dict(color="cyan", width=1)), row=i, col=1)
        fig.add_trace(go.Scatter(x=x_labels, y=d, name="%D",
                                 line=dict(color="orange", width=1)), row=i, col=1)
        fig.add_hline(y=80, line_dash="dash", line_color="red", opacity=0.5, row=i, col=1)
        fig.add_hline(y=20, line_dash="dash", line_color="green", opacity=0.5, row=i, col=1)
    elif sp == "ADX":
        plus_di, minus_di, adx_val = ta.adx(high, low, close, 14)
        fig.add_trace(go.Scatter(x=x_labels, y=adx_val, name="ADX",
                                 line=dict(color="white", width=1.5)), row=i, col=1)
        fig.add_trace(go.Scatter(x=x_labels, y=plus_di, name="+DI",
                                 line=dict(color="green", width=1)), row=i, col=1)
        fig.add_trace(go.Scatter(x=x_labels, y=minus_di, name="-DI",
                                 line=dict(color="red", width=1)), row=i, col=1)
    elif sp == "OBV":
        fig.add_trace(go.Scatter(x=x_labels, y=ta.obv(close, volume),
                                 name="OBV", line=dict(color="magenta", width=1)),
                      row=i, col=1)

fig.update_layout(
    template="plotly_dark", height=200 + 250 * n_rows,
    xaxis_rangeslider_visible=False,
)
for r in range(1, n_rows + 1):
    fig.update_xaxes(type="category", row=r, col=1)
    fig.update_yaxes(side="right", row=r, col=1)

st.plotly_chart(fig, use_container_width=True)

# --- Auto-refresh ---
if auto_refresh:
    import time
    time.sleep(refresh_sec)
    st.rerun()
