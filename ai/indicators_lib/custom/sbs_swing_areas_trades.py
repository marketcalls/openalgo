"""
# ============================================================
# STRATEGY: SBS + Swing Areas/Trades (Combined)
# Converted from Pine Script v5 | 2026-03-21
# Original Pine author: LuxAlgo (combined derivative)
# ============================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_STRATEGY_NAME = "SBS + Swing Areas/Trades (Combined)"
PINE_SHORT_TITLE = "SBS+AreasTrades (LuxAlgo merge)"
PINE_VERSION = "v5"
PINE_AUTHOR = "LuxAlgo"

# Global constants from Pine.
GREEN = "#089981"
RED = "#F23645"
BULLISH_LEG = 1
BEARISH_LEG = 0
BULLISH_AREA = "BULLISH"
BEARISH_AREA = "BEARISH"
BOTH_AREA = "BOTH"

# Module toggles.
DEFAULT_SHOW_SBS = True
DEFAULT_SHOW_AREAS = True

# SBS defaults.
DEFAULT_SBS_PIVOT_LENGTH = 5
DEFAULT_SBS_INTERNAL_LENGTH = 2
DEFAULT_SBS_POINT4_BEYOND_2 = False
DEFAULT_SBS_DETECT_POINT5 = True
DEFAULT_SBS_STRICT_MODE = True
DEFAULT_SBS_STRICT_THRESHOLD_MULT = 0.50
DEFAULT_SBS_SHOW_PATH = False
DEFAULT_SBS_SHOW_BOX = True
DEFAULT_SBS_SHOW_LINES = True
DEFAULT_SBS_AUTO_COLOR = True

# Areas/trades defaults.
DEFAULT_AREA_PIVOT_LENGTH = 20
DEFAULT_AREA_SELECTION_MODE = BOTH_AREA
DEFAULT_AREA_THRESHOLD_MULT = 4.0
DEFAULT_AREA_MAX_DIST = 200
DEFAULT_AREA_MIN_DIST = 10
DEFAULT_AREA_TP_MULT = 8.0
DEFAULT_AREA_SL_MULT = 4.0
DEFAULT_AREA_SHOW_RANGES = True
DEFAULT_AREA_SHOW_AVG = True
DEFAULT_AREA_SHOW_TP_AREAS = True
DEFAULT_AREA_SHOW_SL_AREAS = True
DEFAULT_AREA_OVERLAPPING_TRADES = False

# Derived strategy defaults.
DEFAULT_INITIAL_CAPITAL = 100_000.0
DEFAULT_COMMISSION_PCT = 0.0
DEFAULT_SLIPPAGE_TICKS = 0
DEFAULT_TICK_SIZE = 0.05
DEFAULT_PYRAMIDING = 0

# Export / validation settings.
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\individual\SBS_SwingAreas_ICT_Unicorn.csv")
MISSING_VALUE_SENTINEL = 1e100
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")
LOGIC_COMPARE_ATOL = 1e-9

# Sample export columns. The TradingView export for this script only exposes
# placeholder plot artifacts; the real strategy logic is internal to this port.
EXPORTED_COLUMNS = (
    "Plot",
    "Plot_colorer",
    "Plot_2",
    "Plot_2_colorer",
)
VALIDATION_COLUMN_ALIASES = {name: (name,) for name in EXPORTED_COLUMNS}

PLOT_COLORER_CODE = 37.0
PLOT_2_COLORER_CODE = 39.0


# -- TYPES ------------------------------------------------------------------
@dataclass
class SBSSwingPoint:
    bar_time: int
    bar_index: int
    price_level: float
    swing: int  # HIGH=1, LOW=0


@dataclass
class SBSSequence:
    points: list[SBSSwingPoint]
    direction: int  # 1=bull, -1=bear
    source: str  # "internal" or "swing"


@dataclass
class Area:
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    end_index: Optional[int] = None
    area_high: float = np.nan
    area_low: float = np.nan
    average_price: float = np.nan
    area_color: str = ""
    touched: bool = False


@dataclass
class Trade:
    trade_id: int
    entry: float
    top: float
    bottom: float
    start_time: int
    end_time: int
    start_line_time: int
    open_trade: bool
    direction: int  # 1=long, -1=short
    tp_price: float
    sl_price: float
    source_area_index: int


# -- LOADING ----------------------------------------------------------------
def _normalize_missing_values(df: pd.DataFrame) -> pd.DataFrame:
    """Replace TradingView-style numeric sentinels with NaN."""
    cleaned = df.copy()
    numeric_columns = cleaned.select_dtypes(include=[np.number]).columns
    if len(numeric_columns) > 0:
        cleaned.loc[:, numeric_columns] = cleaned.loc[:, numeric_columns].mask(
            cleaned.loc[:, numeric_columns] == MISSING_VALUE_SENTINEL,
            np.nan,
        )
    return cleaned


def _attach_timestamp_index(df: pd.DataFrame) -> pd.DataFrame:
    """Create a UTC timestamp index from `timestamp` or `datetime`."""
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
    """Load CSV data, normalize sentinels, and attach a UTC timestamp index."""
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    raw = pd.read_csv(csv_path, low_memory=False)
    raw = _normalize_missing_values(raw)
    return _attach_timestamp_index(raw)


def _require_price_columns(df: pd.DataFrame) -> None:
    """Validate that the input contains required OHLCV columns."""
    missing = [column for column in REQUIRED_PRICE_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            "Input data is missing required OHLCV columns: " + ", ".join(missing)
        )


def _normalize_name(value: str) -> str:
    """Lower-case alphanumeric-only normalization for robust column matching."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _find_matching_sample_column(
    sample_df: pd.DataFrame,
    aliases: Iterable[str],
) -> Optional[str]:
    """Resolve the matching sample column for a calculated output."""
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


def _pine_rma(series: pd.Series, length: int) -> pd.Series:
    """Pine-style Wilder RMA seeded with an initial SMA."""
    out = pd.Series(np.nan, index=series.index, dtype=float)
    if len(series) < length:
        return out
    out.iloc[length - 1] = series.iloc[:length].mean()
    alpha = 1.0 / length
    for i in range(length, len(series)):
        out.iloc[i] = alpha * series.iloc[i] + (1.0 - alpha) * out.iloc[i - 1]
    return out


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Pine-style true range."""
    prev_close = close.shift(1)
    return pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _pine_atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    """Pine-style ATR using Wilder RMA."""
    return _pine_rma(_true_range(high, low, close), length)


def _round_to_mintick(value: float, tick_size: float) -> float:
    """Replicate Pine `math.round_to_mintick` with a configurable tick size."""
    if np.isnan(value):
        return np.nan
    if tick_size <= 0:
        raise ValueError("tick_size must be positive.")
    return round(value / tick_size) * tick_size


def _compare_numeric_series(
    actual: pd.Series,
    expected: pd.Series,
    atol: float = LOGIC_COMPARE_ATOL,
) -> tuple[bool, Optional[pd.Timestamp], float, float, float]:
    """Compare numeric series with NaN support and floating tolerance."""
    actual_values = actual.astype(float).to_numpy()
    expected_values = expected.astype(float).to_numpy()
    comparison = np.isclose(
        actual_values,
        expected_values,
        atol=atol,
        rtol=0.0,
        equal_nan=True,
    )
    if comparison.all():
        return True, None, np.nan, np.nan, 0.0

    mismatch_pos = int(np.flatnonzero(~comparison)[0])
    mismatch_idx = actual.index[mismatch_pos]
    actual_value = actual_values[mismatch_pos]
    expected_value = expected_values[mismatch_pos]
    diff = np.nan if np.isnan(actual_value) or np.isnan(expected_value) else abs(actual_value - expected_value)
    return False, mismatch_idx, actual_value, expected_value, diff


def _max_abs_error(actual: pd.Series, expected: pd.Series) -> float:
    """Return the maximum absolute difference while treating paired NaNs as equal."""
    actual_values = actual.astype(float).to_numpy()
    expected_values = expected.astype(float).to_numpy()
    diffs = np.abs(actual_values - expected_values)
    both_nan = np.isnan(actual_values) & np.isnan(expected_values)
    diffs[both_nan] = 0.0
    diffs[np.isnan(diffs)] = np.inf
    return float(np.max(diffs)) if len(diffs) else 0.0


def _bars_per_year(index: pd.DatetimeIndex) -> float:
    """Infer bars per year from the median observed delta."""
    if len(index) < 2:
        return 252.0
    median_delta = index.to_series().diff().dropna().median()
    if pd.isna(median_delta) or median_delta <= pd.Timedelta(0):
        return 252.0
    return float(pd.Timedelta(days=365) / median_delta)


def _empty_event_arrays(length: int) -> dict[str, np.ndarray]:
    """Initialize entry/exit event arrays."""
    return {
        "long_entry": np.zeros(length, dtype=bool),
        "short_entry": np.zeros(length, dtype=bool),
        "long_exit": np.zeros(length, dtype=bool),
        "short_exit": np.zeros(length, dtype=bool),
        "entry_price": np.full(length, np.nan, dtype=float),
        "exit_price": np.full(length, np.nan, dtype=float),
        "tp_price": np.full(length, np.nan, dtype=float),
        "sl_price": np.full(length, np.nan, dtype=float),
        "signal_area_index": np.full(length, np.nan, dtype=float),
        "trade_id_entry": np.full(length, np.nan, dtype=float),
        "trade_id_exit": np.full(length, np.nan, dtype=float),
        "exit_reason_code": np.full(length, np.nan, dtype=float),
    }


# -- SBS HELPERS ------------------------------------------------------------
def _sbs_inside(
    point: SBSSwingPoint,
    top: SBSSwingPoint,
    bottom: SBSSwingPoint,
) -> bool:
    """Pine `sbs_inside` helper."""
    return point.price_level <= top.price_level and point.price_level >= bottom.price_level


def _sbs_inside_level(point: SBSSwingPoint, top: float, bottom: float) -> bool:
    """Pine `sbs_insideLevel` helper."""
    return point.price_level <= top and point.price_level >= bottom


def _sbs_add_point(
    point: SBSSwingPoint,
    points: list[SBSSwingPoint],
    max_size: int,
) -> None:
    """Append a swing point to a bounded list."""
    if len(points) >= max_size:
        points.pop(0)
    points.append(point)


def _sbs_double_top_bottom(
    point4: SBSSwingPoint,
    top: SBSSwingPoint,
    bottom: SBSSwingPoint,
    internal_points: list[SBSSwingPoint],
    strict_mode: bool,
    strict_threshold: float,
) -> Optional[SBSSwingPoint]:
    """Replicate the Pine point-5 search over internal points."""
    for ip in internal_points:
        if ip.bar_index <= point4.bar_index or ip.swing != point4.swing:
            continue
        if strict_mode:
            if _sbs_inside_level(
                ip,
                point4.price_level + strict_threshold,
                point4.price_level - strict_threshold,
            ):
                return ip
        elif _sbs_inside(ip, top, bottom):
            return ip
    return None


def _sbs_try_add_internal_sequence(
    swing_points: list[SBSSwingPoint],
    internal_points: list[SBSSwingPoint],
    sequences: list[SBSSequence],
    point4_beyond_2: bool,
    detect_point5: bool,
    strict_mode: bool,
    strict_threshold: float,
) -> Optional[SBSSequence]:
    """Try to build a new SBS sequence using internal point-5 detection."""
    if len(swing_points) < 6:
        return None

    A, B, p1, p2, p3, p4 = swing_points[-6:]
    d_top: Optional[SBSSwingPoint] = None
    d_bot: Optional[SBSSwingPoint] = None
    if detect_point5:
        d_top = _sbs_double_top_bottom(
            p4,
            B,
            A,
            internal_points,
            strict_mode,
            strict_threshold,
        )
        d_bot = _sbs_double_top_bottom(
            p4,
            A,
            B,
            internal_points,
            strict_mode,
            strict_threshold,
        )

    bear = (
        p1.swing == 0
        and _sbs_inside(p1, A, p3)
        and _sbs_inside(p2, B, A)
        and (
            _sbs_inside(p4, B, p2)
            if point4_beyond_2
            else _sbs_inside(p4, B, A)
        )
        and ((d_top is not None) if detect_point5 else True)
    )
    bull = (
        p1.swing == 1
        and _sbs_inside(p1, p3, A)
        and _sbs_inside(p2, A, B)
        and (
            _sbs_inside(p4, p2, B)
            if point4_beyond_2
            else _sbs_inside(p4, A, B)
        )
        and ((d_bot is not None) if detect_point5 else True)
    )

    if not bull and not bear:
        return None
    if sequences and sequences[-1].points[0].bar_time >= A.bar_time:
        return None

    points = [A, B, p1, p2, p3, p4]
    if detect_point5:
        points.append(d_bot if bull else d_top)  # type: ignore[arg-type]
    sequence = SBSSequence(points=points, direction=1 if bull else -1, source="internal")
    sequences.append(sequence)
    return sequence


def _sbs_try_add_swing_sequence(
    swing_points: list[SBSSwingPoint],
    sequences: list[SBSSequence],
    point4_beyond_2: bool,
    detect_point5: bool,
    strict_mode: bool,
    strict_threshold: float,
) -> Optional[SBSSequence]:
    """Try to build a new SBS sequence directly from swing points."""
    if len(swing_points) < 8:
        return None

    A, B, p1, p2, p3, p4, p5, p6 = swing_points[-8:]
    bear = (
        p1.swing == 0
        and _sbs_inside(p1, A, p3)
        and _sbs_inside(p2, B, A)
        and (
            _sbs_inside(p4, B, p2)
            if point4_beyond_2
            else _sbs_inside(p4, B, A)
        )
        and (
            _sbs_inside_level(
                p6,
                p4.price_level + strict_threshold,
                p4.price_level - strict_threshold,
            )
            if (detect_point5 and strict_mode)
            else _sbs_inside(p6, B, A)
            if detect_point5
            else True
        )
    )
    bull = (
        p1.swing == 1
        and _sbs_inside(p1, p3, A)
        and _sbs_inside(p2, A, B)
        and (
            _sbs_inside(p4, p2, B)
            if point4_beyond_2
            else _sbs_inside(p4, A, B)
        )
        and (
            _sbs_inside_level(
                p6,
                p4.price_level + strict_threshold,
                p4.price_level - strict_threshold,
            )
            if (detect_point5 and strict_mode)
            else _sbs_inside(p6, A, B)
            if detect_point5
            else True
        )
    )

    if not bull and not bear:
        return None
    if sequences and sequences[-1].points[0].bar_time >= A.bar_time:
        return None

    points = [A, B, p1, p2, p3, p4]
    if detect_point5:
        points.append(p6)
    sequence = SBSSequence(points=points, direction=1 if bull else -1, source="swing")
    sequences.append(sequence)
    return sequence


# -- INDICATOR ENGINE -------------------------------------------------------
def calculate_indicators(
    df: pd.DataFrame,
    show_sbs: bool = DEFAULT_SHOW_SBS,
    show_areas: bool = DEFAULT_SHOW_AREAS,
    sbs_pivot_length: int = DEFAULT_SBS_PIVOT_LENGTH,
    sbs_internal_length: int = DEFAULT_SBS_INTERNAL_LENGTH,
    sbs_point4_beyond_2: bool = DEFAULT_SBS_POINT4_BEYOND_2,
    sbs_detect_point5: bool = DEFAULT_SBS_DETECT_POINT5,
    sbs_strict_mode: bool = DEFAULT_SBS_STRICT_MODE,
    sbs_strict_threshold_mult: float = DEFAULT_SBS_STRICT_THRESHOLD_MULT,
    area_pivot_length: int = DEFAULT_AREA_PIVOT_LENGTH,
    area_selection_mode: str = DEFAULT_AREA_SELECTION_MODE,
    area_threshold_mult: float = DEFAULT_AREA_THRESHOLD_MULT,
    area_max_dist: int = DEFAULT_AREA_MAX_DIST,
    area_min_dist: int = DEFAULT_AREA_MIN_DIST,
    area_tp_mult: float = DEFAULT_AREA_TP_MULT,
    area_sl_mult: float = DEFAULT_AREA_SL_MULT,
    area_overlapping_trades: bool = DEFAULT_AREA_OVERLAPPING_TRADES,
    tick_size: float = DEFAULT_TICK_SIZE,
) -> pd.DataFrame:
    """
    Replicate the combined SBS + Swing Areas/Trades indicator.

    Strategy signals are derived from Module 2 (Swing Areas & Trades). Module 1
    (SBS) is fully ported as analytical state.
    """
    _require_price_columns(df)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("calculate_indicators expects a DataFrame indexed by timestamps.")
    if area_selection_mode not in {BULLISH_AREA, BEARISH_AREA, BOTH_AREA}:
        raise ValueError(
            "area_selection_mode must be one of BULLISH, BEARISH, or BOTH."
        )
    if tick_size <= 0:
        raise ValueError("tick_size must be positive.")

    working = df.copy().sort_index()
    open_ = working["open"].astype(float)
    high = working["high"].astype(float)
    low = working["low"].astype(float)
    close = working["close"].astype(float)

    n = len(working)
    high_values = high.to_numpy(dtype=float)
    low_values = low.to_numpy(dtype=float)
    open_values = open_.to_numpy(dtype=float)
    close_values = close.to_numpy(dtype=float)
    time_values = (
        (working.index.view("int64") // 1_000_000).astype(np.int64)
        if isinstance(working.index, pd.DatetimeIndex)
        else np.arange(n, dtype=np.int64)
    )

    atr20 = _pine_atr(high, low, close, 20)
    atr200 = _pine_atr(high, low, close, 200)
    area_fast_atr_values = atr20.to_numpy(dtype=float)
    area_atr200_values = atr200.to_numpy(dtype=float)
    sbs_strict_threshold_series = atr200 * sbs_strict_threshold_mult
    sbs_strict_threshold_values = sbs_strict_threshold_series.to_numpy(dtype=float)

    plot = np.full(n, np.nan, dtype=float)
    plot_colorer = np.full(n, PLOT_COLORER_CODE, dtype=float)
    plot_2 = np.full(n, np.nan, dtype=float)
    plot_2_colorer = np.full(n, PLOT_2_COLORER_CODE, dtype=float)

    sbs_sequence_detected = np.zeros(n, dtype=bool)
    sbs_sequence_direction = np.full(n, np.nan, dtype=float)
    sbs_sequence_count = np.zeros(n, dtype=int)
    sbs_sequence_source_code = np.full(n, np.nan, dtype=float)
    sbs_sequence_start_index = np.full(n, np.nan, dtype=float)
    sbs_sequence_end_index = np.full(n, np.nan, dtype=float)
    sbs_last_bias = np.zeros(n, dtype=float)
    sbs_point_a = np.full(n, np.nan, dtype=float)
    sbs_point_b = np.full(n, np.nan, dtype=float)
    sbs_point_1 = np.full(n, np.nan, dtype=float)
    sbs_point_2 = np.full(n, np.nan, dtype=float)
    sbs_point_3 = np.full(n, np.nan, dtype=float)
    sbs_point_4 = np.full(n, np.nan, dtype=float)
    sbs_point_5 = np.full(n, np.nan, dtype=float)

    area_average_price = np.full(n, np.nan, dtype=float)
    area_touched = np.zeros(n, dtype=bool)
    area_active_count = np.zeros(n, dtype=int)
    area_long_trigger = np.zeros(n, dtype=bool)
    area_short_trigger = np.zeros(n, dtype=bool)
    area_open_trade = np.zeros(n, dtype=bool)
    area_last_trade_dir = np.zeros(n, dtype=float)
    trade_entry = np.full(n, np.nan, dtype=float)
    trade_tp = np.full(n, np.nan, dtype=float)
    trade_sl = np.full(n, np.nan, dtype=float)

    event_arrays = _empty_event_arrays(n)

    sbs_sequences: list[SBSSequence] = []
    sbs_swing_points: list[SBSSwingPoint] = []
    sbs_internal_points: list[SBSSwingPoint] = []

    area_areas: list[Area] = []
    area_trades: list[Trade] = []
    next_trade_id = 1

    # Persistent Pine-style state.
    sbs_current_leg = 0
    sbs_internal_leg = 0
    sbs_leg_index = 0
    sbs_leg_high = high_values[0]
    sbs_leg_low = low_values[0]
    sbs_leg_time = int(time_values[0])
    sbs_internal_leg_index = 0
    sbs_internal_leg_high = high_values[0]
    sbs_internal_leg_low = low_values[0]
    sbs_internal_leg_time = int(time_values[0])
    last_sbs_bias = 0.0

    area_leg_state = 0

    def area_update_values(area: Area, hi: float = np.nan, lo: float = np.nan) -> None:
        if not np.isnan(hi):
            area.area_high = hi
        if not np.isnan(lo):
            area.area_low = lo

    def area_valid_average(avg: float, current_bar: int, threshold: float) -> bool:
        for idx, area in enumerate(area_areas):
            if idx < len(area_areas) - 1 and not area.touched and area.end_index is not None:
                if current_bar - area.end_index <= area_max_dist:
                    if not np.isnan(area.average_price) and abs(area.average_price - avg) <= threshold:
                        return False
        return True

    def area_update_last(
        current_bar: int,
        leg_index_value: Optional[int],
        leg_time_value: Optional[int],
        threshold: float,
        hi: float = np.nan,
        lo: float = np.nan,
    ) -> None:
        if not area_areas:
            return
        area = area_areas[-1]
        area_update_values(area, hi=hi, lo=lo)
        area.end_index = leg_index_value
        area.end_time = leg_time_value
        if not np.isnan(area.area_high) and not np.isnan(area.area_low):
            area.average_price = _round_to_mintick(
                0.5 * (area.area_high + area.area_low),
                tick_size,
            )
            if not area_valid_average(area.average_price, current_bar, threshold):
                area_areas.pop()

    def area_create(
        leg_time_value: Optional[int],
        color_name: str,
        hi: float = np.nan,
        lo: float = np.nan,
    ) -> None:
        area = Area(start_time=leg_time_value, area_color=color_name)
        area_update_values(area, hi=hi, lo=lo)
        if len(area_areas) >= 165:
            area_areas.pop(0)
        area_areas.append(area)

    def area_cross_over(i: int, level: float) -> bool:
        if i <= 0 or np.isnan(level):
            return False
        return close_values[i - 1] < level and close_values[i] > level

    def area_cross_under(i: int, level: float) -> bool:
        if i <= 0 or np.isnan(level):
            return False
        return close_values[i - 1] > level and close_values[i] < level

    for i in range(n):
        if show_sbs:
            prev_leg = sbs_current_leg
            if high_values[i] == np.max(high_values[max(0, i - sbs_pivot_length + 1):i + 1]):
                sbs_current_leg = BULLISH_LEG
            elif low_values[i] == np.min(low_values[max(0, i - sbs_pivot_length + 1):i + 1]):
                sbs_current_leg = BEARISH_LEG
            sbs_new_pivot = i > 0 and sbs_current_leg != prev_leg
            sbs_pivot_low = i > 0 and (sbs_current_leg - prev_leg) == 1
            sbs_pivot_high = i > 0 and (sbs_current_leg - prev_leg) == -1

            prev_internal_leg = sbs_internal_leg
            if high_values[i] == np.max(high_values[max(0, i - sbs_internal_length + 1):i + 1]):
                sbs_internal_leg = BULLISH_LEG
            elif low_values[i] == np.min(low_values[max(0, i - sbs_internal_length + 1):i + 1]):
                sbs_internal_leg = BEARISH_LEG
            sbs_new_internal_pivot = i > 0 and sbs_internal_leg != prev_internal_leg
            sbs_internal_low = i > 0 and (sbs_internal_leg - prev_internal_leg) == 1
            sbs_internal_high = i > 0 and (sbs_internal_leg - prev_internal_leg) == -1

            if sbs_new_internal_pivot:
                point = SBSSwingPoint(
                    bar_time=sbs_internal_leg_time,
                    bar_index=sbs_internal_leg_index,
                    price_level=sbs_internal_leg_low if sbs_internal_low else sbs_internal_leg_high,
                    swing=0 if sbs_internal_low else 1,
                )
                _sbs_add_point(point, sbs_internal_points, sbs_pivot_length)
                sequence = _sbs_try_add_internal_sequence(
                    sbs_swing_points,
                    sbs_internal_points,
                    sbs_sequences,
                    sbs_point4_beyond_2,
                    sbs_detect_point5,
                    sbs_strict_mode,
                    sbs_strict_threshold_values[i],
                )
                if sequence is not None:
                    sbs_sequence_detected[i] = True
                    sbs_sequence_direction[i] = float(sequence.direction)
                    sbs_sequence_count[i] = len(sbs_sequences)
                    sbs_sequence_source_code[i] = 1.0
                    sbs_sequence_start_index[i] = float(sequence.points[0].bar_index)
                    sbs_sequence_end_index[i] = float(sequence.points[-1].bar_index)
                    sbs_point_a[i] = sequence.points[0].price_level
                    sbs_point_b[i] = sequence.points[1].price_level
                    sbs_point_1[i] = sequence.points[2].price_level
                    sbs_point_2[i] = sequence.points[3].price_level
                    sbs_point_3[i] = sequence.points[4].price_level
                    sbs_point_4[i] = sequence.points[5].price_level
                    if len(sequence.points) > 6:
                        sbs_point_5[i] = sequence.points[6].price_level
                    last_sbs_bias = float(sequence.direction)

            sbs_internal_leg_high = high_values[i] if sbs_internal_low else max(high_values[i], sbs_internal_leg_high)
            sbs_internal_leg_low = low_values[i] if sbs_internal_high else min(low_values[i], sbs_internal_leg_low)
            if (
                (sbs_internal_leg == BULLISH_LEG and sbs_internal_leg_high == high_values[i])
                or (sbs_internal_leg == BEARISH_LEG and sbs_internal_leg_low == low_values[i])
            ):
                sbs_internal_leg_index = i
                sbs_internal_leg_time = int(time_values[i])

            if sbs_new_pivot:
                point = SBSSwingPoint(
                    bar_time=sbs_leg_time,
                    bar_index=sbs_leg_index,
                    price_level=sbs_leg_low if sbs_pivot_low else sbs_leg_high,
                    swing=0 if sbs_pivot_low else 1,
                )
                _sbs_add_point(point, sbs_swing_points, 8)
                sequence = _sbs_try_add_swing_sequence(
                    sbs_swing_points,
                    sbs_sequences,
                    sbs_point4_beyond_2,
                    sbs_detect_point5,
                    sbs_strict_mode,
                    sbs_strict_threshold_values[i],
                )
                if sequence is not None:
                    sbs_sequence_detected[i] = True
                    sbs_sequence_direction[i] = float(sequence.direction)
                    sbs_sequence_count[i] = len(sbs_sequences)
                    sbs_sequence_source_code[i] = 2.0
                    sbs_sequence_start_index[i] = float(sequence.points[0].bar_index)
                    sbs_sequence_end_index[i] = float(sequence.points[-1].bar_index)
                    sbs_point_a[i] = sequence.points[0].price_level
                    sbs_point_b[i] = sequence.points[1].price_level
                    sbs_point_1[i] = sequence.points[2].price_level
                    sbs_point_2[i] = sequence.points[3].price_level
                    sbs_point_3[i] = sequence.points[4].price_level
                    sbs_point_4[i] = sequence.points[5].price_level
                    if len(sequence.points) > 6:
                        sbs_point_5[i] = sequence.points[6].price_level
                    last_sbs_bias = float(sequence.direction)

            sbs_leg_high = high_values[i] if sbs_pivot_low else max(high_values[i], sbs_leg_high)
            sbs_leg_low = low_values[i] if sbs_pivot_high else min(low_values[i], sbs_leg_low)
            if (
                (sbs_current_leg == BULLISH_LEG and sbs_leg_high == high_values[i])
                or (sbs_current_leg == BEARISH_LEG and sbs_leg_low == low_values[i])
            ):
                sbs_leg_index = i
                sbs_leg_time = int(time_values[i])

            sbs_sequence_count[i] = len(sbs_sequences)
            sbs_last_bias[i] = last_sbs_bias
        else:
            sbs_last_bias[i] = last_sbs_bias

        if show_areas:
            threshold = area_threshold_mult * (
                area_fast_atr_values[i] if i < 200 else area_atr200_values[i]
            )
            take_profit = area_tp_mult * (
                area_fast_atr_values[i] if i < 200 else area_atr200_values[i]
            )
            stop_loss = area_sl_mult * (
                area_fast_atr_values[i] if i < 200 else area_atr200_values[i]
            )

            if i >= area_pivot_length:
                leg_index_value: Optional[int] = i - area_pivot_length
                leg_high_value = high_values[i - area_pivot_length]
                leg_low_value = low_values[i - area_pivot_length]
                leg_time_value: Optional[int] = int(time_values[i - area_pivot_length])
                new_high = leg_high_value > np.max(high_values[i - area_pivot_length + 1:i + 1])
                new_low = leg_low_value < np.min(low_values[i - area_pivot_length + 1:i + 1])
            else:
                leg_index_value = None
                leg_high_value = np.nan
                leg_low_value = np.nan
                leg_time_value = None
                new_high = False
                new_low = False

            prev_area_leg = area_leg_state
            if new_high:
                area_leg_state = BEARISH_LEG
            elif new_low:
                area_leg_state = BULLISH_LEG

            start_new_leg = i > 0 and area_leg_state != prev_area_leg
            start_bearish_leg = i > 0 and (area_leg_state - prev_area_leg) == -1
            start_bullish_leg = i > 0 and (area_leg_state - prev_area_leg) == 1

            if start_new_leg:
                if start_bearish_leg:
                    if area_selection_mode == BULLISH_AREA:
                        area_update_last(i, leg_index_value, leg_time_value, threshold, hi=leg_high_value)
                    elif area_selection_mode == BEARISH_AREA:
                        area_create(leg_time_value, RED, hi=leg_high_value)
                    else:
                        area_update_last(i, leg_index_value, leg_time_value, threshold, hi=leg_high_value)
                        area_create(leg_time_value, RED, hi=leg_high_value)

                if start_bullish_leg:
                    if area_selection_mode == BULLISH_AREA:
                        area_create(leg_time_value, GREEN, lo=leg_low_value)
                    elif area_selection_mode == BEARISH_AREA:
                        area_update_last(i, leg_index_value, leg_time_value, threshold, lo=leg_low_value)
                    else:
                        area_update_last(i, leg_index_value, leg_time_value, threshold, lo=leg_low_value)
                        area_create(leg_time_value, GREEN, lo=leg_low_value)

            for area_idx, area in enumerate(area_areas):
                open_trade = area_trades[-1].open_trade if area_trades else False
                blocked = (not area_overlapping_trades) and open_trade
                dist = i - area.end_index if area.end_index is not None else np.inf
                reached = (
                    (dist <= area_max_dist)
                    and (dist >= area_min_dist)
                    and (i > 20)
                    and (not blocked)
                    and (
                        area_cross_over(i, area.average_price)
                        or area_cross_under(i, area.average_price)
                    )
                )
                if not area.touched and reached:
                    area.touched = True
                    area_average_price[i] = area.average_price
                    area_touched[i] = True
                    if area_cross_over(i, area.average_price):
                        tp_price = max(area.average_price - take_profit, 0.0)
                        sl_price = area.average_price + stop_loss
                        trade = Trade(
                            trade_id=next_trade_id,
                            entry=area.average_price,
                            top=sl_price,
                            bottom=tp_price,
                            start_time=int(time_values[i]),
                            end_time=int(time_values[i]),
                            start_line_time=area.start_time if area.start_time is not None else int(time_values[i]),
                            open_trade=True,
                            direction=-1,
                            tp_price=tp_price,
                            sl_price=sl_price,
                            source_area_index=area_idx,
                        )
                        next_trade_id += 1
                        if len(area_trades) >= 165:
                            area_trades.pop(0)
                        area_trades.append(trade)
                        area_short_trigger[i] = True
                        trade_entry[i] = trade.entry
                        trade_tp[i] = trade.tp_price
                        trade_sl[i] = trade.sl_price
                        event_arrays["short_entry"][i] = True
                        event_arrays["entry_price"][i] = trade.entry
                        event_arrays["tp_price"][i] = trade.tp_price
                        event_arrays["sl_price"][i] = trade.sl_price
                        event_arrays["signal_area_index"][i] = float(area_idx)
                        event_arrays["trade_id_entry"][i] = float(trade.trade_id)
                    if area_cross_under(i, area.average_price):
                        tp_price = area.average_price + take_profit
                        sl_price = max(area.average_price - stop_loss, 0.0)
                        trade = Trade(
                            trade_id=next_trade_id,
                            entry=area.average_price,
                            top=tp_price,
                            bottom=sl_price,
                            start_time=int(time_values[i]),
                            end_time=int(time_values[i]),
                            start_line_time=area.start_time if area.start_time is not None else int(time_values[i]),
                            open_trade=True,
                            direction=1,
                            tp_price=tp_price,
                            sl_price=sl_price,
                            source_area_index=area_idx,
                        )
                        next_trade_id += 1
                        if len(area_trades) >= 165:
                            area_trades.pop(0)
                        area_trades.append(trade)
                        area_long_trigger[i] = True
                        trade_entry[i] = trade.entry
                        trade_tp[i] = trade.tp_price
                        trade_sl[i] = trade.sl_price
                        event_arrays["long_entry"][i] = True
                        event_arrays["entry_price"][i] = trade.entry
                        event_arrays["tp_price"][i] = trade.tp_price
                        event_arrays["sl_price"][i] = trade.sl_price
                        event_arrays["signal_area_index"][i] = float(area_idx)
                        event_arrays["trade_id_entry"][i] = float(trade.trade_id)

            for trade in area_trades:
                if not trade.open_trade:
                    continue
                if trade.direction == 1:
                    hit_tp = high_values[i] > trade.tp_price
                    hit_sl = low_values[i] < trade.sl_price
                    exit_price = trade.sl_price if (hit_tp and hit_sl) else trade.tp_price if hit_tp else trade.sl_price
                    exit_reason = 2.0 if (hit_tp and hit_sl) or hit_sl else 1.0
                else:
                    hit_tp = low_values[i] < trade.tp_price
                    hit_sl = high_values[i] > trade.sl_price
                    exit_price = trade.sl_price if (hit_tp and hit_sl) else trade.tp_price if hit_tp else trade.sl_price
                    exit_reason = 2.0 if (hit_tp and hit_sl) or hit_sl else 1.0

                if hit_tp or hit_sl:
                    trade.end_time = int(time_values[i])
                    trade.open_trade = False
                    if trade.direction == 1:
                        event_arrays["long_exit"][i] = True
                    else:
                        event_arrays["short_exit"][i] = True
                    event_arrays["exit_price"][i] = exit_price
                    event_arrays["trade_id_exit"][i] = float(trade.trade_id)
                    event_arrays["exit_reason_code"][i] = exit_reason

            open_trade = area_trades[-1].open_trade if area_trades else False
            area_open_trade[i] = open_trade
            area_active_count[i] = sum(not area.touched for area in area_areas)
            area_last_trade_dir[i] = float(area_trades[-1].direction) if area_trades else 0.0

    out = working.assign(
        Plot=plot,
        Plot_colorer=plot_colorer,
        Plot_2=plot_2,
        Plot_2_colorer=plot_2_colorer,
        sbs_sequence_detected=sbs_sequence_detected,
        sbs_sequence_direction=sbs_sequence_direction,
        sbs_sequence_count=sbs_sequence_count,
        sbs_sequence_source_code=sbs_sequence_source_code,
        sbs_sequence_start_index=sbs_sequence_start_index,
        sbs_sequence_end_index=sbs_sequence_end_index,
        sbs_point_a=sbs_point_a,
        sbs_point_b=sbs_point_b,
        sbs_point_1=sbs_point_1,
        sbs_point_2=sbs_point_2,
        sbs_point_3=sbs_point_3,
        sbs_point_4=sbs_point_4,
        sbs_point_5=sbs_point_5,
        sbs_bias=sbs_last_bias,
        area_average_price=area_average_price,
        area_touched=area_touched,
        area_active_count=area_active_count,
        area_long_trigger=area_long_trigger,
        area_short_trigger=area_short_trigger,
        area_open_trade=area_open_trade,
        area_last_trade_dir=area_last_trade_dir,
        trade_entry=trade_entry,
        trade_tp=trade_tp,
        trade_sl=trade_sl,
        long_entry=event_arrays["long_entry"],
        short_entry=event_arrays["short_entry"],
        long_exit=event_arrays["long_exit"],
        short_exit=event_arrays["short_exit"],
        entry_price=event_arrays["entry_price"],
        exit_price=event_arrays["exit_price"],
        tp_price=event_arrays["tp_price"],
        sl_price=event_arrays["sl_price"],
        signal_area_index=event_arrays["signal_area_index"],
        trade_id_entry=event_arrays["trade_id_entry"],
        trade_id_exit=event_arrays["trade_id_exit"],
        exit_reason_code=event_arrays["exit_reason_code"],
    )
    return out


# -- SIGNAL ENGINE ----------------------------------------------------------
def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return strategy signals derived only from Module 2 (Swing Areas & Trades).

    SBS remains an analytical overlay and is not used for trade gating in v1.
    """
    required = {
        "long_entry",
        "short_entry",
        "long_exit",
        "short_exit",
        "entry_price",
        "exit_price",
        "tp_price",
        "sl_price",
        "signal_area_index",
        "sbs_bias",
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(
            "generate_signals requires calculate_indicators output. Missing columns: "
            + ", ".join(missing)
        )

    out = df.copy()
    out["long_entry"] = out["long_entry"].fillna(False).astype(bool)
    out["short_entry"] = out["short_entry"].fillna(False).astype(bool)
    out["long_exit"] = out["long_exit"].fillna(False).astype(bool)
    out["short_exit"] = out["short_exit"].fillna(False).astype(bool)
    return out


# -- BACKTEST ENGINE --------------------------------------------------------
def backtest(
    df: pd.DataFrame,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    commission_pct: float = DEFAULT_COMMISSION_PCT,
    slippage_ticks: int = DEFAULT_SLIPPAGE_TICKS,
    tick_size: float = DEFAULT_TICK_SIZE,
    pyramiding: int = DEFAULT_PYRAMIDING,
) -> dict:
    """
    Backtest the derived Areas/Trades strategy using area-average fills.

    Because the source is an indicator rather than a Pine strategy, this engine
    uses a fixed derived policy:
    - single-position only
    - entry at the area average price on the signal bar
    - same-bar TP/SL resolution allowed
    - if TP and SL are both touched on the same bar, use the conservative SL
    """
    del pyramiding  # The derived strategy is single-position only.

    required = {
        "close",
        "long_entry",
        "short_entry",
        "long_exit",
        "short_exit",
        "entry_price",
        "exit_price",
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(
            "backtest requires generate_signals output. Missing columns: "
            + ", ".join(missing)
        )

    working = df.copy()
    closes = working["close"].astype(float).to_numpy()
    long_entry = working["long_entry"].fillna(False).to_numpy(dtype=bool)
    short_entry = working["short_entry"].fillna(False).to_numpy(dtype=bool)
    long_exit = working["long_exit"].fillna(False).to_numpy(dtype=bool)
    short_exit = working["short_exit"].fillna(False).to_numpy(dtype=bool)
    entry_prices = working["entry_price"].astype(float).to_numpy()
    exit_prices = working["exit_price"].astype(float).to_numpy()

    commission_rate = commission_pct / 100.0
    slip = slippage_ticks * tick_size
    warmup_bars = max(20, DEFAULT_AREA_PIVOT_LENGTH + 1, DEFAULT_SBS_PIVOT_LENGTH + 1)

    equity = initial_capital
    equity_curve = np.full(len(working), np.nan, dtype=float)
    position = 0
    entry_price = np.nan
    entry_equity = np.nan
    entry_equity_before_commission = np.nan
    entry_bar = -1
    trade_pnls: list[float] = []
    bars_in_trade: list[int] = []

    def mark_to_market(close_price: float) -> float:
        if position == 0 or np.isnan(entry_price) or np.isnan(entry_equity):
            return equity
        return entry_equity * (1.0 + position * ((close_price - entry_price) / entry_price))

    for i in range(len(working)):
        if i >= warmup_bars and position == 0:
            if long_entry[i]:
                if np.isnan(entry_prices[i]):
                    raise ValueError(f"Missing entry_price on long entry at {working.index[i]}")
                entry_equity_before_commission = equity
                equity *= (1.0 - commission_rate)
                entry_equity = equity
                entry_price = entry_prices[i] + slip
                position = 1
                entry_bar = i
            elif short_entry[i]:
                if np.isnan(entry_prices[i]):
                    raise ValueError(f"Missing entry_price on short entry at {working.index[i]}")
                entry_equity_before_commission = equity
                equity *= (1.0 - commission_rate)
                entry_equity = equity
                entry_price = entry_prices[i] - slip
                position = -1
                entry_bar = i

        if position == 1 and long_exit[i]:
            if np.isnan(exit_prices[i]):
                raise ValueError(f"Missing exit_price on long exit at {working.index[i]}")
            exit_price = exit_prices[i] - slip
            realized_equity = entry_equity * (1.0 + ((exit_price - entry_price) / entry_price))
            realized_equity *= (1.0 - commission_rate)
            trade_pnls.append(realized_equity - entry_equity_before_commission)
            bars_in_trade.append(i - entry_bar + 1)
            equity = realized_equity
            position = 0
            entry_price = np.nan
            entry_equity = np.nan
            entry_equity_before_commission = np.nan
            entry_bar = -1
        elif position == -1 and short_exit[i]:
            if np.isnan(exit_prices[i]):
                raise ValueError(f"Missing exit_price on short exit at {working.index[i]}")
            exit_price = exit_prices[i] + slip
            realized_equity = entry_equity * (1.0 - ((exit_price - entry_price) / entry_price))
            realized_equity *= (1.0 - commission_rate)
            trade_pnls.append(realized_equity - entry_equity_before_commission)
            bars_in_trade.append(i - entry_bar + 1)
            equity = realized_equity
            position = 0
            entry_price = np.nan
            entry_equity = np.nan
            entry_equity_before_commission = np.nan
            entry_bar = -1

        equity_curve[i] = mark_to_market(closes[i])

    if position != 0:
        final_close = closes[-1]
        if position == 1:
            exit_price = final_close - slip
            realized_equity = entry_equity * (1.0 + ((exit_price - entry_price) / entry_price))
        else:
            exit_price = final_close + slip
            realized_equity = entry_equity * (1.0 - ((exit_price - entry_price) / entry_price))
        realized_equity *= (1.0 - commission_rate)
        trade_pnls.append(realized_equity - entry_equity_before_commission)
        bars_in_trade.append(len(working) - entry_bar)
        equity = realized_equity
        equity_curve[-1] = equity

    equity_series = pd.Series(equity_curve, index=working.index, name="equity_curve").ffill()
    returns = equity_series.pct_change().fillna(0.0)
    negative_returns = returns.where(returns < 0.0, 0.0)

    years = max(
        (working.index[-1] - working.index[0]).total_seconds() / (365.25 * 24 * 3600),
        1e-9,
    )
    total_return_pct = (equity_series.iloc[-1] / initial_capital - 1.0) * 100.0
    cagr_pct = ((equity_series.iloc[-1] / initial_capital) ** (1.0 / years) - 1.0) * 100.0

    bars_per_year = _bars_per_year(working.index)
    sharpe_ratio = 0.0
    if returns.std(ddof=0) > 0:
        sharpe_ratio = float((returns.mean() / returns.std(ddof=0)) * np.sqrt(bars_per_year))

    sortino_ratio = 0.0
    downside_std = negative_returns.std(ddof=0)
    if downside_std > 0:
        sortino_ratio = float((returns.mean() / downside_std) * np.sqrt(bars_per_year))

    running_max = equity_series.cummax()
    drawdown = equity_series / running_max - 1.0
    max_drawdown_pct = float(drawdown.min() * 100.0)

    total_trades = len(trade_pnls)
    win_rate_pct = (
        float(sum(pnl > 0 for pnl in trade_pnls) / total_trades * 100.0)
        if total_trades
        else 0.0
    )
    gross_profit = float(sum(pnl for pnl in trade_pnls if pnl > 0))
    gross_loss = float(-sum(pnl for pnl in trade_pnls if pnl < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
    avg_bars_in_trade = float(np.mean(bars_in_trade)) if bars_in_trade else 0.0

    return {
        "total_return_pct": float(total_return_pct),
        "cagr_pct": float(cagr_pct),
        "sharpe_ratio": float(sharpe_ratio),
        "sortino_ratio": float(sortino_ratio),
        "max_drawdown_pct": float(max_drawdown_pct),
        "win_rate_pct": float(win_rate_pct),
        "profit_factor": float(profit_factor),
        "total_trades": int(total_trades),
        "avg_bars_in_trade": float(avg_bars_in_trade),
        "equity_curve": equity_series,
    }


# -- VALIDATION -------------------------------------------------------------
def validate_against_sample(
    df: pd.DataFrame,
    sample_path: str | Path,
) -> dict[str, dict[str, object]]:
    """Compare calculated placeholder exports against the sample export value-by-value."""
    sample_df = load_csv_data(sample_path)
    common_index = df.index.intersection(sample_df.index)
    if common_index.empty:
        raise ValueError("No overlapping timestamps found between calculated data and sample file.")

    aligned_df = df.loc[common_index]
    aligned_sample = sample_df.loc[common_index]
    results: dict[str, dict[str, object]] = {}

    for output_name in EXPORTED_COLUMNS:
        sample_column = _find_matching_sample_column(
            aligned_sample,
            VALIDATION_COLUMN_ALIASES[output_name],
        )
        if sample_column is None:
            results[output_name] = {
                "status": "MISSING",
                "sample_column": None,
                "max_err": float("nan"),
            }
            continue

        passed, mismatch_idx, actual_value, expected_value, diff = _compare_numeric_series(
            aligned_df[output_name],
            aligned_sample[sample_column],
            atol=LOGIC_COMPARE_ATOL,
        )
        max_err = _max_abs_error(aligned_df[output_name], aligned_sample[sample_column])
        results[output_name] = {
            "status": "PASS" if passed else "FAIL",
            "sample_column": sample_column,
            "max_err": max_err,
        }
        if not passed:
            raise AssertionError(
                f"Validation failed for {output_name} against sample column {sample_column} at "
                f"{mismatch_idx}: actual={actual_value}, expected={expected_value}, diff={diff}"
            )

    return results


# -- INTERNAL TESTS ---------------------------------------------------------
def run_internal_sanity_checks() -> None:
    """Run deterministic internal checks for the non-exported state machines."""
    idx = pd.date_range("2021-01-01 09:15:00", periods=320, freq="1h", tz="UTC")
    closes = np.linspace(100.0, 130.0, len(idx))
    df = pd.DataFrame(
        {
            "open": closes - 0.5,
            "high": closes + 1.0,
            "low": closes - 1.0,
            "close": closes,
            "volume": np.linspace(1000.0, 2000.0, len(idx)),
        },
        index=idx,
    )

    # Sizing / schema smoke test.
    calculated = calculate_indicators(df)
    required_columns = {
        "sbs_sequence_detected",
        "sbs_bias",
        "area_long_trigger",
        "area_short_trigger",
        "trade_entry",
        "trade_tp",
        "trade_sl",
        "long_entry",
        "short_entry",
        "long_exit",
        "short_exit",
    }
    missing = required_columns - set(calculated.columns)
    assert not missing, f"Missing calculated columns: {sorted(missing)}"

    # Bounded list helpers.
    pts = [SBSSwingPoint(0, i, float(i), i % 2) for i in range(3)]
    _sbs_add_point(SBSSwingPoint(0, 3, 3.0, 1), pts, 3)
    assert len(pts) == 3 and pts[0].bar_index == 1

    # Point-5 detection strict mode.
    p4 = SBSSwingPoint(0, 10, 100.0, 1)
    top = SBSSwingPoint(0, 8, 105.0, 1)
    bottom = SBSSwingPoint(0, 7, 95.0, 0)
    internal = [
        SBSSwingPoint(0, 9, 100.1, 1),
        SBSSwingPoint(0, 11, 100.02, 1),
    ]
    detected = _sbs_double_top_bottom(
        p4,
        top,
        bottom,
        internal,
        strict_mode=True,
        strict_threshold=0.05,
    )
    assert detected is not None and detected.bar_index == 11

    # SBS sequence formation smoke test.
    swing_points = [
        SBSSwingPoint(0, 0, 110.0, 1),
        SBSSwingPoint(0, 1, 100.0, 0),
        SBSSwingPoint(0, 2, 112.0, 1),
        SBSSwingPoint(0, 3, 105.0, 0),
        SBSSwingPoint(0, 4, 115.0, 1),
        SBSSwingPoint(0, 5, 103.0, 0),
    ]
    internal_points = [SBSSwingPoint(0, 6, 103.02, 0)]
    seqs: list[SBSSequence] = []
    seq = _sbs_try_add_internal_sequence(
        swing_points,
        internal_points,
        seqs,
        point4_beyond_2=False,
        detect_point5=True,
        strict_mode=True,
        strict_threshold=0.05,
    )
    assert seq is not None and seq.direction == 1

    # Signal generation / backtest smoke test.
    signals = generate_signals(calculated)
    stats = backtest(signals)
    assert "equity_curve" in stats and len(stats["equity_curve"]) == len(signals)


# -- MAIN -------------------------------------------------------------------
def main(argv: list[str]) -> int:
    """Load a CSV, calculate indicators, validate against sample, and print results."""
    sample_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_SAMPLE_PATH

    df = load_csv_data(sample_path)
    run_internal_sanity_checks()
    calculated = calculate_indicators(df)
    validation = validate_against_sample(calculated, sample_path)
    signals = generate_signals(calculated)
    stats = backtest(signals)

    print(f"Strategy: {PINE_STRATEGY_NAME}")
    print(f"Rows: {len(df)}")
    print("Validation:")
    for column in EXPORTED_COLUMNS:
        result = validation[column]
        print(f"  {column}: {result['status']} (max_err={result['max_err']})")

    print("Notes:")
    print("  SBS state and area/trade objects are implemented from Pine.")
    print("  This sample only validates the limited exported placeholder plot columns.")
    print("Backtest:")
    print(f"  total_return_pct={stats['total_return_pct']:.6f}")
    print(f"  cagr_pct={stats['cagr_pct']:.6f}")
    print(f"  sharpe_ratio={stats['sharpe_ratio']:.6f}")
    print(f"  sortino_ratio={stats['sortino_ratio']:.6f}")
    print(f"  max_drawdown_pct={stats['max_drawdown_pct']:.6f}")
    print(f"  win_rate_pct={stats['win_rate_pct']:.6f}")
    print(f"  profit_factor={stats['profit_factor']:.6f}")
    print(f"  total_trades={stats['total_trades']}")
    print(f"  avg_bars_in_trade={stats['avg_bars_in_trade']:.6f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
