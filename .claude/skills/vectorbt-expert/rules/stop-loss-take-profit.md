---
name: stop-loss-take-profit
description: Stop loss, take profit, and trailing stop configurations in VectorBT
metadata:
  tags: stop-loss, take-profit, trailing-stop, risk-management, sl, tp
---

# Stop Loss & Take Profit

## Fixed Stop Loss + Take Profit

```python
pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    sl_stop=0.05,     # Exit if price drops 5% from entry
    tp_stop=0.10,     # Exit if price rises 10% from entry
    init_cash=1_000_000,
    fees=0.00111, fixed_fees=20,
    freq="1D"
)
```

## Trailing Stop Loss

Follows price up, exits on pullback from the highest price since entry:

```python
pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    sl_trail=0.05,    # 5% trailing stop from peak
    init_cash=1_000_000,
    fees=0.00111, fixed_fees=20,
    freq="1D",
)
```

## Combined: Trailing Stop + Take Profit

```python
pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    sl_trail=0.03,    # 3% trailing stop
    tp_stop=0.10,     # 10% take profit
    init_cash=1_000_000,
    fees=0.00111, fixed_fees=20,
    freq="1D",
)
```

## Stop Loss Variations Summary

| Parameter | Behavior |
|-----------|----------|
| `sl_stop=0.05` | Fixed 5% stop from entry price |
| `tp_stop=0.10` | Fixed 10% target from entry price |
| `sl_trail=0.03` | 3% trailing from highest price since entry |

## Best Practices

- Start with no stops, then add them to see impact on strategy performance
- Trailing stops work best in trending markets; fixed SL works better in mean-reverting markets
- Always test stop-loss levels via parameter optimization (see [parameter-optimization](./parameter-optimization.md))
- For intraday strategies, use tighter stops (1-2%); for positional, wider (5-10%)
- Stops are evaluated on `close` prices by default, not intrabar highs/lows
