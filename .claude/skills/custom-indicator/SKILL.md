---
name: custom-indicator
description: Create a custom technical indicator using vectorized NumPy on top of openalgo's Rust-core ta primitives. Generates production-grade, O(n) indicator functions with charting and benchmarking.
argument-hint: "[indicator-name]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

Create a custom technical indicator by composing openalgo's Rust-core `ta` primitives with vectorized NumPy.

## Arguments

- `$0` = indicator name (e.g., zscore, squeeze, vwap-bands, custom-rsi, mean-reversion). Required.

If no arguments, ask the user what indicator they want to build.

## Instructions

1. Read the indicator-expert rules, especially:
   - `rules/custom-indicators.md` — NumPy + ta-primitive patterns and templates
   - `rules/performance.md` — Rust core performance, O(n) guarantees, benchmarking
   - `rules/indicator-catalog.md` — Check if indicator already exists in openalgo.ta
2. **Check first**: If the indicator already exists in `openalgo.ta` (100+ indicators), tell the user and show the existing API
3. Create `custom_indicators/{indicator_name}/` directory (on-demand)
4. Create `{indicator_name}.py` with:

### File Structure

```python
"""
{Indicator Name} — Custom Indicator
Description: {what it measures}
Category: {trend/momentum/volatility/volume/oscillator}
"""
import numpy as np
import pandas as pd
from openalgo import ta

# --- Core Computation (vectorized NumPy on ta primitives) ---
def _compute_{name}(arr: np.ndarray, period: int) -> np.ndarray:
    """Vectorized core computation built on Rust-core primitives."""
    n = len(arr)
    result = np.full(n, np.nan)
    # Compose from ta primitives (they run in Rust):
    # mean = ta.sma(arr, period); std = ta.stdev(arr, period); ...
    # then combine with NumPy array math (np.where, masks)
    return result

# --- Public API ---
def {name}(data, period=20):
    """
    {Indicator Name}

    Args:
        data: Close prices (numpy array, pandas Series, or list)
        period: Lookback period (default: 20)

    Returns:
        Same type as input with indicator values
    """
    if isinstance(data, pd.Series):
        idx = data.index
        result = _compute_{name}(data.values.astype(np.float64), period)
        return pd.Series(result, index=idx, name="{Name}({period})")
    arr = np.asarray(data, dtype=np.float64)
    return _compute_{name}(arr, period)
```

5. Create `chart.py` for visualization:

```python
"""Chart the custom indicator with Plotly."""
import os
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import find_dotenv, load_dotenv
from openalgo import api, ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from {indicator_name} import {name}

# ... fetch data, compute indicator, create chart ...
```

6. Create `benchmark.py` for performance testing (no warmup needed — the Rust core runs at full speed from the first call):

```python
"""Benchmark the custom indicator."""
import numpy as np
import time
from {indicator_name} import {name}

for size in [10_000, 100_000, 500_000]:
    data = np.random.randn(size).cumsum() + 1000
    t0 = time.perf_counter()
    _ = {name}(data, 20)
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"{size:>10,} bars: {elapsed:>8.2f}ms")
```

## NumPy Rules (CRITICAL)

### MUST DO
- Compose from `ta` primitives wherever possible — they run in the Rust core
- `np.full(n, np.nan)` to initialize output arrays
- Vectorize with array expressions, `np.where`, and boolean masks
- Guard divisions: `np.errstate(invalid="ignore", divide="ignore")` plus a safe denominator mask
- Respect NaN warm-up periods from the primitives (mask on `~np.isnan(...)`)
- Float64 for all numeric arrays
- O(n) algorithms only

### MUST NOT
- Never reimplement an indicator that already exists in `openalgo.ta`
- Never write per-bar Python loops over large arrays — vectorize instead
- Never divide without masking zero/NaN denominators
- If the indicator is genuinely path-dependent (sequential state no primitive covers), check whether `ta.ema` / Wilder-style primitives already provide the recursion first; a plain Python loop is a last resort — keep it O(n) and document the trade-off

### Available Building Blocks

Public `ta` methods that run in the Rust core:

```python
from openalgo import ta

# Rolling math:    ta.sma, ta.ema, ta.wma, ta.stdev, ta.highest, ta.lowest
# Price action:    ta.true_range, ta.atr, ta.change, ta.roc
# Bands/channels:  ta.bbands, ta.keltner, ta.donchian
# Signals:         ta.crossover, ta.crossunder, ta.exrem, ta.rising, ta.falling
```

## Common Custom Indicator Patterns

| Pattern | Implementation |
|---------|---------------|
| Z-Score | `(value - rolling_mean) / rolling_stdev` |
| Squeeze | Bollinger inside Keltner channel |
| VWAP Bands | VWAP + N * rolling stdev of (close - vwap) |
| Momentum Score | Weighted sum of RSI + MACD + ADX conditions |
| Mean Reversion | Distance from SMA as % + threshold |
| Range Filter | ATR-based dynamic filter on close |
| Trend Strength | ADX + directional movement composite |

## Example Usage

`/custom-indicator zscore`
`/custom-indicator squeeze-momentum`
`/custom-indicator vwap-bands`
`/custom-indicator range-filter`
