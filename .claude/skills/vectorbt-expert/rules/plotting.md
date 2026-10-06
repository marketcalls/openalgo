---
name: plotting
description: Plotting equity curves, drawdowns, candlestick charts, and custom charts with VectorBT and Plotly
metadata:
  tags: plotting, charts, equity-curve, drawdown, plotly, subplots, visualization, candlestick
---

# Plotting

## Candlestick Chart (Plotly with Category X-Axis)

Always use `xaxis type="category"` for candlestick charts to avoid gaps on weekends/holidays:

```python
import plotly.graph_objects as go
import pandas as pd

# Format X-axis labels
formatted_index = df.index.strftime('%d-%b<br>%H:%M')

# Reduce tick crowding
total_points = len(df)
tick_step = max(1, total_points // 12)
tick_indices = list(range(0, total_points, tick_step))

# Create Plotly Candlestick Chart
fig = go.Figure(data=[
    go.Candlestick(
        x=formatted_index,
        open=df['open'],
        high=df['high'],
        low=df['low'],
        close=df['close'],
        name="RELIANCE"
    )
])

fig.update_layout(
    title="RELIANCE - 5 Minute Chart (Last 20 Days)",
    xaxis_title="Time",
    yaxis_title="Price (INR)",
    xaxis_rangeslider_visible=False,
    template="plotly_dark",
    height=600,
    width=1000,
    xaxis=dict(
        type="category",        # CRITICAL: prevents gaps on weekends/holidays
        tickmode="array",
        tickvals=[formatted_index[i] for i in tick_indices],
        tickangle=0
    )
)

fig.show()
```

## Candlestick with Indicators (Multi-Panel)

```python
from plotly.subplots import make_subplots

formatted_index = df.index.strftime('%d-%b<br>%H:%M')
total_points = len(df)
tick_step = max(1, total_points // 12)
tick_indices = list(range(0, total_points, tick_step))

fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                    row_heights=[0.7, 0.3], vertical_spacing=0.05)

# Candlestick
fig.add_trace(go.Candlestick(
    x=formatted_index,
    open=df['open'], high=df['high'],
    low=df['low'], close=df['close'],
    name="Price"
), row=1, col=1)

# EMA overlay
fig.add_trace(go.Scatter(
    x=formatted_index, y=ema_fast, name="EMA Fast", line=dict(width=1)
), row=1, col=1)
fig.add_trace(go.Scatter(
    x=formatted_index, y=ema_slow, name="EMA Slow", line=dict(width=1)
), row=1, col=1)

# Volume
fig.add_trace(go.Bar(
    x=formatted_index, y=df['volume'], name="Volume", marker_color='gray'
), row=2, col=1)

fig.update_layout(
    xaxis_rangeslider_visible=False,
    template="plotly_dark",
    height=700, width=1000,
    xaxis2=dict(
        type="category",
        tickmode="array",
        tickvals=[formatted_index[i] for i in tick_indices],
        tickangle=0
    )
)
fig.show()
```

## VectorBT Built-in Plots

```python
fig = pf.plot()                                         # Full portfolio plot
fig.show()

fig = pf.plot(subplots=['cum_returns'])                 # Cumulative returns
fig.show()

fig = pf.plot_cum_returns()                             # Dedicated cumulative returns
fig.show()

fig = pf.plot(subplots=['value', 'underwater'])         # Equity + drawdown
fig.show()
```

## Available Subplots

```python
list(pf.subplots.keys())   # See all available subplot names
# Common: 'value', 'cum_returns', 'underwater', 'drawdowns', 'trades', 'orders'
```

## Custom Subplot Settings

```python
fig = pf.plot(
    subplots=['value', 'underwater'],
    subplot_settings={
        'value': {'title': 'Equity Curve'},
        'underwater': {'title': 'Drawdown', 'yaxis_kwargs': {'tickformat': '.1%'}}
    }
)
fig.show()
```

## Full 7-Panel Plot Pack

```python
fig = pf.plot(
    subplots=[
        "value",          # equity curve
        "underwater",     # % drawdown over time
        "drawdowns",      # top-N drawdown ranges
        "orders",         # buy/sell markers
        "trades",         # entry/exit lines
        "net_exposure",   # net exposure
        "cash",           # cash curve
    ],
    make_subplots_kwargs=dict(
        rows=7, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        row_heights=[0.25, 0.12, 0.12, 0.16, 0.12, 0.12, 0.11],
    ),
    template="plotly_dark",
    title="Strategy Backtest Results",
)
fig.show()
```

## Custom Strategy vs Benchmark Chart (Plotly)

```python
import plotly.graph_objects as go
from plotly.subplots import make_subplots

cum_pf = pf.value() / pf.value().iloc[0] - 1
cum_bm = (nifty / nifty.iloc[0] - 1).reindex(cum_pf.index).ffill().bfill()
dd_pf = cum_pf / cum_pf.cummax() - 1

fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                    row_heights=[0.65, 0.35], vertical_spacing=0.07)
fig.add_trace(go.Scatter(x=cum_pf.index, y=cum_pf, name='Strategy (cum %)'), row=1, col=1)
fig.add_trace(go.Scatter(x=cum_bm.index, y=cum_bm, name='NIFTY 50 (cum %)'), row=1, col=1)
fig.add_trace(go.Scatter(x=dd_pf.index, y=dd_pf, name='Drawdown', mode='lines'), row=2, col=1)
fig.update_yaxes(tickformat='.1%', row=1, col=1)
fig.update_yaxes(title_text='Drawdown', tickformat='.1%', row=2, col=1)
fig.update_layout(title='Cumulative Returns vs NIFTY 50 + Drawdown')
fig.show()
```

## Best Practices

- Always use `template="plotly_dark"` for consistent dark-themed charts
- Always use `xaxis type="category"` for candlestick/OHLC charts to avoid weekend/holiday gaps
- Use `xaxis_rangeslider_visible=False` to hide the default range slider on candlestick charts
- Format X-axis labels with `strftime('%d-%b<br>%H:%M')` for clean date-time display
- Limit tick count with `tick_step = max(1, total_points // 12)` to avoid crowding
- Use `shared_xaxes=True` for multi-panel layouts so zooming syncs
- Format percentage axes with `tickformat='.1%'`
- Include benchmark comparison in equity curves for context
- Export charts: `fig.write_html("chart.html")` for sharing

## NEVER Do This

- Never use Plotly's default datetime x-axis for OHLC/candlestick charts (creates gaps on non-trading days)
- Never use VectorBT's built-in RSI/MA indicators for plotting - always use OpenAlgo ta (or TA-Lib if the user requested it) computed values
- Never forget `xaxis_rangeslider_visible=False` on candlestick charts (wastes space)
