"""
Multi-Timeframe Streamlit Dashboard — Same symbol across 4 timeframes
Run: streamlit run app.py
Open: http://localhost:8501
"""
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import find_dotenv, load_dotenv
from openalgo import api, ta

load_dotenv(find_dotenv(), override=False)

st.set_page_config(page_title="Multi-Timeframe Analysis", layout="wide")

client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host=os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"),
)

TIMEFRAMES = {
    "5m": {"interval": "5m", "days": 7, "fmt": "%H:%M"},
    "15m": {"interval": "15m", "days": 30, "fmt": "%m-%d %H:%M"},
    "1h": {"interval": "1h", "days": 90, "fmt": "%m-%d %H:%M"},
    "D": {"interval": "D", "days": 365, "fmt": "%Y-%m-%d"},
}


def fetch_tf_data(symbol, exchange, interval, days):
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

auto_refresh = st.sidebar.checkbox("Auto-refresh", value=False)
refresh_sec = st.sidebar.slider("Refresh interval (sec)", 10, 120, 60,
                                disabled=not auto_refresh)

# --- Title ---
st.title(f"{symbol} Multi-Timeframe Analysis")

# --- Fetch and Chart ---
trends = {}

# 2x2 grid
row1 = st.columns(2)
row2 = st.columns(2)
all_cols = [row1[0], row1[1], row2[0], row2[1]]

for idx, (tf_name, tf_cfg) in enumerate(TIMEFRAMES.items()):
    with all_cols[idx]:
        st.subheader(f"{tf_name}")
        try:
            df = fetch_tf_data(symbol, exchange, tf_cfg["interval"], tf_cfg["days"])
        except Exception as e:
            st.warning(f"Could not load {tf_name}: {e}")
            continue

        if len(df) < 20:
            st.warning(f"Insufficient data for {tf_name}")
            continue

        close = df["close"]
        x = df.index.strftime(tf_cfg["fmt"])

        fig = go.Figure()

        # Candlestick
        fig.add_trace(go.Candlestick(
            x=x, open=df["open"], high=df["high"], low=df["low"], close=close,
            showlegend=False,
        ))

        # EMA overlays
        ema_20 = ta.ema(close, 20)
        ema_50 = ta.ema(close, min(50, len(close) - 1)) if len(close) > 50 else ema_20

        fig.add_trace(go.Scatter(x=x, y=ema_20, name="EMA(20)",
                                 line=dict(color="cyan", width=1), showlegend=False))
        fig.add_trace(go.Scatter(x=x, y=ema_50, name="EMA(50)",
                                 line=dict(color="orange", width=1), showlegend=False))

        fig.update_layout(
            template="plotly_dark", height=350,
            xaxis_rangeslider_visible=False, xaxis_type="category",
            margin=dict(l=10, r=10, t=10, b=10),
        )
        fig.update_yaxes(side="right")
        st.plotly_chart(fig, use_container_width=True)

        # Trend determination
        rsi_val = ta.rsi(close, 14).iloc[-1] if len(close) > 14 else 50
        ema_trend = "Bullish" if ema_20.iloc[-1] > ema_50.iloc[-1] else "Bearish"
        trends[tf_name] = {"trend": ema_trend, "rsi": rsi_val, "ltp": close.iloc[-1]}

# --- Confluence Summary ---
if trends:
    st.markdown("---")
    st.subheader("Confluence Summary")

    bull_count = sum(1 for v in trends.values() if v["trend"] == "Bullish")
    total = len(trends)

    if bull_count == total:
        st.success(f"STRONG BULLISH -- All {total} timeframes aligned")
    elif bull_count == 0:
        st.error(f"STRONG BEARISH -- All {total} timeframes aligned")
    else:
        st.warning(f"MIXED -- {bull_count}/{total} timeframes bullish")

    # Trend cards
    cols = st.columns(len(trends))
    for i, (tf, data) in enumerate(trends.items()):
        with cols[i]:
            delta_color = "normal" if data["trend"] == "Bullish" else "inverse"
            st.metric(
                label=tf,
                value=data["trend"],
                delta=f"RSI: {data['rsi']:.1f}",
                delta_color=delta_color,
            )

# --- Auto-refresh ---
if auto_refresh:
    import time
    time.sleep(refresh_sec)
    st.rerun()
