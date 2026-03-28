from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.config import load_structured_config
from core.constants import DEFAULT_ARTIFACTS_ROOT, DEFAULT_RELIANCE_ROOT, DEFAULT_STRATEGY_ROOT
from data.load_symbol_timeframes import load_symbol_timeframes
from features.build_swing_training_data import build_swing_training_artifacts
from features.feature_schema import align_feature_frame, load_feature_schema
from inference.load_bundle import load_active_bundle
from inference.recommend import recommend_latest
from strategies.registry import build_strategy_registry


def _select_bundle_root(bundle_hint: str | Path | None, expected_prefix: str) -> Path:
    if bundle_hint:
        return Path(bundle_hint)
    candidate_root = DEFAULT_ARTIFACTS_ROOT / "models" / "candidate"
    bundles = sorted(
        [path for path in candidate_root.iterdir() if path.is_dir() and path.name.startswith(expected_prefix)],
        reverse=True,
    )
    if not bundles:
        raise FileNotFoundError(f"No candidate bundles found in {candidate_root} for prefix {expected_prefix}")
    return bundles[0]


def generate_reliance_swing_recommendation(
    config_path: str | Path,
    bundle_root: str | Path | None = None,
) -> dict[str, Any]:
    config = load_structured_config(config_path)
    symbol = str(config.get("symbol", "RELIANCE"))
    market_data_root = Path(config.get("market_data_root", DEFAULT_RELIANCE_ROOT))
    strategy_root = Path(config.get("strategy_root", DEFAULT_STRATEGY_ROOT))
    primary_tf = str(config.get("primary_tf", "15m"))
    confirm_tfs = list(config.get("confirm_tfs", ["1hr", "1day"]))

    bundle_path = _select_bundle_root(bundle_root, expected_prefix=f"{symbol.lower()}_swing_")
    metadata, objects = load_active_bundle(bundle_path)
    feature_columns = load_feature_schema(bundle_path / "feature_schema.json")

    datasets = load_symbol_timeframes(market_data_root, symbol=symbol)
    registry = build_strategy_registry(strategy_root)
    wrappers = [registry[name] for name in objects["selected_strategies"] if name in registry]
    artifacts = build_swing_training_artifacts(
        primary=datasets[primary_tf],
        confirmations=[datasets[timeframe] for timeframe in confirm_tfs],
        wrappers=wrappers,
    )

    latest_timestamp = artifacts.candidate_frame["timestamp"].max()
    latest_candidates = artifacts.candidate_frame[artifacts.candidate_frame["timestamp"] == latest_timestamp].copy()
    latest_regime_frame = align_feature_frame(artifacts.regime_frame.tail(1), feature_columns)
    recommendation = recommend_latest(
        feature_frame=latest_regime_frame,
        candidate_frame=latest_candidates,
        regime_model=objects["regime_model"],
        setup_ranker=objects["setup_ranker"],
        calibrator=objects["confidence_calibrator"],
        model_version=metadata.model_version,
        horizon="swing",
    )

    output_path = DEFAULT_ARTIFACTS_ROOT / "reports" / metadata.model_version / "latest_recommendation.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(recommendation.to_dict(), indent=2), encoding="utf-8")
    return {"bundle_root": str(bundle_path), "output_path": str(output_path), "recommendation_id": recommendation.recommendation_id}


if __name__ == "__main__":
    default_config = Path(__file__).resolve().parents[2] / "configs" / "reliance_swing.yaml"
    result = generate_reliance_swing_recommendation(default_config)
    print(json.dumps(result, indent=2))
