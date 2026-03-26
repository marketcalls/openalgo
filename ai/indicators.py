"""Technical indicator engine adapted from VAYU.

Uses `ta` library (NOT pandas-ta which is broken/unmaintained).
All computations wrapped in _safe() to prevent crashes on short data.
"""

import numpy as np
import pandas as pd
import ta
from utils.logging import get_logger

logger = get_logger(__name__)


def _safe(func, *args, **kwargs):
    """Safely compute an indicator, returning None on error."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.debug(f"Indicator skipped: {e}")
        return None


def _compute_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """Compute Supertrend indicator."""
    hl2 = (df["high"] + df["low"]) / 2
    atr = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=period).average_true_range()

    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    supertrend = pd.Series(np.nan, index=df.index)
    direction = pd.Series(1, index=df.index)

    for i in range(period, len(df)):
        if df["close"].iloc[i] > upper_band.iloc[i - 1]:
            direction.iloc[i] = 1
        elif df["close"].iloc[i] < lower_band.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]
            if direction.iloc[i] == 1 and lower_band.iloc[i] < lower_band.iloc[i - 1]:
                lower_band.iloc[i] = lower_band.iloc[i - 1]
            if direction.iloc[i] == -1 and upper_band.iloc[i] > upper_band.iloc[i - 1]:
                upper_band.iloc[i] = upper_band.iloc[i - 1]

        supertrend.iloc[i] = lower_band.iloc[i] if direction.iloc[i] == 1 else upper_band.iloc[i]

    df["supertrend"] = supertrend
    df["supertrend_dir"] = direction
    return df


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all technical indicators to an OHLCV DataFrame.

    Input: DataFrame with columns: open, high, low, close, volume
    Returns: new DataFrame with indicator columns added (does NOT mutate input).
    """
    if len(df) < 2:
        return df.copy()

    df = df.copy()
    n = len(df)
    h, l, c, v = df["high"], df["low"], df["close"], df["volume"]

    # === Trend ===
    macd_ind = ta.trend.MACD(c, window_slow=26, window_fast=12, window_sign=9)
    df["macd"] = _safe(macd_ind.macd)
    df["macd_signal"] = _safe(macd_ind.macd_signal)
    df["macd_hist"] = _safe(macd_ind.macd_diff)

    if n >= 30:
        adx_ind = ta.trend.ADXIndicator(h, l, c, window=14)
        df["adx_14"] = _safe(adx_ind.adx)
        df["dmp_14"] = _safe(adx_ind.adx_pos)
        df["dmn_14"] = _safe(adx_ind.adx_neg)

    # === Moving Averages ===
    df["ema_9"] = _safe(lambda: ta.trend.EMAIndicator(c, window=9).ema_indicator())
    df["ema_21"] = _safe(lambda: ta.trend.EMAIndicator(c, window=21).ema_indicator())
    if n >= 50:
        df["sma_50"] = _safe(lambda: ta.trend.SMAIndicator(c, window=50).sma_indicator())
    if n >= 200:
        df["sma_200"] = _safe(lambda: ta.trend.SMAIndicator(c, window=200).sma_indicator())

    # === Supertrend ===
    if n >= 15:
        df = _compute_supertrend(df, period=10, multiplier=3.0)

    # === Momentum ===
    df["rsi_14"] = _safe(lambda: ta.momentum.RSIIndicator(c, window=14).rsi())
    df["rsi_7"] = _safe(lambda: ta.momentum.RSIIndicator(c, window=7).rsi())

    if n >= 16:
        stoch = ta.momentum.StochasticOscillator(h, l, c, window=14, smooth_window=3)
        df["stoch_k"] = _safe(stoch.stoch)
        df["stoch_d"] = _safe(stoch.stoch_signal)

    # === Volatility ===
    bb = ta.volatility.BollingerBands(c, window=20, window_dev=2)
    df["bb_high"] = _safe(bb.bollinger_hband)
    df["bb_low"] = _safe(bb.bollinger_lband)
    df["bb_mid"] = _safe(bb.bollinger_mavg)
    df["bb_pband"] = _safe(bb.bollinger_pband)

    if n >= 14:
        df["atr_14"] = _safe(lambda: ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range())

    # === Volume ===
    df["obv"] = _safe(lambda: ta.volume.OnBalanceVolumeIndicator(c, v).on_balance_volume())
    df["vwap"] = _safe(lambda: ta.volume.VolumeWeightedAveragePrice(h, l, c, v).volume_weighted_average_price())

    return df
