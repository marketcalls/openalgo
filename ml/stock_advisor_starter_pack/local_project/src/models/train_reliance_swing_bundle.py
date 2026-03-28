from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import load_structured_config, save_json
from core.constants import DEFAULT_ARTIFACTS_ROOT, DEFAULT_RELIANCE_ROOT, DEFAULT_STRATEGY_ROOT
from core.interfaces import ModelBundleMetadata
from data.load_symbol_timeframes import load_symbol_timeframes
from features.build_swing_training_data import build_swing_training_artifacts
from features.feature_schema import save_feature_schema
from models.calibrate_confidence import fit_confidence_calibrator
from models.model_registry import save_model_bundle
from models.train_regime_model import train_regime_model
from models.train_setup_ranker import train_setup_ranker
from strategies.registry import build_strategy_registry


def _resolve_selected_strategies(config: dict[str, Any], registry: dict[str, Any]) -> list[str]:
    explicit = list(config.get("selected_strategies", []))
    if explicit:
        return [name for name in explicit if name in registry]
    return [name for name, wrapper in registry.items() if not wrapper.unsupported_reason]


def train_reliance_swing_bundle(config_path: str | Path) -> dict[str, Any]:
    config = load_structured_config(config_path)
    symbol = str(config.get("symbol", "RELIANCE"))
    market_data_root = Path(config.get("market_data_root", DEFAULT_RELIANCE_ROOT))
    strategy_root = Path(config.get("strategy_root", DEFAULT_STRATEGY_ROOT))
    output_root = Path(config.get("output_root", DEFAULT_ARTIFACTS_ROOT))
    primary_tf = str(config.get("primary_tf", "15m"))
    confirm_tfs = list(config.get("confirm_tfs", ["1hr", "1day"]))

    datasets = load_symbol_timeframes(market_data_root, symbol=symbol)
    if primary_tf not in datasets:
        raise FileNotFoundError(f"Primary timeframe {primary_tf} not found in {market_data_root}")
    missing_confirms = [timeframe for timeframe in confirm_tfs if timeframe not in datasets]
    if missing_confirms:
        raise FileNotFoundError(f"Missing confirmation timeframes: {missing_confirms}")

    registry = build_strategy_registry(strategy_root)
    selected_strategies = _resolve_selected_strategies(config, registry)
    wrappers = [registry[name] for name in selected_strategies]

    strategy_params = dict(config.get("strategy_params", {}))

    artifacts = build_swing_training_artifacts(
        primary=datasets[primary_tf],
        confirmations=[datasets[timeframe] for timeframe in confirm_tfs],
        wrappers=wrappers,
        strategy_params=strategy_params,
    )
    if artifacts.candidate_frame.empty:
        raise RuntimeError("No candidate rows were generated from the selected strategies.")

    regime_model, feature_columns = train_regime_model(artifacts.regime_frame)
    candidate_frame = artifacts.candidate_frame.copy()
    candidate_frame = candidate_frame[candidate_frame["usable_signal"] != 0].reset_index(drop=True)
    if candidate_frame.empty:
        raise RuntimeError("All candidates were filtered out because they had no usable signal.")

    setup_ranker = train_setup_ranker(candidate_frame)
    raw_scores = setup_ranker.score(candidate_frame)
    calibrator = fit_confidence_calibrator(raw_scores)
    candidate_frame["raw_score"] = raw_scores
    candidate_frame["confidence"] = calibrator.transform(raw_scores)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bundle_name = f"{symbol.lower()}_swing_{primary_tf}_{timestamp}"
    bundle_root = output_root / "models" / "candidate" / bundle_name
    report_root = output_root / "reports" / bundle_name
    report_root.mkdir(parents=True, exist_ok=True)

    metadata = ModelBundleMetadata(
        model_version=bundle_name,
        horizon="swing",
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        feature_columns=feature_columns,
        training_symbols=[symbol],
        notes=f"Primary TF={primary_tf}; confirm TFs={confirm_tfs}; selected strategies={selected_strategies}",
        artifact_root=str(bundle_root),
    )

    save_model_bundle(
        bundle_root,
        metadata,
        {
            "regime_model": regime_model,
            "setup_ranker": setup_ranker,
            "confidence_calibrator": calibrator,
            "selected_strategies": selected_strategies,
            "primary_tf": primary_tf,
            "confirm_tfs": confirm_tfs,
            "strategy_notes": artifacts.strategy_notes,
        },
    )
    save_feature_schema(bundle_root / "feature_schema.json", feature_columns)

    artifacts.regime_frame.to_csv(report_root / "regime_frame.csv", index=False)
    candidate_frame.to_csv(report_root / "candidate_frame.csv", index=False)
    candidate_frame.groupby("strategy_name")["setup_success"].agg(["count", "mean"]).reset_index().to_csv(
        report_root / "strategy_success_summary.csv",
        index=False,
    )
    save_json(
        report_root / "training_summary.json",
        {
            "bundle_name": bundle_name,
            "symbol": symbol,
            "primary_tf": primary_tf,
            "confirm_tfs": confirm_tfs,
            "selected_strategies": selected_strategies,
            "candidate_rows": len(candidate_frame),
            "regime_rows": len(artifacts.regime_frame),
            "strategy_notes": artifacts.strategy_notes,
            "market_data_root": str(market_data_root),
            "strategy_root": str(strategy_root),
        },
    )

    return {
        "bundle_root": str(bundle_root),
        "report_root": str(report_root),
        "bundle_name": bundle_name,
        "candidate_rows": len(candidate_frame),
        "selected_strategies": selected_strategies,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parents[2] / "configs" / "reliance_swing.yaml"),
        help="Path to YAML config file",
    )
    args = parser.parse_args()
    result = train_reliance_swing_bundle(args.config)
    print(json.dumps(result, indent=2))
