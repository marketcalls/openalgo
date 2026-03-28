"""Advanced technical indicators from custom + open-source libraries.

Sources:
- Smart Money Concepts (BOS, CHoCH, FVG, Order Blocks)
- Harmonic Patterns (Gartley, Bat, Butterfly, Crab, Shark, Cypher)
- 15 Candlestick Patterns
- Central Pivot Range (Pivot, BC/TC, R1-R5, S1-S5)
- Fibonacci Retracement Levels
- RSI Divergence
- Volume Exhaustion + VWAP/BB Confluence
"""

import numpy as np
import pandas as pd
from utils.logging import get_logger

logger = get_logger(__name__)


def _safe(func, default=None):
    """Safely execute indicator computation."""
    try:
        return func()
    except Exception as e:
        logger.debug(f"Advanced indicator skipped: {e}")
        return default


# ============================================================
# SMART MONEY CONCEPTS
# ============================================================

def _detect_swing_points(df: pd.DataFrame, length: int = 10) -> pd.DataFrame:
    """Detect swing highs and lows using rolling window."""
    df = df.copy()
    df["swing_high"] = df["high"].rolling(length * 2 + 1, center=True).apply(
        lambda x: 1 if x.iloc[length] == x.max() else 0, raw=False
    )
    df["swing_low"] = df["low"].rolling(length * 2 + 1, center=True).apply(
        lambda x: 1 if x.iloc[length] == x.min() else 0, raw=False
    )
    return df


def compute_smc_indicators(df: pd.DataFrame, swing_length: int = 10) -> pd.DataFrame:
    """Compute Smart Money Concept indicators: BOS, CHoCH, FVG, Order Blocks."""
    df = df.copy()
    n = len(df)

    # Initialize output columns
    for col in ["smc_bos_bullish", "smc_bos_bearish", "smc_choch_bullish", "smc_choch_bearish",
                 "smc_fvg_bullish", "smc_fvg_bearish", "smc_ob_bullish", "smc_ob_bearish"]:
        df[col] = 0

    if n < swing_length * 3:
        return df

    # Detect swings
    df = _detect_swing_points(df, swing_length)

    # --- Fair Value Gaps (3-bar imbalance) ---
    for i in range(2, n):
        # Bullish FVG: bar[i] low > bar[i-2] high (gap up)
        if df["low"].iloc[i] > df["high"].iloc[i - 2]:
            df.iloc[i, df.columns.get_loc("smc_fvg_bullish")] = 1
        # Bearish FVG: bar[i] high < bar[i-2] low (gap down)
        if df["high"].iloc[i] < df["low"].iloc[i - 2]:
            df.iloc[i, df.columns.get_loc("smc_fvg_bearish")] = 1

    # --- Break of Structure / Change of Character ---
    last_swing_high = None
    last_swing_low = None
    trend = 0  # 1=up, -1=down, 0=neutral

    for i in range(swing_length, n):
        if df["swing_high"].iloc[i] == 1:
            last_swing_high = df["high"].iloc[i]
        if df["swing_low"].iloc[i] == 1:
            last_swing_low = df["low"].iloc[i]

        if last_swing_high is not None and df["close"].iloc[i] > last_swing_high:
            if trend == -1:
                df.iloc[i, df.columns.get_loc("smc_choch_bullish")] = 1  # Change of character
            else:
                df.iloc[i, df.columns.get_loc("smc_bos_bullish")] = 1   # Break of structure
            trend = 1

        if last_swing_low is not None and df["close"].iloc[i] < last_swing_low:
            if trend == 1:
                df.iloc[i, df.columns.get_loc("smc_choch_bearish")] = 1
            else:
                df.iloc[i, df.columns.get_loc("smc_bos_bearish")] = 1
            trend = -1

    # --- Order Blocks (last opposite candle before BOS) ---
    for i in range(1, n):
        if df["smc_bos_bullish"].iloc[i] == 1 or df["smc_choch_bullish"].iloc[i] == 1:
            for j in range(i - 1, max(i - 10, 0), -1):
                if df["close"].iloc[j] < df["open"].iloc[j]:  # Last bearish candle
                    df.iloc[j, df.columns.get_loc("smc_ob_bullish")] = 1
                    break
        if df["smc_bos_bearish"].iloc[i] == 1 or df["smc_choch_bearish"].iloc[i] == 1:
            for j in range(i - 1, max(i - 10, 0), -1):
                if df["close"].iloc[j] > df["open"].iloc[j]:  # Last bullish candle
                    df.iloc[j, df.columns.get_loc("smc_ob_bearish")] = 1
                    break

    return df


# ============================================================
# CANDLESTICK PATTERNS (15)
# ============================================================

def compute_candlestick_patterns(df: pd.DataFrame, doji_size: float = 0.05) -> pd.DataFrame:
    """Detect 15 candlestick patterns."""
    df = df.copy()
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = abs(c - o)
    hl_range = h - l
    upper_shadow = h - pd.concat([o, c], axis=1).max(axis=1)
    lower_shadow = pd.concat([o, c], axis=1).min(axis=1) - l

    # Doji
    df["cdl_doji"] = (body <= hl_range * doji_size).astype(int)

    # Hammer (small body at top, long lower shadow)
    df["cdl_hammer"] = ((lower_shadow > body * 2) & (upper_shadow < body * 0.5) & (hl_range > 0)).astype(int)

    # Inverted Hammer
    df["cdl_inverted_hammer"] = ((upper_shadow > body * 2) & (lower_shadow < body * 0.5) & (hl_range > 0)).astype(int)

    # Shooting Star (same shape as inverted hammer but in uptrend)
    df["cdl_shooting_star"] = ((upper_shadow > body * 2) & (lower_shadow < body * 0.3) & (c < o) & (hl_range > 0)).astype(int)

    # Hanging Man (same shape as hammer but in uptrend)
    df["cdl_hanging_man"] = ((lower_shadow > body * 2) & (upper_shadow < body * 0.3) & (c < o) & (hl_range > 0)).astype(int)

    # Engulfing
    prev_body = body.shift(1)
    df["cdl_engulfing_bull"] = ((c > o) & (c.shift(1) < o.shift(1)) & (body > prev_body) & (c > o.shift(1)) & (o < c.shift(1))).astype(int)
    df["cdl_engulfing_bear"] = ((c < o) & (c.shift(1) > o.shift(1)) & (body > prev_body) & (c < o.shift(1)) & (o > c.shift(1))).astype(int)

    # Harami
    df["cdl_harami_bull"] = ((c > o) & (c.shift(1) < o.shift(1)) & (c < o.shift(1)) & (o > c.shift(1))).astype(int)
    df["cdl_harami_bear"] = ((c < o) & (c.shift(1) > o.shift(1)) & (c > o.shift(1)) & (o < c.shift(1))).astype(int)

    # Morning Star (3-bar)
    df["cdl_morning_star"] = (
        (c.shift(2) < o.shift(2)) &  # Bar 1: bearish
        (body.shift(1) < body.shift(2) * 0.3) &  # Bar 2: small body (star)
        (c > o) &  # Bar 3: bullish
        (c > (o.shift(2) + c.shift(2)) / 2)  # Bar 3 closes above bar 1 midpoint
    ).astype(int)

    # Evening Star (3-bar)
    df["cdl_evening_star"] = (
        (c.shift(2) > o.shift(2)) &
        (body.shift(1) < body.shift(2) * 0.3) &
        (c < o) &
        (c < (o.shift(2) + c.shift(2)) / 2)
    ).astype(int)

    # Piercing Line
    df["cdl_piercing_line"] = (
        (c.shift(1) < o.shift(1)) & (c > o) &
        (o < c.shift(1)) & (c > (o.shift(1) + c.shift(1)) / 2) & (c < o.shift(1))
    ).astype(int)

    # Dark Cloud Cover
    df["cdl_dark_cloud"] = (
        (c.shift(1) > o.shift(1)) & (c < o) &
        (o > c.shift(1)) & (c < (o.shift(1) + c.shift(1)) / 2) & (c > o.shift(1))
    ).astype(int)

    # Three White Soldiers
    df["cdl_three_white_soldiers"] = (
        (c > o) & (c.shift(1) > o.shift(1)) & (c.shift(2) > o.shift(2)) &
        (c > c.shift(1)) & (c.shift(1) > c.shift(2)) &
        (o > o.shift(1)) & (o.shift(1) > o.shift(2))
    ).astype(int)

    # Three Black Crows
    df["cdl_three_black_crows"] = (
        (c < o) & (c.shift(1) < o.shift(1)) & (c.shift(2) < o.shift(2)) &
        (c < c.shift(1)) & (c.shift(1) < c.shift(2)) &
        (o < o.shift(1)) & (o.shift(1) < o.shift(2))
    ).astype(int)

    return df


# ============================================================
# CENTRAL PIVOT RANGE
# ============================================================

def compute_cpr_levels(df: pd.DataFrame) -> pd.DataFrame:
    """Compute Central Pivot Range from previous session OHLC."""
    df = df.copy()
    prev_h = df["high"].shift(1)
    prev_l = df["low"].shift(1)
    prev_c = df["close"].shift(1)

    df["pivot"] = (prev_h + prev_l + prev_c) / 3
    mid = (prev_h + prev_l) / 2
    df["bc"] = pd.concat([mid, 2 * df["pivot"] - mid], axis=1).min(axis=1)
    df["tc"] = pd.concat([mid, 2 * df["pivot"] - mid], axis=1).max(axis=1)

    diff = prev_h - prev_l
    df["r1"] = 2 * df["pivot"] - prev_l
    df["s1"] = 2 * df["pivot"] - prev_h
    df["r2"] = df["pivot"] + diff
    df["s2"] = df["pivot"] - diff
    df["r3"] = prev_h + 2 * (df["pivot"] - prev_l)
    df["s3"] = prev_l - 2 * (prev_h - df["pivot"])

    return df


# ============================================================
# FIBONACCI RETRACEMENT
# ============================================================

def compute_fibonacci_levels(df: pd.DataFrame, lookback: int = 50, tolerance: float = 0.005) -> pd.DataFrame:
    """Compute Fibonacci retracement signals from swing highs/lows."""
    df = df.copy()
    df["fib_long"] = 0
    df["fib_short"] = 0
    fib_ratios = [0.382, 0.500, 0.618]

    if len(df) < lookback:
        return df

    for i in range(lookback, len(df)):
        window = df.iloc[i - lookback:i]
        swing_high = window["high"].max()
        swing_low = window["low"].min()
        rng = swing_high - swing_low
        if rng < 0.01:
            continue

        close = df["close"].iloc[i]
        for ratio in fib_ratios:
            # Bullish: price near fib support level (retracement from high)
            support = swing_high - ratio * rng
            if abs(close - support) / close < tolerance:
                df.iloc[i, df.columns.get_loc("fib_long")] = 1
                break
            # Bearish: price near fib resistance level (retracement from low)
            resistance = swing_low + ratio * rng
            if abs(close - resistance) / close < tolerance:
                df.iloc[i, df.columns.get_loc("fib_short")] = 1
                break

    return df


# ============================================================
# HARMONIC PATTERNS (XABCD)
# ============================================================

def compute_harmonic_patterns(df: pd.DataFrame, zigzag_pct: float = 3.0) -> pd.DataFrame:
    """Detect harmonic patterns: Gartley, Bat, Butterfly, Crab, Shark, Cypher."""
    df = df.copy()
    df["harmonic_bullish"] = 0
    df["harmonic_bearish"] = 0

    if len(df) < 30:
        return df

    # Extract zigzag pivots
    pivots = _extract_zigzag(df, pct=zigzag_pct)
    if len(pivots) < 5:
        return df

    # Harmonic ratio definitions {pattern: {XB, AC, BD, XD}}
    PATTERNS = {
        "gartley":    {"XB": (0.618, 0.618), "AC": (0.382, 0.886), "BD": (1.27, 1.618), "XD": (0.786, 0.786)},
        "bat":        {"XB": (0.382, 0.500), "AC": (0.382, 0.886), "BD": (1.618, 2.618), "XD": (0.886, 0.886)},
        "butterfly":  {"XB": (0.786, 0.786), "AC": (0.382, 0.886), "BD": (1.618, 2.618), "XD": (1.27, 1.618)},
        "crab":       {"XB": (0.382, 0.618), "AC": (0.382, 0.886), "BD": (2.24, 3.618),  "XD": (1.618, 1.618)},
    }
    tolerance = 0.08  # 8% ratio tolerance

    for i in range(4, len(pivots)):
        X, A, B, C, D = [pivots[j] for j in range(i - 4, i + 1)]
        xa = abs(A[1] - X[1])
        if xa < 0.01:
            continue

        xb_ratio = abs(B[1] - X[1]) / xa
        ac_ratio = abs(C[1] - A[1]) / abs(B[1] - A[1]) if abs(B[1] - A[1]) > 0.01 else 0
        bd_ratio = abs(D[1] - B[1]) / abs(C[1] - B[1]) if abs(C[1] - B[1]) > 0.01 else 0
        xd_ratio = abs(D[1] - X[1]) / xa

        for name, ratios in PATTERNS.items():
            if (ratios["XB"][0] * (1 - tolerance) <= xb_ratio <= ratios["XB"][1] * (1 + tolerance) and
                ratios["AC"][0] * (1 - tolerance) <= ac_ratio <= ratios["AC"][1] * (1 + tolerance) and
                ratios["BD"][0] * (1 - tolerance) <= bd_ratio <= ratios["BD"][1] * (1 + tolerance) and
                ratios["XD"][0] * (1 - tolerance) <= xd_ratio <= ratios["XD"][1] * (1 + tolerance)):
                d_idx = D[0]
                if D[1] < C[1]:  # D is a low -> bullish
                    df.iloc[d_idx, df.columns.get_loc("harmonic_bullish")] = 1
                else:  # D is a high -> bearish
                    df.iloc[d_idx, df.columns.get_loc("harmonic_bearish")] = 1
                break

    return df


def _extract_zigzag(df: pd.DataFrame, pct: float = 3.0) -> list[tuple[int, float]]:
    """Extract zigzag pivots from OHLCV data. Returns [(index, price), ...]."""
    pivots = []
    last_pivot = df["close"].iloc[0]
    last_idx = 0
    direction = 0  # 1=up, -1=down

    for i in range(1, len(df)):
        h, l = df["high"].iloc[i], df["low"].iloc[i]
        if direction >= 0 and h >= last_pivot * (1 + pct / 100):
            if direction == -1:
                pivots.append((last_idx, last_pivot))
            last_pivot = h
            last_idx = i
            direction = 1
        elif direction <= 0 and l <= last_pivot * (1 - pct / 100):
            if direction == 1:
                pivots.append((last_idx, last_pivot))
            last_pivot = l
            last_idx = i
            direction = -1

    if last_idx > 0:
        pivots.append((last_idx, last_pivot))
    return pivots


# ============================================================
# RSI DIVERGENCE
# ============================================================

def compute_rsi_divergence(df: pd.DataFrame, rsi_period: int = 14, lookback: int = 20) -> pd.DataFrame:
    """Detect bullish/bearish RSI divergence."""
    import ta
    df = df.copy()
    df["rsi_bull_divergence"] = 0
    df["rsi_bear_divergence"] = 0

    rsi = ta.momentum.RSIIndicator(df["close"], window=rsi_period).rsi()
    if rsi is None:
        return df
    df["_rsi"] = rsi

    for i in range(lookback, len(df)):
        window_price = df["close"].iloc[i - lookback:i + 1]
        window_rsi = df["_rsi"].iloc[i - lookback:i + 1]

        # Bullish divergence: price makes lower low, RSI makes higher low
        price_argmin = window_price.argmin()
        if (df["close"].iloc[i] < window_price.min() * 1.005 and
            price_argmin > 0 and
            df["_rsi"].iloc[i] > window_rsi.iloc[price_argmin]):
            df.iloc[i, df.columns.get_loc("rsi_bull_divergence")] = 1

        # Bearish divergence: price makes higher high, RSI makes lower high
        price_argmax = window_price.argmax()
        if (df["close"].iloc[i] > window_price.max() * 0.995 and
            price_argmax > 0 and
            df["_rsi"].iloc[i] < window_rsi.iloc[price_argmax]):
            df.iloc[i, df.columns.get_loc("rsi_bear_divergence")] = 1

    df.drop(columns=["_rsi"], inplace=True)
    return df


# ============================================================
# VOLUME SIGNALS
# ============================================================

def compute_volume_signals(df: pd.DataFrame, vol_mult: float = 2.0) -> pd.DataFrame:
    """Detect volume exhaustion and VWAP/BB confluence."""
    df = df.copy()

    # Volume exhaustion: volume spike > mult * avg volume
    avg_vol = df["volume"].rolling(20).mean()
    df["volume_exhaustion"] = (df["volume"] > avg_vol * vol_mult).astype(int)

    # VWAP/BB confluence: price near both VWAP and Bollinger Band
    try:
        import ta
        vwap = ta.volume.VolumeWeightedAveragePrice(
            df["high"], df["low"], df["close"], df["volume"]
        ).volume_weighted_average_price()
        bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
        bb_low = bb.bollinger_lband()
        bb_high = bb.bollinger_hband()

        near_vwap = abs(df["close"] - vwap) / df["close"] < 0.005
        near_bb_low = abs(df["close"] - bb_low) / df["close"] < 0.005
        near_bb_high = abs(df["close"] - bb_high) / df["close"] < 0.005

        df["vwap_bb_confluence"] = ((near_vwap & near_bb_low) | (near_vwap & near_bb_high)).astype(int)
    except Exception:
        df["vwap_bb_confluence"] = 0

    return df


# ============================================================
# AGGREGATE: Run all advanced indicators
# ============================================================

def compute_all_advanced(df: pd.DataFrame) -> pd.DataFrame:
    """Run all advanced indicators on an OHLCV DataFrame."""
    for fn in [
        compute_smc_indicators,
        compute_candlestick_patterns,
        compute_cpr_levels,
        compute_fibonacci_levels,
        compute_harmonic_patterns,
        compute_rsi_divergence,
        compute_volume_signals,
    ]:
        result = _safe(lambda f=fn: f(df))
        if result is not None:
            df = result
    return df
