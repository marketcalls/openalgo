from __future__ import annotations

import numpy as np
import pandas as pd

SIGNAL_PRIORITY = [
    ("buy", 1),
    ("bull", 1),
    ("long", 1),
    ("piercing", 1),       # piercing_line candlestick pattern → bullish
    ("sell", -1),
    ("bear", -1),
    ("short", -1),
    ("dark_cloud", -1),    # dark_cloud_cover candlestick pattern → bearish
    ("dir", 0),
]

# Column name suffixes that indicate visualization/coloring artifacts, not signals.
# These columns hold color codes or continuous palette values and must be skipped.
_COLOR_SUFFIXES = ("_colorer", "_color", "_color_code", "_candle_color", "_bar_color")


def _is_color_column(col: str) -> bool:
    lower = col.lower()
    return any(lower.endswith(suffix) for suffix in _COLOR_SUFFIXES)


def _coerce_series(series: pd.Series, direction_hint: int | None = None) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.astype(int) * (direction_hint or 1)

    if pd.api.types.is_numeric_dtype(series):
        numeric = pd.to_numeric(series, errors="coerce").fillna(0.0)
        if direction_hint is not None:
            return (numeric != 0).astype(int) * direction_hint
        return numeric.apply(lambda value: 1 if value > 0 else (-1 if value < 0 else 0))

    text = series.astype(str).str.strip().str.lower()
    mapped = pd.Series(0, index=series.index, dtype=int)
    mapped.loc[text.isin({"buy", "bull", "long"})] = 1
    mapped.loc[text.isin({"sell", "bear", "short"})] = -1
    return mapped


def _extract_continuous_strength(col_series: pd.Series) -> pd.Series:
    """Return absolute continuous values normalized to [0, 1].

    For binary columns this still returns {0.0, 1.0}, but for strategies that
    emit ATR multiples, z-scores, or band-distance values the result is a genuine
    continuous measure of signal conviction.
    """
    abs_vals = pd.to_numeric(col_series, errors="coerce").abs().fillna(0.0)
    max_val = float(abs_vals.max())
    if max_val > 0:
        return (abs_vals / (max_val + 1e-9)).clip(0.0, 1.0)
    return pd.Series(1.0, index=col_series.index)


def normalize_strategy_output(
    strategy_name: str, frame: pd.DataFrame
) -> tuple[pd.Series, pd.Series, pd.Series, list[str]]:
    notes: list[str] = []
    signal_parts: list[pd.Series] = []
    raw_parts: list[pd.Series] = []   # continuous pre-threshold values used for strength

    for column in frame.columns:
        if _is_color_column(column):
            continue
        lower = column.lower()
        matched = False
        for token, direction in SIGNAL_PRIORITY:
            if token in lower:
                signal_parts.append(
                    _coerce_series(frame[column], None if token == "dir" else direction)
                )
                # Collect the raw continuous values alongside the binarized signal
                raw_parts.append(_extract_continuous_strength(frame[column]))
                matched = True
                break
        if matched:
            continue

        if strategy_name in {"central_pivot_range", "vedhaviyash4_daily_cpr"} and "close" in frame.columns and (
            {"bp", "tp"}.issubset(frame.columns) or {"daily_bc", "daily_tc"}.issubset(frame.columns)
        ):
            close = pd.to_numeric(frame["close"], errors="coerce")
            tp = pd.to_numeric(frame.get("tp", frame.get("daily_tc")), errors="coerce")
            bp = pd.to_numeric(frame.get("bp", frame.get("daily_bc")), errors="coerce")
            signal = pd.Series(0, index=frame.index, dtype=int)
            signal.loc[close > tp] = 1
            signal.loc[close < bp] = -1
            signal_parts.append(signal)
            # Strength: normalized distance from the pivot band boundary
            band_width = (tp - bp).abs()
            band_width = band_width.where(band_width > 0, other=1.0)
            dist = pd.Series(0.0, index=frame.index)
            long_mask  = close > tp
            short_mask = close < bp
            if long_mask.any():
                dist.loc[long_mask]  = ((close - tp) / band_width).clip(0.0, 1.0).loc[long_mask]
            if short_mask.any():
                dist.loc[short_mask] = ((bp - close) / band_width).clip(0.0, 1.0).loc[short_mask]
            raw_parts.append(dist)
            notes.append("Derived signal from pivot band position.")
            break

    # --- Bug fix: vwap_bb_super_confluence_2 outputs upper_reversal / lower_reversal
    # columns that match no token in SIGNAL_PRIORITY.  Detect them explicitly so the
    # strategy is no longer silenced by the adapter.
    if not signal_parts:
        if "lower_reversal" in frame.columns or "upper_reversal" in frame.columns:
            sig = pd.Series(0, index=frame.index, dtype=int)
            if "lower_reversal" in frame.columns:
                sig[frame["lower_reversal"].astype(bool)] = 1
            if "upper_reversal" in frame.columns:
                sig[frame["upper_reversal"].astype(bool)] = -1
            signal_parts.append(sig)
            # Strength: VWAP/BB zone proximity when available, otherwise 1.0
            if "close" in frame.columns and "vwap" in frame.columns:
                vwap = pd.to_numeric(frame["vwap"], errors="coerce")
                close = pd.to_numeric(frame["close"], errors="coerce")
                bb_width_col = next(
                    (c for c in frame.columns if "bb" in c.lower() and "width" in c.lower()),
                    None,
                )
                if bb_width_col:
                    bb_w = pd.to_numeric(frame[bb_width_col], errors="coerce")
                    bb_w = bb_w.where(bb_w > 0, other=1.0)
                    raw_parts.append(((close - vwap).abs() / bb_w).clip(0.0, 1.0))
                else:
                    raw_parts.append(pd.Series(1.0, index=frame.index))
            else:
                raw_parts.append(pd.Series(1.0, index=frame.index))
            notes.append("vwap_bb: extracted from upper_reversal/lower_reversal")

    if not signal_parts:
        signal = pd.Series(0, index=frame.index, dtype=int)
        notes.append("No directional columns found; defaulted to HOLD.")
    else:
        stacked = pd.concat(signal_parts, axis=1).fillna(0)
        aggregate = stacked.sum(axis=1)
        signal = aggregate.apply(
            lambda value: 1 if value > 0 else (-1 if value < 0 else 0)
        ).astype(int)

    # --- Bug fix: strength was always binary {0, 1} because it was derived from the
    # already-binarized signal.  Now use the raw continuous column values so that
    # strategies with ATR-multiple or z-score outputs produce genuine [0, 1] strength.
    if raw_parts:
        stacked_raw = pd.concat(raw_parts, axis=1).fillna(0.0)
        combined_raw = stacked_raw.mean(axis=1)
        max_val = float(combined_raw.max())
        if max_val > 0:
            strength = (combined_raw / (max_val + 1e-9)).clip(0.0, 1.0)
        else:
            strength = pd.Series(1.0, index=frame.index)
    else:
        # No raw parts collected — binary fallback (same as before)
        strength = signal.abs().astype(float)

    trend = signal.replace({0: np.nan}).ffill().fillna(0).astype(int)
    return signal, strength, trend, notes
