"""
# ============================================================
# INDICATOR: Hybrid ML + VWAP + BB
# Converted from Pine Script v5 | 2026-03-21
# Original Pine author: Unknown
# ============================================================
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "Hybrid ML + VWAP + BB"
PINE_SHORT_NAME = "HybridCPR_ML_VWAP_BB"
PINE_VERSION = "v5"

DEFAULT_ENABLE_GLOBAL_ML = True
DEFAULT_ML_MIN_CONFIDENCE = 65.0
DEFAULT_ML_LEARNING_WINDOW = 150
DEFAULT_ML_ADAPTATION_RATE = 0.08

DEFAULT_ATR_LEN = 14
DEFAULT_AVG_VOL_LEN = 20
DEFAULT_EMA_FAST = 9
DEFAULT_EMA_MID = 21
DEFAULT_EMA_SLOW = 50
DEFAULT_RSI_LEN = 14
DEFAULT_BB_LEN = 20
DEFAULT_BB_MULT = 2.0
DEFAULT_BUY_SELL_COOLDOWN = 3
DEFAULT_REVERSAL_COOLDOWN = 5
DEFAULT_SUCCESS_LOOKAHEAD = 10
DEFAULT_TOLERANCE_ATR_PCT = 0.10

DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\individual\HybridCPR_ML_VWAP_BB.csv")
DEFAULT_SYMBOL = "NSE:SBIN"
DEFAULT_TV_WORKDIR = Path(r"D:\TV_proj")
EXCHANGE_TIMEZONE = "Asia/Kolkata"
MISSING_VALUE_SENTINEL = 1e100
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")
NUMERIC_COMPARE_ATOL = 1e-6
FLOAT_COMPARISON_EPS = 1e-9

HEATMAP_CODE_GE_80 = 23
HEATMAP_CODE_GE_70 = 24
HEATMAP_CODE_GE_60 = 25
HEATMAP_CODE_GE_50 = 26
HEATMAP_CODE_LT_50 = 27

COL_BUY_SIGNAL = "Buy_Signal"
COL_SELL_SIGNAL = "Sell_Signal"
COL_UPPER_CONFL = "Upper_Confluence"
COL_LOWER_CONFL = "Lower_Confluence"
COL_HEATMAP = "ML_Confidence_Heatmap"
COL_BUY_CONF = "ML_Buy_Confidence_"
COL_SELL_CONF = "ML_Sell_Confidence_"
COL_CONFL_CONF = "ML_Confluence_Confidence_"
COL_REV_CONF = "ML_Reversal_Confidence_"
COL_SUCCESS_RATE = "ML_Success_Rate_"
COL_WEIGHT_TREND = "ML_Weight_Trend"
COL_WEIGHT_VOLUME = "ML_Weight_Volume"
COL_WEIGHT_DELTA = "ML_Weight_Delta"
COL_HIGH_CONF_BUY = "ML_High_Confidence_BUY"
COL_HIGH_CONF_SELL = "ML_High_Confidence_SELL"
COL_CONFL_DETECTED = "ML_Confluence_Detected"
COL_REV_SIGNAL = "ML_Reversal_Signal"

EXPORTED_COLUMNS = (
    COL_BUY_SIGNAL,
    COL_SELL_SIGNAL,
    COL_UPPER_CONFL,
    COL_LOWER_CONFL,
    COL_HEATMAP,
    COL_BUY_CONF,
    COL_SELL_CONF,
    COL_CONFL_CONF,
    COL_REV_CONF,
    COL_SUCCESS_RATE,
    COL_WEIGHT_TREND,
    COL_WEIGHT_VOLUME,
    COL_WEIGHT_DELTA,
    COL_HIGH_CONF_BUY,
    COL_HIGH_CONF_SELL,
    COL_CONFL_DETECTED,
    COL_REV_SIGNAL,
)

F_PRICE = 0
F_VOLUME = 1
F_TREND = 2
F_VOLATILITY = 3
F_MOMENTUM = 4
F_DELTA = 5
F_CONFLUENCE = 6
F_PATTERN = 7
F_TIME = 8
F_VWAP = 9

FEATURE_NAMES = (
    "price_position",
    "volume_strength",
    "trend_alignment",
    "volatility",
    "momentum",
    "delta_pressure",
    "confluence_score",
    "pattern_strength",
    "time_factor",
    "vwap_distance",
)


@dataclass
class ValidationResult:
    column: str
    passed: bool
    max_error: float
    sample_column: str


# -- LOADING ----------------------------------------------------------------
def _normalize_missing_values(df: pd.DataFrame) -> pd.DataFrame:
    """Replace TradingView's numeric missing-value sentinel with NaN."""
    cleaned = df.copy()
    numeric_columns = cleaned.select_dtypes(include=[np.number]).columns
    if len(numeric_columns) > 0:
        cleaned.loc[:, numeric_columns] = cleaned.loc[:, numeric_columns].mask(
            cleaned.loc[:, numeric_columns] == MISSING_VALUE_SENTINEL,
            np.nan,
        )
    return cleaned


def _attach_timestamp_index(df: pd.DataFrame) -> pd.DataFrame:
    """Attach a UTC DatetimeIndex based on `timestamp` or `datetime`."""
    indexed = df.copy()
    if isinstance(indexed.index, pd.DatetimeIndex):
        dt_index = indexed.index
    elif "timestamp" in indexed.columns:
        dt_index = pd.to_datetime(indexed["timestamp"], unit="s", utc=True)
    elif "datetime" in indexed.columns:
        dt_index = pd.to_datetime(indexed["datetime"], utc=True)
    else:
        raise ValueError(
            "Input data must provide a DatetimeIndex or a `timestamp`/`datetime` column."
        )

    indexed.index = dt_index
    indexed.index.name = "timestamp"
    return indexed.sort_index()


def load_csv_data(path: str | Path) -> pd.DataFrame:
    """Load the TradingView export CSV and normalize sentinels."""
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    raw = pd.read_csv(csv_path, low_memory=False)
    raw = _normalize_missing_values(raw)
    return _attach_timestamp_index(raw)


def _require_price_columns(df: pd.DataFrame) -> None:
    """Verify OHLCV columns are present."""
    missing = [column for column in REQUIRED_PRICE_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            "Input data is missing required OHLCV columns: " + ", ".join(missing)
        )


def _normalize_name(value: str) -> str:
    """Normalize names for robust sample-column matching."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _find_matching_sample_column(
    sample_df: pd.DataFrame,
    aliases: Iterable[str],
) -> Optional[str]:
    """Resolve a sample column using normalized aliases."""
    normalized_columns = {_normalize_name(column): column for column in sample_df.columns}
    for alias in aliases:
        alias_key = _normalize_name(alias)
        if alias_key in normalized_columns:
            return normalized_columns[alias_key]
    return None


# -- CORE HELPERS -----------------------------------------------------------
def _pine_sma(series: pd.Series, length: int) -> pd.Series:
    """Pine-style SMA."""
    return series.rolling(window=length, min_periods=length).mean()


def _pine_ema(series: pd.Series, length: int) -> pd.Series:
    """Pine-style EMA seeded with the first rolling SMA."""
    values = series.astype(float).to_numpy()
    out = np.full(len(values), np.nan, dtype=float)
    seed = series.rolling(window=length, min_periods=length).mean().to_numpy()
    valid_seed = np.flatnonzero(~np.isnan(seed))
    if len(valid_seed) == 0:
        return pd.Series(out, index=series.index, dtype=float)

    start = int(valid_seed[0])
    out[start] = seed[start]
    alpha = 2.0 / (length + 1.0)
    for i in range(start + 1, len(values)):
        if np.isnan(values[i]):
            out[i] = out[i - 1]
        else:
            out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]

    return pd.Series(out, index=series.index, dtype=float)


def _pine_rma(series: pd.Series, length: int) -> pd.Series:
    """Pine-style Wilder RMA seeded with the first rolling SMA."""
    values = series.astype(float).to_numpy()
    seed = series.rolling(window=length, min_periods=length).mean().to_numpy()
    out = np.full(len(values), np.nan, dtype=float)
    valid_seed = np.flatnonzero(~np.isnan(seed))
    if len(valid_seed) == 0:
        return pd.Series(out, index=series.index, dtype=float)

    start = int(valid_seed[0])
    out[start] = seed[start]
    alpha = 1.0 / length
    for i in range(start + 1, len(values)):
        if np.isnan(values[i]):
            out[i] = out[i - 1]
        else:
            out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]

    return pd.Series(out, index=series.index, dtype=float)


def _pine_stdev(series: pd.Series, length: int) -> pd.Series:
    """Pine-style population standard deviation."""
    return series.rolling(window=length, min_periods=length).std(ddof=0)


def _pine_rsi(series: pd.Series, length: int) -> pd.Series:
    """Pine-style RSI built from Wilder RMAs of gains and losses."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = _pine_rma(gain, length)
    avg_loss = _pine_rma(loss, length)

    rsi = pd.Series(np.nan, index=series.index, dtype=float)
    both_zero = (avg_gain == 0) & (avg_loss == 0)
    loss_zero = (avg_loss == 0) & (avg_gain > 0)
    gain_zero = (avg_gain == 0) & (avg_loss > 0)
    normal = ~(both_zero | loss_zero | gain_zero) & avg_gain.notna() & avg_loss.notna()

    rsi.loc[both_zero] = 50.0
    rsi.loc[loss_zero] = 100.0
    rsi.loc[gain_zero] = 0.0
    rsi.loc[normal] = 100.0 - (100.0 / (1.0 + (avg_gain.loc[normal] / avg_loss.loc[normal])))
    return rsi


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Pine-style true range using prior close where available."""
    prev_close = close.shift(1)
    return pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _session_vwap(
    source: pd.Series,
    volume: pd.Series,
    session_dates: pd.Series,
) -> pd.Series:
    """Compute session-reset VWAP equivalent to `ta.vwap(source)` on intraday data."""
    numerator = (source * volume).groupby(session_dates).cumsum()
    denominator = volume.groupby(session_dates).cumsum()
    vwap = numerator / denominator.replace(0.0, np.nan)
    return pd.Series(vwap, index=source.index, dtype=float)


def fetch_tradingview_daily_reference(
    symbol: str,
    bars: int = 2000,
    tradingview_dir: str | Path = DEFAULT_TV_WORKDIR,
) -> pd.DataFrame:
    """Fetch daily TradingView bars through the local Node pipeline environment."""
    node_script = f"""
import 'dotenv/config';
import TradingView from '@mathieuc/tradingview';

const {{ SESSION, SIGNATURE }} = process.env;
const client = new TradingView.Client({{ token: SESSION, signature: SIGNATURE }});
const chart = new client.Session.Chart();

await new Promise((resolve, reject) => {{
  chart.setMarket({json.dumps(symbol)}, {{ timeframe: 'D', range: {int(bars)} }});
  chart.onError((...err) => reject(new Error(err.join(' '))));
  chart.onUpdate(() => {{ if (chart.periods.length > 0) resolve(); }});
}});

const rows = chart.periods.map((bar) => ({{
  timestamp: bar.time,
  datetime: new Date(bar.time * 1000).toISOString(),
  open: bar.open,
  high: bar.max,
  low: bar.min,
  close: bar.close,
  volume: bar.volume,
}}));
client.end();
console.log(JSON.stringify(rows));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", node_script],
        cwd=str(tradingview_dir),
        capture_output=True,
        text=True,
        timeout=90,
        check=True,
    )
    rows = json.loads(result.stdout)
    return _attach_timestamp_index(pd.DataFrame(rows))


def _daily_security_high_low(
    high: pd.Series,
    low: pd.Series,
    session_dates: pd.Series,
    daily_reference: Optional[pd.DataFrame] = None,
) -> tuple[pd.Series, pd.Series]:
    """
    Approximate `request.security(..., "D", high/low, lookahead_off)` for intraday bars.

    If `daily_reference` is provided, use those actual daily OHLC bars. Otherwise fall
    back to daily bars aggregated from the intraday input.
    """
    date_index = pd.Series(session_dates, index=high.index)
    if daily_reference is not None:
        ref = daily_reference.copy()
        ref_local_dates = pd.Series(
            ref.index.tz_convert(EXCHANGE_TIMEZONE).date,
            index=ref.index,
        )
        final_high_by_day = ref.groupby(ref_local_dates)["high"].last()
        final_low_by_day = ref.groupby(ref_local_dates)["low"].last()
    else:
        final_high_by_day = high.groupby(date_index).max()
        final_low_by_day = low.groupby(date_index).min()

    prev_high = date_index.map(final_high_by_day.shift(1))
    prev_low = date_index.map(final_low_by_day.shift(1))
    curr_high = date_index.map(final_high_by_day)
    curr_low = date_index.map(final_low_by_day)
    is_last_bar_of_day = date_index != date_index.shift(-1)
    bar_count_by_day = date_index.value_counts()
    session_bar_counts = date_index.map(bar_count_by_day)
    typical_session_bars = int(bar_count_by_day.mode().iloc[0])
    use_current_day = is_last_bar_of_day & (
        (session_bar_counts >= typical_session_bars) | (session_bar_counts <= 2)
    )

    security_high = prev_high.where(~use_current_day, curr_high)
    security_low = prev_low.where(~use_current_day, curr_low)
    return security_high.astype(float), security_low.astype(float)


def _ternary_with_na(condition: float | bool, true_value: float, false_value: float) -> float:
    """Pine-like ternary that returns NaN when the condition is NaN."""
    if pd.isna(condition):
        return np.nan
    return true_value if bool(condition) else false_value


def _safe_min_cap(value: float, cap: float) -> float:
    """Return min(cap, value) while preserving NaN."""
    if pd.isna(value):
        return np.nan
    return min(cap, value)


def _confidence_to_heatmap_code(confidence: float) -> int:
    """Map confidence to the observed TradingView background export codes."""
    if pd.isna(confidence) or confidence < 50.0:
        return HEATMAP_CODE_LT_50
    if confidence >= 80.0:
        return HEATMAP_CODE_GE_80
    if confidence >= 70.0:
        return HEATMAP_CODE_GE_70
    if confidence >= 60.0:
        return HEATMAP_CODE_GE_60
    return HEATMAP_CODE_GE_50


def _calculate_ml_confidence(
    features: np.ndarray,
    weights: np.ndarray,
    signal_type: str,
) -> float:
    """Replicate the Pine ML confidence scoring function."""
    components = np.full(10, np.nan, dtype=float)

    if signal_type == "BUY":
        components[F_PRICE] = 1.0 - features[F_PRICE]
    elif signal_type == "SELL":
        components[F_PRICE] = features[F_PRICE]
    else:
        components[F_PRICE] = 0.5

    components[F_VOLUME] = _safe_min_cap(features[F_VOLUME] / 1.5, 1.0)

    if signal_type == "BUY":
        components[F_TREND] = max(0.0, features[F_TREND]) if not pd.isna(features[F_TREND]) else np.nan
    elif signal_type == "SELL":
        components[F_TREND] = max(0.0, -features[F_TREND]) if not pd.isna(features[F_TREND]) else np.nan
    else:
        components[F_TREND] = 0.5

    if pd.isna(features[F_VOLATILITY]):
        components[F_VOLATILITY] = np.nan
    elif features[F_VOLATILITY] < 0.3:
        components[F_VOLATILITY] = features[F_VOLATILITY] / 0.3
    else:
        components[F_VOLATILITY] = (1.0 - features[F_VOLATILITY]) / 0.7

    if signal_type == "BUY":
        components[F_MOMENTUM] = (features[F_MOMENTUM] + 1.0) / 2.0
    elif signal_type == "SELL":
        components[F_MOMENTUM] = (1.0 - features[F_MOMENTUM]) / 2.0
    else:
        components[F_MOMENTUM] = 0.5

    if signal_type == "BUY":
        components[F_DELTA] = (
            min(1.0, max(0.0, features[F_DELTA]))
            if not pd.isna(features[F_DELTA])
            else np.nan
        )
    else:
        components[F_DELTA] = (
            min(1.0, max(0.0, -features[F_DELTA]))
            if not pd.isna(features[F_DELTA])
            else np.nan
        )

    components[F_CONFLUENCE] = features[F_CONFLUENCE]
    components[F_PATTERN] = features[F_PATTERN]
    components[F_TIME] = features[F_TIME] - 0.5 if not pd.isna(features[F_TIME]) else np.nan

    if signal_type in {"REVERSAL", "CONFLUENCE"}:
        if pd.isna(features[F_VWAP]):
            components[F_VWAP] = np.nan
        else:
            components[F_VWAP] = 1.0 - min(1.0, features[F_VWAP] / 2.0)
    else:
        components[F_VWAP] = 0.5

    if np.isnan(components).any():
        return np.nan

    total_weight = float(np.sum(weights))
    score = float(np.sum(weights * components))
    confidence = (score / total_weight) * 100.0
    return max(0.0, min(100.0, confidence))


def _update_ml_weights(
    weights: np.ndarray,
    last_features: np.ndarray,
    success: bool,
    adaptation_rate: float,
) -> np.ndarray:
    """Replicate the Pine ML weight adaptation step."""
    updated = weights.copy()
    adj = adaptation_rate if success else -adaptation_rate * 0.3

    transforms = np.array(
        [
            last_features[F_PRICE],
            last_features[F_VOLUME],
            abs(last_features[F_TREND]),
            1.0 - last_features[F_VOLATILITY],
            abs(last_features[F_MOMENTUM]),
            abs(last_features[F_DELTA]),
            last_features[F_CONFLUENCE],
            last_features[F_PATTERN],
            last_features[F_TIME] - 0.5,
            1.0 - last_features[F_VWAP],
        ],
        dtype=float,
    )

    updated = updated * 0.95 + 0.05 * (updated + adj * transforms)
    updated = np.clip(updated, 0.1, 3.0)
    return updated


# -- INDICATOR ENGINE -------------------------------------------------------
def calculate_indicators(
    df: pd.DataFrame,
    enable_global_ml: bool = DEFAULT_ENABLE_GLOBAL_ML,
    ml_min_confidence: float = DEFAULT_ML_MIN_CONFIDENCE,
    ml_learning_window: int = DEFAULT_ML_LEARNING_WINDOW,
    ml_adaptation_rate: float = DEFAULT_ML_ADAPTATION_RATE,
    daily_reference: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Port the full Hybrid ML + VWAP + BB indicator.

    Input df must have: timestamp/index, open, high, low, close, volume.
    Returns a copy with all exported series plus internal debug columns.
    """
    _require_price_columns(df)
    working = df.copy()

    open_ = working["open"].astype(float)
    high = working["high"].astype(float)
    low = working["low"].astype(float)
    close = working["close"].astype(float)
    volume = working["volume"].astype(float)

    local_index = working.index.tz_convert(EXCHANGE_TIMEZONE)
    session_dates = pd.Series(local_index.date, index=working.index)
    local_hours = pd.Series(local_index.hour, index=working.index, dtype=int)

    atr_14 = _pine_rma(_true_range(high, low, close), DEFAULT_ATR_LEN)
    avg_vol_20 = _pine_sma(volume, DEFAULT_AVG_VOL_LEN)
    ema9 = _pine_ema(close, DEFAULT_EMA_FAST)
    ema21 = _pine_ema(close, DEFAULT_EMA_MID)
    ema50 = _pine_ema(close, DEFAULT_EMA_SLOW)
    rsi_14 = _pine_rsi(close, DEFAULT_RSI_LEN)
    bb_basis_20 = _pine_sma(close, DEFAULT_BB_LEN)
    bb_stdev_20 = _pine_stdev(close, DEFAULT_BB_LEN)
    vwap_value = _session_vwap(close, volume, session_dates)
    daily_high, daily_low = _daily_security_high_low(
        high,
        low,
        session_dates,
        daily_reference=daily_reference,
    )

    n = len(working)
    feature_values = np.full((n, len(FEATURE_NAMES)), np.nan, dtype=float)
    weight_values = np.full((n, len(FEATURE_NAMES)), np.nan, dtype=float)

    buy_conf = np.full(n, np.nan, dtype=float)
    sell_conf = np.full(n, np.nan, dtype=float)
    confluence_conf = np.full(n, np.nan, dtype=float)
    reversal_conf = np.full(n, np.nan, dtype=float)
    success_rate_arr = np.full(n, 0.0, dtype=float)

    buy_signal = np.zeros(n, dtype=int)
    sell_signal = np.zeros(n, dtype=int)
    upper_confl_plot = np.zeros(n, dtype=int)
    lower_confl_plot = np.zeros(n, dtype=int)
    high_conf_buy = np.zeros(n, dtype=int)
    high_conf_sell = np.zeros(n, dtype=int)
    confl_detected = np.zeros(n, dtype=int)
    reversal_signal = np.zeros(n, dtype=int)
    heatmap_codes = np.full(n, HEATMAP_CODE_LT_50, dtype=int)

    meet_upper = np.full(n, np.nan, dtype=float)
    meet_lower = np.full(n, np.nan, dtype=float)
    touch_upper_arr = np.zeros(n, dtype=int)
    touch_lower_arr = np.zeros(n, dtype=int)
    upper_reversal_raw = np.zeros(n, dtype=int)
    lower_reversal_raw = np.zeros(n, dtype=int)
    tracked_signal_type = np.full(n, "", dtype=object)
    pending_evaluation = np.zeros(n, dtype=int)
    success_event = np.full(n, np.nan, dtype=float)

    weights = np.ones(len(FEATURE_NAMES), dtype=float)
    success_history: list[float] = []
    last_signal_bar: Optional[int] = None
    last_signal_type: Optional[str] = None
    last_features: Optional[np.ndarray] = None
    last_buy_sell_bar = 0
    last_reversal_bar = 0

    o = open_.to_numpy()
    h = high.to_numpy()
    l = low.to_numpy()
    c = close.to_numpy()
    v = volume.to_numpy()
    atr = atr_14.to_numpy()
    avg_vol = avg_vol_20.to_numpy()
    e9 = ema9.to_numpy()
    e21 = ema21.to_numpy()
    e50 = ema50.to_numpy()
    rsi = rsi_14.to_numpy()
    bb_basis = bb_basis_20.to_numpy()
    bb_std = bb_stdev_20.to_numpy()
    vwap = vwap_value.to_numpy()
    d_high = daily_high.to_numpy()
    d_low = daily_low.to_numpy()
    hours = local_hours.to_numpy()

    for i in range(n):
        if last_signal_bar is not None and (i - last_signal_bar) == DEFAULT_SUCCESS_LOOKAHEAD:
            pending_evaluation[i] = 1
            atr_now = atr[i]
            signal_close = c[i - DEFAULT_SUCCESS_LOOKAHEAD]
            success = False

            if last_signal_type == "BUY" and not pd.isna(atr_now):
                success = c[i] > signal_close + atr_now * 0.5
            elif last_signal_type == "SELL" and not pd.isna(atr_now):
                success = c[i] < signal_close - atr_now * 0.5
            elif last_signal_type == "REVERSAL" and not pd.isna(atr_now):
                success = abs(c[i] - signal_close) > atr_now * 0.3
            elif last_signal_type == "CONFLUENCE" and not pd.isna(atr_now):
                success = abs(c[i] - signal_close) < atr_now * 0.2

            success_history.append(1.0 if success else 0.0)
            if len(success_history) > ml_learning_window:
                success_history.pop(0)

            if last_features is not None:
                weights = _update_ml_weights(weights, last_features, success, ml_adaptation_rate)

            success_event[i] = 1.0 if success else 0.0
            last_signal_bar = None
            last_signal_type = None
            last_features = None

        daily_range = d_high[i] - d_low[i] if not (pd.isna(d_high[i]) or pd.isna(d_low[i])) else np.nan
        price_position = _ternary_with_na(
            daily_range > 0 if not pd.isna(daily_range) else np.nan,
            (c[i] - d_low[i]) / daily_range if not pd.isna(daily_range) else np.nan,
            0.5,
        )

        volume_strength = _ternary_with_na(
            avg_vol[i] > 0 if not pd.isna(avg_vol[i]) else np.nan,
            min(2.0, v[i] / avg_vol[i]) if not pd.isna(avg_vol[i]) else np.nan,
            1.0,
        )

        trend_score = 0.0
        trend_score += 1.0 if e9[i] > e21[i] else -1.0
        trend_score += 1.0 if e21[i] > e50[i] else -1.0
        trend_score += 0.5 if c[i] > e9[i] else -0.5
        trend_alignment = trend_score / 2.5

        volatility = np.nan
        if c[i] > 0:
            raw_volatility = np.nan if pd.isna(atr[i]) else (atr[i] / c[i] * 100.0)
            volatility = _safe_min_cap(raw_volatility, 1.0)

        momentum = (rsi[i] - 50.0) / 50.0 if not pd.isna(rsi[i]) else np.nan

        body = c[i] - o[i]
        candle_range = h[i] - l[i]
        body_ratio = body / candle_range if candle_range > 0 else 0.0
        volume_ratio = v[i] / max(avg_vol[i], 1.0) if not pd.isna(avg_vol[i]) else np.nan
        delta_pressure = body_ratio * volume_ratio if not pd.isna(volume_ratio) else np.nan

        conf_count = 0.0
        bb_dev = bb_std[i] * DEFAULT_BB_MULT if not pd.isna(bb_std[i]) else np.nan
        if (
            not pd.isna(bb_basis[i])
            and not pd.isna(bb_dev)
            and c[i] > bb_basis[i] - bb_dev
            and c[i] < bb_basis[i] + bb_dev
        ):
            conf_count += 1.0
        confluence_score = conf_count / 3.0

        lower_wick = min(o[i], c[i]) - l[i]
        upper_wick = h[i] - max(o[i], c[i])
        is_hammer = lower_wick > (upper_wick * 2.0 + FLOAT_COMPARISON_EPS)
        is_shooting = upper_wick > (lower_wick * 2.0 + FLOAT_COMPARISON_EPS)
        prev_body_abs = abs(c[i - 1] - o[i - 1]) if i >= 1 else np.nan
        is_engulfing = (
            abs(body) > (prev_body_abs * 1.5 + FLOAT_COMPARISON_EPS)
            if not pd.isna(prev_body_abs)
            else False
        )
        pattern_strength = 1.0 if (is_hammer or is_shooting or is_engulfing) else 0.3

        time_factor = 1.2 if ((9 <= hours[i] <= 10) or (14 <= hours[i] <= 15)) else 1.0

        vwap_distance = _ternary_with_na(
            bb_std[i] > 0 if not pd.isna(bb_std[i]) else np.nan,
            abs(c[i] - vwap[i]) / bb_std[i] if not pd.isna(bb_std[i]) and not pd.isna(vwap[i]) else np.nan,
            0.5,
        )

        features = np.array(
            [
                price_position,
                volume_strength,
                trend_alignment,
                volatility,
                momentum,
                delta_pressure,
                confluence_score,
                pattern_strength,
                time_factor,
                vwap_distance,
            ],
            dtype=float,
        )
        feature_values[i] = features

        buy_conf[i] = _calculate_ml_confidence(features, weights, "BUY")
        sell_conf[i] = _calculate_ml_confidence(features, weights, "SELL")
        confluence_conf[i] = _calculate_ml_confidence(features, weights, "CONFLUENCE")
        reversal_conf[i] = _calculate_ml_confidence(features, weights, "REVERSAL")

        vwap_std = bb_std[i] * DEFAULT_BB_MULT if not pd.isna(bb_std[i]) else np.nan
        vwap_up = vwap[i] + vwap_std if not (pd.isna(vwap[i]) or pd.isna(vwap_std)) else np.nan
        vwap_dn = vwap[i] - vwap_std if not (pd.isna(vwap[i]) or pd.isna(vwap_std)) else np.nan
        bb_up = bb_basis[i] + bb_std[i] * DEFAULT_BB_MULT if not (pd.isna(bb_basis[i]) or pd.isna(bb_std[i])) else np.nan
        bb_dn = bb_basis[i] - bb_std[i] * DEFAULT_BB_MULT if not (pd.isna(bb_basis[i]) or pd.isna(bb_std[i])) else np.nan

        bull_base = (
            ((not pd.isna(vwap_dn) and c[i] < vwap_dn) or (not pd.isna(bb_dn) and c[i] < bb_dn))
            and (not pd.isna(avg_vol[i]) and v[i] > avg_vol[i] * 0.8)
        )
        bear_base = (
            ((not pd.isna(vwap_up) and c[i] > vwap_up) or (not pd.isna(bb_up) and c[i] > bb_up))
            and (not pd.isna(avg_vol[i]) and v[i] > avg_vol[i] * 0.8)
        )

        high_buy = bull_base and (
            (not enable_global_ml)
            or (not pd.isna(buy_conf[i]) and buy_conf[i] >= ml_min_confidence)
        )
        high_sell = bear_base and (
            (not enable_global_ml)
            or (not pd.isna(sell_conf[i]) and sell_conf[i] >= ml_min_confidence)
        )

        if (high_buy or high_sell) and (i - last_buy_sell_bar) > DEFAULT_BUY_SELL_COOLDOWN:
            last_buy_sell_bar = i
            last_signal_bar = i
            last_signal_type = "BUY" if high_buy else "SELL"
            last_features = features.copy()

        tolerance = atr[i] * DEFAULT_TOLERANCE_ATR_PCT if not pd.isna(atr[i]) else np.nan

        raw_upper_confl = False
        raw_lower_confl = False
        upper_meet = np.nan
        lower_meet = np.nan

        upper_vw = [vwap_up, vwap_up * 1.01 if not pd.isna(vwap_up) else np.nan]
        lower_vw = [vwap_dn, vwap_dn * 0.99 if not pd.isna(vwap_dn) else np.nan]
        upper_bb = [bb_up, bb_up * 1.01 if not pd.isna(bb_up) else np.nan]
        lower_bb = [bb_dn, bb_dn * 0.99 if not pd.isna(bb_dn) else np.nan]

        for vwu in upper_vw:
            if raw_upper_confl:
                break
            for bbl in lower_bb:
                if (
                    not pd.isna(tolerance)
                    and not pd.isna(vwu)
                    and not pd.isna(bbl)
                    and h[i] >= vwu - tolerance
                    and l[i] <= bbl + tolerance
                ):
                    raw_upper_confl = True
                    upper_meet = (vwu + bbl) / 2.0
                    break

        for vwl in lower_vw:
            if raw_lower_confl:
                break
            for bbu in upper_bb:
                if (
                    not pd.isna(tolerance)
                    and not pd.isna(vwl)
                    and not pd.isna(bbu)
                    and l[i] <= vwl + tolerance
                    and h[i] >= bbu - tolerance
                ):
                    raw_lower_confl = True
                    lower_meet = (vwl + bbu) / 2.0
                    break

        ml_upper_confl = raw_upper_confl and (
            (not enable_global_ml)
            or (not pd.isna(confluence_conf[i]) and confluence_conf[i] >= ml_min_confidence)
        )
        ml_lower_confl = raw_lower_confl and (
            (not enable_global_ml)
            or (not pd.isna(confluence_conf[i]) and confluence_conf[i] >= ml_min_confidence)
        )

        touch_upper = (
            (not pd.isna(tolerance) and not pd.isna(vwap_up) and h[i] >= vwap_up - tolerance)
            or (not pd.isna(tolerance) and not pd.isna(bb_up) and h[i] >= bb_up - tolerance)
        )
        touch_lower = (
            (not pd.isna(tolerance) and not pd.isna(vwap_dn) and l[i] <= vwap_dn + tolerance)
            or (not pd.isna(tolerance) and not pd.isna(bb_dn) and l[i] <= bb_dn + tolerance)
        )
        touch_upper_arr[i] = int(touch_upper)
        touch_lower_arr[i] = int(touch_lower)

        is_up_trend = e21[i] > e50[i]
        upper_reversal = (
            i >= 1
            and bool(touch_upper_arr[i - 1])
            and c[i - 1] > o[i - 1]
            and l[i] < min(l[i - 1], o[i - 1])
            and not is_up_trend
        )
        lower_reversal = (
            i >= 1
            and bool(touch_lower_arr[i - 1])
            and c[i - 1] < o[i - 1]
            and h[i] > max(h[i - 1], o[i - 1])
            and is_up_trend
        )
        upper_reversal_raw[i] = int(upper_reversal)
        lower_reversal_raw[i] = int(lower_reversal)

        ml_upper_reversal = upper_reversal and (
            (not enable_global_ml)
            or (not pd.isna(reversal_conf[i]) and reversal_conf[i] >= ml_min_confidence)
        )
        ml_lower_reversal = lower_reversal and (
            (not enable_global_ml)
            or (not pd.isna(reversal_conf[i]) and reversal_conf[i] >= ml_min_confidence)
        )

        if (ml_upper_reversal or ml_lower_reversal) and (i - last_reversal_bar) > DEFAULT_REVERSAL_COOLDOWN:
            last_reversal_bar = i
            last_signal_bar = i
            last_signal_type = "REVERSAL"
            last_features = features.copy()

        tracked_signal_type[i] = "" if last_signal_type is None else last_signal_type

        confidence_candidates = np.array(
            [buy_conf[i], sell_conf[i], confluence_conf[i], reversal_conf[i]],
            dtype=float,
        )
        current_conf = (
            np.nan if np.isnan(confidence_candidates).all() else float(np.nanmax(confidence_candidates))
        )
        heatmap_codes[i] = _confidence_to_heatmap_code(current_conf)
        success_rate_arr[i] = (
            float(np.mean(success_history) * 100.0) if len(success_history) > 0 else 0.0
        )
        weight_values[i] = weights

        buy_signal[i] = int(high_buy)
        sell_signal[i] = int(high_sell)
        high_conf_buy[i] = int(high_buy)
        high_conf_sell[i] = int(high_sell)
        upper_confl_plot[i] = int(ml_upper_confl)
        lower_confl_plot[i] = int(ml_lower_confl)
        confl_detected[i] = int(ml_upper_confl or ml_lower_confl)
        reversal_signal[i] = int(ml_upper_reversal or ml_lower_reversal)
        meet_upper[i] = upper_meet
        meet_lower[i] = lower_meet

    for idx, feature_name in enumerate(FEATURE_NAMES):
        working[f"feature_{feature_name}"] = feature_values[:, idx]

    working["atr_14"] = atr_14
    working["avg_vol_20"] = avg_vol_20
    working["ema9"] = ema9
    working["ema21"] = ema21
    working["ema50"] = ema50
    working["rsi_14"] = rsi_14
    working["bb_basis_20"] = bb_basis_20
    working["bb_stdev_20"] = bb_stdev_20
    working["vwap_value"] = vwap_value
    working["daily_high_security"] = daily_high
    working["daily_low_security"] = daily_low

    working[COL_BUY_CONF] = buy_conf
    working[COL_SELL_CONF] = sell_conf
    working[COL_CONFL_CONF] = confluence_conf
    working[COL_REV_CONF] = reversal_conf
    working[COL_SUCCESS_RATE] = success_rate_arr
    working[COL_WEIGHT_TREND] = weight_values[:, F_TREND]
    working[COL_WEIGHT_VOLUME] = weight_values[:, F_VOLUME]
    working[COL_WEIGHT_DELTA] = weight_values[:, F_DELTA]
    working[COL_HEATMAP] = heatmap_codes.astype(int)
    working[COL_BUY_SIGNAL] = buy_signal.astype(int)
    working[COL_SELL_SIGNAL] = sell_signal.astype(int)
    working[COL_HIGH_CONF_BUY] = high_conf_buy.astype(int)
    working[COL_HIGH_CONF_SELL] = high_conf_sell.astype(int)
    working[COL_UPPER_CONFL] = upper_confl_plot.astype(int)
    working[COL_LOWER_CONFL] = lower_confl_plot.astype(int)
    working[COL_CONFL_DETECTED] = confl_detected.astype(int)
    working[COL_REV_SIGNAL] = reversal_signal.astype(int)

    working["ml_weight_price"] = weight_values[:, F_PRICE]
    working["ml_weight_volume"] = weight_values[:, F_VOLUME]
    working["ml_weight_trend"] = weight_values[:, F_TREND]
    working["ml_weight_volatility"] = weight_values[:, F_VOLATILITY]
    working["ml_weight_momentum"] = weight_values[:, F_MOMENTUM]
    working["ml_weight_delta"] = weight_values[:, F_DELTA]
    working["ml_weight_confluence"] = weight_values[:, F_CONFLUENCE]
    working["ml_weight_pattern"] = weight_values[:, F_PATTERN]
    working["ml_weight_time"] = weight_values[:, F_TIME]
    working["ml_weight_vwap"] = weight_values[:, F_VWAP]

    working["meet_upper"] = meet_upper
    working["meet_lower"] = meet_lower
    working["touch_upper"] = touch_upper_arr.astype(int)
    working["touch_lower"] = touch_lower_arr.astype(int)
    working["upper_reversal_raw"] = upper_reversal_raw.astype(int)
    working["lower_reversal_raw"] = lower_reversal_raw.astype(int)
    working["tracked_signal_type"] = tracked_signal_type
    working["pending_ml_evaluation"] = pending_evaluation.astype(int)
    working["ml_success_event"] = success_event

    return working


# -- VALIDATION -------------------------------------------------------------
def validate_against_sample(df: pd.DataFrame, sample_path: str | Path) -> list[ValidationResult]:
    """Validate exported columns against the TradingView sample export."""
    sample = load_csv_data(sample_path)
    joined = df.join(sample, how="inner", lsuffix="__calc", rsuffix="__sample")

    results: list[ValidationResult] = []
    failures: list[str] = []

    exact_columns = {
        COL_BUY_SIGNAL,
        COL_SELL_SIGNAL,
        COL_UPPER_CONFL,
        COL_LOWER_CONFL,
        COL_HEATMAP,
        COL_HIGH_CONF_BUY,
        COL_HIGH_CONF_SELL,
        COL_CONFL_DETECTED,
        COL_REV_SIGNAL,
    }

    for column in EXPORTED_COLUMNS:
        sample_column = _find_matching_sample_column(sample, (column,))
        if sample_column is None:
            raise AssertionError(f"Missing expected sample column: {column}")

        calc_series = joined[f"{column}__calc"].astype(float)
        sample_series = joined[f"{sample_column}__sample"].astype(float)

        if column in exact_columns:
            equal = calc_series.fillna(-999999).eq(sample_series.fillna(-999999))
            passed = bool(equal.all())
            max_error = 0.0 if passed else float((calc_series - sample_series).abs().max())
        else:
            diff = (calc_series - sample_series).abs()
            equal = np.isclose(
                calc_series.to_numpy(),
                sample_series.to_numpy(),
                equal_nan=True,
                atol=NUMERIC_COMPARE_ATOL,
                rtol=0.0,
            )
            passed = bool(equal.all())
            max_error = float(np.nanmax(diff.to_numpy())) if np.isfinite(np.nanmax(diff.to_numpy())) else 0.0

        results.append(
            ValidationResult(
                column=column,
                passed=passed,
                max_error=max_error,
                sample_column=sample_column,
            )
        )
        if not passed:
            failures.append(
                f"{column} vs {sample_column} failed validation (max_err={max_error})"
            )

    if failures:
        raise AssertionError("Validation failed:\n" + "\n".join(failures))

    for result in results:
        if result.column in exact_columns:
            print(f"PASS {result.column}: exact")
        else:
            print(f"PASS {result.column}: max_err={result.max_error:.10f}")
    return results


# -- INTERNAL CHECKS --------------------------------------------------------
def run_internal_sanity_checks() -> None:
    """Run deterministic checks on the core helper logic."""
    assert _confidence_to_heatmap_code(np.nan) == HEATMAP_CODE_LT_50
    assert _confidence_to_heatmap_code(49.99) == HEATMAP_CODE_LT_50
    assert _confidence_to_heatmap_code(50.00) == HEATMAP_CODE_GE_50
    assert _confidence_to_heatmap_code(60.00) == HEATMAP_CODE_GE_60
    assert _confidence_to_heatmap_code(70.00) == HEATMAP_CODE_GE_70
    assert _confidence_to_heatmap_code(80.00) == HEATMAP_CODE_GE_80

    ema_test = _pine_ema(pd.Series([1.0, 2.0, 3.0]), 2)
    assert pd.isna(ema_test.iloc[0])
    assert np.isclose(float(ema_test.iloc[1]), 1.5)
    assert np.isclose(float(ema_test.iloc[2]), 2.5, atol=1e-9)

    sample_index = pd.to_datetime(
        [
            "2024-01-01 03:45:00+00:00",
            "2024-01-01 04:45:00+00:00",
            "2024-01-02 03:45:00+00:00",
            "2024-01-02 04:45:00+00:00",
        ]
    )
    sample_dates = pd.Series(sample_index.tz_convert(EXCHANGE_TIMEZONE).date, index=sample_index)
    sample_source = pd.Series([10.0, 20.0, 30.0, 40.0], index=sample_index)
    sample_volume = pd.Series([1.0, 1.0, 2.0, 2.0], index=sample_index)
    sample_vwap = _session_vwap(sample_source, sample_volume, sample_dates)
    assert np.isclose(float(sample_vwap.iloc[0]), 10.0)
    assert np.isclose(float(sample_vwap.iloc[1]), 15.0)
    assert np.isclose(float(sample_vwap.iloc[2]), 30.0)

    sec_high, sec_low = _daily_security_high_low(
        pd.Series([100.0, 110.0, 90.0, 95.0], index=sample_index),
        pd.Series([90.0, 92.0, 80.0, 85.0], index=sample_index),
        sample_dates,
    )
    assert pd.isna(sec_high.iloc[0])
    assert np.isclose(float(sec_high.iloc[1]), 110.0)
    assert np.isclose(float(sec_high.iloc[2]), 110.0)
    assert np.isclose(float(sec_low.iloc[3]), 80.0)

    weight_test = np.ones(10, dtype=float)
    feature_test = np.array([0.5] * 10, dtype=float)
    updated_weights = _update_ml_weights(weight_test, feature_test, True, 0.08)
    assert np.all(updated_weights >= 0.1)
    assert np.all(updated_weights <= 3.0)


# -- MAIN -------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    """Load the sample, calculate the indicator, validate it, and print a summary."""
    args = sys.argv[1:] if argv is None else argv
    sample_path = Path(args[0]) if args else DEFAULT_SAMPLE_PATH
    symbol = args[1] if len(args) > 1 else DEFAULT_SYMBOL

    df = load_csv_data(sample_path)
    daily_reference: Optional[pd.DataFrame] = None
    try:
        daily_reference = fetch_tradingview_daily_reference(symbol)
        print(f"Fetched TradingView daily reference for {symbol}.")
    except Exception as exc:  # pragma: no cover - fallback path
        print(
            "Warning: failed to fetch TradingView daily reference; "
            f"falling back to intraday-aggregated daily bars ({exc})."
        )

    calculated = calculate_indicators(df, daily_reference=daily_reference)
    validate_against_sample(calculated, sample_path)
    run_internal_sanity_checks()

    print("\nSummary")
    print(f"Rows: {len(calculated)}")
    print(f"Buy signals: {int(calculated[COL_BUY_SIGNAL].sum())}")
    print(f"Sell signals: {int(calculated[COL_SELL_SIGNAL].sum())}")
    print(f"Upper confluences: {int(calculated[COL_UPPER_CONFL].sum())}")
    print(f"Lower confluences: {int(calculated[COL_LOWER_CONFL].sum())}")
    print(f"Reversal signals: {int(calculated[COL_REV_SIGNAL].sum())}")
    print(f"Final ML success rate: {float(calculated[COL_SUCCESS_RATE].iloc[-1]):.4f}%")
    print(f"Final weight trend: {float(calculated[COL_WEIGHT_TREND].iloc[-1]):.10f}")
    print(f"Final weight volume: {float(calculated[COL_WEIGHT_VOLUME].iloc[-1]):.10f}")
    print(f"Final weight delta: {float(calculated[COL_WEIGHT_DELTA].iloc[-1]):.10f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
