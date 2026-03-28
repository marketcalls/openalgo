from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd


@dataclass(slots=True)
class WalkForwardResult:
    train_rows: int
    test_rows: int
    train_metric: float
    test_metric: float
    robustness: float


@dataclass
class RollingWalkForwardResult:
    """Result from a rolling (multi-fold) walk-forward evaluation."""
    n_folds: int
    fold_results: list[dict]         # per-fold: train_start, test_start, test_end, train_metric, test_metric
    mean_test_metric: float
    std_test_metric: float
    mean_train_metric: float
    robustness: float                # mean_test / mean_train — values near 1.0 indicate good generalization

    def passed_gate(
        self,
        min_mean_test: float = 0.55,
        min_robustness: float = 0.70,
        min_fold_test: float  = 0.45,
    ) -> tuple[bool, dict]:
        """Return (passed, details) for the Week 2 promotion gate."""
        checks = {
            "n_folds_ok":       self.n_folds >= 3,
            "mean_test_ok":     self.mean_test_metric >= min_mean_test,
            "robustness_ok":    self.robustness >= min_robustness,
            "no_bad_fold":      all(f["test_metric"] >= min_fold_test for f in self.fold_results),
        }
        return all(checks.values()), checks


def chronological_split(df: pd.DataFrame, train_ratio: float = 0.7) -> tuple[pd.DataFrame, pd.DataFrame]:
    split_index = max(1, int(len(df) * train_ratio))
    return df.iloc[:split_index].copy(), df.iloc[split_index:].copy()


def evaluate_simple_walk_forward(
    df: pd.DataFrame,
    target_col: str,
    prediction_col: str,
) -> WalkForwardResult:
    train_df, test_df = chronological_split(df)
    train_metric = float((train_df[target_col] == train_df[prediction_col]).mean()) if not train_df.empty else 0.0
    test_metric = float((test_df[target_col] == test_df[prediction_col]).mean()) if not test_df.empty else 0.0
    robustness = test_metric / train_metric if train_metric else 0.0
    return WalkForwardResult(
        train_rows=len(train_df),
        test_rows=len(test_df),
        train_metric=train_metric,
        test_metric=test_metric,
        robustness=robustness,
    )


def rolling_walk_forward(
    df: pd.DataFrame,
    target_col: str,
    prediction_fn: Callable[[pd.DataFrame], pd.Series],
    train_bars: int = 2500,
    test_bars: int  = 500,
    step_bars: int  = 250,
) -> RollingWalkForwardResult:
    """Expanding-window rolling walk-forward evaluation.

    For each fold, the model is trained on the first ``train_bars`` rows of the
    current window and evaluated on the next ``test_bars`` rows.  The window
    advances by ``step_bars`` each fold.  Only the test-set metrics are
    aggregated — training set metrics track overfit risk (robustness ratio).

    Parameters
    ----------
    df:
        Chronologically sorted DataFrame.
    target_col:
        Column with ground-truth labels.
    prediction_fn:
        Callable that receives the training split and returns a prediction
        Series aligned to the *full* df index.  The test slice is evaluated
        using ``prediction_fn(train_df)`` projected onto the test rows.
    train_bars, test_bars, step_bars:
        Window geometry in number of rows.
    """
    n = len(df)
    fold_results: list[dict] = []
    start = 0

    while start + train_bars + test_bars <= n:
        train_end = start + train_bars
        test_end  = min(train_end + test_bars, n)

        train_df = df.iloc[start:train_end].copy()
        test_df  = df.iloc[train_end:test_end].copy()

        predictions = prediction_fn(train_df)

        # Align predictions to test index
        if isinstance(predictions, pd.Series):
            preds_test = predictions.reindex(test_df.index)
        else:
            preds_test = pd.Series(predictions, index=test_df.index)

        train_preds = prediction_fn(train_df).reindex(train_df.index)
        train_metric = float(
            (train_df[target_col] == train_preds).mean()
        ) if not train_df.empty else 0.0
        test_metric = float(
            (test_df[target_col] == preds_test).mean()
        ) if not test_df.empty else 0.0

        fold_results.append({
            "fold":         len(fold_results),
            "train_start":  start,
            "train_end":    train_end,
            "test_start":   train_end,
            "test_end":     test_end,
            "train_rows":   len(train_df),
            "test_rows":    len(test_df),
            "train_metric": train_metric,
            "test_metric":  test_metric,
        })
        start += step_bars

    if not fold_results:
        return RollingWalkForwardResult(
            n_folds=0, fold_results=[],
            mean_test_metric=0.0, std_test_metric=0.0,
            mean_train_metric=0.0, robustness=0.0,
        )

    test_metrics  = [f["test_metric"]  for f in fold_results]
    train_metrics = [f["train_metric"] for f in fold_results]
    mean_test  = float(np.mean(test_metrics))
    mean_train = float(np.mean(train_metrics))

    return RollingWalkForwardResult(
        n_folds=len(fold_results),
        fold_results=fold_results,
        mean_test_metric=mean_test,
        std_test_metric=float(np.std(test_metrics)),
        mean_train_metric=mean_train,
        robustness=mean_test / mean_train if mean_train > 0 else 0.0,
    )


def evaluate_regime_walk_forward(
    df: pd.DataFrame,
    model_type: str = "centroid",
    train_bars: int = 2500,
    test_bars: int  = 500,
    step_bars: int  = 250,
) -> RollingWalkForwardResult:
    """Convenience wrapper: trains a regime model on each fold and reports accuracy.

    Parameters
    ----------
    df:
        Raw OHLCV DataFrame (no pre-computed features required).
    model_type:
        ``"centroid"`` (default) or ``"lightgbm"`` — passed to ``train_regime_model``.
    """
    from features.build_regime_features import build_regime_features
    from labels.build_regime_labels import build_regime_labels
    from models.train_regime_model import train_regime_model

    # Build features + labels on the full frame so folds share the same schema
    labeled = build_regime_labels(build_regime_features(df))
    labeled = labeled.dropna(subset=["regime_label"]).reset_index(drop=True)

    def predict_fold(train_df: pd.DataFrame) -> pd.Series:
        model, _ = train_regime_model(train_df, model_type=model_type)
        from features.build_regime_features import build_regime_features as brf
        from labels.build_regime_labels import build_regime_labels as brl
        feat = brl(brf(labeled))
        return model.predict(feat)

    return rolling_walk_forward(
        labeled,
        target_col="regime_label",
        prediction_fn=predict_fold,
        train_bars=train_bars,
        test_bars=test_bars,
        step_bars=step_bars,
    )
