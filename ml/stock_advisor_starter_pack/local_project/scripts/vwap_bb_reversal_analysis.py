"""
VWAP BB Super Confluence 2 — Reversal Signal Analysis
======================================================
vwap_bb_super_confluence_2 outputs Upper_Confluence / Lower_Confluence
and upper_reversal / lower_reversal boolean columns instead of a
buy/sell column, so the default signal adapter emits zero signals.

This script:
  1. Runs the strategy directly on RELIANCE 15m data.
  2. Extracts all reversal and confluence events.
  3. Checks if each event correctly predicted the actual price direction
     over the next N bars (forward PnL test).
  4. Sweeps key parameters (ATR_PCT, BB lengths, VWAP K factors) to find
     the combo that maximises reversal prediction accuracy.
  5. Saves detailed event CSV + parameter sweep summary.

Interpretation:
  upper_reversal = True  -> bearish signal (price at upper band, expect down)
  lower_reversal = True  -> bullish signal (price at lower band, expect up)
  Upper_Confluence       -> zone detection (not yet a confirmed reversal)
  Lower_Confluence       -> zone detection (not yet a confirmed reversal)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from core.constants import DEFAULT_RELIANCE_ROOT, DEFAULT_STRATEGY_ROOT, DEFAULT_ARTIFACTS_ROOT
from data.load_symbol_timeframes import load_symbol_timeframes
from strategies.registry import build_strategy_registry

LOOKAHEAD_BARS = 8
MIN_EVENTS = 5

# ── helpers ──────────────────────────────────────────────────────────────────

def run_vwap_bb(wrapper, df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame | None:
    """Run strategy and return raw_frame with reversal/confluence cols."""
    try:
        result = wrapper.run(df, params=params)
        raw = result.raw_frame.copy()
        raw["close_orig"] = df["close"].values
        raw["high_orig"]  = df["high"].values
        raw["low_orig"]   = df["low"].values
        return raw
    except Exception as exc:
        print(f"    ERROR: {exc}")
        return None


def label_reversals(raw: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """
    Build an event table where each row is a reversal/confluence event.
    side: +1 = bullish (lower band), -1 = bearish (upper band)
    forward_return: actual close change over next LOOKAHEAD_BARS
    success: 1 if price moved in the signalled direction
    """
    close = df["close"].reset_index(drop=True)
    datetimes = df["datetime"].reset_index(drop=True) if "datetime" in df.columns else None
    raw_reset = raw.reset_index(drop=True)

    events = []
    for col, side, label in [
        ("upper_reversal",   -1, "upper_reversal_bearish"),
        ("lower_reversal",   +1, "lower_reversal_bullish"),
        ("Upper_Confluence", -1, "upper_confluence_zone"),
        ("Lower_Confluence", +1, "lower_confluence_zone"),
    ]:
        if col not in raw_reset.columns:
            continue
        pos_indices = raw_reset.index[raw_reset[col].astype(bool)].tolist()
        for pos in pos_indices:
            if pos + LOOKAHEAD_BARS >= len(close):
                continue
            fwd_return = (close.iloc[pos + LOOKAHEAD_BARS] - close.iloc[pos]) / close.iloc[pos]
            success = int(fwd_return * side > 0)
            events.append({
                "event_type": label,
                "side": side,
                "bar_index": pos,
                "datetime": datetimes.iloc[pos] if datetimes is not None else pos,
                "close": close.iloc[pos],
                "forward_return_pct": round(fwd_return * 100, 4),
                "success": success,
            })

    return pd.DataFrame(events) if events else pd.DataFrame()


def summarise_events(events: pd.DataFrame) -> dict[str, Any]:
    if events.empty:
        return {}
    summary = {}
    for event_type, grp in events.groupby("event_type"):
        summary[event_type] = {
            "count": len(grp),
            "win_rate": round(grp["success"].mean(), 4),
            "avg_fwd_return_pct": round(grp["forward_return_pct"].mean(), 4),
        }
    return summary


# ── parameter sweep ───────────────────────────────────────────────────────────

# Key params to sweep (chosen because they govern band width / sensitivity)
PARAM_GRID = {
    "atr_pct":    [0.05, 0.08, 0.10, 0.12, 0.15, 0.20],
    "bb_len1":    [10, 14, 20, 26, 30],
    "bb_k1a":    [0.5, 1.0, 1.5, 2.0],
    "vwap_k1":   [0.5, 1.0, 1.5, 2.0],
    "vwap_k2":   [1.5, 2.0, 2.5, 3.0],
    "require_double_touch": [True, False],
}


def sweep_params(wrapper, df: pd.DataFrame) -> pd.DataFrame:
    """One-at-a-time sweep for each key parameter."""
    rows = []
    for param_name, values in PARAM_GRID.items():
        for val in values:
            raw = run_vwap_bb(wrapper, df, {param_name: val})
            if raw is None:
                continue
            events = label_reversals(raw, df)
            if events.empty:
                continue
            # Focus on confirmed reversals only
            rev = events[events["event_type"].isin(["upper_reversal_bearish", "lower_reversal_bullish"])]
            if len(rev) < MIN_EVENTS:
                continue
            rows.append({
                "param": param_name,
                "value": val,
                "reversal_events": len(rev),
                "reversal_win_rate": round(rev["success"].mean(), 4),
                "all_events": len(events),
                "all_win_rate": round(events["success"].mean(), 4),
            })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("Loading RELIANCE 15m data …")
    datasets = load_symbol_timeframes(DEFAULT_RELIANCE_ROOT, symbol="RELIANCE")
    df = datasets["15m"].frame.reset_index(drop=True)

    print("Loading strategy registry …")
    registry = build_strategy_registry(DEFAULT_STRATEGY_ROOT)

    name = "vwap_bb_super_confluence_2"
    if name not in registry:
        print(f"ERROR: {name} not found in registry at {DEFAULT_STRATEGY_ROOT}")
        return

    wrapper = registry[name]
    output_root = DEFAULT_ARTIFACTS_ROOT / "reports" / "vwap_bb_analysis"
    output_root.mkdir(parents=True, exist_ok=True)

    # ── 1. Default run ────────────────────────────────────────────────────────
    print("\n--- Running with default parameters ---")
    raw_default = run_vwap_bb(wrapper, df, {})
    if raw_default is None:
        print("Strategy run failed with defaults.")
        return

    # Show what columns are produced
    signal_cols = [c for c in raw_default.columns if any(
        kw in c.lower() for kw in ["reversal", "confluence", "signal", "buy", "sell", "touch"]
    )]
    print(f"Signal columns produced: {signal_cols}")

    events_default = label_reversals(raw_default, df)
    summary_default = summarise_events(events_default)

    print("\n=== DEFAULT PARAMETER RESULTS ===")
    if not summary_default:
        print("  No events detected with default parameters.")
    for event_type, stats in summary_default.items():
        print(f"  {event_type:35s}  count={stats['count']:4d}  "
              f"win_rate={stats['win_rate']:.3f}  "
              f"avg_fwd_ret={stats['avg_fwd_return_pct']:+.3f}%")

    if not events_default.empty:
        events_default.to_csv(output_root / "events_default_params.csv", index=False)
        print(f"\nEvent detail CSV -> {output_root / 'events_default_params.csv'}")

    # ── 2. Parameter sweep ────────────────────────────────────────────────────
    print("\n--- Running parameter sweep (one-at-a-time) ---")
    sweep_df = sweep_params(wrapper, df)

    if sweep_df.empty:
        print("  Parameter sweep produced no valid results.")
    else:
        sweep_df = sweep_df.sort_values("reversal_win_rate", ascending=False)
        print("\n=== PARAMETER SWEEP — TOP RESULTS (sorted by reversal win rate) ===")
        print(sweep_df.head(20).to_string(index=False))
        sweep_df.to_csv(output_root / "param_sweep.csv", index=False)
        print(f"\nFull sweep CSV -> {output_root / 'param_sweep.csv'}")

        # Best value per parameter
        best_per_param: dict[str, Any] = {}
        for param, grp in sweep_df.groupby("param"):
            best_row = grp.loc[grp["reversal_win_rate"].idxmax()]
            best_per_param[param] = best_row["value"]
        print(f"\nBest value per param: {best_per_param}")

        # ── 3. Combined best run ──────────────────────────────────────────────
        print("\n--- Running with combined best parameters ---")
        raw_best = run_vwap_bb(wrapper, df, best_per_param)
        if raw_best is not None:
            events_best = label_reversals(raw_best, df)
            summary_best = summarise_events(events_best)
            print("\n=== COMBINED BEST PARAMETER RESULTS ===")
            for event_type, stats in summary_best.items():
                print(f"  {event_type:35s}  count={stats['count']:4d}  "
                      f"win_rate={stats['win_rate']:.3f}  "
                      f"avg_fwd_ret={stats['avg_fwd_return_pct']:+.3f}%")
            if not events_best.empty:
                events_best.to_csv(output_root / "events_best_params.csv", index=False)

        # Save best params
        best_json = output_root / "vwap_bb_best_params.json"
        best_json.write_text(json.dumps(best_per_param, indent=2))
        print(f"\nBest params JSON -> {best_json}")

    # ── 4. Confluence vs Reversal comparison ──────────────────────────────────
    if not events_default.empty:
        print("\n=== CONFLUENCE ZONE vs CONFIRMED REVERSAL (default params) ===")
        comp = events_default.groupby("event_type").agg(
            count=("success", "count"),
            win_rate=("success", "mean"),
            avg_fwd_pct=("forward_return_pct", "mean"),
        ).reset_index()
        comp["win_rate"] = (comp["win_rate"] * 100).round(1)
        comp["avg_fwd_pct"] = comp["avg_fwd_pct"].round(3)
        print(comp.to_string(index=False))
        print("\nNote: 'reversal' = confirmed price touch + reversal bar")
        print("      'confluence' = zone entered (early warning, lower precision)")


if __name__ == "__main__":
    main()
