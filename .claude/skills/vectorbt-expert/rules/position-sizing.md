---
name: position-sizing
description: Position sizing strategies in VectorBT - percent, value, amount, targetpercent
metadata:
  tags: position-sizing, size, percent, value, amount, risk-management
---

# Position Sizing

## Size Types

| SizeType | `size_type=` | `size=` meaning | Best For |
|----------|-------------|-----------------|----------|
| Amount | `"amount"` | Fixed number of shares | Simple testing |
| Value | `"value"` | Fixed cash amount per trade | Fixed exposure |
| Percent | `"percent"` | Fraction of current portfolio (0.5 = 50%) | Risk-adjusted trading |
| TargetPercent | `"targetpercent"` | Target portfolio weight (rebalances) | Portfolio allocation |
| TargetAmount | `"targetamount"` | Rebalance to target shares | Specific share targets |
| TargetValue | `"targetvalue"` | Rebalance to target dollar value | Specific value targets |

Default: `size=np.inf` with Amount = invest all available cash.

## Percent Sizing (Most Popular)

```python
pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    size=0.5,              # 50% of portfolio equity per trade
    size_type="percent",
    init_cash=1_000_000,
    fees=0.00111, fixed_fees=20,
    min_size=1,
    size_granularity=1,
    freq="1D"
)
```

## Value Sizing (Fixed Capital Per Trade)

```python
pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    size=200_000,          # Deploy 2L per trade
    size_type="value",
    init_cash=1_000_000,
    fees=0.00111, fixed_fees=20,
    min_size=1,
    size_granularity=1,
    freq="1D"
)
```

## Target Percent (Portfolio Rebalancing)

```python
pf = vbt.Portfolio.from_orders(
    close=close_panel,          # DataFrame with multiple asset columns
    size=target_weights,        # DataFrame of target weights (0.0-1.0)
    size_type="targetpercent",
    group_by=True,
    cash_sharing=True,
    fees=0.00111, fixed_fees=20,
    init_cash=1_000_000,
    freq="1D",
)
```

## Whole Shares Only (Realistic)

Always use `min_size=1` and `size_granularity=1` for equity backtesting to avoid fractional shares:

```python
pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    size=0.75,
    size_type="percent",
    min_size=1,             # Minimum 1 share
    size_granularity=1,     # Round to whole shares
    init_cash=1_000_000,
    freq="1D",
)
```

## Best Practices

- **Equity intraday/swing**: Use `percent` with 0.5-0.75 (50-75% deployment)
- **Futures**: Use `value` with lot-aware `min_size` and `size_granularity` (see [futures-backtesting](./futures-backtesting.md))
- **Multi-asset portfolio**: Use `targetpercent` with `cash_sharing=True`
- **Accumulation/pyramiding**: Use `accumulate=True` with smaller `percent` per entry
- Always set `min_size=1` and `size_granularity=1` for realistic equity simulation
