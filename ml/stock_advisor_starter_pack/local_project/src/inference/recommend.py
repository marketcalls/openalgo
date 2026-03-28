from __future__ import annotations

import json
import uuid

import pandas as pd

from core.interfaces import Recommendation
from inference.trade_plan import build_trade_plan


def _normalize_parameters(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def recommend_latest(
    feature_frame: pd.DataFrame,
    candidate_frame: pd.DataFrame,
    regime_model,
    setup_ranker,
    calibrator,
    model_version: str,
    horizon: str = "swing",
) -> Recommendation:
    latest = feature_frame.tail(1).copy()
    regime = str(regime_model.predict(latest).iloc[0])

    candidates = candidate_frame.copy()
    raw_scores = setup_ranker.score(candidates)
    candidates["raw_score"] = raw_scores
    candidates["confidence"] = calibrator.transform(raw_scores)
    winner = candidates.sort_values(["confidence", "raw_score"], ascending=False).iloc[0]

    side = 1 if float(winner.get("signal_strength", 0.5)) >= 0 else -1
    trade_plan = build_trade_plan(
        last_close=float(winner.get("close", latest["close"].iloc[0])),
        side=side,
        confidence=float(winner["confidence"]),
        atr=float(winner.get("atr_proxy", latest["close"].iloc[0] * 0.01)),
    )
    symbol = str(winner["symbol"]) if "symbol" in winner.index else str(latest["symbol"].iloc[0]) if "symbol" in latest.columns else "UNKNOWN"
    primary_tf = str(winner["timeframe"]) if "timeframe" in winner.index else str(latest["timeframe"].iloc[0]) if "timeframe" in latest.columns else "UNKNOWN"
    return Recommendation(
        recommendation_id=str(uuid.uuid4()),
        symbol=symbol,
        horizon=horizon,
        regime=regime,
        strategy_combo=[str(winner["strategy_name"])],
        parameters={str(winner["strategy_name"]): _normalize_parameters(winner.get("parameters", {}))},
        primary_tf=primary_tf,
        confirm_tfs=list(winner.get("confirm_tfs", [])) if isinstance(winner.get("confirm_tfs", []), list) else [],
        entry=float(trade_plan["entry"]),
        stop_loss=float(trade_plan["stop_loss"]),
        target_1=float(trade_plan["target_1"]),
        target_2=float(trade_plan["target_2"]),
        confidence=float(trade_plan["confidence"]),
        reason_codes=[f"regime:{regime}", f"strategy:{winner['strategy_name']}"],
        model_version=model_version,
    )
