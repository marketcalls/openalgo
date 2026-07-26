# Plotting — Plotly Chart Patterns

## Global Rules

1. **Always** use `template="plotly_dark"` for all charts
2. **Candlestick charts** must use `xaxis_type="category"` to avoid weekend/holiday gaps
3. **X-axis labels**: `df.index.strftime("%Y-%m-%d")` for daily, `"%Y-%m-%d %H:%M"` for intraday
4. **Never use icons/emojis** in chart titles or annotations
5. Use `make_subplots` for multi-panel layouts

---

## Candlestick with Indicator Overlay

```python
import plotly.graph_objects as go

x_labels = df.index.strftime("%Y-%m-%d")

fig = go.Figure()

# Candlestick
fig.add_trace(go.Candlestick(
    x=x_labels, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
    name="Price",
))

# EMA overlay
fig.add_trace(go.Scatter(
    x=x_labels, y=ema_20, mode="lines",
    name="EMA(20)", line=dict(color="cyan", width=1.5),
))

fig.update_layout(
    template="plotly_dark",
    title=f"{SYMBOL} — EMA(20)",
    xaxis_rangeslider_visible=False,
    xaxis_type="category",
    height=600,
)
fig.show()
```

---

## Multi-Panel Chart (Subplots)

Standard layout: Price + Overlays on top, Oscillators below.

```python
from plotly.subplots import make_subplots

fig = make_subplots(
    rows=3, cols=1, shared_xaxes=True,
    row_heights=[0.5, 0.25, 0.25],
    vertical_spacing=0.03,
    subplot_titles=["Price + Indicators", "RSI(14)", "MACD"],
)

x_labels = df.index.strftime("%Y-%m-%d")

# Row 1: Candlestick + overlays
fig.add_trace(go.Candlestick(
    x=x_labels, open=df["open"], high=high, low=low, close=close,
    name="Price", showlegend=False,
), row=1, col=1)

fig.add_trace(go.Scatter(
    x=x_labels, y=ema_20, mode="lines",
    name="EMA(20)", line=dict(color="cyan", width=1.5),
), row=1, col=1)

# Row 2: RSI
fig.add_trace(go.Scatter(
    x=x_labels, y=rsi, mode="lines",
    name="RSI(14)", line=dict(color="yellow", width=1.5),
), row=2, col=1)
fig.add_hline(y=70, line_dash="dash", line_color="red", opacity=0.5, row=2, col=1)
fig.add_hline(y=30, line_dash="dash", line_color="green", opacity=0.5, row=2, col=1)

# Row 3: MACD
fig.add_trace(go.Scatter(
    x=x_labels, y=macd_line, mode="lines",
    name="MACD", line=dict(color="cyan", width=1),
), row=3, col=1)
fig.add_trace(go.Scatter(
    x=x_labels, y=signal_line, mode="lines",
    name="Signal", line=dict(color="orange", width=1),
), row=3, col=1)

# MACD histogram with color
colors = ["green" if v >= 0 else "red" for v in histogram]
fig.add_trace(go.Bar(
    x=x_labels, y=histogram, name="Histogram",
    marker_color=colors, opacity=0.6,
), row=3, col=1)

fig.update_layout(
    template="plotly_dark",
    title=f"{SYMBOL} Technical Analysis",
    xaxis_rangeslider_visible=False,
    height=900,
)

# Category x-axis for all rows
for i in range(1, 4):
    fig.update_xaxes(type="category", row=i, col=1)

fig.show()
```

---

## Bollinger Bands (Fill Between)

```python
upper, middle, lower = ta.bbands(close, 20, 2.0)

fig = go.Figure()
fig.add_trace(go.Scatter(
    x=x_labels, y=upper, mode="lines", name="Upper BB",
    line=dict(color="rgba(100,149,237,0.5)", width=1),
))
fig.add_trace(go.Scatter(
    x=x_labels, y=lower, mode="lines", name="Lower BB",
    line=dict(color="rgba(100,149,237,0.5)", width=1),
    fill="tonexty", fillcolor="rgba(100,149,237,0.1)",
))
fig.add_trace(go.Scatter(
    x=x_labels, y=middle, mode="lines", name="SMA(20)",
    line=dict(color="cornflowerblue", width=1),
))
fig.add_trace(go.Candlestick(
    x=x_labels, open=df["open"], high=high, low=low, close=close,
    name="Price",
))
fig.update_layout(
    template="plotly_dark", xaxis_rangeslider_visible=False,
    xaxis_type="category", height=600,
)
```

---

## Supertrend (Color-Coded Direction)

```python
st, direction = ta.supertrend(high, low, close, 10, 3.0)

# Split into uptrend and downtrend segments
st_up = pd.Series(st, index=df.index).where(direction == -1)
st_down = pd.Series(st, index=df.index).where(direction == 1)

fig = go.Figure()
fig.add_trace(go.Candlestick(
    x=x_labels, open=df["open"], high=high, low=low, close=close, name="Price",
))
fig.add_trace(go.Scatter(
    x=x_labels, y=st_up, mode="lines", name="Supertrend (Up)",
    line=dict(color="lime", width=2),
))
fig.add_trace(go.Scatter(
    x=x_labels, y=st_down, mode="lines", name="Supertrend (Down)",
    line=dict(color="red", width=2),
))
```

---

## Volume Bar Chart

```python
# Color by price direction
vol_colors = ["green" if c >= o else "red" for c, o in zip(close, df["open"])]

fig.add_trace(go.Bar(
    x=x_labels, y=volume, name="Volume",
    marker_color=vol_colors, opacity=0.5,
), row=volume_row, col=1)
```

---

## Signal Markers (Buy/Sell Arrows)

```python
# Buy signals
buy_idx = df.index[entries == True]
buy_prices = close[entries == True]
fig.add_trace(go.Scatter(
    x=buy_idx.strftime("%Y-%m-%d"), y=buy_prices,
    mode="markers", name="Buy",
    marker=dict(symbol="triangle-up", size=12, color="lime"),
))

# Sell signals
sell_idx = df.index[exits == True]
sell_prices = close[exits == True]
fig.add_trace(go.Scatter(
    x=sell_idx.strftime("%Y-%m-%d"), y=sell_prices,
    mode="markers", name="Sell",
    marker=dict(symbol="triangle-down", size=12, color="red"),
))
```

---

## Save Chart to HTML

```python
fig.write_html(script_dir / f"{SYMBOL}_chart.html")
```

---

## Common Chart Height Guide

| Layout | Height |
|--------|--------|
| Single panel | 500-600px |
| 2 panels | 700px |
| 3 panels | 900px |
| 4 panels | 1000px |
| Dashboard (full) | 1200px |
