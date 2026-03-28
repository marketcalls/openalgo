from __future__ import annotations

from dataclasses import dataclass
import inspect
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from core.interfaces import StrategyRunResult
from strategies.loader import (
    discover_strategy_paths,
    extract_default_constants,
    get_calculate_signature_defaults,
    load_module,
)
from strategies.param_space import build_param_space
from strategies.role_tags import ROLE_TAGS
from strategies.signal_adapter import normalize_strategy_output


@dataclass(slots=True)
class ModuleStrategyWrapper:
    name: str
    module_path: Path
    param_defaults: dict[str, Any]
    param_space: dict[str, list[Any]]
    role_tags: tuple[str, ...]
    unsupported_reason: str | None = None

    def run(self, df: pd.DataFrame, params: Mapping[str, Any] | None = None) -> StrategyRunResult:
        module = load_module(self.module_path)
        if self.unsupported_reason:
            zero_signal = pd.Series(0, index=df.index, dtype=int)
            zero_strength = pd.Series(0.0, index=df.index, dtype=float)
            return StrategyRunResult(
                strategy_name=self.name,
                signal=zero_signal,
                signal_strength=zero_strength,
                trend_state=zero_signal,
                raw_frame=df.copy(),
                adapter_notes=[self.unsupported_reason],
            )

        run_df = df.copy()
        if hasattr(module, "load_csv_data"):
            try:
                if "datetime" in run_df.columns or "timestamp" in run_df.columns:
                    if "timestamp" in run_df.columns:
                        run_df = run_df.copy()
                        run_df.index = pd.to_datetime(run_df["timestamp"], unit="s", utc=True)
                    elif "datetime" in run_df.columns:
                        run_df = run_df.copy()
                        run_df.index = pd.to_datetime(run_df["datetime"], utc=True)
            except Exception:
                pass

        overrides = dict(params or {})
        call_params = _build_call_params(
            strategy_name=self.name,
            module=module,
            df=run_df,
            ast_defaults=self.param_defaults,
            overrides=overrides,
        )
        raw_frame = module.calculate_indicators(run_df, **call_params)
        signal, strength, trend, notes = normalize_strategy_output(self.name, raw_frame)
        return StrategyRunResult(
            strategy_name=self.name,
            signal=signal,
            signal_strength=strength,
            trend_state=trend,
            raw_frame=raw_frame,
            adapter_notes=notes,
        )


def _infer_timeframe_minutes(df: pd.DataFrame) -> int | None:
    timeframe = str(df.get("timeframe").iloc[0]) if "timeframe" in df.columns and not df.empty else ""
    mapping = {
        "1m": 1,
        "3m": 3,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1hr": 60,
        "2hr": 120,
        "4hr": 240,
        "1day": 1440,
        "1month": 43_200,
    }
    return mapping.get(timeframe)


def _default_aliases() -> dict[str, tuple[str, ...]]:
    return {
        "source_column": ("DEFAULT_SOURCE",),
        "filter_mode": ("DEFAULT_FILTER",),
        "len_": ("DEFAULT_LEN",),
        "atr_calc_method": ("DEFAULT_ATR_METHOD",),
        "show_buy_sell_signals": ("DEFAULT_SHOW_BUY_SELL",),
        "show_moving_average_cloud": ("DEFAULT_SHOW_CLOUD",),
    }


def _build_call_params(
    strategy_name: str,
    module,
    df: pd.DataFrame,
    ast_defaults: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> dict[str, Any]:
    signature_defaults = get_calculate_signature_defaults(module)
    signature = inspect.signature(module.calculate_indicators)
    aliases = _default_aliases()

    call_params: dict[str, Any] = {}
    for name, parameter in signature.parameters.items():
        if name == "df":
            continue
        if parameter.default is not inspect._empty:
            call_params[name] = parameter.default

        default_key = f"DEFAULT_{name.upper()}"
        if default_key in ast_defaults:
            call_params[name] = ast_defaults[default_key]
            continue

        for alias_key in aliases.get(name, ()):
            if alias_key in ast_defaults:
                call_params[name] = ast_defaults[alias_key]
                break

    if "timeframe_minutes" in signature.parameters and "timeframe_minutes" not in overrides:
        inferred = _infer_timeframe_minutes(df)
        if inferred is not None:
            call_params["timeframe_minutes"] = inferred

    symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns and not df.empty else ""
    if strategy_name in {"vwap_bb_confluence", "vwap_bb_super_confluence_2", "reversal_radar_v2"}:
        if "symbol" in signature.parameters and symbol:
            call_params["symbol"] = symbol
    if strategy_name == "reversal_radar_v2" and "allow_external_fetch" in signature.parameters:
        call_params["allow_external_fetch"] = False

    for key, value in overrides.items():
        if key in signature.parameters:
            call_params[key] = value
        else:
            translated = key.replace("DEFAULT_", "").lower()
            if translated in signature.parameters:
                call_params[translated] = value

    return call_params


def build_strategy_registry(strategy_root: str | Path) -> dict[str, ModuleStrategyWrapper]:
    registry: dict[str, ModuleStrategyWrapper] = {}
    for path in discover_strategy_paths(strategy_root):
        defaults = extract_default_constants(path)
        module = load_module(path)
        signature_defaults = get_calculate_signature_defaults(module)
        merged_defaults = {**defaults, **{f"DEFAULT_{key.upper()}": value for key, value in signature_defaults.items()}}
        unsupported_reason = None
        if path.stem == "flowscope_hapharmonic":
            unsupported_reason = "Placeholder only: exported data lacks lower-timeframe arrays required for a real signal."
        registry[path.stem] = ModuleStrategyWrapper(
            name=path.stem,
            module_path=path,
            param_defaults=merged_defaults,
            param_space=build_param_space(merged_defaults),
            role_tags=ROLE_TAGS.get(path.stem, ("unclassified",)),
            unsupported_reason=unsupported_reason,
        )
    return registry
