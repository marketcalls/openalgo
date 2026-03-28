from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from data.load_symbol_timeframes import TimeframeDataset
from data.timeframe_alignment import align_higher_timeframes
from features.build_regime_features import build_regime_features
from labels.build_regime_labels import build_regime_labels
from labels.build_setup_labels import build_setup_labels
from strategies.registry import ModuleStrategyWrapper


@dataclass(slots=True)
class SwingTrainingArtifacts:
    regime_frame: pd.DataFrame
    candidate_frame: pd.DataFrame
    strategy_notes: dict[str, list[str]]
    selected_strategies: list[str]
    primary_tf: str
    confirm_tfs: list[str]


def _prepare_primary_frame(primary: TimeframeDataset, confirmations: list[TimeframeDataset]) -> pd.DataFrame:
    higher_frames = [(dataset.timeframe, dataset.frame) for dataset in confirmations]
    aligned = align_higher_timeframes(primary.frame, higher_frames)
    aligned = aligned.reset_index().rename(columns={"timestamp_index": "aligned_timestamp"})
    if "timestamp" in aligned.columns:
        aligned["timestamp"] = aligned["timestamp"].astype(int)
    return aligned


def _confirm_agreement(primary_signal: pd.Series, confirm_trend_columns: list[pd.Series]) -> pd.Series:
    if not confirm_trend_columns:
        return pd.Series(1, index=primary_signal.index, dtype=int)
    agreement = pd.Series(1, index=primary_signal.index, dtype=int)
    for trend in confirm_trend_columns:
        agreement &= (((primary_signal >= 0) & (trend >= 0)) | ((primary_signal <= 0) & (trend <= 0))).astype(int)
    return agreement.astype(int)


def build_swing_training_artifacts(
    primary: TimeframeDataset,
    confirmations: list[TimeframeDataset],
    wrappers: Iterable[ModuleStrategyWrapper],
    strategy_params: dict[str, dict] | None = None,
) -> SwingTrainingArtifacts:
    base_frame = _prepare_primary_frame(primary, confirmations)
    regime_frame = build_regime_labels(build_regime_features(base_frame.copy()))

    _strategy_params = strategy_params or {}
    strategy_notes: dict[str, list[str]] = {}
    candidate_rows: list[pd.DataFrame] = []
    selected_strategy_names: list[str] = []

    for wrapper in wrappers:
        selected_strategy_names.append(wrapper.name)
        params = _strategy_params.get(wrapper.name) or None
        try:
            primary_result = wrapper.run(primary.frame, params=params)
        except Exception as exc:
            strategy_notes[wrapper.name] = [f"Primary timeframe run failed: {type(exc).__name__}: {exc}"]
            continue

        confirm_trends: list[pd.Series] = []
        notes = list(primary_result.adapter_notes)
        for dataset in confirmations:
            try:
                confirm_result = wrapper.run(dataset.frame, params=params)
                aligned_trend = pd.merge_asof(
                    primary.frame[["timestamp"]].sort_values("timestamp"),
                    pd.DataFrame(
                        {
                            "timestamp": dataset.frame["timestamp"],
                            f"{wrapper.name}__trend__{dataset.timeframe}": confirm_result.trend_state.values,
                        }
                    ).sort_values("timestamp"),
                    on="timestamp",
                    direction="backward",
                )[f"{wrapper.name}__trend__{dataset.timeframe}"].fillna(0).astype(int)
                confirm_trends.append(aligned_trend)
            except Exception as exc:
                notes.append(f"Confirmation run failed on {dataset.timeframe}: {type(exc).__name__}: {exc}")

        confirm_agreement = _confirm_agreement(primary_result.signal.reset_index(drop=True), confirm_trends)
        candidate = primary.frame.copy().reset_index(drop=True)
        candidate["strategy_name"] = wrapper.name
        candidate["signal"] = primary_result.signal.reset_index(drop=True)
        candidate["signal_strength"] = primary_result.signal_strength.reset_index(drop=True)
        candidate["trend_state"] = primary_result.trend_state.reset_index(drop=True)
        candidate["confirm_agreement"] = confirm_agreement
        candidate["primary_tf"] = primary.timeframe
        candidate["confirm_tfs"] = ",".join([dataset.timeframe for dataset in confirmations])
        candidate["usable_signal"] = candidate["signal"] * candidate["confirm_agreement"]
        candidate["atr_proxy"] = (candidate["high"] - candidate["low"]).rolling(14, min_periods=1).mean().fillna(0.0)
        candidate["parameters"] = "{}"
        candidate = build_setup_labels(candidate, signal_column="usable_signal", lookahead_bars=8)
        candidate_rows.append(candidate)

        regime_frame[f"{wrapper.name}__signal"] = candidate["signal"].values
        regime_frame[f"{wrapper.name}__strength"] = candidate["signal_strength"].values
        regime_frame[f"{wrapper.name}__confirm"] = candidate["confirm_agreement"].values
        strategy_notes[wrapper.name] = notes

    candidate_frame = pd.concat(candidate_rows, ignore_index=True) if candidate_rows else pd.DataFrame()
    return SwingTrainingArtifacts(
        regime_frame=regime_frame,
        candidate_frame=candidate_frame,
        strategy_notes=strategy_notes,
        selected_strategies=selected_strategy_names,
        primary_tf=primary.timeframe,
        confirm_tfs=[dataset.timeframe for dataset in confirmations],
    )
