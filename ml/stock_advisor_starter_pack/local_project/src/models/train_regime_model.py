from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

import pandas as pd

from core.constants import DEFAULT_ARTIFACTS_ROOT, EXAMPLES_ROOT
from core.interfaces import ModelBundleMetadata
from features.build_regime_features import build_regime_features
from features.feature_schema import infer_feature_columns
from labels.build_regime_labels import build_regime_labels
from mlops.experiment_tracker import tracker
from models.model_registry import save_model_bundle


@dataclass
class CentroidRegimeModel:
    feature_columns: list[str]
    centroids: dict[str, dict[str, float]]

    def predict_proba(self, features: pd.DataFrame) -> pd.DataFrame:
        rows: list[dict[str, float]] = []
        for _, row in features[self.feature_columns].fillna(0.0).iterrows():
            distances: dict[str, float] = {}
            for label, centroid in self.centroids.items():
                distance = 0.0
                for column in self.feature_columns:
                    distance += abs(float(row[column]) - float(centroid[column]))
                distances[label] = 1.0 / max(distance, 1e-6)
            total = sum(distances.values())
            rows.append({label: value / total for label, value in distances.items()})
        return pd.DataFrame(rows, index=features.index)

    def predict(self, features: pd.DataFrame) -> pd.Series:
        probabilities = self.predict_proba(features)
        return probabilities.idxmax(axis=1)


class LightGBMRegimeModel:
    """LightGBM-backed regime classifier with anti-overfitting params for noisy financial data.

    Anti-overfitting configuration:
    - ``min_data_in_leaf=50`` prevents leaf-level noise overfitting
    - ``feature_fraction=0.8`` / ``bagging_fraction=0.8`` add randomisation
    - ``early_stopping_rounds=10`` halts training before validation loss diverges
    """

    def __init__(self, feature_columns: list[str]) -> None:
        self.feature_columns = feature_columns
        self.clf_ = None
        self.best_iteration_: int = 0
        self.feature_importance_: pd.DataFrame = pd.DataFrame()

    def fit(
        self,
        train_df: pd.DataFrame,
        train_labels: pd.Series,
        val_df: pd.DataFrame,
        val_labels: pd.Series,
    ) -> "LightGBMRegimeModel":
        try:
            from lightgbm import LGBMClassifier, early_stopping
        except ImportError as exc:
            raise ImportError(
                "lightgbm is required for LightGBMRegimeModel. "
                "Install it with: pip install lightgbm>=4.0"
            ) from exc

        X_train = train_df[self.feature_columns].fillna(0.0)
        X_val   = val_df[self.feature_columns].fillna(0.0)

        clf = LGBMClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.05,
            class_weight="balanced",
            min_child_samples=50,   # lightgbm name for min_data_in_leaf
            feature_fraction=0.8,
            bagging_fraction=0.8,
            bagging_freq=5,
            verbose=-1,
        )
        clf.fit(
            X_train, train_labels,
            eval_set=[(X_val, val_labels)],
            eval_metric="multi_logloss",
            callbacks=[early_stopping(stopping_rounds=10, verbose=False)],
        )
        self.clf_ = clf
        self.best_iteration_ = int(clf.best_iteration_)
        self.feature_importance_ = pd.DataFrame({
            "feature":    self.feature_columns,
            "importance": clf.feature_importances_,
        }).sort_values("importance", ascending=False).reset_index(drop=True)
        return self

    def predict_proba(self, features: pd.DataFrame) -> pd.DataFrame:
        if self.clf_ is None:
            raise RuntimeError("Model has not been fitted yet.")
        X = features[self.feature_columns].fillna(0.0)
        proba = self.clf_.predict_proba(X)
        return pd.DataFrame(proba, columns=self.clf_.classes_, index=features.index)

    def predict(self, features: pd.DataFrame) -> pd.Series:
        proba = self.predict_proba(features)
        return proba.idxmax(axis=1)


RegimeModel = Union[CentroidRegimeModel, LightGBMRegimeModel]


def train_regime_model(
    df: pd.DataFrame,
    model_type: str = "centroid",
) -> tuple[RegimeModel, list[str]]:
    """Train a regime classification model.

    Parameters
    ----------
    df:
        Raw OHLCV DataFrame.
    model_type:
        ``"centroid"`` (default) — lightweight distance-to-centroid classifier.
        ``"lightgbm"`` — gradient-boosted tree model; requires ``lightgbm>=4.0``.
    """
    feature_frame = build_regime_features(df)
    labeled = build_regime_labels(feature_frame)
    excluded = {"symbol", "timeframe", "datetime", "regime_label", "forward_return"}
    feature_columns = infer_feature_columns(
        labeled.select_dtypes(include=["number"]), excluded=excluded
    )
    train = labeled.dropna(subset=["regime_label"]).copy()

    if model_type == "lightgbm":
        # 80 / 20 chronological split for early stopping validation
        split = max(1, int(len(train) * 0.80))
        train_part = train.iloc[:split]
        val_part   = train.iloc[split:]

        model = LightGBMRegimeModel(feature_columns=feature_columns).fit(
            train_df=train_part,
            train_labels=train_part["regime_label"],
            val_df=val_part,
            val_labels=val_part["regime_label"],
        )

        # Save feature importance CSV alongside model artifacts
        fi_dir = DEFAULT_ARTIFACTS_ROOT / "models" / "candidate"
        fi_dir.mkdir(parents=True, exist_ok=True)
        fi_path = fi_dir / "feature_importance.csv"
        model.feature_importance_.to_csv(fi_path, index=False)

        val_preds = model.predict(val_part[feature_columns].fillna(0.0))
        val_acc = float((val_preds == val_part["regime_label"]).mean()) if not val_part.empty else 0.0
        tracker.log_lightgbm_run(
            model=model,
            metrics={"val_accuracy": val_acc, "best_iteration": float(model.best_iteration_)},
            artifacts={"feature_importance": fi_path},
        )
        return model, feature_columns

    # Default: centroid model (unchanged path)
    centroids: dict[str, dict[str, float]] = {}
    for label, subset in train.groupby("regime_label"):
        centroids[label] = {
            column: float(subset[column].fillna(0.0).mean()) for column in feature_columns
        }
    model = CentroidRegimeModel(feature_columns=feature_columns, centroids=centroids)
    preds = model.predict(train[feature_columns].fillna(0.0))
    accuracy = float((preds == train["regime_label"]).mean()) if not train.empty else 0.0
    tracker.log_regime_training(
        model_type="centroid",
        feature_columns=feature_columns,
        accuracy=accuracy,
    )
    return model, feature_columns


def run_example(bundle_root: str | Path) -> Path:
    sample_path = EXAMPLES_ROOT / "sample_market_data.csv"
    df = pd.read_csv(sample_path)
    model, feature_columns = train_regime_model(df)
    metadata = ModelBundleMetadata(
        model_version="sample-regime-v1",
        horizon="swing",
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        feature_columns=feature_columns,
        training_symbols=sorted(df["symbol"].unique().tolist()),
        notes="Starter centroid regime model trained on sample data.",
    )
    return save_model_bundle(bundle_root, metadata, {"regime_model": model})


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[3] / "artifacts_template" / "models" / "candidate" / "sample_regime_bundle"
    print(run_example(target))
