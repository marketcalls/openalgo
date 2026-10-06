# Custom Indicators — Building with NumPy + openalgo Primitives

## Architecture

Since openalgo 2.0, all built-in indicators run in a compiled Rust core. Custom indicators get the same speed by composition:

1. **Core computation**: vectorized NumPy that composes openalgo `ta` primitives (`ta.sma`, `ta.stdev`, `ta.bbands`, ... — all Rust-backed, all O(n))
2. **Public wrapper**: a plain Python function that handles pandas Series / numpy / list inputs and preserves the index
3. **No JIT, no warmup**: there is nothing to compile — the first call runs at full speed

---

## Template: Simple Custom Indicator

```python
import numpy as np
import pandas as pd
from openalgo import ta


def _compute_zscore(arr: np.ndarray, period: int) -> np.ndarray:
    """Z-Score: (value - mean) / stdev over rolling period. Fully vectorized."""
    mean = ta.sma(arr, period)      # Rust core
    std = ta.stdev(arr, period)     # Rust core

    z = np.full(len(arr), np.nan)
    valid = ~np.isnan(mean) & ~np.isnan(std)
    nonzero = valid & (std > 0)
    z[nonzero] = (arr[nonzero] - mean[nonzero]) / std[nonzero]
    z[valid & (std == 0)] = 0.0
    return z


def zscore(data, period=20):
    """Z-Score indicator with pandas/numpy support."""
    if isinstance(data, pd.Series):
        idx = data.index
        result = _compute_zscore(data.values.astype(np.float64), period)
        return pd.Series(result, index=idx, name=f"ZScore({period})")
    return _compute_zscore(np.asarray(data, dtype=np.float64), period)
```

---

## Template: Multi-Output Custom Indicator

Squeeze Momentum — Bollinger Bands inside Keltner Channel means volatility is compressed. With `ta` primitives this is a few lines:

```python
import numpy as np
from openalgo import ta


def squeeze(high, low, close,
            bb_period=20, bb_mult=2.0,
            kc_period=20, kc_atr=10, kc_mult=1.5):
    """Squeeze Momentum: returns (squeeze_on, momentum).

    squeeze_on: boolean array — True while BB is inside KC (volatility compressed)
    momentum:   distance of close from the midpoint of the recent range
    """
    bb_upper, bb_mid, bb_lower = ta.bbands(close, bb_period, bb_mult)
    kc_upper, kc_mid, kc_lower = ta.keltner(high, low, close, kc_period, kc_atr, kc_mult)

    squeeze_on = (bb_upper < kc_upper) & (bb_lower > kc_lower)

    # Momentum: close vs midpoint of (highest high + lowest low + sma) / range midline
    hh = ta.highest(high, kc_period)
    ll = ta.lowest(low, kc_period)
    midline = (hh + ll) / 2.0
    momentum = np.asarray(close, dtype=np.float64) - (midline + bb_mid) / 2.0

    return squeeze_on, momentum
```

---

## NumPy Rules (MUST FOLLOW)

### DO
- **Compose from `ta` primitives first** — they run in the Rust core and are O(n)
- Use `np.full(n, np.nan)` to initialize output arrays
- Vectorize with array expressions, `np.where`, and boolean masks
- Guard divisions with masks or `np.errstate(invalid="ignore", divide="ignore")`
- Respect the NaN warm-up that primitives emit (mask on `~np.isnan(...)`)
- Return float64 numpy arrays from core functions

### DO NOT
- Never reimplement an indicator that already exists in `openalgo.ta` (100+ available)
- Never write per-bar Python loops over large arrays when a vectorized form exists
- Never divide by a rolling value without masking zeros/NaN
- Never drop the warm-up NaNs silently — downstream signal code must see them

### Path-Dependent Indicators

Some indicators carry sequential state (each bar depends on the previous output). Before writing a loop, check whether a primitive already provides the recursion: `ta.ema` (exponential), `ta.atr` (Wilder), `ta.supertrend` (band-flip logic), `ta.sar`. If the recursion is genuinely custom, a plain Python loop still works — keep it O(n), operate on float64 numpy arrays, and note that it will be slower than vectorized code on very large inputs.

### NaN Handling Pattern

```python
def my_indicator(arr: np.ndarray, period: int) -> np.ndarray:
    base = ta.sma(arr, period)              # NaN for the first period-1 bars
    out = np.full(len(arr), np.nan)
    m = ~np.isnan(base)                     # only compute where inputs are valid
    out[m] = arr[m] - base[m]
    return out
```

---

## Using openalgo Primitives as Building Blocks

All public `ta` methods accept numpy/pandas/list and run in the Rust core:

```python
from openalgo import ta

# Rolling math:    ta.sma, ta.ema, ta.wma, ta.stdev, ta.highest, ta.lowest
# Price action:    ta.true_range, ta.atr, ta.change, ta.roc
# Bands/channels:  ta.bbands, ta.keltner, ta.donchian
# Signals:         ta.crossover, ta.crossunder, ta.exrem, ta.rising, ta.falling


def my_channel(high, low, close, period=20):
    """Custom channel composed entirely from Rust-core primitives."""
    upper = ta.highest(high, period)
    lower = ta.lowest(low, period)
    mid = ta.sma(close, period)
    width = np.where(mid != 0, (upper - lower) / mid * 100.0, np.nan)
    return upper, mid, lower, width
```

---

## Performance Tips

1. **Compose from primitives**: every `ta` call is Rust — chaining a few primitives beats hand-written Python every time
2. **Pre-compute shared arrays**: if multiple outputs need the same rolling value, compute it once
3. **Vectorize**: one array expression over 500k bars is fast; 500k loop iterations in Python are not
4. **No warmup needed**: benchmark directly — there is no JIT compile on the first call
5. **Test with large arrays**: always benchmark on 100k+ bars to verify O(n) scaling

```python
# Benchmark pattern
import time
import numpy as np

data = np.random.randn(500_000).cumsum() + 1000
t0 = time.perf_counter()
_ = my_indicator(data, 20)
elapsed = (time.perf_counter() - t0) * 1000
print(f"my_indicator(500k bars): {elapsed:.2f}ms")
```
