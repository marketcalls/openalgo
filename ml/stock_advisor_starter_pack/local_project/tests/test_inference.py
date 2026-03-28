from pathlib import Path

import pandas as pd

from features.build_regime_features import build_regime_features
from inference.recommend import recommend_latest
from models.calibrate_confidence import fit_confidence_calibrator
from models.train_regime_model import train_regime_model
from models.train_setup_ranker import build_sample_candidates, train_setup_ranker


def test_sample_recommendation_can_be_generated():
    sample_path = Path(__file__).resolve().parents[1] / "examples" / "sample_market_data.csv"
    df = pd.read_csv(sample_path)
    regime_model, _ = train_regime_model(df)
    candidates = build_sample_candidates(df)
    ranker = train_setup_ranker(candidates)
    calibrator = fit_confidence_calibrator(ranker.score(candidates))
    recommendation = recommend_latest(
        feature_frame=build_regime_features(df),
        candidate_frame=candidates,
        regime_model=regime_model,
        setup_ranker=ranker,
        calibrator=calibrator,
        model_version="sample-v1",
    )
    assert recommendation.symbol == "RELIANCE"
    assert 0.0 <= recommendation.confidence <= 1.0
