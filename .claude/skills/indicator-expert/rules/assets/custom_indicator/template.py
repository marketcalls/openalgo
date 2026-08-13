"""
Custom Indicator Template — Z-Score Example
Demonstrates the pattern for building custom indicators on top of openalgo's
Rust-core primitives (openalgo.ta) with vectorized NumPy.

No JIT, no warmup: openalgo 2.x computes ta primitives in a compiled Rust core,
so the first call already runs at full speed.

Usage:
    from zscore_indicator import zscore
    result = zscore(close_prices, period=20)
"""
import numpy as np
import pandas as pd
from openalgo import ta


# =============================================================================
# Core Computation — vectorized NumPy on Rust-core primitives
# =============================================================================

def _compute_zscore(arr: np.ndarray, period: int) -> np.ndarray:
    """
    Z-Score: (value - rolling_mean) / rolling_stdev

    Measures how many standard deviations the current value is from the mean.
    - Z > 2: Extremely high (potential overbought)
    - Z > 1: Above average
    - Z ~ 0: At average
    - Z < -1: Below average
    - Z < -2: Extremely low (potential oversold)

    Complexity: O(n) — ta.sma and ta.stdev run in the Rust core.
    """
    n = len(arr)
    result = np.full(n, np.nan)
    if period < 2 or n < period:
        return result

    mean = ta.sma(arr, period)
    std = ta.stdev(arr, period)

    valid = ~np.isnan(mean) & ~np.isnan(std)
    nonzero = valid & (std > 0)
    result[nonzero] = (arr[nonzero] - mean[nonzero]) / std[nonzero]
    result[valid & (std == 0)] = 0.0
    return result


def _compute_zscore_bands(arr: np.ndarray, period: int,
                          upper_threshold: float,
                          lower_threshold: float):
    """
    Z-Score with upper/lower price bands for signal generation.
    Returns: (zscore, upper_band, lower_band, mean_line)
    """
    n = len(arr)
    zscore_vals = np.full(n, np.nan)
    upper_band = np.full(n, np.nan)
    lower_band = np.full(n, np.nan)
    mean_line = np.full(n, np.nan)
    if period < 2 or n < period:
        return zscore_vals, upper_band, lower_band, mean_line

    mean = ta.sma(arr, period)
    std = ta.stdev(arr, period)

    valid = ~np.isnan(mean) & ~np.isnan(std)
    mean_line[valid] = mean[valid]
    upper_band[valid] = mean[valid] + upper_threshold * std[valid]
    lower_band[valid] = mean[valid] + lower_threshold * std[valid]

    nonzero = valid & (std > 0)
    zscore_vals[nonzero] = (arr[nonzero] - mean[nonzero]) / std[nonzero]
    zscore_vals[valid & (std == 0)] = 0.0
    return zscore_vals, upper_band, lower_band, mean_line


# =============================================================================
# Public API — Handles pandas/numpy/list input
# =============================================================================

def zscore(data, period=20):
    """
    Z-Score Indicator

    Measures how many standard deviations the current price is from its
    rolling mean. Useful for mean-reversion strategies.

    Args:
        data: Close prices (numpy array, pandas Series, or list)
        period: Lookback period (default: 20)

    Returns:
        Z-Score values (same type as input)
    """
    if isinstance(data, pd.Series):
        idx = data.index
        result = _compute_zscore(data.values.astype(np.float64), period)
        return pd.Series(result, index=idx, name=f"ZScore({period})")

    arr = np.asarray(data, dtype=np.float64)
    return _compute_zscore(arr, period)


def zscore_bands(data, period=20, upper=2.0, lower=-2.0):
    """
    Z-Score with price bands.

    Args:
        data: Close prices
        period: Lookback period (default: 20)
        upper: Upper threshold in stdev units (default: 2.0)
        lower: Lower threshold in stdev units (default: -2.0)

    Returns:
        Tuple: (zscore, upper_band, lower_band, mean_line)
    """
    if isinstance(data, pd.Series):
        idx = data.index
        z, ub, lb, ml = _compute_zscore_bands(
            data.values.astype(np.float64), period, upper, lower)
        return (
            pd.Series(z, index=idx, name=f"ZScore({period})"),
            pd.Series(ub, index=idx, name="Upper"),
            pd.Series(lb, index=idx, name="Lower"),
            pd.Series(ml, index=idx, name="Mean"),
        )

    arr = np.asarray(data, dtype=np.float64)
    return _compute_zscore_bands(arr, period, upper, lower)


# =============================================================================
# Benchmark — no warmup needed, first call is full speed
# =============================================================================

if __name__ == "__main__":
    import time

    print("Z-Score Indicator Benchmark")
    print("-" * 40)

    for size in [10_000, 100_000, 500_000]:
        data = np.random.randn(size).cumsum() + 1000

        t0 = time.perf_counter()
        _ = zscore(data, 20)
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  zscore({size:>10,} bars): {elapsed:>8.2f}ms")

        t0 = time.perf_counter()
        _ = zscore_bands(data, 20)
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  bands ({size:>10,} bars): {elapsed:>8.2f}ms")
