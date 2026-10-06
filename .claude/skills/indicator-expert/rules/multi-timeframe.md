# Multi-Timeframe Analysis

## Concept

Multi-timeframe analysis (MTF) computes the same indicator across different timeframes (e.g., 5m, 15m, 1h, D) to identify confluence zones where signals align.

---

## Pattern: Fetch Multiple Timeframes

```python
from datetime import datetime, timedelta

SYMBOL = "SBIN"
EXCHANGE = "NSE"

timeframes = {
    "5m": {"interval": "5m", "days": 30},
    "15m": {"interval": "15m", "days": 60},
    "1h": {"interval": "1h", "days": 180},
    "D": {"interval": "D", "days": 365 * 3},
}

data = {}
for tf_name, tf_config in timeframes.items():
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=tf_config["days"])
    df = client.history(
        symbol=SYMBOL, exchange=EXCHANGE,
        interval=tf_config["interval"],
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
    )
    # Normalize
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
    else:
        df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    if df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    data[tf_name] = df
```

---

## Pattern: Same Indicator Across Timeframes

```python
from openalgo import ta

results = {}
for tf_name, df in data.items():
    close = df["close"]
    results[tf_name] = {
        "rsi": ta.rsi(close, 14),
        "ema_20": ta.ema(close, 20),
        "ema_50": ta.ema(close, 50),
        "trend": "bullish" if ta.ema(close, 20).iloc[-1] > ta.ema(close, 50).iloc[-1] else "bearish",
    }

# Print MTF summary
print(f"\n{'Timeframe':<10} {'RSI(14)':<10} {'EMA Trend':<12}")
print("-" * 35)
for tf_name in timeframes:
    rsi_val = results[tf_name]["rsi"].iloc[-1]
    trend = results[tf_name]["trend"]
    print(f"{tf_name:<10} {rsi_val:<10.2f} {trend:<12}")
```

---

## Pattern: MTF Confluence Detection

```python
def check_confluence(results):
    """Check if all timeframes agree on direction."""
    trends = [results[tf]["trend"] for tf in results]
    all_bullish = all(t == "bullish" for t in trends)
    all_bearish = all(t == "bearish" for t in trends)

    if all_bullish:
        return "STRONG BULLISH - All timeframes aligned"
    elif all_bearish:
        return "STRONG BEARISH - All timeframes aligned"
    else:
        bull_count = sum(1 for t in trends if t == "bullish")
        return f"MIXED - {bull_count}/{len(trends)} bullish"

print(check_confluence(results))
```

---

## Chart: Multi-Timeframe Grid

```python
from plotly.subplots import make_subplots
import plotly.graph_objects as go

tf_list = list(data.keys())
fig = make_subplots(
    rows=2, cols=2,
    subplot_titles=[f"{SYMBOL} — {tf}" for tf in tf_list],
    vertical_spacing=0.08, horizontal_spacing=0.05,
)

for idx, tf in enumerate(tf_list):
    row = idx // 2 + 1
    col = idx % 2 + 1
    df = data[tf]
    x = df.index.strftime("%Y-%m-%d %H:%M") if tf != "D" else df.index.strftime("%Y-%m-%d")

    fig.add_trace(go.Candlestick(
        x=x, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name=tf, showlegend=False,
    ), row=row, col=col)

    ema_20 = ta.ema(df["close"], 20)
    fig.add_trace(go.Scatter(
        x=x, y=ema_20, mode="lines", name=f"EMA(20) {tf}",
        line=dict(color="cyan", width=1),
    ), row=row, col=col)

    fig.update_xaxes(type="category", row=row, col=col)

fig.update_layout(
    template="plotly_dark", height=800,
    title=f"{SYMBOL} Multi-Timeframe Analysis",
    showlegend=False,
)
for row in range(1, 3):
    for col in range(1, 3):
        fig.update_xaxes(rangeslider_visible=False, row=row, col=col)
fig.show()
```

---

## Pattern: Higher Timeframe Filter

Use a higher timeframe indicator as a filter for lower timeframe signals:

```python
# Daily trend filter
daily_ema_50 = ta.ema(data["D"]["close"], 50)
daily_trend_bullish = daily_ema_50.iloc[-1] < data["D"]["close"].iloc[-1]

# 5-minute signals (only take if aligned with daily trend)
close_5m = data["5m"]["close"]
rsi_5m = ta.rsi(close_5m, 14)

if daily_trend_bullish:
    # Only take buy signals on 5m RSI oversold
    buy_signals = rsi_5m < 30
    print("Daily trend: BULLISH — Looking for 5m RSI oversold entries")
else:
    # Only take sell signals on 5m RSI overbought
    sell_signals = rsi_5m > 70
    print("Daily trend: BEARISH — Looking for 5m RSI overbought entries")
```
