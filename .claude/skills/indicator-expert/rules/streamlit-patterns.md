# Streamlit Patterns — Streamlit Web Applications

Alternative to Plotly Dash for building indicator dashboards. Use Streamlit when the user prefers it or asks for `streamlit` specifically.

---

## Basic Streamlit App Structure

```python
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


def fetch_data(symbol, exchange, interval, days=365):
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
interval = st.sidebar.selectbox("Interval", ["1m", "5m", "15m", "1h", "D"])

overlays = st.sidebar.multiselect(
    "Overlay Indicators",
    ["EMA(20)", "EMA(50)", "Bollinger Bands", "Supertrend"],
    default=["EMA(20)"],
)
subplots = st.sidebar.multiselect(
    "Subplot Indicators",
    ["RSI", "MACD", "Volume", "Stochastic", "ADX"],
    default=["RSI", "Volume"],
)

# --- Fetch Data ---
df = fetch_data(symbol, exchange, interval)
close = df["close"]
high = df["high"]
low = df["low"]
x_labels = df.index.strftime("%Y-%m-%d %H:%M" if interval != "D" else "%Y-%m-%d")

# --- Build Chart ---
n_rows = 1 + len(subplots)
row_heights = [0.5] + [0.5 / len(subplots)] * len(subplots) if subplots else [1.0]

fig = make_subplots(
    rows=n_rows, cols=1, shared_xaxes=True,
    row_heights=row_heights, vertical_spacing=0.03,
)

# Candlestick
fig.add_trace(go.Candlestick(
    x=x_labels, open=df["open"], high=high, low=low, close=close,
    name="Price", showlegend=False,
), row=1, col=1)

# Overlays
if "EMA(20)" in overlays:
    fig.add_trace(go.Scatter(x=x_labels, y=ta.ema(close, 20),
                             name="EMA(20)", line=dict(color="cyan", width=1)),
                  row=1, col=1)
if "EMA(50)" in overlays:
    fig.add_trace(go.Scatter(x=x_labels, y=ta.ema(close, 50),
                             name="EMA(50)", line=dict(color="orange", width=1)),
                  row=1, col=1)

# Subplots
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
    elif sp == "Volume":
        vc = ["green" if c >= o else "red" for c, o in zip(close, df["open"])]
        fig.add_trace(go.Bar(x=x_labels, y=df["volume"], name="Volume",
                             marker_color=vc, opacity=0.5), row=i, col=1)

fig.update_layout(
    template="plotly_dark", height=200 + 250 * n_rows,
    xaxis_rangeslider_visible=False,
)
for r in range(1, n_rows + 1):
    fig.update_xaxes(type="category", row=r, col=1)

# --- Display ---
st.title(f"{symbol} Technical Analysis")
st.plotly_chart(fig, use_container_width=True)
```

---

## Metrics Row Pattern

```python
# Stats metrics row
quote = client.quotes(symbol=symbol, exchange=exchange)
d = quote.get("data", {})
ltp = d.get("ltp", 0)
prev_close = d.get("prev_close", 1)
change = ltp - prev_close
change_pct = (change / prev_close) * 100 if prev_close else 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("LTP", f"{ltp:,.2f}", f"{change:+.2f}")
col2.metric("Change %", f"{change_pct:+.2f}%")
col3.metric("Volume", f"{d.get('volume', 0):,}")
col4.metric("Day Range", f"{d.get('low', 0):,.2f} - {d.get('high', 0):,.2f}")
```

---

## Multi-Timeframe Grid Pattern

```python
TIMEFRAMES = {
    "5m": {"interval": "5m", "days": 7, "fmt": "%H:%M"},
    "15m": {"interval": "15m", "days": 30, "fmt": "%m-%d %H:%M"},
    "1h": {"interval": "1h", "days": 90, "fmt": "%m-%d %H:%M"},
    "D": {"interval": "D", "days": 365, "fmt": "%Y-%m-%d"},
}

st.title(f"{symbol} Multi-Timeframe Analysis")

# 2x2 grid
row1_cols = st.columns(2)
row2_cols = st.columns(2)
all_cols = [row1_cols[0], row1_cols[1], row2_cols[0], row2_cols[1]]

trends = {}
for idx, (tf_name, tf_cfg) in enumerate(TIMEFRAMES.items()):
    with all_cols[idx]:
        st.subheader(f"{symbol} - {tf_name}")
        try:
            df = fetch_data(symbol, exchange, tf_cfg["interval"], tf_cfg["days"])
        except Exception:
            st.warning(f"Could not load {tf_name}")
            continue

        close = df["close"]
        x = df.index.strftime(tf_cfg["fmt"])

        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=x, open=df["open"], high=df["high"], low=df["low"], close=close,
            showlegend=False,
        ))

        ema_20 = ta.ema(close, 20)
        fig.add_trace(go.Scatter(x=x, y=ema_20, name="EMA(20)",
                                 line=dict(color="cyan", width=1), showlegend=False))

        fig.update_layout(
            template="plotly_dark", height=350,
            xaxis_rangeslider_visible=False, xaxis_type="category",
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Track trend
        if len(close) > 20:
            ema_50 = ta.ema(close, min(50, len(close) - 1))
            trend = "Bullish" if ema_20.iloc[-1] > ema_50.iloc[-1] else "Bearish"
            rsi_val = ta.rsi(close, 14).iloc[-1] if len(close) > 14 else 50
            trends[tf_name] = {"trend": trend, "rsi": rsi_val}

# Confluence summary
if trends:
    bull_count = sum(1 for v in trends.values() if v["trend"] == "Bullish")
    total = len(trends)

    if bull_count == total:
        st.success(f"STRONG BULLISH -- All {total} timeframes aligned")
    elif bull_count == 0:
        st.error(f"STRONG BEARISH -- All {total} timeframes aligned")
    else:
        st.warning(f"MIXED -- {bull_count}/{total} bullish")

    cols = st.columns(len(trends))
    for i, (tf, data) in enumerate(trends.items()):
        with cols[i]:
            color = "green" if data["trend"] == "Bullish" else "red"
            st.metric(tf, data["trend"], f"RSI: {data['rsi']:.1f}")
```

---

## Scanner Table Pattern

```python
st.title("Indicator Scanner")

scan_type = st.sidebar.selectbox("Scan Type", [
    "RSI Oversold", "RSI Overbought", "EMA Crossover",
    "Supertrend Buy", "Volume Spike",
])

WATCHLIST = ["SBIN", "RELIANCE", "INFY", "HDFCBANK", "TCS", "ICICIBANK"]

if st.sidebar.button("Run Scan"):
    progress = st.progress(0)
    results = []

    for i, sym in enumerate(WATCHLIST):
        progress.progress((i + 1) / len(WATCHLIST))
        try:
            df = fetch_data(sym, "NSE", "D")
            close = df["close"]
            rsi_val = ta.rsi(close, 14).iloc[-1]

            if scan_type == "RSI Oversold" and rsi_val < 30:
                results.append({"Symbol": sym, "LTP": close.iloc[-1],
                                "RSI": round(rsi_val, 2), "Signal": "OVERSOLD"})
            elif scan_type == "RSI Overbought" and rsi_val > 70:
                results.append({"Symbol": sym, "LTP": close.iloc[-1],
                                "RSI": round(rsi_val, 2), "Signal": "OVERBOUGHT"})
        except Exception:
            pass

    progress.empty()

    if results:
        df_results = pd.DataFrame(results)
        st.dataframe(df_results, use_container_width=True)
        st.download_button("Download CSV", df_results.to_csv(index=False),
                           file_name=f"{scan_type.lower().replace(' ', '_')}_results.csv")
    else:
        st.info("No symbols matched the scan criteria.")
```

---

## Auto-Refresh Pattern

```python
import time

# Sidebar refresh control
auto_refresh = st.sidebar.checkbox("Auto-refresh", value=False)
refresh_interval = st.sidebar.slider("Refresh interval (sec)", 5, 60, 10)

# Place at the end of the app
if auto_refresh:
    time.sleep(refresh_interval)
    st.rerun()
```

---

## Dark Theme CSS Injection

Streamlit uses its own theming. For a dark look consistent with Plotly charts:

```python
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .stMetric label { color: #fafafa; }
    .stMetric [data-testid="stMetricValue"] { color: #fafafa; }
</style>
""", unsafe_allow_html=True)
```

Or create `.streamlit/config.toml` in the app directory:

```toml
[theme]
base = "dark"
primaryColor = "#00d4ff"
backgroundColor = "#0e1117"
secondaryBackgroundColor = "#1a1a2e"
textColor = "#fafafa"
```

---

## Running Streamlit Apps

```bash
cd dashboards/{dashboard_name}
streamlit run app.py
# Opens at http://localhost:8501 in browser
```

---

## When to Use Streamlit vs Dash

| Feature | Streamlit | Plotly Dash |
|---------|-----------|-------------|
| Setup complexity | Minimal (no callbacks) | Moderate (callback decorators) |
| Reactivity | Automatic rerun on input change | Explicit callbacks |
| Layout control | `st.columns()`, `st.sidebar` | `dbc.Row/Col`, full CSS |
| Charts | `st.plotly_chart()` | `dcc.Graph()` |
| Stats display | `st.metric()` built-in | `dbc.Card()` manual |
| Tables | `st.dataframe()` built-in | `dash_table.DataTable` |
| File download | `st.download_button()` built-in | `dcc.Download` component |
| Progress bars | `st.progress()` built-in | Manual |
| Best for | Quick prototypes, single-page apps | Complex multi-page apps, fine-grained control |
