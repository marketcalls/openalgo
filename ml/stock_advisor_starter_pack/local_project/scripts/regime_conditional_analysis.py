"""
Regime-Conditional Win Rate Analysis
=====================================
Tests Hypothesis 1 from AI_RESEARCH_PROMPT.md:
  "Filtering flat-regime signals will push win rates up 5-15%pts"

Builds signal matrix with OPTIMIZED params, joins regime labels from the
saved regime_frame.csv, then computes win rates broken down by:

  1. Strategy x Regime x Direction  -- the full 3D conditional table
  2. Combo x Regime filter          -- all combos re-evaluated under each filter
  3. Morning session (09-10 IST) vs all-day comparison
  4. Combined filter: non-flat regime + morning session

Run:
  cd D:/ml/stock_advisor_starter_pack/local_project
  export PYTHONPATH=D:/ml/stock_advisor_starter_pack/local_project/src
  python scripts/regime_conditional_analysis.py
"""

from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from core.constants import (
    DEFAULT_ARTIFACTS_ROOT,
    DEFAULT_RELIANCE_ROOT,
    DEFAULT_STRATEGY_ROOT,
    INDIA_TIMEZONE,
)
from data.load_symbol_timeframes import load_symbol_timeframes
from strategies.registry import build_strategy_registry

# ── constants ─────────────────────────────────────────────────────────────────

LOOKAHEAD_BARS   = 8
MIN_BARS_DISPLAY = 5   # suppress rows with fewer signals than this
MIN_BARS_TRUST   = 30  # flag rows below this as low-confidence

BEST_PARAMS: dict[str, dict[str, Any]] = {
    "twin_range_filter":         {"DEFAULT_PER1": 27, "DEFAULT_MULT1": 1.28,
                                  "DEFAULT_PER2": 55, "DEFAULT_MULT2": 1.6},
    "trend_signals_tp_sl_ualgo": {"DEFAULT_MULTIPLIER": 2.6, "DEFAULT_ATR_PERIOD": 10,
                                  "DEFAULT_CLOUD_VAL": 7, "DEFAULT_STOP_LOSS_PCT": 1.4},
    "bahai_reversal_points":     {"DEFAULT_LENGTH": 25, "DEFAULT_LOOKBACK_LENGTH": 6,
                                  "DEFAULT_THRESHOLD_LEVEL": 0.7},
    "reversal_radar_v2":         {"DEFAULT_BLOCK_START": 16, "DEFAULT_BLOCK_END": 7},
    "central_pivot_range":       {},
}

VWAP_BEST_PARAMS: dict[str, Any] = {
    "atr_pct": 0.15, "bb_k1a": 1.5, "bb_len1": 30,
    "require_double_touch": False, "vwap_k1": 0.5, "vwap_k2": 3.0,
}

REPORTS_ROOT = DEFAULT_ARTIFACTS_ROOT / "reports"

SHORT_NAMES = {
    "twin_range_filter":           "twin_range",
    "trend_signals_tp_sl_ualgo":   "trend_signals",
    "bahai_reversal_points":       "bahai",
    "reversal_radar_v2":           "reversal_radar",
    "central_pivot_range":         "cpr",
    "vwap_bb_reversal":            "vwap_bb",
}


# ── signal matrix ─────────────────────────────────────────────────────────────

def _get_signals(wrapper, df: pd.DataFrame, params: dict) -> pd.Series:
    try:
        return wrapper.run(df, params=params).signal.reset_index(drop=True).astype(int)
    except Exception as e:
        print(f"  [ERROR] {wrapper.name}: {e}")
        return pd.Series(0, index=range(len(df)), dtype=int)


def _get_vwap_bb_signals(wrapper, df: pd.DataFrame, params: dict) -> pd.Series:
    try:
        raw = wrapper.run(df, params=params).raw_frame.reset_index(drop=True)
        sig = pd.Series(0, index=range(len(df)), dtype=int)
        if "lower_reversal" in raw.columns:
            sig[raw["lower_reversal"].astype(bool).values] = 1
        if "upper_reversal" in raw.columns:
            sig[raw["upper_reversal"].astype(bool).values] = -1
        return sig
    except Exception as e:
        print(f"  [ERROR] vwap_bb: {e}")
        return pd.Series(0, index=range(len(df)), dtype=int)


def build_signal_matrix(df: pd.DataFrame, registry: dict) -> pd.DataFrame:
    matrix = pd.DataFrame(index=range(len(df)))
    matrix["datetime"] = pd.to_datetime(df["datetime"].values, utc=True)
    matrix["close"]    = df["close"].values

    print("  Signals (optimized params):")
    for name, params in BEST_PARAMS.items():
        wrapper = registry.get(name)
        if wrapper is None:
            print(f"    [SKIP] {name} not in registry")
            continue
        if wrapper.unsupported_reason:
            print(f"    [SKIP] {name}: unsupported")
            continue
        matrix[name] = _get_signals(wrapper, df, params)
        n = (matrix[name] != 0).sum()
        print(f"    {name}: {n} signal bars")

    vwap = registry.get("vwap_bb_super_confluence_2")
    if vwap:
        matrix["vwap_bb_reversal"] = _get_vwap_bb_signals(vwap, df, VWAP_BEST_PARAMS)
        n = (matrix["vwap_bb_reversal"] != 0).sum()
        print(f"    vwap_bb_reversal: {n} signal bars")

    close  = matrix["close"]
    future = close.shift(-LOOKAHEAD_BARS)
    matrix["forward_return"] = ((future - close) / close).fillna(0.0)
    matrix["success_long"]   = (matrix["forward_return"] > 0).astype(int)
    matrix["success_short"]  = (matrix["forward_return"] < 0).astype(int)
    return matrix


# ── regime + time features ────────────────────────────────────────────────────

def find_latest_regime_frame() -> Path:
    candidates = sorted(
        (p for p in REPORTS_ROOT.iterdir() if (p / "regime_frame.csv").exists()),
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("No regime_frame.csv found in any report folder")
    return candidates[0] / "regime_frame.csv"


def merge_regime(matrix: pd.DataFrame, regime_path: Path) -> pd.DataFrame:
    reg = pd.read_csv(regime_path, usecols=["datetime", "regime_label"])
    reg["datetime"] = pd.to_datetime(reg["datetime"], utc=True)
    reg = reg.drop_duplicates("datetime")
    matrix = matrix.merge(reg, on="datetime", how="left")
    missing = matrix["regime_label"].isna().sum()
    if missing:
        print(f"  [WARN] {missing} bars without regime label -> 'unknown'")
    matrix["regime_label"] = matrix["regime_label"].fillna("unknown")
    return matrix


def add_ist_hour(matrix: pd.DataFrame) -> pd.DataFrame:
    matrix["ist_hour"] = matrix["datetime"].dt.tz_convert(INDIA_TIMEZONE).dt.hour
    return matrix


# ── low-level stat helpers ────────────────────────────────────────────────────

def _regime_mask(matrix: pd.DataFrame, regime: str) -> pd.Series:
    if regime == "non-flat":
        return matrix["regime_label"].isin(["bull", "bear"])
    if regime == "ALL":
        return pd.Series(True, index=matrix.index)
    return matrix["regime_label"] == regime


def _eval_dir(matrix: pd.DataFrame, mask: pd.Series, sc: str):
    n = int(mask.sum())
    if n == 0:
        return 0, float("nan")
    return n, float(matrix.loc[mask, sc].mean() * 100)


def _eval_combo(matrix: pd.DataFrame, lm: pd.Series, sm: pd.Series):
    n = int(lm.sum() + sm.sum())
    if n == 0:
        return 0, 0, 0, float("nan"), float("nan"), float("nan")
    wins = 0
    nl, wrl = _eval_dir(matrix, lm, "success_long")
    ns, wrs = _eval_dir(matrix, sm, "success_short")
    if lm.any():
        wins += matrix.loc[lm, "success_long"].sum()
    if sm.any():
        wins += matrix.loc[sm, "success_short"].sum()
    return n, nl, ns, float(wins / n * 100), wrl, wrs


# ── 1. Strategy x Regime x Direction (3D table) ───────────────────────────────

def analyze_3d(matrix: pd.DataFrame, signal_cols: list[str]) -> pd.DataFrame:
    limit = len(matrix) - LOOKAHEAD_BARS
    rows  = []
    for strat in signal_cols:
        sig = matrix[strat]
        for regime in ["ALL", "non-flat", "bull", "bear", "flat"]:
            rmask = _regime_mask(matrix, regime)
            base  = (matrix.index < limit) & rmask
            lm = (sig == 1)  & base
            sm = (sig == -1) & base
            for dir_val, dir_name, sc in [(1, "LONG", "success_long"),
                                          (-1, "SHORT", "success_short")]:
                mask = (sig == dir_val) & base
                n, wr = _eval_dir(matrix, mask, sc)
                rows.append({"strategy": strat, "regime": regime,
                             "direction": dir_name, "n": n,
                             "win_pct": round(wr, 1) if not np.isnan(wr) else None})
            # combined ALL direction
            n, nl, ns, wr, wrl, wrs = _eval_combo(matrix, lm, sm)
            rows.append({"strategy": strat, "regime": regime,
                         "direction": "ALL", "n": n,
                         "win_pct": round(wr, 1) if not np.isnan(wr) else None})
    return pd.DataFrame(rows)


# ── 2. Combo x Regime ─────────────────────────────────────────────────────────

def analyze_combo_regime(matrix: pd.DataFrame, signal_cols: list[str]) -> pd.DataFrame:
    limit   = len(matrix) - LOOKAHEAD_BARS
    REGIMES = ["ALL", "non-flat", "bull", "bear", "flat"]
    rows    = []

    for size in range(1, len(signal_cols) + 1):
        for combo in combinations(signal_cols, size):
            sub = matrix[list(combo)]
            row: dict = {"combo": " + ".join(combo), "n_strategies": size}

            for regime in REGIMES:
                rmask = _regime_mask(matrix, regime)
                base  = (matrix.index < limit) & rmask
                lm = (sub == 1).all(axis=1) & base
                sm = (sub == -1).all(axis=1) & base
                n, nl, ns, wr, wrl, wrs = _eval_combo(matrix, lm, sm)
                row[f"n_{regime}"]     = n
                row[f"wr_{regime}"]    = round(wr,  1) if not np.isnan(wr)  else None
                row[f"long_{regime}"]  = round(wrl, 1) if not np.isnan(wrl) else None
                row[f"short_{regime}"] = round(wrs, 1) if not np.isnan(wrs) else None

            if row["n_ALL"] < MIN_BARS_DISPLAY:
                continue

            wr_all = row["wr_ALL"]
            wr_nf  = row.get("wr_non-flat")
            row["delta_nonflt"] = (round(wr_nf - wr_all, 1)
                                   if wr_all is not None and wr_nf is not None
                                   else None)
            rows.append(row)

    return pd.DataFrame(rows).sort_values("wr_ALL", ascending=False).reset_index(drop=True)


# ── 3. Morning session ────────────────────────────────────────────────────────

def analyze_morning(matrix: pd.DataFrame, signal_cols: list[str]) -> pd.DataFrame:
    limit = len(matrix) - LOOKAHEAD_BARS
    mm    = matrix["ist_hour"].isin([9, 10])
    rows  = []

    for size in range(1, len(signal_cols) + 1):
        for combo in combinations(signal_cols, size):
            sub = matrix[list(combo)]
            key = " + ".join(combo)

            for label, extra in [("all_day", (matrix.index < limit)),
                                  ("morning", (matrix.index < limit) & mm)]:
                lm = (sub == 1).all(axis=1) & extra
                sm = (sub == -1).all(axis=1) & extra
                n, _, _, wr, _, _ = _eval_combo(matrix, lm, sm)
                rows.append({"combo": key, "session": label, "n": n,
                             "win_pct": round(wr, 1) if not np.isnan(wr) else None})

    df = pd.DataFrame(rows)
    piv = df.pivot_table(index="combo", columns="session",
                         values=["n", "win_pct"], aggfunc="first").reset_index()
    piv.columns = ["combo", "n_all_day", "n_morning", "wr_all_day", "wr_morning"]
    piv = piv[piv["n_all_day"] >= MIN_BARS_DISPLAY].copy()
    piv["delta"] = (piv["wr_morning"] - piv["wr_all_day"]).round(1)
    return piv.sort_values("wr_morning", ascending=False).reset_index(drop=True)


# ── 4. Combined filter ────────────────────────────────────────────────────────

def analyze_combined(matrix: pd.DataFrame, signal_cols: list[str],
                     combo_df: pd.DataFrame) -> pd.DataFrame:
    limit = len(matrix) - LOOKAHEAD_BARS
    mm    = matrix["ist_hour"].isin([9, 10])
    nf    = _regime_mask(matrix, "non-flat")
    rows  = []

    for size in range(1, len(signal_cols) + 1):
        for combo in combinations(signal_cols, size):
            sub  = matrix[list(combo)]
            key  = " + ".join(combo)
            filt = (matrix.index < limit) & mm & nf
            lm = (sub == 1).all(axis=1) & filt
            sm = (sub == -1).all(axis=1) & filt
            n, _, _, wr, _, _ = _eval_combo(matrix, lm, sm)
            if n < MIN_BARS_DISPLAY:
                continue
            base = combo_df.loc[combo_df["combo"] == key, "wr_ALL"]
            wr_base = float(base.iloc[0]) if not base.empty else float("nan")
            rows.append({
                "combo":       key,
                "n":           n,
                "wr_combined": round(wr,      1) if not np.isnan(wr)      else None,
                "wr_base":     round(wr_base, 1) if not np.isnan(wr_base) else None,
                "delta":       round(wr - wr_base, 1)
                               if not np.isnan(wr) and not np.isnan(wr_base) else None,
            })

    return pd.DataFrame(rows).sort_values("wr_combined", ascending=False).reset_index(drop=True)


# ── printing ──────────────────────────────────────────────────────────────────

def _flag(wr, n):
    if n < MIN_BARS_DISPLAY or wr is None or (isinstance(wr, float) and np.isnan(wr)):
        return "    "
    if n < MIN_BARS_TRUST: return " ~  "
    if wr >= 65:            return " ***"
    if wr >= 58:            return " ** "
    if wr < 42:             return " !! "
    return "    "


def _cell(n, wr, w=5):
    if n < MIN_BARS_DISPLAY or wr is None or (isinstance(wr, float) and np.isnan(wr)):
        return f"{'n/a':>{w+8}}"
    return f"{n:>{w}}  {wr:>5.1f}%{_flag(wr, n)}"


def print_3d_table(df: pd.DataFrame):
    print("\n" + "=" * 105)
    print("STRATEGY x REGIME x DIRECTION  --  WIN RATE TABLE")
    print("  *** >= 65%  |  ** >= 58%  |  !! < 42%  |  ~ n < 30 (low confidence)")
    print("=" * 105)
    print(f"  {'Strategy':<22} {'Regime':<10} | {'LONG (n / WR)':>18} | {'SHORT (n / WR)':>18} | {'ALL (n / WR)':>18}")
    print("  " + "-" * 102)

    for strat in df["strategy"].unique():
        sname = SHORT_NAMES.get(strat, strat[:22])
        s     = df[df["strategy"] == strat]
        first = True
        for regime in ["ALL", "non-flat", "bull", "bear", "flat"]:
            r = s[s["regime"] == regime]
            if r.empty:
                continue

            def get(direction):
                row = r[r["direction"] == direction]
                if row.empty:
                    return 0, None
                return int(row["n"].iloc[0]), row["win_pct"].iloc[0]

            nl, wrl = get("LONG")
            ns, wrs = get("SHORT")
            na, wra = get("ALL")
            label = sname if first else ""
            print(f"  {label:<22} {regime:<10} | {_cell(nl, wrl):>18} | {_cell(ns, wrs):>18} | {_cell(na, wra):>18}")
            first = False
        print()


def print_combo_regime_table(df: pd.DataFrame, top_n: int = 25):
    print("\n" + "=" * 118)
    print(f"TOP {top_n} COMBOS  --  WIN RATE BY REGIME FILTER")
    print("  delta = non-flat win rate minus all-regime win rate")
    print("=" * 118)
    h = (f"  {'Combo':<52} | {'n':>5} {'WR_ALL':>7} | "
         f"{'n':>5} {'WR_nonflt':>9} {'d':>5} | "
         f"{'n':>5} {'WR_bull':>7} | {'n':>5} {'WR_bear':>7}")
    print(h)
    print("  " + "-" * 116)

    def fmtwr(val, n, w=6):
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return f"{'--':>{w+4}}"
        return f"{val:>{w}.1f}%{_flag(val, n)}"

    for _, row in df.head(top_n).iterrows():
        delta   = f"{row['delta_nonflt']:+.1f}" if row.get("delta_nonflt") is not None else "  -- "
        n_nf    = int(row.get("n_non-flat") or 0)
        n_b     = int(row.get("n_bull")     or 0)
        n_be    = int(row.get("n_bear")     or 0)
        wr_nf   = fmtwr(row.get("wr_non-flat"), n_nf)
        wr_b    = fmtwr(row.get("wr_bull"),     n_b)
        wr_be   = fmtwr(row.get("wr_bear"),     n_be)
        print(f"  {row['combo']:<52} | {row['n_ALL']:>5} {row['wr_ALL']:>6.1f}% | "
              f"{n_nf:>5} {wr_nf:>8}  {delta:>5} | "
              f"{n_b:>5} {wr_b:>6} | {n_be:>5} {wr_be:>6}")


def print_morning_table(df: pd.DataFrame, top_n: int = 15):
    print("\n" + "=" * 92)
    print(f"MORNING SESSION (09-10 IST) vs ALL-DAY  --  TOP {top_n} BY MORNING WIN RATE")
    print("=" * 92)
    print(f"  {'Combo':<52} | {'n_all':>6} {'WR_all':>7} | {'n_morn':>7} {'WR_morn':>8} {'delta':>6}")
    print("  " + "-" * 90)
    for _, row in df.head(top_n).iterrows():
        wr_m = row.get("wr_morning")
        wr_a = row.get("wr_all_day")
        d    = row.get("delta")
        nm   = int(row["n_morning"]) if row["n_morning"] else 0
        na   = int(row["n_all_day"]) if row["n_all_day"] else 0
        print(f"  {row['combo']:<52} | {na:>6} {str(wr_a or '--'):>7} | "
              f"{nm:>7} {str(wr_m or '--'):>8} {str(d or '--'):>6}")


def print_combined_table(df: pd.DataFrame, top_n: int = 20):
    print("\n" + "=" * 92)
    print(f"COMBINED FILTER: NON-FLAT + MORNING (09-10 IST)  --  TOP {top_n}")
    print("=" * 92)
    print(f"  {'Combo':<52} | {'n':>6} {'WR_combined':>12} {'WR_base':>9} {'delta':>7}")
    print("  " + "-" * 90)
    for _, row in df.head(top_n).iterrows():
        wc = f"{row['wr_combined']:.1f}%" if row["wr_combined"] is not None else "--"
        wb = f"{row['wr_base']:.1f}%"     if row["wr_base"]     is not None else "--"
        d  = f"{row['delta']:+.1f}"        if row["delta"]       is not None else "--"
        print(f"  {row['combo']:<52} | {row['n']:>6} {wc:>11} {wb:>10} {d:>7}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    sep = "=" * 70
    print(sep)
    print("REGIME-CONDITIONAL WIN RATE ANALYSIS")
    print("Hypothesis 1: Does flat-regime filter add 5-15%pts to win rates?")
    print(sep)

    print("\n[1/5] Loading RELIANCE 15m data ...")
    datasets = load_symbol_timeframes(DEFAULT_RELIANCE_ROOT, symbol="RELIANCE")
    df = datasets["15m"].frame.reset_index(drop=True)
    print(f"      {len(df)} bars loaded")

    print("\n[2/5] Building signal matrix (optimized params) ...")
    registry = build_strategy_registry(DEFAULT_STRATEGY_ROOT)
    matrix   = build_signal_matrix(df, registry)

    print("\n[3/5] Merging regime labels ...")
    regime_path = find_latest_regime_frame()
    print(f"      Using: {regime_path}")
    matrix = merge_regime(matrix, regime_path)
    matrix = add_ist_hour(matrix)

    print("\n  Regime distribution:")
    for label, count in matrix["regime_label"].value_counts().items():
        pct = count / len(matrix) * 100
        print(f"    {label:<10}: {count:>5} bars  ({pct:.1f}%)")

    signal_cols = [
        c for c in matrix.columns
        if c not in ("datetime", "close", "forward_return",
                     "success_long", "success_short", "regime_label", "ist_hour")
    ]
    print(f"\n  Signal columns ({len(signal_cols)}): {signal_cols}")

    print("\n[4/5] Computing tables ...")

    # 1. 3D table
    strat_df = analyze_3d(matrix, signal_cols)
    print_3d_table(strat_df)

    # 2. Combo x regime
    combo_df = analyze_combo_regime(matrix, signal_cols)
    print_combo_regime_table(combo_df, top_n=25)

    # Impact summary
    valid = combo_df[combo_df["delta_nonflt"].notna()].copy()
    print(f"\n{sep}")
    print("NON-FLAT REGIME FILTER IMPACT SUMMARY")
    print(sep)
    print(f"  Combos analyzed              : {len(valid)}")
    print(f"  Average delta (nonflt - all) : {valid['delta_nonflt'].mean():+.1f}%pts")
    print(f"  Combos improved              : {(valid['delta_nonflt'] > 0).sum()}  "
          f"({(valid['delta_nonflt'] > 0).mean() * 100:.0f}%)")
    print(f"  Combos hurt                  : {(valid['delta_nonflt'] < 0).sum()}")
    print()
    print("  TOP 5 BY GAIN FROM NON-FLAT FILTER:")
    for _, r in valid.nlargest(5, "delta_nonflt").iterrows():
        nf_wr = r.get("wr_non-flat") or 0
        n_nf  = r.get("n_non-flat") or 0
        print(f"    {r['combo']:<54}  "
              f"{r['wr_ALL']:.1f}% -> {nf_wr:.1f}%  "
              f"(delta{r['delta_nonflt']:+.1f}%pts, n={int(n_nf)})")
    print()
    print("  TOP 5 BY WIN RATE IN NON-FLAT REGIME:")
    for _, r in valid.dropna(subset=["wr_non-flat"]).nlargest(5, "wr_non-flat").iterrows():
        nf_wr = r.get("wr_non-flat") or 0
        n_nf  = r.get("n_non-flat")  or 0
        print(f"    {r['combo']:<54}  {nf_wr:.1f}%  (n={int(n_nf)})")

    # 3. Morning session
    morning_df = analyze_morning(matrix, signal_cols)
    print_morning_table(morning_df, top_n=15)
    valid_m = morning_df.dropna(subset=["delta"])
    print(f"\n  Average morning delta (vs all-day): {valid_m['delta'].mean():+.1f}%pts")
    print(f"  Combos improved by morning filter: {(valid_m['delta'] > 0).sum()}")

    # 4. Combined filter
    combined_df = analyze_combined(matrix, signal_cols, combo_df)
    print_combined_table(combined_df, top_n=20)

    # 5. Save
    print(f"\n[5/5] Saving results ...")
    out = REPORTS_ROOT / "regime_conditional"
    out.mkdir(parents=True, exist_ok=True)
    strat_df.to_csv(out / "strategy_regime_direction.csv", index=False)
    combo_df.to_csv(out / "combo_regime_analysis.csv",    index=False)
    morning_df.to_csv(out / "morning_session_analysis.csv", index=False)
    if not combined_df.empty:
        combined_df.to_csv(out / "combined_filter_analysis.csv", index=False)

    print(f"\n  Saved to: {out}")
    print("    strategy_regime_direction.csv")
    print("    combo_regime_analysis.csv")
    print("    morning_session_analysis.csv")
    print("    combined_filter_analysis.csv")
    print("\nDone.")


if __name__ == "__main__":
    main()
