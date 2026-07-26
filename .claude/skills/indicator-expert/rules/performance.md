# Performance — The Rust Core (openalgo 2.x)

## How Indicators Are Computed

Since openalgo 2.0, every indicator kernel runs in a **compiled Rust core**
(`openalgo._oaindicators`, built with PyO3) that ships inside the wheel:

- `pip install openalgo` is all you need — indicators are built in, no optional
  extra, no separate install step
- Numba and llvmlite are **gone** — they are not dependencies and are never used
- No JIT compilation, no warmup, no compile cache — the first call runs at full speed
- abi3 wheels support **Python 3.12, 3.13, and 3.14** (openalgo 2.x requires Python >= 3.12)
- Dependencies are just: `numpy>=2.0`, `pandas>=2.2`, `httpx`, `websocket-client`

```python
from openalgo import ta
import numpy as np

close = np.random.randn(1_000_000).cumsum() + 1000
ema = ta.ema(close, 20)   # first call — already full Rust speed, no warmup
```

## What Changed vs openalgo 1.x (Numba era)

| openalgo 1.x (Numba) | openalgo 2.x (Rust) |
|----------------------|---------------------|
| `pip install openalgo[indicators]` extra | Plain `pip install openalgo` |
| First call triggered JIT compile (100-500ms) | No compilation — first call is full speed |
| `.nbi`/`.nbc` cache files in `__pycache__/` | No cache files to manage or clear |
| Warmup patterns (`_warmup()`, tiny-array pre-calls) | Not needed; `_warmup()` is now a no-op |
| Blocked on new Python/NumPy versions | Python 3.12 / 3.13 / 3.14, NumPy 2.x |
| `@njit` custom-indicator templates | Vectorized NumPy + `ta` primitives (see custom-indicators.md) |

Legacy imports like `from openalgo.numba_shim import jit` still work — the shim
returns the function unchanged — but nothing is compiled, so do not write new
code against it.

## Speed Guarantees

- **Every indicator is O(n)** — rolling sums, Wilder/EMA recursions, and
  monotonic-deque extrema are implemented in Rust
- Benchmarked head-to-head against TA-Lib on 924k bars: the
  regression/statistics family (`linreg`, `tsf`, `stdev`, `cci`, `macd`, ...)
  runs **faster than TA-Lib**; the rest are on par
- Reference: [TA-Lib performance comparison](https://github.com/marketcalls/openalgo-python-library/blob/master/benchmark/TALIB_PERF_COMPARE.md)
  and [TA-Lib compatibility notes](https://github.com/marketcalls/openalgo-python-library/blob/master/docs/TALIB_COMPATIBILITY.md)

## NumPy Fallback

If the compiled extension is unavailable (e.g., running from a source checkout
without a built wheel), a pure-NumPy fallback in
`openalgo/indicators/_backend.py` computes the **same values**. Installed
wheels always include the Rust core, so user environments never hit the
fallback. Neither path depends on numba.

## Getting the Most Out of It

1. **Pass numpy arrays or pandas Series** — lists are accepted but get converted
   on every call; keep data as float64 arrays in hot paths
2. **Compute once, reuse** — if several charts/signals need `ta.atr(h, l, c, 14)`,
   compute it once and pass it around
3. **Compose custom indicators from `ta` primitives** — `ta.sma`, `ta.ema`,
   `ta.stdev`, `ta.highest`, `ta.lowest`, `ta.true_range` all run in Rust;
   building on them keeps custom code fast (see custom-indicators.md)
4. **Vectorize custom math with NumPy** — avoid per-bar Python loops on large
   arrays; use array expressions, `np.where`, and boolean masks
5. **Input/output types match** — pass a pandas Series, get a Series back with
   the same index; pass numpy, get numpy

## Benchmark Pattern

No warmup call needed — measure directly:

```python
import time
import numpy as np
from openalgo import ta

for size in [100_000, 500_000, 1_000_000]:
    data = np.random.randn(size).cumsum() + 1000
    t0 = time.perf_counter()
    _ = ta.rsi(data, 14)
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"rsi({size:>10,} bars): {elapsed:>8.2f}ms")
```

## Algorithm Complexity (for custom code)

When writing your own indicator math, keep it O(n):

| Pattern | Complexity | Approach |
|---------|------------|----------|
| Rolling sum/mean | O(n) | `np.cumsum` difference, or `ta.sma` |
| Rolling stdev | O(n) | cumsum of x and x^2, or `ta.stdev` |
| EMA/Wilder recursion | O(n) | `ta.ema` / built-in primitives (Rust) |
| Rolling max/min | O(n) | `ta.highest` / `ta.lowest` (deque-based, in Rust) |
| Per-bar window slice | O(n x period) | Avoid: `data[i-period:i].max()` in a loop |
