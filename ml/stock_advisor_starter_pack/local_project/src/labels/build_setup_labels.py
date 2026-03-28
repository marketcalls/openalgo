from __future__ import annotations

import pandas as pd


def build_setup_labels(df: pd.DataFrame, signal_column: str, lookahead_bars: int = 5) -> pd.DataFrame:
    working = df.copy()
    future_close = working["close"].shift(-lookahead_bars)
    side = working[signal_column].fillna(0)
    pnl = (future_close - working["close"]) * side
    working["setup_forward_pnl"] = pnl.fillna(0.0)
    working["setup_success"] = (working["setup_forward_pnl"] > 0).astype(int)
    return working
