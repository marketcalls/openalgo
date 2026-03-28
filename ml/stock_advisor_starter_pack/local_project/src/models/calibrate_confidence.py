from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class MinMaxConfidenceCalibrator:
    min_score: float
    max_score: float

    def transform(self, raw_scores: pd.Series) -> pd.Series:
        if self.max_score <= self.min_score:
            return pd.Series(0.5, index=raw_scores.index, dtype=float)
        return ((raw_scores - self.min_score) / (self.max_score - self.min_score)).clip(0.0, 1.0)


def fit_confidence_calibrator(raw_scores: pd.Series) -> MinMaxConfidenceCalibrator:
    raw = pd.to_numeric(raw_scores, errors="coerce").fillna(0.0)
    return MinMaxConfidenceCalibrator(min_score=float(raw.min()), max_score=float(raw.max()))
