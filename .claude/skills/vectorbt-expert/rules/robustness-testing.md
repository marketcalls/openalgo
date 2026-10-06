---
name: robustness-testing
description: Comprehensive robustness testing - Monte Carlo, noise test, parameter sensitivity, entry/exit delay, cross-symbol validation
metadata:
  tags: robustness, monte-carlo, noise-test, sensitivity, validation, stress-test, overfitting
---

# Robustness Testing

Robustness testing is a set of stress tests to validate or break an algorithmic trading strategy BEFORE risking real capital. No single test is sufficient - use multiple tests together.

## 1. Monte Carlo Simulation (Trade Shuffling)

Randomize trade sequence to estimate confidence intervals on drawdown and returns:

```python
import numpy as np
import pandas as pd

def monte_carlo_trades(pf, n_simulations=1000, seed=42):
    """Shuffle trade P&L to estimate worst-case drawdown and return distribution."""
    rng = np.random.default_rng(seed)
    trades = pf.trades.records_readable
    if len(trades) == 0:
        return None

    trade_pnl = (trades['Exit Price'] - trades['Entry Price']) * trades['Size']
    trade_returns = trade_pnl.values

    sim_final_returns = []
    sim_max_drawdowns = []

    for _ in range(n_simulations):
        shuffled = rng.permutation(trade_returns)
        equity = np.cumsum(shuffled) + pf.init_cash
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / peak
        sim_final_returns.append((equity[-1] / pf.init_cash) - 1)
        sim_max_drawdowns.append(drawdown.min())

    results = pd.DataFrame({
        'final_return': sim_final_returns,
        'max_drawdown': sim_max_drawdowns,
    })

    print(f"Monte Carlo ({n_simulations} simulations)")
    print(f"  Return - Mean: {results['final_return'].mean():.2%}, "
          f"5th pctl: {results['final_return'].quantile(0.05):.2%}, "
          f"95th pctl: {results['final_return'].quantile(0.95):.2%}")
    print(f"  Max DD - Mean: {results['max_drawdown'].mean():.2%}, "
          f"Worst 5%: {results['max_drawdown'].quantile(0.05):.2%}")
    return results
```

**What it tells you:** If the 5th percentile return is still positive, the strategy has edge regardless of trade ordering. If max drawdown in the worst 5% is -40%, you must be prepared for that.

## 2. Noise Test (Price Perturbation)

Add random noise to price data and re-run the strategy. If results collapse, the strategy was fit to specific price noise:

```python
from openalgo import ta

def noise_test(close, high, low, run_strategy_fn, n_tests=100, noise_pct=0.001, seed=42):
    """Re-run strategy with slightly perturbed price data."""
    rng = np.random.default_rng(seed)
    base_result = run_strategy_fn(close, high, low)
    noise_results = []

    for i in range(n_tests):
        noise_c = close * (1 + rng.normal(0, noise_pct, len(close)))
        noise_h = high * (1 + rng.normal(0, noise_pct, len(high)))
        noise_l = low * (1 + rng.normal(0, noise_pct, len(low)))
        # Ensure high >= close >= low
        noise_h = np.maximum(noise_h, noise_c)
        noise_l = np.minimum(noise_l, noise_c)

        result = run_strategy_fn(noise_c, noise_h, noise_l)
        noise_results.append(result)

    results_df = pd.DataFrame(noise_results)
    pct_profitable = (results_df['total_return'] > 0).mean()
    print(f"Noise Test ({n_tests} runs, noise={noise_pct*100:.1f}%)")
    print(f"  % Profitable: {pct_profitable:.0%}")
    print(f"  Avg Return: {results_df['total_return'].mean():.2%}")
    print(f"  Original Return: {base_result['total_return']:.2%}")
    return results_df

# Example: Define strategy function that returns metrics dict
def run_ema_strategy(close_series, high_series, low_series):
    close_s = pd.Series(close_series, index=close.index) if not isinstance(close_series, pd.Series) else close_series
    ema_f = ta.ema(close_s, 10)
    ema_s = ta.ema(close_s, 20)
    buy_raw = (ema_f > ema_s) & (ema_f.shift(1) <= ema_s.shift(1))
    sell_raw = (ema_f < ema_s) & (ema_f.shift(1) >= ema_s.shift(1))
    entries = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
    exits = ta.exrem(sell_raw.fillna(False), buy_raw.fillna(False))
    pf = vbt.Portfolio.from_signals(
        close_s, entries, exits,
        size=0.75, size_type="percent",
        fees=0.00111, fixed_fees=20,
        init_cash=1_000_000, freq="1D",
        min_size=1, size_granularity=1,
    )
    return {
        'total_return': pf.total_return(),
        'sharpe': pf.sharpe_ratio(),
        'max_dd': pf.max_drawdown(),
    }
```

**What it tells you:** If >70% of noise-perturbed runs are profitable, the strategy captures real signal, not noise.

## 3. Parameter Sensitivity (Neighbor Test)

Test parameters near the optimal values. Robust strategies have broad profitable regions:

```python
from openalgo import ta

def parameter_sensitivity(close, best_fast, best_slow, delta=3):
    """Test parameters in a neighborhood around optimal values."""
    results = []
    for fast in range(best_fast - delta, best_fast + delta + 1):
        for slow in range(best_slow - delta, best_slow + delta + 1):
            if fast >= slow or fast < 2:
                continue
            ema_f = ta.ema(close, fast)
            ema_s = ta.ema(close, slow)
            buy_raw = (ema_f > ema_s) & (ema_f.shift(1) <= ema_s.shift(1))
            sell_raw = (ema_f < ema_s) & (ema_f.shift(1) >= ema_s.shift(1))
            entries = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
            exits = ta.exrem(sell_raw.fillna(False), buy_raw.fillna(False))
            pf = vbt.Portfolio.from_signals(
                close, entries, exits,
                size=0.75, size_type="percent",
                fees=0.00111, fixed_fees=20,
                init_cash=1_000_000, freq="1D",
                min_size=1, size_granularity=1,
            )
            results.append({
                'fast': fast, 'slow': slow,
                'return': pf.total_return(),
                'sharpe': pf.sharpe_ratio(),
            })

    df = pd.DataFrame(results)
    pct_profitable = (df['return'] > 0).mean()
    print(f"Parameter Sensitivity (delta={delta})")
    print(f"  Neighbors tested: {len(df)}")
    print(f"  % Profitable: {pct_profitable:.0%}")
    print(f"  Avg Return: {df['return'].mean():.2%}")
    print(f"  Min Return: {df['return'].min():.2%}")
    return df
```

**What it tells you:** If >80% of neighboring parameters are profitable, the strategy is robust. If only the exact parameters work, it is overfit.

## 4. Entry/Exit Delay Test

Delay entries and/or exits by 1-3 bars. Robust strategies survive small timing changes:

```python
def delay_test(close, entries, exits, max_delay=3):
    """Test strategy with delayed entries and exits."""
    results = []
    for entry_delay in range(0, max_delay + 1):
        for exit_delay in range(0, max_delay + 1):
            delayed_entries = entries.shift(entry_delay).fillna(False).astype(bool)
            delayed_exits = exits.shift(exit_delay).fillna(False).astype(bool)

            pf = vbt.Portfolio.from_signals(
                close, delayed_entries, delayed_exits,
                size=0.75, size_type="percent",
                fees=0.00111, fixed_fees=20,
                init_cash=1_000_000, freq="1D",
                min_size=1, size_granularity=1,
            )
            results.append({
                'entry_delay': entry_delay,
                'exit_delay': exit_delay,
                'total_return': pf.total_return(),
                'sharpe': pf.sharpe_ratio(),
                'max_dd': pf.max_drawdown(),
            })

    df = pd.DataFrame(results)
    pct_profitable = (df['total_return'] > 0).mean()
    print(f"Entry/Exit Delay Test (max_delay={max_delay})")
    print(f"  Combinations tested: {len(df)}")
    print(f"  % Profitable: {pct_profitable:.0%}")
    for _, row in df.iterrows():
        print(f"  Entry+{int(row['entry_delay'])}, Exit+{int(row['exit_delay'])}: "
              f"Return={row['total_return']:.2%}, Sharpe={row['sharpe']:.2f}")
    return df
```

**What it tells you:** If a 1-bar delay destroys the strategy, it depends on exact timing that is unreliable in live trading.

## 5. Cross-Symbol Validation

Test the same strategy logic on multiple symbols. True edge works across instruments:

```python
def cross_symbol_test(symbols, exchange, strategy_fn):
    """Test strategy across multiple symbols."""
    results = []
    for symbol in symbols:
        df = client.history(symbol=symbol, exchange=exchange, interval="D",
                           start_date=start_date, end_date=end_date)
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        if df.index.tz is not None:
            df.index = df.index.tz_convert(None)

        metrics = strategy_fn(df['close'], df['high'], df['low'])
        metrics['symbol'] = symbol
        results.append(metrics)

    df = pd.DataFrame(results)
    pct_profitable = (df['total_return'] > 0).mean()
    print(f"Cross-Symbol Test ({len(symbols)} symbols)")
    print(f"  % Profitable: {pct_profitable:.0%}")
    print(f"  Avg Return: {df['total_return'].mean():.2%}")
    print(df[['symbol', 'total_return', 'sharpe', 'max_dd']].to_string(index=False))
    return df

# Example usage
symbols = ["RELIANCE", "HDFCBANK", "INFY", "TCS", "SBIN", "ICICIBANK", "WIPRO", "TATAMOTORS"]
cross_symbol_test(symbols, "NSE", run_ema_strategy)
```

**What it tells you:** If the strategy is profitable on >60% of symbols, it has genuine edge.

## 6. Time Period Stability

Test the strategy on different historical periods:

```python
def period_stability_test(close, high, low, strategy_fn, window_years=2):
    """Test strategy across rolling multi-year windows."""
    results = []
    start = close.index[0]
    end = close.index[-1]
    window = pd.DateOffset(years=window_years)
    step = pd.DateOffset(months=6)
    current = start

    while current + window <= end:
        window_end = current + window
        mask = (close.index >= current) & (close.index < window_end)
        c = close[mask]
        h = high[mask]
        l = low[mask]
        if len(c) < 100:
            current += step
            continue
        metrics = strategy_fn(c, h, l)
        metrics['period_start'] = current.strftime('%Y-%m-%d')
        metrics['period_end'] = window_end.strftime('%Y-%m-%d')
        results.append(metrics)
        current += step

    df = pd.DataFrame(results)
    pct_profitable = (df['total_return'] > 0).mean()
    print(f"Period Stability ({window_years}Y rolling windows)")
    print(f"  Windows tested: {len(df)}")
    print(f"  % Profitable: {pct_profitable:.0%}")
    print(df[['period_start', 'period_end', 'total_return', 'sharpe']].to_string(index=False))
    return df
```

## Robustness Scorecard

Run all tests and generate a pass/fail summary:

```python
def robustness_scorecard(results_dict):
    """Print pass/fail scorecard for robustness tests."""
    thresholds = {
        'monte_carlo_5pctl_positive': ('Monte Carlo 5th pctl > 0', True),
        'noise_pct_profitable_70': ('Noise Test >70% profitable', True),
        'param_sensitivity_80': ('Param Sensitivity >80% profitable', True),
        'delay_test_profitable': ('Delay Test: 0/1 delay profitable', True),
        'cross_symbol_60': ('Cross-Symbol >60% profitable', True),
        'period_stability_70': ('Period Stability >70% profitable', True),
    }

    print("\n=== ROBUSTNESS SCORECARD ===")
    passed = 0
    total = len(results_dict)
    for key, (label, expected) in thresholds.items():
        result = results_dict.get(key, False)
        status = "PASS" if result == expected else "FAIL"
        if result == expected:
            passed += 1
        print(f"  [{status}] {label}")
    print(f"\nScore: {passed}/{total}")
    if passed >= total * 0.8:
        print("Strategy is ROBUST - suitable for live trading consideration")
    elif passed >= total * 0.5:
        print("Strategy has MODERATE robustness - proceed with caution")
    else:
        print("Strategy FAILS robustness - do NOT trade live")
```

## Best Practices

- Run ALL tests, not just the ones that confirm your bias
- A strategy that passes 5/6 tests is far better than one that passes 1/6
- Monte Carlo gives confidence intervals; noise test confirms real signal; parameter sensitivity checks stability
- The entry/exit delay test catches strategies that depend on exact execution (unreliable live)
- Cross-symbol validation is the strongest test of genuine edge
- Never skip transaction costs in robustness tests (see [indian-market-costs](./indian-market-costs.md))
