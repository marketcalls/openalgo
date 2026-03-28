from __future__ import annotations

import pandas as pd


def build_regime_labels(
    df: pd.DataFrame,
    lookahead_bars: int = 5,
    threshold: float = 0.002,
    threshold_mode: str = "atr",
) -> pd.DataFrame:
    """Label each bar as bull / bear / flat based on forward return.

    Parameters
    ----------
    lookahead_bars:
        How many bars ahead to measure the return.
    threshold:
        Used when ``threshold_mode="fixed"``.  A bar is labelled bull if
        ``forward_return > threshold`` and bear if ``forward_return < -threshold``.
    threshold_mode:
        ``"fixed"`` (default) — uses the constant ``threshold`` value.
        ``"atr"``  — derives a volatility-relative threshold:
        ``0.5 * ATR_14 / close`` so that the band adapts to current volatility.
        Requires ``high`` and ``low`` columns to be present.
    """
    working = df.copy()
    forward_return = working["close"].shift(-lookahead_bars) / working["close"] - 1.0
    working["forward_return"] = forward_return

    if threshold_mode == "atr":
        if "high" not in working.columns or "low" not in working.columns:
            raise ValueError(
                "threshold_mode='atr' requires 'high' and 'low' columns in the DataFrame"
            )
        atr = (working["high"] - working["low"]).rolling(14, min_periods=1).mean()
        dynamic_threshold = (0.5 * atr / working["close"]).fillna(threshold)
    else:
        # Fixed threshold — backward-compatible default
        dynamic_threshold = pd.Series(threshold, index=working.index)

    working["regime_label"] = "flat"
    working.loc[forward_return >  dynamic_threshold, "regime_label"] = "bull"
    working.loc[forward_return < -dynamic_threshold, "regime_label"] = "bear"
    return working
