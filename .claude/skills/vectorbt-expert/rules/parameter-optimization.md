---
name: parameter-optimization
description: Parameter optimization techniques in VectorBT - broadcasting and loop-based grid search
metadata:
  tags: optimization, grid-search, heatmap, broadcasting, parameters, sharpe, drawdown
---

# Parameter Optimization

## Method 1: Broadcasting (Vectorized - VectorBT's Killer Feature)

Test thousands of parameter combinations simultaneously without loops.

**Exception:** Broadcasting requires VectorBT's built-in `vbt.MA.run()` because neither OpenAlgo ta nor TA-Lib can vectorize across parameter arrays. This is the ONLY case where `vbt.MA.run()` is acceptable — for parameter sweeps only, never for production backtests.

```python
import numpy as np
import vectorbt as vbt

# Test 99 x 99 = 9,801 window combinations at once
fast_ma = vbt.MA.run(close, window=np.arange(2, 101))
slow_ma = vbt.MA.run(close, window=np.arange(2, 101))

entries = fast_ma.ma_crossed_above(slow_ma)
exits = fast_ma.ma_crossed_below(slow_ma)

pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    init_cash=1_000_000, fees=0.00111, fixed_fees=20, freq="1D",
    min_size=1, size_granularity=1,
)

# Get total return for all combinations
total_returns = pf.total_return()

# Find best parameters
best_idx = total_returns.idxmax()
print(f"Best fast window: {best_idx[0]}, Best slow window: {best_idx[1]}")
print(f"Best return: {total_returns.max():.2%}")
```

## Method 2: Loop-Based Optimization (Recommended)

Uses OpenAlgo ta for indicators (default, compliant with project rules — swap to TA-Lib only if the user explicitly asks for it). More control, collects custom metrics:

```python
import numpy as np
import pandas as pd
import vectorbt as vbt
from tqdm import tqdm
from openalgo import ta

# Parameter grid
short_spans = np.arange(5, 15, 1)   # 5 to 14
long_spans = np.arange(15, 30, 1)   # 15 to 29

results = []

for short_span in tqdm(short_spans, desc="Optimizing"):
    for long_span in long_spans:
        if short_span >= long_span:
            continue

        ema_f = ta.ema(close, int(short_span))
        ema_s = ta.ema(close, int(long_span))

        buy_raw = (ema_f > ema_s) & (ema_f.shift(1) <= ema_s.shift(1))
        sell_raw = (ema_f < ema_s) & (ema_f.shift(1) >= ema_s.shift(1))

        entries = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
        exits = ta.exrem(sell_raw.fillna(False), buy_raw.fillna(False))

        portfolio = vbt.Portfolio.from_signals(
            close, entries, exits,
            size=0.75, size_type='percent',
            fees=0.00111, fixed_fees=20,
            init_cash=1_000_000, freq='1D',
            min_size=1, size_granularity=1,
        )

        results.append({
            'short_span': short_span,
            'long_span': long_span,
            'total_return': portfolio.total_return(),
            'sharpe_ratio': portfolio.sharpe_ratio(),
            'max_drawdown': portfolio.max_drawdown(),
            'trade_count': portfolio.trades.count(),
        })

# Convert to DataFrame for analysis
results_df = pd.DataFrame(results)
best = results_df.loc[results_df['sharpe_ratio'].idxmax()]
print(f"Best: Short EMA={int(best['short_span'])}, Long EMA={int(best['long_span'])}")
print(f"Return: {best['total_return']:.2%}, Sharpe: {best['sharpe_ratio']:.2f}")
```

## Heatmap Visualization

```python
import plotly.graph_objects as go

# Pivot results for heatmap (from loop-based optimization)
pivot_return = results_df.pivot_table(
    values='total_return',
    index='long_span',
    columns='short_span',
    aggfunc='first',
)

fig = go.Figure(data=go.Heatmap(
    z=pivot_return.values * 100,
    x=pivot_return.columns,
    y=pivot_return.index,
    colorscale='RdYlGn',
    text=np.round(pivot_return.values * 100, 1),
    texttemplate='%{text}%',
    textfont={"size": 8},
    colorbar=dict(title="Return %"),
))
fig.update_layout(
    title="EMA Crossover Optimization - Total Return Heatmap",
    xaxis_title="Fast EMA Period",
    yaxis_title="Slow EMA Period",
    template="plotly_dark",
    height=800,
    width=800,
)
fig.show()
```

## When to Use Which Method

| Method | Pros | Cons |
|--------|------|------|
| Broadcasting | Extremely fast, tests thousands at once | Limited to VectorBT's built-in indicators (exception to the OpenAlgo ta / TA-Lib rule) |
| Loop-based | Full OpenAlgo ta (or TA-Lib, if requested) compliance, any indicator, custom metrics | Slower, needs tqdm for progress |

**Prefer loop-based** for production optimization. Use broadcasting only for rapid exploration.

## Best Practices

- Always optimize on in-sample data and validate on out-of-sample (see [walk-forward](./walk-forward.md))
- Optimize for Sharpe ratio or risk-adjusted returns, not just total return
- Check trade count - high-return parameters with very few trades are unreliable
- Watch for overfitting: if neighboring parameter values give wildly different results, the strategy is fragile (see [pitfalls](./pitfalls.md))
- Use the heatmap to visualize parameter stability - look for broad green regions, not isolated spikes
