---
name: long-short-trading
description: Long and short backtesting - simultaneous directions, comparison, short_entries/short_exits
metadata:
  tags: long, short, both, direction, short_entries, short_exits, comparison
---

# Long + Short Backtesting

## Simultaneous Long and Short

Use `short_entries` and `short_exits` for simultaneous long/short:

```python
pf_both = vbt.Portfolio.from_signals(
    close,
    entries=entries_long,
    exits=exits_long,
    short_entries=entries_short,
    short_exits=exits_short,
    init_cash=30_00_000,
    size=20_00_000,
    size_type="value",
    fees=0.0003,
    min_size=lot_size,
    size_granularity=lot_size,
    freq="1h",
)
# Note: direction="both" is ignored when short_entries/short_exits are provided
```

## Compare Long-Only vs Short-Only vs Both

```python
common_kwargs = dict(
    init_cash=1_000_000,
    size=500_000,
    size_type="value",
    fees=0.00022,
    freq="5min",
)

EMPTY = pd.Series(False, index=close.index)

pf_long = vbt.Portfolio.from_signals(close, entries=LE, exits=LX,
                                      direction="longonly", **common_kwargs)
pf_short = vbt.Portfolio.from_signals(close, short_entries=SE, short_exits=SX,
                                       direction="shortonly", **common_kwargs)
pf_both = vbt.Portfolio.from_signals(close, entries=LE, exits=LX,
                                      short_entries=SE, short_exits=SX, **common_kwargs)

# Side-by-side comparison
stats = pd.concat([
    pf_long.stats().to_frame("Long Only"),
    pf_short.stats().to_frame("Short Only"),
    pf_both.stats().to_frame("Both"),
], axis=1)
print(stats)
```

## Best Practices

- Test long-only first before adding short side
- Short strategies need separate signal logic (not just inverted long signals)
- For Indian equities, shorting is only available intraday (MIS/CO product types)
- Futures/options can be shorted for positional trades
- When comparing, always use `common_kwargs` to ensure identical conditions
