from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from features.build_regime_features import build_regime_features
from feedback.ingest_paper_trade_log import append_feedback_log
from labels.build_regime_labels import build_regime_labels
from models.calibrate_confidence import fit_confidence_calibrator
from models.train_regime_model import train_regime_model
from models.train_setup_ranker import build_sample_candidates, train_setup_ranker

# Minimum real feedback records before abandoning the synthetic fallback.
_MIN_FEEDBACK_RECORDS = 20
# Only use feedback from the last N days.
_FEEDBACK_WINDOW_DAYS = 90
# Exponential decay half-life in days (recent trades weighted more).
_DECAY_HALFLIFE_DAYS  = 30


def _build_candidates_from_feedback(
    feedback_df: pd.DataFrame,
    model_version: str | None = None,
    decay_halflife_days: int = _DECAY_HALFLIFE_DAYS,
) -> pd.DataFrame:
    """Convert real paper-trade records into a candidates DataFrame.

    Parameters
    ----------
    feedback_df:
        Rows from feedback_store.csv (PaperTradeRecord schema).
    model_version:
        If set, filters to records produced by this model version only.
    decay_halflife_days:
        Exponential decay half-life — older records get lower sample weight.

    Returns
    -------
    DataFrame with: strategy_name, setup_success, signal_strength, sample_weight.
    """
    df = feedback_df.copy()

    # Drop manually rejected trades
    if "manual_reject" in df.columns:
        df = df[~df["manual_reject"].astype(bool)]

    if df.empty:
        return pd.DataFrame()

    # Filter by model version
    if model_version and "model_version" in df.columns:
        df = df[df["model_version"] == model_version]

    # Restrict to recent window and apply time-decay weights
    if "exit_time" in df.columns:
        df["_exit_dt"] = pd.to_datetime(df["exit_time"], errors="coerce", utc=True)
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=_FEEDBACK_WINDOW_DAYS)
        df = df[df["_exit_dt"] >= cutoff]
        if df.empty:
            return pd.DataFrame()
        now = pd.Timestamp.now(tz="UTC")
        days_old = (now - df["_exit_dt"]).dt.total_seconds() / 86400.0
        df["sample_weight"] = days_old.apply(
            lambda d: math.exp(-d / decay_halflife_days)
        )
    else:
        df["sample_weight"] = 1.0

    # setup_success from realized PnL
    pnl_col = "net_pnl" if "net_pnl" in df.columns else "gross_pnl" if "gross_pnl" in df.columns else None
    if pnl_col is None:
        return pd.DataFrame()
    pnl = pd.to_numeric(df[pnl_col], errors="coerce")
    df["setup_success"] = (pnl > 0).astype(int)

    # signal_strength from normalized |PnL| — larger wins/losses = higher conviction
    pnl_abs = pnl.abs().fillna(0.0)
    max_pnl = float(pnl_abs.max())
    df["signal_strength"] = (pnl_abs / (max_pnl + 1e-9)).clip(0.0, 1.0) if max_pnl > 0 else 1.0

    # strategy_name — try to extract from recommendation_id prefix, then side, then generic
    if "recommendation_id" in df.columns:
        # IDs may be formatted as "strategy_name__timestamp__..." — take first segment
        df["strategy_name"] = (
            df["recommendation_id"].astype(str)
            .str.split("__").str[0].str.strip()
            .replace("", "feedback_trade")
        )
    elif "side" in df.columns:
        df["strategy_name"] = (
            df["side"].astype(str).str.lower()
            .map({"long": "feedback_long", "short": "feedback_short"})
            .fillna("feedback_trade")
        )
    else:
        df["strategy_name"] = "feedback_trade"

    return df[["strategy_name", "setup_success", "signal_strength", "sample_weight"]].reset_index(drop=True)


def run_daily_retrain(
    market_data_path: str | Path,
    feedback_source_path: str | Path,
    feedback_store_path: str | Path,
    model_version: str | None = None,
) -> dict[str, object]:
    """Retrain regime model and setup ranker; use real feedback when available.

    Previously this function called build_sample_candidates() which generates
    synthetic data — the feedback loop was structurally broken.  Now real
    paper-trade outcomes from feedback_store.csv drive the setup ranker when
    sufficient records exist (>= _MIN_FEEDBACK_RECORDS).
    """
    # Step 1 — append new source feedback to the persistent store
    feedback_store = append_feedback_log(feedback_source_path, feedback_store_path)

    # Step 2 — load market data, rebuild features + labels
    market_df  = pd.read_csv(market_data_path)
    feature_df = build_regime_features(market_df)
    labeled    = build_regime_labels(feature_df)

    # Step 3 — retrain regime model (unchanged path)
    regime_model, feature_columns = train_regime_model(labeled)

    # Step 4 — build candidates from REAL feedback (the bug fix)
    feedback_df      = pd.read_csv(feedback_store)
    real_candidates  = _build_candidates_from_feedback(feedback_df, model_version=model_version)

    if len(real_candidates) >= _MIN_FEEDBACK_RECORDS:
        candidates  = real_candidates
        ranker_mode = "real_feedback"
    else:
        # Not enough real trades yet — fall back to synthetic samples
        candidates  = build_sample_candidates(labeled)
        ranker_mode = "synthetic_fallback"

    # Step 5 — train setup ranker and calibrate
    setup_ranker = train_setup_ranker(candidates)
    calibrator   = fit_confidence_calibrator(setup_ranker.score(candidates))

    return {
        "feedback_store":      str(feedback_store),
        "rows":                len(market_df),
        "feature_columns":     feature_columns,
        "calibrator_range":    [calibrator.min_score, calibrator.max_score],
        "available_strategies": sorted(setup_ranker.strategy_scores),
        "regime_centroids":    sorted(regime_model.centroids),
        "ranker_mode":         ranker_mode,
        "n_feedback_records":  len(real_candidates),
        "retrained_at_utc":    datetime.now(timezone.utc).isoformat(),
    }
