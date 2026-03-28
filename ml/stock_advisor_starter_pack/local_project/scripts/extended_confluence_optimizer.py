"""
extended_confluence_optimizer.py
=================================
Tests every combination of all qualifying strategies (existing + new) to find the
highest win rate / lowest loss rate setups on RELIANCE 15m data.

Qualifying strategies (13 total):
  Existing (with optimized params):
    trend_signals_tp_sl_ualgo, reversal_radar_v2, central_pivot_range,
    twin_range_filter, vwap_bb_super_confluence_2, bahai_reversal_points
  New (default params, passed audit):
    sfp_candelacharts, outside_reversal,
    dark_cloud_piercing_line_tradingfinder, n_bar_reversal_luxalgo
  SMC (from opensource_indicators, built 2026-03-22):
    smc_fvg (58.2% WR, 985 signals),
    smc_bos (73.8% WR, 237 signals),
    smc_ob  (95.5% WR, 22 signals)

Method:
  - For each strategy, run on RELIANCE 15m with its best-known parameters
  - Build a signal matrix: one column per strategy, value = +1 / -1 / 0
  - For every subset of 2-4 strategies: find bars where ALL agree on the same direction
  - Direction-aware win rate: signal=+1 wins if price went up in next 8 bars
  - Report: win_rate, loss_rate, n_signals, long_wr, short_wr

Usage:
    PYTHONPATH=src python scripts/extended_confluence_optimizer.py
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import pandas as pd

from core.constants import DEFAULT_RELIANCE_ROOT, DEFAULT_STRATEGY_ROOT
from data.load_symbol_timeframes import load_symbol_timeframes
from strategies.loader import extract_default_constants, load_module
from strategies.registry import ModuleStrategyWrapper
from strategies.param_space import build_param_space

LOOKAHEAD = 8
STRATEGY_ROOT = Path(DEFAULT_STRATEGY_ROOT)
REPORT_DIR = Path(__file__).resolve().parents[1].parent / "artifacts_template" / "reports" / "extended_confluence_v2"

# ── Strategy configs ────────────────────────────────────────────────────────────
STRATEGY_CONFIGS: list[dict] = [
    # Existing — optimized params from param_optimizer.py
    {
        "name": "trend_signals_tp_sl_ualgo",
        "params": {"DEFAULT_MULTIPLIER": 2.6, "DEFAULT_ATR_PERIOD": 10, "DEFAULT_CLOUD_VAL": 7, "DEFAULT_STOP_LOSS_PCT": 1.4},
    },
    {
        "name": "reversal_radar_v2",
        "params": {"DEFAULT_BLOCK_START": 16, "DEFAULT_BLOCK_END": 7},
    },
    {
        "name": "central_pivot_range",
        "params": {},
    },
    {
        "name": "twin_range_filter",
        "params": {"DEFAULT_PER1": 27, "DEFAULT_MULT1": 1.28, "DEFAULT_PER2": 55, "DEFAULT_MULT2": 1.6},
    },
    {
        "name": "vwap_bb_super_confluence_2",
        "params": {"bb_len1": 30, "require_double_touch": False},
    },
    {
        "name": "bahai_reversal_points",
        "params": {"DEFAULT_LENGTH": 25, "DEFAULT_LOOKBACK_LENGTH": 6},
    },
    # New — default params (not yet optimized)
    {"name": "sfp_candelacharts",                     "params": {}},
    {"name": "outside_reversal",                       "params": {}},
    {"name": "dark_cloud_piercing_line_tradingfinder", "params": {}},
    {"name": "n_bar_reversal_luxalgo",                 "params": {}},
    # SMC (Smart Money Concepts) — from opensource_indicators/smart-money-concepts
    # Standalone win rates: smc_bos=73.8%, smc_fvg=58.2%, smc_ob=95.5%(22 signals)
    {"name": "smc_fvg",  "params": {}},
    {"name": "smc_bos",  "params": {}},
    {"name": "smc_ob",   "params": {}},
]


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


def _run_strategy(wrapper: ModuleStrategyWrapper, frame: pd.DataFrame, params: dict) -> pd.Series:
    try:
        result = wrapper.run(frame, params=params or None)
        return result.signal.reset_index(drop=True)
    except Exception as exc:
        print(f"    [WARN] {wrapper.name} failed: {exc}")
        return pd.Series(0, index=range(len(frame)), dtype=int)


def _direction_aware_metrics(
    signals: pd.Series, forward_dir: pd.Series
) -> tuple[int, int, float, float, float, float]:
    """Return (n_long, n_short, win_rate, loss_rate, long_wr, short_wr)."""
    long_mask  = signals == 1
    short_mask = signals == -1
    n_long  = int(long_mask.sum())
    n_short = int(short_mask.sum())
    n_total = n_long + n_short
    if n_total == 0:
        return 0, 0, float("nan"), float("nan"), float("nan"), float("nan")

    long_win  = float(((forward_dir[long_mask])  > 0).mean()) if n_long  > 0 else float("nan")
    short_win = float(((forward_dir[short_mask]) < 0).mean()) if n_short > 0 else float("nan")

    wins = (
        ((forward_dir[long_mask])  > 0).sum() +
        ((forward_dir[short_mask]) < 0).sum()
    )
    win_rate  = float(wins) / n_total
    loss_rate = 1.0 - win_rate
    return n_long, n_short, win_rate, loss_rate, long_win, short_win


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading RELIANCE 15m data...")
    datasets = load_symbol_timeframes(DEFAULT_RELIANCE_ROOT, symbol="RELIANCE")
    pf = datasets["15m"].frame.reset_index(drop=True)
    forward_return = (pf["close"].shift(-LOOKAHEAD) / pf["close"] - 1.0).reset_index(drop=True)
    forward_dir = forward_return.apply(lambda v: 1 if v > 0 else (-1 if v < 0 else 0))
    print(f"  {len(pf)} bars  |  lookahead={LOOKAHEAD} bars\n")

    # Build signal matrix
    print("Running strategies...")
    signal_matrix: dict[str, pd.Series] = {}
    for cfg in STRATEGY_CONFIGS:
        name = cfg["name"]
        print(f"  {name}...", end=" ", flush=True)
        wrapper = _build_wrapper(cfg)
        sig = _run_strategy(wrapper, pf, cfg["params"])
        signal_matrix[name] = sig
        n = int((sig != 0).sum())
        long_n = int((sig == 1).sum())
        short_n = int((sig == -1).sum())
        if n > 0:
            nl, ns, wr, lr, lw, sw = _direction_aware_metrics(sig, forward_dir)
            print(f"signals={n} (long={long_n}, short={short_n})  wr={wr:.1%}")
        else:
            print("0 signals")

    strategy_names = list(signal_matrix.keys())
    print(f"\nSignal matrix built for {len(strategy_names)} strategies.")

    # Enumerate combinations (size 1 to 4)
    print("\nTesting all combinations (size 1–4)...")
    rows: list[dict] = []

    for size in range(1, 5):
        for combo in itertools.combinations(strategy_names, size):
            # Aggregate signals: only bars where ALL strategies in combo agree on same nonzero direction
            sig_stack = pd.concat([signal_matrix[s] for s in combo], axis=1)
            sig_stack.columns = list(combo)

            # Consensus: all nonzero AND all same sign
            nonzero_mask = (sig_stack != 0).all(axis=1)
            same_sign_mask = (sig_stack.gt(0).all(axis=1) | sig_stack.lt(0).all(axis=1))
            active = nonzero_mask & same_sign_mask

            if active.sum() == 0:
                continue

            consensus_signal = sig_stack[active].mean(axis=1).apply(
                lambda v: 1 if v > 0 else -1
            )
            full_signal = pd.Series(0, index=sig_stack.index, dtype=int)
            full_signal[active] = consensus_signal

            nl, ns, wr, lr, lw, sw = _direction_aware_metrics(full_signal, forward_dir)
            n_total = nl + ns
            rows.append({
                "combo": " + ".join(combo),
                "n_strategies": size,
                "n_signals": n_total,
                "n_long": nl,
                "n_short": ns,
                "win_rate": round(wr, 4),
                "loss_rate": round(lr, 4),
                "long_win_rate": round(lw, 4) if lw == lw else None,
                "short_win_rate": round(sw, 4) if sw == sw else None,
            })

    df = pd.DataFrame(rows).sort_values("win_rate", ascending=False).reset_index(drop=True)

    # Save full results
    all_path = REPORT_DIR / "all_combos_extended.csv"
    df.to_csv(all_path, index=False)

    # Save top 30 (min 5 signals)
    top = df[df["n_signals"] >= 5].head(30)
    top_path = REPORT_DIR / "top30_combos_extended.csv"
    top.to_csv(top_path, index=False)

    print(f"\nTotal combinations tested: {len(df)}")
    print(f"Reports saved to {REPORT_DIR}\n")

    # Print top 20 with >= 5 signals
    print("=" * 100)
    print(f"{'RANK':<5} {'WIN%':>5} {'LOSS%':>6} {'N':>5} {'LONG%':>6} {'SHORT%':>6}  COMBO")
    print("=" * 100)
    for rank, (_, row) in enumerate(top.iterrows(), 1):
        lw = f"{row['long_win_rate']:.1%}" if row["long_win_rate"] else "  —"
        sw = f"{row['short_win_rate']:.1%}" if row["short_win_rate"] else "  —"
        print(
            f"{rank:<5} {row['win_rate']:.1%}  {row['loss_rate']:.1%}  "
            f"{int(row['n_signals']):>5}  {lw:>6}  {sw:>6}  {row['combo']}"
        )

    # Best per filter size
    print("\n--- Best combo per number of strategies agreeing ---")
    for size in range(1, 5):
        sub = df[(df["n_strategies"] == size) & (df["n_signals"] >= 5)]
        if sub.empty:
            continue
        best = sub.iloc[0]
        print(f"  {size} strategy combo:  {best['win_rate']:.1%} win  |  "
              f"{int(best['n_signals'])} signals  |  {best['combo']}")

    # Save best combo config JSON
    if not top.empty:
        best = top.iloc[0]
        import json
        best_config = {
            "best_combo": best["combo"].split(" + "),
            "win_rate": best["win_rate"],
            "loss_rate": best["loss_rate"],
            "n_signals": int(best["n_signals"]),
            "n_long": int(best["n_long"]),
            "n_short": int(best["n_short"]),
            "long_win_rate": best["long_win_rate"],
            "short_win_rate": best["short_win_rate"],
        }
        with open(REPORT_DIR / "best_combo_extended.json", "w") as f:
            json.dump(best_config, f, indent=2)
        print(f"\nBest combo config saved to {REPORT_DIR / 'best_combo_extended.json'}")


if __name__ == "__main__":
    main()
