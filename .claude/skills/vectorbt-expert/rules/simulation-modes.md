---
name: simulation-modes
description: VectorBT portfolio simulation modes - from_signals, from_orders, from_order_func, from_holding
metadata:
  tags: portfolio, simulation, from_signals, from_orders, from_holding, direction
---

# VectorBT Simulation Modes

## 1. from_signals (Signal-Based) - Most Common

Entry/exit boolean arrays. VectorBT processes signals sequentially - after entry, waits for exit before next entry (unless `accumulate=True`).

```python
import vectorbt as vbt
import numpy as np

pf = vbt.Portfolio.from_signals(
    close,                      # Price series (required)
    entries,                    # Boolean Series - True = buy signal
    exits,                      # Boolean Series - True = sell signal
    init_cash=1_000_000,        # Starting capital
    fees=0.00111,               # Indian delivery equity (see indian-market-costs.md)
    fixed_fees=20,              # Rs 20 per order
    slippage=0.0005,            # 0.05% slippage
    size=0.75,                  # Position size
    size_type="percent",        # How to interpret size
    direction="longonly",       # longonly, shortonly, both
    freq="1D",                  # Data frequency
    min_size=1,                 # Minimum order size
    size_granularity=1,         # Round to whole shares
    sl_stop=0.05,               # 5% stop loss (optional)
    tp_stop=0.10,               # 10% take profit (optional)
    accumulate=False,           # True = allow pyramiding
)
```

## 2. from_orders (Order-Based) - Direct Orders

Provide explicit order arrays. Best for portfolio rebalancing and target-weight strategies.

```python
pf = vbt.Portfolio.from_orders(
    close=close,
    size=0.15,                  # Target 15% allocation
    size_type='targetpercent',  # Rebalances to target weight
    group_by=True,              # Group columns as one portfolio
    cash_sharing=True,          # Share cash across assets
    fees=0.00111, fixed_fees=20,
    init_cash=1_000_000,
    freq='1D',
    min_size=1,
    size_granularity=1,
)
```

## 3. from_order_func (Custom Callback) - Most Powerful

Numba-compiled functions called at each bar with full portfolio state access. Use for complex logic (e.g., dynamic position sizing based on portfolio state, multi-asset coordination). `flexible=True` allows multiple orders per symbol per bar.

## 4. from_holding (Buy-and-Hold Benchmark)

```python
pf_benchmark = vbt.Portfolio.from_holding(close, init_cash=1_000_000, fees=0.00111, freq="1D")
```

## Direction

| Direction | `direction=` | Behavior |
|-----------|-------------|----------|
| Long Only | `"longonly"` | Only buy and sell (default) |
| Short Only | `"shortonly"` | Only short and cover |
| Both | `"both"` | Can go long and short |

## Key Parameters Reference

| Parameter | Default | Description |
|-----------|---------|-------------|
| `init_cash` | 100 | Starting capital |
| `fees` | 0 | Transaction fee as decimal (0.001 = 0.1%) |
| `fixed_fees` | 0 | Flat fee per trade |
| `slippage` | 0 | Price slippage as decimal |
| `size` | np.inf | Position size |
| `size_type` | Amount | How to interpret size |
| `direction` | longonly | Trade direction |
| `freq` | auto | Data frequency (1D, 1H, 5T, etc.) |
| `accumulate` | False | Allow pyramiding |
| `sl_stop` | None | Stop loss (decimal, e.g. 0.05 = 5%) |
| `tp_stop` | None | Take profit (decimal) |
| `sl_trail` | None | Trailing stop (decimal) |
| `min_size` | 0 | Minimum order size |
| `size_granularity` | None | Round size to this increment |

## Random Signal Baseline

```python
pf_random = vbt.Portfolio.from_random_signals(close, n=50, init_cash=1_000_000, fees=0.00111, freq="1D")
```

## Save/Load Portfolio

```python
pf.save("my_backtest.pkl")
pf_loaded = vbt.Portfolio.load("my_backtest.pkl")
```

## When to Use Which Mode

| Use Case | Mode |
|----------|------|
| Technical indicator signals (EMA crossover, RSI, etc.) | `from_signals` |
| Portfolio rebalancing, target weights | `from_orders` |
| Complex multi-asset logic, dynamic sizing | `from_order_func` |
| Buy-and-hold benchmark | `from_holding` |
| Random baseline comparison | `from_random_signals` |
