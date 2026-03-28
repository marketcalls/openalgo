from __future__ import annotations

import pandas as pd


def build_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    working["return_1"] = working["close"].pct_change().fillna(0.0)
    working["return_5"] = working["close"].pct_change(5).fillna(0.0)
    working["volatility_10"] = working["return_1"].rolling(10, min_periods=1).std().fillna(0.0)
    working["volume_zscore_10"] = (
        (working["volume"] - working["volume"].rolling(10, min_periods=1).mean())
        / working["volume"].rolling(10, min_periods=1).std().replace(0, 1)
    ).fillna(0.0)
    working["close_ma_5"] = working["close"].rolling(5, min_periods=1).mean()
    working["close_ma_20"] = working["close"].rolling(20, min_periods=1).mean()
    working["ma_spread"] = (working["close_ma_5"] - working["close_ma_20"]).fillna(0.0)

    # Time-of-day features — only when datetime column is present
    if "datetime" in working.columns:
        dt = pd.to_datetime(working["datetime"], errors="coerce")
        if dt.dt.tz is None:
            dt = dt.dt.tz_localize("UTC")
        ist = dt.dt.tz_convert("Asia/Kolkata")
        working["ist_hour"] = ist.dt.hour
        # session_norm: 0.0 = market open (09:15), 1.0 = market close (15:30)
        working["session_norm"] = (
            (ist.dt.hour * 60 + ist.dt.minute - 555) / 375
        ).clip(0.0, 1.0).fillna(0.0)

    # RSI-14
    delta = working["close"].diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=1).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=1).mean()
    working["rsi_14"] = (100 - (100 / (1 + gain / loss.replace(0, 1e-9)))).fillna(50.0)

    # ATR-14 — only when high and low columns are present
    if "high" in working.columns and "low" in working.columns:
        working["atr_14"] = (
            (working["high"] - working["low"]).rolling(14, min_periods=1).mean()
        ).fillna(0.0)
        working["atr_pct"] = (working["atr_14"] / working["close"].replace(0, 1e-9)).fillna(0.0)

    return working
