from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from core.constants import EXAMPLES_ROOT
from core.interfaces import ModelBundleMetadata
from mlops.experiment_tracker import tracker
from models.model_registry import save_model_bundle


@dataclass
class HeuristicSetupRanker:
    strategy_scores: dict[str, float]
    fallback_score: float

    def score(self, candidates: pd.DataFrame) -> pd.Series:
        strategy_name = candidates.get("strategy_name", pd.Series("unknown", index=candidates.index))
        strength = pd.to_numeric(candidates.get("signal_strength", 0.5), errors="coerce").fillna(0.5)
        base = strategy_name.map(self.strategy_scores).fillna(self.fallback_score)
        return base + strength * 0.25


def train_setup_ranker(candidates: pd.DataFrame, target_col: str = "setup_success") -> HeuristicSetupRanker:
    grouped = candidates.groupby("strategy_name")[target_col].mean().to_dict()
    fallback = float(candidates[target_col].mean()) if not candidates.empty else 0.5
    ranker = HeuristicSetupRanker(
        strategy_scores={str(k): float(v) for k, v in grouped.items()},
        fallback_score=fallback,
    )
    tracker.log_setup_ranker(strategy_scores=ranker.strategy_scores, fallback_score=fallback)
    return ranker


def build_sample_candidates(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    working["signal_strength"] = ((working["close"] - working["open"]).abs() / working["open"]).clip(0.0, 1.0)
    working["strategy_name"] = ["twin_range_filter" if idx % 2 == 0 else "trend_signals_tp_sl_ualgo" for idx in range(len(working))]
    working["setup_success"] = (working["close"].shift(-1) > working["close"]).fillna(False).astype(int)
    return working


def run_example(bundle_root: str | Path) -> Path:
    df = pd.read_csv(EXAMPLES_ROOT / "sample_market_data.csv")
    candidates = build_sample_candidates(df)
    ranker = train_setup_ranker(candidates)
    metadata = ModelBundleMetadata(
        model_version="sample-setup-v1",
        horizon="swing",
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        feature_columns=["signal_strength"],
        training_symbols=sorted(df["symbol"].unique().tolist()),
        notes="Starter setup ranker trained on sample candidates.",
    )
    return save_model_bundle(bundle_root, metadata, {"setup_ranker": ranker})


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[3] / "artifacts_template" / "models" / "candidate" / "sample_setup_bundle"
    print(run_example(target))
