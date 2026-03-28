"""
hstry_oos_validation.py
=======================
Out-of-sample validation using HSTRY data for RELIANCE and INFY.

Split: 75% TRAIN (find best combos) → 25% TEST (holdout, never seen during search).

RELIANCE 15m split:
  Train: 2021-03-22 to 2024-12-23  (23,160 bars)
  Test:  2024-12-23 to 2026-03-20  ( 7,721 bars)

INFY 15m split:
  Train: 2015-02-02 to 2023-06-12  (51,510 bars)
  Test:  2023-06-12 to 2026-03-20  (17,171 bars)

Three analyses per symbol:
  1. 15m standalone combos     — find best on train, validate on test
  2. 1hr standalone combos     — find best on train, validate on test
  3. Cross-TF: 15m + 1hr       — 15m signal + same direction on 1hr (aligned)

Also compares RELIANCE vs INFY to see if combos generalise across symbols.

Output: artifacts_template/reports/hstry_oos_validation/
  {symbol}_{tf}_train_top20.csv
  {symbol}_{tf}_test_results.csv    — same combos re-measured on holdout
  cross_tf_{symbol}_results.csv
  oos_summary.csv                   — in-sample vs out-of-sample comparison
  oos_summary.json

Usage:
    PYTHONUTF8=1 PYTHONPATH=src python scripts/hstry_oos_validation.py
"""
from __future__ import annotations

import itertools
import json
import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("PYTHONUTF8", "1")

import pandas as pd

from core.constants import DEFAULT_STRATEGY_ROOT
from core.analysis_rules import (   # MANDATORY — read rules before modifying
    RULE_NO_COMBO_REUSE,
    REQUIRED_OUTPUT_FORMAT,
    LOOKAHEAD_BARS,
    TRAIN_RATIO,
    MIN_SIGNALS_TRAIN,
    MIN_SIGNALS_TEST,
    print_rules,
)
from strategies.loader import extract_default_constants
from strategies.registry import ModuleStrategyWrapper
from strategies.param_space import build_param_space

# ── Config ────────────────────────────────────────────────────────────────────
HSTRY_DIR     = Path("C:/Users/sakth/Downloads/HSTRY")
STRATEGY_ROOT = Path(DEFAULT_STRATEGY_ROOT)
REPORT_DIR    = (
    Path(__file__).resolve().parents[1].parent
    / "artifacts_template" / "reports" / "hstry_oos_validation"
)

LOOKAHEAD    = LOOKAHEAD_BARS     # from analysis_rules — fixed, do not override
MIN_SIGNALS  = MIN_SIGNALS_TEST   # 5 — minimum per split
TOP_N_TRAIN  = 20                 # top combos to carry into test evaluation

SYMBOLS = ["RELIANCE", "INFY"]
TFS     = ["15m", "1h"]          # HSTRY uses "1h" not "1hr"
TF_MAP  = {"15m": "15m", "1h": "1hr"}   # internal name for reporting

# 13 qualifying strategies (optimized params where known)
STRATEGY_CONFIGS: list[dict] = [
    {"name": "trend_signals_tp_sl_ualgo",
     "params": {"DEFAULT_MULTIPLIER": 2.6, "DEFAULT_ATR_PERIOD": 10,
                "DEFAULT_CLOUD_VAL": 7, "DEFAULT_STOP_LOSS_PCT": 1.4}},
    {"name": "reversal_radar_v2",
     "params": {"DEFAULT_BLOCK_START": 16, "DEFAULT_BLOCK_END": 7}},
    {"name": "central_pivot_range",             "params": {}},
    {"name": "twin_range_filter",
     "params": {"DEFAULT_PER1": 27, "DEFAULT_MULT1": 1.28,
                "DEFAULT_PER2": 55, "DEFAULT_MULT2": 1.6}},
    {"name": "vwap_bb_super_confluence_2",
     "params": {"bb_len1": 30, "require_double_touch": False}},
    {"name": "bahai_reversal_points",
     "params": {"DEFAULT_LENGTH": 25, "DEFAULT_LOOKBACK_LENGTH": 6}},
    {"name": "sfp_candelacharts",                      "params": {}},
    {"name": "outside_reversal",                       "params": {}},
    {"name": "dark_cloud_piercing_line_tradingfinder", "params": {}},
    {"name": "n_bar_reversal_luxalgo",                 "params": {}},
    {"name": "smc_fvg",  "params": {}},
    {"name": "smc_bos",  "params": {}},
    {"name": "smc_ob",   "params": {}},
]


# ── Data loading ──────────────────────────────────────────────────────────────

def load_hstry(symbol: str, tf: str) -> pd.DataFrame:
    """Load HSTRY CSV, normalize columns to match strategy expectations."""
    path = HSTRY_DIR / f"{symbol}_NSE_{tf}.csv"
    df = pd.read_csv(path)
    # Combine date + time into a unix timestamp (seconds)
    df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str))
    df["timestamp"] = df["datetime"].astype("int64") // 10**9
    df = df.rename(columns={"volume": "volume"})
    # Ensure required columns exist
    for col in ["open", "high", "low", "close", "volume"]:
        if col not in df.columns:
            df[col] = 0.0
    df = df[["timestamp", "datetime", "open", "high", "low", "close", "volume"]].copy()
    df = df.reset_index(drop=True)
    return df


def split_75_25(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    split = int(len(df) * TRAIN_RATIO)
    return df.iloc[:split].reset_index(drop=True), df.iloc[split:].reset_index(drop=True)


# ── Strategy helpers ──────────────────────────────────────────────────────────

def _build_wrapper(cfg: dict) -> ModuleStrategyWrapper:
    path = STRATEGY_ROOT / f"{cfg['name']}.py"
    defaults = extract_default_constants(path)
    return ModuleStrategyWrapper(
        name=cfg["name"],
        module_path=path,
        param_defaults=defaults,
        param_space=build_param_space(defaults),
        role_tags=(),
        unsupported_reason=None,
    )


def _run(wrapper: ModuleStrategyWrapper, frame: pd.DataFrame, params: dict) -> pd.Series:
    try:
        return wrapper.run(frame, params=params or None).signal.reset_index(drop=True)
    except Exception as exc:
        print(f"    [WARN] {wrapper.name}: {type(exc).__name__}: {exc}")
        return pd.Series(0, index=range(len(frame)), dtype=int)


def _fwd_dir(frame: pd.DataFrame) -> pd.Series:
    ret = (frame["close"].shift(-LOOKAHEAD) / frame["close"] - 1.0).reset_index(drop=True)
    return ret.apply(lambda v: 1 if v > 0 else (-1 if v < 0 else 0))


def _metrics(signals: pd.Series, fwd: pd.Series) -> dict:
    lm = signals == 1
    sm = signals == -1
    nl, ns = int(lm.sum()), int(sm.sum())
    n = nl + ns
    if n == 0:
        return {"n": 0, "nl": 0, "ns": 0, "wr": None, "lwr": None, "swr": None}
    wins = int((fwd[lm] > 0).sum()) + int((fwd[sm] < 0).sum())
    lwr = round(float((fwd[lm] > 0).mean()), 4) if nl else None
    swr = round(float((fwd[sm] < 0).mean()), 4) if ns else None
    return {"n": n, "nl": nl, "ns": ns,
            "wr": round(wins / n, 4), "lwr": lwr, "swr": swr}


def _combo_signal(signal_matrix: dict[str, pd.Series], combo: tuple) -> pd.Series:
    stack = pd.concat([signal_matrix[s] for s in combo], axis=1)
    stack.columns = list(combo)
    active = (stack != 0).all(axis=1) & (
        stack.gt(0).all(axis=1) | stack.lt(0).all(axis=1)
    )
    out = pd.Series(0, index=stack.index, dtype=int)
    out[active] = stack[active].mean(axis=1).apply(lambda v: 1 if v > 0 else -1)
    return out


def _align_to_primary(primary_ts: pd.Series,
                       higher_ts: pd.Series,
                       higher_sig: pd.Series) -> pd.Series:
    prim = pd.DataFrame({"ts": primary_ts.values}).reset_index()
    high = pd.DataFrame({"ts": higher_ts.values, "sig": higher_sig.values}).sort_values("ts")
    merged = (
        pd.merge_asof(prim.sort_values("ts"), high, on="ts", direction="backward")
        .set_index("index").sort_index()
    )
    return merged["sig"].fillna(0).astype(int)


def build_signal_matrix(frame: pd.DataFrame, verbose: bool = False) -> dict[str, pd.Series]:
    matrix: dict[str, pd.Series] = {}
    fwd = _fwd_dir(frame)
    for cfg in STRATEGY_CONFIGS:
        sig = _run(_build_wrapper(cfg), frame, cfg["params"])
        matrix[cfg["name"]] = sig
        if verbose:
            n_s = int((sig != 0).sum())
            if n_s:
                m = _metrics(sig, fwd)
                print(f"    {cfg['name']:<45} n={n_s:>5}  wr={m['wr']:.1%}")
            else:
                print(f"    {cfg['name']:<45} 0 signals")
    return matrix


def combo_search(signal_matrix: dict[str, pd.Series],
                 fwd: pd.Series,
                 max_size: int = 4) -> pd.DataFrame:
    rows = []
    names = list(signal_matrix.keys())
    for size in range(1, max_size + 1):
        for combo in itertools.combinations(names, size):
            sig = _combo_signal(signal_matrix, combo)
            m = _metrics(sig, fwd)
            if m["n"] == 0:
                continue
            rows.append({
                "combo":          " + ".join(combo),
                "n_strategies":   size,
                "n_signals":      m["n"],
                "n_long":         m["nl"],
                "n_short":        m["ns"],
                "win_rate":       m["wr"],
                "loss_rate":      round(1 - m["wr"], 4),
                "long_win_rate":  m["lwr"],
                "short_win_rate": m["swr"],
            })
    return pd.DataFrame(rows).sort_values("win_rate", ascending=False).reset_index(drop=True)


def eval_combos_on_frame(combos: list[str],
                          signal_matrix: dict[str, pd.Series],
                          fwd: pd.Series,
                          split_label: str) -> pd.DataFrame:
    """Apply pre-selected combo list to a (different) frame's signal matrix."""
    rows = []
    for combo_str in combos:
        combo = tuple(combo_str.split(" + "))
        # Check all strategies exist in this signal_matrix
        missing = [s for s in combo if s not in signal_matrix]
        if missing:
            rows.append({"combo": combo_str, "split": split_label,
                         "n_signals": 0, "win_rate": None,
                         "loss_rate": None, "long_win_rate": None, "short_win_rate": None})
            continue
        sig = _combo_signal(signal_matrix, combo)
        m = _metrics(sig, fwd)
        rows.append({
            "combo":          combo_str,
            "split":          split_label,
            "n_signals":      m["n"],
            "n_long":         m["nl"],
            "n_short":        m["ns"],
            "win_rate":       m["wr"],
            "loss_rate":      round(1 - m["wr"], 4) if m["wr"] is not None else None,
            "long_win_rate":  m["lwr"],
            "short_win_rate": m["swr"],
        })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
# Per-TF analysis (standalone, no cross-TF)
# ══════════════════════════════════════════════════════════════════════════════

def analyze_tf(symbol: str, hstry_tf: str) -> pd.DataFrame:
    """Full train/test analysis for one symbol × TF. Returns comparison DataFrame."""
    tf_label = TF_MAP.get(hstry_tf, hstry_tf)
    print(f"\n  [{symbol} {tf_label}] Loading data...", flush=True)

    df = load_hstry(symbol, hstry_tf)
    train_df, test_df = split_75_25(df)

    print(f"  [{symbol} {tf_label}] Train={len(train_df)} bars "
          f"({train_df.iloc[0]['datetime'].date()} to {train_df.iloc[-1]['datetime'].date()})  "
          f"Test={len(test_df)} bars "
          f"({test_df.iloc[0]['datetime'].date()} to {test_df.iloc[-1]['datetime'].date()})")

    # Build signal matrices
    print(f"  [{symbol} {tf_label}] Running strategies on TRAIN...", flush=True)
    train_matrix = build_signal_matrix(train_df, verbose=True)
    train_fwd    = _fwd_dir(train_df)

    print(f"  [{symbol} {tf_label}] Running strategies on TEST...", flush=True)
    test_matrix  = build_signal_matrix(test_df, verbose=False)
    test_fwd     = _fwd_dir(test_df)

    # Combo search on TRAIN
    print(f"  [{symbol} {tf_label}] Testing combos on TRAIN...", flush=True)
    train_combos = combo_search(train_matrix, train_fwd)
    qualified    = train_combos[train_combos["n_signals"] >= MIN_SIGNALS]

    # Save train top 20
    out_train = REPORT_DIR / f"{symbol}_{tf_label}_train_top20.csv"
    qualified.head(20).to_csv(out_train, index=False)

    if qualified.empty:
        print(f"  [{symbol} {tf_label}] No qualified combos on train.")
        return pd.DataFrame()

    top_combos = qualified.head(TOP_N_TRAIN)["combo"].tolist()

    print(f"\n  [{symbol} {tf_label}] TOP 5 TRAIN COMBOS:")
    print(f"    {'WIN%':>6} {'N':>5}  COMBO")
    for _, row in qualified.head(5).iterrows():
        print(f"    {row['win_rate']:.1%}  {int(row['n_signals']):>5}  {row['combo']}")

    # Evaluate SAME combos on TEST
    train_results = eval_combos_on_frame(top_combos, train_matrix, train_fwd, "train")
    test_results  = eval_combos_on_frame(top_combos, test_matrix,  test_fwd,  "test")

    # Merge train vs test for comparison
    cmp = train_results.merge(
        test_results[["combo", "n_signals", "win_rate", "loss_rate", "long_win_rate", "short_win_rate"]],
        on="combo",
        suffixes=("_train", "_test"),
    )
    cmp["wr_drop"] = cmp.apply(
        lambda r: round(r["win_rate_train"] - r["win_rate_test"], 4)
        if (r["win_rate_train"] is not None and r["win_rate_test"] is not None)
        else None, axis=1
    )
    cmp["symbol"] = symbol
    cmp["tf"]     = tf_label

    # Save comparison
    out_cmp = REPORT_DIR / f"{symbol}_{tf_label}_oos_comparison.csv"
    cmp.to_csv(out_cmp, index=False)

    # Print comparison
    print(f"\n  [{symbol} {tf_label}] TRAIN vs TEST (out-of-sample):")
    print(f"    {'TRAIN WR':>8} {'TEST WR':>8} {'DROP':>6} {'N_TRAIN':>7} {'N_TEST':>7}  COMBO")
    print(f"    {'-' * 80}")
    for _, row in cmp.head(10).iterrows():
        twr  = f"{row['win_rate_train']:.1%}" if row["win_rate_train"] is not None else "  N/A"
        tswr = f"{row['win_rate_test']:.1%}"  if row["win_rate_test"]  is not None else "  N/A"
        drop = f"{row['wr_drop']:.1%}"        if row["wr_drop"]       is not None else "  N/A"
        nt   = int(row["n_signals_train"]) if row["n_signals_train"] else 0
        ns   = int(row["n_signals_test"])  if row["n_signals_test"]  else 0
        held = " HELD" if (row["win_rate_test"] and row["win_rate_test"] >= 0.70) else ""
        print(f"    {twr:>8}  {tswr:>8}  {drop:>6}  {nt:>7}  {ns:>7}  {row['combo']}{held}")

    return cmp


# ══════════════════════════════════════════════════════════════════════════════
# Cross-TF analysis: 15m + 1hr confirmation
# ══════════════════════════════════════════════════════════════════════════════

def analyze_cross_tf(symbol: str) -> pd.DataFrame:
    """Test cross-TF confirmation (15m + 1hr) for train and test periods."""
    print(f"\n  [{symbol} CROSS-TF 15m+1hr] Loading data...", flush=True)

    df_15m = load_hstry(symbol, "15m")
    df_1h  = load_hstry(symbol, "1h")

    # Use same chronological split point for both TFs
    split_idx_15m = int(len(df_15m) * TRAIN_RATIO)
    split_date    = df_15m.iloc[split_idx_15m]["datetime"]

    train_15m = df_15m[df_15m["datetime"] < split_date].reset_index(drop=True)
    test_15m  = df_15m[df_15m["datetime"] >= split_date].reset_index(drop=True)
    train_1h  = df_1h[df_1h["datetime"] < split_date].reset_index(drop=True)
    test_1h   = df_1h[df_1h["datetime"] >= split_date].reset_index(drop=True)

    print(f"  [{symbol} CROSS-TF] 15m train={len(train_15m)}, test={len(test_15m)}  "
          f"1h train={len(train_1h)}, test={len(test_1h)}")

    rows: list[dict] = []

    for split_label, pf_15m, pf_1h in [
        ("train", train_15m, train_1h),
        ("test",  test_15m,  test_1h),
    ]:
        print(f"  [{symbol} CROSS-TF] Building signal bank ({split_label})...", flush=True)
        mat_15m = build_signal_matrix(pf_15m, verbose=(split_label == "train"))
        mat_1h  = build_signal_matrix(pf_1h,  verbose=False)
        fwd     = _fwd_dir(pf_15m)

        for cfg in STRATEGY_CONFIGS:
            name = cfg["name"]
            sig_15m = mat_15m[name]
            sig_1h_aligned = _align_to_primary(
                pf_15m["timestamp"], pf_1h["timestamp"], mat_1h[name]
            )

            # Baseline: 15m only
            m0 = _metrics(sig_15m, fwd)

            # Confirmed: 15m + 1hr same direction
            agree = ((sig_15m > 0) & (sig_1h_aligned > 0)) | \
                    ((sig_15m < 0) & (sig_1h_aligned < 0))
            sig_conf = sig_15m.where(agree, 0)
            m1 = _metrics(sig_conf, fwd)

            for level, m in [("15m_only", m0), ("15m_plus_1hr", m1)]:
                rows.append({
                    "symbol": symbol, "split": split_label,
                    "strategy": name, "level": level,
                    "n": m["n"], "win_rate": m["wr"],
                    "long_wr": m["lwr"], "short_wr": m["swr"],
                })

    result_df = pd.DataFrame(rows)
    out_path  = REPORT_DIR / f"cross_tf_{symbol}_results.csv"
    result_df.to_csv(out_path, index=False)

    # Print cross-TF comparison (15m_plus_1hr, train vs test)
    print(f"\n  [{symbol} CROSS-TF] Per-strategy: 15m+1hr  TRAIN vs TEST")
    print(f"    {'STRATEGY':<45} {'TRAIN':>7} {'N_TR':>5}  {'TEST':>7} {'N_TS':>5}  HELD?")
    print(f"    {'-' * 85}")

    for cfg in STRATEGY_CONFIGS:
        name = cfg["name"]
        tr = result_df[(result_df["strategy"] == name) & (result_df["level"] == "15m_plus_1hr") &
                       (result_df["split"] == "train")]
        te = result_df[(result_df["strategy"] == name) & (result_df["level"] == "15m_plus_1hr") &
                       (result_df["split"] == "test")]
        if tr.empty or te.empty:
            continue
        tr_r, te_r = tr.iloc[0], te.iloc[0]
        twr  = f"{tr_r['win_rate']:.1%}" if tr_r["win_rate"] else "  N/A"
        tswr = f"{te_r['win_rate']:.1%}" if te_r["win_rate"] else "  N/A"
        nt   = int(tr_r["n"]) if tr_r["n"] else 0
        ns   = int(te_r["n"]) if te_r["n"] else 0
        held = " HELD" if (te_r["win_rate"] and te_r["win_rate"] >= 0.65 and ns >= MIN_SIGNALS) else ""
        print(f"    {name:<45} {twr:>7}  {nt:>5}  {tswr:>7}  {ns:>5}{held}")

    return result_df


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    all_comparisons: list[pd.DataFrame] = []
    summary_rows: list[dict] = []

    # Print rules reminder — fresh analysis required per stock/TF
    print_rules()

    print("=" * 80)
    print("HSTRY Out-of-Sample Validation")
    print("Train 75% -> find combos | Test 25% -> validate (unseen data)")
    print("=" * 80)

    # ── Phase 1: Per-TF standalone ────────────────────────────────────────────
    for symbol in SYMBOLS:
        for hstry_tf, tf_label in TF_MAP.items():
            print(f"\n{'#' * 70}")
            print(f"# {symbol}  {tf_label}  (standalone combo search)")
            print(f"{'#' * 70}")
            cmp = analyze_tf(symbol, hstry_tf)
            if cmp.empty:
                continue
            all_comparisons.append(cmp)

            # Summarize: best combos that HELD in test
            held = cmp[(cmp["win_rate_test"].notna()) &
                       (cmp["win_rate_test"] >= 0.65) &
                       (cmp["n_signals_test"] >= MIN_SIGNALS)]
            if not held.empty:
                b = held.sort_values("win_rate_test", ascending=False).iloc[0]
                summary_rows.append({
                    "symbol":          symbol,
                    "tf":              tf_label,
                    "analysis":        "standalone",
                    "combo":           b["combo"],
                    "train_wr":        b["win_rate_train"],
                    "test_wr":         b["win_rate_test"],
                    "wr_drop":         b["wr_drop"],
                    "n_train":         int(b["n_signals_train"]),
                    "n_test":          int(b["n_signals_test"]),
                })

    # ── Phase 2: Cross-TF ─────────────────────────────────────────────────────
    for symbol in SYMBOLS:
        print(f"\n{'#' * 70}")
        print(f"# {symbol}  Cross-TF 15m + 1hr confirmation")
        print(f"{'#' * 70}")
        ctf_df = analyze_cross_tf(symbol)
        if ctf_df.empty:
            continue

        # Summarize held cross-TF strategies
        held_ctf = ctf_df[
            (ctf_df["level"] == "15m_plus_1hr") &
            (ctf_df["split"] == "test") &
            (ctf_df["win_rate"].notna()) &
            (ctf_df["win_rate"] >= 0.65) &
            (ctf_df["n"] >= MIN_SIGNALS)
        ]
        if not held_ctf.empty:
            b = held_ctf.sort_values("win_rate", ascending=False).iloc[0]
            summary_rows.append({
                "symbol":   symbol,
                "tf":       "15m+1hr",
                "analysis": "cross_tf",
                "combo":    b["strategy"],
                "train_wr": ctf_df[(ctf_df["strategy"] == b["strategy"]) &
                                   (ctf_df["level"] == "15m_plus_1hr") &
                                   (ctf_df["split"] == "train")]["win_rate"].values[0],
                "test_wr":  b["win_rate"],
                "wr_drop":  None,
                "n_train":  None,
                "n_test":   int(b["n"]),
            })

    # ── Save OOS summary ──────────────────────────────────────────────────────
    if all_comparisons:
        full_cmp = pd.concat(all_comparisons, ignore_index=True)
        full_cmp.to_csv(REPORT_DIR / "all_oos_comparisons.csv", index=False)

    summary_df = pd.DataFrame(summary_rows)
    if not summary_df.empty:
        summary_df.to_csv(REPORT_DIR / "oos_summary.csv", index=False)

    # ── Final printout ────────────────────────────────────────────────────────
    print(f"\n\n{'=' * 80}")
    print("FINAL OUT-OF-SAMPLE SUMMARY")
    print("Combos that HELD (test WR >= 65%, min 5 signals on test set)")
    print(f"{'=' * 80}")
    if not summary_df.empty:
        print(f"  {'SYMBOL':<10} {'TF':<8} {'TRAIN WR':>9} {'TEST WR':>8} {'DROP':>6} {'N_TS':>5}  COMBO")
        print(f"  {'-' * 80}")
        for _, r in summary_df.sort_values("test_wr", ascending=False).iterrows():
            twr  = f"{r['train_wr']:.1%}" if r["train_wr"] else "  N/A"
            tswr = f"{r['test_wr']:.1%}"  if r["test_wr"]  else "  N/A"
            drop = f"{r['wr_drop']:.1%}"  if r["wr_drop"]  else "  N/A"
            nt   = str(int(r["n_test"])) if r["n_test"] else "?"
            print(f"  {r['symbol']:<10} {r['tf']:<8} {twr:>9}  {tswr:>8}  {drop:>6}  {nt:>5}  {r['combo']}")
    else:
        print("  No combos held at 65%+ WR in out-of-sample test.")

    # Save summary JSON
    with open(REPORT_DIR / "oos_summary.json", "w") as f:
        json.dump(summary_rows, f, indent=2)

    print(f"\nAll reports saved to: {REPORT_DIR}")


if __name__ == "__main__":
    main()
