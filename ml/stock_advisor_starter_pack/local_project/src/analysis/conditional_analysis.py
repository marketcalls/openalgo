"""
conditional_analysis.py
========================
Produces conditional win-rate tables for strategy screening.

Inputs
------
candidate_frame : pd.DataFrame
    Output of ``build_swing_training_artifacts`` after ``build_setup_labels``.
    Required columns: strategy_name, signal, usable_signal, setup_success,
                      setup_forward_pnl, close.

regime_series : pd.Series (optional)
    Maps integer bar-index → regime label ("bull" / "bear" / "flat").
    If None the analysis still runs; regime columns are filled with "unknown".

Output tables (returned as a dict of DataFrames)
-------------------------------------------------
1. ``strategy``             — per-strategy: signals, win%, loss%, long%, short%
2. ``strategy_direction``   — per-strategy × direction (LONG / SHORT)
3. ``strategy_regime``      — per-strategy × regime (bull / bear / flat)
4. ``strategy_regime_dir``  — per-strategy × regime × direction (full 3-way)

Usage
-----
    from analysis.conditional_analysis import build_conditional_tables
    from analysis.conditional_analysis import print_tables, save_tables

    tables = build_conditional_tables(candidate_frame, regime_series=regime_s)
    print_tables(tables)
    save_tables(tables, output_dir=Path("artifacts_template/reports/conditional"))
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _direction_label(signal: pd.Series) -> pd.Series:
    return signal.map(lambda v: "LONG" if v > 0 else "SHORT")


def _win_loss_block(grp: pd.DataFrame) -> pd.Series:
    """Aggregate one group into win-rate metrics."""
    n = len(grp)
    wins = int(grp["setup_success"].sum())
    long_mask  = grp["direction"] == "LONG"
    short_mask = grp["direction"] == "SHORT"
    n_long  = int(long_mask.sum())
    n_short = int(short_mask.sum())
    long_wins  = int(grp.loc[long_mask,  "setup_success"].sum()) if n_long  else 0
    short_wins = int(grp.loc[short_mask, "setup_success"].sum()) if n_short else 0
    avg_pnl = float(grp["setup_forward_pnl"].mean()) if "setup_forward_pnl" in grp.columns else float("nan")
    return pd.Series(
        {
            "signals":      n,
            "wins":         wins,
            "losses":       n - wins,
            "win_pct":      round(wins / n * 100, 1) if n else float("nan"),
            "loss_pct":     round((n - wins) / n * 100, 1) if n else float("nan"),
            "long_signals": n_long,
            "long_win_pct": round(long_wins / n_long * 100, 1) if n_long else float("nan"),
            "short_signals": n_short,
            "short_win_pct": round(short_wins / n_short * 100, 1) if n_short else float("nan"),
            "avg_pnl_pct":  round(avg_pnl * 100, 4),
        }
    )


def _direction_block(grp: pd.DataFrame) -> pd.Series:
    """Aggregate one (strategy, direction) group."""
    n = len(grp)
    wins = int(grp["setup_success"].sum())
    avg_pnl = float(grp["setup_forward_pnl"].mean()) if "setup_forward_pnl" in grp.columns else float("nan")
    return pd.Series(
        {
            "signals":     n,
            "wins":        wins,
            "losses":      n - wins,
            "win_pct":     round(wins / n * 100, 1) if n else float("nan"),
            "loss_pct":    round((n - wins) / n * 100, 1) if n else float("nan"),
            "avg_pnl_pct": round(avg_pnl * 100, 4),
        }
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_conditional_tables(
    candidate_frame: pd.DataFrame,
    regime_series: Optional[pd.Series] = None,
    min_signals: int = 3,
) -> dict[str, pd.DataFrame]:
    """
    Build win-rate breakdown tables from a labeled candidate frame.

    Parameters
    ----------
    candidate_frame:
        Must contain: strategy_name, signal, usable_signal, setup_success.
        Optional but recommended: setup_forward_pnl.
    regime_series:
        pd.Series indexed by integer bar position → "bull" / "bear" / "flat".
        If None, regime column is set to "unknown" for all rows.
    min_signals:
        Groups with fewer than this many signals are dropped from output tables.

    Returns
    -------
    dict with keys: "strategy", "strategy_direction",
                    "strategy_regime", "strategy_regime_dir"
    """
    # ── 1. Filter to actual trade signals ───────────────────────────────────
    df = candidate_frame.copy()
    if "usable_signal" in df.columns:
        df = df[df["usable_signal"] != 0].copy()
    else:
        df = df[df["signal"] != 0].copy()

    if df.empty:
        empty = pd.DataFrame()
        return {k: empty for k in ("strategy", "strategy_direction",
                                   "strategy_regime", "strategy_regime_dir")}

    # ── 2. Derived columns ───────────────────────────────────────────────────
    df["direction"] = _direction_label(df["signal"])

    # Attach regime label
    if regime_series is not None:
        df["regime"] = df.index.map(
            lambda i: regime_series.iloc[i] if i < len(regime_series) else "unknown"
        )
    else:
        df["regime"] = "unknown"

    # Ensure setup_forward_pnl exists
    if "setup_forward_pnl" not in df.columns:
        df["setup_forward_pnl"] = float("nan")

    # ── 3. Table 1: per-strategy ─────────────────────────────────────────────
    t_strategy = (
        df.groupby("strategy_name")
        .apply(_win_loss_block, include_groups=False)
        .reset_index()
        .rename(columns={"strategy_name": "strategy"})
        .sort_values("win_pct", ascending=False)
    )
    t_strategy = t_strategy[t_strategy["signals"] >= min_signals]

    # ── 4. Table 2: per-strategy × direction ────────────────────────────────
    t_dir = (
        df.groupby(["strategy_name", "direction"])
        .apply(_direction_block, include_groups=False)
        .reset_index()
        .rename(columns={"strategy_name": "strategy"})
        .sort_values(["strategy", "direction"])
    )
    t_dir = t_dir[t_dir["signals"] >= min_signals]

    # ── 5. Table 3: per-strategy × regime ───────────────────────────────────
    t_regime = (
        df.groupby(["strategy_name", "regime"])
        .apply(_direction_block, include_groups=False)
        .reset_index()
        .rename(columns={"strategy_name": "strategy"})
        .sort_values(["strategy", "regime"])
    )
    t_regime = t_regime[t_regime["signals"] >= min_signals]

    # ── 6. Table 4: per-strategy × regime × direction (3-way) ───────────────
    t_full = (
        df.groupby(["strategy_name", "regime", "direction"])
        .apply(_direction_block, include_groups=False)
        .reset_index()
        .rename(columns={"strategy_name": "strategy"})
        .sort_values(["strategy", "regime", "direction"])
    )
    t_full = t_full[t_full["signals"] >= min_signals]

    return {
        "strategy":           t_strategy,
        "strategy_direction": t_dir,
        "strategy_regime":    t_regime,
        "strategy_regime_dir": t_full,
    }


def print_tables(tables: dict[str, pd.DataFrame]) -> None:
    """Print all conditional tables to stdout."""
    titles = {
        "strategy":            "Strategy Win Rates",
        "strategy_direction":  "Strategy × Direction",
        "strategy_regime":     "Strategy × Regime",
        "strategy_regime_dir": "Strategy × Regime × Direction (Full Conditional)",
    }
    for key, title in titles.items():
        t = tables.get(key)
        if t is None or t.empty:
            print(f"\n[{title}]  (empty)\n")
            continue
        print(f"\n{'=' * 70}")
        print(f"  {title}")
        print(f"{'=' * 70}")
        print(t.to_string(index=False))
    print()


def save_tables(
    tables: dict[str, pd.DataFrame],
    output_dir: Path,
) -> None:
    """Save each table as a CSV under output_dir."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for key, df in tables.items():
        path = output_dir / f"{key}.csv"
        df.to_csv(path, index=False)
    print(f"Conditional analysis tables saved to {output_dir}")


# ---------------------------------------------------------------------------
# CLI entry point  (quick audit from a saved candidate CSV)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from core.constants import DEFAULT_RELIANCE_ROOT, DEFAULT_STRATEGY_ROOT
    from data.load_symbol_timeframes import load_symbol_timeframes
    from features.build_swing_training_data import build_swing_training_artifacts
    from labels.build_regime_labels import build_regime_labels
    from labels.build_setup_labels import build_setup_labels
    from strategies.registry import build_strategy_registry

    print("Loading data...")
    datasets = load_symbol_timeframes(DEFAULT_RELIANCE_ROOT, symbol="RELIANCE")
    primary_tf = "15m"

    print("Building regime labels...")
    primary_df = datasets[primary_tf].frame.copy().reset_index(drop=True)
    regime_df = build_regime_labels(primary_df, lookahead_bars=5, threshold_mode="atr")
    regime_series = regime_df["regime_label"]

    print("Running strategies...")
    confirm_tfs = ["1hr", "1day"]
    _selected = {"trend_signals_tp_sl_ualgo", "sfp_candelacharts",
                 "smc_bos", "smc_fvg", "outside_reversal", "n_bar_reversal_luxalgo"}
    all_wrappers = build_strategy_registry(DEFAULT_STRATEGY_ROOT)
    wrappers = [w for w in all_wrappers.values() if w.name in _selected]
    confirmations = [datasets[tf] for tf in confirm_tfs if tf in datasets]
    artifacts = build_swing_training_artifacts(
        primary=datasets[primary_tf],
        confirmations=confirmations,
        wrappers=wrappers,
    )

    # Label setup success
    cand = artifacts.candidate_frame.copy()
    cand = build_setup_labels(cand, signal_column="usable_signal", lookahead_bars=8)

    print("Building conditional tables...")
    tables = build_conditional_tables(cand, regime_series=regime_series, min_signals=3)
    print_tables(tables)
    save_tables(
        tables,
        output_dir=Path(__file__).resolve().parents[2].parent
        / "artifacts_template" / "reports" / "conditional_analysis",
    )
