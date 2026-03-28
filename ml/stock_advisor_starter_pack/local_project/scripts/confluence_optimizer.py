"""
Combined Confluence Optimizer
==============================
Runs ALL strategies with their OPTIMIZED parameters plus vwap_bb
reversal signals, then tests every possible combination (single,
pairs, triples, quadruples, quintuples) to find the highest win rate.

Logic per bar:
  - Each strategy emits: +1 (buy), -1 (sell), 0 (no signal)
  - vwap_bb: lower_reversal -> +1, upper_reversal -> -1
  - For a bar to "fire" a combo: ALL selected strategies must agree
    on the same non-zero direction on that bar.
  - Win: forward 8-bar return moves in the signaled direction.

Output:
  - Full combo table sorted by win rate (all subsets)
  - Top-20 combos
  - Best combo per signal count level
  - Saved CSVs for review
"""

from __future__ import annotations

import json
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from core.constants import DEFAULT_RELIANCE_ROOT, DEFAULT_STRATEGY_ROOT, DEFAULT_ARTIFACTS_ROOT
from data.load_symbol_timeframes import load_symbol_timeframes
from mlops.experiment_tracker import tracker
from strategies.registry import build_strategy_registry

LOOKAHEAD_BARS = 8
MIN_BARS = 8   # minimum signals a combo must produce to be reported

BEST_PARAMS: dict[str, dict[str, Any]] = {
    "twin_range_filter":       {"DEFAULT_PER1": 27, "DEFAULT_MULT1": 1.28, "DEFAULT_PER2": 55, "DEFAULT_MULT2": 1.6},
    "trend_signals_tp_sl_ualgo": {"DEFAULT_MULTIPLIER": 2.6, "DEFAULT_ATR_PERIOD": 10, "DEFAULT_CLOUD_VAL": 7, "DEFAULT_STOP_LOSS_PCT": 1.4},
    "bahai_reversal_points":   {"DEFAULT_LENGTH": 25, "DEFAULT_LOOKBACK_LENGTH": 6, "DEFAULT_THRESHOLD_LEVEL": 0.7},
    "reversal_radar_v2":       {"DEFAULT_BLOCK_START": 16, "DEFAULT_BLOCK_END": 7},
    "central_pivot_range":     {},
}

VWAP_BEST_PARAMS: dict[str, Any] = {
    "atr_pct": 0.15, "bb_k1a": 1.5, "bb_len1": 30,
    "require_double_touch": False, "vwap_k1": 0.5, "vwap_k2": 3.0,
}

ALL_STRATEGIES = list(BEST_PARAMS.keys())


# ── build signal matrix ───────────────────────────────────────────────────────

def get_strategy_signals(wrapper, df: pd.DataFrame, params: dict) -> pd.Series:
    """Return signal Series (+1/-1/0) aligned to df index."""
    try:
        result = wrapper.run(df, params=params)
        sig = result.signal.reset_index(drop=True)
        # Only keep bars where signal != 0
        return sig.astype(int)
    except Exception as exc:
        print(f"  [ERROR] {wrapper.name}: {exc}")
        return pd.Series(0, index=range(len(df)), dtype=int)


def get_vwap_bb_signals(wrapper, df: pd.DataFrame, params: dict) -> pd.Series:
    """Run vwap_bb and extract upper_reversal / lower_reversal as +1/-1."""
    try:
        result = wrapper.run(df, params=params)
        raw = result.raw_frame.reset_index(drop=True)
        sig = pd.Series(0, index=range(len(df)), dtype=int)
        if "lower_reversal" in raw.columns:
            sig[raw["lower_reversal"].astype(bool).values] = 1
        if "upper_reversal" in raw.columns:
            sig[raw["upper_reversal"].astype(bool).values] = -1
        return sig
    except Exception as exc:
        print(f"  [ERROR] vwap_bb: {exc}")
        return pd.Series(0, index=range(len(df)), dtype=int)


def build_signal_matrix(df: pd.DataFrame, registry: dict) -> pd.DataFrame:
    """Wide DataFrame: each column = one strategy's signal per bar."""
    n = len(df)
    matrix = pd.DataFrame(index=range(n))
    matrix["datetime"] = df["datetime"].values
    matrix["close"]    = df["close"].values

    print("  Building signals with optimized params:")
    for name, params in BEST_PARAMS.items():
        if name not in registry:
            print(f"    [SKIP] {name} not in registry")
            continue
        wrapper = registry[name]
        if wrapper.unsupported_reason:
            print(f"    [SKIP] {name}: unsupported")
            continue
        matrix[name] = get_strategy_signals(wrapper, df, params)
        active = (matrix[name] != 0).sum()
        wr_col = name
        print(f"    {name}: {active} bars with signal")

    # vwap_bb reversal
    if "vwap_bb_super_confluence_2" in registry:
        matrix["vwap_bb_reversal"] = get_vwap_bb_signals(
            registry["vwap_bb_super_confluence_2"], df, VWAP_BEST_PARAMS
        )
        active = (matrix["vwap_bb_reversal"] != 0).sum()
        print(f"    vwap_bb_reversal: {active} bars with signal")

    return matrix


# ── label forward success ─────────────────────────────────────────────────────

def add_forward_labels(matrix: pd.DataFrame) -> pd.DataFrame:
    """Add forward_return and per-direction success columns."""
    close = matrix["close"]
    future = close.shift(-LOOKAHEAD_BARS)
    matrix["forward_return"] = ((future - close) / close).fillna(0.0)
    # success_long: price went up
    matrix["success_long"] = (matrix["forward_return"] > 0).astype(int)
    # success_short: price went down
    matrix["success_short"] = (matrix["forward_return"] < 0).astype(int)
    return matrix


# ── evaluate a combination ────────────────────────────────────────────────────

def evaluate_combo(matrix: pd.DataFrame, signal_cols: list[str]) -> dict | None:
    """
    Find bars where ALL listed strategies agree on the same direction.
    Return win rate stats or None if too few signals.
    """
    sub = matrix[signal_cols].copy()

    # Long bars: all cols == +1
    long_mask = (sub == 1).all(axis=1) & (matrix.index < len(matrix) - LOOKAHEAD_BARS)
    # Short bars: all cols == -1
    short_mask = (sub == -1).all(axis=1) & (matrix.index < len(matrix) - LOOKAHEAD_BARS)

    n_long  = long_mask.sum()
    n_short = short_mask.sum()
    n_total = n_long + n_short

    if n_total < MIN_BARS:
        return None

    wr_long  = matrix.loc[long_mask,  "success_long"].mean()  if n_long  > 0 else 0.0
    wr_short = matrix.loc[short_mask, "success_short"].mean() if n_short > 0 else 0.0

    # Combined directional win rate
    wins = 0
    if n_long  > 0: wins += matrix.loc[long_mask,  "success_long"].sum()
    if n_short > 0: wins += matrix.loc[short_mask, "success_short"].sum()
    combined_wr = wins / n_total if n_total > 0 else 0.0

    return {
        "combo":        " + ".join(signal_cols),
        "n_strategies": len(signal_cols),
        "n_total":      int(n_total),
        "n_long":       int(n_long),
        "n_short":      int(n_short),
        "win_rate":     round(combined_wr, 4),
        "wr_long":      round(wr_long, 4),
        "wr_short":     round(wr_short, 4),
    }


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("Loading RELIANCE 15m data ...")
    datasets = load_symbol_timeframes(DEFAULT_RELIANCE_ROOT, symbol="RELIANCE")
    df = datasets["15m"].frame.reset_index(drop=True)

    print("Loading strategy registry ...")
    registry = build_strategy_registry(DEFAULT_STRATEGY_ROOT)

    print("\nBuilding signal matrix (all strategies, optimized params) ...")
    matrix = build_signal_matrix(df, registry)
    matrix = add_forward_labels(matrix)

    # All signal columns (strategy columns only, not datetime/close/etc)
    signal_cols = [c for c in matrix.columns
                   if c not in ("datetime", "close", "forward_return", "success_long", "success_short")]

    print(f"\nSignal columns: {signal_cols}")
    print(f"Total bars: {len(matrix)}\n")

    # ── evaluate all subsets ──────────────────────────────────────────────────
    print("Evaluating all combinations (single -> quintuples) ...")
    rows = []

    for size in range(1, len(signal_cols) + 1):
        for combo in combinations(signal_cols, size):
            result = evaluate_combo(matrix, list(combo))
            if result:
                rows.append(result)

    if not rows:
        print("No valid combinations found.")
        return

    results_df = pd.DataFrame(rows).sort_values("win_rate", ascending=False).reset_index(drop=True)

    # ── print summary ─────────────────────────────────────────────────────────
    print("=" * 70)
    print("TOP 25 COMBINATIONS BY WIN RATE")
    print("=" * 70)
    top = results_df.head(25).copy()
    top["win_rate_%"]  = (top["win_rate"]  * 100).round(1)
    top["wr_long_%"]   = (top["wr_long"]   * 100).round(1)
    top["wr_short_%"]  = (top["wr_short"]  * 100).round(1)
    print(top[["combo", "n_strategies", "n_total", "win_rate_%", "wr_long_%", "wr_short_%"]].to_string(index=False))

    print("\n" + "=" * 70)
    print("BEST COMBO PER STRATEGY COUNT LEVEL")
    print("=" * 70)
    for size in sorted(results_df["n_strategies"].unique()):
        grp = results_df[results_df["n_strategies"] == size]
        best = grp.iloc[0]
        print(f"  {size} strategy/ies: {round(best['win_rate']*100,1)}% win  "
              f"({int(best['n_total'])} signals)  [{best['combo']}]")

    # ── directional breakdown for top combos ──────────────────────────────────
    print("\n" + "=" * 70)
    print("DIRECTIONAL BREAKDOWN — TOP 10 COMBOS")
    print("=" * 70)
    for _, row in results_df.head(10).iterrows():
        combo_cols = row["combo"].split(" + ")
        sub = matrix[combo_cols]
        long_mask  = (sub == 1).all(axis=1)
        short_mask = (sub == -1).all(axis=1)
        print(f"\n  [{row['combo']}]")
        print(f"    Total signals : {row['n_total']}  |  Win rate: {row['win_rate']*100:.1f}%")
        print(f"    LONG  signals : {row['n_long']:4d}  |  Win rate: {row['wr_long']*100:.1f}%")
        print(f"    SHORT signals : {row['n_short']:4d}  |  Win rate: {row['wr_short']*100:.1f}%")

    # ── false signal filter effectiveness ─────────────────────────────────────
    print("\n" + "=" * 70)
    print("FALSE SIGNAL REDUCTION vs ADDING MORE STRATEGY FILTERS")
    print("=" * 70)
    baseline_single = results_df[results_df["n_strategies"] == 1]["win_rate"].mean()
    print(f"  Average win rate with 1 strategy  : {baseline_single*100:.1f}%")
    for size in range(2, len(signal_cols) + 1):
        grp = results_df[results_df["n_strategies"] == size]
        if grp.empty:
            break
        avg = grp["win_rate"].mean()
        best = grp["win_rate"].max()
        count = grp["n_total"].mean()
        print(f"  {size} strategies agree (avg/best)   : {avg*100:.1f}% / {best*100:.1f}%  "
              f"(avg {count:.0f} signals per combo)")

    # ── vwap_bb contribution ───────────────────────────────────────────────────
    if "vwap_bb_reversal" in signal_cols:
        print("\n" + "=" * 70)
        print("VWAP BB REVERSAL CONTRIBUTION — does adding it help?")
        print("=" * 70)
        with_vwap    = results_df[results_df["combo"].str.contains("vwap_bb_reversal")]
        without_vwap = results_df[~results_df["combo"].str.contains("vwap_bb_reversal")]
        for size in sorted(results_df["n_strategies"].unique()):
            w  = with_vwap[with_vwap["n_strategies"] == size]
            wo = without_vwap[without_vwap["n_strategies"] == size]
            if w.empty or wo.empty:
                continue
            print(f"  {size}-combo  WITH vwap_bb: {w['win_rate'].max()*100:.1f}%  "
                  f"WITHOUT vwap_bb: {wo['win_rate'].max()*100:.1f}%  "
                  f"(delta: {(w['win_rate'].max()-wo['win_rate'].max())*100:+.1f}%pts)")

    # ── save ──────────────────────────────────────────────────────────────────
    out_root = DEFAULT_ARTIFACTS_ROOT / "reports" / "confluence_optimizer"
    out_root.mkdir(parents=True, exist_ok=True)

    results_df["win_rate_%"]  = (results_df["win_rate"] * 100).round(1)
    results_df["wr_long_%"]   = (results_df["wr_long"]  * 100).round(1)
    results_df["wr_short_%"]  = (results_df["wr_short"] * 100).round(1)
    results_df.to_csv(out_root / "all_combos.csv", index=False)

    results_df.head(20).to_csv(out_root / "top20_combos.csv", index=False)

    # Save best combo config as JSON for next retraining
    best_row = results_df.iloc[0]
    best_combo_cols = best_row["combo"].split(" + ")
    config = {
        "best_combo": best_combo_cols,
        "win_rate": float(best_row["win_rate"]),
        "n_signals": int(best_row["n_total"]),
        "optimized_strategy_params": BEST_PARAMS,
        "vwap_bb_params": VWAP_BEST_PARAMS,
    }
    (out_root / "best_combo_config.json").write_text(json.dumps(config, indent=2))

    tracker.log_confluence_result(
        top_combo=best_combo_cols,
        top_win_rate=float(best_row["win_rate"]),
        n_signals=int(best_row["n_total"]),
    )
    print(f"\nAll {len(results_df)} combos saved: {out_root / 'all_combos.csv'}")
    print(f"Top 20 saved       : {out_root / 'top20_combos.csv'}")
    print(f"Best config JSON   : {out_root / 'best_combo_config.json'}")


if __name__ == "__main__":
    main()
