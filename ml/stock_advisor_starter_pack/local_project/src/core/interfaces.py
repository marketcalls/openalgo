from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Mapping, Protocol

import pandas as pd


@dataclass(slots=True)
class StrategyRunResult:
    strategy_name: str
    signal: pd.Series
    signal_strength: pd.Series
    trend_state: pd.Series
    raw_frame: pd.DataFrame
    adapter_notes: list[str] = field(default_factory=list)


class StrategyWrapper(Protocol):
    name: str
    role_tags: tuple[str, ...]
    param_defaults: Mapping[str, Any]
    param_space: Mapping[str, list[Any]]
    unsupported_reason: str | None

    def run(self, df: pd.DataFrame, params: Mapping[str, Any] | None = None) -> StrategyRunResult:
        ...


@dataclass(slots=True)
class Recommendation:
    recommendation_id: str
    symbol: str
    horizon: str
    regime: str
    strategy_combo: list[str]
    parameters: dict[str, dict[str, Any]]
    primary_tf: str
    confirm_tfs: list[str]
    entry: float
    stop_loss: float
    target_1: float
    target_2: float
    confidence: float
    reason_codes: list[str]
    model_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PaperTradeRecord:
    recommendation_id: str
    symbol: str
    horizon: str
    model_version: str
    side: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    quantity: float
    gross_pnl: float
    net_pnl: float
    sl_hit: bool
    tp_hit: bool
    manual_reject: bool = False
    reject_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ModelBundleMetadata:
    model_version: str
    horizon: str
    created_at_utc: str
    feature_columns: list[str]
    training_symbols: list[str]
    notes: str = ""
    artifact_root: str = ""

    @property
    def artifact_path(self) -> Path | None:
        return Path(self.artifact_root) if self.artifact_root else None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
