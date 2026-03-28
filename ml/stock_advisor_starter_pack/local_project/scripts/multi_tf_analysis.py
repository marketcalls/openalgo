"""
multi_tf_analysis.py
====================
Single-call analysis across timeframes. Runs two experiments back-to-back:

PHASE 1 — Per-TF Primary Scan
  For every available RELIANCE TF (1m → 1day), independently run all 13
  qualifying strategies, test every 1–4 strategy combo, and find the best
  combo per TF. Answers: "Which primary timeframe gives the highest win rate?"

PHASE 2 — Multi-TF Signal Confluence
  Using 15m as the primary TF, test whether requiring the same strategy to
  also fire on 1hr and/or 4hr simultaneously improves win rate.
    Level 0: 15m signal only (baseline)
    Level 1: 15m signal AND same direction on 1hr
    Level 2: 15m signal AND same direction on 4hr
    Level 3: 15m signal AND same direction on 1hr + 4hr (all 3 agree)
  Also tests combo-level cross-TF confirmation (combos that agree on 15m +
  at least one strategy confirms on 1hr).

LOOKAHEAD: 8 bars for all TFs (= 2 hrs on 15m, 8 hrs on 1hr, ~2 days on 4hr).

Output: artifacts_template/reports/multi_tf_analysis/
  Phase 1
    tf_scan_summary.csv          — best combo per TF (one row per TF)
    {tf}_top20.csv               — top 20 combos for each TF

  Phase 2
    per_strategy_confirmation.csv — per-strategy WR at each confirmation level
    combo_confirmation.csv        — combo WR gain from cross-TF filter

  Combined
    full_summary.json             — key findings across both phases

Usage:
    PYTHONUTF8=1 PYTHONPATH=src python scripts/multi_tf_analysis.py
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

from core.constants import DEFAULT_RELIANCE_ROOT, DEFAULT_STRATEGY_ROOT
from core.analysis_rules import (   # MANDATORY — read rules before modifying
    RULE_NO_COMBO_REUSE,
    REQUIRED_OUTPUT_FORMAT,
    LOOKAHEAD_BARS,
    MIN_SIGNALS_TEST,
    print_rules,
)
from data.load_symbol_timeframes import load_symbol_timeframes
from strategies.loader import extract_default_constants
from strategies.registry import ModuleStrategyWrapper
from strategies.param_space import build_param_space

# ── Config ────────────────────────────────────────────────────────────────────
# NOTE: LOOKAHEAD and MIN_SIGNALS come from analysis_rules.py — do not override
LOOKAHEAD     = LOOKAHEAD_BARS   # 8 bars — fixed across all TFs for comparability
MIN_SIGNALS   = MIN_SIGNALS_TEST # 5 — minimum per split to draw conclusions
MIN_BARS      = 300
SKIP_TFS      = {"1month"}
PRIMARY_TF    = "15m"
CONFIRM_TFS   = ["1hr", "4hr"]
TF_ORDER      = ["1m", "3m", "5m", "15m", "30m", "1hr", "2hr", "4hr", "1day", "1month"]
STRATEGY_ROOT = Path(DEFAULT_STRATEGY_ROOT)
REPORT_DIR    = (
    Path(__file__).resolve().parents[1].parent
    / "artifacts_template" / "reports" / "multi_tf_analysis"
)

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


# ── Shared helpers ─────────────────────────────────────────────────────────────

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


def _forward_dir(frame: pd.DataFrame) -> pd.Series:
    ret = (frame["close"].shift(-LOOKAHEAD) / frame["close"] - 1.0).reset_index(drop=True)
    return ret.apply(lambda v: 1 if v > 0 else (-1 if v < 0 else 0))


def _metrics(signals: pd.Series, fwd: pd.Series) -> dict:
    lm = signals == 1
    sm = signals == -1
    nl, ns = int(lm.sum()), int(sm.sum())
    n = nl + ns
    if n == 0:
        return {"n": 0, "nl": 0, "ns": 0, "wr": None, "lwr": None, "swr": None}
    wins = int(((fwd[lm] > 0).sum()) + ((fwd[sm] < 0).sum()))
    lwr = round(float((fwd[lm] > 0).mean()), 4) if nl else None
    swr = round(float((fwd[sm] < 0).mean()), 4) if ns else None
    return {"n": n, "nl": nl, "ns": ns,
            "wr": round(wins / n, 4), "lwr": lwr, "swr": swr}


def _combo_signal(signal_matrix: dict[str, pd.Series], combo: tuple) -> pd.Series:
    """Consensus signal: nonzero where ALL strategies in combo agree on direction."""
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
    """Carry higher-TF signal forward to each primary bar via merge_asof."""
    prim = pd.DataFrame({"ts": primary_ts.values}).reset_index()
    high = pd.DataFrame({"ts": higher_ts.values, "sig": higher_sig.values}).sort_values("ts")
    merged = (
        pd.merge_asof(prim.sort_values("ts"), high, on="ts", direction="backward")
        .set_index("index")
        .sort_index()
    )
    return merged["sig"].fillna(0).astype(int)


def _build_signal_matrix(frame: pd.DataFrame) -> dict[str, pd.Series]:
    matrix: dict[str, pd.Series] = {}
    for cfg in STRATEGY_CONFIGS:
        matrix[cfg["name"]] = _run(_build_wrapper(cfg), frame, cfg["params"])
    return matrix


def _run_combo_search(
    signal_matrix: dict[str, pd.Series], fwd: pd.Series
) -> pd.DataFrame:
    """Test all 1–4 strategy combos. Returns sorted DataFrame."""
    rows = []
    strategy_names = list(signal_matrix.keys())
    for size in range(1, 5):
        for combo in itertools.combinations(strategy_names, size):
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


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — Per-TF Primary Scan
# ══════════════════════════════════════════════════════════════════════════════

def phase1_per_tf_scan(datasets: dict) -> tuple[pd.DataFrame, list[dict]]:
    """
    Run full combo search on every available TF.
    Returns (summary_df, list of best_combo dicts per TF).
    """
    tfs = [tf for tf in TF_ORDER
           if tf in datasets
           and tf not in SKIP_TFS
           and len(datasets[tf].frame) >= MIN_BARS]

    summary_rows: list[dict] = []
    best_per_tf: list[dict] = []

    print(f"\n{'#' * 80}")
    print("# PHASE 1 — Per-TF Primary Scan")
    print(f"# TFs to scan: {tfs}")
    print(f"{'#' * 80}")

    for tf in tfs:
        frame = datasets[tf].frame.reset_index(drop=True)
        fwd   = _forward_dir(frame)
        n     = len(frame)

        print(f"\n{'=' * 70}")
        print(f"  TF: {tf}  |  {n} bars  |  lookahead = {LOOKAHEAD} bars")
        print(f"{'=' * 70}")

        # Build signal matrix (with per-strategy WR print)
        signal_matrix: dict[str, pd.Series] = {}
        for cfg in STRATEGY_CONFIGS:
            sig = _run(_build_wrapper(cfg), frame, cfg["params"])
            signal_matrix[cfg["name"]] = sig
            n_sig = int((sig != 0).sum())
            if n_sig:
                m = _metrics(sig, fwd)
                print(f"  {cfg['name']:<45} signals={n_sig:>4}  wr={m['wr']:.1%}")
            else:
                print(f"  {cfg['name']:<45} 0 signals")

        print(f"  Testing combos...", flush=True)
        combo_df = _run_combo_search(signal_matrix, fwd)
        qualified = combo_df[combo_df["n_signals"] >= MIN_SIGNALS]

        # Save per-TF top 20
        safe_tf = tf.replace("/", "_")
        out_path = REPORT_DIR / f"{safe_tf}_top20.csv"
        qualified.head(20).to_csv(out_path, index=False)

        if not qualified.empty:
            b = qualified.iloc[0]
            row = {
                "tf":             tf,
                "bars":           n,
                "best_combo":     b["combo"],
                "n_strategies":   int(b["n_strategies"]),
                "n_signals":      int(b["n_signals"]),
                "win_rate":       b["win_rate"],
                "loss_rate":      b["loss_rate"],
                "long_win_rate":  b["long_win_rate"],
                "short_win_rate": b["short_win_rate"],
            }
            summary_rows.append(row)
            best_per_tf.append(row)

            print(f"\n  BEST: {b['win_rate']:.1%} WR  |  {int(b['n_signals'])} signals  →  {b['combo']}")
            print(f"  {'RANK':<4} {'WIN%':>6} {'LOSS%':>6} {'N':>5} {'LONG%':>6} {'SHORT%':>7}  COMBO")
            for rank, (_, row_) in enumerate(qualified.head(5).iterrows(), 1):
                lw = f"{row_['long_win_rate']:.1%}" if row_["long_win_rate"] else "   —"
                sw = f"{row_['short_win_rate']:.1%}" if row_["short_win_rate"] else "   —"
                print(f"  {rank:<4} {row_['win_rate']:.1%}  {row_['loss_rate']:.1%}  "
                      f"{int(row_['n_signals']):>5}  {lw:>6}  {sw:>7}  {row_['combo']}")
        else:
            print(f"  [SKIP] No combo reached {MIN_SIGNALS} signals on {tf}")

    summary_df = pd.DataFrame(summary_rows).sort_values("win_rate", ascending=False)
    summary_df.to_csv(REPORT_DIR / "tf_scan_summary.csv", index=False)

    print(f"\n\n{'=' * 80}")
    print("PHASE 1 SUMMARY — best combo per TF (min 5 signals, ranked by win rate)")
    print(f"{'=' * 80}")
    print(f"  {'TF':<8} {'BARS':>6} {'WIN%':>6} {'N':>5}  COMBO")
    for _, row in summary_df.iterrows():
        print(f"  {row['tf']:<8} {int(row['bars']):>6} {row['win_rate']:.1%}  {int(row['n_signals']):>5}  {row['best_combo']}")

    return summary_df, best_per_tf


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — Multi-TF Signal Confluence
# ══════════════════════════════════════════════════════════════════════════════

def phase2_multi_tf_confluence(datasets: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Test per-strategy and per-combo cross-TF confirmation on PRIMARY_TF.
    Returns (per_strategy_df, combo_df).
    """
    for tf in [PRIMARY_TF] + CONFIRM_TFS:
        if tf not in datasets:
            print(f"  [SKIP Phase 2] Required TF {tf} not available.")
            return pd.DataFrame(), pd.DataFrame()

    primary_frame = datasets[PRIMARY_TF].frame.reset_index(drop=True)
    primary_ts    = primary_frame["timestamp"]
    fwd           = _forward_dir(primary_frame)
    n             = len(primary_frame)

    print(f"\n\n{'#' * 80}")
    print("# PHASE 2 — Multi-TF Signal Confluence")
    print(f"# Primary: {PRIMARY_TF} ({n} bars)  |  Confirm: {CONFIRM_TFS}")
    print(f"{'#' * 80}")

    # ── Build signal bank: strategy → TF → signal aligned to primary bars ──
    print("\nBuilding signal bank (primary + all confirm TFs)...")
    signal_bank: dict[str, dict[str, pd.Series]] = {}

    for cfg in STRATEGY_CONFIGS:
        name = cfg["name"]
        wrapper = _build_wrapper(cfg)
        signal_bank[name] = {}

        sig_p = _run(wrapper, primary_frame, cfg["params"])
        signal_bank[name][PRIMARY_TF] = sig_p
        info = [f"{PRIMARY_TF}={int((sig_p != 0).sum()):>4}"]

        for ctf in CONFIRM_TFS:
            cf = datasets[ctf].frame.reset_index(drop=True)
            sig_c = _run(wrapper, cf, cfg["params"])
            aligned = _align_to_primary(primary_ts, cf["timestamp"], sig_c)
            signal_bank[name][ctf] = aligned
            info.append(f"{ctf}={int((aligned != 0).sum()):>4}")

        print(f"  {name:<45} {', '.join(info)}")

    strategy_names = list(signal_bank.keys())

    # ── Experiment A: Per-strategy confirmation levels ──────────────────────
    print(f"\n{'=' * 80}")
    print("A) Per-strategy — WR at each confirmation level")
    print(f"{'=' * 80}")
    print(f"  {'STRATEGY':<45} {'LEVEL':<22} {'WIN%':>6} {'N':>5} {'LONG%':>6} {'SHORT%':>7}")
    print(f"  {'-' * 90}")

    per_strat_rows: list[dict] = []

    for name in strategy_names:
        sig_p   = signal_bank[name][PRIMARY_TF]
        sig_1hr = signal_bank[name]["1hr"]
        sig_4hr = signal_bank[name]["4hr"]

        # Build all four confirmation masks
        agree_1hr = (sig_p > 0) & (sig_1hr > 0) | (sig_p < 0) & (sig_1hr < 0)
        agree_4hr = (sig_p > 0) & (sig_4hr > 0) | (sig_p < 0) & (sig_4hr < 0)

        levels = {
            "15m only":      sig_p.copy(),
            "15m + 1hr":     sig_p.where(agree_1hr, 0),
            "15m + 4hr":     sig_p.where(agree_4hr, 0),
            "15m + 1hr+4hr": sig_p.where(agree_1hr & agree_4hr, 0),
        }

        first = True
        for level_name, sig in levels.items():
            m = _metrics(sig, fwd)
            wr_s  = f"{m['wr']:.1%}" if m["wr"] is not None else "  N/A"
            lwr_s = f"{m['lwr']:.1%}" if m["lwr"] is not None else "    —"
            swr_s = f"{m['swr']:.1%}" if m["swr"] is not None else "    —"
            star  = " ★" if (m["wr"] and m["wr"] >= 0.80 and m["n"] >= MIN_SIGNALS) else ""
            tag   = name if first else ""
            print(f"  {tag:<45} {level_name:<22} {wr_s:>6}  {m['n']:>5}  {lwr_s:>6}  {swr_s:>7}{star}")
            first = False
            per_strat_rows.append({
                "strategy": name, "level": level_name,
                "n": m["n"], "n_long": m["nl"], "n_short": m["ns"],
                "win_rate": m["wr"], "long_wr": m["lwr"], "short_wr": m["swr"],
            })
        print()

    per_strat_df = pd.DataFrame(per_strat_rows)
    per_strat_df.to_csv(REPORT_DIR / "per_strategy_confirmation.csv", index=False)

    # ── Experiment B: Combo-level cross-TF confirmation ─────────────────────
    print(f"{'=' * 80}")
    print("B) Combo confluence — 15m agreement vs 15m + 1hr TF boost")
    print(f"{'=' * 80}")

    # Build primary signal matrix for combo search
    primary_matrix = {n: signal_bank[n][PRIMARY_TF] for n in strategy_names}

    combo_rows: list[dict] = []

    for size in range(2, 4):
        for combo in itertools.combinations(strategy_names, size):
            sig_base = _combo_signal(primary_matrix, combo)
            m_base   = _metrics(sig_base, fwd)
            if m_base["n"] == 0:
                continue

            combo_key = " + ".join(combo)

            # Enhanced: consensus on 15m + ≥1 strategy confirms on 1hr
            any_1hr = pd.Series(False, index=sig_base.index)
            any_4hr = pd.Series(False, index=sig_base.index)
            for s in combo:
                any_1hr |= (
                    ((sig_base > 0) & (signal_bank[s]["1hr"] > 0)) |
                    ((sig_base < 0) & (signal_bank[s]["1hr"] < 0))
                )
                any_4hr |= (
                    ((sig_base > 0) & (signal_bank[s]["4hr"] > 0)) |
                    ((sig_base < 0) & (signal_bank[s]["4hr"] < 0))
                )

            sig_1hr_enh = sig_base.where(any_1hr, 0)
            sig_4hr_enh = sig_base.where(any_4hr, 0)
            sig_all_enh = sig_base.where(any_1hr & any_4hr, 0)

            m_1hr = _metrics(sig_1hr_enh, fwd)
            m_4hr = _metrics(sig_4hr_enh, fwd)
            m_all = _metrics(sig_all_enh, fwd)

            for level, m in [
                ("15m_only",         m_base),
                ("15m_plus_1hr",     m_1hr),
                ("15m_plus_4hr",     m_4hr),
                ("15m_plus_1hr_4hr", m_all),
            ]:
                combo_rows.append({
                    "combo": combo_key, "n_strategies": size, "level": level,
                    "n": m["n"], "n_long": m["nl"], "n_short": m["ns"],
                    "win_rate": m["wr"], "long_wr": m["lwr"], "short_wr": m["swr"],
                })

    combo_df = pd.DataFrame(combo_rows)
    combo_df.to_csv(REPORT_DIR / "combo_confirmation.csv", index=False)

    # Print: biggest WR improvement from 1hr filter
    if not combo_df.empty:
        base_d = (combo_df[combo_df["level"] == "15m_only"]
                  [["combo", "n_strategies", "n", "win_rate"]]
                  .rename(columns={"win_rate": "wr_base", "n": "n_base"}))
        enh_d  = (combo_df[combo_df["level"] == "15m_plus_1hr"]
                  [["combo", "n", "win_rate"]]
                  .rename(columns={"win_rate": "wr_enh", "n": "n_enh"}))
        cmp = (base_d.merge(enh_d, on="combo")
               .query("wr_base == wr_base and wr_enh == wr_enh")
               .assign(wr_gain=lambda d: d["wr_enh"] - d["wr_base"])
               .query(f"n_enh >= {MIN_SIGNALS}")
               .sort_values("wr_enh", ascending=False))

        print(f"\n  {'RANK':<4} {'BASE':>6} {'→ +1HR':>8} {'GAIN':>7} {'N_BASE':>7} {'N_ENH':>6}  COMBO")
        print(f"  {'-' * 90}")
        for rank, (_, row) in enumerate(cmp.head(20).iterrows(), 1):
            gain_s = f"+{row['wr_gain']:.1%}" if row["wr_gain"] >= 0 else f"{row['wr_gain']:.1%}"
            star   = " ★" if row["wr_enh"] >= 0.85 else ""
            print(f"  {rank:<4} {row['wr_base']:.1%}  →  {row['wr_enh']:.1%}  {gain_s:>7}  "
                  f"{int(row['n_base']):>6}  {int(row['n_enh']):>6}  {row['combo']}{star}")

    return per_strat_df, combo_df


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Print rules reminder — each stock/TF needs its own fresh analysis
    print_rules()

    print("Loading RELIANCE data for all timeframes...")
    datasets = load_symbol_timeframes(DEFAULT_RELIANCE_ROOT, symbol="RELIANCE")
    print(f"  Available TFs: {sorted(datasets.keys())}")
    print(f"  Reports will be saved to: {REPORT_DIR}\n")

    # Phase 1
    tf_summary_df, best_per_tf = phase1_per_tf_scan(datasets)

    # Phase 2
    per_strat_df, combo_df = phase2_multi_tf_confluence(datasets)

    # ── Full summary JSON ────────────────────────────────────────────────────
    summary: dict = {
        "lookahead_bars": LOOKAHEAD,
        "min_signals":    MIN_SIGNALS,
        "phase1_best_per_tf": best_per_tf,
        "phase2_primary_tf":  PRIMARY_TF,
        "phase2_confirm_tfs": CONFIRM_TFS,
    }

    # Best combo across all TFs (Phase 1)
    if not tf_summary_df.empty:
        b = tf_summary_df.iloc[0]
        summary["phase1_overall_best"] = {
            "tf":        b["tf"],
            "combo":     b["best_combo"],
            "win_rate":  b["win_rate"],
            "n_signals": int(b["n_signals"]),
        }

    # Best per-strategy with cross-TF confirmation (Phase 2)
    if not per_strat_df.empty:
        best_confirmed = (
            per_strat_df[per_strat_df["n"] >= MIN_SIGNALS]
            .sort_values("win_rate", ascending=False)
            .head(5)
            .to_dict(orient="records")
        )
        summary["phase2_best_strategy_confirmed"] = best_confirmed

    # Best combo with 1hr confirmation (Phase 2)
    if not combo_df.empty:
        enh = (combo_df[(combo_df["level"] == "15m_plus_1hr") &
                        (combo_df["n"] >= MIN_SIGNALS)]
               .sort_values("win_rate", ascending=False))
        if not enh.empty:
            b2 = enh.iloc[0]
            summary["phase2_best_combo_with_1hr"] = {
                "combo":     b2["combo"],
                "n":         int(b2["n"]),
                "win_rate":  b2["win_rate"],
                "long_wr":   b2["long_wr"],
                "short_wr":  b2["short_wr"],
            }

    with open(REPORT_DIR / "full_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    # ── Final printout ───────────────────────────────────────────────────────
    print(f"\n\n{'#' * 80}")
    print("# FINAL SUMMARY")
    print(f"{'#' * 80}")

    if "phase1_overall_best" in summary:
        b = summary["phase1_overall_best"]
        print(f"\nBest overall (Phase 1 — any TF):")
        print(f"  TF={b['tf']}  WR={b['win_rate']:.1%}  signals={b['n_signals']}")
        print(f"  Combo: {b['combo']}")

    if "phase2_best_combo_with_1hr" in summary:
        b = summary["phase2_best_combo_with_1hr"]
        print(f"\nBest combo with 1hr cross-TF confirmation (Phase 2):")
        print(f"  WR={b['win_rate']:.1%}  N={b['n']}  "
              f"Long={b['long_wr']:.1%}  Short={b['short_wr']:.1%}")
        print(f"  Combo: {b['combo']}")

    print(f"\nAll reports saved to: {REPORT_DIR}")
    print(f"  tf_scan_summary.csv")
    print(f"  {{tf}}_top20.csv  (one file per TF)")
    print(f"  per_strategy_confirmation.csv")
    print(f"  combo_confirmation.csv")
    print(f"  full_summary.json")


if __name__ == "__main__":
    main()
