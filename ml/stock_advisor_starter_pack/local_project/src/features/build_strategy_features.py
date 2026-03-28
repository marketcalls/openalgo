from __future__ import annotations

from typing import Iterable

import pandas as pd

from strategies.registry import ModuleStrategyWrapper


def build_strategy_feature_frame(
    df: pd.DataFrame,
    wrappers: Iterable[ModuleStrategyWrapper],
) -> pd.DataFrame:
    working = df.copy()
    for wrapper in wrappers:
        result = wrapper.run(df)
        working[f"{wrapper.name}__signal"] = result.signal.values
        working[f"{wrapper.name}__strength"] = result.signal_strength.values
        working[f"{wrapper.name}__trend"] = result.trend_state.values
    return working
