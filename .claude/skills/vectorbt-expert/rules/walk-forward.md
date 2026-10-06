---
name: walk-forward
description: Walk-forward analysis, in-sample/out-of-sample testing, and robustness validation for backtesting
metadata:
  tags: walk-forward, out-of-sample, validation, robustness, overfitting, train-test, anchored, rolling
---

# Walk-Forward Analysis

Walk-forward analysis prevents overfitting by optimizing on in-sample data and validating on unseen out-of-sample data. This is the gold standard for strategy validation.

## Why Walk-Forward Matters

A strategy that performs well on historical data but fails live is likely overfit. Walk-forward analysis simulates real-world conditions where you:
1. Optimize parameters on past data (in-sample)
2. Trade with those parameters on new data (out-of-sample)
3. Roll the window forward and repeat

If out-of-sample performance is consistently positive, the strategy has real edge.

## Simple Train/Test Split

The simplest form: split data into training (in-sample) and testing (out-of-sample):

```python
from openalgo import ta

# Split data: 70% train, 30% test
split_idx = int(len(close) * 0.7)
close_train = close.iloc[:split_idx]
close_test = close.iloc[split_idx:]

# Optimize on training data
best_return = -np.inf
best_params = {}

for fast in range(5, 30):
    for slow in range(20, 60):
        if fast >= slow:
            continue
        ema_f = ta.ema(close_train, fast)
        ema_s = ta.ema(close_train, slow)

        buy_raw = (ema_f > ema_s) & (ema_f.shift(1) <= ema_s.shift(1))
        sell_raw = (ema_f < ema_s) & (ema_f.shift(1) >= ema_s.shift(1))
        entries = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
        exits = ta.exrem(sell_raw.fillna(False), buy_raw.fillna(False))

        pf = vbt.Portfolio.from_signals(
            close_train, entries, exits,
            size=0.75, size_type="percent",
            fees=0.00111, fixed_fees=20,
            init_cash=1_000_000, freq="1D",
            min_size=1, size_granularity=1,
        )
        ret = pf.total_return()
        if ret > best_return:
            best_return = ret
            best_params = {'fast': fast, 'slow': slow}

print(f"Best in-sample params: {best_params}, Return: {best_return:.2%}")

# Validate on test data with best parameters
ema_f = ta.ema(close_test, best_params['fast'])
ema_s = ta.ema(close_test, best_params['slow'])

buy_raw = (ema_f > ema_s) & (ema_f.shift(1) <= ema_s.shift(1))
sell_raw = (ema_f < ema_s) & (ema_f.shift(1) >= ema_s.shift(1))
entries_test = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
exits_test = ta.exrem(sell_raw.fillna(False), buy_raw.fillna(False))

pf_test = vbt.Portfolio.from_signals(
    close_test, entries_test, exits_test,
    size=0.75, size_type="percent",
    fees=0.00111, fixed_fees=20,
    init_cash=1_000_000, freq="1D",
    min_size=1, size_granularity=1,
)
print(f"Out-of-sample return: {pf_test.total_return():.2%}")
print(f"Out-of-sample Sharpe: {pf_test.sharpe_ratio():.2f}")
```

## Rolling Walk-Forward

More rigorous: slide the optimization window forward in steps:

```python
from openalgo import ta

TRAIN_DAYS = 252 * 2    # 2 years training
TEST_DAYS = 63           # 3 months testing (1 quarter)
STEP_DAYS = 63           # Step forward by 1 quarter

oos_results = []
start = 0

while start + TRAIN_DAYS + TEST_DAYS <= len(close):
    train_slice = close.iloc[start:start + TRAIN_DAYS]
    test_slice = close.iloc[start + TRAIN_DAYS:start + TRAIN_DAYS + TEST_DAYS]

    # Optimize on training window
    best_return = -np.inf
    best_fast, best_slow = 10, 20

    for fast in range(5, 25):
        for slow in range(20, 50):
            if fast >= slow:
                continue
            ema_f = ta.ema(train_slice, fast)
            ema_s = ta.ema(train_slice, slow)

            buy_raw = (ema_f > ema_s) & (ema_f.shift(1) <= ema_s.shift(1))
            sell_raw = (ema_f < ema_s) & (ema_f.shift(1) >= ema_s.shift(1))
            entries = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
            exits = ta.exrem(sell_raw.fillna(False), buy_raw.fillna(False))

            pf = vbt.Portfolio.from_signals(
                train_slice, entries, exits,
                size=0.75, size_type="percent",
                fees=0.00111, fixed_fees=20,
                init_cash=1_000_000, freq="1D",
                min_size=1, size_granularity=1,
            )
            ret = pf.total_return()
            if ret > best_return:
                best_return = ret
                best_fast, best_slow = fast, slow

    # Test on out-of-sample window
    ema_f = ta.ema(test_slice, best_fast)
    ema_s = ta.ema(test_slice, best_slow)

    buy_raw = (ema_f > ema_s) & (ema_f.shift(1) <= ema_s.shift(1))
    sell_raw = (ema_f < ema_s) & (ema_f.shift(1) >= ema_s.shift(1))
    entries_t = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
    exits_t = ta.exrem(sell_raw.fillna(False), buy_raw.fillna(False))

    pf_t = vbt.Portfolio.from_signals(
        test_slice, entries_t, exits_t,
        size=0.75, size_type="percent",
        fees=0.00111, fixed_fees=20,
        init_cash=1_000_000, freq="1D",
        min_size=1, size_granularity=1,
    )

    oos_results.append({
        'window_start': train_slice.index[0],
        'test_start': test_slice.index[0],
        'test_end': test_slice.index[-1],
        'best_fast': best_fast,
        'best_slow': best_slow,
        'in_sample_return': best_return,
        'oos_return': pf_t.total_return(),
        'oos_sharpe': pf_t.sharpe_ratio(),
        'oos_max_dd': pf_t.max_drawdown(),
    })

    start += STEP_DAYS

results_df = pd.DataFrame(oos_results)
print(results_df.to_string(index=False))
print(f"\nAvg OOS Return: {results_df['oos_return'].mean():.2%}")
print(f"OOS Win Rate: {(results_df['oos_return'] > 0).mean():.0%}")
```

## Walk-Forward Efficiency Ratio

The WFE measures how much in-sample performance carries to out-of-sample:

```python
wfe = results_df['oos_return'].mean() / results_df['in_sample_return'].mean()
print(f"Walk-Forward Efficiency: {wfe:.2%}")
# > 50% is acceptable, > 70% is good
```

## Anchored Walk-Forward

Training window always starts from the beginning (grows over time):

```python
# Same as rolling, but change:
# train_slice = close.iloc[0:start + TRAIN_DAYS]  # Anchored: always from day 0
# This gives more training data in later windows
```

## Best Practices

- **Minimum 2 years** of in-sample data for daily strategies
- **Minimum 3 months** of out-of-sample per window
- **At least 5 walk-forward windows** for statistical significance
- **Consistent OOS performance** matters more than high IS performance
- If IS return is 50% but OOS is -5%, the strategy is overfit
- Use Sharpe ratio for optimization objective, not total return (more stable)
- Always include realistic transaction costs (see [indian-market-costs](./indian-market-costs.md))
- Track parameter stability: if optimal params change wildly each window, strategy is fragile (see [pitfalls](./pitfalls.md))

## Template

See [assets/walk_forward/template.py](./assets/walk_forward/template.py) for a complete production-ready walk-forward script.
